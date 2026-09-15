"""Synthetic inverses for REQ-TRAV-020/EVID-013/STATE-009/011.

No incident fixtures, captured state, production patches, or live access.
Original IDs retain the component guarantees in completion-persistence-mapping:
A-K/R-S/V/W use explicit PersistenceComponents; L-Q/X-Y remain frontier units;
T/U and the original initial-zero=True branch remain current-engine checks.
The component's original 45s deadline is NOT selected-path occupancy expiry.
Additive test_current_* counterparts qualify PATH001..006/HEALTH001..004 and
strict current persistence separately. Component documents never enter the
current reader except deliberately incompatible specimens with a real current
header and unchanged selected/health records. No reader dispatch or bypass.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import persistence
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.profiles import SHARED_PROFILES
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeState,
    SensorInput,
    TraversalToken,
    ZoneModelResult,
    ZoneModelSnapshot,
)
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    restore_components,
)
from tests.test_zone_model_traversal import NODES, episode, graph, issue

pytestmark = pytest.mark.target_model
START = datetime(2026, 6, 1, 10, tzinfo=UTC)
MICROSECOND = timedelta(microseconds=1)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def synthetic_map(*, tip_stay: bool = False) -> PredictiveMap:
    """A fork with a removable priming branch, not the production house graph."""
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {
                        "motion": "binary_sensor.source",
                        "pir": "binary_sensor.source_alias",
                    },
                    "initial_weight": 0.9,
                    "adjacent": ["bridge", "target"],
                },
                "bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bridge"},
                    "adjacent": ["source", "tip"],
                },
                "tip": {
                    "role": "room_occupancy" if tip_stay else "transition_gate",
                    "occupancy_behavior": "sustained" if tip_stay else "transient",
                    "entities": {
                        "mmwave" if tip_stay else "motion": "binary_sensor.tip",
                    },
                    "adjacent": ["bridge"],
                },
                "target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.target"},
                    "initial_weight": 0.6,
                    "adjacent": ["source"],
                },
                "unrelated": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.unrelated"},
                },
            }
        }
    )


def new_engine(
    count: int = 2, *, alias_baseline: str = "off", tip_stay: bool = False,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    predictive_map = synthetic_map(tip_stay=tip_stay)
    engine = ZoneModelEngine(predictive_map, count, at(-1))
    engine.bootstrap_sensor_snapshot(
        tuple(
            SensorInput(
                entity,
                alias_baseline if entity.endswith("source_alias") else "off",
                at(-1),
            )
            for node in predictive_map.nodes.values()
            for entity in node.entities.values()
        ),
        at(-1),
    )
    return predictive_map, engine


def observe(
    engine: ZoneModelEngine | PersistenceComponents,
    node: str, state: str, seconds: float,
) -> ZoneModelResult:
    return engine.observe(SensorInput(f"binary_sensor.{node}", state, at(seconds)))


def source_state(snapshot: ZoneModelSnapshot) -> EpisodeState:
    return next(state for state in snapshot.episode_states if state.node_id == "source")


def new_components(
    count: int = 2, *, alias_baseline: str = "off", tip_stay: bool = False,
) -> tuple[PredictiveMap, PersistenceComponents]:
    """Explicit TRAV020 component laboratory, never a selected engine mode."""
    predictive_map = synthetic_map(tip_stay=tip_stay)
    components = PersistenceComponents(predictive_map, count, at(-1))
    components.bootstrap_sensor_snapshot(
        tuple(
            SensorInput(
                entity,
                alias_baseline if entity.endswith("source_alias") else "off",
                at(-1),
            )
            for node in predictive_map.nodes.values()
            for entity in node.entities.values()
        ),
        at(-1),
    )
    return predictive_map, components


def primed_components(
    count: int = 2, *, alias_baseline: str = "off",
) -> tuple[PredictiveMap, PersistenceComponents, TraversalToken]:
    """A-K/R-S/W: authentic original component token, all original scalars."""
    predictive_map, engine = new_components(count, alias_baseline=alias_baseline)
    first = observe(engine, "source", "on", 0)
    assert first.snapshot.traversal_tokens == ()
    assert len(first.snapshot.pending_candidates) == 1
    pair = observe(engine, "bridge", "on", 2)
    assert pair.authorizations[0].reason == "provisional_track_acquired"
    third = observe(engine, "tip", "on", 4)
    assert third.authorizations[0].reason == "track_confirmed"
    original = next(
        token for token in third.snapshot.traversal_tokens if token.node_id == "source"
    )
    assert original.accepted_at == START
    assert original.valid_until == at(45)
    assert original.continuity_reopened_at is None
    assert all(
        binding.token_id != original.token_id
        for binding in third.snapshot.support_token_bindings
    )
    # Remove live, historical, missed-edge, pending, and settled fallback sources
    # by real health inputs; no replacement of component internal state.
    observe(engine, "bridge", "unavailable", 5)
    observe(engine, "tip", "unavailable", 6)
    engine.commit_prediction_learning()
    assert_only_original(engine.snapshot, original)
    assert engine.snapshot.authorization_uses  # Exercise use retention/cleanup.
    return predictive_map, engine, original


def assert_only_original(
    snapshot: ZoneModelSnapshot, original: TraversalToken,
) -> None:
    assert snapshot.traversal_tokens == (original,)
    assert snapshot.retained_traversal_tokens == ()
    assert snapshot.pending_candidates == ()
    assert snapshot.anonymous_supports == ()
    assert snapshot.support_token_bindings == ()


def assert_no_authority(snapshot: ZoneModelSnapshot) -> None:
    assert snapshot.traversal_tokens == ()
    assert snapshot.retained_traversal_tokens == ()
    assert snapshot.current_token_ids == ()
    assert snapshot.authorization_uses == ()
    assert snapshot.anonymous_supports == ()
    assert snapshot.support_token_bindings == ()


def assert_no_evidence(before: ZoneModelSnapshot, result: ZoneModelResult) -> None:
    """Compare at an already advanced frontier, excluding legitimate time decay."""
    after = result.snapshot
    assert after.belief_states == before.belief_states
    assert after.traversal_tokens == before.traversal_tokens
    assert after.retained_traversal_tokens == before.retained_traversal_tokens
    assert after.authorization_uses == before.authorization_uses
    assert after.anonymous_supports == before.anonymous_supports
    assert after.support_token_bindings == before.support_token_bindings
    assert after.count_state == before.count_state
    assert result.authorizations == ()
    assert result.policy_events == ()


def warn(engine: PersistenceComponents, original: TraversalToken) -> None:
    """EVID013 component warning; current health uses six completed cycles."""
    observe(engine, "source", "off", 8)
    engine.advance(at(9))
    before = engine.snapshot
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    result = observe(engine, "source", "on", 9)
    assert result.disposition == "correlated_reassertion"
    assert_no_evidence(before, result)
    assert_only_original(result.snapshot, original)
    source = source_state(result.snapshot)
    assert source.episode_id == original.episode_id
    assert source.generation == 1
    assert source.cadence_warning_reason == "impossible_cadence"
    assert source.cadence_warning and source.known_on
    assert source.status == "asserted" and not source.health_warning
    assert source.traversal_valid_until is None
    assert original.token_id not in result.snapshot.current_token_ids
    # Dataclass equality checks every token field, not just the deadline.
    assert asdict(result.snapshot.traversal_tokens[0]) == asdict(original)
    warning, = result.snapshot.reliability_warning_occurrences
    assert warning.reason == "impossible_cadence" and warning.cleared_at is None
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before


def arrive(
    engine: PersistenceComponents | ZoneModelEngine,
    when: datetime, original: TraversalToken | None,
) -> ZoneModelResult:
    """Legacy component arrival, or the current no-authority/count-zero inverse."""
    published: list[tuple[str, str]] = []
    result = engine.observe(
        SensorInput("binary_sensor.target", "on", when, 0.6),
        decision_callback=lambda event, _decision, _authorization: published.append(
            (event.zone, event.kind)
        ),
    )
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "target"
    )
    authorization, = result.authorizations
    if original is None:
        assert not policy.active
        assert not authorization.authorized
        assert authorization.reason == "track_bootstrap_pending"
        assert authorization.source_tokens == ()
        assert authorization.settled_handoff is None
        assert published == []
        assert not any(event.kind == "acquired" for event in result.policy_events)
        assert not any(
            contribution.kind == "arrival_transition"
            for belief in result.snapshot.belief_states if belief.zone == "target"
            for contribution in belief.contributions
        )
    else:
        assert policy.active
        assert authorization.authorized
        assert authorization.reason == "adjacent_authorized"
        assert authorization.source_tokens == (original,)
        assert authorization.settled_handoff is None
        assert len(authorization.new_uses) == 1
        assert authorization.new_uses[0].token_id == original.token_id
        assert published == [("target", "acquired")]
        assert [(event.zone, event.kind) for event in result.policy_events] == published
        assert next(
            belief for belief in result.snapshot.belief_states
            if belief.zone == "target"
        ).probability >= 0.75
        assert next(
            token for token in result.snapshot.traversal_tokens
            if token.node_id == "source"
        ) == original
    return result


def wire(predictive_map: PredictiveMap, engine: ZoneModelEngine) -> dict[str, Any]:
    """Exercise JSON, not merely dataclass snapshot replacement."""
    return cast(
        dict[str, Any],
        json.loads(json.dumps(serialize_target_state(predictive_map, engine))),
    )


def mutable_record(value: object) -> dict[str, object]:
    """Narrow a mutable JSON object without copying away the intended mutation."""
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return cast(dict[str, object], value)


def mutable_rows(value: object) -> list[dict[str, object]]:
    """Typed access to the real list of JSON objects, not an Any escape hatch."""
    assert isinstance(value, list)
    for row in value:
        mutable_record(row)
    return cast(list[dict[str, object]], value)


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("warning", [False, True], ids=["continuous-on", "warned"])
def test_engine_original_unbound_token_authorizes_fresh_public_target(
    count: int, warning: bool,
) -> None:
    """A: original engine-named ID now qualifies TRAV020 component publication."""
    _, engine, original = primed_components(count)
    if warning:
        warn(engine, original)
    else:
        engine.advance(at(9))
        assert original.token_id in engine.snapshot.current_token_ids
        assert not source_state(engine.snapshot).cadence_warning
    arrive(engine, at(20), original)


@pytest.mark.parametrize("callback", ["repeat", "alias", "stale", "stale-health"])
def test_warned_repeat_alias_and_stale_inputs_are_zero_evidence(callback: str) -> None:
    """B: complete EVID002/006/013 component ignored-input oracle."""
    _, engine, original = primed_components()
    warn(engine, original)
    engine.advance(at(10))
    before = engine.snapshot
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    entity, state, seconds, disposition = {
        "repeat": ("source", "on", 10, "duplicate"),
        "alias": ("source_alias", "on", 10, "correlated_alias"),
        "stale": ("source_alias", "on", 9, "stale"),
        "stale-health": ("source", "unavailable", 9, "stale"),
    }[callback]
    result = observe(engine, entity, state, seconds)
    assert result.disposition == disposition
    assert_no_evidence(before, result)
    assert result.snapshot.current_token_ids == ()
    assert source_state(result.snapshot).episode_id == original.episode_id
    assert source_state(result.snapshot).cadence_warning
    if disposition in {"stale", "duplicate"}:
        assert result.snapshot == before
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    arrive(engine, at(20), original)


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize(
    "offset", [-MICROSECOND, timedelta(0)], ids=["minus-1us", "equality"],
)
def test_engine_original_expiry_has_no_pending_or_settled_fallback(
    count: int, offset: timedelta,
) -> None:
    """C: original engine-named ID owns the component's exact 45s deadline."""
    _, engine, original = primed_components(count)
    warn(engine, original)
    assert_only_original(engine.snapshot, original)
    result = arrive(
        engine, original.valid_until + offset,
        original if offset < timedelta(0) else None,
    )
    if offset == timedelta(0):
        assert_no_authority(result.snapshot)
        assert [
            item.node_id for item in result.snapshot.pending_candidates
        ] == ["target"]


@pytest.mark.parametrize("seed", ["raw-baseline", "pending"])
def test_warning_cannot_manufacture_original_from_raw_on_or_pending(seed: str) -> None:
    """D: bootstrap/pending is not an original warned component token."""
    predictive_map, engine = new_components()
    if seed == "raw-baseline":
        engine.bootstrap_sensor_snapshot(
            (SensorInput("binary_sensor.source", "on", START),), START,
        )
        assert engine.snapshot.pending_candidates == ()
    else:
        observe(engine, "source", "on", 0)
        assert len(engine.snapshot.pending_candidates) == 1
    assert engine.snapshot.traversal_tokens == ()
    observe(engine, "source", "off", 8)
    observe(engine, "source", "on", 9)
    assert source_state(engine.snapshot).cadence_warning
    assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    restored = restore_components(
        predictive_map, component_wire(predictive_map, engine), at(9),
    )
    assert arrive(restored, at(20), None) == arrive(engine, at(20), None)


@pytest.mark.parametrize("health", ["unknown", "unavailable"])
@pytest.mark.parametrize(
    "partial_alias", [False, True], ids=["last-on-alias", "other-alias-on"],
)
def test_live_health_invalidates_before_warning_clear_without_resurrection(
    health: str, partial_alias: bool,
) -> None:
    """E: any live alias health revokes legacy component token preservation."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    if partial_alias:
        observe(engine, "source_alias", "on", 10)
    result = observe(engine, "source", health, 11)
    assert result.disposition == "neutral_availability"
    assert_no_authority(result.snapshot)
    assert result.snapshot.pending_candidates == ()
    source = source_state(result.snapshot)
    assert source.known_on is partial_alias
    assert not source.cadence_warning
    assert source.traversal_valid_until is None
    assert result.authorizations == ()
    assert not any(
        event.kind in {"acquired", "refreshed"} for event in result.policy_events
    )
    if partial_alias:
        # Aggregate on never changed: warning-clear and recovery alias must not
        # turn the removed token into physically-current authority.
        recovered = observe(engine, "source", "on", 12)
        assert recovered.disposition == "correlated_alias"
        assert source_state(recovered.snapshot).episode_id == original.episode_id
        assert_no_authority(recovered.snapshot)
    restored = restore_components(
        predictive_map, component_wire(predictive_map, engine), at(13),
    )
    engine.advance(at(13), emit_events=False)
    assert restored.snapshot == engine.snapshot
    assert arrive(restored, at(20), None) == arrive(engine, at(20), None)


@pytest.mark.parametrize("health", ["unknown", "unavailable"])
def test_unchanged_startup_health_alias_is_not_a_new_health_event(health: str) -> None:
    """F: unchanged baseline alias preserves the component's original token."""
    _, engine, original = primed_components(alias_baseline=health)
    warn(engine, original)
    engine.advance(at(10))
    before = engine.snapshot
    result = observe(engine, "source_alias", health, 10)
    assert result.disposition == "duplicate"
    assert result.snapshot == before
    assert_no_evidence(before, result)
    arrive(engine, at(20), original)


def test_warned_raw_clear_and_repeated_flaps_never_renew_or_resurrect() -> None:
    """G: original three component flaps and stable-clear25 never resurrect."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    for clear_at, positive_at in ((10, 11), (12, 13), (16, 17)):
        observe(engine, "source", "off", clear_at)
        assert_no_authority(engine.snapshot)
        engine.advance(at(positive_at))
        before = engine.snapshot
        result = observe(engine, "source", "on", positive_at)
        assert result.disposition == "correlated_reassertion"
        assert_no_evidence(before, result)
        assert source_state(result.snapshot).episode_id == original.episode_id
        assert source_state(result.snapshot).traversal_valid_until is None
        assert_no_authority(result.snapshot)
    # Clear the warning at a real stable-clear frontier, not with a token reset.
    observe(engine, "source", "off", 20)
    engine.advance(at(25))
    assert not source_state(engine.snapshot).cadence_warning
    assert_no_authority(engine.snapshot)
    restored = restore_components(
        predictive_map, component_wire(predictive_map, engine), at(25),
    )
    assert arrive(restored, at(26), None) == arrive(engine, at(26), None)


@pytest.mark.parametrize("initial_zero", [False, True])
def test_count_zero_prevents_preservation_and_positive_count_cannot_restore_it(
    initial_zero: bool,
) -> None:
    """H: True keeps the full passing current proof; False owns component reset."""
    if initial_zero:
        assert_current_zero_sequence(initial_zero=True)
        return
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    engine.observe_count(CountInput("empty", 0, True, at(10)))
    assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    assert not any(policy.active for policy in engine.snapshot.policy_states)
    observe(engine, "source", "on", 11)
    assert_no_authority(engine.snapshot)
    engine.observe_count(CountInput("occupied", 1, True, at(12)))
    assert_no_authority(engine.snapshot)
    payload = component_wire(predictive_map, engine)
    uninterrupted = arrive(engine, at(20), None)
    # Keep the complete component warning/count roundtrip; never sanitize it.
    restored = restore_components(predictive_map, payload, at(12))
    assert arrive(restored, at(20), None) == uninterrupted


def test_assertion_degradation_cannot_recover_expired_warned_lineage() -> None:
    """I: legacy component trust60/degraded lineage, not current health600."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    result = engine.advance(at(60))
    source = source_state(result.snapshot)
    assert source.status == "degraded" and source.health_warning
    assert source.degradation_reason == "assertion_timeout"
    assert source.cadence_warning
    assert_no_authority(result.snapshot)
    restored = restore_components(
        predictive_map, component_wire(predictive_map, engine), at(60),
    )
    assert arrive(restored, at(61), None) == arrive(engine, at(61), None)


@pytest.mark.parametrize("driver", ["timer", "unrelated-event", "count"])
@pytest.mark.parametrize(
    "offset", [-MICROSECOND, timedelta(0)], ids=["minus-1us", "equality"],
)
def test_all_frontier_drivers_cleanup_before_serialization(
    driver: str, offset: timedelta,
) -> None:
    """J: timer/event/count all own the same half-open component expiry."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    when = original.valid_until + offset
    if driver == "timer":
        engine.advance(when)
    elif driver == "unrelated-event":
        # Accepted baseline health transition; no unrelated pending candidate.
        engine.observe(SensorInput("binary_sensor.unrelated", "unknown", when))
    else:
        engine.observe_count(CountInput("frontier", 1, True, when))
    if offset < timedelta(0):
        assert_only_original(engine.snapshot, original)
        assert engine.snapshot.authorization_uses
    else:
        assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    payload = component_wire(predictive_map, engine)
    restored = restore_components(predictive_map, payload, when)
    assert component_wire(predictive_map, restored) == payload
    assert restored.snapshot == engine.snapshot
    expected = original if offset < timedelta(0) else None
    assert arrive(restored, when, expected) == arrive(engine, when, expected)


@pytest.mark.parametrize(
    "save_offset",
    [timedelta(seconds=9), timedelta(seconds=45) - MICROSECOND, timedelta(seconds=45)],
    ids=["warning", "minus-1us", "equality"],
)
@pytest.mark.parametrize(
    "advance_restore", [False, True], ids=["same-frontier", "advanced-frontier"],
)
def test_serialized_restore_matches_uninterrupted_next_target(
    save_offset: timedelta, advance_restore: bool,
) -> None:
    """K: all original save/equal/+1us component snapshot/audit/arrival checks."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    saved_at = START + save_offset
    engine.advance(saved_at, emit_events=False)
    payload = component_wire(predictive_map, engine)
    saved_payload = deepcopy(payload)
    restored_at = saved_at + (MICROSECOND if advance_restore else timedelta(0))
    restored = restore_components(predictive_map, payload, restored_at)
    if advance_restore:
        engine.advance(restored_at, emit_events=False)
    assert payload == saved_payload
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert component_wire(predictive_map, restored) == component_wire(
        predictive_map, engine,
    )
    expected = original if restored_at < original.valid_until else None
    assert arrive(restored, restored_at, expected) == arrive(
        engine, restored_at, expected,
    )


def unit_original() -> tuple[TraversalFrontier, EpisodeState, TraversalToken]:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode("hall", "hall", "transition_fast", START)
    original = issue(frontier, source)
    target = episode("room_a", "room_a", "stay_pir", at(1))
    assert frontier.authorize(target, at(1), count=None).authorized
    warned = replace(
        source, cadence_warning=True, cadence_warning_reason="impossible_cadence",
        traversal_valid_until=None,
    )
    return frontier, warned, original


@pytest.mark.parametrize(
    "case",
    [
        "no-warning", "episode-validity", "raw-off", "unknown", "unavailable",
        "degraded", "health-warning", "wrong-node", "wrong-zone", "wrong-profile",
        "wrong-generation", "wrong-start", "stay-role", "entry-role",
        "late-acceptance", "short-deadline", "extended-deadline", "reopened",
        "before-acceptance", "expiry-equality",
    ],
)
def test_preservation_predicate_rejects_each_inverse(case: str) -> None:
    _, state, token = unit_original()
    when = at(20)
    assert TraversalFrontier.preserves_warned_token(token, state, when)
    if case == "no-warning":
        state = replace(state, cadence_warning=False, cadence_warning_reason=None)
    elif case == "episode-validity":
        state = replace(state, traversal_valid_until=token.valid_until)
    elif case in {"raw-off", "unknown", "unavailable"}:
        raw = "off" if case == "raw-off" else case
        state = replace(state, alias_states=(("binary_sensor.hall", raw),))
    elif case == "degraded":
        state = replace(state, status="degraded")
    elif case == "health-warning":
        state = replace(state, health_warning=True)
    elif case == "wrong-node":
        token = replace(token, node_id="middle")
    elif case == "wrong-zone":
        token = replace(token, zone="room_b")
    elif case == "wrong-profile":
        token = replace(token, profile_name="stay_pir")
    elif case == "wrong-generation":
        state = replace(state, generation=2, episode_id=f"hall:2:{at(2).isoformat()}")
    elif case == "wrong-start":
        state = replace(state, started_at=at(1))
    elif case in {"stay-role", "entry-role"}:
        token = replace(token, role=case.removesuffix("-role"))
    elif case == "late-acceptance":
        token = replace(token, accepted_at=at(1), valid_until=at(46))
    elif case == "short-deadline":
        token = replace(token, valid_until=token.valid_until - MICROSECOND)
    elif case == "extended-deadline":
        token = replace(token, valid_until=token.valid_until + MICROSECOND)
    elif case == "reopened":
        token = replace(token, continuity_reopened_at=at(15), valid_until=at(60))
    elif case == "before-acceptance":
        when = START - MICROSECOND
    else:
        assert case == "expiry-equality"
        when = token.valid_until
    assert not TraversalFrontier.preserves_warned_token(token, state, when)


@pytest.mark.parametrize("invalidate", [False, True])
def test_sync_preserves_every_original_field_and_use_or_explicitly_invalidates(
    invalidate: bool,
) -> None:
    frontier, state, token = unit_original()
    original_fields = asdict(token)
    uses = frontier.uses
    current_ids = frontier.current_token_ids
    assert current_ids == (token.token_id,)
    for when in (at(9), at(10), token.valid_until - MICROSECOND):
        frontier.sync(state, when, invalidate=invalidate)
        assert frontier.current_token_ids == ()
        assert frontier.retained_tokens == ()
        if invalidate:
            assert frontier.tokens == ()
            assert frontier.uses == ()
        else:
            assert frontier.tokens == (token,)
            assert asdict(frontier.tokens[0]) == original_fields
            assert frontier.uses == uses
    frontier.sync(state, token.valid_until)
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()


@pytest.mark.parametrize(
    "case",
    ["wrong-generation", "clearing", "health", "degraded", "unavailable", "reopened"],
)
def test_sync_drops_ineligible_live_token_and_its_uses(case: str) -> None:
    frontier, state, original = unit_original()
    if case == "wrong-generation":
        state = replace(state, generation=2, episode_id=f"hall:2:{at(2).isoformat()}")
    elif case == "clearing":
        state = replace(
            state, status="clearing", alias_states=(("binary_sensor.hall", "off"),),
        )
    elif case == "health":
        state = replace(state, health_warning=True)
    elif case in {"degraded", "unavailable"}:
        state = replace(state, status=case)
    else:
        reopened = replace(original, continuity_reopened_at=at(15), valid_until=at(60))
        frontier.restore_snapshot(
            (reopened,), (reopened.token_id,), frontier.uses, at(20),
        )
    frontier.sync(state, at(20))
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()
    assert frontier.current_token_ids == ()
    # Repeated sync, including a later warning-free shape, never reconstructs it.
    frontier.sync(
        replace(state, cadence_warning=False, cadence_warning_reason=None), at(21),
    )
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()
    target = episode("room_b", "room_b", "stay_pir", at(22))
    assert not frontier.authorize(target, at(22), count=None).authorized


@pytest.mark.parametrize(
    ("node_id", "profile"),
    [
        ("entry", "entry_boundary"), ("room_a", "stay_pir"),
        ("room_a_presence", "stay_presence"),
    ],
)
def test_nontransition_roles_cannot_preserve_original_on_warning(
    node_id: str, profile: str,
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    physical = next(node for node in NODES if node.node_id == node_id)
    source = episode(
        node_id, physical.zone, profile, START,
        valid_for=SHARED_PROFILES[profile].traversal_context_window,
    )
    token = issue(frontier, source)
    warned = replace(
        source, cadence_warning=True, cadence_warning_reason="impossible_cadence",
        traversal_valid_until=None,
    )
    assert not TraversalFrontier.preserves_warned_token(token, warned, at(2))
    frontier.sync(warned, at(2))
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()


def test_dormant_original_is_not_recovered_by_warning() -> None:
    frontier, state, token = unit_original()
    frontier.advance(token.valid_until)
    retained = frontier.retained_tokens
    assert retained == (token,)
    assert frontier.uses
    frontier.sync(state, token.valid_until)
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()


def test_preserved_token_only_authorizes_distinct_targets_once_each() -> None:
    frontier, state, original = unit_original()
    frontier.sync(state, at(9))
    before = frontier.uses
    self_result = frontier.authorize(state, at(9), count=None)
    assert not self_result.authorized
    assert frontier.pending_candidates == ()
    assert frontier.uses == before
    for node_id in ("room_b", "room_a_presence"):
        target = episode(
            node_id, "room_b" if node_id == "room_b" else "room_a",
            "stay_pir" if node_id == "room_b" else "stay_presence", at(10),
        )
        result = frontier.authorize(target, at(10), count=None)
        assert result.authorized and result.source_tokens == (original,)
        assert len(result.new_uses) == 1
        assert frontier.authorize(target, at(10), count=None).new_uses == ()
        assert frontier.tokens == (original,)
        assert frontier.current_token_ids == ()
    assert len(frontier.uses) == len(before) + 2


def mutate_warned_payload(
    payload: dict[str, object], original: TraversalToken, case: str,
    source_token: dict[str, object], uses: list[dict[str, object]],
) -> None:
    """R: all eight original field/value mutations, shared with strict inverses."""
    snapshot = mutable_record(payload["snapshot"])
    if case == "dormant":
        snapshot["retained_traversal_tokens"] = [deepcopy(source_token)]
        snapshot["authorization_uses"] = deepcopy(uses)
    elif case == "current":
        snapshot["current_token_ids"] = [original.token_id]
    elif case == "pending":
        snapshot["pending_candidates"] = [{
            "node_id": "source", "zone": "source", "profile_name": "transition_fast",
            "episode_id": original.episode_id, "created_at": START.isoformat(),
            "expires_at": at(45).isoformat(),
            "traversal_valid_until": at(45).isoformat(),
            "reliability": 0.9,
        }]
    else:
        token = mutable_rows(snapshot["traversal_tokens"])[0]
        if case == "reopened":
            token["continuity_reopened_at"] = at(15).isoformat()
            token["valid_until"] = at(60).isoformat()
        elif case == "extended-deadline":
            token["valid_until"] = (original.valid_until + MICROSECOND).isoformat()
        elif case == "late-acceptance":
            token["accepted_at"] = at(1).isoformat()
            token["valid_until"] = at(46).isoformat()
        elif case == "bad-provenance":
            token["provenance_kind"] = "invented"
        else:
            token["path_node_ids"] = ["unrelated", "source"]


@pytest.mark.parametrize(
    "case",
    [
        "current", "reopened", "dormant", "pending", "extended-deadline",
        "late-acceptance", "bad-provenance", "bad-path",
    ],
)
def test_serialized_malformed_warned_state_rejects_atomically(case: str) -> None:
    """R: accepted component codec baseline reaches each original exact error."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    initial = mutable_record(component_wire(predictive_map, engine)["snapshot"])
    source_token = deepcopy(mutable_rows(initial["traversal_tokens"])[0])
    uses = deepcopy(mutable_rows(initial["authorization_uses"]))
    if case == "reopened":
        engine.advance(at(20))
    elif case == "dormant":
        engine.advance(original.valid_until)
    baseline = component_wire(predictive_map, engine)
    restored = restore_components(predictive_map, baseline, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert component_wire(predictive_map, restored) == baseline
    payload = deepcopy(baseline)
    mutate_warned_payload(payload, original, case, source_token, uses)
    assert payload != baseline
    expected = {
        "current": "not physically current",
        "reopened": "Warned traversal token is not preservable",
        "dormant": "Warned traversal token is not preservable",
        "pending": "Pending candidate is not bound",
        "extended-deadline": "not bound to its physical episode",
        "late-acceptance": "not bound to its physical episode",
        "bad-provenance": "provenance is incompatible",
        "bad-path": "path is graph-incompatible",
    }[case]
    before = deepcopy(payload)
    live_before = component_wire(predictive_map, engine)
    with pytest.raises(ValueError, match=expected):
        restore_components(predictive_map, payload, engine.snapshot.updated_at)
    assert payload == before
    assert component_wire(predictive_map, engine) == live_before
    assert component_wire(
        predictive_map,
        restore_components(predictive_map, live_before, engine.snapshot.updated_at),
    ) == live_before
    target_at = max(at(20), engine.snapshot.updated_at)
    expected_token = original if target_at < original.valid_until else None
    assert arrive(restored, target_at, expected_token) == arrive(
        engine, target_at, expected_token,
    )


def test_healthy_historical_generation_restores_but_warned_one_rejects() -> None:
    """S: real component historical generation20 and warned generation22."""
    predictive_map, engine, original = primed_components()
    observe(engine, "source", "off", 16)
    # Beyond hardware hold and burst, before stable clear.
    observe(engine, "source", "on", 20)
    healthy = component_wire(predictive_map, engine)
    source = source_state(engine.snapshot)
    assert source.generation == 2 and source.episode_id != original.episode_id
    assert original in engine.snapshot.traversal_tokens
    assert original.token_id not in engine.snapshot.current_token_ids
    restored = restore_components(predictive_map, healthy, at(20))
    assert restored.snapshot == engine.snapshot
    old_token = next(
        token for token in mutable_rows(
            mutable_record(healthy["snapshot"])["traversal_tokens"],
        )
        if token["token_id"] == original.token_id
    )
    observe(engine, "source", "off", 21)
    observe(engine, "source", "on", 22)
    assert source_state(engine.snapshot).cadence_warning
    assert_no_authority(engine.snapshot)
    payload = component_wire(predictive_map, engine)
    snapshot = mutable_record(payload["snapshot"])
    snapshot["traversal_tokens"] = [old_token]
    assert snapshot["current_token_ids"] == []
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="Warned traversal token is not preservable"):
        restore_components(predictive_map, payload, at(22))
    assert payload == before


def digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


@pytest.mark.parametrize("warning", [False, True], ids=["before-flap", "after-flap"])
def test_pre_preservation_fingerprint_rejects_before_decoding(
    monkeypatch: pytest.MonkeyPatch, warning: bool,
) -> None:
    predictive_map, engine = new_engine()
    for node, state, seconds in (
        ("source", "on", 0), ("bridge", "on", 2), ("tip", "on", 4),
        ("bridge", "unavailable", 5), ("tip", "unavailable", 6),
    ):
        observe(engine, node, state, seconds)
    engine.commit_prediction_learning()
    if warning:
        observe(engine, "source", "off", 8)
        observe(engine, "source", "on", 9)
    current = persistence._target_map_fingerprint_payload(predictive_map)
    discriminator = "impossible_cadence_preservation_version"
    assert type(current[discriminator]) is int and current[discriminator] == 1
    assert current["settled_adjacent_transfer_version"] == 1
    previous = deepcopy(current)
    previous.pop(discriminator)
    assert digest(current) == persistence.target_map_fingerprint(predictive_map)
    assert digest(previous) != digest(current)
    payload = wire(predictive_map, engine)
    assert payload["schema"] == "zone-belief-v4"
    assert discriminator not in payload and discriminator not in payload["snapshot"]
    assert all(
        discriminator not in profile
        for profile in cast(dict[str, Any], current["profiles"]).values()
    )

    def unexpected_decode(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Incompatible fingerprint reached the snapshot decoder")

    monkeypatch.setattr(persistence, "_decode_snapshot", unexpected_decode)
    for old_fingerprint in (
        digest(previous),
        persistence.pre_feature_target_map_fingerprint(predictive_map),
        persistence.legacy_target_map_fingerprint(predictive_map),
    ):
        incompatible = deepcopy(payload)
        incompatible["map_fingerprint"] = old_fingerprint
        before = deepcopy(incompatible)
        with pytest.raises(ValueError, match="map fingerprint"):
            restore_target_state(
                predictive_map, incompatible, engine.snapshot.updated_at,
            )
        assert incompatible == before


def test_historical_fingerprint_recipes_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Independently compose the small historical recipe probe. Constants are
    # retained historical hashes, not computed from today's implementation.
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        node: {"role": role, "entities": {"motion": f"binary_sensor.{node}"}}
        for node, role in (("hall", "transition_gate"), ("room", "room_occupancy"))
    }})
    current = persistence._target_map_fingerprint_payload(predictive_map)
    pre_handoff = deepcopy(current)
    pre_handoff.pop("impossible_cadence_preservation_version")
    pre_handoff.pop("settled_adjacent_transfer_version")
    for later_key in (
        "support_departure_version", "supported_gap_acquisition_version",
        "settled_endpoint_release_version", "selected_path_version",
        "path_health_calibration", "presence_gated_departure_version",
        "selected_prediction_execution_version", "unsupported_jump_diagnostics_version",
        "deferred_prediction_learning_version",
    ):
        pre_handoff.pop(later_key)
    assert digest(pre_handoff) == (
        "e5741a7c71744863ca85bbafa3576ce102e71da1ef01c3f7017f67f508bd561c"
    )
    historical = persistence._target_map_fingerprint_payload(
        predictive_map, pre_feature=True,
    )
    assert "impossible_cadence_preservation_version" not in historical
    assert "settled_adjacent_transfer_version" not in historical
    expected = deepcopy(pre_handoff)
    for profile in cast(dict[str, Any], expected["profiles"]).values():
        profile.pop("cycle_correlation_window")
        profile.pop("sustained_cadence_warning_window")
    assert historical == expected
    assert persistence.pre_feature_target_map_fingerprint(predictive_map) == (
        "1b0494301c398bfa60bad3c5d7648950aef79964f99b6c77b4e09bd09627a39d"
    )
    old_profiles = dict(SHARED_PROFILES)
    old_profiles["stay_presence"] = replace(
        old_profiles["stay_presence"], traversal_context_window=timedelta(seconds=120),
    )
    with monkeypatch.context() as patch:
        patch.setattr(persistence, "SHARED_PROFILES", old_profiles)
        assert persistence.pre_feature_target_map_fingerprint(predictive_map) == (
            "f5143467f623123cb6c71d8912a0f1e05b2330484cfb0ec8e9a58ae4eb6357a8"
        )
    legacy = {
        node_id: {
            "zone": node.occupancy_zone,
            "adjacent": sorted(node.adjacent),
            "transition_seconds": dict(sorted(node.transition_seconds.items())),
            "role": node.role,
            "occupancy_behavior": predictive_map.occupancy_behavior_for_node(node),
            "entities": dict(sorted(node.entities.items())),
        }
        for node_id, node in sorted(predictive_map.nodes.items())
    }
    assert persistence.legacy_target_map_fingerprint(predictive_map) == digest(legacy)


def test_warning_cannot_mutate_existing_support_or_enter_prediction_learning() -> None:
    # A confirmed transition-only chain is not count support. Use a real stay
    # endpoint for this nonempty-support inverse; expiry tests keep it absent.
    _, engine = new_components(tip_stay=True)
    observe(engine, "source", "on", 0)
    observe(engine, "bridge", "on", 2)
    observe(engine, "tip", "on", 4)
    engine.commit_prediction_learning()
    observe(engine, "source", "off", 8)
    engine.advance(at(9))
    before = engine.snapshot
    original = next(
        token for token in before.traversal_tokens if token.node_id == "source"
    )
    assert before.anonymous_supports and before.support_token_bindings
    assert all(
        binding.token_id != original.token_id
        for binding in before.support_token_bindings
    )
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    result = observe(engine, "source", "on", 9)
    assert_no_evidence(before, result)
    assert source_state(result.snapshot).cadence_warning
    assert original.token_id not in result.snapshot.current_token_ids
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before


@pytest.mark.parametrize(
    "offset", [-MICROSECOND, timedelta(0)], ids=["minus-1us", "equality"],
)
def test_warning_snapshot_restored_directly_at_original_deadline(
    offset: timedelta,
) -> None:
    """W: real component decode advances from warning9 to original45±1us."""
    predictive_map, engine, original = primed_components()
    warn(engine, original)
    payload = component_wire(predictive_map, engine)
    when = original.valid_until + offset
    restored = restore_components(predictive_map, payload, when)
    engine.advance(when, emit_events=False)
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    if offset == timedelta(0):
        assert_no_authority(restored.snapshot)
    else:
        assert_only_original(restored.snapshot, original)
    expected = original if offset < timedelta(0) else None
    assert arrive(restored, when, expected) == arrive(engine, when, expected)


def test_sync_always_invalidates_pending_even_when_original_is_preserved() -> None:
    frontier, warned, token = unit_original()
    pending_frontier = TraversalFrontier(graph(), NODES)
    healthy = replace(
        warned, cadence_warning=False, cadence_warning_reason=None,
        traversal_valid_until=token.valid_until,
    )
    assert not pending_frontier.authorize(healthy, START, count=None).authorized
    frontier.restore_snapshot(
        frontier.tokens, frontier.current_token_ids, frontier.uses, at(2),
        pending_candidates=pending_frontier.pending_candidates,
    )
    uses = frontier.uses
    assert frontier.pending_candidates
    frontier.sync(warned, at(9))
    assert frontier.tokens == (token,)
    assert frontier.uses == uses
    assert frontier.current_token_ids == ()
    assert frontier.pending_candidates == ()


def test_sustained_flapping_warning_is_not_the_impossible_cadence_exception() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode(
        "room_a_presence", "room_a", "stay_presence", START,
        valid_for=SHARED_PROFILES["stay_presence"].traversal_context_window,
    )
    token = issue(frontier, source)
    warned = replace(
        source, cadence_warning=True, cadence_warning_reason="sustained_flapping",
        cadence_run_started_at=START, cadence_last_transition_at=START,
        cadence_cycle_count=1, traversal_valid_until=None,
    )
    # Isolate the reason guard even if the token role is spuriously transition.
    assert not frontier.preserves_warned_token(
        replace(token, role="transition"), warned, at(1),
    )
    frontier.sync(warned, at(1))
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert frontier.uses == ()


def primed_selected(
    count: int = 2, *, alias_baseline: str = "off", flap: bool = True,
    tip_stay: bool = False, remove_branch: bool = True,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    """PATH001..004: current factory/events, never token-shaped engine repair."""
    predictive_map, engine = new_engine(
        count, alias_baseline=alias_baseline, tip_stay=tip_stay,
    )
    first = observe(engine, "source", "on", 0)
    assert first.snapshot.traversal_tokens == ()
    assert len(first.snapshot.pending_candidates) == 1
    for node, seconds in (("bridge", 2), ("tip", 4)):
        result = observe(engine, node, "on", seconds)
        authorization, = result.authorizations
        assert authorization.authorized
        assert authorization.reason == "selected_path"
        assert authorization.provenance_kind == "selected_path"
        assert authorization.source_tokens == ()
        assert authorization.new_uses == ()
    assert len(engine.snapshot.selected_paths) == count
    assert sum(path is not None for path in engine.snapshot.selected_paths) == 1
    if remove_branch:
        observe(engine, "bridge", "unavailable", 5)
        observe(engine, "tip", "unavailable", 6)
    engine.commit_prediction_learning()
    if flap:
        observe(engine, "source", "off", 8)
        engine.advance(at(9))
        before = engine.snapshot
        prediction_before = deepcopy(engine.prediction_manager.serialize())
        result = observe(engine, "source", "on", 9)
        assert result.disposition == "correlated_reassertion"
        assert_no_evidence(before, result)
        engine.commit_prediction_learning()
        assert engine.prediction_manager.serialize() == prediction_before
        assert not source_state(engine.snapshot).cadence_warning
        assert not source_state(engine.snapshot).health_warning
        assert engine.snapshot.reliability_warning_occurrences == ()
    assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    source = next(s for s in engine.snapshot.selected_sources if s.node_id == "source")
    assert source.origin == "ordinary" and source.consumed
    assert source.at == START
    return predictive_map, engine


def selected_arrive(
    engine: ZoneModelEngine, when: datetime, *, authorized: bool = True,
    path_node_ids: tuple[str, ...] = ("source", "target"),
) -> ZoneModelResult:
    """Real current callback/active/arrival transition; no legacy token oracle."""
    source = source_state(engine.snapshot)
    counts_before = deepcopy(engine.prediction_manager.chain.counts)
    published: list[tuple[str, str]] = []
    result = engine.observe(
        SensorInput("binary_sensor.target", "on", when, 0.6),
        decision_callback=lambda event, _decision, _authorization: published.append(
            (event.zone, event.kind)
        ),
    )
    authorization, = result.authorizations
    policy = next(s for s in result.snapshot.policy_states if s.zone == "target")
    belief = next(s for s in result.snapshot.belief_states if s.zone == "target")
    assert authorization.authorized is authorized
    assert policy.active is authorized
    assert authorization.source_tokens == ()
    assert authorization.new_uses == ()
    assert authorization.settled_handoff is None
    assert not authorization.equivalent_confirmed_strength
    assert published == ([("target", "acquired")] if authorized else [])
    assert [(event.zone, event.kind) for event in result.policy_events] == published
    if authorized:
        assert authorization.reason == "selected_path"
        assert authorization.provenance_kind == "selected_path"
        assert authorization.path_node_ids == path_node_ids
        assert authorization.selected_source_episode_ids == (source.episode_id,)
        assert belief.probability >= 0.75
        assert any(c.kind == "arrival_transition" for c in belief.contributions)
        assert any(
            path is not None and path.visits[-1].node_id == "target"
            for path in result.snapshot.selected_paths
        )
    else:
        assert authorization.reason == "track_bootstrap_pending"
        assert authorization.selected_source_episode_ids == ()
        assert not any(c.kind == "arrival_transition" for c in belief.contributions)
    assert_no_authority(result.snapshot)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts == counts_before
    return result


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("flap", [False, True], ids=["continuous-on", "one-cycle"])
@pytest.mark.parametrize(
    "when", [at(20), at(45) - MICROSECOND, at(45), at(600)],
    ids=["target20", "minus-1us", "component-expiry45", "health-window600"],
)
def test_current_selected_continuation_has_no_component_ttl(
    count: int, flap: bool, when: datetime,
) -> None:
    """A/C/I: selected sourceON survives45/600; only the real target acquires."""
    _, engine = primed_selected(count, flap=flap)
    if not flap:
        engine.advance(at(9))
    paths = engine.snapshot.selected_paths
    sources = engine.snapshot.selected_sources
    engine.advance(when)
    assert engine.snapshot.selected_paths == paths
    assert engine.snapshot.selected_sources == sources
    assert not source_state(engine.snapshot).cadence_warning
    assert not source_state(engine.snapshot).health_warning
    assert engine.snapshot.reliability_warning_occurrences == ()
    assert not next(
        p for p in engine.snapshot.policy_states if p.zone == "source"
    ).active
    selected_arrive(engine, when)


@pytest.mark.parametrize("callback", ["repeat", "alias", "stale", "stale-health"])
def test_current_ignored_callbacks_preserve_selection_and_learning(
    callback: str,
) -> None:
    """B: all four original callbacks remain zero evidence on selected state."""
    _, engine = primed_selected()
    engine.advance(at(10))
    before = engine.snapshot
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    entity, state, seconds, disposition = {
        "repeat": ("source", "on", 10, "duplicate"),
        "alias": ("source_alias", "on", 10, "correlated_alias"),
        "stale": ("source_alias", "on", 9, "stale"),
        "stale-health": ("source", "unavailable", 9, "stale"),
    }[callback]
    result = observe(engine, entity, state, seconds)
    assert result.disposition == disposition
    assert_no_evidence(before, result)
    assert result.snapshot.selected_paths == before.selected_paths
    assert result.snapshot.selected_sources == before.selected_sources
    assert result.snapshot.path_health == before.path_health
    assert not source_state(result.snapshot).cadence_warning
    if disposition in {"stale", "duplicate"}:
        assert result.snapshot == before
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    selected_arrive(engine, at(20))


@pytest.mark.parametrize("seed", ["raw-baseline", "pending"])
def test_current_raw_or_pending_flap_cannot_seed_selection(seed: str) -> None:
    """D: neither startupON nor correlated unselected origin authorizes target20."""
    predictive_map, engine = new_engine()
    if seed == "raw-baseline":
        engine.bootstrap_sensor_snapshot(
            (SensorInput("binary_sensor.source", "on", START),), START,
        )
        assert engine.snapshot.pending_candidates == ()
    else:
        observe(engine, "source", "on", 0)
        assert len(engine.snapshot.pending_candidates) == 1
    observe(engine, "source", "off", 8)
    observe(engine, "source", "on", 9)
    assert not source_state(engine.snapshot).cadence_warning
    assert engine.snapshot.reliability_warning_occurrences == ()
    assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    assert engine.snapshot.selected_paths == (None, None)
    payload = wire(predictive_map, engine)
    saved = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, at(9))
    assert restored.snapshot == engine.snapshot
    assert selected_arrive(restored, at(20), authorized=False) == selected_arrive(
        engine, at(20), authorized=False,
    )
    assert payload == saved


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("health", ["unknown", "unavailable"])
@pytest.mark.parametrize(
    "partial_alias", [False, True], ids=["last-on-alias", "other-alias-on"],
)
def test_current_health_revokes_origin_without_reseeding(
    count: int, health: str, partial_alias: bool,
) -> None:
    """E: no origin resurrection; a still-ON selected alias is a distinct boundary.

    Current reconciliation retains the existing selected branch with a known-ON
    peer. Unlike TRAV020 component tokens, any-alias health does not remove that
    branch. The same consumed source record must NOT become a fresh origin.
    """
    predictive_map, engine = primed_selected(count)
    sources = engine.snapshot.selected_sources
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    if partial_alias:
        observe(engine, "source_alias", "on", 10)
    result = observe(engine, "source", health, 11)
    assert result.disposition == "neutral_availability"
    assert result.authorizations == ()
    assert not any(e.kind in {"acquired", "refreshed"} for e in result.policy_events)
    source = source_state(result.snapshot)
    assert source.known_on is partial_alias
    assert not source.cadence_warning
    assert source.traversal_valid_until is None
    assert_no_authority(result.snapshot)
    assert result.snapshot.pending_candidates == ()
    assert result.snapshot.selected_sources == sources
    if partial_alias:
        recovered = observe(engine, "source", "on", 12)
        assert recovered.disposition == "correlated_alias"
        assert source_state(recovered.snapshot).episode_id == source.episode_id
        assert recovered.snapshot.selected_sources == sources
    restored = restore_target_state(
        predictive_map, wire(predictive_map, engine), at(13),
    )
    engine.advance(at(13), emit_events=False)
    assert restored.snapshot == engine.snapshot
    branches = tuple(
        v for path in engine.snapshot.selected_paths if path is not None
        for v in path.visits if v.node_id == "source"
    )
    assert branches and all(v.branch_active is partial_alias for v in branches)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    continued = selected_arrive(restored, at(20), authorized=partial_alias)
    assert continued == selected_arrive(
        engine, at(20), authorized=partial_alias,
    )


@pytest.mark.parametrize("health", ["unknown", "unavailable"])
def test_current_unchanged_startup_health_alias_is_duplicate(health: str) -> None:
    """F: baseline health does not withdraw a current selected source."""
    _, engine = primed_selected(alias_baseline=health)
    engine.advance(at(10))
    before = engine.snapshot
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    result = observe(engine, "source_alias", health, 10)
    assert result.disposition == "duplicate"
    assert result.snapshot == before
    assert_no_evidence(before, result)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    selected_arrive(engine, at(20))


def test_current_repeated_flaps_and_stable_clear_do_not_reseed() -> None:
    """G: preserve OFF/ON10/11,12/13,16/17 and clear20/25/target26 exactly."""
    predictive_map, engine = primed_selected()
    original = source_state(engine.snapshot)
    sources = engine.snapshot.selected_sources
    counts_before = deepcopy(engine.prediction_manager.chain.counts)
    for clear_at, positive_at in ((10, 11), (12, 13), (16, 17)):
        observe(engine, "source", "off", clear_at)
        assert_no_authority(engine.snapshot)
        engine.advance(at(positive_at))
        before = engine.snapshot
        result = observe(engine, "source", "on", positive_at)
        assert result.disposition == "correlated_reassertion"
        assert_no_evidence(before, result)
        assert source_state(result.snapshot).episode_id == original.episode_id
        assert result.snapshot.selected_sources == sources
        assert not source_state(result.snapshot).cadence_warning
    observe(engine, "source", "off", 20)
    engine.advance(at(25))
    assert engine.snapshot.reliability_warning_occurrences == ()
    assert engine.snapshot.selected_sources == sources
    assert_no_authority(engine.snapshot)
    health = next(s for s in engine.snapshot.path_health if s.node_id == "source")
    assert health.completed_cycles == (at(8), at(10), at(12), at(16), at(20))
    restored = restore_target_state(
        predictive_map, wire(predictive_map, engine), at(25),
    )
    assert selected_arrive(restored, at(26), authorized=False) == selected_arrive(
        engine, at(26), authorized=False,
    )
    assert engine.prediction_manager.chain.counts == counts_before


def assert_current_zero_sequence(*, initial_zero: bool) -> None:
    """H: full original initial-zero current oracle, plus selected count reset."""
    if initial_zero:
        predictive_map, engine = new_engine(0)
        observe(engine, "source", "on", 0)
        observe(engine, "source", "off", 8)
        observe(engine, "source", "on", 9)
    else:
        predictive_map, engine = primed_selected()
        engine.observe_count(CountInput("empty", 0, True, at(10)))
    assert_no_authority(engine.snapshot)
    assert engine.snapshot.pending_candidates == ()
    assert not any(policy.active for policy in engine.snapshot.policy_states)
    assert engine.snapshot.selected_paths == ()
    original = source_state(engine.snapshot)
    counts_before = deepcopy(engine.prediction_manager.chain.counts)
    observe(engine, "source", "on", 11)
    assert_no_authority(engine.snapshot)
    occupied = engine.observe_count(CountInput("occupied", 1, True, at(12)))
    assert_no_authority(engine.snapshot)
    assert occupied.snapshot.selected_paths == (None,)
    assert source_state(engine.snapshot).episode_id == original.episode_id
    payload = wire(predictive_map, engine)
    before = deepcopy(payload)
    uninterrupted = arrive(engine, at(20), None)
    # Original strict current reader and all arrival assertions remain intact.
    restored = restore_target_state(predictive_map, payload, at(12))
    assert wire(predictive_map, restored) == before
    assert arrive(restored, at(20), None) == uninterrupted
    assert payload == before
    engine.commit_prediction_learning()
    restored.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts == counts_before
    assert restored.prediction_manager.chain.counts == counts_before


@pytest.mark.parametrize("initial_zero", [False, True])
def test_current_count_zero_and_positive_count_never_resurrect(
    initial_zero: bool,
) -> None:
    """H: additive complete current counterparts for both original count paths."""
    assert_current_zero_sequence(initial_zero=initial_zero)


@pytest.mark.parametrize("count", [1, 2])
def test_current_six_completed_cycles_not_five_are_diagnostic_only(count: int) -> None:
    """G/I/Y: actual aggregate cycles, never the legacy single-flap warning."""
    predictive_map, engine = primed_selected(count)
    assert engine.snapshot.reliability_warning_occurrences == ()
    original = source_state(engine.snapshot)
    sources = engine.snapshot.selected_sources
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    # The first completed OFF8 is in primed_selected; these make exactly five.
    for clear_at, positive_at in ((10, 11), (12, 13), (16, 17), (20, 21)):
        observe(engine, "source", "off", clear_at)
        result = observe(engine, "source", "on", positive_at)
        assert result.disposition == "correlated_reassertion"
        assert result.authorizations == ()
        assert result.policy_events == ()
        assert engine.snapshot.reliability_warning_occurrences == ()
    health = next(s for s in engine.snapshot.path_health if s.node_id == "source")
    assert health.completed_cycles == (at(8), at(10), at(12), at(16), at(20))
    sixth = observe(engine, "source", "off", 22)
    health = next(s for s in sixth.snapshot.path_health if s.node_id == "source")
    assert health.completed_cycles == (at(8), at(10), at(12), at(16), at(20), at(22))
    warning, = sixth.snapshot.reliability_warning_occurrences
    assert warning.reason == "sustained_flapping" and warning.cleared_at is None
    assert warning.first_observed_at == at(22)
    assert warning.last_observed_at == at(22)
    result = observe(engine, "source", "on", 23)
    assert result.disposition == "correlated_reassertion"
    assert result.authorizations == () and result.policy_events == ()
    assert source_state(result.snapshot).episode_id == original.episode_id
    assert not source_state(result.snapshot).cadence_warning
    assert not source_state(result.snapshot).health_warning
    assert result.snapshot.selected_sources == sources
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    restored = restore_target_state(
        predictive_map, wire(predictive_map, engine), at(23),
    )
    assert restored.snapshot == engine.snapshot
    arrival = selected_arrive(engine, at(24))
    assert selected_arrive(restored, at(24)) == arrival
    assert arrival.snapshot.reliability_warning_occurrences[0].cleared_at is None


@pytest.mark.parametrize("count", [1, 2])
def test_current_unsupported_on_warns_at_600_without_expiring_origin(
    count: int,
) -> None:
    """I: trust60 is not current degradation; real unsupported600 is diagnostic."""
    predictive_map, engine = new_engine(count)
    observe(engine, "source", "on", 0)
    original = source_state(engine.snapshot)
    sources = engine.snapshot.selected_sources
    counts_before = deepcopy(engine.prediction_manager.chain.counts)
    engine.advance(at(60))
    assert engine.snapshot.reliability_warning_occurrences == ()
    assert not source_state(engine.snapshot).health_warning
    engine.advance(at(600) - MICROSECOND)
    assert engine.snapshot.reliability_warning_occurrences == ()
    payload = wire(predictive_map, engine)
    before = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, at(600))
    advanced = engine.advance(at(600), emit_events=False)
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert payload == before
    warning, = advanced.snapshot.reliability_warning_occurrences
    assert warning.reason == "assertion_timeout" and warning.cleared_at is None
    assert warning.first_observed_at == at(600)
    assert warning.last_observed_at == at(600)
    assert source_state(engine.snapshot).status == "asserted"
    assert not source_state(engine.snapshot).health_warning
    assert not source_state(engine.snapshot).cadence_warning
    assert source_state(engine.snapshot).episode_id == original.episode_id
    assert engine.snapshot.selected_sources == sources
    assert engine.snapshot.selected_paths == (None,) * count
    arrival = selected_arrive(engine, at(601))
    assert selected_arrive(restored, at(601)) == arrival
    warning, = arrival.snapshot.reliability_warning_occurrences
    assert warning.cleared_at == at(601)
    assert engine.prediction_manager.chain.counts == counts_before


@pytest.mark.parametrize("driver", ["timer", "unrelated-event", "count"])
@pytest.mark.parametrize(
    "offset", [-MICROSECOND, timedelta(0)], ids=["minus-1us", "equality"],
)
def test_current_frontier_drivers_preserve_selected_continuation(
    driver: str, offset: timedelta,
) -> None:
    """J: original three drivers at45±1us use strict current serialization."""
    predictive_map, engine = primed_selected()
    when = at(45) + offset
    paths = tuple(path for path in engine.snapshot.selected_paths if path is not None)
    sources = engine.snapshot.selected_sources
    counts_before = deepcopy(engine.prediction_manager.chain.counts)
    if driver == "timer":
        engine.advance(when)
    elif driver == "unrelated-event":
        engine.observe(SensorInput("binary_sensor.unrelated", "unknown", when))
    else:
        engine.observe_count(CountInput("frontier", 1, True, when))
    assert tuple(p for p in engine.snapshot.selected_paths if p is not None) == paths
    assert engine.snapshot.selected_sources == sources
    assert engine.snapshot.pending_candidates == ()
    assert_no_authority(engine.snapshot)
    payload = wire(predictive_map, engine)
    before = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, when)
    assert wire(predictive_map, restored) == payload
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert selected_arrive(restored, when) == selected_arrive(engine, when)
    assert payload == before
    assert engine.prediction_manager.chain.counts == counts_before


@pytest.mark.parametrize(
    "save_offset",
    [timedelta(seconds=9), timedelta(seconds=45) - MICROSECOND, timedelta(seconds=45)],
    ids=["warning", "minus-1us", "equality"],
)
@pytest.mark.parametrize(
    "advance_restore", [False, True], ids=["same-frontier", "advanced-frontier"],
)
def test_current_serialized_restore_matches_next_selected_target(
    save_offset: timedelta, advance_restore: bool,
) -> None:
    """K: full original six-frontier matrix against actual current wire reader."""
    predictive_map, engine = primed_selected()
    saved_at = START + save_offset
    engine.advance(saved_at, emit_events=False)
    payload = wire(predictive_map, engine)
    saved_payload = deepcopy(payload)
    restored_at = saved_at + (MICROSECOND if advance_restore else timedelta(0))
    restored = restore_target_state(predictive_map, payload, restored_at)
    if advance_restore:
        engine.advance(restored_at, emit_events=False)
    assert payload == saved_payload
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert wire(predictive_map, restored) == wire(predictive_map, engine)
    assert selected_arrive(restored, restored_at) == selected_arrive(
        engine, restored_at,
    )


@pytest.mark.parametrize(
    "offset", [-MICROSECOND, timedelta(0)], ids=["minus-1us", "equality"],
)
def test_current_flap_snapshot_restores_directly_at_component_deadline(
    offset: timedelta,
) -> None:
    """W: save9/restore45±1us retains selection, not original token TTL."""
    predictive_map, engine = primed_selected()
    payload = wire(predictive_map, engine)
    before = deepcopy(payload)
    when = at(45) + offset
    restored = restore_target_state(predictive_map, payload, when)
    engine.advance(when, emit_events=False)
    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert wire(predictive_map, restored) == wire(predictive_map, engine)
    assert payload == before
    assert selected_arrive(restored, when) == selected_arrive(engine, when)


def current_warning_specimen(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
    components: PersistenceComponents,
) -> dict[str, object]:
    """Deliberately incompatible episode/token fields, NOT selected-state surgery.

    Keep a real current serializer's header, prediction, policy, selection and
    PathHealth from the identical observations. Only legacy component fields are
    substituted to expose the early strict legacy-warning guard independently
    from the deeper component cross-link validators.
    """
    component = components.snapshot
    assert component.updated_at == engine.snapshot.updated_at
    snapshot = replace(
        engine.snapshot, episode_states=component.episode_states,
        traversal_tokens=component.traversal_tokens,
        retained_traversal_tokens=component.retained_traversal_tokens,
        current_token_ids=component.current_token_ids,
        pending_candidates=component.pending_candidates,
        authorization_uses=component.authorization_uses,
    )
    payload = mutable_record(wire(predictive_map, engine))
    payload["snapshot"] = persistence._json_value(asdict(snapshot))
    return payload


@pytest.mark.parametrize(
    "case",
    [
        "current", "reopened", "dormant", "pending", "extended-deadline",
        "late-acceptance", "bad-provenance", "bad-path",
    ],
)
def test_current_strict_reader_rejects_each_legacy_warned_mutation(case: str) -> None:
    """R: accepted current control plus warning-only and exact original mutation."""
    predictive_map, components, original = primed_components()
    warn(components, original)
    _, engine = primed_selected()
    initial = mutable_record(component_wire(predictive_map, components)["snapshot"])
    source_token = deepcopy(mutable_rows(initial["traversal_tokens"])[0])
    uses = deepcopy(mutable_rows(initial["authorization_uses"]))
    if case in {"reopened", "dormant"}:
        when = at(20) if case == "reopened" else original.valid_until
        components.advance(when)
        engine.advance(when)
    baseline = wire(predictive_map, engine)
    saved_baseline = deepcopy(baseline)
    restored = restore_target_state(
        predictive_map, baseline, engine.snapshot.updated_at,
    )
    assert restored.snapshot == engine.snapshot
    assert wire(predictive_map, restored) == baseline
    payload = current_warning_specimen(predictive_map, engine, components)
    warning_only = deepcopy(payload)
    with pytest.raises(ValueError, match="cannot restore legacy warnings"):
        restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert payload == warning_only
    mutate_warned_payload(payload, original, case, source_token, uses)
    assert payload != warning_only
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="cannot restore legacy warnings"):
        restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert payload == before
    assert baseline == saved_baseline
    assert wire(predictive_map, engine) == saved_baseline
    target_at = max(at(20), engine.snapshot.updated_at)
    assert selected_arrive(restored, target_at) == selected_arrive(engine, target_at)


def test_current_historical_generation_and_legacy_warning_rejection() -> None:
    """S: strict current generation20/22 and incompatible historical component."""
    predictive_map, components, original = primed_components()
    _, engine = primed_selected(flap=False)
    for model in (engine, components):
        observe(model, "source", "off", 16)
        observe(model, "source", "on", 20)
    source = source_state(engine.snapshot)
    assert source.generation == 2 and source.episode_id != original.episode_id
    healthy = wire(predictive_map, engine)
    restored = restore_target_state(predictive_map, healthy, at(20))
    assert restored.snapshot == engine.snapshot
    for model in (engine, components, restored):
        observe(model, "source", "off", 21)
        observe(model, "source", "on", 22)
    assert restored.snapshot == engine.snapshot
    assert source_state(components.snapshot).cadence_warning
    assert not source_state(engine.snapshot).cadence_warning
    assert_no_authority(engine.snapshot)
    baseline = wire(predictive_map, engine)
    assert restore_target_state(
        predictive_map, baseline, at(22),
    ).snapshot == engine.snapshot
    payload = current_warning_specimen(predictive_map, engine, components)
    mutable_record(payload["snapshot"])["traversal_tokens"] = [
        persistence._json_value(asdict(original)),
    ]
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="cannot restore legacy warnings"):
        restore_target_state(predictive_map, payload, at(22))
    assert payload == before
    assert wire(predictive_map, engine) == baseline
    # Distinct generations of source are retained visits, not an invented edge
    # through an unseen middle. Preserve the exact current path, including both.
    path = ("source", "source", "target")
    assert selected_arrive(restored, at(23), path_node_ids=path) == selected_arrive(
        engine, at(23), path_node_ids=path,
    )


def test_current_real_stay_selection_flap_cannot_learn_or_mutate_support() -> None:
    """V: real staytip4 selects/retains; component nonempty support stays separate."""
    predictive_map, engine = primed_selected(
        tip_stay=True, remove_branch=False, flap=False,
    )
    observe(engine, "source", "off", 8)
    engine.advance(at(9))
    before = engine.snapshot
    assert any(
        path is not None and path.visits[-1].node_id == "tip"
        for path in before.selected_paths
    )
    assert next(p for p in before.policy_states if p.zone == "tip").active
    assert before.anonymous_supports == ()
    assert before.support_token_bindings == ()
    prediction_before = deepcopy(engine.prediction_manager.serialize())
    result = observe(engine, "source", "on", 9)
    assert_no_evidence(before, result)
    assert result.snapshot.selected_sources == before.selected_sources
    assert not source_state(result.snapshot).cadence_warning
    assert next(p for p in result.snapshot.policy_states if p.zone == "tip").active
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    restored = restore_target_state(predictive_map, wire(predictive_map, engine), at(9))
    assert restored.snapshot == engine.snapshot
