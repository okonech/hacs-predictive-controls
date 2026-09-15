"""Public PATH001..005 retention/departure and isolated POLICY013/STATE005/010.

Marked runtime scenarios use observed inputs, registered timers and public active
edges only, with opaque JSON continuation. Section16/REQ-GOV-005 (2026-09-13)
amends only the two named single-path branch outcomes, not their original inputs.
The synthetic convergence case independently qualifies same-room multiplicity.
Legacy supports/outward records come from real isolated components. Historical
defaults never feed incomplete selected-engine state. Current missing-field
checks use accepted complete snapshots with a declared component outward donor.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import (
    ZoneBeliefFilter,
    probability_to_log_odds,
)
from custom_components.predictive_controls.zone_model.persistence import (
    _decode_snapshot,
    _json_value,
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    ZonePolicy,
)
from custom_components.predictive_controls.zone_model.prediction import (
    LEASE_DURATION,
    MATURITY_PROBABILITY,
    MATURITY_SUPPORT,
    PredictionLease,
)
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    OutwardContext,
    SensorInput,
    ZoneBeliefState,
    ZoneModelSnapshot,
    ZonePolicyState,
)
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    decode_component_snapshot,
    restore_components,
)
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario

pytestmark = pytest.mark.target_model
NOW = datetime(2026, 9, 1, tzinfo=UTC)
EPSILON = timedelta(microseconds=1)


def _at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _map(*, presence: bool = False, branch: bool = False) -> PredictiveMap:
    """Three physical nodes, plus an optional sibling branch off the hallway."""
    nodes: dict[str, object] = {
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
            "adjacent": ["source", "room", *(["hall2"] if branch else [])],
        },
        "room": {
            "role": "room_occupancy",
            "occupancy_behavior": "sustained",
            "entities": {"mmwave" if presence else "motion": "binary_sensor.room"},
            "adjacent": ["hall"],
        },
    }
    if branch:
        nodes["hall2"] = {
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.hall2"},
            "adjacent": ["hall"],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


def _belief(snapshot: ZoneModelSnapshot) -> ZoneBeliefState:
    return next(state for state in snapshot.belief_states if state.zone == "room")


def _endpoint(snapshot: ZoneModelSnapshot) -> AnonymousOccupancySupport:
    matches = tuple(
        support for support in snapshot.anonymous_supports
        if support.current_node_id == "room" and support.state == "settled"
    )
    assert len(matches) == 1, "This repair protects settled, not supportless, zones"
    return matches[0]


def _settle(components: PersistenceComponents) -> AnonymousOccupancySupport:
    """L: original observations qualify actual legacy traversal/support records."""
    components.observe(SensorInput("binary_sensor.source", "on", _at(0)))
    components.observe(SensorInput("binary_sensor.hall", "on", _at(1)))
    result = components.observe(SensorInput("binary_sensor.room", "on", _at(2)))
    support = _endpoint(result.snapshot)
    assert support.path_node_ids == ("source", "hall", "room")
    assert support.valid_until is None
    assert [(e.zone, e.kind, e.event_at) for e in result.policy_events] == [
        ("room", "acquired", _at(2)),
    ]
    return support


def _clear_all(replay: RuntimeReplay, *, branch: bool = False) -> None:
    # Clear transition sensors well before their health horizons. No synthetic
    # warnings or timeout invalidation may masquerade as endpoint departure.
    replay.send("binary_sensor.source", "off", _at(4))
    replay.send("binary_sensor.hall", "off", _at(5))
    if branch:
        replay.send("binary_sensor.hall2", "off", _at(6))
    replay.send("binary_sensor.room", "off", _at(7))
    replay.advance(_at(20))


def _weak_branch(components: PersistenceComponents) -> AnonymousOccupancySupport:
    support = _settle(components)
    result = components.observe(SensorInput("binary_sensor.hall2", "on", _at(3)))
    assert any(e.zone == "hall2" and e.kind == "acquired" for e in result.policy_events)
    snapshot = result.snapshot
    target = next(
        token for token in snapshot.traversal_tokens if token.node_id == "hall2"
    )
    # The still-current hallway wins the selected path. Room is merely linked
    # through that hallway's earlier authorization, not an on-path predecessor.
    assert target.path_node_ids == ("source", "hall", "hall2")
    assert _endpoint(snapshot) == support
    outward = _belief(snapshot).outward_context
    assert outward is not None, "Exercise real linked outward, not no outward"
    assert outward.qualified_until is None
    return support


def _current_outward_checkpoint(
    replay: RuntimeReplay, components: PersistenceComponents,
) -> dict[str, object]:
    """D: accepted structural composite, NOT selected-engine outward production.

    Both branches observed source0/hall1/room2/hall2at3. The current engine has
    displacement but no legacy outward. Donate only the actual component record;
    keep all current selection, physical health/holds, policy, audit/prediction.
    """
    current = replay.inference_snapshot()
    donor = _belief(components.snapshot)
    belief = _belief(current)
    assert belief.generation_episode_id == donor.generation_episode_id
    assert belief.log_odds == donor.log_odds
    assert belief.contributions == donor.contributions
    assert belief.outward_context is None and donor.outward_context is not None
    assert donor.outward_context.qualified_until is None
    assert belief.path_displaced_at == _at(3)
    payload = deepcopy(replay.checkpoint())
    row = next(row for row in _rows(payload, "belief_states") if row["zone"] == "room")
    row["outward_context"] = _json_value(asdict(donor.outward_context))
    frozen = deepcopy(payload)
    restored = restore_target_state(replay.map, payload, _at(3))
    expected = replace(current, belief_states=tuple(
        replace(item, outward_context=donor.outward_context)
        if item.zone == "room" else item for item in current.belief_states
    ))
    assert restored.snapshot == expected
    assert serialize_target_state(replay.map, restored) == payload
    assert payload == frozen
    return payload


def _continue_current_reader(
    receiver: ZoneModelEngine, control: ZoneModelEngine,
) -> None:
    """A rejected load must leave nonempty inference usable on original clears."""
    if receiver.snapshot.updated_at == _at(3):
        for node, seconds in (("source", 4), ("hall", 5), ("hall2", 6), ("room", 7)):
            event = SensorInput(f"binary_sensor.{node}", "off", _at(seconds))
            assert receiver.observe(event) == control.observe(event)
        assert receiver.advance(_at(20)) == control.advance(_at(20))
    assert receiver.advance(_at(1200)) == control.advance(_at(1200))
    assert receiver.audit_rows == control.audit_rows
    assert (
        receiver.prediction_manager.serialize()
        == control.prediction_manager.serialize()
    )


def _observe_route(replay: RuntimeReplay) -> None:
    """Original three inputs; public acquisition replaces legacy support premises."""
    replay.send("binary_sensor.source", "on", _at(0))
    replay.send("binary_sensor.hall", "on", _at(1))
    assert replay.send("binary_sensor.room", "on", _at(2)).active("room")
    assert replay.input_edges_for("room") == (ActiveEdge(_at(2), "room", True),)
    assert replay.edges_for("room") == (ActiveEdge(_at(2), "room", True),)


def _observe_branch(replay: RuntimeReplay) -> None:
    """One observed route plus U at N2, never two independently observed paths."""
    _observe_route(replay)
    assert replay.send("binary_sensor.hall2", "on", _at(3)).active("hall2")
    assert replay.input_edges_for("hall2") == (ActiveEdge(_at(3), "hall2", True),)


@pytest.mark.scenario
@pytest.mark.parametrize(("presence", "count"), ((False, 1), (True, 2)))
def test_runtime_healthy_clear_retains_endpoint_for_24h_after_token_expiry(
    presence: bool, count: int,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(presence=presence), count)
        _observe_route(replay)
        _clear_all(replay)
        inputs = tuple(replay.normalized_inputs)

        assert replay.advance(NOW + timedelta(hours=24)).active("room")
        assert replay.edges_for("room") == (ActiveEdge(_at(2), "room", True),)
        assert tuple(replay.normalized_inputs) == inputs
        # Timer execution, rather than one fixture engine.advance(), is essential.
        assert any(
            at > NOW + timedelta(hours=23)
            for at, _ in scenario.clock.executions
        )


@pytest.mark.scenario
@pytest.mark.parametrize("count_state", ("0", "unknown", "unavailable"))
def test_runtime_count_zero_releases_but_invalid_count_preserves_retention(
    count_state: str,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(), 2)
        _observe_route(replay)
        _clear_all(replay)
        at = NOW + timedelta(minutes=20)
        assert replay.advance(at).active("room")

        view = replay.send("sensor.replay_people", count_state, at)
        delivery = replay.deliveries[-1]
        assert delivery.delivered and delivery.is_count
        assert delivery.raw_state == count_state
        assert delivery.callback_at == delivery.processing_at == at
        if count_state == "0":
            assert not view.active("room")
            assert replay.edges_for("room") == (
                ActiveEdge(_at(2), "room", True), ActiveEdge(at, "room", False),
            )
        else:
            assert view.active("room")
            assert replay.advance(at + timedelta(hours=1)).active("room")
            assert replay.edges_for("room") == (ActiveEdge(_at(2), "room", True),)


@pytest.mark.scenario
def test_runtime_persisted_low_belief_hold_roundtrips_public_continuation() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(_map(), 1)
        restored = scenario.create(_map(), 1)
        _observe_route(live)
        _clear_all(live)
        at = NOW + timedelta(minutes=20)
        assert live.advance(at).active("room")
        # Preserve the originally empty restore branch: public OFF -> later ON
        # proves this is not a no-op restore into an already identical runtime.
        assert not restored.view().active("room")
        inputs = tuple(live.normalized_inputs)
        payload = json.loads(json.dumps(live.checkpoint()))
        unmodified = deepcopy(payload)

        restored.restore(payload)
        assert payload == unmodified
        live.advance(at + timedelta(hours=1))
        assert live.view() == restored.view()
        assert live.view().active("room")
        assert live.edges_for("room") == (ActiveEdge(_at(2), "room", True),)
        assert not any(not edge.active for edge in restored.edges_for("room"))
        assert tuple(live.normalized_inputs) == inputs
        assert not restored.deliveries and not restored.normalized_inputs


@pytest.mark.scenario
def test_runtime_single_path_branch_releases_former_room() -> None:
    """Approved replacement for off_path_linked_outward_cannot_release_settled_endpoint.

    PATH002/004: source0/hall1/room2/hall2at3 is one path plus U, not overlap.
    The original OFF4..7 inputs remain; branch displacement permits public OFF95.
    """
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(branch=True), 2)
        _observe_branch(replay)
        _clear_all(replay, branch=True)
        inputs = tuple(replay.normalized_inputs)
        release_at = _at(95)
        assert replay.advance(release_at - EPSILON).active("room")
        assert not replay.advance(release_at).active("room")
        assert not replay.advance(NOW + timedelta(hours=1)).active("room")
        assert replay.edges_for("room") == (
            ActiveEdge(_at(2), "room", True), ActiveEdge(release_at, "room", False),
        )
        assert tuple(replay.normalized_inputs) == inputs


@pytest.mark.scenario
def test_runtime_hall_reassertion_does_not_delay_branch_release() -> None:
    """Approved replacement of the legacy causal-transfer/full-dwell scenario.

    PATH002/004: preserve the original route, clears and hallON85. That reassertion
    does not restart a full legacy support-transfer dwell; room still releases95.
    """
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(branch=True), 2)
        _observe_branch(replay)
        _clear_all(replay, branch=True)
        assert replay.advance(_at(50)).active("room")
        departure_at = _at(85)
        assert replay.advance(departure_at).active("room")
        assert replay.send("binary_sensor.hall", "on", departure_at).active("room")
        inputs = tuple(replay.normalized_inputs)
        deadline = _at(95)
        assert replay.advance(deadline - EPSILON).active("room")
        assert not replay.advance(deadline).active("room")
        assert not replay.advance(_at(115)).active("room")
        assert replay.edges_for("room") == (
            ActiveEdge(_at(2), "room", True), ActiveEdge(deadline, "room", False),
        )
        assert tuple(replay.normalized_inputs) == inputs


@pytest.mark.scenario
def test_runtime_untracked_positive_does_not_gain_endpoint_hold_or_activation() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(), 1)
        assert not replay.send("binary_sensor.room", "on", NOW).active("room")
        replay.send("binary_sensor.room", "off", _at(7))
        assert not replay.advance(NOW + timedelta(hours=1)).active("room")
        assert not replay.edges_for("room")


def _convergence_map() -> PredictiveMap:
    """Synthetic original-role graph plus independent x-y-room and hall-f-g-room."""
    adjacency = {
        "source": ["hall"],
        "hall": ["source", "room", "hall2", "f"],
        "room": ["hall", "y", "g"],
        "hall2": ["hall"],
        "x": ["y"],
        "y": ["x", "room"],
        "f": ["hall", "g"],
        "g": ["f", "room"],
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": "room_occupancy" if node == "room" else "transition_gate",
                "occupancy_behavior": "sustained" if node == "room" else "transient",
                "entities": {"motion": f"binary_sensor.{node}"},
                "adjacent": neighbors,
            }
            for node, neighbors in adjacency.items()
        },
    })


@pytest.mark.scenario
@pytest.mark.parametrize(("count", "second_approach", "release_seconds"), (
    pytest.param(2, True, None, id="two-converged-paths-retain"),
    pytest.param(1, True, 115, id="one-slot-same-inputs-release"),
    pytest.param(2, False, 110, id="two-slots-without-second-approach-release"),
))
def test_runtime_converged_paths_retain_room_after_one_continues(
    count: int, second_approach: bool, release_seconds: int | None,
) -> None:
    """Synthetic PATH001/002/004 and PATH-STATE001 multiplicity/restore proof.

    Independent source-hall and x-y observations precede room4. The still-open
    hallway approach continues through f20/g21 to room22, then hall/hall2. HallON23
    is deliberately a duplicate level, not an invented independent crossing.
    All eight physical witnesses are OFF25..32. At N2 both approaches must leave
    one room endpoint after the other continues; N1 and N2 without x/y must OFF.
    These are public timelines, not inferred identities or private-state seeds.
    """
    prefix: tuple[tuple[str, str, int], ...] = (
        ("source", "on", 0), ("hall", "on", 1),
        ("x", "on", 2), ("y", "on", 3),
        ("room", "on", 4), ("room", "off", 6),
        ("f", "on", 20), ("g", "on", 21), ("room", "on", 22),
    )
    if not second_approach:
        prefix = tuple(row for row in prefix if row[0] not in {"x", "y"})
    suffix = (
        ("hall", "on", 23), ("hall2", "on", 24),
        ("source", "off", 25), ("hall", "off", 26),
        ("x", "off", 27), ("y", "off", 28),
        ("f", "off", 29), ("g", "off", 30),
        ("room", "off", 31), ("hall2", "off", 32),
    )
    expected_inputs = [
        SensorInput(f"binary_sensor.{node}", state, _at(offset))
        for node, state, offset in (*prefix, *suffix)
    ]
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(_convergence_map(), count)
        restored = scenario.create(_convergence_map(), count)
        branches = (live, restored)
        for node, state, offset in prefix:
            for replay in branches:
                replay.send(f"binary_sensor.{node}", state, _at(offset))
        assert all(replay.view().active("room") for replay in branches)
        payload = json.loads(json.dumps(live.checkpoint()))
        unmodified = deepcopy(payload)
        suffix_starts = tuple(len(replay.edges) for replay in branches)
        restored.restore(payload)
        assert payload == unmodified
        for node, state, offset in suffix:
            for replay in branches:
                replay.send(f"binary_sensor.{node}", state, _at(offset))
        if release_seconds is not None:
            live.advance(_at(release_seconds) - EPSILON)
            assert all(replay.view().active("room") for replay in branches)
            live.advance(_at(release_seconds))
            assert all(not replay.view().active("room") for replay in branches)
        live.advance(NOW + timedelta(hours=2))
        room_edges: tuple[ActiveEdge, ...] = (ActiveEdge(_at(4), "room", True),)
        if release_seconds is not None:
            room_edges += (ActiveEdge(_at(release_seconds), "room", False),)
        for replay in branches:
            assert replay.view().active("room") is (release_seconds is None)
            assert replay.edges_for("room") == room_edges
            assert replay.input_edges_for("room") == (ActiveEdge(_at(4), "room", True),)
            assert replay.normalized_inputs == expected_inputs
            assert len(replay.deliveries) == len(expected_inputs) == (
                19 if second_approach else 17
            )
            for delivery, event in zip(replay.deliveries, expected_inputs, strict=True):
                assert delivery.delivered and not delivery.is_count
                assert delivery.entity_id == event.entity_id
                assert delivery.raw_state == event.state
                assert delivery.callback_at == delivery.processing_at == event.event_at
                assert delivery.event_at == event.event_at
                assert delivery.normalized == event
                assert delivery.retained_input is None  # Native map reliability.
            last_levels = {
                delivery.entity_id: delivery.raw_state for delivery in replay.deliveries
            }
            assert last_levels == {
                f"binary_sensor.{node}": "off" for node in replay.map.nodes
            }
            if second_approach:
                for node, offset in (("hall", 1), ("y", 3)):
                    assert tuple(
                        edge for edge in replay.input_edges_for(node)
                        if edge.at == _at(offset)
                    ) == (ActiveEdge(_at(offset), node, True),)
            if count == 2:
                # Qualify the real continuing approach/output, not time-only release.
                for node, offset in (("f", 20), ("g", 21), ("hall2", 24)):
                    assert ActiveEdge(
                        _at(offset), node, True,
                    ) in replay.input_edges_for(node)
        assert live.view() == restored.view()
        assert live.edges[suffix_starts[0]:] == restored.edges[suffix_starts[1]:]


def _low_belief(
    at: datetime, *, qualified_at: datetime | None = None,
) -> ZoneBeliefState:
    return ZoneBeliefState(
        "room", "stay_pir", probability_to_log_odds(0.1), at,
        "cleared_without_outward" if qualified_at is None else "cleared_with_outward",
        generation_episode_id="room:1", qualified_departure_at=qualified_at,
    )


def _evidence_policy() -> ZonePolicy:
    """An already-acquired unit-policy input, not a fabricated engine support."""
    state = ZonePolicyState(
        "room", "stay_pir", True, NOW, phase="active",
        activation_provenance="evidence", activation_episode_id="room:1",
        activation_at=NOW, activation_reason="track_confirmed",
        activation_track_confidence="confirmed",
        activation_path_node_ids=("source", "hall", "room"),
        activation_provenance_kind="adjacent",
    )
    return ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, state=state)


@pytest.mark.parametrize("qualified", (False, True))
def test_policy_hold_cancels_old_pending_and_loss_never_backdates_protected_time(
    qualified: bool,
) -> None:
    policy = _evidence_policy()
    low = _low_belief(NOW)
    pending = policy.evaluate(
        NOW, low, low, local_state=None, local_effect=None, authorization=None,
    )
    assert pending.state.pending_release_since == NOW
    held_at = NOW + timedelta(hours=1)
    low = _low_belief(held_at)
    held = policy.evaluate(
        held_at, low, low, local_state=None, local_effect=None, authorization=None,
        below_threshold_since=NOW, retained_endpoint_hold=True,
    )
    assert held.state.active and held.event is None
    assert held.state.pending_release_since is None
    assert held.state.retained_endpoint_hold
    assert held.decision.reason == "retained_endpoint_hold"
    policy = ZonePolicy(
        "room", POLICY_CALIBRATIONS["stay_pir"], held_at, state=held.state,
    )

    lost_at = NOW + timedelta(hours=24)
    proof_at = lost_at - timedelta(seconds=10) if qualified else None
    frontier = lost_at if proof_at is None else proof_at
    low = _low_belief(lost_at, qualified_at=proof_at)
    lost = policy.evaluate(
        lost_at, low, low, local_state=None, local_effect=None, authorization=None,
        below_threshold_since=NOW, retained_endpoint_hold=False,
    )
    assert lost.state.active and lost.event is None
    assert not lost.state.retained_endpoint_hold
    assert lost.state.pending_release_since == frontier
    deadline = frontier + POLICY_CALIBRATIONS["stay_pir"].release_dwell
    for at, expected_active in ((deadline - EPSILON, True), (deadline, False)):
        low = _low_belief(at, qualified_at=proof_at)
        update = policy.evaluate(
            at, low, low, local_state=None, local_effect=None, authorization=None,
            below_threshold_since=NOW,
        )
        assert update.state.active is expected_active
        if not expected_active:
            assert update.event is not None and update.event.kind == "released"


@pytest.mark.parametrize("predicted", (False, True))
def test_policy_retention_neither_acquires_nor_extends_prediction(
    predicted: bool,
) -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    high = replace(_low_belief(NOW), log_odds=probability_to_log_odds(0.95))
    if predicted:
        lease = PredictionLease(
            "source", "hall", "room", "room", MATURITY_PROBABILITY,
            MATURITY_SUPPORT, "hall:1", NOW, NOW + LEASE_DURATION, True, "mature",
        )
        acquired = policy.apply_prediction(lease, high)
        assert acquired is not None and acquired.state.active
    update = policy.evaluate(
        NOW, high, high, local_state=None, local_effect=None, authorization=None,
        retained_endpoint_hold=True,
    )
    assert update.state.active is predicted
    assert not update.state.retained_endpoint_hold
    assert update.event is None
    if predicted:
        expiry = NOW + LEASE_DURATION
        released = policy.expire_prediction(
            expiry, replace(high, last_updated_at=expiry),
        )
        assert released is not None and not released.state.active
        assert released.event is not None and released.event.kind == "released"


def _filter() -> ZoneBeliefFilter:
    result = ZoneBeliefFilter("room", BELIEF_PROFILES["stay_pir"], NOW)
    result.apply_positive("room:1", NOW)
    return result


@pytest.mark.parametrize("weak_first", (False, True))
@pytest.mark.parametrize("clear_offset_us", (-1, 0, 1))
def test_pending_qualification_has_its_own_half_open_deadline(
    weak_first: bool, clear_offset_us: int,
) -> None:
    filter_ = _filter()
    expiry = _at(20)
    registrations: tuple[tuple[bool, datetime], ...] = (
        (False, _at(60)), (True, expiry),
    )
    if not weak_first:
        registrations = tuple(reversed(registrations))
    for index, (qualified, until) in enumerate(registrations, start=1):
        filter_.register_outward("room:1", until, _at(index), qualified=qualified)
    pending = filter_.state
    assert pending.outward_context == OutwardContext("room:1", _at(60), expiry)
    assert pending.qualified_departure_at is None
    assert filter_.register_outward("room:1", _at(60), _at(2)) == pending
    # Restore cannot turn the longer weak deadline into qualified authority.
    filter_ = ZoneBeliefFilter.restore(BELIEF_PROFILES["stay_pir"], pending)
    at = expiry + timedelta(microseconds=clear_offset_us)
    cleared = filter_.apply_stable_clear("room:1", at)
    assert cleared.context == "cleared_with_outward"  # Weak evidence still exists.
    assert cleared.outward_context is None
    assert cleared.qualified_departure_at == (at if clear_offset_us < 0 else None)
    assert filter_.apply_stable_clear("room:1", at) == cleared


def test_weak_committed_outward_upgrades_without_reapplying_evidence() -> None:
    filter_ = _filter()
    filter_.apply_stable_clear("room:1", _at(1))
    weak = filter_.register_outward("room:1", _at(60), _at(2))
    assert weak.context == "cleared_with_outward"
    assert weak.qualified_departure_at is None
    qualified = filter_.register_outward("room:1", _at(20), _at(2), qualified=True)
    assert qualified.qualified_departure_at == _at(2)
    assert qualified.outward_context is None
    assert qualified.log_odds == weak.log_odds
    assert qualified.contributions == weak.contributions
    # Later genuine proofs may not postpone an already-committed departure.
    later = filter_.register_outward("room:1", _at(120), _at(3), qualified=True)
    assert later.qualified_departure_at == _at(2)
    assert filter_.advance(_at(121)).qualified_departure_at == _at(2)


def test_qualified_stable_clear_commits_once_and_survives_expiry_and_restore() -> None:
    filter_ = _filter()
    filter_.register_outward("room:1", _at(20), _at(1), qualified=True)
    saved = filter_.state
    coarse = ZoneBeliefFilter.restore(BELIEF_PROFILES["stay_pir"], saved)
    fine = ZoneBeliefFilter.restore(BELIEF_PROFILES["stay_pir"], saved)
    for candidate in (coarse, fine):
        committed = candidate.apply_stable_clear("room:1", _at(10))
        assert committed.qualified_departure_at == _at(10)
        assert committed.outward_context is None
    fine.advance(_at(19))
    fine = ZoneBeliefFilter.restore(
        BELIEF_PROFILES["stay_pir"], fine.state, restore_at=_at(20),
    )
    fine.advance(_at(60))
    final_at = NOW + timedelta(hours=24)
    coarse.advance(final_at)
    fine.advance(final_at)
    assert coarse.state.context == fine.state.context == "cleared_with_outward"
    assert (
        coarse.state.qualified_departure_at
        == fine.state.qualified_departure_at == _at(10)
    )
    assert coarse.state.probability == pytest.approx(fine.state.probability, abs=1e-12)
    assert not coarse.state.outward_context and not fine.state.outward_context


@pytest.mark.parametrize("operation", (
    "positive", "correlated", "interaction", "reselect", "unavailable",
    "count_zero", "supersede", "availability_episode", "availability_no_episode",
))
def test_generation_and_context_resets_remove_pending_and_committed_qualification(
    operation: str,
) -> None:
    for committed in (False, True):
        filter_ = _filter()
        filter_.register_outward("room:1", _at(20), _at(1), qualified=True)
        if committed:
            filter_.apply_stable_clear("room:1", _at(2))
            assert filter_.state.qualified_departure_at == _at(2)
        else:
            outward = filter_.state.outward_context
            assert outward is not None and outward.qualified_until == _at(20)
        at = _at(3)
        if operation == "positive":
            state = filter_.apply_positive("room:2", at)
        elif operation == "correlated":
            state = filter_.apply_correlated_positive("room:2", at)
        elif operation == "interaction":
            state = filter_.apply_interaction("room:2", at)
        elif operation == "reselect":
            before = filter_.advance(at)
            state = filter_.reselect_asserted_context("room:2", at)
            assert state.log_odds == before.log_odds
            assert state.contributions == before.contributions
            assert filter_.reselect_asserted_context("room:2", at) == state
        elif operation == "unavailable":
            state = filter_.apply_unavailable(at)
            assert filter_.apply_unavailable(at) == state
        elif operation == "count_zero":
            state = filter_.apply_empty_baseline(at)
            assert state.generation_episode_id is None
        elif operation == "supersede":
            state = filter_.supersede_outward("room:1", at)
            assert filter_.supersede_outward("room:1", at) == state
        else:
            filter_.apply_unavailable(at)
            episode_id = "room:1" if operation == "availability_episode" else None
            state = filter_.apply_availability_clear(episode_id, at)
            assert state.context == "cleared_without_outward"
            assert filter_.apply_availability_clear(episode_id, at) == state
        assert state.qualified_departure_at is None
        assert state.outward_context is None
        if operation in {"positive", "correlated", "interaction", "reselect"}:
            assert state.generation_episode_id == "room:2"
            assert state.context == "asserted"
            cleared = filter_.apply_stable_clear("room:2", _at(4))
            assert cleared.context == "cleared_without_outward"
            assert cleared.qualified_departure_at is None
        else:
            assert state.context != "cleared_with_outward"


def _rows(payload: dict[str, object], field: str) -> list[dict[str, object]]:
    snapshot = cast(dict[str, object], payload["snapshot"])
    return cast(list[dict[str, object]], snapshot[field])


@pytest.mark.parametrize("missing", (
    "retained_endpoint_hold", "qualified_departure_at", "qualified_until",
))
def test_current_restore_rejects_missing_retention_fields_atomically(
    missing: str,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(branch=True), 2)
        _observe_branch(replay)
        public_before = replay.checkpoint()
        components = PersistenceComponents(replay.map, 2, NOW)
        _weak_branch(components)
        component_payload = component_wire(replay.map, components)
        assert (
            decode_component_snapshot(component_payload["snapshot"])
            == components.snapshot
        )
        assert restore_components(
            replay.map, component_payload, _at(3),
        ).snapshot == components.snapshot
        original = _current_outward_checkpoint(replay, components)
        receiver = restore_target_state(replay.map, original, scenario.clock.now)
        control = restore_target_state(replay.map, original, scenario.clock.now)
        assert any(state.active for state in receiver.snapshot.policy_states)
        receiver_before = serialize_target_state(replay.map, receiver)
        malformed = deepcopy(original)
        if missing == "retained_endpoint_hold":
            row = next(
                row for row in _rows(malformed, "policy_states")
                if row["zone"] == "room"
            )
        else:
            row = next(
                row for row in _rows(malformed, "belief_states")
                if row["zone"] == "room"
            )
            if missing == "qualified_until":
                row = cast(dict[str, object], row["outward_context"])
        assert missing in row, "Current writer must emit explicit nullable fields"
        del row[missing]
        before = deepcopy(malformed)
        message = {
            "retained_endpoint_hold": "Target retained_endpoint_hold must be boolean",
            "qualified_departure_at": (
                "Target belief qualified departure field is missing"
            ),
            "qualified_until": "Target outward qualification field is missing",
        }[missing]
        with pytest.raises(ValueError, match=f"^{message}$"):
            receiver = restore_target_state(replay.map, malformed, scenario.clock.now)
        assert malformed == before
        assert serialize_target_state(replay.map, receiver) == receiver_before
        assert replay.checkpoint() == public_before
        assert replay.view().active("room")
        _continue_current_reader(receiver, control)
        assert malformed == before


def test_historical_decoders_default_empty_without_inventing_departure() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(_map(branch=True), 2)
        _observe_branch(replay)
        components = PersistenceComponents(replay.map, 2, NOW)
        _weak_branch(components)
        # Test both an actual pending weak record (so qualified_until is really
        # removed) and the original committed weak-outward20 state after clears.
        pending_component = component_wire(replay.map, components)
        pending_current = _current_outward_checkpoint(replay, components)
        _clear_all(replay, branch=True)
        for node, seconds in (("source", 4), ("hall", 5), ("hall2", 6), ("room", 7)):
            components.observe(SensorInput(
                f"binary_sensor.{node}", "off", _at(seconds),
            ))
        components.advance(_at(20))
        assert _belief(components.snapshot).context == "cleared_with_outward"
        assert _belief(components.snapshot).qualified_departure_at is None
        public_before = replay.checkpoint()
        for original, current, frontier in (
            (pending_component, pending_current, _at(3)),
            (component_wire(replay.map, components), public_before, _at(20)),
        ):
            baseline = decode_component_snapshot(original["snapshot"])
            restored = restore_components(replay.map, original, frontier)
            assert restored.snapshot == baseline
            historical = deepcopy(original)
            for row in _rows(historical, "policy_states"):
                row.pop("retained_endpoint_hold")
            for row in _rows(historical, "belief_states"):
                row.pop("qualified_departure_at")
                outward = row["outward_context"]
                if outward is not None:
                    cast(dict[str, object], outward).pop("qualified_until")
            frozen = deepcopy(historical)
            for legacy_v3, pre_feature_v4 in ((True, False), (False, True)):
                decoded = _decode_snapshot(
                    historical["snapshot"], legacy_v3=legacy_v3,
                    pre_feature_v4=pre_feature_v4,
                )
                assert _belief(decoded).context == (
                    "asserted" if frontier == _at(3) else "cleared_with_outward"
                )
                # Defaults may not erase genuine weak source/deadline evidence.
                assert (
                    _belief(decoded).outward_context
                    == _belief(baseline).outward_context
                )
                if frontier == _at(3):
                    assert _belief(decoded).outward_context is not None
                else:
                    assert _belief(decoded).outward_context is None
                assert all(
                    s.qualified_departure_at is None for s in decoded.belief_states
                )
                assert all(not s.retained_endpoint_hold for s in decoded.policy_states)
                assert all(
                    s.outward_context is None
                    or s.outward_context.qualified_until is None
                    for s in decoded.belief_states
                )
                assert decoded.anonymous_supports == (
                    () if legacy_v3 else baseline.anonymous_supports
                )
            with pytest.raises(
                ValueError,
                match="^Target belief qualified departure field is missing$",
            ):
                restored = restore_components(replay.map, historical, frontier)
            assert historical == frozen
            assert component_wire(replay.map, restored) == original
            component_control = restore_components(replay.map, original, frontier)
            assert restored.advance(_at(1200)) == component_control.advance(_at(1200))

            # Independently mutate the accepted CURRENT envelope. The component
            # specimen must not fail at a schema/selected-ledger guard instead.
            receiver = restore_target_state(replay.map, current, frontier)
            control = restore_target_state(replay.map, current, frontier)
            receiver_before = serialize_target_state(replay.map, receiver)
            malformed = deepcopy(current)
            for row in _rows(malformed, "policy_states"):
                row.pop("retained_endpoint_hold")
            for row in _rows(malformed, "belief_states"):
                row.pop("qualified_departure_at")
                outward = row["outward_context"]
                if outward is not None:
                    cast(dict[str, object], outward).pop("qualified_until")
            frozen_current = deepcopy(malformed)
            with pytest.raises(
                ValueError,
                match="^Target belief qualified departure field is missing$",
            ):
                receiver = restore_target_state(replay.map, malformed, frontier)
            assert malformed == frozen_current
            assert serialize_target_state(replay.map, receiver) == receiver_before
            _continue_current_reader(receiver, control)
        assert replay.checkpoint() == public_before


@pytest.mark.parametrize("malformation", (
    "future", "naive", "wrong_context", "missing_generation", "outward_deadline",
))
def test_qualification_state_rejects_malformed_time_or_generation(
    malformation: str,
) -> None:
    valid = _low_belief(_at(10), qualified_at=_at(5))
    with pytest.raises(ValueError):
        if malformation == "future":
            replace(valid, qualified_departure_at=_at(11))
        elif malformation == "naive":
            replace(valid, qualified_departure_at=_at(5).replace(tzinfo=None))
        elif malformation == "wrong_context":
            replace(valid, context="cleared_without_outward")
        elif malformation == "missing_generation":
            replace(valid, generation_episode_id=None)
        else:
            OutwardContext("room:1", _at(10), qualified_until=_at(10) + EPSILON)


def test_policy_hold_rejects_nonboolean_pending_or_nonevidence_state() -> None:
    state = _evidence_policy().state
    with pytest.raises(ValueError):
        replace(state, retained_endpoint_hold=cast(bool, "true"))
    with pytest.raises(ValueError):
        replace(state, retained_endpoint_hold=True, pending_release_since=NOW)
    with pytest.raises(ValueError):
        ZonePolicyState("room", "stay_pir", False, NOW, retained_endpoint_hold=True)
    low = _low_belief(NOW)
    with pytest.raises(ValueError):
        _evidence_policy().evaluate(
            NOW, low, low, local_state=None, local_effect=None, authorization=None,
            retained_endpoint_hold=cast(bool, 1),
        )
