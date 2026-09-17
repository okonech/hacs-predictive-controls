"""Synthetic final-review qualifications for strict selected-origin provenance.

Source: September16 final-review report and its A ON0/OFF10/ON21, X ON22
counterexample, using the presence-gate graph. These invented times/nodes are
not a production incident or a reconstructed user report. Protect PATH003/008,
PATH-STATE002 and STATE002/008 at the real JSON restore/engine boundary.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.profiles import SHARED_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)
from tests.test_presence_gated_departure import at, gate_map, observe, policy


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return value


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _wire(mapping: PredictiveMap, engine: ZoneModelEngine) -> dict[str, object]:
    return _object(json.loads(json.dumps(serialize_target_state(mapping, engine))))


def _roundtrip(mapping: PredictiveMap, engine: ZoneModelEngine) -> ZoneModelEngine:
    payload = _wire(mapping, engine)
    untouched = deepcopy(payload)
    restored = restore_target_state(mapping, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert _wire(mapping, restored) == payload == untouched
    return restored


def test_current_correlated_origin_cannot_restore_as_unconsumed_ordinary() -> None:
    mapping = gate_map()
    assert {key: set(node.adjacent) for key, node in mapping.nodes.items()} == {
        "a": {"b", "x"}, "b": {"a", "c"}, "c": {"b", "y"},
        "x": {"a"}, "y": {"c"},
    }
    receiver = ZoneModelEngine(mapping, 1, at(0))
    for value, seconds in (("on", 0), ("off", 10), ("on", 21)):
        observe(receiver, "a", value, seconds)
    physical = next(s for s in receiver.snapshot.episode_states if s.node_id == "a")
    source = next(s for s in receiver.snapshot.selected_sources if s.node_id == "a")
    assert physical.cadence_correlated
    assert physical.episode_id == source.episode_id
    assert (source.origin, source.consumed) == ("correlated", True)
    assert receiver.snapshot.selected_paths == (None,)
    control = _roundtrip(mapping, receiver)
    before = _wire(mapping, receiver)
    observe(control, "x", "on", 22)
    assert not policy(control, "x").active

    invalid = deepcopy(before)
    ledger = _array(_object(invalid["snapshot"])["selected_sources"])
    entry = next(_object(item) for item in ledger if _object(item)["node_id"] == "a")
    entry["origin"], entry["consumed"] = "ordinary", False
    untouched = deepcopy(invalid)
    with pytest.raises(
        ValueError, match="Selected source contradicts physical correlation",
    ):
        receiver = restore_target_state(mapping, invalid, at(21))
    assert invalid == untouched
    assert _wire(mapping, receiver) == before
    observe(receiver, "x", "on", 22)
    assert not policy(receiver, "x").active
    assert _wire(mapping, receiver) == _wire(mapping, control)
    _roundtrip(mapping, receiver)


def _ledger(payload: dict[str, object], node: str) -> dict[str, object]:
    records = _array(_object(payload["snapshot"])["selected_sources"])
    return next(_object(item) for item in records if _object(item)["node_id"] == node)


def _correlated(mapping: PredictiveMap, *, selected: bool = False) -> ZoneModelEngine:
    engine = ZoneModelEngine(mapping, 1, at(0))
    if "presence" in mapping.nodes["c"].entities:
        observe(engine, "c_alias", "off", 0)
    observe(engine, "c", "on", 0)
    observe(engine, "c", "off", 10)
    if selected:
        observe(engine, "a", "on", 19)
        observe(engine, "b", "on", 20)
    observe(engine, "c", "on", 21)
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    source = next(s for s in engine.snapshot.selected_sources if s.node_id == "c")
    assert physical.cadence_correlated and physical.episode_id == source.episode_id
    assert (source.origin, source.consumed) == ("correlated", True)
    return engine


def _continue_pair(
    mapping: PredictiveMap, left: ZoneModelEngine, right: ZoneModelEngine,
    node: str = "y",
) -> None:
    assert left.snapshot.updated_at == right.snapshot.updated_at
    event = SensorInput(
        f"binary_sensor.{node}", "on",
        left.snapshot.updated_at + timedelta(seconds=1),
    )
    left.observe(event)
    right.observe(event)
    assert _wire(mapping, left) == _wire(mapping, right)
    _roundtrip(mapping, left)


@pytest.mark.parametrize("branch", (False, True))
@pytest.mark.parametrize("confirm", (False, True))
def test_current_consumed_correlation_cannot_be_retyped_in_any_path_copy(
    branch: bool, confirm: bool,
) -> None:
    mapping = gate_map()
    receiver = _correlated(mapping, selected=True)
    if branch:
        observe(receiver, "x", "on", 22)
    path = next(p for p in receiver.snapshot.selected_paths if p is not None)
    assert path.track_confidence == "provisional"
    if branch:
        assert any(w[-1].node_id == "c" for w in path.branch_routes)
        assert all(v.node_id != "c" for v in path.route)
    else:
        assert path.endpoint.node_id == "c"
    control = _roundtrip(mapping, receiver)
    before = _wire(mapping, receiver)
    invalid = deepcopy(before)
    source = _ledger(invalid, "c")
    assert source["consumed"] is True
    source["origin"] = "ordinary"
    wire_path = _object(_array(_object(invalid["snapshot"])["selected_paths"])[0])
    copies = 0
    for sequence in (
        wire_path["visits"], wire_path["route"],
        *_array(wire_path["branch_routes"]),
    ):
        for raw in _array(sequence):
            visit = _object(raw)
            if visit["episode_id"] == source["episode_id"]:
                assert visit["kind"] == "correlated_positive"
                visit["kind"] = "positive"
                copies += 1
    assert copies >= 2
    if confirm:
        wire_path["track_confidence"] = "confirmed"
    untouched = deepcopy(invalid)
    with pytest.raises(
        ValueError, match="Selected source contradicts physical correlation",
    ):
        receiver = restore_target_state(mapping, invalid, receiver.snapshot.updated_at)
    assert invalid == untouched
    assert _wire(mapping, receiver) == before
    _continue_pair(mapping, receiver, control)
    assert policy(receiver, "y").active  # Legitimate correlated tip still continues.


@pytest.mark.parametrize("stage", ("clearing", "clear", "quiet"))
def test_current_correlation_proof_survives_clear_and_quiet_expiry(stage: str) -> None:
    mapping = gate_map()
    receiver = _correlated(mapping)
    if stage == "quiet":
        receiver.advance(
            at(21) + SHARED_PROFILES["stay_presence"].cycle_correlation_window,
        )
    else:
        observe(receiver, "c", "off", 22)
        if stage == "clear":
            receiver.advance(at(32))
    physical = next(s for s in receiver.snapshot.episode_states if s.node_id == "c")
    assert physical.cadence_correlated
    assert physical.status == ("asserted" if stage == "quiet" else stage)
    assert (physical.cadence_run_started_at is None) is (stage == "quiet")
    control = _roundtrip(mapping, receiver)
    before = _wire(mapping, receiver)
    invalid = deepcopy(before)
    source = _ledger(invalid, "c")
    assert source["consumed"] is True
    source["origin"] = "ordinary"  # Consumed is not an exemption from provenance.
    untouched = deepcopy(invalid)
    with pytest.raises(
        ValueError, match="Selected source contradicts physical correlation",
    ):
        receiver = restore_target_state(mapping, invalid, receiver.snapshot.updated_at)
    assert invalid == untouched
    assert _wire(mapping, receiver) == before
    _continue_pair(mapping, receiver, control)
    assert not policy(receiver, "y").active


@pytest.mark.parametrize("reset", (
    "count_zero", "count_recovery", "unavailable", "startup_off", "alias_on",
))
def test_same_episode_cadence_reset_does_not_retype_its_recorded_origin(
    reset: str,
) -> None:
    mapping = gate_map(aliases=reset == "alias_on")
    engine = _correlated(mapping)
    original = _ledger(_wire(mapping, engine), "c")
    if reset in {"count_zero", "count_recovery"}:
        engine.observe_count(CountInput("zero", 0, True, at(22)))
        _roundtrip(mapping, engine)
        if reset == "count_recovery":
            engine.observe_count(CountInput("positive", 1, True, at(23)))
    elif reset == "unavailable":
        observe(engine, "c", "unavailable", 22)
    elif reset == "startup_off":
        engine.reconcile_restored_asserted_contexts(tuple(
            SensorInput(f"binary_sensor.{node}", "off", at(22))
            for node in mapping.nodes
        ), at(22))
    else:
        observe(engine, "c_alias", "on", 22)
        observe(engine, "c", "unknown", 23)
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    assert physical.episode_id == original["episode_id"]
    assert not physical.cadence_correlated
    assert physical.cadence_run_started_at is None
    assert _ledger(_wire(mapping, engine), "c") == original
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored)


def test_correlated_saved_tip_survives_same_episode_alias_cadence_reset() -> None:
    mapping = gate_map(aliases=True)
    engine = _correlated(mapping, selected=True)
    observe(engine, "x", "on", 22)
    original = _ledger(_wire(mapping, engine), "c")
    observe(engine, "c_alias", "on", 23)
    observe(engine, "c", "unknown", 24)
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    assert physical.episode_id == original["episode_id"] and physical.known_on
    assert not physical.cadence_correlated
    assert physical.cadence_run_started_at is None
    path = next(p for p in engine.snapshot.selected_paths if p is not None)
    tip = next(w[-1] for w in path.branch_routes if w[-1].node_id == "c")
    assert tip.kind == "correlated_positive" and tip.branch_active
    assert _ledger(_wire(mapping, engine), "c") == original
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored)
    assert policy(engine, "y").active


def test_historical_ordinary_prefix_is_not_retyped_from_current_correlation() -> None:
    mapping = gate_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    for seconds, node in enumerate(("a", "b", "c", "x")):
        observe(engine, node, "on", seconds)
    observe(engine, "a", "off", 10)
    observe(engine, "a", "on", 21)
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "a")
    assert physical.cadence_correlated
    path = next(p for p in engine.snapshot.selected_paths if p is not None)
    historical = tuple(v for v in path.occurrences if v.node_id == "a"
                       and v.episode_id != physical.episode_id)
    assert historical
    assert all(v.kind == "positive" and not v.branch_active for v in historical)
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored)
    assert policy(engine, "y").active


def test_equal_time_new_startup_generation_cannot_classify_older_origin() -> None:
    mapping = gate_map()
    engine = _correlated(mapping)
    original = _ledger(_wire(mapping, engine), "c")
    observe(engine, "c", "unavailable", 21)
    engine.reconcile_restored_asserted_contexts((
        SensorInput("binary_sensor.c", "on", at(21)),
    ), at(21))
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "c")
    assert physical.episode_id != original["episode_id"]
    assert physical.started_at == physical.cadence_run_started_at == at(21)
    assert original["at"] == at(21).isoformat()
    assert not physical.cadence_correlated
    assert _ledger(_wire(mapping, engine), "c") == original
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored)
    assert not policy(engine, "y").active


def test_ordinary_generation_inside_existing_run_remains_a_legitimate_origin() -> None:
    mapping = gate_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    for value, seconds in (("on", 0), ("off", 10), ("on", 14)):
        observe(engine, "a", value, seconds)
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "a")
    assert not physical.cadence_correlated
    assert physical.cadence_run_started_at == at(0)
    assert physical.started_at == at(14) > physical.cadence_run_started_at
    source = _ledger(_wire(mapping, engine), "a")
    assert source["origin"] == "ordinary" and source["consumed"] is False
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored, "x")
    assert policy(engine, "x").active


def test_cold_bootstrap_roundtrip_does_not_invent_a_pending_origin() -> None:
    mapping = gate_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    engine.bootstrap_sensor_snapshot((
        SensorInput("binary_sensor.a", "on", at(0)),
    ), at(0))
    assert _ledger(_wire(mapping, engine), "a")["origin"] == "none"
    restored = _roundtrip(mapping, engine)
    _continue_pair(mapping, engine, restored, "x")
    assert not policy(engine, "x").active
    assert engine.snapshot.selected_paths == (None,)
