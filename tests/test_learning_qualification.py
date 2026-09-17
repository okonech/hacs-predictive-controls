"""Synthetic regression for September17 learning-fixture repair, not an incident.

Expected: genuine independent confirmed adjacent t38 teaches only after u39
publication. Observed: original donor retains selected c overlap and cannot learn.
Source: repair-learning-intake-cf77c638 and probe6-f45b67d3 (43 owned failures).
Scope: actual prefix-bound eviction, strict current composite and false positives;
original production incident, shared harness and all consumer assertions frozen.
"""

from copy import deepcopy

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.learning_qualification_fixture import (
    LEARNING_STEPS,
    learning_qualification_inputs,
    learning_qualification_map,
)
from tests.test_learning_publication_completion import (
    _at,
    _input,
    _map,
    _restored,
    _round_trip,
)
from tests.test_zone_model_persistence import structural_payload

pytestmark = pytest.mark.target_model


def _base_map() -> PredictiveMap:
    """Frozen original synthetic graph, independent of the repaired factory."""
    adjacent = {
        "a": ["b"], "b": ["a", "c"], "c": ["b", "z", "t"],
        "x": ["y"], "y": ["x", "z"], "z": ["y", "c", "e"],
        "e": ["z"], "t": ["c", "u"], "u": ["t"],
    }
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"motion": f"binary_sensor.{node}"},
            "adjacent": neighbors,
        } for node, neighbors in adjacent.items()
    }})


def _prefix() -> tuple[SensorInput, ...]:
    return tuple(_input(node, state, seconds) for node, state, seconds in (
        ("a", "on", 0), ("b", "on", 1), ("c", "on", 2),
        ("c", "unavailable", 3), ("x", "on", 4), ("y", "on", 5),
        ("z", "on", 6), ("c", "on", 36),
    ))


def test_owned_learning_donor_reaches_independent_adjacent_authority() -> None:
    """RED on original _restored: c36 remains in selected history after e37."""
    model = _map()
    engine = _restored(model)
    current = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    engine.observe(_input("e", "on", 37))
    assert all(current.episode_id != visit.episode_id
               for path in engine.snapshot.selected_paths if path is not None
               for visit in path.occurrences)
    result = engine.observe(_input("t", "on", 38))
    authorization, = result.authorizations
    assert authorization.provenance_kind == "adjacent"
    assert authorization.path_node_ids == ("z", "c", "t")
    assert engine._pending_prediction_learning == [authorization]
    _round_trip(model, engine)


@pytest.mark.parametrize("steps", (0, 1, 2, 3))
def test_only_real_history_eviction_exposes_independent_learning(steps: int) -> None:
    base = _base_map()
    original = deepcopy(base)
    model = learning_qualification_map(base)
    assert base == original
    for node, config in base.nodes.items():
        assert model.nodes[node].entities == config.entities
        assert set(config.adjacent) <= set(model.nodes[node].adjacent)
    events = _prefix() + learning_qualification_inputs(_at(36))[:steps]
    payload = structural_payload(model, events, count=2)
    unchanged = deepcopy(payload)
    engine = restore_target_state(model, payload, _at(36))
    _round_trip(model, engine)
    current = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    assert current.started_at == _at(36) and current.status == "asserted"
    assert not current.cadence_correlated
    token, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "c")
    assert token.episode_id == current.episode_id
    assert token.path_node_ids == ("y", "z", "c")
    assert token.track_confidence == "confirmed" and token.valid_until > _at(38)
    assert engine.snapshot.anonymous_supports
    assert engine.snapshot.support_token_bindings
    ledger = next(s for s in engine.snapshot.selected_sources if s.node_id == "c")
    assert ledger.episode_id == current.episode_id and ledger.consumed
    assert ledger.origin == "ordinary"
    assert any(witness[-1].episode_id == current.episode_id
               for path in engine.snapshot.selected_paths if path is not None
               for witness in path.branch_routes) is bool(steps)

    result = engine.observe(_input("e", "on", 37))
    assert result.authorizations[0].provenance_kind == "selected_path"
    assert not engine._pending_prediction_learning
    assert not next(p for p in engine.snapshot.policy_states if p.zone == "t").active
    old, = (p for p in engine.snapshot.selected_paths
            if p is not None and p.endpoint.node_id == "c")
    assert old.endpoint.at == _at(2)
    assert old.endpoint.episode_id != current.episode_id
    assert old.endpoint in old.coverage
    assert not old.endpoint_eligible
    selected_current = any(current.episode_id == v.episode_id
                           for p in engine.snapshot.selected_paths if p is not None
                           for v in p.occurrences)
    assert selected_current is (steps < 3)
    assert token in engine.snapshot.traversal_tokens
    _round_trip(model, engine)
    result = engine.observe(_input("t", "on", 38))
    authorization, = result.authorizations
    assert authorization.authorized and authorization.track_confidence == "confirmed"
    assert authorization.path_node_ids == ("z", "c", "t")
    assert next(p for p in result.snapshot.policy_states if p.zone == "t").active
    if steps == 3:
        assert authorization.provenance_kind == "adjacent"
        # Authorization also records linked historical tokens. Only c directly
        # neighbors t; linked support history must not invent another graph edge.
        assert tuple(t for t in authorization.source_tokens
                     if "t" in model.neighbors(t.node_id)) == (token,)
        assert {t.node_id for t in authorization.source_tokens} == {
            "c", LEARNING_STEPS[0],
        }
        assert engine._pending_prediction_learning == [authorization]
    else:
        assert authorization.provenance_kind == "selected_path"
        assert not engine._pending_prediction_learning
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    _round_trip(model, engine)
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == (1 if steps == 3 else 0)
    assert payload == unchanged
    _round_trip(model, engine)


def test_current_only_stream_cannot_recreate_independent_token_or_learning() -> None:
    model = learning_qualification_map(_base_map())
    engine = ZoneModelEngine(model, 2, _at(0))
    for event in (*_prefix(), *learning_qualification_inputs(_at(36)),
                  _input("e", "on", 37)):
        engine.observe(event)
        _round_trip(model, engine)
    assert not any(t.node_id == "c" for t in engine.snapshot.traversal_tokens)
    result = engine.observe(_input("t", "on", 38))
    assert all(not authorization.authorized for authorization in result.authorizations)
    assert not next(p for p in result.snapshot.policy_states if p.zone == "t").active
    assert not engine._pending_prediction_learning
    assert not engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    _round_trip(model, engine)


@pytest.mark.parametrize("state", ("unknown", "unavailable"))
def test_real_source_availability_loss_prevents_learning(state: str) -> None:
    model = learning_qualification_map(_base_map())
    events = _prefix() + learning_qualification_inputs(_at(36))
    engine = restore_target_state(model, structural_payload(model, events, count=2),
                                  _at(36))
    engine.observe(_input("e", "on", 37))
    engine.observe(_input("c", state, 37))
    assert not any(t.node_id == "c" for t in engine.snapshot.traversal_tokens)
    _round_trip(model, engine)
    result = engine.observe(_input("t", "on", 38))
    assert all(not authorization.authorized for authorization in result.authorizations)
    assert not next(p for p in result.snapshot.policy_states if p.zone == "t").active
    assert not engine._pending_prediction_learning
    assert not engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    assert serialize_target_state(model, engine)["prediction"] == (
        engine.prediction_state
    )
    assert len(LEARNING_STEPS) == 3
    _round_trip(model, engine)
