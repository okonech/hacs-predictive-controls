"""User request: defer real pending learning until after public callbacks.

Expected: committed publication precedes exactly-once eligible route learning,
without weakening mature execution, strict restoration, or reentry guards.
Observed: the retained c->t38/u39 regression learns before both callbacks.
Source: 2026-09-14 selected-path-completion qualification and explicit repair
request; synthetic accepted structural restore, NOT a captured physical incident.
Scope: engine publication, failure, same-row lease consistency and nonlearning
controls. The original test_zone_model_handoff regression remains unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.prediction import PredictionLease
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
)
from tests.learning_qualification_fixture import (
    learning_qualification_inputs,
    learning_qualification_map,
)
from tests.test_zone_model_persistence import structural_payload

START = datetime(2026, 9, 8, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def _at(seconds: int) -> datetime:
    return START + timedelta(seconds=seconds)


def _input(node: str, state: str, seconds: int) -> SensorInput:
    return SensorInput(f"binary_sensor.{node}", state, _at(seconds))


def _map(*, same_row: bool = False) -> PredictiveMap:
    adjacent = {
        "a": ["b"], "b": ["a", "c"], "c": ["b", "z", "t"],
        "x": ["y"], "y": ["x", "z"], "z": ["y", "c", "e"],
        "e": ["z"], "t": ["c", "u"], "u": ["t"],
    }
    if same_row:
        adjacent.update({
            "z": ["y", "c", "w"], "w": ["z", "q"],
            "q": ["w", "r"], "r": ["q", "e"], "e": ["r", "c"],
            "c": ["b", "z", "t", "e", "v"], "v": ["c"],
        })
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"motion": f"binary_sensor.{node}"},
            "adjacent": neighbors,
        }
        for node, neighbors in adjacent.items()
    }})
    return predictive_map if same_row else learning_qualification_map(predictive_map)


def _round_trip(predictive_map: PredictiveMap, engine: ZoneModelEngine) -> None:
    """Validate the real writer/reader without deleting either prediction table."""
    payload = serialize_target_state(predictive_map, engine)
    before = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == payload == before


def _restored(
    predictive_map: PredictiveMap, *, qualify_overlap: bool = True,
) -> ZoneModelEngine:
    prefix = tuple(_input(node, state, at) for node, state, at in (
        ("a", "on", 0), ("b", "on", 1), ("c", "on", 2),
        ("c", "unavailable", 3), ("x", "on", 4), ("y", "on", 5),
        ("z", "on", 6), ("c", "on", 36),
    ))
    if qualify_overlap:
        # e37 must actually evict c36, not use its valid nonlearning overlap.
        prefix += learning_qualification_inputs(_at(36))
    payload = structural_payload(predictive_map, prefix, count=2)
    original = deepcopy(payload)
    engine = restore_target_state(predictive_map, payload, _at(36))
    assert serialize_target_state(predictive_map, engine) == payload == original
    assert not engine._pending_prediction_learning
    return engine


def _pending(
    *, same_row: bool = False, equal_time: bool = False, support: int = 0,
) -> tuple[PredictiveMap, ZoneModelEngine, TraversalAuthorization, SensorInput]:
    """Actual observations create learning; no private queue/state injection."""
    predictive_map = _map(same_row=same_row)
    engine = _restored(predictive_map, qualify_overlap=not same_row)
    if same_row:
        engine.observe(_input("c", "off", 64 if equal_time else 67))
        assert not engine.prediction_manager.leases
        for _ in range(support):
            assert engine.prediction_manager.chain.observe("c", "v")
        for node in ("w", "q", "r", "e"):
            engine.observe(_input(node, "on", 68))
            _round_trip(predictive_map, engine)
        learning_at = 68
        next_event = _input("c", "on", 68 if equal_time else 71)
    else:
        engine.observe(_input("e", "on", 37))
        _round_trip(predictive_map, engine)
        learning_at = 38
        next_event = _input("u", "on", 39)
    result = engine.observe(_input("t", "on", learning_at))
    queued, = engine._pending_prediction_learning
    assert queued in result.authorizations
    assert queued.reason == "adjacent_authorized"
    assert queued.provenance_kind == "adjacent"
    assert queued.track_confidence == "confirmed"
    assert queued.path_node_ids == ("z", "c", "t")
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    _round_trip(predictive_map, engine)
    return predictive_map, engine, queued, next_event


@pytest.mark.parametrize("boundary", ("both", "result", "edge"))
@pytest.mark.parametrize("fail", (False, True))
def test_prior_learning_waits_for_callbacks(boundary: str, fail: bool) -> None:
    """PERF001/PRED006: actual count0 during publication, count1 afterward."""
    predictive_map, engine, queued, event = _pending()
    observed: list[tuple[str, float]] = []
    failure = RuntimeError("synthetic learning subscriber failure")

    def check(label: str) -> None:
        observed.append((label, engine.prediction_manager.chain.counts["c"]["t"]))
        snapshot = engine.snapshot
        pending = tuple(engine._pending_prediction_learning)
        predictions = deepcopy(engine.prediction_manager.serialize())
        for action in (
            engine.commit_prediction_learning,
            lambda: engine.observe(_input("u", "off", 40)),
            lambda: engine.advance(_at(40)),
        ):
            with pytest.raises(ValueError, match="Model mutation is forbidden"):
                action()
        assert engine.snapshot == snapshot
        assert tuple(engine._pending_prediction_learning) == pending
        assert engine.prediction_manager.serialize() == predictions
        _round_trip(predictive_map, engine)
        if fail:
            raise failure

    def result_callback(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        check("result")

    def edge_callback(
        current: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert current.zone == "u" and decision.active_after
        assert authorization is not None
        check("edge")

    if fail:
        with pytest.raises(RuntimeError) as caught:
            engine.observe(
                event,
                result_callback=result_callback if boundary != "edge" else None,
                decision_callback=edge_callback if boundary != "result" else None,
            )
        assert caught.value is failure
    else:
        result = engine.observe(
            event,
            result_callback=result_callback if boundary != "edge" else None,
            decision_callback=edge_callback if boundary != "result" else None,
        )
        assert result.snapshot == engine.snapshot
    expected = ["edge"] if boundary == "edge" else ["result"]
    if boundary == "both" and not fail:
        expected.append("edge")
    assert observed == [(label, 0) for label in expected]
    # Runtime's finally block explicitly drains after publication. Do not impose
    # a stronger requirement that every standalone observe flush before return.
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    assert queued not in engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("boundary", ("result", "edge"))
def test_new_learning_commits_despite_callback_failure(boundary: str) -> None:
    """Accepted t38 learning cannot be discarded with a failed subscriber."""
    predictive_map = _map()
    engine = _restored(predictive_map)
    engine.observe(_input("e", "on", 37))
    assert not engine._pending_prediction_learning
    calls: list[str] = []
    failure = RuntimeError("synthetic new-learning failure")

    def result_callback(result: ZoneModelResult) -> None:
        queued, = engine._pending_prediction_learning
        assert queued in result.authorizations
        assert engine.prediction_manager.chain.counts["c"]["t"] == 0
        calls.append("result")
        if boundary == "result":
            raise failure

    def edge_callback(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "t" and decision.active_after
        assert authorization is not None
        calls.append("edge")
        raise failure

    with pytest.raises(RuntimeError) as caught:
        engine.observe(
            _input("t", "on", 38), result_callback=result_callback,
            decision_callback=edge_callback,
        )
    assert caught.value is failure
    assert calls == (["result"] if boundary == "result" else ["result", "edge"])
    assert next(p for p in engine.snapshot.policy_states if p.zone == "t").active
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    assert not engine._pending_prediction_learning
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("equal_time", (False, True), ids=("later", "equal"))
@pytest.mark.parametrize("support", (0, 30), ids=("diagnostic", "mature"))
def test_same_row_publication_preserves_mature_snapshot(
    equal_time: bool, support: int,
) -> None:
    """PRED005/008/STATE001: late learning cannot invalidate new frozen leases."""
    predictive_map, engine, queued, event = _pending(
        same_row=True, equal_time=equal_time, support=support,
    )
    publications: list[ZoneModelResult] = []
    published_leases: list[tuple[PredictionLease, ...]] = []
    observed: list[float] = []
    edges: list[str] = []

    def result_callback(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        authorization, = result.authorizations
        assert authorization.provenance_kind == "selected_path"
        assert authorization.track_confidence == "confirmed"
        assert authorization.path_node_ids == ("r", "e", "c")
        leases = engine.prediction_manager.leases
        row_leases = tuple(lease for lease in leases if lease.current_node_id == "c")
        assert row_leases
        assert len(result.snapshot.selected_prediction_grants) == sum(
            lease.authority_kind == "selected_prediction_grant" for lease in leases
        )
        target, = (lease for lease in leases if lease.target_node_id == "v")
        policy = next(p for p in result.snapshot.policy_states if p.zone == "v")
        assert target.support == support
        assert target.mature == bool(support)
        assert policy.active == bool(support)
        if support:
            assert policy.phase == "predicted"
            assert policy.prediction_probability == target.probability
        _round_trip(predictive_map, engine)
        observed.append(engine.prediction_manager.chain.counts["c"]["t"])
        publications.append(result)
        published_leases.append(leases)

    def edge_callback(
        current: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert decision.active_after
        edges.append(current.zone)
        _round_trip(predictive_map, engine)
        observed.append(engine.prediction_manager.chain.counts["c"]["t"])

    result = engine.observe(
        event, result_callback=result_callback, decision_callback=edge_callback,
    )
    assert publications == [result]
    assert edges == (["c", "v"] if support else ["c"])
    assert observed == [0] * (3 if support else 2)
    engine.commit_prediction_learning()
    # PRED009 approved amendment: full-row frozen leases defer the increment,
    # not prediction execution or persistence of the already-qualified work.
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    debt = engine.prediction_manager.serialize()["deferred_counts"]
    assert isinstance(debt, dict) and debt["c"]["t"] == 1
    assert queued not in engine._pending_prediction_learning
    assert engine.snapshot == result.snapshot
    assert engine.prediction_manager.leases == published_leases[0]
    _round_trip(predictive_map, engine)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    expiry = max(lease.expires_at for lease in published_leases[0])
    engine.advance(expiry)
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    debt = engine.prediction_manager.serialize()["deferred_counts"]
    assert isinstance(debt, dict) and debt["c"]["t"] is None
    _round_trip(predictive_map, engine)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1


@pytest.mark.parametrize("kind", ("stale", "duplicate"))
def test_stale_and_duplicate_do_not_drain(kind: str) -> None:
    """Ignored callbacks do not introduce or drain a real pending observation."""
    predictive_map, engine, queued, _ = _pending()
    event = _input("t", "on", 37 if kind == "stale" else 38)
    before = engine.snapshot
    predictions = deepcopy(engine.prediction_manager.serialize())
    results: list[ZoneModelResult] = []
    result = engine.observe(event, result_callback=results.append)
    assert result.disposition == kind
    assert results == [result]
    assert engine.snapshot == before
    assert engine.prediction_manager.serialize() == predictions
    assert engine._pending_prediction_learning == [queued]
    _round_trip(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
def test_selected_mature_execution_remains_nonlearning(count: int) -> None:
    """Current selected mature execution still publishes without learning."""
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, count, START)
    engine.observe(_input("a", "on", 0))
    engine.observe(_input("b", "on", 1))
    for _ in range(30):
        assert engine.prediction_manager.chain.observe("c", "t")
    counts = engine.prediction_manager.chain.counts
    seen: list[ZoneModelResult] = []
    result = engine.observe(_input("c", "on", 2), result_callback=seen.append)
    assert seen == [result]
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("c", "acquired"), ("t", "acquired"),
    ]
    assert next(p for p in result.snapshot.policy_states if p.zone == "t").phase == (
        "predicted"
    )
    assert result.snapshot.selected_prediction_grants
    engine.commit_prediction_learning()
    assert not engine._pending_prediction_learning
    assert engine.prediction_manager.chain.counts == counts
    _round_trip(predictive_map, engine)
