"""User request: complete engine contracts and repair the reproduced T38 failure.

Expected: strictly accepted correlated fallback completes and continues consistently.
Observed: token cleanup raised before support preparation, leaving physical38/model37.
Source: 2026-09-14 independent source/probe reviews supplied with the engine task.
Scope: synthetic component/current composites and public engine outcomes, NOT a
captured physical-light incident. All original tests and scenarios remain frozen.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import OccupancyTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.prediction import (
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedSource,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
)
from tests.engine_completion_fixture import (
    at,
    bootstrap_pair,
    chain,
    compose,
    correlated_ready,
    donate_frontier,
    event,
    graph,
    roundtrip,
    snapshot_payload,
)
from tests.persistence_component_fixture import PersistenceComponents
from tests.test_prediction import NOW
from tests.test_selected_prediction import graph as prediction_graph
from tests.test_selected_prediction import prepared
from tests.test_zone_model_engine import target_map
from tests.test_zone_model_persistence import structural_payload

pytestmark = pytest.mark.target_model


def test_correlated_fallback_completes_and_continues() -> None:
    """TRAV014: successful strict T38 observation, not an expected-exception test."""
    predictive_map, engine = correlated_ready()
    before = engine.snapshot
    c_token, = (token for token in before.traversal_tokens
                if token.node_id == "c" and token.accepted_at == at(36))
    binding, = (item for item in before.support_token_bindings
                if item.token_id == c_token.token_id)
    support, = (item for item in before.anonymous_supports
                if item.support_id == binding.support_id)
    assert c_token.accepted_at >= support.updated_at
    assert "c" in engine._selected_paths.covered_nodes
    assert any(path is not None and path.endpoint.node_id == "c"
               and path.endpoint.episode_id != c_token.episode_id
               and not path.endpoint_eligible for path in before.selected_paths)
    old_t = next(state for state in before.episode_states if state.node_id == "t")
    assert old_t.status == "clear" and old_t.profile_name == "stay_presence"
    assert not engine._pending_prediction_learning
    counts = engine.prediction_manager.chain.counts
    debt = engine.prediction_state["deferred_counts"]
    publications: list[ZoneModelResult] = []

    def published(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        assert result.snapshot.updated_at == at(38)
        roundtrip(predictive_map, engine)
        publications.append(result)

    result = engine.observe(event("t", "on", 38), result_callback=published)
    assert publications == [result]
    assert result.disposition == "accepted_correlated_positive"
    authorization, = result.authorizations
    assert authorization.reason == "adjacent_authorized"
    assert authorization.track_confidence == "confirmed"
    assert authorization.path_node_ids == ("z", "c", "t")
    assert c_token in authorization.source_tokens
    t_token, = (token for token in result.snapshot.traversal_tokens
                if token.node_id == "t")
    assert t_token.episode_id == authorization.target_episode_id
    assert t_token.accepted_at == at(38) and t_token.valid_until == at(218)
    assert result.snapshot.selected_paths == before.selected_paths
    moved, = (item for item in result.snapshot.anonymous_supports
              if item.support_id == support.support_id)
    assert moved.current_node_id == "t" and moved.created_at == support.created_at
    assert len(result.snapshot.anonymous_supports) <= len(before.anonymous_supports)
    assert next(p for p in result.snapshot.policy_states if p.zone == "t").active
    assert [(p.zone, p.kind) for p in result.policy_events] == [("t", "acquired")]
    assert not engine._pending_prediction_learning
    assert engine.prediction_manager.chain.counts == counts
    assert engine.prediction_state["deferred_counts"] == debt
    assert all(lease.source_episode_id != t_token.episode_id
               for lease in engine.prediction_manager.leases)
    restored = roundtrip(predictive_map, engine)
    continuation = engine.observe(event("u", "on", 39))
    assert continuation == restored.observe(event("u", "on", 39))
    onward, = continuation.authorizations
    assert t_token in onward.source_tokens
    assert next(p for p in continuation.snapshot.policy_states if p.zone == "u").active
    assert next(s for s in continuation.snapshot.anonymous_supports
                if s.support_id == support.support_id).current_node_id == "u"
    roundtrip(predictive_map, engine)


def test_correlated_issuance_capacity_preserves_frozen_source_transfer() -> None:
    """Issuance may evict its source, never the target or its selected support."""
    predictive_map, engine = correlated_ready()
    source, = (t for t in engine.snapshot.traversal_tokens
               if t.node_id == "c" and t.accepted_at == at(36))
    for token in engine.snapshot.traversal_tokens:
        if token != source:
            engine._frontier._remove_token(token.token_id)
    engine._advance_supports(at(37))
    roundtrip(predictive_map, engine)
    support, = engine.snapshot.anonymous_supports
    engine._frontier._token_limit = 1
    result = engine.observe(event("t", "on", 38))
    target, = result.snapshot.traversal_tokens
    assert source in result.authorizations[0].source_tokens
    assert target.node_id == "t" and source not in result.snapshot.traversal_tokens
    moved, = result.snapshot.anonymous_supports
    assert (moved.support_id, moved.created_at) == (
        support.support_id, support.created_at,
    )
    assert {b.token_id for b in result.snapshot.support_token_bindings} == {
        target.token_id,
    }
    restored = roundtrip(predictive_map, engine)
    restored._frontier._token_limit = 1
    onward = engine.observe(event("u", "on", 39))
    assert onward == restored.observe(event("u", "on", 39))
    assert target in onward.authorizations[0].source_tokens
    assert [t.node_id for t in onward.snapshot.traversal_tokens] == ["u"]
    engine.observe(event("t", "off", 40))
    engine.observe(event("t", "on", 41))
    assert all(t.node_id != "t" for t in engine.snapshot.traversal_tokens)
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("clearing", (False, True))
def test_correlated_settled_handoff_requires_asserted_source(clearing: bool) -> None:
    predictive_map, engine = correlated_ready()
    engine._frontier.clear(at(37))
    engine._advance_supports(at(37))
    support, = engine.snapshot.anonymous_supports
    if clearing:
        engine.observe(event("c", "off", 37))
    roundtrip(predictive_map, engine)
    result = engine.observe(event("t", "on", 38))
    auth, = result.authorizations
    assert auth.authorized is not clearing
    if clearing:
        assert auth.reason == "untracked_rejected"
        assert not result.snapshot.traversal_tokens
    else:
        assert auth.reason == "settled_adjacent_transfer"
        token, = result.snapshot.traversal_tokens
        assert token.provenance_kind == auth.reason
        assert token.track_confidence == "provisional"
        assert token.equivalent_confirmed_strength
        moved, = result.snapshot.anonymous_supports
        assert (moved.support_id, moved.created_at) == (
            support.support_id, support.created_at,
        )
        assert moved.current_node_id == "t"
        assert all(t.node_id != "t" for p in result.snapshot.selected_paths
                   if p is not None for t in p.visits)
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)


def test_correlated_unbound_authorization_is_target_only() -> None:
    predictive_map, engine = correlated_ready()
    engine._supports.clear(at(37))
    roundtrip(predictive_map, engine)
    result = engine.observe(event("t", "on", 38))
    auth, = result.authorizations
    assert auth.authorized and auth.reason == "adjacent_authorized"
    assert auth.source_tokens
    assert all(t.node_id != "t" for t in result.snapshot.traversal_tokens)
    assert not result.snapshot.anonymous_supports
    assert next(p for p in result.snapshot.policy_states if p.zone == "t").active
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("mode", ("hold", "clear", "expiry", "reopen", "trust"))
def test_correlated_token_keeps_original_lifecycle(mode: str) -> None:
    predictive_map, engine = correlated_ready()
    engine.observe(event("t", "on", 38))
    token, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "t")
    if mode == "hold":
        engine.observe(event("t", "off", 39))
        result = engine.observe(event("t", "on", 40))
        assert not result.authorizations
        assert token in engine.snapshot.traversal_tokens
        physical = next(s for s in engine.snapshot.episode_states if s.node_id == "t")
        assert physical.episode_id == token.episode_id
        assert physical.traversal_valid_until is None
    elif mode == "clear":
        engine.observe(event("t", "off", 44))
        engine.advance(at(54))
        assert token in engine.snapshot.traversal_tokens
        assert token.token_id not in engine.snapshot.current_token_ids
    elif mode == "expiry":
        engine.advance(at(218))
        assert token not in engine.snapshot.traversal_tokens
        assert token in engine.snapshot.retained_traversal_tokens
    elif mode == "reopen":
        engine.observe(event("t", "off", 217))
        engine.observe(event("t", "on", 219))
        reopened, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "t")
        assert reopened.token_id == token.token_id
        assert reopened.accepted_at == token.accepted_at
        assert reopened.continuity_reopened_at == at(219)
        assert reopened.valid_until == at(399)
    else:
        engine.advance(at(1838))
        assert token not in engine.snapshot.traversal_tokens
        assert token not in engine.snapshot.retained_traversal_tokens
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("state", ("unknown", "unavailable"))
def test_correlated_availability_removes_authority_permanently(state: str) -> None:
    predictive_map, engine = correlated_ready()
    engine.observe(event("t", "on", 38))
    token, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "t")
    engine.observe(event("t", state, 39))
    roundtrip(predictive_map, engine)
    engine.observe(event("t", "on", 40))
    assert token not in engine.snapshot.traversal_tokens
    assert token not in engine.snapshot.retained_traversal_tokens
    roundtrip(predictive_map, engine)


def test_correlated_count_zero_clears_authority_but_preserves_real_learning() -> None:
    predictive_map, engine = correlated_ready()
    engine.observe(event("t", "on", 38))
    engine.observe(event("u", "on", 39))
    queued, = engine._pending_prediction_learning
    assert queued.path_node_ids[-2:] == ("t", "u")
    debt = engine.prediction_state["deferred_counts"]
    engine.observe_count(CountInput("zero40", 0, True, at(40)))
    snapshot = engine.snapshot
    assert not any((snapshot.traversal_tokens, snapshot.retained_traversal_tokens,
                    snapshot.current_token_ids, snapshot.authorization_uses,
                    snapshot.pending_candidates, snapshot.anonymous_supports,
                    snapshot.support_token_bindings, snapshot.selected_paths,
                    snapshot.selected_prediction_grants,
                    engine.prediction_manager.leases))
    assert not any(p.active for p in snapshot.policy_states)
    assert engine.prediction_state["deferred_counts"] == debt
    restored = roundtrip(predictive_map, engine)
    for item in (engine, restored):
        assert item.commit_prediction_learning()
        assert item.prediction_manager.chain.counts["t"]["u"] == 1
        assert not item.commit_prediction_learning()
        item.observe_count(CountInput("one41", 1, True, at(41)))
        item.observe(event("t", "on", 42))
        assert not item.snapshot.traversal_tokens
        roundtrip(predictive_map, item)


@pytest.mark.parametrize("failure_at", ("result", "edge"))
def test_correlated_callback_failure_keeps_committed_strict_state(
    failure_at: str,
) -> None:
    predictive_map, engine = correlated_ready()
    control = roundtrip(predictive_map, engine)
    expected = control.observe(event("t", "on", 38))
    failure = RuntimeError("synthetic correlated subscriber failure")
    calls: list[str] = []

    def check(label: str) -> None:
        calls.append(label)
        assert engine.snapshot == expected.snapshot
        roundtrip(predictive_map, engine)
        with pytest.raises(ValueError, match="Model mutation is forbidden"):
            engine.advance(at(39))
        assert engine.snapshot == expected.snapshot
        if label == failure_at:
            raise failure

    def result_callback(result: ZoneModelResult) -> None:
        assert result.snapshot == expected.snapshot
        check("result")

    def edge_callback(
        current: PolicyEvent, decision: PolicyDecision,
        auth: TraversalAuthorization | None,
    ) -> None:
        assert current.zone == "t" and decision.active_after and auth is not None
        check("edge")

    with pytest.raises(RuntimeError) as caught:
        engine.observe(event("t", "on", 38), result_callback=result_callback,
                       decision_callback=edge_callback)
    assert caught.value is failure
    assert calls == (["result"] if failure_at == "result" else ["result", "edge"])
    assert serialize_target_state(predictive_map, engine) == serialize_target_state(
        predictive_map, control,
    )
    assert engine.observe(event("u", "on", 39)) == control.observe(event("u", "on", 39))


def test_startup_due_clear_is_not_replayed_as_positive() -> None:
    predictive_map = chain("room")
    engine = ZoneModelEngine(predictive_map, 1, at(0))
    engine.observe(event("room", "on", 0))
    engine.observe(event("room", "off", 40))
    engine.bootstrap_sensor_snapshot((), at(45))
    roundtrip(predictive_map, engine)
    before = engine.snapshot
    result = engine.reconcile_restored_asserted_contexts(
        (event("room", "off", 45),), at(45),
    )
    assert result.episode_states[0].status == "clear"
    assert result.episode_states[0].episode_id == before.episode_states[0].episode_id
    assert not result.traversal_tokens
    assert result.selected_paths == before.selected_paths
    assert result.belief_states == before.belief_states
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("reacquire", (False, True))
def test_bootstrap_settled_authority_transfers_without_fresh_origin(
    reacquire: bool,
) -> None:
    nodes = ("a", "b", "t") if reacquire else ("a", "b", "c", "d")
    predictive_map = chain(
        *nodes, presence=frozenset({"t"}) if reacquire else frozenset(),
    )
    engine, donor = bootstrap_pair(predictive_map, nodes[:3])
    if reacquire:
        engine.observe(event("t", "off", 10))
        donor.observe(event("t", "off", 10))
    engine.advance(at(100))
    donor.advance(at(100))
    engine = compose(predictive_map, engine, donate_frontier(engine, donor))
    support, = engine.snapshot.anonymous_supports
    assert support.state == "settled"
    target = "t" if reacquire else "d"
    result = engine.observe(event(target, "on", 101))
    auth, = result.authorizations
    assert auth.reason == (
        "settled_endpoint_reacquired" if reacquire else "settled_adjacent_transfer"
    )
    assert auth.equivalent_confirmed_strength is not reacquire
    assert auth.track_confidence == ("confirmed" if reacquire else "provisional")
    moved, = result.snapshot.anonymous_supports
    assert (moved.support_id, moved.created_at) == (
        support.support_id, support.created_at,
    )
    assert moved.current_node_id == target
    assert next(p for p in result.snapshot.policy_states if p.zone == target).active
    assert not engine._pending_prediction_learning
    assert all(b.outward_context is None for b in result.snapshot.belief_states)
    roundtrip(predictive_map, engine)


def test_boundary_same_generation_continuity_has_no_new_acquisition() -> None:
    predictive_map = graph({"entry": ()}, entries=frozenset({"entry"}))
    engine = ZoneModelEngine(predictive_map, 0, at(0))
    engine.observe_count(CountInput("arrival", 1, True, at(0)))
    engine.observe(event("entry", "on", 1))
    engine.observe(event("entry", "off", 12))
    roundtrip(predictive_map, engine)
    original, = engine.snapshot.traversal_tokens
    result = engine.observe(event("entry", "on", 13))
    assert result.authorizations == ()
    assert result.policy_events == ()
    assert any(d.local_evidence_kind == "correlated_continuity_authorized"
               for d in result.policy_decisions)
    continued, = result.snapshot.traversal_tokens
    assert (continued.token_id, continued.accepted_at) == (
        original.token_id, original.accepted_at,
    )
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)


def test_same_zone_generation_owns_outward_context_from_real_use() -> None:
    predictive_map = graph(
        {"p": ("t",), "g": (), "t": ("p",)}, zones={"p": "s", "g": "s"},
    )
    engine, donor = bootstrap_pair(predictive_map, ("p", "g"))
    engine = compose(predictive_map, engine, donate_frontier(engine, donor))
    generation = next(s for s in engine.snapshot.episode_states if s.node_id == "g")
    assert any(use.target_episode_id == generation.episode_id
               for use in engine.snapshot.authorization_uses)
    engine.observe(event("p", "off", 2))
    engine.advance(at(7))
    result = engine.observe(event("t", "on", 8))
    assert result.authorizations[0].authorized
    outward = next(b for b in result.snapshot.belief_states if b.zone == "s")
    assert outward.outward_context is not None
    assert outward.outward_context.source_episode_id == generation.episode_id
    assert outward.outward_context.qualified_until == at(98)
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("outside_chain", (False, True))
def test_confirmed_departure_qualifies_actual_interaction_generation(
    outside_chain: bool,
) -> None:
    predictive_map = graph({
        "s": ("h",), "i": (), "h": ("s", "m"),
        "m": ("h", "r"), "r": ("m",),
    }, interactions=frozenset({"i"}), zones={"i": "s"})
    engine, donor = bootstrap_pair(predictive_map, ("s",))
    sequence = [event("i", "pressed", 1)]
    if outside_chain:
        sequence += [event(n, "on", t) for t, n in enumerate(("h", "m", "r"), 2)]
    sequence.append(event("s", "off", 5))
    for input_ in sequence:
        engine.observe(input_)
        donor.observe(input_)
    engine.advance(at(6))
    donor.advance(at(6))
    snapshot = donate_frontier(engine, donor)
    snapshot = replace(snapshot, belief_states=tuple(
        donor.filters["s"].state if b.zone == "s" else b
        for b in snapshot.belief_states
    ))
    engine = compose(predictive_map, engine, snapshot)
    result = engine.observe(event("s", "off", 10))
    belief = next(b for b in result.snapshot.belief_states if b.zone == "s")
    interaction = next(s for s in result.snapshot.episode_states if s.node_id == "i")
    assert belief.generation_episode_id == interaction.episode_id
    assert belief.qualified_departure_at == (at(10) if outside_chain else None)
    assert not result.authorizations
    roundtrip(predictive_map, engine)


def test_asserted_stay_hold_cancels_authentic_pending_release() -> None:
    nodes = ("a", "p", "q", "r", "s", "t")
    predictive_map = chain(*nodes, presence=frozenset(nodes))
    engine = ZoneModelEngine(predictive_map, 1, at(0))
    for seconds, node in enumerate(nodes):
        engine.observe(event(node, "on", seconds))
    donor = roundtrip(predictive_map, engine)
    donor.observe(event("p", "off", 6))
    donor.advance(at(250))
    pending = next(p for p in donor.snapshot.policy_states if p.zone == "p")
    assert pending.pending_release_since is not None
    engine.advance(at(250))
    engine = compose(predictive_map, engine, replace(
        engine.snapshot, policy_states=tuple(
            pending if p.zone == "p" else p for p in engine.snapshot.policy_states
        ),
    ))
    result = engine.observe(event("t", "on", 250))
    assert [(d.zone, d.reason) for d in result.policy_decisions] == [
        ("p", "asserted_stay_hold"),
    ]
    assert not result.policy_events
    policy = next(p for p in result.snapshot.policy_states if p.zone == "p")
    assert policy.active and policy.pending_release_since is None
    roundtrip(predictive_map, engine)


def test_legacy_settled_clear_does_not_backdate_unqualified_release() -> None:
    predictive_map = chain("a", "b", "c", "d")
    engine, donor = bootstrap_pair(predictive_map, ("a", "b", "c"),
                                   active_seed={"c": True})
    engine.advance(at(3))
    donor.advance(at(3))
    engine = compose(predictive_map, engine, donate_frontier(engine, donor))
    assert engine.snapshot.anonymous_supports[0].state == "settled"
    engine.observe(event("c", "off", 40))
    result = engine.observe(event("c", "off", 1400))
    belief = next(b for b in result.snapshot.belief_states if b.zone == "c")
    policy = next(p for p in result.snapshot.policy_states if p.zone == "c")
    assert belief.qualified_departure_at is None and belief.path_displaced_at is None
    assert policy.active and policy.pending_release_since is None
    assert not result.policy_events
    later = engine.advance(at(1401))
    policy = next(p for p in later.snapshot.policy_states if p.zone == "c")
    assert policy.pending_release_since == at(1400)
    roundtrip(predictive_map, engine)
    assert not engine.advance(at(1459.999999)).policy_events
    released = engine.advance(at(1460))
    assert [(p.zone, p.kind) for p in released.policy_events] == [("c", "released")]
    roundtrip(predictive_map, engine)


def test_clear_without_continuous_crossing_waits_for_real_dwell() -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, at(0), active_seed={"hall": True})
    engine.observe(event("hall", "on", 0))
    engine.observe(event("hall", "off", 15))
    roundtrip(predictive_map, engine)
    result = engine.observe(event("hall", "off", 20))
    policy = next(p for p in result.snapshot.policy_states if p.zone == "hall")
    assert policy.active and policy.pending_release_since is None
    assert not result.policy_events
    engine.advance(at(21))
    policy = next(p for p in engine.snapshot.policy_states if p.zone == "hall")
    assert policy.pending_release_since == at(20)
    engine.advance(at(60))
    assert not next(p for p in engine.snapshot.policy_states if p.zone == "hall").active
    roundtrip(predictive_map, engine)


def test_retention_loss_without_crossing_updates_hold_without_edge() -> None:
    predictive_map = graph({"p": (), "q": ()}, interactions=frozenset({"p", "q"}))
    payload = structural_payload(predictive_map, (
        event("p", "pressed", 0), event("q", "pressed", 1),
    ), count=1, component_policy=True)
    engine = restore_target_state(predictive_map, payload, at(1))
    roundtrip(predictive_map, engine)
    held = next(p for p in engine.snapshot.policy_states if p.zone == "p")
    assert held.retained_endpoint_hold
    result = engine.observe(event("q", "pressed", 1))
    assert [(d.zone, d.reason) for d in result.policy_decisions] == [
        ("p", "active_hold"),
    ]
    assert not result.policy_events
    unheld = next(p for p in result.snapshot.policy_states if p.zone == "p")
    assert not unheld.retained_endpoint_hold
    roundtrip(predictive_map, engine)


def test_retention_loss_releases_after_real_qualified_departure_once() -> None:
    predictive_map = graph({
        "m": ("a",), "i": (), "a": ("m", "b"), "b": ("a", "c"), "c": ("b",),
    }, presence=frozenset({"m"}), interactions=frozenset({"i"}),
        sticky=frozenset({"i"}), zones={"m": "p", "i": "p"})
    engine, donor = bootstrap_pair(predictive_map, ("m",))
    for input_ in (event("i", "pressed", .5), event("a", "on", 1),
                   event("b", "on", 2), event("c", "on", 3), event("m", "off", 4)):
        engine.observe(input_)
        donor.observe(input_)
    engine.advance(at(14))
    donor.advance(at(14))
    source = next(s for s in donor.episodes.states if s.node_id == "m")
    token = donor.frontier.confirmed_departure_token(source, at(14))
    assert token is not None and token.path_node_ids == ("a", "b", "c")
    generation = donor.filters["p"].state.generation_episode_id
    assert generation is not None
    donor.filters["p"].register_outward(generation, token.valid_until, at(14),
                                       qualified=True)
    snapshot = donate_frontier(engine, donor)
    snapshot = replace(snapshot, belief_states=tuple(
        donor.filters["p"].state if b.zone == "p" else b for b in snapshot.belief_states
    ), policy_states=donor.snapshot.policy_states)
    engine = compose(predictive_map, engine, snapshot, audit=donor.audit_rows)
    result = engine.observe(event("c", "on", 600))
    assert [(p.zone, p.kind) for p in result.policy_events] == [("p", "released")]
    assert not next(p for p in result.snapshot.policy_states if p.zone == "p").active
    assert not engine.observe(event("c", "on", 601)).policy_events
    roundtrip(predictive_map, engine)


def _prediction_input(node: str, state: str, seconds: float) -> SensorInput:
    return SensorInput(f"binary_sensor.{node}", state, NOW + timedelta(seconds=seconds))


def _reject_preserving_live_receiver(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
    malformed: dict[str, object], message: str,
) -> None:
    """Whole-reader rejection plus actual nonempty facade transaction boundary."""
    control = roundtrip(predictive_map, engine)
    good = serialize_target_state(predictive_map, engine)
    original = deepcopy(malformed)
    with pytest.raises(ValueError, match=f"^{message}$"):
        restore_target_state(predictive_map, malformed, engine.snapshot.updated_at)
    receiver = OccupancyTracker(predictive_map)
    assert receiver.restore_state(good, engine.snapshot.updated_at)
    before = receiver.occupancy_store_data()
    assert not receiver.restore_state(malformed, engine.snapshot.updated_at)
    assert receiver.occupancy_store_data() == before == good
    assert serialize_target_state(predictive_map, engine) == good
    assert malformed == original
    assert receiver._engine is not None
    continuation = SensorInput("binary_sensor.t00", "on",
                               engine.snapshot.updated_at + timedelta(seconds=1))
    assert receiver._engine.observe(continuation) == control.observe(continuation)
    roundtrip(predictive_map, receiver._engine)


@pytest.mark.parametrize("kind,message", (
    ("audit", "Selected-path audit source is incompatible"),
    ("health", "Path health disagrees with physical aggregate/coverage"),
    ("eligible", "Selected authority disagrees with physical generations"),
    ("activation", "Selected activation is not episode-derived"),
    ("target", "Prediction lease survived contradictory target evidence"),
    ("ledger", "Selected prediction grant lacks source ledger"),
    ("available", "Selected prediction grant source is not ordinary available"),
))
def test_current_strict_reader_rejects_one_detached_record(
    kind: str, message: str,
) -> None:
    predictive_map, engine = prepared(prediction_graph(peers=5))
    if kind in {"health", "target", "ledger", "available"}:
        for i in range(5):
            engine.observe(_prediction_input(f"p{i}", "on", 3 + i))
        assert all(v.node_id != "c" for p in engine.snapshot.selected_paths
                   if p is not None for v in (*p.visits, *p.route))
    if kind == "eligible":
        engine.observe(_prediction_input("c", "unavailable", 3))
    if kind == "available":
        engine.advance(NOW + timedelta(seconds=8))
    roundtrip(predictive_map, engine)
    snapshot = engine.snapshot
    audit = None
    if kind == "audit":
        row = next(r for r in engine.audit_rows
                   if r.traversal_reason == "selected_path" and r.zone == "c")
        historical = next(s for s in snapshot.selected_sources if s.node_id == "a")
        assert historical.episode_id is not None and row.episode_id is not None
        corrupt = replace(row, evidence_ids=(row.episode_id, historical.episode_id))
        audit = tuple(corrupt if r is row else r for r in engine.audit_rows)
    elif kind == "health":
        snapshot = replace(snapshot, path_health=tuple(
            replace(h, unsupported_started_at=h.on_started_at) if h.node_id == "p4"
            else h for h in snapshot.path_health
        ))
    elif kind == "eligible":
        snapshot = replace(snapshot, selected_paths=tuple(
            replace(p, endpoint_eligible=True)
            if p is not None and p.endpoint.node_id == "c" else p
            for p in snapshot.selected_paths
        ))
    elif kind == "activation":
        snapshot = replace(snapshot, policy_states=tuple(
            replace(p, activation_path_node_ids=("t00", "b", "c")) if p.zone == "c"
            else p for p in snapshot.policy_states
        ))
    elif kind == "target":
        # Equality with issuance remains accepted; only later evidence contradicts.
        equal = replace(snapshot, episode_states=tuple(
            replace(s, last_event_at=NOW + timedelta(seconds=2)) if s.node_id == "t00"
            else s for s in snapshot.episode_states
        ))
        compose(predictive_map, engine, equal)
        snapshot = replace(snapshot, episode_states=tuple(
            replace(s, last_event_at=NOW + timedelta(seconds=3)) if s.node_id == "t00"
            else s for s in snapshot.episode_states
        ))
    elif kind == "ledger":
        snapshot = replace(snapshot, selected_sources=tuple(
            SelectedSource("b") if s.node_id == "b" else s
            for s in snapshot.selected_sources
        ))
    else:
        donor = roundtrip(predictive_map, engine)
        donor.observe(_prediction_input("c", "unavailable", 8))
        actual = next(s for s in donor.snapshot.episode_states if s.node_id == "c")
        snapshot = replace(snapshot, episode_states=tuple(
            actual if s.node_id == "c" else s for s in snapshot.episode_states
        ))
    malformed = snapshot_payload(predictive_map, engine, snapshot, audit=audit)
    _reject_preserving_live_receiver(predictive_map, engine, malformed, message)


def test_independent_prediction_validator_rejects_real_unavailable_source() -> None:
    predictive_map, engine = prepared()
    roundtrip(predictive_map, engine)
    manager = TargetPredictionManager.restored(
        predictive_map, engine.prediction_state, engine.snapshot.updated_at,
        grants=engine.snapshot.selected_prediction_grants, strict_frontier=True,
    )
    engine._validate_prediction_consistency(manager)
    engine.observe(_prediction_input("c", "unavailable", 3))
    control = roundtrip(predictive_map, engine)
    before = serialize_target_state(predictive_map, engine)
    manager_before = manager.serialize()
    with pytest.raises(ValueError,
                       match="^Selected prediction lease source is invalid$"):
        engine._validate_prediction_consistency(manager)
    assert manager.serialize() == manager_before
    assert serialize_target_state(predictive_map, engine) == before
    assert engine.observe(_prediction_input("t00", "on", 4)) == control.observe(
        _prediction_input("t00", "on", 4),
    )


@pytest.mark.parametrize("membership", ("visits", "route", "direct"))
def test_selected_correlated_retirement_survives_history_eviction(
    membership: str,
) -> None:
    """Actual inactive visits-only and route-only records each deny exemption."""
    adjacent = {
        "a": ("b",), "b": ("a", "c"), "c": ("b", "t"),
        "t": ("c", "u", "x"), "u": ("t", "v"), "v": ("u",),
        "x": ("t", "y"), "y": ("x", "z"), "z": ("y", "w"), "w": ("z",),
    }
    if membership != "route":
        adjacent.update({"c": ("b", "t", "x"), "t": ("c",),
                         "x": ("c", "y"), "u": ("v",)})
    predictive_map = graph(adjacent, presence=frozenset({"t"}))
    sequence = [event("t", "on", -40), event("t", "off", -20),
                event("a", "on", 0), event("b", "on", 1), event("c", "on", 2)]
    if membership == "visits":
        # X4 now retains T as overlap. Qualify actual stable clear in BOTH
        # producers before composition, retaining the unexpired component token.
        sequence += [event("t", "on", 3), event("x", "on", 4),
                     event("t", "off", 4), event("x", "on", 14)]
    elif membership == "route":
        sequence += [event("t", "on", 3), event("u", "on", 4),
                     event("v", "on", 5), event("x", "on", 6),
                     event("y", "on", 7), event("t", "off", 8),
                     event("y", "on", 18)]
    payload = structural_payload(predictive_map, tuple(sequence), count=1)
    engine = restore_target_state(predictive_map, payload, sequence[-1].event_at)
    roundtrip(predictive_map, engine)
    if membership == "direct":
        before_learning = engine.prediction_state["deferred_counts"]
        result = engine.observe(event("t", "on", 3))
        assert result.disposition == "accepted_correlated_positive"
        assert result.authorizations[0].reason == "selected_path"
        assert not any(t.node_id in {"c", "t"}
                   for t in result.snapshot.traversal_tokens)
        assert engine.prediction_state["deferred_counts"] == before_learning
        assert not engine._pending_prediction_learning
        engine.observe(event("x", "on", 4))
        engine.observe(event("t", "off", 4))
        engine.advance(at(13.999999))
        assert "t" in engine._selected_paths.covered_nodes
        engine.advance(at(14))
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "t")
    source = next(s for s in engine.snapshot.selected_sources if s.node_id == "t")
    assert physical.cadence_correlated and source.origin == "correlated"
    assert source.consumed and source.episode_id == physical.episode_id
    assert "t" not in engine._selected_paths.covered_nodes
    visits = [v for p in engine.snapshot.selected_paths if p is not None
              for v in p.visits if v.episode_id == physical.episode_id]
    route = [v for p in engine.snapshot.selected_paths if p is not None
             for v in p.route if v.episode_id == physical.episode_id]
    assert bool(visits) is (membership != "route")
    assert bool(route) is (membership == "route")
    assert all(not v.branch_active for v in (*visits, *route))
    if membership != "direct":
        token, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "t")
        assert token.episode_id == physical.episode_id
        assert token.accepted_at == source.at == physical.started_at
        assert token.provenance_kind == "adjacent"
        cleanup_at = at(19 if membership == "route" else 15)
        assert token.valid_until > cleanup_at
        # Ordinary clear sync retains this token. Selected-history exclusion,
        # not expiry, unavailability or a missing correlated flag, must remove it.
        control = roundtrip(predictive_map, engine)
        control._frontier.sync(physical, engine.snapshot.updated_at)
        assert token in control.snapshot.traversal_tokens
        assert token.token_id not in control.snapshot.current_token_ids
        engine.advance(cleanup_at)
        assert token not in engine.snapshot.traversal_tokens
        assert token not in engine.snapshot.retained_traversal_tokens
        assert token.token_id not in engine.snapshot.current_token_ids
        assert all(b.token_id != token.token_id
                   for b in engine.snapshot.support_token_bindings)
    roundtrip(predictive_map, engine)
    suffix = (("z", 20), ("w", 21)) if membership == "route" else (
        ("y", 16), ("z", 17), ("w", 18),
    )
    for node, seconds in suffix:
        engine.observe(event(node, "on", seconds))
    assert all(v.episode_id != physical.episode_id
               for p in engine.snapshot.selected_paths if p is not None
               for v in (*p.visits, *p.route))
    assert all(v.episode_id != physical.episode_id
               for p in engine.snapshot.selected_paths if p is not None
               for v in p.occurrences)
    restored = roundtrip(predictive_map, engine)
    # Same clear generation here; the original held-ON stream is separately
    # retained in test_engine_overlap_qualification's history-eviction boundary.
    duplicate = event("t", "off", 22 if membership == "route" else 19)
    for item in (engine, restored):
        item.observe(duplicate)
        assert all(t.episode_id != physical.episode_id for t in (
            *item.snapshot.traversal_tokens, *item.snapshot.retained_traversal_tokens,
        ))
        assert next(s for s in item.snapshot.episode_states
                    if s.node_id == "t").episode_id == physical.episode_id
        roundtrip(predictive_map, item)


def test_old_selected_node_does_not_block_new_correlated_generation() -> None:
    predictive_map = graph({
        "a": ("b",), "b": ("a", "c"), "c": ("b", "t", "x"),
        "t": ("c",), "x": ("c",),
    }, presence=frozenset({"t"}))
    engine = ZoneModelEngine(predictive_map, 1, at(0))
    donor = PersistenceComponents(predictive_map, 1, at(0))
    old_donor = PersistenceComponents(predictive_map, 1, at(0))
    for seconds, node in enumerate(("a", "b", "c")):
        engine.observe(event(node, "on", seconds))
        donor.observe(event(node, "on", seconds))
        old_donor.observe(event(node, "on", seconds))
    engine.observe(event("t", "on", 3))
    old_donor.observe(event("t", "on", 3))
    old_token, = (t for t in old_donor.snapshot.traversal_tokens if t.node_id == "t")
    donor.bootstrap_sensor_snapshot((event("t", "on", 3),), at(3))
    for input_ in (event("t", "off", 8), event("x", "on", 9),
                   event("c", "off", 10), event("t", "on", 19)):
        engine.observe(input_)
    donor.observe(event("t", "off", 8))
    donor.observe(event("t", "on", 19))
    snapshot = donate_frontier(engine, donor)
    token, = snapshot.traversal_tokens
    # Both generations are authentic records. Only the current correlated one
    # qualifies: preserving it must not accidentally preserve its older neighbor.
    snapshot = replace(snapshot, traversal_tokens=tuple(sorted(
        (*snapshot.traversal_tokens, old_token), key=lambda t: t.token_id,
    )))
    engine = compose(predictive_map, engine, snapshot)
    assert token.provenance_kind == "settled_adjacent_transfer"
    old, = (v for p in engine.snapshot.selected_paths if p is not None
            for v in p.visits if v.node_id == "t")
    assert old.episode_id != token.episode_id
    assert old.episode_id == old_token.episode_id
    assert old.at == at(3) and token.accepted_at == at(19)
    assert "t" not in engine._selected_paths.covered_nodes
    engine.advance(at(20))
    assert engine.snapshot.traversal_tokens == (token,)
    assert old_token not in engine.snapshot.retained_traversal_tokens
    assert engine.snapshot.support_token_bindings
    roundtrip(predictive_map, engine)


def test_correlated_duplicates_and_stale_inputs_do_not_refresh_authority() -> None:
    predictive_map, engine = correlated_ready()
    engine.observe(event("t", "on", 38))
    before = engine.snapshot
    token, = (t for t in before.traversal_tokens if t.node_id == "t")
    assert engine.observe(event("t", "on", 38)).snapshot == before
    assert engine.observe(event("t", "off", 37)).snapshot == before
    result = engine.observe(event("t", "on", 39))
    assert not result.authorizations and not result.policy_events
    assert token in result.snapshot.traversal_tokens
    assert engine._pending_prediction_learning == []
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("mode", ("result", "edge", "both"))
def test_correlated_success_callbacks_see_complete_committed_state(mode: str) -> None:
    predictive_map, engine = correlated_ready()
    control = roundtrip(predictive_map, engine)
    expected = control.observe(event("t", "on", 38))
    calls: list[str] = []

    def check(label: str) -> None:
        calls.append(label)
        assert engine.snapshot == expected.snapshot
        live_ids = {t.token_id for t in (*engine.snapshot.traversal_tokens,
                                         *engine.snapshot.retained_traversal_tokens)}
        assert all(b.token_id in live_ids
               for b in engine.snapshot.support_token_bindings)
        roundtrip(predictive_map, engine)

    def result_callback(result: ZoneModelResult) -> None:
        assert result.snapshot == expected.snapshot
        check("result")

    def edge_callback(
        current: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert current.zone == "t" and decision.active_after
        assert authorization == expected.authorizations[0]
        check("edge")

    actual = engine.observe(
        event("t", "on", 38),
        result_callback=result_callback if mode != "edge" else None,
        decision_callback=edge_callback if mode != "result" else None,
    )
    assert actual == expected
    assert calls == (["result", "edge"] if mode == "both" else [mode])
    assert serialize_target_state(predictive_map, engine) == serialize_target_state(
        predictive_map, control,
    )
