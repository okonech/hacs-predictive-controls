from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.count import (
    DIAGNOSTIC_LIMIT,
    CountConflictTracker,
    CountContext,
    CountInput,
    CountState,
    apply_count_update,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import (
    ZoneBeliefFilter,
)
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountSupport,
    EpisodeEffect,
    SensorInput,
)
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
)
from tests.endpoint_count_fixture import (
    advance_count_components,
    observe_count_control,
    observe_count_sensor,
)
from tests.handoff_lifecycle_fixture import component_arrival
from tests.persistence_component_fixture import PersistenceComponents
from tests.runtime_replay import RuntimeScenario
from tests.test_zone_model_engine import stale_transfer_map

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def test_count_conflict_support_projection_is_canonical() -> None:
    tracker = CountConflictTracker()
    support = CountSupport("support:one", "one", "one", ("one",))
    with pytest.raises(ValueError, match="unique and sorted"):
        tracker.evaluate(NOW, 1, (), (), (support, support), {})

    tracker.evaluate(NOW, 1, (), (), (support,), {})
    assert tracker.support_ids_outside("other", "other") == ("support:one",)
    assert tracker.support_ids_outside("one", "other") == ()
    assert tracker.support_ids_outside("other", "one") == ()


def test_count_validation_preserves_last_valid_value() -> None:
    context = CountContext(0)
    accepted = context.observe(CountInput("one", 1, True, NOW))
    duplicate = context.observe(CountInput("one", 1, True, NOW))
    stale = context.observe(CountInput("stale", 0, True, NOW - timedelta(seconds=1)))
    invalid = context.observe(
        CountInput("invalid", 3, True, NOW + timedelta(seconds=1))
    )
    unavailable = context.observe(
        CountInput("unavailable", None, False, NOW + timedelta(seconds=2))
    )
    same_value = context.observe(
        CountInput("same-value", 1, True, NOW + timedelta(seconds=3))
    )

    assert accepted.disposition == "accepted"
    assert accepted.state.expected_count == 1
    assert accepted.state.positive_transition_at == NOW
    assert duplicate.disposition == "duplicate"
    assert stale.disposition == "stale"
    assert invalid.disposition == "invalid"
    assert unavailable.disposition == "unavailable"
    assert same_value.disposition == "duplicate"
    assert context.state.expected_count == 1
    assert context.state.diagnostics == (1, 2, 1, 1, 1)


def test_count_zero_resets_filters_and_frontier_but_positive_invents_nothing() -> None:
    context = CountContext(1)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unused": {
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.unused"},
                }
            }
        }
    )
    frontier = TraversalFrontier(predictive_map, ())
    filters = {
        "a": ZoneBeliefFilter("a", BELIEF_PROFILES["stay_pir"], NOW),
        "b": ZoneBeliefFilter("b", BELIEF_PROFILES["stay_presence"], NOW),
    }
    filters["a"].apply_positive("a-episode", NOW + timedelta(seconds=1))
    filters["b"].apply_positive("b-episode", NOW + timedelta(seconds=1))

    zero = context.observe(CountInput("zero", 0, True, NOW + timedelta(seconds=2)))
    apply_count_update(zero, filters, frontier)
    for zone, filter_ in filters.items():
        assert filter_.state.generation_episode_id is None
        profile_name = "stay_pir" if zone == "a" else "stay_presence"
        assert filter_.state.probability == pytest.approx(
            BELIEF_PROFILES[profile_name].prior_probability
        )
    assert frontier.tokens == ()

    positive = context.observe(
        CountInput("positive", 2, True, NOW + timedelta(seconds=3))
    )
    before = {zone: filter_.state for zone, filter_ in filters.items()}
    apply_count_update(positive, filters, frontier)
    assert {zone: filter_.state for zone, filter_ in filters.items()} == before
    assert frontier.tokens == ()


def test_count_diagnostics_compare_clusters_without_forcing_zones() -> None:
    context = CountContext(2)
    diagnostics = context.diagnostics(evidence_cluster_count=1)
    assert diagnostics.expected_count == 2
    assert diagnostics.evidence_cluster_count == 1
    assert diagnostics.cluster_delta == -1


@pytest.mark.parametrize("initial_count", [True, 1.5, -1, 3])
def test_count_context_rejects_invalid_initial_count(initial_count: object) -> None:
    with pytest.raises(ValueError):
        CountContext(initial_count)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "event",
    [
        CountInput("none", None, True, NOW),
        CountInput("bool", True, True, NOW),
    ],
)
def test_count_context_rejects_non_integer_values(event: CountInput) -> None:
    assert CountContext(0).observe(event).disposition == "invalid"


def test_count_state_and_input_validate_direct_construction() -> None:
    with pytest.raises(ValueError):
        CountInput("", 0, True, NOW)
    with pytest.raises(ValueError):
        CountInput("event", 0, 1, NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CountInput("event", 0, True, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        CountState(3)
    with pytest.raises(ValueError):
        CountState(1, positive_transition_at=NOW)
    with pytest.raises(ValueError):
        CountState(
            1,
            positive_transition_at=NOW,
            positive_transition_until=NOW,
        )
    with pytest.raises(ValueError):
        CountState(1, seen_event_ids=("same", "same"))
    with pytest.raises(ValueError):
        CountState(1, seen_event_ids=("",))
    with pytest.raises(ValueError):
        CountState(1, diagnostics=(0, 0, 0, 0))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CountState(1, diagnostics=(0, 0, 0, 0, -1))


def test_count_diagnostics_are_bounded_and_validate_cluster_count() -> None:
    assert CountContext._increment((DIAGNOSTIC_LIMIT, 0, 0, 0, 0), 0)[0] == (
        DIAGNOSTIC_LIMIT
    )
    with pytest.raises(ValueError):
        CountContext(0).diagnostics(-1)


def test_count_seen_event_ids_are_bounded() -> None:
    context = CountContext(0)
    for index in range(40):
        context.observe(CountInput(f"event-{index}", None, False, NOW))
    assert len(context.state.seen_event_ids) == 32
    assert context.state.seen_event_ids[0] == "event-8"


def test_count_seen_event_bound_retains_latest_accepted_id() -> None:
    context = CountContext(1)
    context.observe(CountInput("accepted", 2, True, NOW))
    for index in range(32):
        context.observe(
            CountInput(f"unavailable-{index}", None, False, NOW)
        )

    assert len(context.state.seen_event_ids) == 32
    assert context.state.last_event_id == "accepted"
    assert "accepted" in context.state.seen_event_ids


def test_count_zero_rejects_stale_filter_or_frontier_atomically() -> None:
    context = CountContext(1)
    zero = context.observe(CountInput("zero", 0, True, NOW))
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unused": {
                    "entities": {"motion": "binary_sensor.unused"},
                }
            }
        }
    )
    frontier = TraversalFrontier(predictive_map, ())
    future_filter = ZoneBeliefFilter(
        "future", BELIEF_PROFILES["stay_pir"], NOW + timedelta(seconds=1)
    )
    before = future_filter.state
    with pytest.raises(ValueError, match="predates a zone belief"):
        apply_count_update(zero, {"future": future_filter}, frontier)
    assert future_filter.state == before

    frontier.advance(NOW + timedelta(seconds=1))
    current_filter = ZoneBeliefFilter("current", BELIEF_PROFILES["stay_pir"], NOW)
    with pytest.raises(ValueError, match="cannot move backward"):
        apply_count_update(zero, {"current": current_filter}, frontier)
    assert current_filter.state.last_updated_at == NOW


def conflict_map(
    *,
    extend_a: bool = False,
    target_presence: bool = False,
    target_reliability: float = 1.0,
) -> PredictiveMap:
    target_signal = "mmwave" if target_presence else "motion"
    nodes: dict[str, object] = {
        "target_source": {
            "zone": "target_source",
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.target_source"},
            "adjacent": ["target"],
        },
        "target": {
            "zone": "target",
            "entities": {target_signal: "binary_sensor.target"},
            "adjacent": ["target_source"],
            "initial_weight": target_reliability,
        },
    }
    for prefix in ("a", "d"):
        first, middle, stay = prefix, f"{prefix}m", f"{prefix}s"
        nodes[first] = {
            "zone": first,
            "entities": {"motion": f"binary_sensor.{first}"},
            "adjacent": [middle],
        }
        nodes[middle] = {
            "zone": middle,
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": f"binary_sensor.{middle}"},
            "adjacent": [first, stay],
        }
        stay_adjacent = [middle]
        if extend_a and prefix == "a":
            stay_adjacent.append("ax")
        nodes[stay] = {
            "zone": stay,
            "entities": {"motion": f"binary_sensor.{stay}"},
            "adjacent": stay_adjacent,
        }
    if extend_a:
        nodes["ax"] = {
            "zone": "ax",
            "entities": {"motion": "binary_sensor.ax"},
            "adjacent": ["as"],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


def observe_on(engine: ZoneModelEngine, node_id: str, seconds: float) -> None:
    engine.observe(
        SensorInput(
            f"binary_sensor.{node_id}",
            "on",
            NOW + timedelta(seconds=seconds),
        )
    )


def engine_with_two_front_conflict(*, extend_a: bool = False) -> ZoneModelEngine:
    engine = ZoneModelEngine(conflict_map(extend_a=extend_a), 2, NOW)
    observe_on(engine, "target_source", 0)
    observe_on(engine, "target", 1)
    for node_id, seconds in (
        ("a", 2),
        ("am", 3),
        ("as", 4),
        ("d", 5),
        ("dm", 6),
        ("ds", 7),
    ):
        observe_on(engine, node_id, seconds)
    return engine


def observe_component_on(
    engine: PersistenceComponents, node_id: str, seconds: float,
) -> None:
    observe_count_sensor(
        engine,
        SensorInput(
            f"binary_sensor.{node_id}",
            "on",
            NOW + timedelta(seconds=seconds),
        )
    )


def components_with_two_front_conflict(
    *, extend_a: bool = False,
) -> PersistenceComponents:
    """Original COUNT-009 inputs at their isolated component boundary.

    HEALTH-003 prohibits this degradation in the selected engine; separate runtime
    tests below preserve that distinction rather than testing empty support sets.
    """
    engine = PersistenceComponents(conflict_map(extend_a=extend_a), 2, NOW)
    observe_component_on(engine, "target_source", 0)
    observe_component_on(engine, "target", 1)
    for node_id, seconds in (
        ("a", 2),
        ("am", 3),
        ("as", 4),
        ("d", 5),
        ("dm", 6),
        ("ds", 7),
    ):
        observe_component_on(engine, node_id, seconds)
    return engine


def test_two_settled_supports_degrade_stuck_assertion_only_after_full_dwell() -> None:
    engine = components_with_two_front_conflict()
    assert engine.diagnostic_counters["count_conflict_started"] == 1
    assert engine.diagnostic_counters["count_conflict_degraded"] == 0
    snapshot = engine.snapshot
    assert len(snapshot.anonymous_supports) == 2
    assert len(snapshot.count_conflicts) == 1
    conflict = snapshot.count_conflicts[0]
    assert conflict.target_node_id == "target"
    assert conflict.deadline == NOW + timedelta(seconds=67)

    before = advance_count_components(
        engine, conflict.deadline - timedelta(microseconds=1),
    )
    target_before = next(
        state for state in before.snapshot.episode_states if state.node_id == "target"
    )
    assert target_before.status == "asserted"
    assert not target_before.health_warning

    crossed = advance_count_components(engine, conflict.deadline)
    target = next(
        state for state in crossed.snapshot.episode_states if state.node_id == "target"
    )
    target_policy = next(
        state for state in crossed.snapshot.policy_states if state.zone == "target"
    )
    assert target.status == "degraded"
    assert target.degradation_reason == "count_conflict"
    assert target.health_warning
    assert target.traversal_valid_until is None
    assert target_policy.active  # Count diagnoses health; it never writes active off.
    occurrence = next(
        item
        for item in crossed.snapshot.reliability_warning_occurrences
        if item.node_id == "target" and item.reason == "count_conflict"
    )
    assert occurrence.kind == "suspected_stuck"
    assert occurrence.first_observed_at == conflict.deadline
    assert occurrence.cleared_at is None
    conflict_row = next(
        row for row in engine.audit_rows if row.reason == "stuck_count_conflict"
    )
    assert conflict_row.count_conflict_support_ids == conflict.support_ids
    assert conflict_row.reliability_result == "degraded"
    assert engine.diagnostic_counters["count_conflict_degraded"] == 1

    held = advance_count_components(engine, NOW + timedelta(minutes=10))
    target_policy = next(
        state for state in held.snapshot.policy_states if state.zone == "target"
    )
    assert target_policy.active
    assert target_policy.pending_release_since is None
    assert any(row.reason == "asserted_stay_hold" for row in engine.audit_rows)

    clear_at = NOW + timedelta(minutes=10, seconds=1)
    observe_count_sensor(engine, SensorInput("binary_sensor.target", "off", clear_at))
    stable_clear_at = clear_at + timedelta(seconds=5)
    cleared = advance_count_components(engine, stable_clear_at)
    cleared_target = next(
        state for state in cleared.snapshot.episode_states if state.node_id == "target"
    )
    cleared_belief = next(
        state for state in cleared.snapshot.belief_states if state.zone == "target"
    )
    cleared_policy = next(
        state for state in cleared.snapshot.policy_states if state.zone == "target"
    )
    assert not cleared_target.health_warning
    assert cleared_target.degradation_reason is None
    assert not cleared_belief.health_warning
    assert cleared.snapshot.count_conflicts == ()
    occurrence = next(
        item
        for item in cleared.snapshot.reliability_warning_occurrences
        if item.node_id == "target" and item.reason == "count_conflict"
    )
    assert occurrence.last_observed_at == stable_clear_at
    assert occurrence.cleared_at == stable_clear_at
    assert cleared_policy.active
    assert cleared_policy.pending_release_since == stable_clear_at

    almost = advance_count_components(
        engine, stable_clear_at + timedelta(seconds=60) - timedelta(microseconds=1),
    )
    still_held = next(s for s in almost.snapshot.policy_states if s.zone == "target")
    assert still_held.active
    assert still_held.pending_release_since == stable_clear_at
    released = advance_count_components(engine, stable_clear_at + timedelta(seconds=60))
    target_policy = next(
        state for state in released.snapshot.policy_states if state.zone == "target"
    )
    assert not target_policy.active
    assert any(
        event.zone == "target" and event.kind == "released"
        for event in released.policy_events
    )


def test_count_degraded_clear_reassertion_remains_held_and_valid() -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    advance_count_components(engine, deadline)

    observe_count_sensor(
        engine,
        SensorInput("binary_sensor.target", "off", deadline + timedelta(seconds=1))
    )
    reasserted = observe_count_sensor(
        engine,
        SensorInput("binary_sensor.target", "on", deadline + timedelta(seconds=2))
    )
    target = next(
        state
        for state in reasserted.snapshot.episode_states
        if state.node_id == "target"
    )
    target_policy = next(
        state
        for state in reasserted.snapshot.policy_states
        if state.zone == "target"
    )

    assert target.status == "degraded"
    assert target.known_on
    assert target.health_warning
    assert target.degradation_reason == "count_conflict"
    assert target.traversal_valid_until is None
    assert target.clear_started_at is None
    assert target.clear_deadline is None
    assert target_policy.active

    retained = advance_count_components(engine, deadline + timedelta(minutes=10))
    assert next(
        state for state in retained.snapshot.policy_states if state.zone == "target"
    ).active


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
def test_neutral_availability_removes_asserted_stay_hold(state: str) -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    advance_count_components(engine, deadline)
    unavailable_at = deadline + timedelta(seconds=1)

    result = observe_count_sensor(
        engine,
        SensorInput("binary_sensor.target", state, unavailable_at)
    )
    target = next(
        item for item in result.snapshot.episode_states if item.node_id == "target"
    )
    assert target.status == "unavailable"
    assert not target.health_warning
    assert target.degradation_reason is None
    assert result.snapshot.count_conflicts == ()
    occurrence = engine.warnings[("target", "count_conflict")]
    assert occurrence.cleared_at == unavailable_at
    recovery, = (row for row in engine.audit_rows
                 if row.reason == "stuck_conflict_cleared")
    assert recovery.count_conflict_support_ids
    assert recovery.reliability_result == "recovered"

    released = advance_count_components(engine, unavailable_at + timedelta(minutes=30))
    target_policy = next(
        item for item in released.snapshot.policy_states if item.zone == "target"
    )
    assert not target_policy.active
    assert any(event.kind == "released" for event in released.policy_events)


def test_count_zero_bypasses_asserted_stay_hold() -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    advance_count_components(engine, deadline)

    result = observe_count_control(
        engine,
        CountInput("count-zero", 0, True, deadline + timedelta(seconds=1))
    )

    assert not next(
        state for state in result.snapshot.policy_states if state.zone == "target"
    ).active
    assert any(
        event.zone == "target"
        and event.kind == "released"
        and event.policy_reason == "count_zero"
        for event in result.policy_events
    )


def test_count_zero_resets_cadence_without_a_synthetic_sensor_edge() -> None:
    engine = ZoneModelEngine(conflict_map(target_presence=True), 1, NOW)
    engine.observe(SensorInput("binary_sensor.target", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.target", "off", NOW + timedelta(seconds=20))
    )
    engine.advance(NOW + timedelta(seconds=30))
    engine.observe(
        SensorInput("binary_sensor.target", "on", NOW + timedelta(seconds=60))
    )

    before = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert before.cadence_correlated
    generation = before.generation

    engine.observe_count(CountInput("zero", 0, True, NOW + timedelta(seconds=61)))

    after = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert after.generation == generation
    assert after.cadence_run_started_at is None
    assert after.cadence_last_transition_at is None
    assert after.cadence_cycle_count == 0
    assert not after.cadence_correlated
    assert not after.cadence_warning


def test_count_zero_clears_active_cadence_warning_occurrence() -> None:
    # Legacy cadence occurrence lifecycle, not current HEALTH-002 thresholds.
    engine = PersistenceComponents(conflict_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.target", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.target", "off", NOW + timedelta(seconds=10))
    )
    engine.observe(
        SensorInput("binary_sensor.target", "on", NOW + timedelta(seconds=12))
    )

    result = engine.observe_count(
        CountInput("zero", 0, True, NOW + timedelta(seconds=13))
    )

    occurrence = result.snapshot.reliability_warning_occurrences[0]
    assert occurrence.reason == "impossible_cadence"
    assert occurrence.cleared_at == NOW + timedelta(seconds=13)


def test_warning_clear_requires_one_active_occurrence() -> None:
    engine = ZoneModelEngine(conflict_map(), 1, NOW)
    warning = EpisodeEffect(
        "target",
        "target",
        "target:1",
        "impossible_cadence",
        NOW,
        warning_reason="impossible_cadence",
    )
    cleared = replace(
        warning,
        kind="cadence_warning_cleared",
        at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="no active occurrence"):
        engine._apply_warning_effect(cleared)  # noqa: SLF001
    engine._apply_warning_effect(warning)  # noqa: SLF001
    engine._apply_warning_effect(cleared)  # noqa: SLF001
    with pytest.raises(ValueError, match="no active occurrence"):
        engine._apply_warning_effect(cleared)  # noqa: SLF001


def test_retained_support_prevents_count_conflict_on_its_asserted_endpoint() -> None:
    # Real traversal/support transactions; a stale bridge binding is lineage,
    # never authority to move the already-retained endpoint (COUNT-011).
    engine = PersistenceComponents(stale_transfer_map(), 2, NOW)
    for node_id, seconds in (
        ("independent_entry", 0.1), ("independent_transition", 0.2),
        ("independent_stay", 0.3), ("source", 1), ("bridge", 2), ("retained", 3),
    ):
        component_arrival(engine, SensorInput(
            f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
        ))
    retained = next(s for s in engine.supports.supports if s.current_zone == "retained")

    arrival = component_arrival(
        engine,
        SensorInput("binary_sensor.second", "on", NOW + timedelta(seconds=4))
    )
    assert arrival.authorizations[0].authorized
    advance_count_components(engine, NOW + timedelta(seconds=5))
    assert next(
        s for s in engine.supports.supports if s.support_id == retained.support_id
    ) == retained

    assert {support.current_zone for support in engine.snapshot.anonymous_supports} == {
        "independent_stay",
        "retained",
    }
    assert not any(
        conflict.target_node_id == "retained"
        for conflict in engine.snapshot.count_conflicts
    )
    assert any(
        conflict.target_node_id == "second"
        for conflict in engine.snapshot.count_conflicts
    )


def test_external_clear_at_conflict_deadline_cannot_prevent_health_diagnosis() -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline

    observe_count_sensor(engine, SensorInput("binary_sensor.target", "off", deadline))

    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.status == "clearing"
    assert target.health_warning
    assert target.degradation_reason == "count_conflict"


def test_provisional_or_insufficient_supports_cannot_start_count_conflict() -> None:
    engine = PersistenceComponents(conflict_map(), 2, NOW)
    observe_component_on(engine, "target_source", 0)
    observe_component_on(engine, "target", 1)
    observe_component_on(engine, "a", 2)
    observe_component_on(engine, "am", 3)
    observe_component_on(engine, "d", 4)
    observe_component_on(engine, "dm", 5)

    tokens = engine.snapshot.traversal_tokens
    assert {token.node_id for token in tokens} == {
        "target_source", "target", "a", "am", "d", "dm",
    }
    assert all(token.track_confidence == "provisional" for token in tokens)
    assert all(not token.equivalent_confirmed_strength for token in tokens)
    assert engine.snapshot.anonymous_supports == ()
    assert engine.snapshot.count_conflicts == ()
    advance_count_components(engine, NOW + timedelta(minutes=5))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.degradation_reason is None


def test_provisional_high_belief_stay_episode_cannot_create_support() -> None:
    engine = PersistenceComponents(conflict_map(), 2, NOW)
    observe_component_on(engine, "target_source", 0)
    observe_component_on(engine, "target", 1)

    target_belief = next(
        state for state in engine.snapshot.belief_states if state.zone == "target"
    )
    assert target_belief.probability >= 0.7
    token = next(t for t in engine.snapshot.traversal_tokens if t.node_id == "target")
    assert token.node_id == "target"
    assert token.track_confidence == "provisional"
    assert not token.equivalent_confirmed_strength
    assert engine.snapshot.anonymous_supports == ()


def test_settled_supports_survive_traversal_token_expiry() -> None:
    engine = components_with_two_front_conflict()
    initial = engine.snapshot.anonymous_supports
    assert {support.current_zone for support in initial} == {"as", "ds"}

    expired = advance_count_components(engine, NOW + timedelta(seconds=100)).snapshot

    assert expired.traversal_tokens == ()
    assert expired.anonymous_supports == initial


def test_outward_movement_moves_support_and_return_settles_it() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["source", "room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )
    engine = PersistenceComponents(predictive_map, 1, NOW)
    observe_component_on(engine, "source", 0)
    observe_component_on(engine, "hall", 1)
    observe_component_on(engine, "room", 2)
    original = engine.snapshot.anonymous_supports[0]

    origin = next(t for t in engine.frontier.tokens if t.node_id == "source")
    assert origin.token_id not in engine.frontier.current_token_ids
    observe_count_sensor(
        engine, SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3)),
    )
    observe_component_on(engine, "hall", 20)
    assert origin.token_id not in engine.frontier.current_token_ids
    moving = engine.snapshot.anonymous_supports[0]
    assert moving.support_id == original.support_id
    assert moving.state == "moving"
    assert moving.current_zone == "hall"

    observe_count_sensor(
        engine,
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=21))
    )
    advance_count_components(engine, NOW + timedelta(seconds=31))
    observe_component_on(engine, "room", 32)
    restored = engine.snapshot.anonymous_supports[0]
    assert restored.support_id == original.support_id
    assert restored.state == "settled"
    assert restored.current_zone == "room"


def test_count_conflict_restore_rejects_duplicate_targets() -> None:
    snapshot = components_with_two_front_conflict().snapshot
    conflict = snapshot.count_conflicts[0]
    tracker = CountConflictTracker()

    tracker.restore((conflict,), 2)
    before = tracker.conflicts
    with pytest.raises(ValueError, match="targets must be unique"):
        tracker.restore((conflict, conflict), 2)
    assert tracker.conflicts == before


def test_restored_degraded_conflict_handles_matching_and_replaced_episode() -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    advance_count_components(engine, deadline)
    snapshot = engine.snapshot
    conflict = snapshot.count_conflicts[0]
    target = next(
        state for state in snapshot.episode_states if state.node_id == "target"
    )
    asserted = replace(
        target,
        status="asserted",
        degraded_at=None,
        degradation_reason=None,
        health_warning=False,
    )
    release_dwells = {
        belief.zone: timedelta(seconds=60) for belief in snapshot.belief_states
    }
    supports = tuple(
        CountSupport(
            support.support_id,
            support.current_node_id,
            support.current_zone,
            support.path_node_ids,
        )
        for support in snapshot.anonymous_supports
    )

    matching = CountConflictTracker()
    matching.restore((conflict,), 2)
    matching.evaluate(
        deadline + timedelta(microseconds=1),
        2,
        engine.nodes,
        tuple(
            asserted if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        supports,
        release_dwells,
    )
    assert matching.conflicts[0].target_episode_id == asserted.episode_id
    restarted_at = deadline + timedelta(microseconds=1)
    assert matching.conflicts[0].started_at == restarted_at
    assert matching.conflicts[0].deadline == restarted_at + timedelta(seconds=60)
    assert matching.conflicts[0].degraded_at is None
    assert matching.conflicts[0].support_ids == conflict.support_ids

    replaced_episode = replace(asserted, episode_id="replacement")
    replaced_tracker = CountConflictTracker()
    replaced_tracker.restore((conflict,), 2)
    replaced_tracker.evaluate(
        deadline + timedelta(microseconds=1),
        2,
        engine.nodes,
        tuple(
            replaced_episode if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        supports,
        release_dwells,
    )
    assert not replaced_tracker.conflicts


def test_support_loss_resets_continuous_conflict_dwell() -> None:
    engine = components_with_two_front_conflict()
    original_deadline = engine.snapshot.count_conflicts[0].deadline
    observe_count_sensor(
        engine,
        SensorInput("binary_sensor.ds", "unavailable", NOW + timedelta(seconds=20))
    )
    assert len(engine.snapshot.anonymous_supports) == 1
    assert engine.snapshot.count_conflicts == ()

    advance_count_components(engine, original_deadline)
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert not target.health_warning


def test_support_movement_preserves_continuous_conflict_dwell() -> None:
    engine = components_with_two_front_conflict(extend_a=True)
    before = next(
        conflict
        for conflict in engine.snapshot.count_conflicts
        if conflict.target_node_id == "target"
    )
    before_support = next(
        support
        for support in engine.snapshot.anonymous_supports
        if support.current_node_id == "as"
    )

    observe_component_on(engine, "ax", 8)

    after = next(
        conflict
        for conflict in engine.snapshot.count_conflicts
        if conflict.target_node_id == "target"
    )
    after_support = next(
        support
        for support in engine.snapshot.anonymous_supports
        if support.current_node_id == "ax"
    )
    assert after_support.support_id == before_support.support_id
    assert after.started_at == before.started_at
    assert after.deadline == before.deadline
    assert after.support_ids == before.support_ids


def test_stuck_conflict_recovers_after_stable_clear_and_fresh_episode() -> None:
    engine = components_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    advance_count_components(engine, deadline)
    observe_count_sensor(
        engine,
        SensorInput("binary_sensor.target", "off", deadline + timedelta(seconds=1))
    )
    cleared = advance_count_components(engine, deadline + timedelta(seconds=6))
    cleared_target = next(
        state for state in cleared.snapshot.episode_states if state.node_id == "target"
    )
    assert not cleared_target.health_warning
    recovery_row = next(
        row for row in engine.audit_rows if row.reason == "stuck_conflict_cleared"
    )
    assert recovery_row.count_conflict_support_ids
    assert recovery_row.reliability_result == "recovered"

    observe_count_sensor(
        engine,
        SensorInput("binary_sensor.target", "on", deadline + timedelta(seconds=7))
    )

    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.status == "asserted"
    assert target.generation == 2
    assert not target.health_warning
    assert target.degradation_reason is None
    assert engine.snapshot.count_conflicts == ()


def test_count_change_cancels_unmatured_conflict_without_releasing_target() -> None:
    engine = components_with_two_front_conflict()
    observe_count_control(
        engine, CountInput("count-one", 1, True, NOW + timedelta(seconds=8)),
    )
    assert engine.snapshot.count_conflicts == ()
    assert engine.diagnostic_counters["count_conflict_started"] == 1
    assert engine.diagnostic_counters["count_conflict_canceled"] == 1
    advance_count_components(engine, NOW + timedelta(seconds=67))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    policy = next(
        state for state in engine.snapshot.policy_states if state.zone == "target"
    )
    assert not target.health_warning
    assert policy.active


@pytest.mark.parametrize("count", [1, 2])
def test_runtime_count_slots_and_conflict_inputs_do_not_degrade_health(
    count: int,
) -> None:
    """PATH-001/003/HEALTH-003: same original input, actual public consumers."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(conflict_map(), count)
        assert replay.inference_snapshot().selected_paths == (None,) * count
        for node_id, seconds in (
            ("target_source", 0), ("target", 1),
            ("a", 2), ("am", 3), ("as", 4),
            ("d", 5), ("dm", 6), ("ds", 7),
        ):
            before = replay.inference_snapshot().selected_paths
            replay.send(
                f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
            )
            snapshot = replay.inference_snapshot()
            assert len(snapshot.selected_paths) == count
            # Anonymous slots are canonicalized, not stable person-indexed IDs.
            changed = Counter(snapshot.selected_paths) - Counter(before)
            assert sum(changed.values()) <= 1
            episode = next(s for s in snapshot.episode_states if s.node_id == node_id)
            assert sum(
                path is not None and any(
                    visit.episode_id == episode.episode_id for visit in path.visits
                ) for path in snapshot.selected_paths
            ) <= 1
            if node_id == "target_source":
                assert snapshot.selected_paths == (None,) * count
                assert not replay.view().active("target_source")
            if node_id == "target":
                located = tuple(
                    path for path in snapshot.selected_paths if path is not None
                )
                assert len(located) == 1
                assert snapshot.selected_paths.count(None) == count - 1
                assert located[0].endpoint.node_id == "target"
                assert located[0].track_confidence == "provisional"
                assert replay.view().active("target")
                assert not replay.view().active("target_source")
                target = next(b for b in snapshot.belief_states if b.zone == "target")
                assert target.probability >= 0.7
        replay.advance(NOW + timedelta(seconds=67))
        snapshot = replay.inference_snapshot()
        assert snapshot.count_conflicts == ()
        assert snapshot.anonymous_supports == ()
        assert all(s.degradation_reason is None for s in snapshot.episode_states)
        assert not any(
            w.reason == "count_conflict"
            for w in snapshot.reliability_warning_occurrences
        )
        assert replay.view().active("as")
        assert replay.view().active("ds")


@pytest.mark.parametrize("count", [1, 2])
def test_runtime_physical_presence_hold_survives_diagnostic_then_count_zero(
    count: int,
) -> None:
    """PATH-005/HEALTH-003: displaced actual presence holds, warnings do not veto it."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(
            conflict_map(target_presence=True), count,
        ).watch_reliability()
        for node_id, seconds in (
            ("target_source", 0), ("target", 1),
            ("a", 2), ("am", 3), ("as", 4),
            ("d", 5), ("dm", 6), ("ds", 7),
        ):
            replay.send(
                f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
            )
        replay.advance(NOW + timedelta(seconds=630))
        snapshot = replay.inference_snapshot()
        target = next(b for b in snapshot.belief_states if b.zone == "target")
        assert target.physical_hold
        assert target.path_displaced_at is not None
        assert replay.view().active("target")
        assert all(edge.active for edge in replay.edges_for("target"))
        assert any(w.node_id == "target" and w.cleared_at is None
                   for w in snapshot.reliability_warning_occurrences)
        physical = next(s for s in snapshot.episode_states if s.node_id == "target")
        assert not physical.health_warning
        assert replay.reliability_writes
        replay.send("sensor.replay_people", "0", NOW + timedelta(seconds=631))
        assert not replay.view().active("target")
        empty = replay.inference_snapshot()
        assert empty.selected_paths == ()
        assert all(not b.physical_hold for b in empty.belief_states)
        replay.send("sensor.replay_people", str(count), NOW + timedelta(seconds=632))
        assert replay.inference_snapshot().selected_paths == (None,) * count
        assert not replay.view().active("target")


def test_current_short_cadence_count_zero_does_not_create_legacy_warning() -> None:
    """HEALTH-002: original 0/10/12/13 inputs are not six completed cycles."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(conflict_map(), 1)
        for state, seconds in (("on", 0), ("off", 10), ("on", 12)):
            replay.send("binary_sensor.target", state, NOW + timedelta(seconds=seconds))
        before = replay.inference_snapshot()
        replay.send("sensor.replay_people", "0", NOW + timedelta(seconds=13))
        after = replay.inference_snapshot()
        assert before.reliability_warning_occurrences == ()
        assert after.reliability_warning_occurrences == ()
        original = next(s for s in before.episode_states if s.node_id == "target")
        assert original.episode_id == next(
            s for s in after.episode_states if s.node_id == "target"
        ).episode_id
        assert not replay.view().active("target")


def test_degraded_component_support_loss_recovers_same_asserted_episode() -> None:
    """COUNT-009 recovery: no new sensor generation or warning fabrication."""
    components = components_with_two_front_conflict()
    conflict, = components.snapshot.count_conflicts
    advance_count_components(components, conflict.deadline)
    observe_count_sensor(components, SensorInput(
        "binary_sensor.ds", "unavailable", conflict.deadline + timedelta(seconds=1),
    ))
    state = next(s for s in components.episodes.states if s.node_id == "target")
    assert state.episode_id == conflict.target_episode_id
    assert state.status == "asserted"
    assert state.known_on and not state.health_warning
    assert components.snapshot.count_conflicts == ()
    assert components.policies["target"].state.active
    recovery, = (
        row for row in components.audit_rows if row.reason == "stuck_conflict_cleared"
    )
    assert recovery.count_conflict_support_ids == conflict.support_ids
    assert recovery.reliability_result == "recovered"
    occurrence = components.warnings[("target", "count_conflict")]
    assert occurrence.cleared_at == conflict.deadline + timedelta(seconds=1)


def test_component_count_snapshot_validator_keeps_exact_support_and_dwell_binding(
) -> None:
    """STATE-010: real cross-link validator, accepted specimen, atomic corruption."""
    components = components_with_two_front_conflict()
    snapshot = components.snapshot
    validator = SnapshotValidator(
        components.predictive_map, components.nodes,
        components.supports._confirmed_strength,  # noqa: SLF001
    )
    validator.validate_count_snapshot(snapshot)
    original = deepcopy(snapshot)
    conflict, = snapshot.count_conflicts
    for malformed in (
        replace(conflict, support_ids=(conflict.support_ids[0],)),
        replace(conflict, deadline=conflict.deadline + timedelta(microseconds=1)),
    ):
        rejected = replace(snapshot, count_conflicts=(malformed,))
        unchanged = deepcopy(rejected)
        with pytest.raises(ValueError, match="Count-conflict snapshot is incompatible"):
            validator.validate_count_snapshot(rejected)
        assert rejected == unchanged
        assert components.snapshot == original
    advanced = advance_count_components(components, conflict.deadline)
    target = next(s for s in advanced.snapshot.episode_states if s.node_id == "target")
    assert target.health_warning


@pytest.mark.parametrize("count", [1, 2])
def test_runtime_stale_transfer_inputs_keep_physical_hold_not_legacy_support(
    count: int,
) -> None:
    """PATH-001/005 counterpart to the authentic stale-binding component test."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(stale_transfer_map(), count)
        for node_id, seconds in (
            ("independent_entry", 0.1), ("independent_transition", 0.2),
            ("independent_stay", 0.3), ("source", 1), ("bridge", 2),
            ("retained", 3), ("second", 4),
        ):
            replay.send(
                f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
            )
        replay.advance(NOW + timedelta(seconds=5))
        snapshot = replay.inference_snapshot()
        assert snapshot.anonymous_supports == ()
        assert snapshot.count_conflicts == ()
        assert len(snapshot.selected_paths) == count
        assert any(p is not None and p.endpoint.node_id == "second"
                   for p in snapshot.selected_paths)
        assert replay.view().active("second")
        assert replay.view().active("retained")
        assert next(b for b in snapshot.belief_states
                    if b.zone == "retained").physical_hold


@pytest.mark.parametrize("state", ["off", "unknown", "unavailable"])
def test_runtime_presence_loss_uses_stable_clear_or_neutral_frontier(
    state: str,
) -> None:
    """PATH-005: physical holds end on real clear confirmation or availability loss."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(conflict_map(target_presence=True), 2)
        for node_id, seconds in (
            ("target_source", 0), ("target", 1),
            ("a", 2), ("am", 3), ("as", 4),
            ("d", 5), ("dm", 6), ("ds", 7),
        ):
            replay.send(
                f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
            )
        replay.send("binary_sensor.target", state, NOW + timedelta(seconds=8))
        snapshot = replay.inference_snapshot()
        target = next(b for b in snapshot.belief_states if b.zone == "target")
        physical = next(s for s in snapshot.episode_states if s.node_id == "target")
        assert target.physical_hold == (state == "off")
        assert physical.status == ("clearing" if state == "off" else "unavailable")
        assert replay.view().active("target")
        if state == "off":
            assert physical.clear_deadline == NOW + timedelta(seconds=18)
            replay.advance(physical.clear_deadline - timedelta(microseconds=1))
            assert next(b for b in replay.inference_snapshot().belief_states
                        if b.zone == "target").physical_hold
            # Runtime schedules on five-second ticks: the due clear at18 is
            # consumed by the registered20 tick, never fabricated at callback17.
            replay.advance(NOW + timedelta(seconds=20))
            assert not next(b for b in replay.inference_snapshot().belief_states
                            if b.zone == "target").physical_hold


@pytest.mark.parametrize("count", [1, 2])
def test_runtime_provisional_conflict_inputs_keep_only_selected_n_slots(
    count: int,
) -> None:
    """Exact passing provisional stream: PATH slots, not absent legacy tokens."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(conflict_map(), count)
        for node_id, seconds in (
            ("target_source", 0), ("target", 1),
            ("a", 2), ("am", 3), ("d", 4), ("dm", 5),
        ):
            replay.send(
                f"binary_sensor.{node_id}", "on", NOW + timedelta(seconds=seconds),
            )
        snapshot = replay.inference_snapshot()
        located = tuple(p for p in snapshot.selected_paths if p is not None)
        assert len(located) == count
        assert {p.endpoint.node_id for p in located} == (
            {"dm"} if count == 1 else {"am", "dm"}
        )
        assert all(p.track_confidence == "provisional" for p in located)
        assert replay.view().active("dm")
        assert not replay.view().active("d")
        replay.advance(NOW + timedelta(minutes=5))
        after = replay.inference_snapshot()
        assert after.selected_paths == snapshot.selected_paths
        assert replay.view().active("dm")
        assert after.count_conflicts == ()
        assert not next(s for s in after.episode_states
                        if s.node_id == "target").health_warning
