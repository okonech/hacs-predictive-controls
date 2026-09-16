"""Retained TRAV-018 component lifecycle and separate PATH integration proofs.

Original IDs and physical streams remain at the authentic component boundary;
their historical names do not assert selected-engine transfers. Additive
test_selected_* counterparts exercise today's unmodified engine independently.
These synthetic qualifications never replace or retime a frozen incident.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import overload
from unittest.mock import patch

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.supports import (
    PreparedSupportUpdate,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    SupportTokenBinding,
    SupportTransition,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
    ZonePolicyState,
)
from tests.handoff_lifecycle_fixture import component_arrival
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    restore_components,
)
from tests.test_zone_model_persistence import structural_payload

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


def _episode(
    engine: ZoneModelEngine | PersistenceComponents, node: str,
) -> EpisodeState:
    return next(s for s in engine.snapshot.episode_states if s.node_id == node)


def _belief(
    engine: ZoneModelEngine | PersistenceComponents, node: str,
) -> ZoneBeliefState:
    return next(s for s in engine.snapshot.belief_states if s.zone == node)


def _policy(
    engine: ZoneModelEngine | PersistenceComponents, node: str,
) -> ZonePolicyState:
    return next(s for s in engine.snapshot.policy_states if s.zone == node)


def _token(engine: PersistenceComponents, node: str) -> TraversalToken:
    episode_id = _episode(engine, node).episode_id
    return next(
        t for t in engine.snapshot.traversal_tokens if t.episode_id == episode_id
    )


@overload
def _round_trip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> ZoneModelEngine: ...


@overload
def _round_trip(
    predictive_map: PredictiveMap, engine: PersistenceComponents,
) -> PersistenceComponents: ...


def _round_trip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine | PersistenceComponents,
) -> ZoneModelEngine | PersistenceComponents:
    if isinstance(engine, PersistenceComponents):
        # Tagged component codecs/crosslinks, NOT the selected whole-state reader.
        payload = component_wire(predictive_map, engine)
        components = restore_components(
            predictive_map, payload, engine.snapshot.updated_at,
        )
        assert components.snapshot == engine.snapshot
        assert component_wire(predictive_map, components) == payload
        return components
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, restored) == payload
    return restored


def _seed(
    predictive_map: PredictiveMap, count: int = 2, *, frontier: float = 302,
    second: bool = False, correlated: bool = False,
    token_capacity: int = 64,
) -> PersistenceComponents:
    """Original history at the legacy component boundary; not engine seeding."""
    engine = PersistenceComponents(predictive_map, count, _at(-41))
    engine.frontier._token_limit = token_capacity
    if correlated:
        # Prime B while no support or traversal exists, before creating source A.
        primed = component_arrival(engine, _input("b", "on", -40))
        assert primed.authorizations[0].reason == "track_bootstrap_pending"
        assert not primed.policy_events and not primed.snapshot.anonymous_supports
        engine.observe(_input("b", "off", -30))
    for offset, node in enumerate(("x", "y", "a")):
        result = component_arrival(engine, _input(node, "on", offset))
    assert result.authorizations[0].track_confidence == "confirmed"
    support, = engine.snapshot.anonymous_supports
    assert support.current_node_id == "a" and support.state == "settled"
    assert support.path_node_ids == ("x", "y", "a")
    assert support.created_at == _at(2)
    if second:
        for offset, node in enumerate(("u", "v", "z"), start=3):
            component_arrival(engine, _input(node, "on", offset))
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
    assert not engine.learning
    assert not _policy(engine, "b").active
    assert _episode(engine, "a").started_at == _at(2)
    return engine


def _assert_source(engine: PersistenceComponents, node: str = "a") -> None:
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


def _handoff(engine: PersistenceComponents, seconds: float = 302) -> ZoneModelResult:
    _assert_source(engine)
    result = component_arrival(engine, _input("b", "on", seconds))
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
    assert not engine.learning
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
    ordering: list[str] = []
    counters = engine.supports.counters
    commit_impl = engine.supports.commit_prepared
    count_impl = engine.evaluate_count_conflicts

    def commit_after_publication(proposal: PreparedSupportUpdate) -> SupportTransition:
        assert ordering == ["publication"] and len(observed) == 1
        assert engine.snapshot.anonymous_supports == (source,)
        assert engine.snapshot.support_token_bindings == bindings
        assert engine.supports.counters == counters
        assert proposal.owner is engine.supports and proposal.at == _at(302)
        transition = commit_impl(proposal)
        assert transition == proposal.transition
        ordering.append("commit")
        return transition

    def count_after_commit(at: datetime) -> None:
        assert ordering == ["publication", "commit"]
        committed, = engine.snapshot.anonymous_supports
        assert committed.support_id == source.support_id
        assert committed.current_node_id == "b" and committed.updated_at == at
        assert engine.snapshot.support_token_bindings == (
            SupportTokenBinding(_token(engine, "b").token_id, source.support_id),
        )
        assert len(observed) == 1
        count_impl(at)
        ordering.append("count")

    with (
        patch.object(
            engine.supports, "prepare_handoff", wraps=engine.supports.prepare_handoff,
        ) as prepare,
        patch.object(
            engine.supports, "prepare", wraps=engine.supports.prepare,
        ) as prepare_support,
        patch.object(
            engine.supports, "commit_prepared", side_effect=commit_after_publication,
        ) as commit,
        patch.object(
            engine, "evaluate_count_conflicts", side_effect=count_after_commit,
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
            # prepare computes a detached prospective result; commit_prepared
            # counts its live event commit, NOT advance()'s elapsed _commit calls.
            assert prepare.call_count == prepare_support.call_count == 1
            assert commit.call_count == count.call_count == 0
            assert engine.snapshot.anonymous_supports == (source,)
            assert engine.snapshot.support_token_bindings == bindings
            assert engine.supports.counters == counters
            assert not ordering
            ordering.append("publication")
            observed.append(event)
            if failure:
                raise RuntimeError("synthetic subscriber failure")

        if failure:
            with pytest.raises(RuntimeError, match="synthetic subscriber failure"):
                component_arrival(
                    engine, _input("b", "on", 302), decision_callback=callback,
                )
        else:
            result = component_arrival(
                engine, _input("b", "on", 302), decision_callback=callback,
            )
            assert result.policy_events == tuple(observed)
            assert result.disposition == (
                "accepted_correlated_positive" if correlated else "accepted_positive"
            )
        assert prepare.call_count == prepare_support.call_count == 1
        assert commit.call_count == count.call_count == 1
        assert ordering == ["publication", "commit", "count"]
        prepared = commit.call_args.args[0]
        assert prepared.transition.supports == engine.snapshot.anonymous_supports
        assert prepared.transition.bindings == engine.snapshot.support_token_bindings
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
    assert not engine.learning
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
    """PATH/TRAV-006: current preparation seam, not unreachable legacy handoff."""
    engine = _selected_seed(_map())
    supports = engine.snapshot.anonymous_supports
    with (
        patch.object(
            engine._supports, "prepare",
            side_effect=ValueError("invalid proposal"),
        ),
        patch.object(
            engine, "_evaluate_policies", wraps=engine._evaluate_policies,
        ) as publish,
        patch.object(
            engine._supports, "commit_prepared", wraps=engine._supports.commit_prepared,
        ) as commit,
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
    result = component_arrival(engine, _input("b", "on", at))
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
    # TRAV-018 component rejection; PATH-003 live pairing is tested separately.
    engine = PersistenceComponents(predictive_map, 2, _at(-1))
    if bootstrap:
        engine.bootstrap_sensor_snapshot((_input("a", "on", 2),), _at(2))
    else:
        first = component_arrival(engine, _input("a", "on", 2))
        assert first.authorizations[0].reason == "track_bootstrap_pending"
    engine.advance(_at(7202))
    assert _episode(engine, "a").known_on
    assert _belief(engine, "a").probability >= 0.7
    assert not engine.snapshot.anonymous_supports
    result = component_arrival(engine, _input("b", "on", 7202))
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
    result = component_arrival(engine, _input("b", "on", 302))
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
        engine.supports, "settled_adjacent_for",
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
        engine.supports, "settled_adjacent_for",
        side_effect=AssertionError("stale lookup"),
    ):
        stale = engine.observe(_input("b", "on", 301), processing_at=_at(303))
    assert stale.disposition == "stale" and stale.snapshot == before
    assert not stale.policy_events and not stale.authorizations
    _handoff(engine)
    counters = engine.diagnostic_counters
    after = engine.snapshot
    with patch.object(
        engine.supports, "settled_adjacent_for",
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
        component_arrival(engine, _input("a", "on", 3903))
        at, target, reason = 3904, "b", "adjacent_authorized"
        _assert_source(engine)
    elif authority == "pending":
        pending = component_arrival(engine, _input("c", "on", 302))
        assert pending.authorizations[0].reason == "track_bootstrap_pending"
        assert not pending.policy_events
        at, target, reason = 303, "b", "provisional_track_acquired"
        _assert_source(engine)
    else:
        engine.observe(_input("a", "off", 302))
        engine.advance(_at(3902))
        at, target, reason = 3903, "a", "settled_endpoint_reacquired"
    with patch.object(
        engine.supports, "settled_adjacent_for",
        side_effect=AssertionError("eager fallback"),
    ):
        result = component_arrival(engine, _input(target, "on", at))
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
) -> tuple[PredictiveMap, PersistenceComponents]:
    """POLICY-013/COUNT-011: expired traversal is not an expired active endpoint."""
    predictive_map = _map(target="pir" if pir else "presence")
    engine = _seed(predictive_map, count)
    _handoff(engine)
    original, = engine.snapshot.anonymous_supports
    learned = engine.prediction_manager.serialize()
    clear = engine.observe(_input("b", "off", 312))
    expired = engine.advance(_at(3902))
    assert not engine.snapshot.traversal_tokens
    assert not engine.snapshot.retained_traversal_tokens
    assert not engine.snapshot.support_token_bindings
    assert _episode(engine, "b").status == "clear"
    policy, belief = _policy(engine, "b"), _belief(engine, "b")
    assert policy.active and policy.retained_endpoint_hold
    assert policy.pending_release_since is None
    assert belief.probability < POLICY_CALIBRATIONS[belief.profile_name].off_threshold
    assert belief.qualified_departure_at is None
    assert not any(
        event.zone == "b" and event.kind in {"acquired", "released"}
        for result in (clear, expired) for event in result.policy_events
    )
    assert engine.snapshot.anonymous_supports == (original,)
    restored = _round_trip(predictive_map, engine)
    rebind = component_arrival(engine, _input("b", "on", 3903))
    assert component_arrival(restored, _input("b", "on", 3903)) == rebind
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
    assert _policy(engine, "b").active
    assert [(e.zone, e.kind, e.event_at) for e in rebind.policy_events] == [
        ("b", "refreshed", _at(3903))
    ]
    assert not engine.learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    _round_trip(predictive_map, engine)
    return predictive_map, engine


@pytest.mark.parametrize("count", (1, 2))
def test_retained_expired_pair_rebind_needs_fresh_b_c_d_and_strict_restore_before_d(
    count: int,
) -> None:
    """Replace test_expired_pair_rebind_needs_fresh_b_c_d_and_strict_restore_before_d.

    REQ-POLICY-013/005 replace timeout OFF/acquired with retained ON/refreshed;
    REQ-TRAV-016/018, COUNT-011 and STATE-010 retain expiry, B-C-D and strict restore.
    """
    predictive_map, engine = _expired_pair_rebind(count)
    original, = engine.snapshot.anonymous_supports
    learned = engine.prediction_manager.serialize()
    result = component_arrival(engine, _input("c", "on", 3904))
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
    assert not engine.learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    # Crucial: restore BEFORE a third node can hide the short support path.
    restored = _round_trip(predictive_map, engine)
    expected = component_arrival(engine, _input("d", "on", 3905))
    assert component_arrival(restored, _input("d", "on", 3905)) == expected
    confirmed, = expected.authorizations
    assert confirmed.path_node_ids == ("b", "c", "d")
    assert confirmed.track_confidence == "confirmed"
    assert confirmed.reason == "track_confirmed"
    assert [(e.zone, e.kind) for e in expected.policy_events] == [("d", "acquired")]
    assert engine.learning
    counts_before = engine.prediction_manager.chain.counts["c"]["d"]
    engine.commit_prediction_learning()
    restored.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["d"] == counts_before + 1
    assert component_wire(predictive_map, restored) == (
        component_wire(predictive_map, engine)
    )
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
def test_live_original_pair_confirms_only_next_independent_node(count: int) -> None:
    predictive_map = _map()
    engine = _seed(predictive_map, count)
    _handoff(engine)
    assert not engine.learning
    restored = _round_trip(predictive_map, engine)
    result = component_arrival(engine, _input("c", "on", 303))
    assert component_arrival(restored, _input("c", "on", 303)) == result
    authorization, = result.authorizations
    assert authorization.path_node_ids == ("a", "b", "c")
    assert authorization.reason == "track_confirmed"
    assert authorization.track_confidence == "confirmed"
    assert _token(engine, "c").path_node_ids == ("a", "b", "c")
    assert engine.learning
    engine.commit_prediction_learning()
    restored.commit_prediction_learning()
    assert component_wire(predictive_map, restored) == (
        component_wire(predictive_map, engine)
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
    result = component_arrival(engine, _input("b", "on", 503))
    assert component_arrival(restored, _input("b", "on", 503)) == result
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
    assert not engine.learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    _round_trip(predictive_map, engine)


def test_retained_rebound_pair_backtracking_never_confirms_or_teaches_third_node(
) -> None:
    """Replace test_rebound_pair_backtracking_never_confirms_or_teaches_third_node.

    REQ-POLICY-013 retains B, not its expired traversal authority. REQ-TRAV-016/018
    still forbid two-node backtracking from confirming or teaching a third node.
    """
    predictive_map, engine = _expired_pair_rebind(pir=True)
    learned = engine.prediction_manager.serialize()
    component_arrival(engine, _input("c", "on", 3904))
    for node, clear_at, positive_at in (("b", 3905, 3945), ("c", 3946, 3986)):
        engine.observe(_input(node, "off", clear_at))
        result = component_arrival(engine, _input(node, "on", positive_at))
        assert result.disposition == "accepted_positive"
        authorization, = result.authorizations
        assert authorization.track_confidence == "provisional"
        assert set(authorization.path_node_ids) == {"b", "c"}
        assert not authorization.equivalent_confirmed_strength
        assert _token(engine, node).track_confidence == "provisional"
        assert not engine.learning
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
        component_arrival(engine, _input("a", "on", 304))
        assert _episode(engine, "a").episode_id != source_id[0]
    else:
        assert _episode(engine, "a").status == "unavailable"
        assert engine.snapshot.anonymous_supports == (support,)
    assert _policy(engine, "b").active
    assert _policy(engine, "b").activation_source_episode_ids == source_id
    if not audit:
        # Optional audit is not required to validate historical physical proof.
        payload = component_wire(predictive_map, engine)
        payload["audit"] = []
        engine = restore_components(predictive_map, payload, engine.snapshot.updated_at)
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
        engine.supports, "settled_adjacent_for",
        side_effect=AssertionError("flap attempted departure selection"),
    ):
        result = engine.observe(_input("b", "on", 304))
    assert _episode(engine, "b").episode_id == episode_id
    assert not result.authorizations and not result.policy_events
    assert engine.diagnostic_counters["support_transferred"] == transfers
    assert not engine.learning
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
    prepare = engine.supports.prepare_handoff
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

    with patch.object(engine.supports, "prepare_handoff", wraps=prepare) as prepared:
        result = component_arrival(
            engine, _input("b", "on", 302), decision_callback=callback,
        )
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
    assert not engine.learning
    retry = engine.observe(_input("b", "on", 302))
    assert retry.snapshot == result.snapshot and not retry.policy_events


@pytest.mark.parametrize("receiving", ("a", "z"))
@pytest.mark.parametrize("reverse_creation", (False, True))
@pytest.mark.parametrize("frontier", (302, 3902))
def test_retained_receiving_zone_collision_coalesces_with_least_id_min_creation(
    receiving: str, reverse_creation: bool, frontier: int,
) -> None:
    """Replace the timeout-only receiving-zone collision oracle.

    Replaces:
    test_receiving_zone_collision_coalesces_after_selection_with_least_id_min_creation.
    REQ-POLICY-013/005 require retained ON/refreshed at both frontiers; COUNT-008/011
    and TRAV-018 preserve selection, least-ID/min-creation coalescence and ordering.
    """
    predictive_map = _map(second=True, receiving=receiving)
    engine = PersistenceComponents(predictive_map, 2, _at(-1))
    routes: tuple[tuple[str, ...], ...] = (("x", "y", "a"), ("u", "v", "z"))
    if reverse_creation:
        routes = tuple(reversed(routes))
    for seconds, node in enumerate(node for route in routes for node in route):
        component_arrival(engine, _input(node, "on", seconds))
    assert len(engine.snapshot.anonymous_supports) == 2
    assert _policy(engine, "b").active
    after_acquisition: list[PolicyEvent] = []
    for seconds, node in enumerate(("x", "y", "u", "v", receiving), start=10):
        cleared = engine.observe(_input(node, "off", seconds))
        after_acquisition.extend(cleared.policy_events)
        assert _policy(engine, "b").active
    engine.commit_prediction_learning()
    elapsed = engine.advance(_at(frontier))
    after_acquisition.extend(elapsed.policy_events)
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
    assert _policy(engine, "b").active and _policy(engine, "b").retained_endpoint_hold
    assert _policy(engine, "b").pending_release_since is None
    assert not any(
        event.zone == "b" and event.kind in {"acquired", "released"}
        for event in after_acquisition
    )
    expected_kind = "refreshed"
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
    counters = engine.supports.counters
    source_belief = _belief(engine, source_node)
    observed: list[PolicyEvent] = []
    ordering: list[str] = []
    prepare = engine.supports.prepare_handoff
    commit_impl = engine.supports.commit_prepared
    count_impl = engine.evaluate_count_conflicts

    def commit_after_publication(proposal: PreparedSupportUpdate) -> SupportTransition:
        assert ordering == ["publication"] and len(observed) == 1
        assert engine.snapshot.anonymous_supports == before.anonymous_supports
        assert engine.supports.counters == counters
        assert proposal.owner is engine.supports and proposal.at == _at(frontier)
        transition = commit_impl(proposal)
        assert transition == proposal.transition
        ordering.append("commit")
        return transition

    def count_after_commit(at: datetime) -> None:
        assert ordering == ["publication", "commit"]
        committed, = engine.snapshot.anonymous_supports
        assert committed.support_id == expected_winner
        assert committed.created_at == expected_created
        assert committed.current_node_id == "b" and committed.updated_at == at
        assert committed.last_transition == "coalesced"
        assert engine.supports.counters["support_coalesced"] == (
            counters["support_coalesced"] + 1
        )
        count_impl(at)
        ordering.append("count")

    def callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert authorization is not None and authorization.settled_handoff is not None
        assert authorization.settled_handoff.support_id == source.support_id
        assert authorization.settled_handoff.source_node_id == source_node
        assert decision.active_after and event.kind == expected_kind
        assert engine.snapshot.anonymous_supports == before.anonymous_supports
        assert engine.supports.counters == counters
        assert prepared.call_count == prepare_support.call_count == 1
        assert commit.call_count == count.call_count == 0
        assert not ordering
        ordering.append("publication")
        observed.append(event)

    with (
        patch.object(engine.supports, "prepare_handoff", wraps=prepare) as prepared,
        patch.object(
            engine.supports, "prepare", wraps=engine.supports.prepare,
        ) as prepare_support,
        patch.object(
            engine.supports, "commit_prepared", side_effect=commit_after_publication,
        ) as commit,
        patch.object(
            engine, "evaluate_count_conflicts", side_effect=count_after_commit,
        ) as count,
    ):
        result = component_arrival(
            engine, _input("b", "on", frontier), decision_callback=callback,
        )
        assert prepared.call_count == prepare_support.call_count == 1
        assert commit.call_count == count.call_count == 1
        assert ordering == ["publication", "commit", "count"]
        proposal = commit.call_args.args[0]
        assert proposal.transition.supports == result.snapshot.anonymous_supports
        assert proposal.transition.bindings == result.snapshot.support_token_bindings
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
    latest = engine.supports.latest_transition
    assert latest is not None and latest.reason == "same_zone"
    assert latest.coalesced_support_ids == tuple(
        sorted((source.support_id, resident.support_id))
    )
    assert engine.supports.counters["support_created"] == counters["support_created"]
    assert engine.supports.counters["support_coalesced"] == (
        counters["support_coalesced"] + 1
    )
    assert _belief(engine, source_node) == source_belief
    assert not engine.learning
    after = engine.snapshot
    assert engine.observe(_input("b", "on", frontier)).snapshot == after
    assert engine.supports.counters["support_coalesced"] == (
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
        result = component_arrival(
            engine,
            SensorInput(f"event.filler_{index}", "pressed", _at(304 + index / 1000)),
        )
        assert result.authorizations[0].reason == "local_interaction"
        assert len(result.snapshot.anonymous_supports) == 2
    engine.commit_prediction_learning()
    engine.advance(_at(305))
    before = engine.snapshot
    assert engine.frontier._token_limit == 64
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
    assert not engine.learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == learned
    assert engine.observe(_input("b", "on", 305)).snapshot == result.snapshot


def _selected_seed(
    predictive_map: PredictiveMap, count: int = 2, *, frontier: float = 302,
    second: bool = False, correlated: bool = False,
) -> ZoneModelEngine:
    """Same original physical stream, without legacy support prerequisites."""
    engine = ZoneModelEngine(predictive_map, count, _at(-41))
    if correlated:
        engine.observe(_input("b", "on", -40))
        engine.observe(_input("b", "off", -30))
    for seconds, node in enumerate(("x", "y", "a")):
        engine.observe(_input(node, "on", seconds))
    if second:
        for seconds, node in enumerate(("u", "v", "z"), 3):
            engine.observe(_input(node, "on", seconds))
    for seconds, node in enumerate(("x", "y", *(("u", "v") if second else ())), 10):
        engine.observe(_input(node, "off", seconds))
    engine.commit_prediction_learning()
    engine.advance(_at(frontier))
    assert not engine.snapshot.anonymous_supports
    assert not engine.snapshot.traversal_tokens
    assert not engine._pending_prediction_learning
    return engine


def _assert_selected_arrival(
    engine: ZoneModelEngine, before: ZoneModelResult | None, result: ZoneModelResult,
    *, target: str = "b",
) -> None:
    """PATH001/003/004: actual source, one slot, no legacy issuance or learning."""
    authorization, = result.authorizations
    assert authorization.authorized and authorization.reason == "selected_path"
    assert authorization.path_node_ids[-1] == target
    assert authorization.selected_source_episode_ids
    assert not authorization.source_tokens and not authorization.new_uses
    assert authorization.settled_handoff is None
    assert _policy(engine, target).active
    assert not result.snapshot.traversal_tokens
    assert not result.snapshot.retained_traversal_tokens
    assert not result.snapshot.anonymous_supports
    assert not result.snapshot.support_token_bindings
    assert not engine._pending_prediction_learning
    assert len(result.snapshot.selected_paths) == (
        result.snapshot.count_state.expected_count
    )
    if before is not None:
        # Slots are an anonymous canonical multiset, not stable positional IDs.
        unchanged = Counter(before.snapshot.selected_paths) & Counter(
            result.snapshot.selected_paths,
        )
        assert sum(unchanged.values()) == len(result.snapshot.selected_paths) - 1


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("bootstrap", (False, True), ids=("live", "bootstrap"))
def test_selected_live_origin_pairs_but_bootstrap_does_not(
    count: int, bootstrap: bool,
) -> None:
    """PATH003 replaces only the production no-support rejection, not TRAV018."""
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, count, _at(-1))
    if bootstrap:
        engine.bootstrap_sensor_snapshot((_input("a", "on", 2),), _at(2))
    else:
        engine.observe(_input("a", "on", 2))
    engine.advance(_at(7202))
    assert _episode(engine, "a").known_on and _belief(engine, "a").probability >= 0.7
    restored = _round_trip(predictive_map, engine)
    before = ZoneModelResult("advanced", engine.snapshot)
    result = engine.observe(_input("b", "on", 7202))
    assert restored.observe(_input("b", "on", 7202)) == result
    assert not _policy(engine, "a").active  # never retroactively acquire the origin
    assert _policy(engine, "b").active == (not bootstrap)
    if bootstrap:
        assert not result.authorizations[0].authorized and not result.policy_events
        assert all(path is None for path in result.snapshot.selected_paths)
    else:
        _assert_selected_arrival(engine, before, result)
        assert [(e.zone, e.kind) for e in result.policy_events] == [("b", "acquired")]
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("age", (7200, 86400))
@pytest.mark.parametrize("target", ("presence", "transition"))
def test_selected_long_age_and_cleared_endpoint_have_no_legacy_token_ttl(
    count: int, age: int, target: str,
) -> None:
    """PATH002/003: original ages and exact180/45s checkpoints are not slot TTLs."""
    predictive_map = _map(target=target)
    engine = _selected_seed(predictive_map, count, frontier=age + 2)
    source = _episode(engine, "a")
    assert source.started_at == _at(2)
    assert source.assertion_trust_until is not None
    assert source.assertion_trust_until < engine.snapshot.updated_at
    before = engine.advance(_at(age + 2))
    assert engine.advance(_at(age + 2)).snapshot == before.snapshot
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", age + 2))
    assert restored.observe(_input("b", "on", age + 2)) == result
    _assert_selected_arrival(engine, before, result)
    assert _episode(engine, "a") == source
    engine.observe(_input("b", "off", age + 12))
    slots = engine.snapshot.selected_paths
    deadline = _at(age + 2 + (180 if target == "presence" else 45))
    for at in (deadline - EPSILON, deadline, deadline + EPSILON, _at(age + 3902)):
        engine.advance(at)
        assert _policy(engine, "b").active
        assert [
            p.endpoint.node_id if p else None for p in engine.snapshot.selected_paths
        ] == [
            p.endpoint.node_id if p else None for p in slots
        ]
        assert not engine.snapshot.traversal_tokens
        _round_trip(predictive_map, engine)


@pytest.mark.parametrize("fault", ("clearing", "clear", "unknown", "unavailable"))
def test_selected_source_faults_preserve_retained_endpoint(fault: str) -> None:
    """PATH002: loss of source usability never erases its selected occupancy."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    engine.observe(_input("a", "off" if fault in {"clearing", "clear"} else fault, 302))
    at = 313 if fault == "clear" else 303
    engine.advance(_at(at))
    assert any(
        p is not None and p.endpoint.node_id == "a"
        for p in engine.snapshot.selected_paths
    )
    assert _policy(engine, "a").active
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", at))
    assert restored.observe(_input("b", "on", at)) == result
    if fault in {"clearing", "clear"}:
        _assert_selected_arrival(engine, None, result)
    else:
        assert not result.authorizations[0].authorized
        assert not _policy(engine, "b").active
        assert any(
            p is not None and p.endpoint.node_id == "a"
            for p in result.snapshot.selected_paths
        )
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize(
    "remove_second", (False, True), ids=("ambiguous", "one-healthy"),
)
@pytest.mark.parametrize("correlated", (False, True))
def test_selected_two_source_choice_is_deterministic_not_legacy_ambiguity(
    remove_second: bool, correlated: bool,
) -> None:
    """PATH001: latest eligible Z wins; OFF alone does not disqualify its endpoint."""
    predictive_map = _map(second=True)
    engine = _selected_seed(predictive_map, second=True, correlated=correlated)
    if remove_second:
        engine.observe(_input("z", "off", 302))
    before = ZoneModelResult("advanced", engine.snapshot)
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", 302))
    assert restored.observe(_input("b", "on", 302)) == result
    _assert_selected_arrival(engine, before, result)
    assert result.authorizations[0].selected_source_episode_ids == (
        _episode(engine, "z").episode_id,
    )
    assert result.authorizations[0].path_node_ids == ("v", "z", "b")
    assert any(
        p is not None and p.endpoint.node_id == "a"
        for p in result.snapshot.selected_paths
    )
    assert engine.observe(_input("b", "on", 302)).snapshot == result.snapshot
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize("failure", (None, "result", "b", "c"))
def test_selected_committed_result_precedes_edges_and_audit(
    correlated: bool, failure: str | None,
) -> None:
    """PUBLIC001/PATH-STATE/PRED008: committed metadata, true edges, deferred audit.

Ordinary B emits B acquisition and mature C prediction, so failure at C is a
genuine later subscriber failure. Correlated B cannot prepare that prediction.
No expected list is changed to bless work done before an external callback.
"""
    predictive_map = _map()
    engine = _selected_seed(predictive_map, correlated=correlated)
    for _ in range(10):
        assert engine.prediction_manager.chain.observe("b", "c")
    counts = deepcopy(engine.prediction_manager.chain.counts)
    prior_audit = engine.audit_rows
    publications: list[str] = []
    committed: list[ZoneModelResult] = []
    receivers: list[ZoneModelEngine] = []
    injected = RuntimeError("synthetic selected subscriber failure")
    with ExitStack() as stack:
        flushes = [stack.enter_context(patch.object(
            policy.audit, "flush_deferred", wraps=policy.audit.flush_deferred,
        )) for policy in engine._policies.values()]
        support_commit = stack.enter_context(patch.object(
            engine._supports, "commit_prepared", wraps=engine._supports.commit_prepared,
        ))
        count = stack.enter_context(patch.object(
            engine, "_apply_count_conflicts", wraps=engine._apply_count_conflicts,
        ))

        def inspect_committed() -> None:
            assert engine._in_decision_callback
            assert engine.snapshot.updated_at == _at(302)
            assert support_commit.call_count == 1 and count.call_count >= 1
            assert engine.audit_rows == prior_audit
            assert all(spy.call_count == 0 for spy in flushes)
            assert engine.prediction_manager.chain.counts == counts
            assert not engine._pending_prediction_learning
            assert _policy(engine, "b").activation_reason == "selected_path"
            assert _policy(engine, "b").activation_source_episode_ids == (
                _episode(engine, "a").episode_id,
            )
            assert _belief(engine, "b").physical_hold
            health = next(h for h in engine.snapshot.path_health if h.node_id == "b")
            assert health.phase == "on" and health.on_started_at == _at(302)
            assert health.unsupported_started_at is None
            assert engine.snapshot.count_state.expected_count == 2
            assert not engine.snapshot.count_conflicts
            receivers.append(_round_trip(predictive_map, engine))

        def result_callback(result: ZoneModelResult) -> None:
            inspect_committed()
            assert result.snapshot == engine.snapshot
            assert any(
                d.zone == "b" and d.active_after for d in result.policy_decisions
            )
            assert _policy(engine, "c").active == (not correlated)
            assert bool(result.snapshot.selected_prediction_grants) == (not correlated)
            assert bool(engine.prediction_manager.leases) == (not correlated)
            committed.append(result)
            publications.append("result")
            if failure == "result":
                raise injected

        def edge_callback(
            event: PolicyEvent, decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            inspect_committed()
            assert len(committed) == 1 and event in committed[0].policy_events
            assert decision in committed[0].policy_decisions
            if event.zone == "b":
                assert authorization == committed[0].authorizations[0]
            publications.append(event.zone)
            if failure == event.zone:
                raise injected

        raises = failure in {"result", "b"} or failure == "c" and not correlated
        if raises:
            with pytest.raises(
                RuntimeError, match="synthetic selected subscriber failure",
            ) as caught:
                engine.observe(
                    _input("b", "on", 302), result_callback=result_callback,
                    decision_callback=edge_callback,
                )
            assert caught.value is injected
        else:
            assert engine.observe(
                _input("b", "on", 302), result_callback=result_callback,
                decision_callback=edge_callback,
            ) == committed[0]
        expected = ["result"]
        if failure != "result":
            expected.append("b")
            if failure != "b" and not correlated:
                expected.append("c")
        assert publications == expected
        assert all(spy.call_count == 1 for spy in flushes)
    assert engine.snapshot == committed[0].snapshot
    assert any(
        row.zone == "b" and row.event_kind == "acquired" and row.event_at == _at(302)
        for row in engine.audit_rows
    )
    assert not engine._in_decision_callback
    # Callback receivers intentionally lack deferred audit, but inference and
    # actual next-event results must still be identical after callback failure.
    next_event = _input("c", "on", 303)
    result = engine.observe(next_event)
    assert all(receiver.observe(next_event) == result for receiver in receivers)
    assert engine.prediction_manager.chain.counts == counts
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("boundary", ("result", "edge"))
def test_selected_callback_reentry_is_atomic(boundary: str) -> None:
    """PATH-STATE001: every guarded public mutation rejects without any change."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    checked: list[str] = []

    def attempt() -> None:
        snapshot = engine.snapshot
        counters = engine.diagnostic_counters
        prediction = engine.prediction_manager.serialize()
        learning = tuple(engine._pending_prediction_learning)
        operations: tuple[tuple[str, Callable[[], object]], ...] = (
            ("observe", lambda: engine.observe(_input("c", "on", 303))),
            ("advance", lambda: engine.advance(_at(303))),
            ("count", lambda: engine.observe_count(
                CountInput("reentry", 0, True, _at(303)),
            )),
            ("bootstrap", lambda: engine.bootstrap_sensor_snapshot(
                (_input("b", "off", 303),), _at(303),
            )),
            ("learn", engine.commit_prediction_learning),
            ("prediction", lambda: engine.restore_prediction_state(
                prediction, _at(302),
            )),
            ("reconcile", lambda: engine.reconcile_restored_asserted_contexts(
                (_input("b", "on", 302),), _at(302),
            )),
        )
        for name, operation in operations:
            with pytest.raises(ValueError, match="Model mutation is forbidden"):
                operation()
            assert engine.snapshot == snapshot
            assert engine.diagnostic_counters == counters
            assert engine.prediction_manager.serialize() == prediction
            assert tuple(engine._pending_prediction_learning) == learning
            checked.append(name)

    def result_callback(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        if boundary == "result":
            attempt()

    def edge_callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "b" and decision.active_after and authorization is not None
        if boundary == "edge":
            attempt()

    engine.observe(
        _input("b", "on", 302), result_callback=result_callback,
        decision_callback=edge_callback,
    )
    assert len(checked) == 7 and not engine._in_decision_callback
    assert engine.observe(_input("c", "on", 303)).policy_events


def test_selected_preparation_failure_blocks_all_external_publication() -> None:
    """Real prepare failure occurs before policies, support commit and callbacks."""
    engine = _selected_seed(_map())
    publications: list[object] = []
    policies = engine.snapshot.policy_states
    supports = engine.snapshot.anonymous_supports
    with (
        patch.object(
            engine._supports, "prepare", side_effect=ValueError("invalid proposal"),
        ) as prepare,
        patch.object(
            engine, "_evaluate_policies", wraps=engine._evaluate_policies,
        ) as policy,
        patch.object(
            engine._supports, "commit_prepared", wraps=engine._supports.commit_prepared,
        ) as commit,
    ):
        with pytest.raises(ValueError, match="invalid proposal"):
            engine.observe(
                _input("b", "on", 302), result_callback=publications.append,
                decision_callback=lambda event, _decision, _authorization:
                    publications.append(event),
            )
        assert prepare.call_count == 1
        assert policy.call_count == commit.call_count == 0
    assert not publications and not engine._in_decision_callback
    assert engine.snapshot.policy_states == policies
    assert engine.snapshot.anonymous_supports == supports
    assert not engine._pending_prediction_learning


def test_selected_count_zero_recovery_and_replays_do_not_remint_paths() -> None:
    """COUNT001/PATH001: original controls and replay frontiers, no invented path."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    before = engine.snapshot
    assert engine.observe(
        _input("b", "on", 301), processing_at=_at(303),
    ).snapshot == before
    engine.observe_count(CountInput("empty", 0, True, _at(302)))
    empty = engine.observe(_input("b", "on", 303))
    assert not empty.authorizations and not empty.policy_events
    assert not empty.snapshot.selected_paths
    assert not any(policy.active for policy in empty.snapshot.policy_states)
    engine.observe_count(CountInput("occupied", 2, True, _at(304)))
    assert engine.snapshot.selected_paths == (None, None)
    result = engine.observe(_input("b", "on", 305))
    assert not result.authorizations and not result.policy_events
    assert result.snapshot.selected_paths == (None, None)
    assert engine.observe(_input("b", "on", 305)).snapshot == result.snapshot
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("pir", (False, True))
def test_selected_rebind_and_backtracking_never_learn(count: int, pir: bool) -> None:
    """PATH004/PRED008: retain original312/3902/B-C-D or PIR backtrack stream."""
    predictive_map = _map(target="pir" if pir else "presence")
    engine = _selected_seed(predictive_map, count)
    engine.observe(_input("b", "on", 302))
    engine.observe(_input("b", "off", 312))
    engine.advance(_at(3902))
    assert _policy(engine, "b").active and not engine.snapshot.traversal_tokens
    counts = deepcopy(engine.prediction_manager.chain.counts)
    rebound = engine.observe(_input("b", "on", 3903))
    _assert_selected_arrival(engine, None, rebound)
    assert [(e.zone, e.kind) for e in rebound.policy_events] == [("b", "refreshed")]
    leading = engine.observe(_input("c", "on", 3904))
    _assert_selected_arrival(engine, None, leading, target="c")
    assert [(e.zone, e.kind) for e in leading.policy_events] == [("c", "acquired")]
    restored = _round_trip(predictive_map, engine)  # BEFORE third D, as original
    if pir:
        events = tuple(_input(node, state, at) for node, state, at in (
            ("b", "off", 3905), ("b", "on", 3945),
            ("c", "off", 3946), ("c", "on", 3986),
        ))
    else:
        events = (_input("d", "on", 3905),)
    for event in events:
        result = engine.observe(event)
        assert restored.observe(event) == result
        if event.state == "on":
            node = event.entity_id.removeprefix("binary_sensor.")
            _assert_selected_arrival(engine, None, result, target=node)
            assert [(e.zone, e.kind) for e in result.policy_events] == [
                (node, "refreshed" if pir else "acquired"),
            ]
            assert any(
                path is not None and path.endpoint.node_id == node
                and path.endpoint.episode_id == _episode(engine, node).episode_id
                for path in result.snapshot.selected_paths
            )
        assert not engine._pending_prediction_learning
        assert not result.snapshot.traversal_tokens
        assert not result.snapshot.anonymous_supports
    assert engine.prediction_manager.chain.counts == counts
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("fault", ("unknown", "unavailable", "new-generation"))
@pytest.mark.parametrize("audit", (False, True), ids=("without-audit", "with-audit"))
def test_selected_historical_source_metadata_survives_strict_restore(
    fault: str, audit: bool,
) -> None:
    """STATE001/PATH-STATE: original source references are historical, not live."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    engine.observe(_input("b", "on", 302))
    source_ids = _policy(engine, "b").activation_source_episode_ids
    engine.observe(_input("a", "unknown" if fault == "new-generation" else fault, 303))
    if fault == "new-generation":
        engine.observe(_input("a", "on", 304))
        assert _episode(engine, "a").episode_id != source_ids[0]
    assert _policy(engine, "b").active
    assert _policy(engine, "b").activation_source_episode_ids == source_ids
    payload = serialize_target_state(predictive_map, engine)
    if not audit:
        payload["audit"] = []
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert restored.observe(_input("c", "on", 305)) == engine.observe(
        _input("c", "on", 305),
    )


def test_selected_diagnostic_health_is_committed_before_callbacks() -> None:
    """HEALTH001/003: exact600s warning recovers on real path before publication."""
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, 2, _at(-1))
    engine.observe(_input("a", "on", 2))
    engine.advance(_at(602) - EPSILON)
    assert not engine.snapshot.reliability_warning_occurrences
    engine.advance(_at(602))
    warning, = engine.snapshot.reliability_warning_occurrences
    assert warning.node_id == "a" and warning.cleared_at is None
    checked: list[ZoneModelResult] = []

    def callback(result: ZoneModelResult) -> None:
        recovered, = result.snapshot.reliability_warning_occurrences
        assert recovered.node_id == "a" and recovered.cleared_at == _at(7202)
        assert result.snapshot == engine.snapshot
        assert _policy(engine, "b").active and not _policy(engine, "a").active
        assert not result.snapshot.count_conflicts
        _round_trip(predictive_map, engine)
        checked.append(result)

    result = engine.observe(_input("b", "on", 7202), result_callback=callback)
    assert checked == [result]


def test_reachable_pending_learning_order_is_explicit() -> None:
    """PRED008/009: selected arrivals neither learn nor eagerly drain.

    The original b302/c303/d304 trace has no raw or folded learning debt.
    Genuine adjacent learning is qualified separately; its explicit drain must
    wait until after publication, even though this selected-only drain is inert.
    """
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    counts = deepcopy(engine.prediction_manager.chain.counts)
    empty_debt = {
        source: dict.fromkeys(node.adjacent)
        for source, node in predictive_map.nodes.items()
    }
    assert engine.prediction_state["deferred_counts"] == empty_debt
    with patch.object(
        engine.prediction_manager, "commit",
        wraps=engine.prediction_manager.commit,
    ) as commit:
        for node, at in (("b", 302), ("c", 303), ("d", 304)):
            result = engine.observe(_input(node, "on", at))
            assert result.authorizations[0].provenance_kind == "selected_path"
            assert not engine._pending_prediction_learning
            assert engine.prediction_state["deferred_counts"] == empty_debt
            assert engine.prediction_manager.chain.counts == counts
            commit.assert_not_called()
        before = engine.snapshot
        prediction_before = deepcopy(engine.prediction_state)
        assert engine.commit_prediction_learning() is False
        commit.assert_called_once_with(())
        assert not engine._pending_prediction_learning
        assert engine.prediction_manager.chain.counts == counts
        assert engine.prediction_state["deferred_counts"] == empty_debt
        assert engine.snapshot == before
        assert engine.prediction_state == prediction_before


@pytest.mark.parametrize("authority", ("ordinary", "pending", "endpoint"))
def test_selected_precedence_uses_current_path_not_legacy_fallback(
    authority: str,
) -> None:
    """PATH003: original rebind/pending streams; selected A outranks pending C."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map)
    if authority == "ordinary":
        engine.observe(_input("a", "off", 302))
        engine.advance(_at(3902))
        engine.observe(_input("a", "on", 3903))
        at, target = 3904, "b"
    elif authority == "pending":
        pending = engine.observe(_input("c", "on", 302))
        assert not pending.authorizations[0].authorized
        assert not pending.policy_events and not _policy(engine, "c").active
        at, target = 303, "b"
    else:
        engine.observe(_input("a", "off", 302))
        engine.advance(_at(3902))
        at, target = 3903, "a"
    restored = _round_trip(predictive_map, engine)
    with patch.object(
        engine._supports, "settled_adjacent_for",
        side_effect=AssertionError("selected path must precede fallback"),
    ):
        result = engine.observe(_input(target, "on", at))
    assert restored.observe(_input(target, "on", at)) == result
    _assert_selected_arrival(engine, None, result, target=target)
    assert result.authorizations[0].path_node_ids[-2:] == ("a", target)
    assert not any(p.node_id == target for p in result.snapshot.pending_candidates)
    if authority == "pending":
        assert not _policy(engine, "c").active
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
def test_selected_replay_and_same_episode_flap_do_not_advance_slot(count: int) -> None:
    """EVID002/006/PATH003: stale301, duplicate302, same303 and flap303/304."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map, count)
    before = engine.snapshot
    stale = engine.observe(_input("b", "on", 301), processing_at=_at(303))
    assert stale.disposition == "stale" and stale.snapshot == before
    engine.observe(_input("b", "on", 302))
    restored = _round_trip(predictive_map, engine)
    after = engine.snapshot
    duplicate = engine.observe(_input("b", "on", 302))
    assert duplicate.snapshot == after
    assert not duplicate.authorizations and not duplicate.policy_events
    assert restored.observe(_input("b", "on", 302)) == duplicate
    later = engine.observe(_input("b", "on", 303))
    assert not later.authorizations and not later.policy_events
    assert later.snapshot.selected_paths == after.selected_paths
    assert restored.observe(_input("b", "on", 303)) == later
    engine.observe(_input("b", "off", 303))
    restored.observe(_input("b", "off", 303))
    cleared_paths = engine.snapshot.selected_paths
    episode_id = _episode(engine, "b").episode_id
    result = engine.observe(_input("b", "on", 304))
    assert restored.observe(_input("b", "on", 304)) == result
    assert not result.authorizations and not result.policy_events
    assert _episode(engine, "b").episode_id == episode_id
    assert result.snapshot.selected_paths == cleared_paths
    assert not engine._pending_prediction_learning
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("correlated", (False, True))
def test_selected_live_and_correlated_endpoint_continuations_are_nonlearning(
    count: int, correlated: bool,
) -> None:
    """PATH004: original live C303 or correlated endpoint B503 stays nonlearning."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map, count)
    engine.observe(_input("b", "on", 302))
    if correlated:
        engine.observe(_input("b", "off", 312))
        engine.advance(_at(502))
        event = _input("b", "on", 503)
    else:
        event = _input("c", "on", 303)
    counts = deepcopy(engine.prediction_manager.chain.counts)
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(event)
    assert restored.observe(event) == result
    _assert_selected_arrival(engine, None, result, target="b" if correlated else "c")
    if correlated:
        assert result.disposition == "accepted_correlated_positive"
        assert not result.policy_events
    else:
        assert [(e.zone, e.kind) for e in result.policy_events] == [("c", "acquired")]
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts == counts
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("receiving", ("a", "z"))
@pytest.mark.parametrize("reverse_creation", (False, True))
@pytest.mark.parametrize("frontier", (302, 3902))
def test_selected_receiving_zone_keeps_two_slots_without_support_coalescence(
    receiving: str, reverse_creation: bool, frontier: int,
) -> None:
    """PATH001: same original collision histories, no legacy least-ID authority."""
    predictive_map = _map(second=True, receiving=receiving)
    engine = ZoneModelEngine(predictive_map, 2, _at(-1))
    routes: tuple[tuple[str, ...], ...] = (("x", "y", "a"), ("u", "v", "z"))
    if reverse_creation:
        routes = tuple(reversed(routes))
    for at, node in enumerate(node for route in routes for node in route):
        engine.observe(_input(node, "on", at))
    assert _policy(engine, "b").active
    for at, node in enumerate(("x", "y", "u", "v", receiving), 10):
        result = engine.observe(_input(node, "off", at))
        assert not any(
            e.zone == "b" and e.kind == "released" for e in result.policy_events
        )
        assert _policy(engine, "b").active
    before = engine.advance(_at(frontier))
    assert _policy(engine, "b").active
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", frontier))
    assert restored.observe(_input("b", "on", frontier)) == result
    _assert_selected_arrival(engine, before, result)
    source_node = "a" if reverse_creation else "z"
    assert result.authorizations[0].selected_source_episode_ids == (
        _episode(engine, source_node).episode_id,
    )
    assert [(e.zone, e.kind) for e in result.policy_events] == [("b", "refreshed")]
    assert all(path is not None for path in result.snapshot.selected_paths)
    assert engine.diagnostic_counters["support_coalesced"] == 0
    assert engine.observe(_input("b", "on", frontier)).snapshot == result.snapshot
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize("capacity", (1, 3, 64))
def test_selected_capacity_streams_do_not_depend_on_legacy_lineage(
    correlated: bool, capacity: int,
) -> None:
    """PATH001/003: original1/3 bounds and62 pulses cannot mint token authority."""
    full = capacity == 64
    predictive_map = _map(second=full, filler_tokens=62 if full else 0)
    engine = _selected_seed(predictive_map, second=full, correlated=correlated)
    engine._frontier._token_limit = capacity
    at = 302
    if full:
        for node in ("x", "y", "u", "v"):
            engine.observe(_input(node, "unavailable", 302))
        engine.observe(_input("z", "off", 303))
        for index in range(62):
            pulse = engine.observe(SensorInput(
                f"event.filler_{index}", "pressed", _at(304 + index / 1000),
            ))
            assert pulse.authorizations[0].authorized
            assert not pulse.snapshot.traversal_tokens
            assert not pulse.snapshot.anonymous_supports
            assert len(pulse.snapshot.selected_paths) == 2
        engine.commit_prediction_learning()
        engine.advance(_at(305))
        at = 305
    before = ZoneModelResult("advanced", engine.snapshot)
    counts = deepcopy(engine.prediction_manager.chain.counts)
    restored = _round_trip(predictive_map, engine)
    result = engine.observe(_input("b", "on", at))
    assert restored.observe(_input("b", "on", at)) == result
    _assert_selected_arrival(engine, before, result)
    assert [(e.zone, e.kind) for e in result.policy_events] == [("b", "acquired")]
    assert engine.prediction_manager.chain.counts == counts
    assert engine.observe(_input("b", "on", at)).snapshot == result.snapshot
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
def test_selected_prediction_execution_does_not_become_learning(count: int) -> None:
    """PRED008/STATE009: actual mature grant+lease survives strict restore/expiry."""
    predictive_map = _map()
    engine = _selected_seed(predictive_map, count)
    for _ in range(10):
        assert engine.prediction_manager.chain.observe("b", "c")
    counts = deepcopy(engine.prediction_manager.chain.counts)
    before = ZoneModelResult("advanced", engine.snapshot)
    result = engine.observe(_input("b", "on", 302))
    _assert_selected_arrival(engine, before, result)
    assert [(e.zone, e.kind) for e in result.policy_events] == [
        ("b", "acquired"), ("c", "acquired"),
    ]
    assert _policy(engine, "c").phase == "predicted"
    assert _episode(engine, "c").episode_id is None
    assert all(
        path is None or path.endpoint.node_id != "c"
        for path in result.snapshot.selected_paths
    )
    assert len(result.snapshot.selected_prediction_grants) == 1
    assert len(engine.prediction_manager.leases) == 1
    restored = _round_trip(predictive_map, engine)
    for at in (_at(312) - EPSILON, _at(312), _at(312) + EPSILON):
        advanced = engine.advance(at)
        assert restored.advance(at) == advanced
        assert _policy(engine, "c").active == (at < _at(312))
        assert bool(advanced.snapshot.selected_prediction_grants) == (at < _at(312))
        assert bool(engine.prediction_manager.leases) == (at < _at(312))
        assert _policy(engine, "b").active
        assert not engine._pending_prediction_learning
        assert engine.prediction_manager.chain.counts == counts
        _round_trip(predictive_map, engine)


def test_selected_tenth_physical_cycle_is_committed_before_result_callback() -> None:
    """HEALTH002/003: nine actual cycles are quiet; tenthOFF warns without eviction."""
    predictive_map = _map(target="transition")
    engine = _selected_seed(predictive_map)
    for start in (302, 312, 322, 332, 342, 352, 362, 372, 382):
        engine.observe(_input("b", "on", start))
        engine.observe(_input("b", "off", start + 1))
    assert not any(
        row.reason == "sustained_flapping"
        for row in engine.snapshot.reliability_warning_occurrences
    )
    engine.observe(_input("b", "on", 392))
    checked: list[ZoneModelResult] = []

    def callback(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        health = next(h for h in result.snapshot.path_health if h.node_id == "b")
        assert health.completed_cycles == tuple(
            _at(at) for at in (303, 313, 323, 333, 343, 353, 363, 373, 383, 393)
        )
        assert len(health.completed_cycles) == 10
        warning, = (
            row for row in result.snapshot.reliability_warning_occurrences
            if row.reason == "sustained_flapping"
        )
        assert warning.first_observed_at == _at(393) and warning.cleared_at is None
        assert _policy(engine, "b").active
        assert any(
            path is not None and path.endpoint.node_id == "b"
            for path in result.snapshot.selected_paths
        )
        _round_trip(predictive_map, engine)
        checked.append(result)

    result = engine.observe(_input("b", "off", 393), result_callback=callback)
    assert checked == [result]


def test_current_restored_adjacent_learning_must_wait_until_after_publication() -> None:
    """Minimal synthetic REQ-PRED-006/PERF-001 production-order regression.

Source: 2026-09-14 completion qualification, NOT a captured physical incident.
Expected: queued real c->t learning does not precede next policy/publication.
Observed: _prepare_predictions drains it before both callbacks. Components supply
    historical tokens in a fully accepted current structural composite; subsequent
    e37/t38/u39 observations, not queue injection, reach current-engine fallback.
Production owner must repair/reconcile this red; this test-only worker cannot.
"""
    adjacent = {
        "a": ["b"], "b": ["a", "c"], "c": ["b", "z", "t"],
        "x": ["y"], "y": ["x", "z"], "z": ["y", "c", "e"],
        "e": ["z"], "t": ["c", "u"], "u": ["t"],
    }
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"motion": f"binary_sensor.{node}"},
            "adjacent": neighbors,
        }
        for node, neighbors in adjacent.items()
    }})
    prefix = tuple(_input(node, state, at) for node, state, at in (
        ("a", "on", 0), ("b", "on", 1), ("c", "on", 2),
        ("c", "unavailable", 3), ("x", "on", 4), ("y", "on", 5),
        ("z", "on", 6), ("c", "on", 36),
    ))
    payload = structural_payload(predictive_map, prefix, count=2)
    original = deepcopy(payload)
    engine = restore_target_state(predictive_map, payload, _at(36))
    assert serialize_target_state(predictive_map, engine) == original == payload
    assert not engine._pending_prediction_learning
    engine.observe(_input("e", "on", 37))
    _round_trip(predictive_map, engine)
    result = engine.observe(_input("t", "on", 38))
    queued, = engine._pending_prediction_learning
    assert queued in result.authorizations
    assert queued.reason == "adjacent_authorized"
    assert queued.provenance_kind == "adjacent"
    assert queued.track_confidence == "confirmed"
    assert queued.path_node_ids == ("z", "c", "t")
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    observed: list[tuple[str, float]] = []

    def result_callback(current: ZoneModelResult) -> None:
        assert current.snapshot == engine.snapshot
        observed.append(("result", engine.prediction_manager.chain.counts["c"]["t"]))

    def edge_callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "u" and decision.active_after
        assert authorization is not None
        observed.append(("edge", engine.prediction_manager.chain.counts["c"]["t"]))

    engine.observe(
        _input("u", "on", 39), result_callback=result_callback,
        decision_callback=edge_callback,
    )
    assert payload == original
    assert observed == [("result", 0), ("edge", 0)], (
        "Actual deferred learning ran before committed public callbacks", observed,
    )
