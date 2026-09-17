"""Synthetic PATH005 qualifications; the unchanged Aug22 replay is the incident.

Public runtime cases assert actual scheduled control writes, not forced policy
evaluations. Separate filter/engine cases qualify calibration, exact deadline
groups, sparse versus stepped continuation, strict JSON and physical provenance.
No private state is injected into the public runtime acceptance cases.
"""

from __future__ import annotations

import asyncio
import json
import math
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import (
    ZoneBeliefFilter,
    probability_to_log_odds,
)
from custom_components.predictive_controls.zone_model.persistence import (
    _decode_belief,
    _target_map_fingerprint_payload,
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
    ZoneBeliefState,
    ZonePolicyState,
)
from tests.overlap_retirement_fixture import retire_overlap
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 12, tzinfo=UTC) + timedelta(seconds=seconds)


def gate_map(
    *, aliases: bool = False, peer: bool = False, kind: str = "mmwave",
) -> PredictiveMap:
    nodes: dict[str, Any] = {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"mmwave": f"binary_sensor.{node}"},
            "adjacent": neighbors,
        }
        for node, neighbors in (
            ("a", ["b", "x"]), ("b", ["a", "c"]),
            ("c", ["b", "y"]), ("x", ["a"]), ("y", ["c"]),
        )
    }
    nodes["c"]["entities"] = {kind: "binary_sensor.c"}
    if aliases:
        nodes["c"]["entities"]["presence"] = "binary_sensor.c_alias"
    if peer:
        nodes["d"] = {
            "zone": "c", "role": "room_occupancy",
            "occupancy_behavior": "sustained",
            "entities": {"presence": "binary_sensor.d"},
            "adjacent": [],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


def observe(engine: ZoneModelEngine, node: str, value: str, seconds: float) -> None:
    engine.observe(SensorInput(f"binary_sensor.{node}", value, at(seconds)))


def belief(engine: ZoneModelEngine, zone: str = "c") -> ZoneBeliefState:
    return next(state for state in engine.snapshot.belief_states if state.zone == zone)


def policy(engine: ZoneModelEngine, zone: str = "c") -> ZonePolicyState:
    return next(state for state in engine.snapshot.policy_states if state.zone == zone)


def retired(
    predictive_map: PredictiveMap, count: int = 1,
) -> ZoneModelEngine:
    engine = ZoneModelEngine(predictive_map, count, at(0))
    for seconds, node in enumerate(("a", "b", "c", "x")):
        observe(engine, node, "on", seconds)
    # Separate synthetic retirement qualification, not the public overlap replay.
    retire_overlap(engine.observe, at(3))
    assert all(visit.node_id not in {"b", "c"}
               for path in engine.snapshot.selected_paths if path is not None
               for visit in path.occurrences)
    assert next(state for state in engine.snapshot.episode_states
                if state.node_id == "c").known_on
    assert policy(engine).active
    assert belief(engine).path_displaced_at == at(3)
    return engine


def roundtrip(
    engine: ZoneModelEngine, predictive_map: PredictiveMap,
) -> ZoneModelEngine:
    payload = json.loads(json.dumps(serialize_target_state(predictive_map, engine)))
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    return restored


@pytest.mark.parametrize("count", (1, 2))
def test_runtime_presence_until_clear_then_release_without_branch_revival(
    count: int,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count)
        for seconds, node in enumerate(("a", "b", "c", "x")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        replay.advance(at(700))
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)
        replay.send("binary_sensor.y", "on", at(701))
        # C is a retained overlap tip, not a retired raw-ON origin.
        assert replay.edges_for("y") == (ActiveEdge(at(701), "y", True),)
        replay.send("binary_sensor.c", "off", at(710))
        replay.advance(at(719))
        assert replay.view().active("c")
        replay.advance(at(720))  # Stable clear; no protected time earns dwell.
        assert replay.view().active("c")
        replay.advance(at(1000))
        assert replay.view().active("c")
        replay.advance(at(1300))
        edges = replay.edges_for("c")
        assert len(edges) == 2 and not edges[-1].active
        assert at(1020) < edges[-1].at <= at(1300)
        assert not replay.view().active("c")
        assert edges == (ActiveEdge(at(2), "c", True),
                 ActiveEdge(at(1050), "c", False))
        assert replay.edges_for("y") == (ActiveEdge(at(701), "y", True),)


@pytest.mark.parametrize("count", (1, 2))
def test_runtime_no_movement_clear_retains_selected_endpoint(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count)
        for seconds, node in enumerate(("a", "b", "c")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        replay.send("binary_sensor.c", "off", at(100))
        replay.advance(at(1800))
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)


@pytest.mark.parametrize("count", (1, 2))
def test_engine_confidence_gate_and_full_dwell_stepped_sparse_restore(
    count: int,
) -> None:
    predictive_map = gate_map()
    stepped = retired(predictive_map, count)
    sparse = roundtrip(stepped, predictive_map)
    original = belief(stepped)
    for seconds in range(5, 706, 5):
        stepped.advance(at(seconds))
    sparse.advance(at(705))
    profile = BELIEF_PROFILES["stay_presence"]
    expected = profile.asserted.baseline_probability + (
        original.probability - profile.asserted.baseline_probability
    ) * math.exp(-702 / profile.asserted.time_constant.total_seconds())
    assert belief(stepped).probability == pytest.approx(expected, abs=1e-12)
    assert belief(sparse).probability == pytest.approx(expected, abs=1e-12)
    assert belief(sparse).physical_hold
    for engine in (stepped, sparse):
        observe(engine, "c", "off", 710)
        assert belief(engine).physical_hold
        assert policy(engine).pending_release_since is None
    restored = roundtrip(sparse, predictive_map)
    for engine in (stepped,):
        engine.advance(at(715))
        assert belief(engine).physical_hold
        engine.advance(at(720))
    clear = belief(stepped)
    assert not clear.physical_hold
    assert clear.path_displaced_at == at(3)
    assert policy(stepped).pending_release_since is None
    probe = ZoneBeliefFilter.restore(profile, clear)
    calibration = POLICY_CALIBRATIONS["stay_presence"]
    crossing = probe.threshold_crossed_at(clear, calibration.off_threshold, at(1500))
    assert crossing is not None and crossing > at(720)
    release = crossing + calibration.release_dwell
    for seconds in range(725, 1501, 5):
        stepped.advance(at(seconds))
        if at(seconds) < release:
            assert policy(stepped).active
    for engine in (sparse, restored):
        engine.advance(at(1500))
        assert not policy(engine).active
        assert belief(engine).probability == pytest.approx(
            belief(stepped).probability, abs=1e-12,
        )
        roundtrip(engine, predictive_map)
    assert sparse.snapshot == restored.snapshot


def test_filter_switch_advances_old_calibration_not_new_or_frozen() -> None:
    profile = BELIEF_PROFILES["stay_presence"]
    filter_ = ZoneBeliefFilter("c", profile, at(0))
    filter_.apply_positive(f"c:1:{at(1).isoformat()}", at(1))
    filter_.set_physical_hold(True, at(1))
    filter_.displace_path(at(3))
    start = filter_.state
    filter_.set_physical_hold(False, at(100))
    expected = 0.95 + (start.probability - 0.95) * math.exp(-97 / 1200)
    assert filter_.state.probability == pytest.approx(expected)
    filter_.advance(at(280))
    assert filter_.state.probability == pytest.approx(
        0.05 + (expected - 0.05) * math.exp(-1),
    )
    assert filter_.state.path_displaced_at == at(3)
    before = filter_.state
    with pytest.raises(ValueError, match="boolean"):
        filter_.set_physical_hold(1, at(300))  # type: ignore[arg-type]
    assert filter_.state == before


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("unknown", ("unknown", "unavailable"))
def test_alias_on_wins_but_unknown_breaks_clearing_continuity(
    count: int, unknown: str,
) -> None:
    predictive_map = gate_map(aliases=True)
    engine = retired(predictive_map, count)
    observe(engine, "c_alias", "on", 4)
    paths = engine.snapshot.selected_paths
    observe(engine, "c", "off", 100)
    assert belief(engine).physical_hold
    assert engine.snapshot.selected_paths == paths
    observe(engine, "c_alias", "off", 101)
    assert belief(engine).physical_hold
    observe(engine, "c", unknown, 105)
    assert not belief(engine).physical_hold
    roundtrip(engine, predictive_map)
    observe(engine, "c", "off", 106)
    assert not belief(engine).physical_hold  # All OFF cannot recreate the witness.
    engine.advance(at(110))
    assert not belief(engine).physical_hold
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("same_time", (True, False))
@pytest.mark.parametrize("count", (1, 2))
def test_same_zone_survivor_reselection_and_final_clear_group(
    count: int, same_time: bool,
) -> None:
    predictive_map = gate_map(peer=True)
    engine = retired(predictive_map, count)
    observe(engine, "d", "on", 4)
    paths = engine.snapshot.selected_paths
    observe(engine, "c", "off", 100)
    observe(engine, "d", "off", 100 if same_time else 105)
    restored = roundtrip(engine, predictive_map)
    engine.advance(at(110))
    assert belief(engine).physical_hold is (not same_time)
    engine.advance(at(115))
    assert not belief(engine).physical_hold
    assert belief(engine).path_displaced_at is not None
    assert policy(engine).active
    restored.advance(at(115))
    assert belief(restored).probability == pytest.approx(belief(engine).probability)
    assert restored.snapshot.selected_paths == engine.snapshot.selected_paths == paths
    roundtrip(restored, predictive_map)


def test_same_zone_unknown_cannot_remint_one_node_while_other_holds() -> None:
    predictive_map = gate_map(aliases=True, peer=True)
    engine = retired(predictive_map)
    observe(engine, "c_alias", "off", 4)
    observe(engine, "d", "on", 5)
    observe(engine, "c", "off", 100)
    observe(engine, "c_alias", "unknown", 101)
    assert belief(engine).physical_hold
    observe(engine, "c_alias", "off", 102)
    observe(engine, "d", "unavailable", 103)
    assert not belief(engine).physical_hold
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
def test_fresh_retired_presence_restores_local_hold_not_acquisition(count: int) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map, count)
    observe(engine, "c", "unavailable", 100)
    assert not belief(engine).physical_hold
    observe(engine, "c", "on", 101)
    assert belief(engine).physical_hold
    assert belief(engine).path_displaced_at == at(101)
    assert policy(engine).active
    assert policy(engine).pending_release_since is None
    observe(engine, "c", "off", 200)
    engine.advance(at(1200))
    assert not policy(engine).active
    observe(engine, "c", "on", 1201)
    assert belief(engine).physical_hold
    assert not policy(engine).active
    assert all(path is None or path.endpoint.node_id != "c"
               for path in engine.snapshot.selected_paths)
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("level", ("on", "off", "unknown", "unavailable"))
def test_startup_reconciles_hold_before_return_without_downtime_backdating(
    count: int, level: str,
) -> None:
    predictive_map = gate_map()
    live = retired(predictive_map, count)
    restored = roundtrip(live, predictive_map)
    events = tuple(SensorInput(f"binary_sensor.{node}", value, at(700))
                   for node, value in (
                       ("a", "on"), ("b", "on"), ("c", level),
                       ("x", "on"), ("y", "unknown"),
                   ))
    live.advance(at(700))
    restored.reconcile_restored_asserted_contexts(events, at(700))
    assert belief(restored).probability == pytest.approx(belief(live).probability)
    assert belief(restored).physical_hold is (level == "on")
    assert policy(restored).active
    assert belief(restored).path_displaced_at == at(3)
    roundtrip(restored, predictive_map)
    restored.advance(at(705))
    assert belief(restored).physical_hold is (level == "on")


@pytest.mark.parametrize("count", (1, 2))
def test_bootstrap_only_presence_and_inactive_live_presence_cannot_acquire(
    count: int,
) -> None:
    predictive_map = gate_map()
    engine = ZoneModelEngine(predictive_map, count, at(0))
    engine.bootstrap_sensor_snapshot((SensorInput("binary_sensor.c", "on", at(0)),),
                                     at(0))
    assert not belief(engine).physical_hold
    engine.advance(at(700))
    assert not belief(engine).physical_hold
    assert not policy(engine).active
    roundtrip(engine, predictive_map)
    live = ZoneModelEngine(predictive_map, count, at(0))
    observe(live, "c", "on", 1)
    assert belief(live).physical_hold  # Physical derivation has no policy feedback.
    live.advance(at(700))
    assert not policy(live).active
    roundtrip(live, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
def test_count_zero_and_positive_count_reduction_do_not_invent_arrivals(
    count: int,
) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map, 2)
    engine.observe_count(CountInput("reduce", count, True, at(100)))
    assert belief(engine).physical_hold and policy(engine).active
    engine.observe_count(CountInput("zero", 0, True, at(101)))
    assert all(not state.physical_hold for state in engine.snapshot.belief_states)
    assert not policy(engine).active
    roundtrip(engine, predictive_map)
    engine.observe_count(CountInput("increase", count, True, at(102)))
    assert not policy(engine).active
    assert all(path is None for path in engine.snapshot.selected_paths)
    roundtrip(engine, predictive_map)


def test_pir_and_interaction_never_create_physical_presence_gate() -> None:
    predictive_map = gate_map(kind="motion")
    engine = retired(predictive_map)
    assert not belief(engine).physical_hold
    engine.advance(at(700))
    assert not policy(engine).active
    interaction_map = PredictiveMap.from_mapping({"nodes": {"press": {
        "role": "room_occupancy", "occupancy_behavior": "sticky",
        "entities": {"interaction": "event.press"},
    }}})
    interaction = ZoneModelEngine(interaction_map, 1, at(0))
    interaction.observe(SensorInput("event.press", "pressed", at(1)))
    assert not belief(interaction, "press").physical_hold
    roundtrip(interaction, interaction_map)


@pytest.mark.parametrize("bad", (None, 0, 1, "false", [], {}))
def test_current_and_historical_decode_reject_nonboolean_flag(bad: object) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map)
    payload = json.loads(json.dumps(serialize_target_state(predictive_map, engine)))
    raw = next(state for state in payload["snapshot"]["belief_states"]
               if state["zone"] == "c")
    raw["physical_hold"] = bad
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, at(3))
    with pytest.raises(ValueError):
        _decode_belief(raw, historical=True)


def test_strict_flag_required_historical_default_and_old_fingerprint_rejection(
) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map)
    payload = json.loads(json.dumps(serialize_target_state(predictive_map, engine)))
    raw = next(state for state in payload["snapshot"]["belief_states"]
               if state["zone"] == "c")
    del raw["physical_hold"]
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, at(3))
    assert not _decode_belief(raw, historical=True).physical_hold
    current = _target_map_fingerprint_payload(predictive_map)
    assert type(current["presence_gated_departure_version"]) is int
    assert current["presence_gated_departure_version"] == 1
    assert "presence_gated_departure_version" not in _target_map_fingerprint_payload(
        predictive_map, pre_feature=True,
    )
    payload["map_fingerprint"] = "old-fingerprint"
    payload["snapshot"] = None
    with pytest.raises(ValueError, match="fingerprint"):
        restore_target_state(predictive_map, payload, at(3))


@pytest.mark.parametrize("mutation", ("false-with-witness", "true-without", "count0"))
def test_strict_cross_component_flag_rejects_contradictory_witnesses(
    mutation: str,
) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map)
    if mutation == "count0":
        engine.observe_count(CountInput("zero", 0, True, at(4)))
    elif mutation == "true-without":
        observe(engine, "c", "unknown", 4)
    payload = json.loads(json.dumps(serialize_target_state(predictive_map, engine)))
    raw = next(state for state in payload["snapshot"]["belief_states"]
               if state["zone"] == "c")
    raw["physical_hold"] = mutation != "false-with-witness"
    with pytest.raises(ValueError, match="Physical hold"):
        restore_target_state(predictive_map, payload, engine.snapshot.updated_at)


def test_low_belief_hold_starts_full_dwell_at_loss_and_callbacks_keep_frontier(
) -> None:
    """Explicit synthetic scalar qualification, not an incident/runtime fixture."""
    predictive_map = gate_map()
    engine = retired(predictive_map)
    snapshot = engine.snapshot
    snapshot = replace(snapshot, belief_states=tuple(
        replace(state, log_odds=probability_to_log_odds(0.1))
        if state.zone == "c" else state for state in snapshot.belief_states
    ))
    # STATE001/PRED008: scalar calibration does not erase independent grants.
    prediction_state = engine.prediction_manager.serialize()
    original_prediction = deepcopy(prediction_state)
    assert snapshot.selected_prediction_grants
    assert engine.prediction_manager.leases
    engine = ZoneModelEngine.restore(
        predictive_map, snapshot, (), at(3), prediction_state=prediction_state,
    )
    assert engine.snapshot == snapshot
    assert belief(engine).probability == pytest.approx(0.1)
    assert engine.prediction_manager.serialize() == original_prediction
    assert prediction_state == original_prediction
    engine.advance(at(5))
    assert policy(engine).active and policy(engine).pending_release_since is None
    observe(engine, "c", "off", 6)
    engine.advance(at(16))
    assert policy(engine).pending_release_since == at(16)
    for seconds in (17, 20, 25):
        observe(engine, "c", "off", seconds)
        engine.observe_count(CountInput(f"count-{seconds}", 1, True, at(seconds)))
        assert policy(engine).pending_release_since == at(16)
    dwell = POLICY_CALIBRATIONS["stay_presence"].release_dwell
    engine.advance(at(16) + dwell - timedelta(microseconds=1))
    assert policy(engine).active
    engine.advance(at(16) + dwell)
    assert not policy(engine).active


@pytest.mark.parametrize("count", (1, 2))
def test_retired_held_sensor_health_is_independent_of_supported_sensor(
    count: int,
) -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map, count)
    engine.advance(at(602))
    assert not any(row.node_id == "c" for row
                   in engine.snapshot.reliability_warning_occurrences)
    engine.advance(at(603))
    warning = next(row for row in engine.snapshot.reliability_warning_occurrences
                   if row.node_id == "c")
    assert warning.kind == "suspected_stuck"
    assert warning.first_observed_at == at(603)
    assert policy(engine).active and belief(engine).physical_hold
    assert not any(row.node_id == "x" for row
                   in engine.snapshot.reliability_warning_occurrences)
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
def test_runtime_alias_availability_release_and_count_zero(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(aliases=True), count)
        for seconds, node in enumerate(("a", "b", "c", "x")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        replay.send("binary_sensor.c_alias", "on", at(4))
        replay.send("binary_sensor.c", "unknown", at(100))
        replay.advance(at(700))
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)
        replay.send("binary_sensor.c_alias", "unavailable", at(701))
        replay.advance(at(1300))
        assert tuple(edge.active for edge in replay.edges_for("c")) == (True, False)
        assert replay.edges_for("c")[-1].at > at(1000)
        assert replay.view().active("x")
        replay.send("sensor.replay_people", "0", at(1301))
        assert replay.input_edges_for("x")[-1] == ActiveEdge(at(1301), "x", False)
        replay.send("sensor.replay_people", str(count), at(1302))
        replay.advance(at(1310))
        assert not any(active for _, active in replay.view().zones)


def test_callback_snapshot_is_strict_at_presence_acquisition() -> None:
    predictive_map = gate_map()
    engine = ZoneModelEngine(predictive_map, 1, at(0))
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    captured: list[bool] = []

    def capture(*_args: object) -> None:
        restored = roundtrip(engine, predictive_map)
        captured.append(belief(restored).physical_hold)

    engine.observe(SensorInput("binary_sensor.c", "on", at(2)),
                   decision_callback=capture)
    assert captured == [True]


def test_sparse_loss_preserves_threshold_crossing_and_full_dwell() -> None:
    predictive_map = gate_map()
    stepped = retired(predictive_map)
    stepped.advance(at(700))
    observe(stepped, "c", "off", 710)
    sparse = roundtrip(stepped, predictive_map)
    for seconds in range(715, 961, 5):
        stepped.advance(at(seconds))
    sparse.advance(at(960))
    pending = policy(stepped).pending_release_since
    assert pending is not None
    other = policy(sparse).pending_release_since
    assert other is not None
    assert abs((pending - other).total_seconds()) <= 0.00001
    restored = roundtrip(sparse, predictive_map)
    due = other + POLICY_CALIBRATIONS["stay_presence"].release_dwell
    for engine in (sparse, restored):
        engine.advance(due - timedelta(microseconds=1))
        assert policy(engine).active
        engine.advance(due)
        assert not policy(engine).active


def test_correlated_presence_origin_protects_without_a_new_path() -> None:
    predictive_map = gate_map()
    engine = retired(predictive_map)
    observe(engine, "c", "off", 100)
    engine.advance(at(110))
    paths = engine.snapshot.selected_paths
    observe(engine, "c", "on", 111)
    source = next(source for source in engine.snapshot.selected_sources
                  if source.node_id == "c")
    assert source.origin == "correlated" and source.consumed
    assert belief(engine).physical_hold and policy(engine).active
    assert engine.snapshot.selected_paths == paths
    roundtrip(engine, predictive_map)


def test_no_on_mixed_aliases_cannot_gain_continuity_by_later_all_off() -> None:
    predictive_map = gate_map(aliases=True)
    engine = retired(predictive_map)
    # The never-observed second alias is unknown, not a confirmed clear.
    observe(engine, "c", "off", 100)
    assert not belief(engine).physical_hold
    observe(engine, "c_alias", "off", 101)
    assert not belief(engine).physical_hold
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("aliases", (False, True))
def test_startup_matching_pending_clear_preserves_existing_confirmation(
    count: int, aliases: bool,
) -> None:
    predictive_map = gate_map(aliases=aliases)
    engine = retired(predictive_map, count)
    if aliases:
        observe(engine, "c_alias", "off", 4)
    observe(engine, "c", "off", 100)
    restored = roundtrip(engine, predictive_map)
    events = tuple(SensorInput(alias, value, at(105))
                   for state in engine.snapshot.episode_states
                   for alias, value in state.alias_states)
    before = next(state for state in engine.snapshot.episode_states
                  if state.node_id == "c")
    engine.advance(at(105))
    restored.reconcile_restored_asserted_contexts(events, at(105))
    assert belief(restored).physical_hold
    after = next(state for state in restored.snapshot.episode_states
                 if state.node_id == "c")
    assert after == replace(before, advanced_at=at(105))
    assert belief(restored) == belief(engine)
    roundtrip(restored, predictive_map)
    engine.advance(at(110))
    restored.advance(at(110))
    assert not belief(restored).physical_hold
    assert belief(restored) == belief(engine)
    assert sum(item.kind == "stable_clear"
               for item in belief(restored).contributions) == 1
    roundtrip(restored, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
def test_startup_off_mismatch_cannot_remint_via_same_zone_survivor(count: int) -> None:
    predictive_map = gate_map(peer=True)
    engine = retired(predictive_map, count)
    observe(engine, "d", "on", 4)
    events = tuple(SensorInput(alias, "off" if alias == "binary_sensor.c" else value,
                               at(100))
                   for state in engine.snapshot.episode_states
                   for alias, value in state.alias_states)
    engine.reconcile_restored_asserted_contexts(events, at(100))
    assert belief(engine).physical_hold  # Actual D presence still protects.
    observe(engine, "d", "unavailable", 101)
    assert not belief(engine).physical_hold  # Startup C OFF cannot remint a hold.
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("saved_on", ("c", "c_alias"))
@pytest.mark.parametrize("displaced", (False, True))
def test_startup_alias_on_swap_is_atomic_without_evidence_or_branch_changes(
    count: int, saved_on: str, displaced: bool,
) -> None:
    predictive_map = gate_map(aliases=True)
    engine = ZoneModelEngine(predictive_map, count, at(0))
    for seconds, node in enumerate(("a", "b", saved_on)):
        observe(engine, node, "on", seconds)
    if displaced:
        observe(engine, "x", "on", 3)
    startup_on = "c_alias" if saved_on == "c" else "c"
    engine.advance(at(100))
    before = engine.snapshot
    events = tuple(SensorInput(alias, value, at(100))
                   for state in before.episode_states
                   for alias, old in state.alias_states
                   for value in ("on" if alias == f"binary_sensor.{startup_on}"
                                 else "off" if alias == f"binary_sensor.{saved_on}"
                                 else old,))
    inverse = roundtrip(engine, predictive_map)
    engine.reconcile_restored_asserted_contexts(events, at(100))
    inverse.reconcile_restored_asserted_contexts(tuple(reversed(events)), at(100))
    assert inverse.snapshot == engine.snapshot
    original = next(state for state in before.episode_states if state.node_id == "c")
    current = next(state for state in engine.snapshot.episode_states
                   if state.node_id == "c")
    assert current == replace(
        original, alias_states=tuple(sorted((
            (f"binary_sensor.{saved_on}", "off"),
            (f"binary_sensor.{startup_on}", "on"),
        ))), last_event_at=at(100),
    )
    assert engine.snapshot.belief_states == before.belief_states
    assert engine.snapshot.selected_sources == before.selected_sources
    assert engine.snapshot.selected_paths == before.selected_paths
    assert engine.snapshot.policy_states == before.policy_states
    assert belief(engine).physical_hold
    assert engine.snapshot.reliability_warning_occurrences == ()
    roundtrip(engine, predictive_map)
    engine.reconcile_restored_asserted_contexts(events, at(100))
    assert engine.snapshot == inverse.snapshot
    result = engine.advance(at(110))
    assert result.policy_events == ()
    assert belief(engine).physical_hold and policy(engine).active
    assert not any(item.kind == "stable_clear" for item in belief(engine).contributions)
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("level", ("off", "unknown", "unavailable", "missing"))
def test_startup_no_on_is_neutral_and_cannot_remint_after_peer_loss(
    count: int, level: str,
) -> None:
    predictive_map = gate_map(aliases=True, peer=True)
    engine = retired(predictive_map, count)
    observe(engine, "c_alias", "off", 4)
    observe(engine, "d", "on", 5)
    engine.advance(at(100))
    before = engine.snapshot
    original = next(state for state in before.episode_states if state.node_id == "c")
    events = tuple(SensorInput(alias, level if alias == "binary_sensor.c" else value,
                               at(100))
                   for state in before.episode_states
                   for alias, value in state.alias_states
                   if not (level == "missing" and alias == "binary_sensor.c"))
    engine.reconcile_restored_asserted_contexts(events, at(100))
    current = next(state for state in engine.snapshot.episode_states
                   if state.node_id == "c")
    assert current.status == ("baseline" if level == "off" else "unavailable")
    assert current.episode_id == original.episode_id
    assert current.generation == original.generation
    assert current.clear_started_at is current.clear_deadline is None
    assert not current.clear_emitted
    assert current.traversal_valid_until is None
    assert dict(current.alias_states)["binary_sensor.c"] == (
        "unknown" if level == "missing" else level
    )
    assert engine.snapshot.selected_paths == before.selected_paths
    assert belief(engine).probability == next(
        state.probability for state in before.belief_states if state.zone == "c"
    )
    assert belief(engine).physical_hold
    roundtrip(engine, predictive_map)
    observe(engine, "c", "off", 101)
    observe(engine, "d", "unavailable", 102)
    assert not belief(engine).physical_hold
    roundtrip(engine, predictive_map)
    engine.advance(at(120))
    assert not belief(engine).physical_hold
    assert not any(item.kind == "stable_clear" for item in belief(engine).contributions)
    assert engine.snapshot.reliability_warning_occurrences == ()
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (0, 1, 2))
@pytest.mark.parametrize("on_alias", ("c", "c_alias"))
def test_cold_bootstrap_alias_on_seeds_once_without_live_origin(
    count: int, on_alias: str,
) -> None:
    predictive_map = gate_map(aliases=True)
    engine = ZoneModelEngine(predictive_map, count, at(0))
    engine.bootstrap_sensor_snapshot((
        SensorInput(f"binary_sensor.{on_alias}", "on", at(0)),
        SensorInput("binary_sensor.c_alias" if on_alias == "c"
                    else "binary_sensor.c", "unknown", at(0)),
    ), at(0))
    state = next(state for state in engine.snapshot.episode_states
                 if state.node_id == "c")
    assert state.generation == 1 and state.known_on
    assert sum(item.kind == "local_positive" for item in belief(engine).contributions
               ) == (1 if count else 0)
    assert not belief(engine).physical_hold and not policy(engine).active
    assert all(source.origin == "none" for source in engine.snapshot.selected_sources)
    assert all(path is None for path in engine.snapshot.selected_paths)
    roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("saved_on", ("c", "c_alias"))
@pytest.mark.parametrize("displaced", (False, True))
def test_runtime_startup_alias_swap_has_no_false_off_on_or_warning(
    count: int, saved_on: str, displaced: bool,
) -> None:
    predictive_map = gate_map(aliases=True)
    with RuntimeScenario(at(0)) as scenario:
        live = scenario.create(predictive_map, count)
        for seconds, node in enumerate(("a", "b", saved_on)):
            live.send(f"binary_sensor.{node}", "on", at(seconds))
        if displaced:
            live.send("binary_sensor.x", "on", at(3))
        payload = json.loads(json.dumps(live.checkpoint()))
        live.close()
        scenario.clock.advance(at(100))
        restored = scenario.create(predictive_map, count).watch_reliability()
        asyncio.run(restored.runtime.async_stop())
        startup_on = "c_alias" if saved_on == "c" else "c"
        restored.hass.values.update({
            entity: SimpleNamespace(state=value)
            for entity, value in (
                ("binary_sensor.a", "on"), ("binary_sensor.b", "on"),
                (f"binary_sensor.{saved_on}", "off"),
                (f"binary_sensor.{startup_on}", "on"),
                ("binary_sensor.x", "on" if displaced else "unknown"),
                ("binary_sensor.y", "unknown"),
            )
        })
        restored.restore(payload)
        restored.runtime.start()
        assert restored.normalized_inputs == []
        assert restored.edges_for("c") == (ActiveEdge(at(100), "c", True),)
        assert restored.input_edges_for("c") == ()
        restored.inference_snapshot()  # Strict current-state writer/reader.
        restored.advance(at(130))
        assert restored.edges_for("c") == (ActiveEdge(at(100), "c", True),)
        assert restored.edges_for("a") == restored.edges_for("y") == ()
        assert restored.edges_for("x") == (
            (ActiveEdge(at(100), "x", True),) if displaced else ()
        )
        warnings = restored.reliability_attributes
        assert warnings is not None and warnings["active_count"] == 0
        restored.inference_snapshot()

