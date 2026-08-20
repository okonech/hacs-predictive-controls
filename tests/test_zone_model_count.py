from __future__ import annotations

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
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountSupport,
    SensorInput,
)

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


def test_two_settled_supports_degrade_stuck_assertion_only_after_full_dwell() -> None:
    engine = engine_with_two_front_conflict()
    assert engine.diagnostic_counters["count_conflict_started"] == 1
    assert engine.diagnostic_counters["count_conflict_degraded"] == 0
    snapshot = engine.snapshot
    assert len(snapshot.anonymous_supports) == 2
    assert len(snapshot.count_conflicts) == 1
    conflict = snapshot.count_conflicts[0]
    assert conflict.target_node_id == "target"
    assert conflict.deadline == NOW + timedelta(seconds=67)

    before = engine.advance(conflict.deadline - timedelta(microseconds=1))
    target_before = next(
        state for state in before.snapshot.episode_states if state.node_id == "target"
    )
    assert target_before.status == "asserted"
    assert not target_before.health_warning

    crossed = engine.advance(conflict.deadline)
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
    conflict_row = next(
        row for row in engine.audit_rows if row.reason == "stuck_count_conflict"
    )
    assert conflict_row.count_conflict_support_ids == conflict.support_ids
    assert conflict_row.reliability_result == "degraded"
    assert engine.diagnostic_counters["count_conflict_degraded"] == 1

    released = engine.advance(NOW + timedelta(minutes=10))
    target_policy = next(
        state for state in released.snapshot.policy_states if state.zone == "target"
    )
    assert not target_policy.active


def test_external_clear_at_conflict_deadline_cannot_prevent_health_diagnosis() -> None:
    engine = engine_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline

    engine.observe(SensorInput("binary_sensor.target", "off", deadline))

    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.status == "clearing"
    assert target.health_warning
    assert target.degradation_reason == "count_conflict"


def test_provisional_or_insufficient_supports_cannot_start_count_conflict() -> None:
    engine = ZoneModelEngine(conflict_map(), 2, NOW)
    observe_on(engine, "target_source", 0)
    observe_on(engine, "target", 1)
    observe_on(engine, "a", 2)
    observe_on(engine, "am", 3)
    observe_on(engine, "d", 4)
    observe_on(engine, "dm", 5)

    assert engine.snapshot.anonymous_supports == ()
    assert engine.snapshot.count_conflicts == ()
    engine.advance(NOW + timedelta(minutes=5))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.degradation_reason is None


def test_provisional_high_belief_stay_episode_cannot_create_support() -> None:
    engine = ZoneModelEngine(conflict_map(), 2, NOW)
    observe_on(engine, "target_source", 0)
    observe_on(engine, "target", 1)

    target_belief = next(
        state for state in engine.snapshot.belief_states if state.zone == "target"
    )
    assert target_belief.probability >= 0.7
    assert engine.snapshot.anonymous_supports == ()


def test_settled_supports_survive_traversal_token_expiry() -> None:
    engine = engine_with_two_front_conflict()
    initial = engine.snapshot.anonymous_supports
    assert {support.current_zone for support in initial} == {"as", "ds"}

    expired = engine.advance(NOW + timedelta(seconds=100)).snapshot

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
                    "entities": {"mmwave": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    observe_on(engine, "source", 0)
    observe_on(engine, "hall", 1)
    observe_on(engine, "room", 2)
    original = engine.snapshot.anonymous_supports[0]

    engine.observe(SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3)))
    observe_on(engine, "hall", 20)
    moving = engine.snapshot.anonymous_supports[0]
    assert moving.support_id == original.support_id
    assert moving.state == "moving"
    assert moving.current_zone == "hall"

    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=21))
    )
    engine.advance(NOW + timedelta(seconds=31))
    observe_on(engine, "room", 32)
    restored = engine.snapshot.anonymous_supports[0]
    assert restored.support_id == original.support_id
    assert restored.state == "settled"
    assert restored.current_zone == "room"


def test_count_conflict_restore_rejects_duplicate_targets() -> None:
    snapshot = engine_with_two_front_conflict().snapshot
    conflict = snapshot.count_conflicts[0]
    tracker = CountConflictTracker()

    with pytest.raises(ValueError, match="targets must be unique"):
        tracker.restore((conflict, conflict), 2)


def test_restored_degraded_conflict_handles_matching_and_replaced_episode() -> None:
    engine = engine_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    engine.advance(deadline)
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
        engine._nodes,  # noqa: SLF001
        tuple(
            asserted if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        supports,
        release_dwells,
    )
    assert matching.conflicts[0].target_episode_id == asserted.episode_id

    replaced_episode = replace(asserted, episode_id="replacement")
    replaced_tracker = CountConflictTracker()
    replaced_tracker.restore((conflict,), 2)
    replaced_tracker.evaluate(
        deadline + timedelta(microseconds=1),
        2,
        engine._nodes,  # noqa: SLF001
        tuple(
            replaced_episode if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        supports,
        release_dwells,
    )
    assert not replaced_tracker.conflicts


def test_support_loss_resets_continuous_conflict_dwell() -> None:
    engine = engine_with_two_front_conflict()
    original_deadline = engine.snapshot.count_conflicts[0].deadline
    engine.observe(
        SensorInput("binary_sensor.ds", "unavailable", NOW + timedelta(seconds=20))
    )
    assert len(engine.snapshot.anonymous_supports) == 1
    assert engine.snapshot.count_conflicts == ()

    engine.advance(original_deadline)
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert not target.health_warning


def test_inc_2026_08_20_support_loss_recovers_asserted_stay_zone() -> None:
    target_on_at = datetime(2026, 8, 20, 21, 13, 22, 395673, tzinfo=UTC)
    conflict_started_at = datetime(2026, 8, 20, 21, 13, 27, 131114, tzinfo=UTC)
    degraded_at = datetime(2026, 8, 20, 21, 15, 27, 764256, tzinfo=UTC)
    support_lost_at = datetime(2026, 8, 20, 21, 17, 7, 784372, tzinfo=UTC)
    observed_release_at = datetime(2026, 8, 20, 21, 23, 2, 849850, tzinfo=UTC)
    setup_at = target_on_at - timedelta(minutes=1)
    engine = ZoneModelEngine(
        conflict_map(target_presence=True),
        2,
        setup_at,
    )
    for node_id, event_at in (
        ("a", setup_at),
        ("am", setup_at + timedelta(seconds=1)),
        ("as", setup_at + timedelta(seconds=2)),
        ("d", setup_at + timedelta(seconds=3)),
        ("dm", setup_at + timedelta(seconds=4)),
        ("ds", setup_at + timedelta(seconds=5)),
        ("target_source", datetime(2026, 8, 20, 21, 13, 16, 5579, tzinfo=UTC)),
        ("target", target_on_at),
    ):
        engine.observe(SensorInput(f"binary_sensor.{node_id}", "on", event_at))

    acquired = engine.snapshot
    engine.advance(conflict_started_at)
    conflict = engine.snapshot.count_conflicts[0]
    assert conflict.started_at == conflict_started_at
    assert conflict.deadline == conflict_started_at + timedelta(minutes=2)
    degraded = engine.advance(degraded_at)
    engine.observe(
        SensorInput(
            "binary_sensor.ds",
            "unavailable",
            support_lost_at,
        )
    )

    assert len(engine.snapshot.anonymous_supports) == 1
    assert engine.snapshot.count_conflicts == ()
    recovery_row = next(
        row
        for row in engine.audit_rows
        if row.zone == "target" and row.reason == "stuck_conflict_cleared"
    )
    assert recovery_row.event_at == support_lost_at
    assert recovery_row.count_conflict_support_ids == conflict.support_ids
    assert recovery_row.reliability_result == "recovered"
    retained = engine.advance(observed_release_at)
    target = next(
        state for state in retained.snapshot.episode_states if state.node_id == "target"
    )
    target_policy = next(
        state for state in retained.snapshot.policy_states if state.zone == "target"
    )

    assert target.known_on
    assert not target.health_warning
    assert next(
        state for state in acquired.policy_states if state.zone == "target"
    ).active
    assert target_policy.active
    assert not any(
        event.zone == "target" and event.kind == "released"
        for result in (degraded, retained)
        for event in result.policy_events
    )


def test_support_movement_preserves_continuous_conflict_dwell() -> None:
    engine = engine_with_two_front_conflict(extend_a=True)
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

    observe_on(engine, "ax", 8)

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
    engine = engine_with_two_front_conflict()
    deadline = engine.snapshot.count_conflicts[0].deadline
    engine.advance(deadline)
    engine.observe(
        SensorInput("binary_sensor.target", "off", deadline + timedelta(seconds=1))
    )
    engine.advance(deadline + timedelta(seconds=6))
    engine.observe(
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
    recovery_row = next(
        row for row in engine.audit_rows if row.reason == "stuck_conflict_cleared"
    )
    assert recovery_row.count_conflict_support_ids
    assert recovery_row.reliability_result == "recovered"


def test_count_change_cancels_unmatured_conflict_without_releasing_target() -> None:
    engine = engine_with_two_front_conflict()
    engine.observe_count(CountInput("count-one", 1, True, NOW + timedelta(seconds=8)))
    assert engine.snapshot.count_conflicts == ()
    assert engine.diagnostic_counters["count_conflict_started"] == 1
    assert engine.diagnostic_counters["count_conflict_canceled"] == 1
    engine.advance(NOW + timedelta(seconds=67))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    policy = next(
        state for state in engine.snapshot.policy_states if state.zone == "target"
    )
    assert not target.health_warning
    assert policy.active
