"""Synthetic event-driven integration proofs for REQ-TRAV-018.

These generic routes complement, never replace or retime, the frozen incident.
Supports, tokens, generations and faults below are created by sensor inputs, not
by injecting hypothetical production events or relaxing snapshot validation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    SupportTokenBinding,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
    ZonePolicyState,
)

pytestmark = pytest.mark.target_model
START = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
EPSILON = timedelta(microseconds=1)


def _at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def _map(
    *, target: str = "presence", second: bool = False, receiving: str | None = None,
    filler_tokens: int = 0,
) -> PredictiveMap:
    """Two disjoint creation routes meet only at the unvisited target B."""
    neighbors = {
        "x": ["y"], "y": ["x", "a"], "a": ["y", "b"],
        "b": ["a", "c"], "c": ["b", "d"], "d": ["c"],
    }
    if second:
        neighbors.update({"u": ["v"], "v": ["u", "z"], "z": ["v", "b"]})
        neighbors["b"].append("z")
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "zone": "b" if node == receiving else node,
                "role": (
                    "transition_gate" if node == "b" and target == "transition"
                    else "room_occupancy"
                ),
                "occupancy_behavior": (
                    "transient" if node == "b" and target == "transition"
                    else "sustained"
                ),
                "entities": {
                    "motion" if node in {"b", "c", "d"} and target != "presence"
                    else "mmwave": f"binary_sensor.{node}"
                },
                "adjacent": adjacent,
                "initial_weight": 0.8,
            }
            for node, adjacent in neighbors.items()
        } | {
            f"filler_{index}": {
                "role": "room_occupancy",
                "occupancy_behavior": "sticky",
                "entities": {"interaction": f"event.filler_{index}"},
            }
            for index in range(filler_tokens)
        },
    })


def _input(node: str, state: str, seconds: float) -> SensorInput:
    return SensorInput(f"binary_sensor.{node}", state, _at(seconds))


def _episode(engine: ZoneModelEngine, node: str) -> EpisodeState:
    return next(s for s in engine.snapshot.episode_states if s.node_id == node)


def _belief(engine: ZoneModelEngine, node: str) -> ZoneBeliefState:
    return next(s for s in engine.snapshot.belief_states if s.zone == node)


def _policy(engine: ZoneModelEngine, node: str) -> ZonePolicyState:
    return next(s for s in engine.snapshot.policy_states if s.zone == node)


def _token(engine: ZoneModelEngine, node: str) -> TraversalToken:
    episode_id = _episode(engine, node).episode_id
    return next(
        t for t in engine.snapshot.traversal_tokens if t.episode_id == episode_id
    )


def _round_trip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> ZoneModelEngine:
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, restored) == payload
    return restored


def _seed(
    predictive_map: PredictiveMap, count: int = 2, *, frontier: float = 302,
    second: bool = False, correlated: bool = False,
    token_capacity: int = 64,
) -> ZoneModelEngine:
    engine = ZoneModelEngine(predictive_map, count, _at(-41))
    engine._frontier._token_limit = token_capacity
    if correlated:
        # Prime B while no support or traversal exists, before creating source A.
        primed = engine.observe(_input("b", "on", -40))
        assert primed.authorizations[0].reason == "track_bootstrap_pending"
        assert not primed.policy_events and not primed.snapshot.anonymous_supports
        engine.observe(_input("b", "off", -30))
    for offset, node in enumerate(("x", "y", "a")):
        result = engine.observe(_input(node, "on", offset))
    assert result.authorizations[0].track_confidence == "confirmed"
    support, = engine.snapshot.anonymous_supports
    assert support.current_node_id == "a" and support.state == "settled"
    assert support.path_node_ids == ("x", "y", "a")
    assert support.created_at == _at(2)
    if second:
        for offset, node in enumerate(("u", "v", "z"), start=3):
            engine.observe(_input(node, "on", offset))
        assert {s.current_node_id for s in engine.snapshot.anonymous_supports} == {
            "a", "z"
        }
    cleared_nodes = ("x", "y", *(("u", "v") if second else ()))
    for offset, node in enumerate(cleared_nodes, start=10):
        engine.observe(_input(node, "off", offset))
    engine.commit_prediction_learning()
    engine.advance(_at(frontier))
    assert not engine.snapshot.traversal_tokens
    assert not engine.snapshot.pending_candidates
    assert not engine._pending_prediction_learning
    assert not _policy(engine, "b").active
    assert _episode(engine, "a").started_at == _at(2)
    return engine


def _assert_source(engine: ZoneModelEngine, node: str = "a") -> None:
    support = next(
        s for s in engine.snapshot.anonymous_supports if s.current_node_id == node
    )
    state, belief = _episode(engine, node), _belief(engine, node)
    assert support.state == "settled" and support.valid_until is None
    assert support.current_episode_id == state.episode_id
    assert state.status == "asserted" and state.known_on
    assert not state.health_warning and not state.cadence_warning
    assert not belief.health_warning and belief.context == "asserted"
    assert (
        belief.generation_episode_id == belief.asserted_episode_id == state.episode_id
    )
    assert belief.outward_context is None
    assert belief.probability >= POLICY_CALIBRATIONS[belief.profile_name].on_threshold


def _handoff(engine: ZoneModelEngine, seconds: float = 302) -> ZoneModelResult:
    _assert_source(engine)
    result = engine.observe(_input("b", "on", seconds))
    authorization, = result.authorizations
    assert authorization.authorized
    assert authorization.reason == "settled_adjacent_transfer"
    assert authorization.settled_handoff is not None
    assert not authorization.source_tokens and not authorization.new_uses
    assert _policy(engine, "b").active
    assert [(e.zone, e.kind, e.event_at) for e in result.policy_events] == [
        ("b", "acquired", _at(seconds))
    ]
    return result


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("age", (7200, 86400))
def test_continuous_source_past_trust_is_consumed_not_timer_renewed(
    count: int, age: int,
) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map, count, frontier=age + 2)
    source = _episode(engine, "a")
    assert source.assertion_trust_until is not None
    assert engine.snapshot.updated_at > source.assertion_trust_until
    assert source.started_at is not None
    assert engine.snapshot.updated_at - source.started_at == timedelta(seconds=age)
    assert not engine.snapshot.retained_traversal_tokens
    assert not engine.snapshot.support_token_bindings
    before = engine.snapshot
    support, = before.anonymous_supports
    learned = engine.prediction_manager.serialize()
    created = engine.diagnostic_counters["support_created"]
    # Same-frontier timer replay cannot create a token or renew the old episode.
    assert engine.advance(before.updated_at).snapshot == before
    _handoff(engine, age + 2)
    assert _episode(engine, "a") == source
    assert _belief(engine, "a") == next(
        s for s in before.belief_states if s.zone == "a"
    )
    moved, = engine.snapshot.anonymous_supports
    assert (moved.support_id, moved.created_at) == (
        support.support_id, support.created_at
    )
    assert moved.path_node_ids == ("a", "b") and moved.updated_at == _at(age + 2)
    assert engine.diagnostic_counters["support_created"] == created
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("target", ("presence", "transition"))
def test_target_settlement_or_moving_expiry_is_exact(count: int, target: str) -> None:
    predictive_map = _map(target=target)
    engine = _seed(predictive_map, count)
    original, = engine.snapshot.anonymous_supports
    _handoff(engine)
    token = _token(engine, "b")
    moved, = engine.snapshot.anonymous_supports
    assert moved.support_id == original.support_id
    assert moved.created_at == original.created_at
    assert token.accepted_at == _at(302)
    assert token.valid_until == _at(302 + (180 if target == "presence" else 45))
    assert token.valid_until == _episode(engine, "b").traversal_valid_until
    assert token.path_node_ids == ("a", "b") and token.track_confidence == "provisional"
    assert token.equivalent_confirmed_strength
    assert moved.state == ("settled" if target == "presence" else "moving")
    assert moved.valid_until == (None if target == "presence" else token.valid_until)
    restored = _round_trip(predictive_map, engine)
    for at in (
        token.valid_until - EPSILON, token.valid_until, token.valid_until + EPSILON,
    ):
        result = engine.advance(at)
        assert restored.advance(at) == result
        assert bool(result.snapshot.anonymous_supports) == (
            target == "presence" or at < token.valid_until
        )
        token_absent = all(
            t.token_id != token.token_id for t in result.snapshot.traversal_tokens
        )
        assert token_absent == (at >= token.valid_until)
        if target == "presence":
            assert result.snapshot.anonymous_supports == (moved,)
        assert engine.advance(at).snapshot == result.snapshot
        _round_trip(predictive_map, engine)


@pytest.mark.parametrize(
    "failure", (False, True), ids=("publication", "subscriber-exception"),
)
@pytest.mark.parametrize("correlated", (False, True))
def test_prepared_transfer_publishes_before_commit_then_count_even_on_failure(
    failure: bool, correlated: bool,
) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map, correlated=correlated)
    before = engine.snapshot
    source, = before.anonymous_supports
    bindings = before.support_token_bindings
    retained = {t.token_id: t for t in before.retained_traversal_tokens}
    assert bindings and all(b.token_id in retained for b in bindings)
    assert any(retained[b.token_id].accepted_at < source.updated_at for b in bindings)
    assert any(retained[b.token_id].accepted_at == source.updated_at for b in bindings)
    learned = engine.prediction_manager.serialize()
    transferred = engine.diagnostic_counters["support_transferred"]
    observed: list[PolicyEvent] = []
    count_impl = engine._apply_count_conflicts

    def count_after_commit(
        at: datetime, *, local_effect: EpisodeEffect | None = None,
        authorization: TraversalAuthorization | None = None,
    ) -> None:
        committed, = engine.snapshot.anonymous_supports
        assert committed.support_id == source.support_id
        assert committed.current_node_id == "b" and committed.updated_at == at
        assert engine.snapshot.support_token_bindings == (
            SupportTokenBinding(_token(engine, "b").token_id, source.support_id),
        )
        assert len(observed) == 1
        count_impl(at, local_effect=local_effect, authorization=authorization)

    with (
        patch.object(
            engine._supports, "prepare_handoff", wraps=engine._supports.prepare_handoff,
        ) as prepare,
        patch.object(engine._supports, "apply", wraps=engine._supports.apply) as apply,
        patch.object(
            engine, "_apply_count_conflicts", side_effect=count_after_commit,
        ) as count,
    ):
        def callback(
            event: PolicyEvent, decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            assert (event.zone, event.kind, event.event_at) == (
                "b", "acquired", _at(302)
            )
            assert decision.active_after and _policy(engine, "b").active
            assert authorization is not None
            assert authorization.settled_handoff is not None
            selection = authorization.settled_handoff
            assert selection.support_id == source.support_id
            assert selection.source_updated_at == source.updated_at
            assert selection.source_episode_id == source.current_episode_id
            assert selection.target_episode_id == _episode(engine, "b").episode_id
            assert selection.authorized_at == event.event_at
            assert _policy(engine, "b").activation_source_episode_ids == (
                source.current_episode_id,
            )
            assert prepare.call_count == 1 and apply.call_count == count.call_count == 0
            assert engine.snapshot.anonymous_supports == (source,)
            assert engine.snapshot.support_token_bindings == bindings
            observed.append(event)
            if failure:
                raise RuntimeError("synthetic subscriber failure")

        if failure:
            with pytest.raises(RuntimeError, match="synthetic subscriber failure"):
                engine.observe(_input("b", "on", 302), decision_callback=callback)
        else:
            result = engine.observe(_input("b", "on", 302), decision_callback=callback)
            assert result.policy_events == tuple(observed)
            assert result.disposition == (
                "accepted_correlated_positive" if correlated else "accepted_positive"
            )
        assert prepare.call_count == apply.call_count == count.call_count == 1
        prepared = apply.call_args.kwargs["prepared_handoff"]
        assert prepared is not None
        assert prepared.supports == engine.snapshot.anonymous_supports
        assert prepared.bindings == engine.snapshot.support_token_bindings
    assert len(observed) == 1
    moved, = engine.snapshot.anonymous_supports
    token = _token(engine, "b")
    assert moved.support_id == source.support_id and moved.current_node_id == "b"
    assert engine.snapshot.support_token_bindings == (
        SupportTokenBinding(token.token_id, source.support_id),
    )
    assert engine.snapshot.retained_traversal_tokens == before.retained_traversal_tokens
    assert engine.snapshot.authorization_uses == before.authorization_uses
    assert engine.diagnostic_counters["support_transferred"] == transferred + 1
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    assert any(d.zone == "b" and d.event_at == _at(302) for d in engine.audit_rows)
    snapshot = engine.snapshot
    for current in (engine, _round_trip(predictive_map, engine)):
        retry = current.observe(_input("b", "on", 302), decision_callback=callback)
        assert not retry.policy_events and not retry.authorizations
        assert retry.snapshot == snapshot
    assert len(observed) == 1
    assert engine.diagnostic_counters["support_transferred"] == transferred + 1


def test_preparation_failure_never_publishes_success() -> None:
    engine = _seed(_map())
    supports = engine.snapshot.anonymous_supports
    with (
        patch.object(
            engine._supports, "prepare_handoff",
            side_effect=ValueError("invalid proposal"),
        ),
        patch.object(
            engine, "_evaluate_policies", wraps=engine._evaluate_policies,
        ) as publish,
        patch.object(engine._supports, "apply", wraps=engine._supports.apply) as commit,
    ):
        with pytest.raises(ValueError, match="invalid proposal"):
            engine.observe(_input("b", "on", 302))
        assert publish.call_count == commit.call_count == 0
    assert not _policy(engine, "b").active
    assert engine.snapshot.anonymous_supports == supports
    assert not engine._pending_prediction_learning


@pytest.mark.parametrize("fault", ("clearing", "clear", "unknown", "unavailable"))
def test_source_faults_remove_departure_authority_not_raw_local_evidence(
    fault: str,
) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    _assert_source(engine)
    engine.observe(_input("a", "off" if fault in {"clearing", "clear"} else fault, 302))
    at = 313 if fault == "clear" else 303
    engine.advance(_at(at))
    assert _episode(engine, "a").status == (
        "unavailable" if fault in {"unknown", "unavailable"} else fault
    )
    if fault in {"clearing", "clear"}:
        assert engine.snapshot.anonymous_supports  # retention is not departure trust
    else:
        assert not engine.snapshot.anonymous_supports
    before = engine.snapshot
    result = engine.observe(_input("b", "on", at))
    authorization, = result.authorizations
    assert not authorization.authorized and authorization.settled_handoff is None
    assert not _policy(engine, "b").active
    assert not result.policy_events
    assert result.snapshot.anonymous_supports == before.anonymous_supports
    assert not result.snapshot.traversal_tokens
    assert _belief(engine, "b").generation_episode_id == (
        _episode(engine, "b").episode_id
    )
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize(
    "bootstrap", (False, True), ids=("unsupported-positive", "raw-bootstrap"),
)
def test_asserted_source_without_authentic_support_cannot_handoff(
    bootstrap: bool,
) -> None:
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, 2, _at(-1))
    if bootstrap:
        engine.bootstrap_sensor_snapshot((_input("a", "on", 2),), _at(2))
    else:
        first = engine.observe(_input("a", "on", 2))
        assert first.authorizations[0].reason == "track_bootstrap_pending"
    engine.advance(_at(7202))
    assert _episode(engine, "a").known_on
    assert _belief(engine, "a").probability >= 0.7
    assert not engine.snapshot.anonymous_supports
    result = engine.observe(_input("b", "on", 7202))
    assert not result.authorizations[0].authorized
    assert result.authorizations[0].settled_handoff is None
    assert not _policy(engine, "b").active and not result.policy_events
    assert not result.snapshot.traversal_tokens
    assert not result.snapshot.anonymous_supports


@pytest.mark.parametrize(
    "remove_second", (False, True), ids=("ambiguous", "one-healthy"),
)
@pytest.mark.parametrize("correlated", (False, True))
def test_two_independent_settled_neighbors_fail_closed_until_one_is_ineligible(
    remove_second: bool, correlated: bool,
) -> None:
    predictive_map = _map(second=True)
    engine = _seed(predictive_map, second=True, correlated=correlated)
    _assert_source(engine, "a")
    _assert_source(engine, "z")
    if remove_second:
        # A clear retains the second support but removes its departure trust.
        engine.observe(_input("z", "off", 302))
    supports = engine.snapshot.anonymous_supports
    assert len(supports) == 2
    result = engine.observe(_input("b", "on", 302))
    assert result.disposition == (
        "accepted_correlated_positive" if correlated else "accepted_positive"
    )
    authorization, = result.authorizations
    assert authorization.authorized == remove_second
    assert _policy(engine, "b").active == remove_second
    assert len(result.snapshot.anonymous_supports) == 2
    if remove_second:
        assert authorization.reason == "settled_adjacent_transfer"
        assert authorization.settled_handoff is not None
        assert authorization.settled_handoff.source_node_id == "a"
        assert {s.current_node_id for s in result.snapshot.anonymous_supports} == {
            "b", "z"
        }
        second = next(s for s in supports if s.current_node_id == "z")
        assert second in result.snapshot.anonymous_supports
    else:
        assert authorization.settled_handoff is None
        assert not result.policy_events and not result.snapshot.traversal_tokens
        assert result.snapshot.anonymous_supports == supports
        assert bool(result.snapshot.pending_candidates) == (not correlated)
    _round_trip(predictive_map, engine)


def test_count_zero_clears_authority_and_count_recovery_does_not_recreate_it() -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    result = engine.observe_count(CountInput("empty", 0, True, _at(302)))
    assert not result.snapshot.anonymous_supports
    assert not result.snapshot.support_token_bindings
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("count-zero lookup"),
    ):
        empty = engine.observe(_input("b", "on", 303))
    assert not empty.authorizations and not empty.policy_events
    assert not any(p.active for p in empty.snapshot.policy_states)
    assert not empty.snapshot.traversal_tokens and not empty.snapshot.pending_candidates
    engine.observe_count(CountInput("occupied", 2, True, _at(304)))
    assert not engine.snapshot.anonymous_supports
    again = engine.observe(_input("b", "on", 305))
    assert not again.policy_events and not _policy(engine, "b").active
    assert not engine.snapshot.anonymous_supports
    _round_trip(predictive_map, engine)


def test_stale_duplicate_and_same_episode_callbacks_never_repeat_transfer() -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    before = engine.snapshot
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("stale lookup"),
    ):
        stale = engine.observe(_input("b", "on", 301), processing_at=_at(303))
    assert stale.disposition == "stale" and stale.snapshot == before
    assert not stale.policy_events and not stale.authorizations
    _handoff(engine)
    counters = engine.diagnostic_counters
    after = engine.snapshot
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("repeat lookup"),
    ):
        duplicate = engine.observe(_input("b", "on", 302))
        assert duplicate.snapshot == after
        later = engine.observe(_input("b", "on", 303))
    assert not duplicate.authorizations and not duplicate.policy_events
    assert not later.authorizations and not later.policy_events
    assert later.snapshot.anonymous_supports == after.anonymous_supports
    assert later.snapshot.traversal_tokens == after.traversal_tokens
    assert engine.diagnostic_counters["support_transferred"] == (
        counters["support_transferred"]
    )
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("authority", ("ordinary", "pending", "endpoint"))
def test_existing_authority_wins_without_invoking_lazy_fallback(authority: str) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    if authority == "ordinary":
        # Exact A rebind establishes a legitimate fresh ordinary source token.
        engine.observe(_input("a", "off", 302))
        engine.advance(_at(3902))
        engine.observe(_input("a", "on", 3903))
        at, target, reason = 3904, "b", "adjacent_authorized"
        _assert_source(engine)
    elif authority == "pending":
        pending = engine.observe(_input("c", "on", 302))
        assert pending.authorizations[0].reason == "track_bootstrap_pending"
        assert not pending.policy_events
        at, target, reason = 303, "b", "provisional_track_acquired"
        _assert_source(engine)
    else:
        engine.observe(_input("a", "off", 302))
        engine.advance(_at(3902))
        at, target, reason = 3903, "a", "settled_endpoint_reacquired"
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("eager fallback"),
    ):
        result = engine.observe(_input(target, "on", at))
    authorization, = result.authorizations
    assert authorization.reason == reason and authorization.authorized
    assert authorization.settled_handoff is None
    assert _policy(engine, target).active
    assert not any(p.node_id == target for p in result.snapshot.pending_candidates)
    if authority == "pending":
        assert authorization.path_node_ids == ("c", "b")
        assert not result.snapshot.pending_candidates
        assert not _policy(engine, "c").active
        assert result.snapshot.anonymous_supports[0].current_node_id == "a"
    _round_trip(predictive_map, engine)


def _expired_pair_rebind(
    count: int = 2, *, pir: bool = False,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    predictive_map = _map(target="pir" if pir else "presence")
    engine = _seed(predictive_map, count)
    _handoff(engine)
    original, = engine.snapshot.anonymous_supports
    engine.observe(_input("b", "off", 312))
    engine.advance(_at(3902))
    assert not engine.snapshot.traversal_tokens
    assert not engine.snapshot.retained_traversal_tokens
    assert not _policy(engine, "b").active
    assert engine.snapshot.anonymous_supports == (original,)
    rebind = engine.observe(_input("b", "on", 3903))
    assert rebind.disposition == "accepted_positive"
    authorization, = rebind.authorizations
    assert authorization.reason == "settled_endpoint_reacquired"
    assert authorization.path_node_ids == ("b",)
    assert authorization.track_confidence == "provisional"
    assert not authorization.equivalent_confirmed_strength
    assert not authorization.source_tokens and not authorization.new_uses
    assert authorization.settled_handoff is None
    token = _token(engine, "b")
    assert token.path_node_ids == ("b",) and token.track_confidence == "provisional"
    assert token.provenance_kind == "settled_endpoint"
    assert not token.equivalent_confirmed_strength
    support, = engine.snapshot.anonymous_supports
    assert support.support_id == original.support_id
    assert support.created_at == original.created_at
    assert support.path_node_ids == ("a", "b")
    assert [(e.zone, e.kind) for e in rebind.policy_events] == [("b", "acquired")]
    assert not engine._pending_prediction_learning
    _round_trip(predictive_map, engine)
    return predictive_map, engine


@pytest.mark.parametrize("count", (1, 2))
def test_expired_pair_rebind_needs_fresh_b_c_d_and_strict_restore_before_d(
    count: int,
) -> None:
    predictive_map, engine = _expired_pair_rebind(count)
    original, = engine.snapshot.anonymous_supports
    learned = engine.prediction_manager.serialize()
    result = engine.observe(_input("c", "on", 3904))
    authorization, = result.authorizations
    assert authorization.reason == "adjacent_authorized"
    assert authorization.path_node_ids == ("b", "c")
    assert authorization.track_confidence == "provisional"
    assert not authorization.equivalent_confirmed_strength
    token = _token(engine, "c")
    assert token.path_node_ids == ("b", "c") and token.track_confidence == "provisional"
    support, = engine.snapshot.anonymous_supports
    assert support.support_id == original.support_id
    assert support.path_node_ids == ("b", "c") and support.provenance_kind == "adjacent"
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    # Crucial: restore BEFORE a third node can hide the short support path.
    restored = _round_trip(predictive_map, engine)
    expected = engine.observe(_input("d", "on", 3905))
    assert restored.observe(_input("d", "on", 3905)) == expected
    confirmed, = expected.authorizations
    assert confirmed.path_node_ids == ("b", "c", "d")
    assert confirmed.track_confidence == "confirmed"
    assert confirmed.reason == "track_confirmed"
    assert [(e.zone, e.kind) for e in expected.policy_events] == [("d", "acquired")]
    assert engine._pending_prediction_learning
    counts_before = engine.prediction_manager.chain.counts["c"]["d"]
    engine.commit_prediction_learning()
    restored.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["d"] == counts_before + 1
    assert serialize_target_state(predictive_map, restored) == (
        serialize_target_state(predictive_map, engine)
    )
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
def test_live_original_pair_confirms_only_next_independent_node(count: int) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map, count)
    _handoff(engine)
    assert not engine._pending_prediction_learning
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("c", "on", 303))
    assert restored.observe(_input("c", "on", 303)) == result
    authorization, = result.authorizations
    assert authorization.path_node_ids == ("a", "b", "c")
    assert authorization.reason == "track_confirmed"
    assert authorization.track_confidence == "confirmed"
    assert _token(engine, "c").path_node_ids == ("a", "b", "c")
    assert engine._pending_prediction_learning
    engine.commit_prediction_learning()
    restored.commit_prediction_learning()
    assert serialize_target_state(predictive_map, restored) == (
        serialize_target_state(predictive_map, engine)
    )
    _round_trip(predictive_map, engine)


def test_correlated_exact_endpoint_of_transferred_pair_still_issues_no_token() -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    _handoff(engine)
    original, = engine.snapshot.anonymous_supports
    engine.observe(_input("b", "off", 312))
    engine.advance(_at(502))  # old B token has expired, cadence run has not
    assert not engine.snapshot.traversal_tokens
    tokens = engine.snapshot.retained_traversal_tokens
    bindings = engine.snapshot.support_token_bindings
    learned = engine.prediction_manager.serialize()
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", 503))
    assert restored.observe(_input("b", "on", 503)) == result
    assert result.disposition == "accepted_correlated_positive"
    authorization, = result.authorizations
    assert authorization.reason == "settled_endpoint_reacquired"
    assert authorization.settled_handoff is None
    assert not authorization.source_tokens and not authorization.new_uses
    assert not result.snapshot.traversal_tokens
    assert result.snapshot.retained_traversal_tokens == tokens
    assert result.snapshot.support_token_bindings == bindings
    support, = result.snapshot.anonymous_supports
    assert support.support_id == original.support_id
    assert support.current_episode_id == _episode(engine, "b").episode_id
    assert support.path_node_ids == ("a", "b")
    assert not any(e.kind == "refreshed" for e in result.policy_events)
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    _round_trip(predictive_map, engine)


def test_rebound_pair_backtracking_never_confirms_or_teaches_third_node() -> None:
    predictive_map, engine = _expired_pair_rebind(pir=True)
    learned = engine.prediction_manager.serialize()
    engine.observe(_input("c", "on", 3904))
    for node, clear_at, positive_at in (("b", 3905, 3945), ("c", 3946, 3986)):
        engine.observe(_input(node, "off", clear_at))
        result = engine.observe(_input(node, "on", positive_at))
        assert result.disposition == "accepted_positive"
        authorization, = result.authorizations
        assert authorization.track_confidence == "provisional"
        assert set(authorization.path_node_ids) == {"b", "c"}
        assert not authorization.equivalent_confirmed_strength
        assert _token(engine, node).track_confidence == "provisional"
        assert not engine._pending_prediction_learning
        engine.commit_prediction_learning()
        assert engine.prediction_manager.serialize() == learned
        _round_trip(predictive_map, engine)


@pytest.mark.parametrize("fault", ("unknown", "unavailable", "new-generation"))
@pytest.mark.parametrize("audit", (False, True), ids=("without-audit", "with-audit"))
def test_historical_handoff_source_can_change_health_and_generation_after_transfer(
    fault: str, audit: bool,
) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map)
    _handoff(engine)
    source_id = _policy(engine, "b").activation_source_episode_ids
    support, = engine.snapshot.anonymous_supports
    engine.observe(_input("a", "unknown" if fault == "new-generation" else fault, 303))
    if fault == "new-generation":
        engine.observe(_input("a", "on", 304))
        assert _episode(engine, "a").episode_id != source_id[0]
    else:
        assert _episode(engine, "a").status == "unavailable"
        assert engine.snapshot.anonymous_supports == (support,)
    assert _policy(engine, "b").active
    assert _policy(engine, "b").activation_source_episode_ids == source_id
    if not audit:
        # Optional audit is not required to validate historical physical proof.
        engine = ZoneModelEngine.restore(
            predictive_map, engine.snapshot, (), engine.snapshot.updated_at,
        )
        assert not engine.audit_rows
    _round_trip(predictive_map, engine)


def test_same_episode_flap_never_attempts_a_second_handoff() -> None:
    engine = _seed(_map())
    _handoff(engine)
    episode_id = _episode(engine, "b").episode_id
    transfers = engine.diagnostic_counters["support_transferred"]
    learned = engine.prediction_manager.serialize()
    engine.observe(_input("b", "off", 303))
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("flap attempted departure selection"),
    ):
        result = engine.observe(_input("b", "on", 304))
    assert _episode(engine, "b").episode_id == episode_id
    assert not result.authorizations and not result.policy_events
    assert engine.diagnostic_counters["support_transferred"] == transfers
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned


@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize("capacity", (1, 3))
def test_target_issuance_evicts_real_dormant_lineage_before_prepared_handoff(
    correlated: bool, capacity: int,
) -> None:
    """A reduced real frontier bound forces eviction, including source origin."""
    predictive_map = _map()
    engine = _seed(
        predictive_map, correlated=correlated, token_capacity=capacity,
    )
    before = engine.snapshot
    support, = before.anonymous_supports
    assert len(before.retained_traversal_tokens) == capacity
    assert not before.traversal_tokens
    origin_id = support.support_id.removeprefix("support:")
    assert origin_id in {t.token_id for t in before.retained_traversal_tokens}
    assert SupportTokenBinding(origin_id, support.support_id) in (
        before.support_token_bindings
    )
    # Equal profile horizons make acceptance order the deterministic eviction order.
    evicted = min(
        before.retained_traversal_tokens, key=lambda t: (t.accepted_at, t.token_id),
    )
    if capacity == 1:
        assert evicted.token_id == origin_id
    source_episode = _episode(engine, "a")
    source_belief = _belief(engine, "a")
    prepare = engine._supports.prepare_handoff
    observed: list[PolicyEvent] = []

    def callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert authorization is not None and authorization.settled_handoff is not None
        assert authorization.settled_handoff.support_id == support.support_id
        assert decision.active_after
        assert engine.snapshot.anonymous_supports == (support,)
        retained_ids = {t.token_id for t in engine.snapshot.retained_traversal_tokens}
        assert evicted.token_id not in retained_ids
        assert len(engine.snapshot.traversal_tokens) + len(retained_ids) == capacity
        assert all(
            b.token_id != evicted.token_id
            for b in engine.snapshot.support_token_bindings
        )
        observed.append(event)

    with patch.object(engine._supports, "prepare_handoff", wraps=prepare) as prepared:
        result = engine.observe(_input("b", "on", 302), decision_callback=callback)
        assert prepared.call_count == 1
    assert result.authorizations[0].reason == "settled_adjacent_transfer"
    assert [(event.zone, event.kind) for event in observed] == [("b", "acquired")]
    moved, = result.snapshot.anonymous_supports
    assert (moved.support_id, moved.created_at) == (
        support.support_id, support.created_at,
    )
    assert moved.current_node_id == "b" and moved.updated_at == _at(302)
    assert result.snapshot.support_token_bindings == (
        SupportTokenBinding(_token(engine, "b").token_id, support.support_id),
    )
    assert result.snapshot.retained_traversal_tokens == tuple(
        token for token in before.retained_traversal_tokens if token != evicted
    )
    known_ids = {t.token_id for t in (
        *result.snapshot.traversal_tokens, *result.snapshot.retained_traversal_tokens,
    )}
    assert all(use.token_id in known_ids for use in result.snapshot.authorization_uses)
    assert _episode(engine, "a") == source_episode
    assert _belief(engine, "a") == source_belief
    assert engine.diagnostic_counters["support_created"] == 1
    assert not engine._pending_prediction_learning
    retry = engine.observe(_input("b", "on", 302))
    assert retry.snapshot == result.snapshot and not retry.policy_events


@pytest.mark.parametrize("receiving", ("a", "z"))
@pytest.mark.parametrize("reverse_creation", (False, True))
@pytest.mark.parametrize("frontier", (302, 3902))
def test_receiving_zone_collision_coalesces_after_selection_with_least_id_min_creation(
    receiving: str, reverse_creation: bool, frontier: int,
) -> None:
    """Two real routes converge: selected support may lose ID only at coalescence."""
    predictive_map = _map(second=True, receiving=receiving)
    engine = ZoneModelEngine(predictive_map, 2, _at(-1))
    routes: tuple[tuple[str, ...], ...] = (("x", "y", "a"), ("u", "v", "z"))
    if reverse_creation:
        routes = tuple(reversed(routes))
    for seconds, node in enumerate(node for route in routes for node in route):
        engine.observe(_input(node, "on", seconds))
    assert len(engine.snapshot.anonymous_supports) == 2
    for seconds, node in enumerate(("x", "y", "u", "v", receiving), start=10):
        engine.observe(_input(node, "off", seconds))
    engine.commit_prediction_learning()
    engine.advance(_at(frontier))
    before = engine.snapshot
    source_node = "z" if receiving == "a" else "a"
    _assert_source(engine, source_node)
    source = next(
        s for s in before.anonymous_supports if s.current_node_id == source_node
    )
    resident = next(
        s for s in before.anonymous_supports if s.current_node_id == receiving
    )
    assert resident.state == "settled" and resident.current_zone == "b"
    assert _episode(engine, receiving).status == "clear"
    assert not before.traversal_tokens and not before.pending_candidates
    assert bool(before.retained_traversal_tokens) == (frontier == 302)
    assert bool(before.support_token_bindings) == (frontier == 302)
    assert _policy(engine, "b").active == (frontier == 302)
    expected_kind = "refreshed" if frontier == 302 else "acquired"
    resident_bindings = tuple(
        binding for binding in before.support_token_bindings
        if binding.support_id == resident.support_id
    )
    expected_winner = min(source.support_id, resident.support_id)
    expected_created = min(source.created_at, resident.created_at)
    assert expected_created == _at(2)
    if reverse_creation:
        # Least ID was created later: preserve both independent writer choices.
        winner = next(
            s for s in before.anonymous_supports if s.support_id == expected_winner
        )
        assert winner.created_at == _at(5)
    counters = engine._supports.counters
    source_belief = _belief(engine, source_node)
    observed: list[PolicyEvent] = []
    prepare = engine._supports.prepare_handoff

    def callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert authorization is not None and authorization.settled_handoff is not None
        assert authorization.settled_handoff.support_id == source.support_id
        assert authorization.settled_handoff.source_node_id == source_node
        assert decision.active_after and event.kind == expected_kind
        assert engine.snapshot.anonymous_supports == before.anonymous_supports
        assert engine._supports.counters == counters
        observed.append(event)

    with (
        patch.object(engine._supports, "prepare_handoff", wraps=prepare) as prepared,
        patch.object(engine._supports, "apply", wraps=engine._supports.apply) as commit,
    ):
        result = engine.observe(
            _input("b", "on", frontier), decision_callback=callback,
        )
        assert prepared.call_count == commit.call_count == 1
        proposal = commit.call_args.kwargs["prepared_handoff"]
        assert proposal.supports == result.snapshot.anonymous_supports
        assert proposal.bindings == result.snapshot.support_token_bindings
    assert result.authorizations[0].reason == "settled_adjacent_transfer"
    assert [(event.zone, event.kind) for event in observed] == [("b", expected_kind)]
    merged, = result.snapshot.anonymous_supports
    assert merged.support_id == expected_winner
    assert merged.created_at == expected_created
    assert merged.current_node_id == "b" and merged.current_zone == "b"
    assert merged.updated_at == _at(frontier)
    assert merged.path_node_ids == (source_node, "b")
    assert merged.last_transition == "coalesced" and merged.valid_until is None
    assert result.snapshot.support_token_bindings == tuple(
        sorted(
            (
                SupportTokenBinding(_token(engine, "b").token_id, expected_winner),
                *(SupportTokenBinding(binding.token_id, expected_winner)
                  for binding in resident_bindings),
            ),
            key=lambda binding: binding.token_id,
        )
    )
    assert result.snapshot.retained_traversal_tokens == before.retained_traversal_tokens
    purged_source_ids = {
        binding.token_id for binding in before.support_token_bindings
        if binding.support_id == source.support_id
    }
    assert not purged_source_ids & {
        binding.token_id for binding in result.snapshot.support_token_bindings
    }
    latest = engine._supports.latest_transition
    assert latest is not None and latest.reason == "same_zone"
    assert latest.coalesced_support_ids == tuple(
        sorted((source.support_id, resident.support_id))
    )
    assert engine._supports.counters["support_created"] == counters["support_created"]
    assert engine._supports.counters["support_coalesced"] == (
        counters["support_coalesced"] + 1
    )
    assert _belief(engine, source_node) == source_belief
    assert not engine._pending_prediction_learning
    after = engine.snapshot
    assert engine.observe(_input("b", "on", frontier)).snapshot == after
    assert engine._supports.counters["support_coalesced"] == (
        counters["support_coalesced"] + 1
    )


@pytest.mark.parametrize("correlated", (False, True))
def test_full_64_token_bound_evicts_selected_origin_without_losing_either_support(
    correlated: bool,
) -> None:
    """Real independent pulses fill capacity without creating a third support."""
    engine = _seed(
        _map(second=True, filler_tokens=62), second=True, correlated=correlated,
    )
    for node in ("x", "y", "u", "v"):
        engine.observe(_input(node, "unavailable", 302))
    assert len(engine.snapshot.retained_traversal_tokens) == 2
    engine.observe(_input("z", "off", 303))
    for index in range(62):
        result = engine.observe(
            SensorInput(f"event.filler_{index}", "pressed", _at(304 + index / 1000)),
        )
        assert result.authorizations[0].reason == "local_interaction"
        assert len(result.snapshot.anonymous_supports) == 2
    engine.commit_prediction_learning()
    engine.advance(_at(305))
    before = engine.snapshot
    assert engine._frontier._token_limit == 64
    assert len(before.traversal_tokens) == 62
    assert len(before.retained_traversal_tokens) == 2
    _assert_source(engine)
    source = next(s for s in before.anonymous_supports if s.current_node_id == "a")
    other = next(s for s in before.anonymous_supports if s.current_node_id == "z")
    origin_id = source.support_id.removeprefix("support:")
    assert SupportTokenBinding(origin_id, source.support_id) in (
        before.support_token_bindings
    )
    learned = engine.prediction_manager.serialize()
    result = _handoff(engine, 305)
    assert len(result.snapshot.traversal_tokens) == 63
    assert len(result.snapshot.retained_traversal_tokens) == 1
    assert result.snapshot.retained_traversal_tokens == tuple(
        token for token in before.retained_traversal_tokens
        if token.token_id != origin_id
    )
    assert other in result.snapshot.anonymous_supports
    moved = next(s for s in result.snapshot.anonymous_supports if s != other)
    assert (moved.support_id, moved.created_at) == (
        source.support_id, source.created_at,
    )
    assert moved.current_node_id == "b" and moved.path_node_ids == ("a", "b")
    assert result.snapshot.support_token_bindings == tuple(
        sorted(
            (
                SupportTokenBinding(_token(engine, "b").token_id, source.support_id),
                *(binding for binding in before.support_token_bindings
                  if binding.support_id == other.support_id),
            ),
            key=lambda binding: binding.token_id,
        )
    )
    known_ids = {token.token_id for token in (
        *result.snapshot.traversal_tokens, *result.snapshot.retained_traversal_tokens,
    )}
    assert len(known_ids) == 64 and origin_id not in known_ids
    assert all(
        binding.token_id in known_ids
        for binding in result.snapshot.support_token_bindings
    )
    assert all(use.token_id in known_ids for use in result.snapshot.authorization_uses)
    assert engine.diagnostic_counters["support_created"] == 2
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    assert engine.observe(_input("b", "on", 305)).snapshot == result.snapshot
