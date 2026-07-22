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
    SensorInput,
    StrongTrackedFront,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


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


def conflict_map(*, extend_a: bool = False) -> PredictiveMap:
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
            "entities": {"motion": "binary_sensor.target"},
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


def test_two_confirmed_fronts_degrade_stuck_assertion_only_after_full_dwell() -> None:
    engine = engine_with_two_front_conflict()
    snapshot = engine.snapshot
    assert len(snapshot.strong_fronts) == 2
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
    assert conflict_row.count_conflict_front_ids == conflict.strong_front_ids
    assert conflict_row.reliability_result == "degraded"

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


def test_provisional_or_insufficient_fronts_cannot_start_count_conflict() -> None:
    engine = ZoneModelEngine(conflict_map(), 2, NOW)
    observe_on(engine, "target_source", 0)
    observe_on(engine, "target", 1)
    observe_on(engine, "a", 2)
    observe_on(engine, "am", 3)
    observe_on(engine, "d", 4)
    observe_on(engine, "dm", 5)

    assert engine.snapshot.strong_fronts == ()
    assert engine.snapshot.count_conflicts == ()
    engine.advance(NOW + timedelta(minutes=5))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert target.degradation_reason is None


def test_ordinary_missed_edge_lineage_is_not_a_strong_front() -> None:
    engine = engine_with_two_front_conflict()
    snapshot = engine.snapshot
    tokens = tuple(
        replace(
            token,
            provenance_kind="missed_edge",
            equivalent_confirmed_strength=False,
        )
        for token in snapshot.traversal_tokens
    )

    fronts = CountConflictTracker()._build_fronts(  # noqa: SLF001
        snapshot.updated_at,
        {state.node_id: state for state in snapshot.episode_states},
        {state.zone: state for state in snapshot.belief_states},
        tokens,
    )

    assert fronts == ()


def test_overlapping_confirmed_lineages_coalesce_to_one_strong_front() -> None:
    engine = engine_with_two_front_conflict()
    snapshot = engine.snapshot
    states = {state.node_id: state for state in snapshot.episode_states}
    a_token = next(
        token
        for token in snapshot.traversal_tokens
        if token.node_id == "as" and token.track_confidence == "confirmed"
    )
    d_token = next(
        token
        for token in snapshot.traversal_tokens
        if token.node_id == "ds" and token.track_confidence == "confirmed"
    )
    target = states["target"]
    assert target.episode_id is not None
    bridge = replace(
        a_token,
        token_id="zz-bridging-target-front",
        node_id="target",
        zone="target",
        episode_id=target.episode_id,
        path_node_ids=("a", "d", "target"),
    )

    fronts = CountConflictTracker()._build_fronts(  # noqa: SLF001
        snapshot.updated_at,
        states,
        {state.zone: state for state in snapshot.belief_states},
        (a_token, d_token, bridge),
    )

    assert len(fronts) == 1
    assert fronts[0].token_ids == tuple(
        sorted((a_token.token_id, d_token.token_id, bridge.token_id))
    )


def test_graph_connected_confirmed_lineages_coalesce_to_one_strong_front() -> None:
    engine = engine_with_two_front_conflict()
    snapshot = engine.snapshot
    a_token = next(
        token
        for token in snapshot.traversal_tokens
        if token.node_id == "as" and token.track_confidence == "confirmed"
    )
    d_token = next(
        token
        for token in snapshot.traversal_tokens
        if token.node_id == "ds" and token.track_confidence == "confirmed"
    )
    connected_left = a_token.path_node_ids[-1]
    connected_right = d_token.path_node_ids[0]
    tracker = CountConflictTracker({connected_left: (connected_right,)})

    fronts = tracker._build_fronts(  # noqa: SLF001
        snapshot.updated_at,
        {state.node_id: state for state in snapshot.episode_states},
        {state.zone: state for state in snapshot.belief_states},
        (a_token, d_token),
    )

    assert len(fronts) == 1
    assert fronts[0].token_ids == tuple(
        sorted((a_token.token_id, d_token.token_id))
    )


def test_count_conflict_restore_rejects_duplicate_fronts_and_targets() -> None:
    snapshot = engine_with_two_front_conflict().snapshot
    front = snapshot.strong_fronts[0]
    conflict = snapshot.count_conflicts[0]
    tracker = CountConflictTracker()

    with pytest.raises(ValueError, match="front.*unique"):
        tracker.restore((front, front), (), 2)
    with pytest.raises(ValueError, match="targets must be unique"):
        tracker.restore((), (conflict, conflict), 2)


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

    matching = CountConflictTracker()
    matching.restore(snapshot.strong_fronts, (conflict,), 2)
    matching.evaluate(
        deadline + timedelta(microseconds=1),
        2,
        engine._nodes,  # noqa: SLF001
        tuple(
            asserted if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        snapshot.belief_states,
        snapshot.traversal_tokens,
        release_dwells,
    )
    assert matching.conflicts[0].target_episode_id == asserted.episode_id

    replaced_episode = replace(asserted, episode_id="replacement")
    replaced_tracker = CountConflictTracker()
    replaced_tracker.restore(snapshot.strong_fronts, (conflict,), 2)
    replaced_tracker.evaluate(
        deadline + timedelta(microseconds=1),
        2,
        engine._nodes,  # noqa: SLF001
        tuple(
            replaced_episode if state.node_id == "target" else state
            for state in snapshot.episode_states
        ),
        snapshot.belief_states,
        snapshot.traversal_tokens,
        release_dwells,
    )
    assert not replaced_tracker.conflicts


def test_front_loss_resets_continuous_conflict_dwell() -> None:
    engine = engine_with_two_front_conflict()
    original_deadline = engine.snapshot.count_conflicts[0].deadline
    engine.observe(
        SensorInput("binary_sensor.ds", "unavailable", NOW + timedelta(seconds=20))
    )
    assert len(engine.snapshot.strong_fronts) == 1
    assert engine.snapshot.count_conflicts == ()

    engine.advance(original_deadline)
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    assert not target.health_warning


def test_connected_front_growth_preserves_continuous_conflict_dwell() -> None:
    engine = engine_with_two_front_conflict(extend_a=True)
    before = engine.snapshot.count_conflicts[0]
    before_front = next(
        front for front in engine.snapshot.strong_fronts if "as" in front.node_ids
    )

    observe_on(engine, "ax", 8)

    after = engine.snapshot.count_conflicts[0]
    after_front = next(
        front for front in engine.snapshot.strong_fronts if "ax" in front.node_ids
    )
    assert after_front.front_id == before_front.front_id
    assert after.started_at == before.started_at
    assert after.deadline == before.deadline
    assert after.strong_front_ids == before.strong_front_ids


def test_front_identity_stabilization_resolves_competing_and_colliding_ids() -> None:
    def front(front_id: str, node_id: str) -> StrongTrackedFront:
        return StrongTrackedFront(
            front_id,
            (f"token-{node_id}",),
            (node_id,),
            (node_id,),
            (f"episode-{node_id}",),
            NOW + timedelta(minutes=1),
        )

    tracker = CountConflictTracker({"a": ("d",)})
    previous = (front("shared", "a"), front("shared#2", "d"))
    current = (
        front("new-a", "a"),
        front("new-d", "d"),
        front("shared", "x"),
    )

    stabilized = tracker._stabilize_front_ids(previous, current)  # noqa: SLF001

    assert {item.front_id for item in stabilized} == {
        "shared",
        "shared#2",
        "shared#3",
    }


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
    assert recovery_row.count_conflict_front_ids
    assert recovery_row.reliability_result == "recovered"


def test_count_change_cancels_unmatured_conflict_without_releasing_target() -> None:
    engine = engine_with_two_front_conflict()
    engine.observe_count(CountInput("count-one", 1, True, NOW + timedelta(seconds=8)))
    assert engine.snapshot.count_conflicts == ()
    engine.advance(NOW + timedelta(seconds=67))
    target = next(
        state for state in engine.snapshot.episode_states if state.node_id == "target"
    )
    policy = next(
        state for state in engine.snapshot.policy_states if state.zone == "target"
    )
    assert not target.health_warning
    assert policy.active
