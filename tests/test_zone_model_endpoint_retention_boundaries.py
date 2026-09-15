"""PATH001..004 / POLICY013 / STATE005/010/011 endpoint boundary proofs.

Only the explicitly isolated historical decoder may default a missing hold.
Real components qualify legacy supports; current selected paths have no tokens.
Historical decoding never supplies an incomplete snapshot to the current engine.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.persistence import (
    _decode_snapshot,
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    ZonePolicy,
)
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    OutwardContext,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneBeliefState,
    ZoneModelResult,
    ZoneModelSnapshot,
    ZonePolicyState,
)
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
)
from tests.handoff_lifecycle_fixture import (
    commit_component_arrival,
    prepare_component_arrival,
    publish_component_arrival,
)
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    decode_component_snapshot,
    restore_components,
)

pytestmark = pytest.mark.target_model
START = datetime(2026, 9, 1, tzinfo=UTC)
EPSILON = timedelta(microseconds=1)


def _at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def _map() -> PredictiveMap:
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": "room_occupancy" if node == "room" else "transition_gate",
                "occupancy_behavior": "sustained" if node == "room" else "transient",
                "entities": {"motion": f"binary_sensor.{node}"},
                "adjacent": adjacent,
            }
            for node, adjacent in (
                ("source", ["hall"]), ("hall", ["source", "room"]),
                ("room", ["hall"]),
            )
        },
    })


def _policy(snapshot: ZoneModelSnapshot) -> ZonePolicyState:
    return next(state for state in snapshot.policy_states if state.zone == "room")


def _belief(snapshot: ZoneModelSnapshot) -> ZoneBeliefState:
    return next(state for state in snapshot.belief_states if state.zone == "room")


def _send(
    engine: ZoneModelEngine | PersistenceComponents,
    node: str, state: str, seconds: float,
) -> ZoneModelResult:
    return engine.observe(SensorInput(f"binary_sensor.{node}", state, _at(seconds)))


def _settled(
    count: int, *, seeded: bool = False,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    predictive_map = _map()
    engine = ZoneModelEngine(
        predictive_map, count, START,
        active_seed={"room": True} if seeded else None,
    )
    for node, state, seconds in (
        ("source", "on", 0), ("hall", "on", 1), ("room", "on", 2),
        ("source", "off", 4), ("hall", "off", 5), ("room", "off", 7),
    ):
        _send(engine, node, state, seconds)
    snapshot = engine.advance(_at(20)).snapshot
    assert _policy(snapshot).active
    paths = tuple(path for path in snapshot.selected_paths if path is not None)
    assert len(paths) == 1
    assert tuple(visit.node_id for visit in paths[0].visits) == (
        "source", "hall", "room",
    )
    assert paths[0].track_confidence == "confirmed"
    assert len(snapshot.selected_paths) == count
    assert not snapshot.anonymous_supports and not snapshot.support_token_bindings
    assert not snapshot.traversal_tokens and not snapshot.retained_traversal_tokens
    assert _belief(snapshot).context == "cleared_without_outward"
    return predictive_map, engine


def _settled_components(
    count: int, *, seeded: bool = False,
) -> tuple[PredictiveMap, PersistenceComponents]:
    """Original observations and calibration at the legacy component boundary."""
    predictive_map = _map()
    components = PersistenceComponents(predictive_map, count, START)
    if seeded:
        components.policies["room"] = ZonePolicy(
            "room", POLICY_CALIBRATIONS["stay_pir"], START, active=True,
        )
    for node, state, seconds in (
        ("source", "on", 0), ("hall", "on", 1), ("room", "on", 2),
        ("source", "off", 4), ("hall", "off", 5), ("room", "off", 7),
    ):
        _send(components, node, state, seconds)
    snapshot = components.advance(_at(20)).snapshot
    assert _policy(snapshot).active
    assert len(snapshot.anonymous_supports) == 1
    support = snapshot.anonymous_supports[0]
    assert support.state == "settled" and support.current_node_id == "room"
    assert support.path_node_ids == ("source", "hall", "room")
    assert support.valid_until is None
    assert _belief(snapshot).context == "cleared_without_outward"
    assert not snapshot.selected_paths
    return predictive_map, components


def _restore_component(
    predictive_map: PredictiveMap, components: PersistenceComponents,
) -> PersistenceComponents:
    payload = component_wire(predictive_map, components)
    frozen = deepcopy(payload)
    assert decode_component_snapshot(payload["snapshot"]) == components.snapshot
    restored = restore_components(
        predictive_map, json.loads(json.dumps(payload)), components.updated_at,
    )
    assert payload == frozen
    assert restored.snapshot == components.snapshot
    assert restored.audit_rows == components.audit_rows
    return restored


def _restore(predictive_map: PredictiveMap, engine: ZoneModelEngine) -> ZoneModelEngine:
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(
        predictive_map, json.loads(json.dumps(payload)), engine.snapshot.updated_at,
    )
    assert restored.snapshot == engine.snapshot
    return restored


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("pending", (False, True))
@pytest.mark.parametrize("trigger", ("duplicate", "invalid_count", "unavailable_count"))
def test_historical_default_hold_initializes_before_ignored_input_can_release(
    count: int, pending: bool, trigger: str,
) -> None:
    # D/L: historical hold default and pending cancellation belong to the real
    # decoder/policy, not a selected engine with missing physical/path ledgers.
    predictive_map, live = _settled_components(count)
    before = live.advance(_at(1200)).snapshot
    assert _policy(before).retained_endpoint_hold
    assert _belief(before).probability < POLICY_CALIBRATIONS["stay_pir"].off_threshold
    assert not before.traversal_tokens and not before.retained_traversal_tokens
    assert not before.support_token_bindings
    original = component_wire(predictive_map, live)
    candidate = _restore_component(predictive_map, live)
    historical = deepcopy(original)
    raw = cast(dict[str, object], historical["snapshot"])
    for row in cast(list[dict[str, object]], raw["policy_states"]):
        del row["retained_endpoint_hold"]

    # The strict component reader reaches the same required policy field.
    # The separately named current matrix checks the complete current envelope.
    frozen = deepcopy(historical)
    with pytest.raises(
        ValueError, match="^Target retained_endpoint_hold must be boolean$",
    ):
        candidate = restore_components(predictive_map, historical, before.updated_at)
    assert historical == frozen
    assert component_wire(predictive_map, candidate) == original
    decoded = _decode_snapshot(raw, pre_feature_v4=True)
    assert decoded.anonymous_supports == before.anonymous_supports
    assert _policy(decoded).activation_provenance == "evidence"
    assert not _policy(decoded).retained_endpoint_hold
    assert _belief(decoded).qualified_departure_at is None
    if pending:
        # Reproduce historical, support-unaware policy evaluation, not an
        # arbitrary pending timestamp grafted onto a currently held policy.
        old_policy = ZonePolicy(
            "room", POLICY_CALIBRATIONS["stay_pir"], before.updated_at,
            state=_policy(decoded),
        )
        update = old_policy.evaluate(
            before.updated_at, _belief(decoded), _belief(decoded),
            local_state=None, local_effect=None, authorization=None,
        )
        assert update.state.pending_release_since == before.updated_at
        decoded = replace(decoded, policy_states=tuple(
            update.state if state.zone == "room" else state
            for state in decoded.policy_states
        ))
    # Install only decoded policies into independent real component policies.
    # No historical inference snapshot is ever passed to ZoneModelEngine.restore.
    for state in decoded.policy_states:
        candidate.policies[state.zone] = ZonePolicy(
            state.zone, POLICY_CALIBRATIONS[state.profile_name], decoded.updated_at,
            state=state, audit=candidate.policies[state.zone].audit,
        )
    assert not _policy(candidate.snapshot).retained_endpoint_hold
    if trigger == "duplicate":
        # This fixture deliberately does not schedule policies on duplicate
        # observe(). Explicitly evaluate due component policy before ignored input.
        result = candidate.advance(_at(1300))
        ignored = _send(candidate, "room", "off", 1300)
        assert ignored.disposition == "duplicate"
        assert not ignored.authorizations and not ignored.policy_events
        assert ignored.snapshot == result.snapshot
    else:
        result = candidate.observe_count(CountInput(
            trigger, None if trigger == "invalid_count" else count,
            trigger != "unavailable_count", _at(1300),
        ))
        assert result.disposition == (
            "invalid" if trigger == "invalid_count" else "unavailable"
        )
    state = _policy(result.snapshot)
    assert state.active and state.retained_endpoint_hold
    assert state.pending_release_since is None
    assert result.snapshot.count_state.expected_count == count
    assert not result.policy_events and not result.authorizations
    decisions = [row for row in result.policy_decisions if row.zone == "room"]
    assert len(decisions) == 1
    assert decisions[0].reason == "retained_endpoint_hold"
    assert not decisions[0].local_trustworthy
    assert result.snapshot.anonymous_supports == before.anonymous_supports
    control = live.advance(_at(1300)).snapshot
    assert _belief(result.snapshot) == _belief(control)
    assert result.snapshot.episode_states == control.episode_states
    current = component_wire(predictive_map, candidate)
    assert current["schema"] == "persistence-component-specimen"
    candidate = _restore_component(predictive_map, candidate)
    repeated = _send(candidate, "room", "off", 1300)
    assert not repeated.policy_events and not repeated.policy_decisions
    assert _policy(candidate.advance(_at(3600)).snapshot).active
    assert historical == frozen


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("pending", (False, True))
@pytest.mark.parametrize("trigger", ("duplicate", "invalid_count", "unavailable_count"))
def test_current_selected_hold_initializes_before_ignored_input_can_release(
    count: int, pending: bool, trigger: str,
) -> None:
    """S/D: full current baseline, exact deletion, and real pending evaluation."""
    predictive_map, live = _settled(count)
    before = live.advance(_at(1200)).snapshot
    assert _policy(before).retained_endpoint_hold
    assert _belief(before).probability < POLICY_CALIBRATIONS["stay_pir"].off_threshold
    original = serialize_target_state(predictive_map, live)
    receiver = _restore(predictive_map, live)
    malformed = deepcopy(original)
    raw = cast(dict[str, object], malformed["snapshot"])
    for row in cast(list[dict[str, object]], raw["policy_states"]):
        del row["retained_endpoint_hold"]
    frozen = deepcopy(malformed)
    receiver_before = serialize_target_state(predictive_map, receiver)
    with pytest.raises(
        ValueError, match="^Target retained_endpoint_hold must be boolean$",
    ):
        receiver = restore_target_state(predictive_map, malformed, before.updated_at)
    assert malformed == frozen
    assert serialize_target_state(predictive_map, receiver) == receiver_before

    # A present False field is structurally valid current state, unlike deletion.
    # Reproduce unheld evaluation using the actual policy, not a grafted deadline.
    state = replace(_policy(before), retained_endpoint_hold=False)
    if pending:
        policy = ZonePolicy(
            "room", POLICY_CALIBRATIONS["stay_pir"], before.updated_at, state=state,
        )
        state = policy.evaluate(
            before.updated_at, _belief(before), _belief(before),
            local_state=None, local_effect=None, authorization=None,
        ).state
        assert state.pending_release_since == before.updated_at
    snapshot = replace(before, policy_states=tuple(
        state if item.zone == "room" else item for item in before.policy_states
    ))
    candidate = ZoneModelEngine.restore(
        predictive_map, snapshot, live.audit_rows, before.updated_at,
        prediction_state=live.prediction_manager.serialize(),
    )
    candidate = _restore(predictive_map, candidate)
    assert candidate.snapshot == snapshot
    if trigger == "duplicate":
        result = _send(candidate, "room", "off", 1300)
        assert result.disposition == "duplicate"
    else:
        result = candidate.observe_count(CountInput(
            trigger, None if trigger == "invalid_count" else count,
            trigger != "unavailable_count", _at(1300),
        ))
        assert result.disposition == (
            "invalid" if trigger == "invalid_count" else "unavailable"
        )
    held = _policy(result.snapshot)
    assert held.active and held.retained_endpoint_hold
    assert held.pending_release_since is None
    assert result.snapshot.count_state.expected_count == count
    assert not result.policy_events and not result.authorizations
    decision, = (row for row in result.policy_decisions if row.zone == "room")
    assert decision.reason == "retained_endpoint_hold"
    assert not decision.local_trustworthy
    assert result.snapshot.selected_paths == before.selected_paths
    assert not result.snapshot.anonymous_supports
    assert not result.snapshot.traversal_tokens
    control = receiver.advance(_at(1300)).snapshot
    assert _belief(result.snapshot) == _belief(control)
    assert result.snapshot.episode_states == control.episode_states
    candidate = _restore(predictive_map, candidate)
    repeated = _send(candidate, "room", "off", 1300)
    assert not repeated.policy_events and not repeated.policy_decisions
    continuation = _restore(predictive_map, candidate)
    assert (
        candidate.advance(_at(3600)).snapshot
        == continuation.advance(_at(3600)).snapshot
    )
    assert _policy(candidate.snapshot).active
    assert malformed == frozen


@pytest.mark.parametrize("count", (1, 2))
def test_real_settled_support_protects_evidence_not_compatibility_seed(
    count: int,
) -> None:
    predictive_map, evidence = _settled(count)
    _, seed = _settled(count, seeded=True)
    # PATH004: identical real observations do not promote a compatibility seed.
    assert seed.snapshot.selected_paths == evidence.snapshot.selected_paths
    assert seed.snapshot.belief_states == evidence.snapshot.belief_states
    assert _policy(seed.snapshot).activation_provenance == "restored_seed"
    assert not _policy(seed.snapshot).retained_endpoint_hold
    assert _policy(evidence.snapshot).activation_provenance == "evidence"
    for candidate, expected_active in ((evidence, True), (seed, False)):
        for continuation in (candidate, _restore(predictive_map, candidate)):
            result = _send(continuation, "room", "off", 1200)
            assert result.disposition == "duplicate"
            assert _policy(result.snapshot).active is expected_active
            assert _policy(result.snapshot).retained_endpoint_hold is expected_active
            assert _belief(result.snapshot).qualified_departure_at is None
            assert not result.snapshot.anonymous_supports
            assert not result.snapshot.traversal_tokens
            paths = tuple(p for p in result.snapshot.selected_paths if p is not None)
            assert len(paths) == 1 and paths[0].visits[-1].node_id == "room"
            assert not result.authorizations
            assert [e.kind for e in result.policy_events if e.zone == "room"] == (
                [] if expected_active else ["released"]
            )
            _restore(predictive_map, continuation)


@pytest.mark.parametrize("count", (1, 2))
def test_legacy_settled_support_protects_evidence_not_compatibility_seed(
    count: int,
) -> None:
    """E/L: same original 0/1/2/4/5/7 observations and 20/1200 boundaries."""
    predictive_map, evidence = _settled_components(count)
    _, seed = _settled_components(count, seeded=True)
    assert seed.snapshot.anonymous_supports == evidence.snapshot.anonymous_supports
    assert seed.snapshot.belief_states == evidence.snapshot.belief_states
    assert _policy(seed.snapshot).activation_provenance == "restored_seed"
    assert not _policy(seed.snapshot).retained_endpoint_hold
    assert _policy(evidence.snapshot).activation_provenance == "evidence"
    for candidate, expected_active in ((evidence, True), (seed, False)):
        for continuation in (candidate, _restore_component(predictive_map, candidate)):
            before = _belief(continuation.snapshot)
            result = _send(continuation, "room", "off", 1200)
            assert result.disposition == "duplicate"
            belief = continuation.filters["room"]
            crossing = belief.threshold_crossed_at(
                before, POLICY_CALIBRATIONS["stay_pir"].off_threshold, _at(1200),
            )
            assert crossing is not None
            support, = continuation.supports.supports
            assert support.state == "settled" and support.current_zone == "room"
            update = continuation.policies["room"].evaluate(
                _at(1200), before, belief.state,
                local_state=None, local_effect=None, authorization=None,
                below_threshold_since=crossing,
                retained_endpoint_hold=True,
            )
            assert update.state.active is expected_active
            assert update.state.retained_endpoint_hold is expected_active
            assert belief.state.qualified_departure_at is None
            assert not result.authorizations
            assert ([] if update.event is None else [update.event.kind]) == (
                [] if expected_active else ["released"]
            )
            _restore_component(predictive_map, continuation)


def test_prospective_hold_blocks_nested_count_zero_until_support_commit() -> None:
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, 1, START)
    _send(engine, "source", "on", 0)
    _send(engine, "hall", "on", 1)
    callbacks: list[ZoneModelSnapshot] = []

    def publish(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "room" and event.kind == "acquired"
        assert decision.active_after and authorization is not None
        before = engine.snapshot
        assert _policy(before).retained_endpoint_hold
        # O/S: current selection is committed before external callbacks; the
        # separately retained component case owns legacy post-publication support.
        assert not before.anonymous_supports and not before.traversal_tokens
        path, = before.selected_paths
        assert path is not None and path.visits[-1].node_id == "room"
        wire = serialize_target_state(predictive_map, engine)
        frozen = deepcopy(wire)
        assert restore_target_state(
            predictive_map, wire, _at(2),
        ).snapshot == before
        assert wire == frozen
        with pytest.raises(ValueError, match="forbidden during decision callback"):
            engine.observe_count(CountInput("nested-zero", 0, True, _at(2)))
        assert engine.snapshot == before
        assert serialize_target_state(predictive_map, engine) == wire
        callbacks.append(before)

    result = engine.observe(
        SensorInput("binary_sensor.room", "on", _at(2)), decision_callback=publish,
    )
    assert len(callbacks) == 1
    assert [(e.zone, e.kind) for e in result.policy_events] == [("room", "acquired")]
    assert not result.snapshot.anonymous_supports
    assert result.snapshot.selected_paths == callbacks[0].selected_paths
    assert _policy(result.snapshot).retained_endpoint_hold
    _restore(predictive_map, engine)
    zero = engine.observe_count(CountInput("real-zero", 0, True, _at(3)))
    assert not _policy(zero.snapshot).active
    assert not zero.snapshot.anonymous_supports
    assert not zero.snapshot.selected_paths
    assert [(e.zone, e.kind) for e in zero.policy_events if e.zone == "room"] == [
        ("room", "released"),
    ]


def test_legacy_prospective_hold_publishes_before_real_support_commit() -> None:
    """O/L: actual prepare -> prospective policy -> callback -> support commit."""
    predictive_map = _map()
    components = PersistenceComponents(predictive_map, 1, START)
    _send(components, "source", "on", 0)
    _send(components, "hall", "on", 1)
    prepared = prepare_component_arrival(
        components, SensorInput("binary_sensor.room", "on", _at(2)),
    )
    assert not components.supports.supports
    support, = prepared.support.transition.supports
    assert support.state == "settled" and support.current_node_id == "room"
    callbacks: list[ZoneModelSnapshot] = []

    def publish(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "room" and event.kind == "acquired"
        assert decision.active_after and authorization == prepared.authorization
        assert _policy(components.snapshot).retained_endpoint_hold
        assert not components.supports.supports
        callbacks.append(components.snapshot)

    _, events, failure = publish_component_arrival(components, prepared, publish)
    assert failure is None and len(callbacks) == 1
    assert [(e.zone, e.kind) for e in events] == [("room", "acquired")]
    assert not components.supports.supports
    commit_component_arrival(components, prepared)
    assert components.supports.supports == (support,)
    assert _policy(components.snapshot).retained_endpoint_hold
    _restore_component(predictive_map, components)
    zero = components.observe_count(CountInput("real-zero", 0, True, _at(3)))
    assert not _policy(zero.snapshot).active and not zero.snapshot.anonymous_supports
    assert [(e.zone, e.kind) for e in zero.policy_events if e.zone == "room"] == [
        ("room", "released"),
    ]


def test_restore_rejects_stale_settled_support_after_real_unavailability() -> None:
    # E/D: legacy support invalidation is not selected-path endpoint eviction.
    predictive_map, engine = _settled_components(1)
    retained = engine.advance(_at(1200)).snapshot
    retained_payload = component_wire(predictive_map, engine)
    assert not retained.support_token_bindings
    unavailable = _send(engine, "room", "unavailable", 1201).snapshot
    assert not unavailable.anonymous_supports
    assert not _policy(unavailable).retained_endpoint_hold
    receiver = _restore_component(predictive_map, engine)
    # Simulate a torn persisted support component. Every other component is the
    # genuine post-unavailability state; a valid old endpoint cannot override it.
    malformed = replace(unavailable, anonymous_supports=retained.anonymous_supports)
    validator = SnapshotValidator(
        predictive_map, engine.nodes, engine.supports._confirmed_strength,
    )
    validator.validate(unavailable)
    with pytest.raises(ValueError, match="^Settled anonymous support is incompatible$"):
        validator.validate(malformed)
    payload = component_wire(predictive_map, engine)
    raw = cast(dict[str, object], payload["snapshot"])
    old_raw = cast(dict[str, object], retained_payload["snapshot"])
    # Use the exact retained1200 support, not a reconstructed scalar/identifier.
    raw["anonymous_supports"] = old_raw["anonymous_supports"]
    assert decode_component_snapshot(raw) == malformed
    frozen = deepcopy(payload)
    receiver_before = component_wire(predictive_map, receiver)
    with pytest.raises(ValueError, match="^Settled anonymous support is incompatible$"):
        receiver = restore_components(predictive_map, payload, _at(1201))
    assert payload == frozen
    assert component_wire(predictive_map, receiver) == receiver_before
    assert engine.snapshot == unavailable
    assert receiver.advance(_at(1300)).snapshot == engine.advance(_at(1300)).snapshot
    _restore_component(predictive_map, engine)


def test_current_selected_unavailable_endpoint_retains_but_rejects_torn_support(
) -> None:
    """PATH002/STATE: unavailable withdraws branch authority, not occupancy."""
    predictive_map, engine = _settled(1)
    retained = engine.advance(_at(1200)).snapshot
    unavailable = _send(engine, "room", "unavailable", 1201).snapshot
    path, = retained.selected_paths
    assert path is not None and path.endpoint_eligible
    assert unavailable.selected_paths == (replace(path, endpoint_eligible=False),)
    assert _belief(unavailable).context == "unavailable"
    assert _policy(unavailable).active and _policy(unavailable).retained_endpoint_hold
    assert not unavailable.anonymous_supports
    receiver = _restore(predictive_map, engine)
    _, legacy = _settled_components(1)
    legacy.advance(_at(1200))
    payload = serialize_target_state(predictive_map, engine)
    raw = cast(dict[str, object], payload["snapshot"])
    legacy_raw = cast(
        dict[str, object], component_wire(predictive_map, legacy)["snapshot"],
    )
    raw["anonymous_supports"] = legacy_raw["anonymous_supports"]
    frozen = deepcopy(payload)
    receiver_before = serialize_target_state(predictive_map, receiver)
    with pytest.raises(ValueError, match="^Settled anonymous support is incompatible$"):
        receiver = restore_target_state(predictive_map, payload, _at(1201))
    assert payload == frozen
    assert serialize_target_state(predictive_map, receiver) == receiver_before
    assert receiver.advance(_at(1300)).snapshot == engine.advance(_at(1300)).snapshot
    assert _policy(receiver.snapshot).active
    _restore(predictive_map, receiver)


@pytest.mark.parametrize("weak_first", (False, True))
def test_expired_qualification_cleans_up_without_shortening_or_renewing_weak_outward(
    weak_first: bool,
) -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    filter_ = ZoneBeliefFilter("room", profile, START)
    filter_.apply_positive("room:1", START)
    registrations = [(False, _at(60)), (True, _at(20))]
    if not weak_first:
        registrations.reverse()
    for index, (qualified, deadline) in enumerate(registrations, start=1):
        filter_.register_outward("room:1", deadline, _at(index), qualified=qualified)
    saved = filter_.state
    assert saved.outward_context == OutwardContext("room:1", _at(60), _at(20))
    weak = ZoneBeliefFilter.restore(profile, replace(
        saved, outward_context=OutwardContext("room:1", _at(60)),
    ))
    just_before = filter_.advance(_at(20) - EPSILON)
    assert just_before.outward_context == saved.outward_context
    for candidate in (filter_, ZoneBeliefFilter.restore(profile, saved)):
        expired = candidate.advance(_at(20))
        assert expired.outward_context == OutwardContext("room:1", _at(60))
        assert expired.qualified_departure_at is None
        assert candidate.advance(_at(20)) == expired
        candidate = ZoneBeliefFilter.restore(profile, expired)
        extended = candidate.register_outward("room:1", _at(120), _at(21))
        assert extended.outward_context == OutwardContext("room:1", _at(120))
        cleared = candidate.apply_stable_clear("room:1", _at(30))
        assert cleared.context == "cleared_with_outward"
        assert cleared.qualified_departure_at is None
        assert cleared.outward_context is None
        control = ZoneBeliefFilter.restore(profile, weak.state)
        control.advance(_at(20))
        control.register_outward("room:1", _at(120), _at(21))
        expected = control.apply_stable_clear("room:1", _at(30))
        assert cleared.probability == pytest.approx(expected.probability, abs=1e-12)
        assert all(
            c.kind in {"local_positive", "elapsed_decay", "stable_clear"}
            for c in cleared.contributions
        ), "Qualification expiry must not manufacture an observation"


@pytest.mark.parametrize("value", (None, 0, 1, "true"))
def test_outward_qualification_requires_boolean_before_any_filter_mutation(
    value: object,
) -> None:
    filter_ = ZoneBeliefFilter("room", BELIEF_PROFILES["stay_pir"], START)
    filter_.apply_positive("room:1", START)
    before = filter_.state
    with pytest.raises(ValueError, match="Outward qualification must be boolean"):
        filter_.register_outward(
            "room:1", _at(20), _at(10), qualified=cast(bool, value),
        )
    assert filter_.state == before
