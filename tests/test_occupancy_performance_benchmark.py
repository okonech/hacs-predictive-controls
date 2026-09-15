from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pytest

from benchmarks import occupancy_performance as benchmark
from benchmarks.occupancy_performance import (
    FAST_PATH_HARD_MS,
    FAST_PATH_P99_MS,
    MAX_BENCHMARK_EVENTS,
    ROUTINE_BENCHMARK_EVENTS,
    TRACE_PROFILES,
    _assert_handoff_source,
    _build_workload,
    _capture_workload,
    _handoff_fixture,
    _handoff_qualified,
    _measure_core,
    _measure_fast_paths,
    _measure_timer_work,
    _render_json,
    _semantic_differences,
    _semantic_value,
    compare_semantic,
    main,
    run_benchmark,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
    target_map_fingerprint,
)
from custom_components.predictive_controls.zone_model.prediction import PredictionLease
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
    ZoneModelSnapshot,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
MAP_PATH = Path(__file__).parents[1] / "benchmarks" / "reference-map.yaml"
RESULTS_PATH = Path(__file__).parents[1] / "PERFORMANCE_RESULTS.json"
HANDOFF_PATHS = {"settled_adjacent_transfer", "correlated_settled_adjacent_transfer"}
EXISTING_FAST_PATHS = {
    "adjacent_pair", "boundary", "cadence_correlated_target", "confirmed_token",
    "correlated_continuity", "local_interaction", "missed_edge", "mature_prediction",
    "same_zone", "third_node_confirmation",
}
CURRENT_FAST_PATHS = (EXISTING_FAST_PATHS | HANDOFF_PATHS) - {"missed_edge"}
# These existing mechanism-mutation cases exercise selected movement, not
# predicted policy grants. Mature prediction remains mandatory in live acceptance.
SELECTED_ACQUISITION_PATHS = CURRENT_FAST_PATHS - {"mature_prediction"}


# The normal repository check intentionally skips importing benchmark internals.
# Keep the actual call/return contracts here, and validate their dynamic returns.
PredictionProof = tuple[
    PredictiveMap, tuple[PredictionLease, ...], Mapping[str, Mapping[str, float]],
]
FastPathOperation = tuple[ZoneModelSnapshot, ZoneModelResult, str, str, datetime]
FastPathPredicate = Callable[
    [str, ZoneModelSnapshot, ZoneModelResult, str, str, datetime,
     PredictionProof | None], bool,
]
RejectionChecks = Callable[
    [ZoneModelSnapshot, ZoneModelResult, str, str, datetime], dict[str, bool],
]
MeasurementReports = dict[str, dict[str, object]]


class AcquisitionPredicate(Protocol):
    def __call__(
        self, before: ZoneModelSnapshot, result: ZoneModelResult,
        target_zone: str, event_at: datetime,
        prediction: PredictionProof | None = None,
        *, require_prediction: bool = False,
    ) -> bool: ...


def _checked_boolean(value: object) -> bool:
    """Validate the skipped-import return, never coerce a truthy non-boolean."""
    assert isinstance(value, bool)
    return value


def _checked_flags(value: object) -> dict[str, bool]:
    """Preserve every flag/key while checking the real predicate return shape."""
    assert isinstance(value, dict)
    flags: dict[str, bool] = {}
    for key, flag in value.items():
        assert isinstance(key, str)
        flags[key] = _checked_boolean(flag)
    return flags


def _checked_reports(value: object) -> MeasurementReports:
    """Check collection/record keys without replacing any measurement values."""
    assert isinstance(value, dict)
    reports: dict[str, dict[str, object]] = {}
    for name, raw in value.items():
        assert isinstance(name, str)
        assert isinstance(raw, dict)
        record: dict[str, object] = {}
        for key, item in raw.items():
            assert isinstance(key, str)
            record[key] = item
        reports[name] = record
    return reports


def _checked_number(value: object) -> int | float:
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return value


def _complete_component_reports(iterations: int) -> tuple[
    dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]],
]:
    """Explicit COMPONENT gate operands, never claimed as measured acquisitions."""
    fast = {name: {
        "current_equivalent": benchmark.FAST_PATH_EQUIVALENTS[name],
        "requested_count": iterations, "attempt_count": iterations,
        "prior_off_count": iterations, "sample_count": iterations,
        "activation_count": iterations, "path_qualification_count": iterations,
        "publication_count": iterations, "public_write_count": iterations,
        "fanout_count": iterations, "registered_entity_count": 34,
        "dispatch_callback_count": 18 * iterations,
        "update_subscriber_count": 18, "failure_reasons": [],
        "all_activated": True, "all_path_qualified": True,
        "all_publications_scheduled": True, "p99_gate": True, "hard_gate": True,
        "p99_ms": FAST_PATH_P99_MS, "max_ms": FAST_PATH_HARD_MS - 0.001,
    } for name in CURRENT_FAST_PATHS}
    timer = {name: {
        "requested_count": iterations, "attempt_count": iterations,
        "sample_count": iterations, "completion_count": iterations,
        "all_completed": True, "p95_gate": True, "hard_gate": True,
        "p95_ms": benchmark.PREFERRED_CALLBACK_MS,
        "max_ms": benchmark.HARD_CALLBACK_MS,
    } for name in ("pending_expiry", "unsupported_on_health_deadline")}
    negative = {"rejected_jump": {
        "requested_count": iterations, "attempt_count": iterations,
        "sample_count": iterations, "outcome": "rejected", "failure_reasons": [],
        "on_write_count": 0, "acquired_event_count": 0,
        "public_write_count": iterations, "registered_entity_count": 34,
        "dispatch_callback_count": 18 * iterations,
        "update_subscriber_count": 18, "occupants": 2,
        "p99_ms": FAST_PATH_P99_MS, "max_ms": FAST_PATH_HARD_MS - 0.001,
        **{f"{key}_count": iterations for key in (
            "prior_off", "remained_off", "rejection", "warning", "selection_unchanged",
            "no_acquired", "fanout", "qualified",
        )},
    }}
    return fast, timer, negative


def _stub_complete_reports(monkeypatch: pytest.MonkeyPatch, iterations: int) -> None:
    fast, timer, negative = _complete_component_reports(iterations)
    monkeypatch.setattr(benchmark, "_measure_fast_paths", lambda *a, **k: fast)
    monkeypatch.setattr(benchmark, "_measure_timer_work", lambda *a, **k: timer)
    monkeypatch.setattr(benchmark, "_measure_rejected_jumps", lambda *a, **k: negative)


@pytest.mark.parametrize("family", ("fast", "timer", "negative"))
@pytest.mark.parametrize("mutation", (
    "unchanged", "empty", "missing", "renamed", "extra", "partial", "flag_only",
    "nan", "over", "boolean_count",
))
def test_required_workload_inventory_and_counters_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], family: str, mutation: str,
) -> None:
    """PERF001/002/007/008: forged flags and absent paths cannot pass CLI."""
    fast, timer, negative = _complete_component_reports(2)
    reports = {"fast": fast, "timer": timer, "negative": negative}
    selected = reports[family]
    key = sorted(selected)[0]
    trace = selected[key]
    if mutation == "empty":
        selected.clear()
    elif mutation == "missing":
        del selected[key]
    elif mutation == "renamed":
        selected["not_the_workload"] = selected.pop(key)
    elif mutation == "extra":
        selected["extra_workload"] = dict(trace)
    elif mutation == "partial":
        trace["sample_count"] = 1
    elif mutation == "flag_only":
        trace["completion_count" if family == "timer" else
              "qualified_count" if family == "negative" else
              "path_qualification_count"] = 1
    elif mutation == "boolean_count":
        trace["attempt_count"] = True
    elif mutation == "nan":
        trace["max_ms"] = float("nan")
    elif mutation == "over":
        trace["max_ms"] = (benchmark.HARD_CALLBACK_MS + 0.001
                           if family == "timer" else FAST_PATH_HARD_MS)
    monkeypatch.setattr(benchmark, "_measure_fast_paths", lambda *a, **k: fast)
    monkeypatch.setattr(benchmark, "_measure_timer_work", lambda *a, **k: timer)
    monkeypatch.setattr(benchmark, "_measure_rejected_jumps", lambda *a, **k: negative)
    report = run_benchmark(MAP_PATH, event_count=2)
    assert report["passed"] is (mutation == "unchanged")
    output = tmp_path / "inventory.json"
    monkeypatch.setattr("sys.argv", ["benchmark", "--events", "2", "--output",
                                     str(output)])
    if mutation == "unchanged":
        main()
    else:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == (2 if mutation == "nan" else 1)
    captured = capsys.readouterr()
    assert captured.out == ""
    if mutation == "nan":
        assert not output.exists()
        assert json.loads(captured.err)["passed"] is False
    else:
        assert captured.err == ("" if mutation == "unchanged" else output.read_text())
        assert json.loads(output.read_text())["passed"] is (mutation == "unchanged")


def test_actual_mature_prediction_is_an_acquisition_not_a_local_episode(
    predictive_map: PredictiveMap,
) -> None:
    """Minimal predicate red, separate from the independently proved write bug."""
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    for _ in range(11):
        engine.prediction_manager.chain.observe("stairs_bottom_sensor",
                                                 "guest_bedroom_sensor")
    for ms, node in enumerate(("dining_sensor", "foyer_sensor"), 1):
        engine.observe(SensorInput(next(iter(predictive_map.nodes[node].entities.values())),
                                   "on", NOW + timedelta(milliseconds=ms)))
    before = engine.snapshot
    at = NOW + timedelta(milliseconds=3)
    result = engine.observe(SensorInput(next(iter(
        predictive_map.nodes["stairs_bottom_sensor"].entities.values())), "on", at))
    assert any(e.zone == "guest_bedroom" and e.kind == "acquired"
               for e in result.policy_events)
    assert any(lease.mature and lease.target_zone == "guest_bedroom"
               for lease in engine.prediction_manager.leases)
    # Both gates require real post-operation independent state.
    proof = (predictive_map, engine.prediction_manager.leases,
             engine.prediction_manager.chain.counts)
    assert benchmark._acquisition_qualified(before, result, "guest_bedroom", at, proof)
    assert benchmark._fast_path_qualified(
        "mature_prediction", before, result, "stairs_bottom_sensor", "guest_bedroom",
        at, proof,
    )


def test_duplicate_matching_acquisition_decision_is_not_qualified(
    predictive_map: PredictiveMap,
) -> None:
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    engine.observe(SensorInput(next(iter(
        predictive_map.nodes["entrance_sensor"].entities.values())), "on", NOW))
    before = engine.snapshot
    at = NOW + timedelta(seconds=1)
    result = engine.observe(SensorInput(next(iter(
        predictive_map.nodes["bathroom_laundry_sensor"].entities.values())), "on", at))
    assert benchmark._acquisition_qualified(before, result, "bathroom_laundry", at)
    decision = next(d for d in result.policy_decisions if d.event_kind == "acquired")
    corrupted = replace(result, policy_decisions=(*result.policy_decisions, decision))
    assert not benchmark._acquisition_qualified(
        before, corrupted, "bathroom_laundry", at,
    )


@pytest.mark.parametrize("mutation", (
    "unchanged", "missing_proof", "missing_leases", "missing_grant", "missing_counts",
    "immature", "support", "probability", "full_row", "expired", "wrong_source",
    "wrong_target_node", "wrong_target_zone", "wrong_time", "prior_on", "no_event",
    "duplicate_event", "refresh", "no_decision", "duplicate_decision", "wrong_reason",
    "wrong_evidence", "uncommitted_authorization",
))
def test_mature_prediction_requires_independent_provenance_in_both_predicates(
    predictive_map: PredictiveMap, mutation: str,
) -> None:
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    for _ in range(11):
        engine.prediction_manager.chain.observe("stairs_bottom_sensor",
                                                 "guest_bedroom_sensor")
    for ms, node in enumerate(("dining_sensor", "foyer_sensor"), 1):
        engine.observe(SensorInput(next(iter(
            predictive_map.nodes[node].entities.values())), "on",
            NOW + timedelta(milliseconds=ms)))
    before = engine.snapshot
    at = NOW + timedelta(milliseconds=3)
    source, zone = "stairs_bottom_sensor", "guest_bedroom"
    result = engine.observe(SensorInput(next(iter(
        predictive_map.nodes[source].entities.values())), "on", at))
    leases = engine.prediction_manager.leases
    counts = engine.prediction_manager.chain.counts
    proof: PredictionProof | None = (predictive_map, leases, counts)
    assert benchmark._acquisition_qualified(before, result, zone, at, proof)
    assert benchmark._fast_path_qualified("mature_prediction", before, result,
                                          source, zone, at, proof)
    if mutation == "missing_proof":
        proof = None
    elif mutation == "missing_leases":
        proof = (predictive_map, (), counts)
    elif mutation == "missing_grant":
        result = replace(result, snapshot=replace(result.snapshot,
                                                  selected_prediction_grants=()))
    elif mutation in {"missing_counts", "full_row"}:
        if mutation == "missing_counts":
            counts = {}
        else:
            counts[source]["stairs_top_sensor"] = 100.0
        proof = (predictive_map, leases, counts)
    elif mutation in {"immature", "support", "probability", "expired", "wrong_source",
                      "wrong_target_node"}:
        changes: dict[str, object] = {
            "immature": {"mature": False}, "support": {"support": 4.0},
            "probability": {"probability": 0.84},
            "expired": {"expires_at": at},
            "wrong_source": {"source_node_id": "dining_sensor"},
            "wrong_target_node": {"target_node_id": "stairs_top_sensor"},
        }
        fields_changed = changes[mutation]
        assert isinstance(fields_changed, dict)
        leases = tuple(
            replace(lease, **fields_changed) if lease.target_zone == zone else lease
            for lease in leases
        )
        proof = (predictive_map, leases, counts)
    elif mutation == "wrong_target_zone":
        zone = "office_a"
    elif mutation == "wrong_time":
        at += timedelta(microseconds=1)
    elif mutation == "prior_on":
        before = replace(before, policy_states=result.snapshot.policy_states)
    elif mutation in {"no_event", "duplicate_event", "refresh"}:
        events = tuple(e for e in result.policy_events if e.zone == zone)
        target_event, = events
        kept = tuple(e for e in result.policy_events if e.zone != zone)
        replacement = (() if mutation == "no_event" else
                       (target_event, target_event) if mutation == "duplicate_event"
                       else (replace(target_event, kind="refreshed"),))
        result = replace(result, policy_events=(*kept, *replacement))
    elif mutation in {"no_decision", "duplicate_decision", "wrong_reason",
                      "wrong_evidence"}:
        decision = next(d for d in result.policy_decisions
                        if d.zone == zone and d.event_kind == "acquired")
        kept_decisions = tuple(d for d in result.policy_decisions if d is not decision)
        replacement_decisions = (
            () if mutation == "no_decision" else
            (decision, decision) if mutation == "duplicate_decision" else
            (replace(decision, reason="acquired"),) if mutation == "wrong_reason" else
            (replace(decision, evidence_ids=()),)
        )
        result = replace(result, policy_decisions=(*kept_decisions,
                                                   *replacement_decisions))
    elif mutation == "uncommitted_authorization":
        result = replace(result, authorizations=())
    assert benchmark._acquisition_qualified(before, result, zone, at, proof) is (
        mutation == "unchanged"
    )
    assert benchmark._fast_path_qualified("mature_prediction", before, result,
                                          source, zone, at, proof) is (
        mutation == "unchanged"
    )


@pytest.fixture
def actual_mature_prediction_operation(predictive_map: PredictiveMap) -> tuple[
    ZoneModelSnapshot, ZoneModelResult, str, str, datetime, PredictionProof,
]:
    """Reuse the actual eleven-support history without altering existing fixtures."""
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    source, zone = "stairs_bottom_sensor", "guest_bedroom"
    for _ in range(11):
        engine.prediction_manager.chain.observe(source, "guest_bedroom_sensor")
    for ms, node in enumerate(("dining_sensor", "foyer_sensor"), 1):
        engine.observe(SensorInput(next(iter(
            predictive_map.nodes[node].entities.values())), "on",
            NOW + timedelta(milliseconds=ms)))
    before = engine.snapshot
    at = NOW + timedelta(milliseconds=3)
    result = engine.observe(SensorInput(next(iter(
        predictive_map.nodes[source].entities.values())), "on", at))
    proof = (predictive_map, engine.prediction_manager.leases,
             engine.prediction_manager.chain.counts)
    return before, result, source, zone, at, proof


def _ordinary_prediction_counterfeit(
    result: ZoneModelResult, zone: str, proof: PredictionProof,
    mutation: str,
) -> tuple[ZoneModelResult, PredictionProof]:
    """Synthetic gate operands, not a claimed real acquisition or restorable state."""
    model, leases, counts = proof
    target = next(p for p in result.snapshot.policy_states if p.zone == zone)
    lease = next(lease for lease in leases if lease.target_zone == zone)
    source_zone = model.nodes[lease.current_node_id].occupancy_zone
    source = next(p for p in result.snapshot.policy_states if p.zone == source_zone)
    event = next(e for e in result.policy_events if e.zone == zone)
    assert target.phase == "predicted" and source.phase == "active"
    assert lease.mature and result.snapshot.selected_prediction_grants and counts
    # Reuse the same operation's ordinary policy shape at the predicted target.
    # Keep its real lease even when independent grants/counts are absent.
    ordinary = replace(source, zone=zone, profile_name=target.profile_name)
    snapshot = replace(result.snapshot, policy_states=tuple(
        ordinary if p.zone == zone else p for p in result.snapshot.policy_states
    ))
    if mutation in {"missing_grants", "missing_both"}:
        snapshot = replace(snapshot, selected_prediction_grants=())
    if mutation in {"missing_counts", "missing_both"}:
        counts = {}
    corrupted = replace(
        result, snapshot=snapshot,
        policy_events=tuple(
            replace(e, authorization_reason="selected_path", policy_reason="acquired")
            if e.zone == zone else e for e in result.policy_events
        ),
        policy_decisions=tuple(
            replace(d, reason="acquired", episode_id=event.episode_id,
                    traversal_reason="selected_path")
            if d.zone == zone else d for d in result.policy_decisions
        ),
    )
    return corrupted, (model, leases, counts)


@pytest.mark.parametrize("mutation", (
    "full_proof", "missing_grants", "missing_counts", "missing_both",
))
def test_mature_prediction_rejects_ordinary_acquisition_counterfeit(
    actual_mature_prediction_operation: tuple[
        ZoneModelSnapshot, ZoneModelResult, str, str, datetime,
        PredictionProof,
    ], mutation: str,
) -> None:
    """Sept13 source review: an ordinary edge plus lease must not certify prediction."""
    before, result, source, zone, at, proof = actual_mature_prediction_operation
    assert benchmark._acquisition_qualified(before, result, zone, at, proof)
    assert benchmark._fast_path_qualified(
        "mature_prediction", before, result, source, zone, at, proof,
    )
    corrupted, proof = _ordinary_prediction_counterfeit(result, zone, proof, mutation)
    # Ordinary acquisition semantics remain valid, even with incidental leases.
    assert benchmark._acquisition_qualified(before, corrupted, zone, at, proof)
    assert not benchmark._fast_path_qualified(
        "mature_prediction", before, corrupted, source, zone, at, proof,
    )


@pytest.mark.parametrize("mutation", (
    "full_proof", "missing_grants", "missing_counts", "missing_both",
))
def test_mature_measurement_rejects_ordinary_acquisition_counterfeit(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    """Isolate the outer gate: a later predicate cannot hide cross-mode acceptance."""
    original_acquisition: AcquisitionPredicate = benchmark._acquisition_qualified
    original_path: FastPathPredicate = benchmark._fast_path_qualified
    mutated = 0

    def acquire(
        before: ZoneModelSnapshot, result: ZoneModelResult, zone: str, at: datetime,
        proof: PredictionProof | None = None, *, require_prediction: bool = False,
    ) -> bool:
        nonlocal mutated
        if proof is not None:
            assert original_acquisition(
                before, result, zone, at, proof, require_prediction=require_prediction,
            )
            result, proof = _ordinary_prediction_counterfeit(
                result, zone, proof, mutation,
            )
            mutated += 1
        return _checked_boolean(
            original_acquisition(
                before, result, zone, at, proof, require_prediction=require_prediction,
            ),
        )

    def path(
        name: str, before: ZoneModelSnapshot, result: ZoneModelResult,
        source: str, zone: str, at: datetime,
        proof: PredictionProof | None = None,
    ) -> bool:
        if name == "mature_prediction":
            return True  # Deliberately isolate the earlier acquisition gate.
        return _checked_boolean(
            original_path(name, before, result, source, zone, at, proof),
        )

    monkeypatch.setattr(benchmark, "_acquisition_qualified", acquire)
    monkeypatch.setattr(benchmark, "_fast_path_qualified", path)
    paths = _measure_fast_paths(predictive_map, iterations=1)
    assert set(paths) == CURRENT_FAST_PATHS and mutated == 1
    for name in SELECTED_ACQUISITION_PATHS:
        assert paths[name]["activation_count"] == 1
        assert paths[name]["path_qualification_count"] == 1
        assert paths[name]["publication_count"] == paths[name]["sample_count"] == 1
    trace = paths["mature_prediction"]
    assert trace["prior_off_count"] == trace["public_write_count"] == 1
    assert trace["activation_count"] == 0
    assert trace["path_qualification_count"] == trace["publication_count"] == 0
    assert trace["sample_count"] == 0
    assert trace["p99_ms"] is None and trace["max_ms"] is None
    assert not trace["all_activated"] and not trace["all_path_qualified"]
    assert not trace["p99_gate"] and not trace["hard_gate"]


@pytest.mark.parametrize("counter", (
    "requested_count", "attempt_count", "sample_count", "prior_off_count",
    "activation_count", "path_qualification_count", "publication_count",
    "public_write_count", "fanout_count",
))
def test_positive_aggregate_requires_every_count_despite_true_flags(
    counter: str,
) -> None:
    fast, _, _ = _complete_component_reports(2)
    assert all(benchmark._positive_workload_gates(fast, 2, 16).values())
    fast["mature_prediction"][counter] = 1
    assert not all(benchmark._positive_workload_gates(fast, 2, 16).values())


@pytest.mark.parametrize("counter", (
    "requested_count", "attempt_count", "sample_count", "completion_count",
))
def test_timer_aggregate_requires_every_count_despite_true_flags(counter: str) -> None:
    _, timer, _ = _complete_component_reports(2)
    assert all(benchmark._timer_workload_gates(timer, 2).values())
    timer["pending_expiry"][counter] = 1
    assert not all(benchmark._timer_workload_gates(timer, 2).values())


@pytest.mark.parametrize(("metric", "value", "passes"), (
    ("p99_ms", 5.0, True), ("p99_ms", 5.000001, False),
    ("max_ms", 9.999999, True), ("max_ms", 10.0, False),
    ("p99_ms", -1.0, False), ("max_ms", None, False),
))
def test_positive_latency_budget_is_unchanged_and_independent_of_flags(
    metric: str, value: float | None, passes: bool,
) -> None:
    fast, _, _ = _complete_component_reports(2)
    fast["mature_prediction"][metric] = value
    assert all(benchmark._positive_workload_gates(fast, 2, 16).values()) is passes


@pytest.mark.parametrize("target_only", (False, True))
def test_rejection_requires_executed_fanout_not_just_registered_handlers(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch, target_only: bool,
) -> None:
    """PERF007/008: registration cannot certify a bypassed real dispatcher."""
    types = benchmark._runtime_publication_types()

    def bypass(self: Any) -> None:
        if target_only:
            # Real zone callback but preceding Home/Problem/other zones skipped.
            callbacks: list[Callable[[], None]] = next(
                iter(self.hass._dispatch.values()), [],
            )
            if callbacks:
                callbacks[-1]()

    monkeypatch.setattr(types[0], "_dispatch_update", bypass)
    monkeypatch.setattr(benchmark, "_runtime_publication_types", lambda: types)
    measurements = benchmark._measure_rejected_jumps(predictive_map, iterations=1)
    assert measurements["rejected_jump"]["sample_count"] == 1
    assert not benchmark._negative_workload_gates(measurements, 1)["correctness"]


@pytest.fixture(scope="module")
def predictive_map() -> PredictiveMap:
    return load_predictive_map(MAP_PATH.read_text())


@pytest.mark.parametrize("profile", TRACE_PROFILES)
def test_benchmark_workloads_cover_target_profiles(
    predictive_map: PredictiveMap,
    profile: str,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=ROUTINE_BENCHMARK_EVENTS,
        started_at=NOW,
        occupants=2,
        trace_profile=profile,
    )

    assert len(workload.events) == ROUTINE_BENCHMARK_EVENTS
    assert len(workload.events) == len(workload.receive_at)
    assert workload.trace_profile == profile
    if profile == "out_of_order":
        assert any(
            later.event_at < earlier.event_at
            for earlier, later in zip(
                workload.events, workload.events[1:], strict=False
            )
        )
    if profile == "all_episodes_active":
        assert len({event.entity_id for event in workload.events[:17]}) == 17


def test_benchmark_rejects_more_than_one_thousand_events() -> None:
    with pytest.raises(ValueError, match="must not exceed 1000"):
        run_benchmark(MAP_PATH, event_count=MAX_BENCHMARK_EVENTS + 1)


def test_target_benchmark_reports_required_bounded_metrics() -> None:
    instrumented = run_benchmark(MAP_PATH, event_count=1, target_counts=(2,))
    assert set(instrumented["fast_paths"]) == CURRENT_FAST_PATHS
    assert instrumented["map"]["zones"] == 16
    assert instrumented["map"]["nodes"] == 17
    assert instrumented["map"]["occupants"] == [2]
    assert set(instrumented["negative_workloads"]) == {"rejected_jump"}
    for family in ("negative_gates", "positive_gates", "timer_gates"):
        assert all(value for gate, value in instrumented[family].items()
                   if not gate.endswith("latency"))
    for name, trace in instrumented["fast_paths"].items():
        assert trace["current_equivalent"] == benchmark.FAST_PATH_EQUIVALENTS[name]
        assert trace["attempt_count"] == trace["prior_off_count"] == 1
        assert trace["fixture_kind"] == (
            "synthetic_learned_counts_and_observations" if name == "mature_prediction"
            else "synthetic_observations"
        )
        assert trace["registered_entity_count"] == 34
        assert trace["update_subscriber_count"] == 18
        assert trace["failure_reasons"] == [], (name, trace["failure_reasons"])
        assert trace["sample_count"] == trace["activation_count"] == 1
        assert trace["path_qualification_count"] == 1
        assert trace["publication_count"] == 1
        assert trace["public_write_count"] == 1
        assert trace["requested_count"] == trace["fanout_count"] == 1
        assert all(math.isfinite(trace[key]) and trace[key] >= 0
               for key in ("p99_ms", "max_ms"))
        assert trace["all_activated"]
        assert trace["all_path_qualified"]
        assert trace["all_publications_scheduled"]
        assert trace["registered_entity_count"] == 34
        assert trace["update_subscriber_count"] == 18
    for name in HANDOFF_PATHS:
        assert instrumented["fast_paths"][name]["public_write_count"] == 1
    core = instrumented["counts"]["2"]["core"]
    assert core["selected_slot_max"] == core["selected_slot_limit"] == 2
    assert core["selected_path_max"] <= 2
    assert core["selected_visit_max"] <= core["selected_history_limit"] == 4
    assert core["selected_route_max"] <= 4
    assert core["selected_source_max"] == core["selected_source_limit"] == 17
    assert core["health_state_max"] == core["health_state_limit"] == 17
    assert core["health_cycle_max"] <= core["health_cycle_limit"] == 6
    assert all(value for gate, value in instrumented["counts"]["2"]["gates"].items()
               if gate not in {"preferred_callback", "hard_callback"})
    assert core["event_count"] == 1
    assert all(math.isfinite(core[key]) and core[key] >= 0 for key in (
        "startup_ms", "total_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms",
    ))
    assert set(instrumented["timer_work"]) == {
        "pending_expiry", "unsupported_on_health_deadline",
    }
    assert all(t["all_completed"] for t in instrumented["timer_work"].values())
    for trace in instrumented["timer_work"].values():
        assert trace["requested_count"] == trace["attempt_count"] == 1
        assert trace["sample_count"] == trace["completion_count"] == 1
        assert all(math.isfinite(trace[key]) and trace[key] >= 0
                   for key in ("p95_ms", "max_ms"))


def test_historical_benchmark_artifact_is_not_current_qualification() -> None:

    # The retained 100-sample result is generated by the standalone benchmark
    # process, outside pytest coverage instrumentation that changes wall time.
    result = json.loads(RESULTS_PATH.read_text())
    count = result["counts"]["2"]
    core = count["core"]

    assert result["engine"] == "zone_belief"
    assert core["event_count"] == 100
    assert core["max_ms"] <= 100.0
    assert core["token_max"] <= core["token_limit"]
    assert core["support_max"] <= core["support_limit"]
    assert core["support_binding_max"] <= core["support_binding_limit"]
    assert core["audit_bytes"] <= 2 * 1024 * 1024
    assert core["persistence_bytes"] > 0
    assert core["persistence_byte_stable"] is True
    # Historical checked-in aggregate is not new handoff qualification evidence.
    assert set(result["fast_paths"]) == EXISTING_FAST_PATHS
    for trace in result["fast_paths"].values():
        assert trace["all_activated"]
        assert trace["all_path_qualified"]
        assert trace["all_publications_scheduled"]
        assert trace["registered_entity_count"] == 34
        assert trace["update_subscriber_count"] == 18
        assert trace["p99_ms"] <= FAST_PATH_P99_MS
        assert trace["max_ms"] < FAST_PATH_HARD_MS
    assert set(result["timer_work"]) == {"pending_expiry", "count_conflict"}
    for trace in result["timer_work"].values():
        assert trace["sample_count"] == 100
        assert trace["all_completed"]
        assert trace["p95_gate"]
        assert trace["hard_gate"]
    assert all(count["gates"].values())
    assert result["passed"] is True


@pytest.mark.parametrize("correlated", (False, True))
def test_handoff_fixture_is_selected_asserted_and_repeatably_continuable(
    predictive_map: PredictiveMap, correlated: bool,
) -> None:
    fingerprint = target_map_fingerprint(predictive_map)
    assert len(predictive_map.zones()) == 16 and len(predictive_map.nodes) == 17
    snapshot = _handoff_fixture(predictive_map, NOW, correlated=correlated)
    frozen = _render_json(_semantic_value(snapshot))
    path, unlocated = snapshot.selected_paths
    assert path is not None and unlocated is None
    source = next(v for v in path.route if v.node_id == "guest_bedroom_sensor")
    assert source.branch_active
    assert tuple(v.node_id for v in path.route) == (
        ("foyer_sensor", "stairs_bottom_sensor", "guest_bedroom_sensor",
         "stairs_bottom_sensor") if correlated else
        ("dining_sensor", "foyer_sensor", "stairs_bottom_sensor",
         "guest_bedroom_sensor")
    )
    at = snapshot.updated_at + timedelta(microseconds=1)
    source_episode = next(
        s for s in snapshot.episode_states if s.node_id == source.node_id
    )
    assert source_episode.started_at == NOW + timedelta(seconds=3)
    assert at - source_episode.started_at == timedelta(hours=2)
    target = next(
        s for s in snapshot.episode_states if s.node_id == "living_left_sensor"
    )
    assert (target.cadence_run_started_at is not None) == correlated
    if correlated:
        assert target.status == "clear"
        assert all(value == "off" for _, value in target.alias_states)
        assert target.cadence_run_started_at == NOW + timedelta(seconds=6603)
        assert target.cadence_last_transition_at == NOW + timedelta(seconds=6613)
        assert any(v.node_id == target.node_id and not v.branch_active
                   for v in path.visits)
    else:
        assert target.generation == 0
    assert not next(p for p in snapshot.policy_states if p.zone == "living_room").active
    assert all(p.node_id == "living_left_sensor" for p in snapshot.pending_candidates)
    results = []
    for _ in range(2):
        engine = ZoneModelEngine.restore(
            predictive_map, snapshot, (), snapshot.updated_at,
        )
        payload = serialize_target_state(predictive_map, engine)
        engine = restore_target_state(predictive_map, payload, snapshot.updated_at)
        assert serialize_target_state(predictive_map, engine) == payload
        # Independent same-frontier projection distinguishes elapsed decay from
        # forbidden synthetic renewal or a handoff-induced source likelihood.
        projected = restore_target_state(predictive_map, payload, at).snapshot
        _assert_handoff_source(predictive_map, projected)
        before_prediction = engine.prediction_manager.serialize()
        before_counts = engine.prediction_manager.chain.counts
        before_pending = tuple(engine._pending_prediction_learning)
        event = SensorInput(
            next(iter(predictive_map.nodes["living_left_sensor"].entities.values())),
            "on", at,
        )
        result = engine.observe(event)
        assert _handoff_qualified(snapshot, result, correlated=correlated)
        assert not _handoff_qualified(snapshot, result, correlated=not correlated)
        assert next(s for s in result.snapshot.episode_states
                    if s.node_id == source.node_id) == next(
                        s for s in projected.episode_states
                        if s.node_id == source.node_id
                    )
        assert next(s for s in result.snapshot.belief_states
                    if s.zone == source.zone) == next(
                        s for s in projected.belief_states
                        if s.zone == source.zone
                    )
        assert not engine._pending_prediction_learning
        assert tuple(engine._pending_prediction_learning) == before_pending == ()
        assert engine.prediction_manager.chain.counts == before_counts
        if correlated:
            # Genuine correlated/legacy transfer exclusions remain nonissuing.
            assert engine.prediction_manager.serialize() == before_prediction
        else:
            # PRED008 selected execution is not PRED007 legacy-transfer learning.
            grants = result.snapshot.selected_prediction_grants
            leases = engine.prediction_manager.leases
            assert grants and len(grants) == len(leases) <= 64
            assert {g.key for g in grants} == {
                (lease.source_node_id, lease.current_node_id, lease.target_node_id,
                 lease.source_episode_id) for lease in leases
            }
            assert all(g.authorization == result.authorizations[0]
                       and g.effect_kind == "positive"
                       and g.expires_at == at + timedelta(seconds=10) for g in grants)
            assert all(
                lease.source_node_id == source.node_id
                and lease.current_node_id == "living_left_sensor"
                and lease.target_node_id
                in predictive_map.nodes[lease.current_node_id].adjacent
                and lease.source_episode_id
                == result.authorizations[0].target_episode_id
                and lease.authority_kind == "selected_prediction_grant"
                and lease.created_at == at
                and lease.expires_at == at + timedelta(seconds=10)
                and not lease.mature and lease.support == 0 for lease in leases
            )
        assert not result.snapshot.traversal_tokens
        assert not result.snapshot.support_token_bindings
        assert not result.snapshot.anonymous_supports
        moved_path, unlocated = result.snapshot.selected_paths
        assert moved_path is not None and unlocated is None
        assert moved_path.endpoint.node_id == "living_left_sensor"
        assert moved_path.endpoint.at == at
        assert source in moved_path.route
        assert not result.snapshot.pending_candidates
        assert not engine.observe(event).policy_events
        moved = serialize_target_state(predictive_map, engine)
        restored = restore_target_state(predictive_map, moved, at)
        assert serialize_target_state(predictive_map, restored) == moved
        if not correlated:
            restored.advance(at + timedelta(seconds=9, microseconds=999999))
            assert restored.prediction_manager.leases == leases
            assert restored.snapshot.selected_prediction_grants == grants
            restored.advance(at + timedelta(seconds=10))
            assert restored.prediction_manager.leases == ()
            assert restored.snapshot.selected_prediction_grants == ()
            assert restored.prediction_manager.chain.counts == before_counts
        results.append(result)
    assert results[0] == results[1]
    assert _render_json(_semantic_value(snapshot)) == frozen
    assert target_map_fingerprint(predictive_map) == fingerprint


@pytest.mark.parametrize("mutation", (
    "no_authorization", "wrong_provenance", "no_public_event", "refresh",
    "no_selected_movement", "no_continuation", "wrong_disposition",
    "no_decision", "wrong_target", "already_active", "source_changed",
    "wrong_source", "wrong_route",
))
def test_handoff_qualification_rejects_unproven_path_or_acquisition(
    predictive_map: PredictiveMap, mutation: str,
) -> None:
    snapshot = _handoff_fixture(predictive_map, NOW, correlated=False)
    engine = ZoneModelEngine.restore(predictive_map, snapshot, (), snapshot.updated_at)
    result = engine.observe(SensorInput(
        next(iter(predictive_map.nodes["living_left_sensor"].entities.values())),
        "on", snapshot.updated_at + timedelta(microseconds=1),
    ))
    assert _handoff_qualified(snapshot, result, correlated=False)
    if mutation == "no_authorization":
        result = replace(result, authorizations=())
    elif mutation == "wrong_provenance":
        result = replace(result, authorizations=(replace(
            result.authorizations[0], reason="boundary_authorized",
            provenance_kind="boundary", selected_source_episode_ids=(),
            path_node_ids=("living_left_sensor",),
        ),))
    elif mutation == "no_public_event":
        result = replace(result, policy_events=())
    elif mutation == "refresh":
        result = replace(result, policy_events=(replace(
            result.policy_events[0], kind="refreshed",
        ),))
    elif mutation == "no_selected_movement":
        result = replace(result, snapshot=replace(
            result.snapshot, selected_paths=(None, None),
        ))
    elif mutation == "no_continuation":
        result = replace(result, snapshot=replace(
            result.snapshot, selected_paths=snapshot.selected_paths,
        ))
    elif mutation == "no_decision":
        result = replace(result, policy_decisions=())
    elif mutation == "wrong_target":
        result = replace(result, policy_events=(replace(
            result.policy_events[0], zone="guest_bedroom",
        ),))
    elif mutation == "already_active":
        snapshot = replace(snapshot, policy_states=result.snapshot.policy_states)
    elif mutation == "source_changed":
        result = replace(result, snapshot=replace(
            result.snapshot, episode_states=tuple(
                replace(e, last_event_at=result.snapshot.updated_at)
                if e.node_id == "guest_bedroom_sensor" else e
                for e in result.snapshot.episode_states
            ),
        ))
    elif mutation == "wrong_source":
        result = replace(result, authorizations=(replace(
            result.authorizations[0], selected_source_episode_ids=(
                f"guest_bedroom_sensor:2:{NOW.isoformat()}",
            ),
        ),))
    elif mutation == "wrong_route":
        result = replace(result, authorizations=(replace(
            result.authorizations[0],
            path_node_ids=("guest_bedroom_sensor", "living_left_sensor"),
        ),))
    else:
        result = replace(result, disposition="duplicate")
    assert not _handoff_qualified(snapshot, result, correlated=False)


def test_handoff_preparation_precedes_timing_and_each_event_gets_a_new_engine(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines: list[ZoneModelEngine] = []
    original = ZoneModelEngine.observe
    prepared = []
    fixture = benchmark._handoff_fixture

    def prepare(*args: Any, **kwargs: Any) -> ZoneModelSnapshot:
        snapshot = fixture(*args, **kwargs)
        assert isinstance(snapshot, ZoneModelSnapshot)
        prepared.append(snapshot)
        return snapshot

    def observe(
        self: ZoneModelEngine, event: SensorInput, **kwargs: Any,
    ) -> ZoneModelResult:
        if (event.entity_id == next(iter(
            predictive_map.nodes["living_left_sensor"].entities.values()))
            and event.event_at == NOW.replace(hour=15) + timedelta(seconds=3)):
            assert len(prepared) == 2
            assert self.snapshot in prepared
            assert all(self is not previous for previous in engines)
            engines.append(self)
        return original(self, event, **kwargs)

    monkeypatch.setattr(benchmark, "_handoff_fixture", prepare)
    monkeypatch.setattr(ZoneModelEngine, "observe", observe)
    paths = _measure_fast_paths(predictive_map, iterations=2)
    assert len(engines) == 4
    assert set(paths) == CURRENT_FAST_PATHS
    for name in HANDOFF_PATHS:
        trace = paths[name]
        assert trace["sample_count"] == trace["path_qualification_count"] == 2
        assert trace["public_write_count"] == trace["publication_count"] == 2


@pytest.mark.parametrize("iterations", (0, MAX_BENCHMARK_EVENTS + 1))
def test_fast_path_benchmark_rejects_invalid_iteration_bounds(
    predictive_map: PredictiveMap, iterations: int
) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        _measure_fast_paths(predictive_map, iterations=iterations)


@pytest.mark.parametrize("iterations", (0, MAX_BENCHMARK_EVENTS + 1))
def test_timer_work_benchmark_rejects_invalid_iteration_bounds(
    iterations: int,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        _measure_timer_work(iterations=iterations)


def test_out_of_order_workload_is_model_neutral_and_within_budget(
    predictive_map: PredictiveMap,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=100,
        started_at=NOW,
        occupants=2,
        trace_profile="out_of_order",
    )

    result, engine = _measure_core(predictive_map, workload)

    assert result["stale_event_count"] > 0
    assert result["event_count"] == 100
    assert all(math.isfinite(result[key]) and result[key] >= 0 for key in (
        "startup_ms", "total_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms",
    ))
    assert all(
        0.0 <= belief.probability <= 1.0 for belief in engine.snapshot.belief_states
    )


@pytest.fixture(scope="module")
def actual_fast_path_operations(
    predictive_map: PredictiveMap,
) -> dict[str, FastPathOperation]:
    """Capture real preconditions/results outside latency, never fabricate a path."""

    operations: dict[str, FastPathOperation] = {}
    original: FastPathPredicate = benchmark._fast_path_qualified

    def capture(
        name: str, before: ZoneModelSnapshot, result: ZoneModelResult,
        target_id: str, zone: str, at: datetime,
        prediction: PredictionProof | None = None,
    ) -> bool:
        operations[name] = (before, result, target_id, zone, at)
        return _checked_boolean(
            original(name, before, result, target_id, zone, at, prediction),
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(benchmark, "_fast_path_qualified", capture)
        _measure_fast_paths(predictive_map, iterations=1)
    # Preserve these selected-mechanism controls independently of prediction's
    # different policy contract. The live acceptance above still requires every ON.
    selected = {name: args for name, args in operations.items()
                if name in SELECTED_ACQUISITION_PATHS}
    assert set(selected) == SELECTED_ACQUISITION_PATHS
    return selected


def test_named_selected_fixtures_preserve_distinct_preconditions(
    actual_fast_path_operations: dict[str, FastPathOperation],
) -> None:
    operations = actual_fast_path_operations
    for name in ("adjacent_pair", "same_zone", "cadence_correlated_target"):
        before, result, target_id, zone, _ = operations[name]
        assert before.selected_paths == (None, None)
        source_id = result.authorizations[0].path_node_ids[-2]
        source = next(s for s in before.selected_sources if s.node_id == source_id)
        assert source.origin == "ordinary" and not source.consumed
        assert source.node_id != target_id
        if name == "same_zone":
            assert next(e.zone for e in before.episode_states
                        if e.node_id == source_id) == zone
        if name == "cadence_correlated_target":
            target = next(e for e in before.episode_states if e.node_id == target_id)
            assert target.status == "clear"
            assert target.cadence_run_started_at is not None
            assert result.disposition == "accepted_correlated_positive"
    for name, confidence, length in (
        ("third_node_confirmation", "provisional", 2),
        ("confirmed_token", "confirmed", 3),
    ):
        before, result, *_ = operations[name]
        path, unlocated = before.selected_paths
        assert path is not None and unlocated is None
        assert path.track_confidence == confidence and len(path.route) == length
        assert result.authorizations[0].track_confidence == "confirmed"
    before, result, *_ = operations["correlated_continuity"]
    source_episode = next(e for e in before.episode_states
                          if e.node_id == "stairs_top_sensor")
    assert source_episode.status == "asserted" and source_episode.known_on
    assert source_episode.started_at is not None
    assert source_episode.last_event_at is not None
    assert source_episode.started_at < source_episode.last_event_at
    assert source_episode.last_event_at.second == 45  # Actual correlated reassertion.
    assert result.authorizations[0].selected_source_episode_ids == (
        source_episode.episode_id,
    )
    before, result, *_ = operations["local_interaction"]
    assert before.selected_paths == (None, None)
    assert result.disposition == "accepted_interaction"
    assert result.authorizations[0].selected_source_episode_ids == ()


@pytest.mark.parametrize("profile", TRACE_PROFILES)
def test_core_reports_observed_selected_state_bounds(
    predictive_map: PredictiveMap, profile: str,
) -> None:
    workload = _build_workload(predictive_map, event_count=20, started_at=NOW,
                               occupants=2, trace_profile=profile)
    metrics, engine = _measure_core(predictive_map, workload)
    assert metrics["selected_slot_max"] == len(engine.snapshot.selected_paths) == 2
    assert 0 < metrics["selected_path_max"] <= 2
    assert 2 <= metrics["selected_route_max"] <= 4
    assert 2 <= metrics["selected_visit_max"] <= 4
    assert metrics["selected_source_max"] == len(engine.snapshot.selected_sources) == 17
    assert metrics["health_state_max"] == len(engine.snapshot.path_health) == 17
    assert metrics["health_cycle_max"] <= 6
    assert metrics["persistence_byte_stable"]


@pytest.mark.parametrize("name", sorted(SELECTED_ACQUISITION_PATHS))
@pytest.mark.parametrize("mutation", (
    "unchanged", "prior_on", "no_acquired", "refresh", "no_decision",
    "no_selected_movement", "duplicate", "wrong_target",
))
def test_each_current_fast_path_requires_real_acquisition(
    actual_fast_path_operations: dict[str, FastPathOperation], name: str, mutation: str,
) -> None:
    before, result, target_id, zone, at = actual_fast_path_operations[name]
    assert benchmark._fast_path_qualified(name, before, result, target_id, zone, at)
    if mutation == "prior_on":
        before = replace(before, policy_states=result.snapshot.policy_states)
    elif mutation == "no_acquired":
        result = replace(result, policy_events=())
    elif mutation == "refresh":
        result = replace(result, policy_events=tuple(
            replace(e, kind="refreshed") if e.zone == zone else e
            for e in result.policy_events
        ))
    elif mutation == "no_decision":
        result = replace(result, policy_decisions=())
    elif mutation == "no_selected_movement":
        result = replace(result, snapshot=replace(
            result.snapshot, selected_paths=before.selected_paths,
        ))
    elif mutation == "duplicate":
        result = replace(result, disposition="duplicate")
    elif mutation == "wrong_target":
        result = replace(result, policy_events=tuple(
            replace(e, zone="not_the_measured_zone") for e in result.policy_events
        ))
    assert benchmark._fast_path_qualified(
        name, before, result, target_id, zone, at,
    ) is (mutation == "unchanged")


@pytest.mark.parametrize("mutation", ("no_write", "off_write", "duplicate_write"))
def test_no_latency_sample_without_exact_matching_public_write(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    original = benchmark._BenchmarkBinarySensorEntity.async_write_ha_state
    if mutation == "off_write":
        types = benchmark._runtime_publication_types()
        monkeypatch.setattr(types[3], "is_on", property(lambda self: False))
        monkeypatch.setattr(benchmark, "_runtime_publication_types", lambda: types)
    else:
        def write(self: Any) -> None:
            if mutation == "duplicate_write":
                original(self)
                original(self)

        monkeypatch.setattr(benchmark._BenchmarkBinarySensorEntity,
                            "async_write_ha_state", write)
    paths = _measure_fast_paths(predictive_map, iterations=1)
    assert set(paths) == CURRENT_FAST_PATHS
    for name, trace in paths.items():
        if name in SELECTED_ACQUISITION_PATHS:
            assert trace["activation_count"] == trace["path_qualification_count"] == 1
        assert trace["sample_count"] == trace["publication_count"] == 0
        assert trace["max_ms"] is None and trace["p99_ms"] is None
        assert not trace["all_publications_scheduled"]
        assert not trace["p99_gate"] and not trace["hard_gate"]


def test_every_requested_sample_must_qualify(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original: FastPathPredicate = benchmark._fast_path_qualified
    seen = 0

    def reject_one(
        name: str, before: ZoneModelSnapshot, result: ZoneModelResult,
        target_id: str, zone: str, at: datetime,
        prediction: PredictionProof | None = None,
    ) -> bool:
        nonlocal seen
        qualified = _checked_boolean(
            original(name, before, result, target_id, zone, at, prediction),
        )
        if name == "same_zone":
            seen += 1
            return qualified and seen != 1
        return qualified

    monkeypatch.setattr(benchmark, "_fast_path_qualified", reject_one)
    trace = _measure_fast_paths(predictive_map, iterations=2)["same_zone"]
    assert trace["attempt_count"] == trace["activation_count"] == 2
    assert trace["publication_count"] == 2
    assert trace["sample_count"] == trace["path_qualification_count"] == 1
    assert not trace["all_path_qualified"]
    assert not trace["p99_gate"] and not trace["hard_gate"]


def test_mature_prediction_setup_rejects_unlearned_fixture(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.predictive_controls.markov import MarkovChain

    monkeypatch.setattr(MarkovChain, "observe", lambda *args, **kwargs: False)
    with pytest.raises(AssertionError):
        _measure_fast_paths(predictive_map, iterations=1)


@pytest.mark.parametrize("mutation", (
    "unchanged", "no_warning", "early_warning", "occupancy_degradation",
    "selection_changed", "public_state_changed", "wrong_frontier",
))
def test_count_conflict_replacement_is_diagnostic_health_deadline_only(
    mutation: str,
) -> None:
    model = benchmark._timer_health_map()
    engine = ZoneModelEngine(model, 2, NOW)
    initial = engine.snapshot
    for seconds, node in enumerate(("target", "a", "am", "as", "d", "dm", "ds")):
        engine.observe(SensorInput(f"binary_sensor.{node}", "on",
                                   NOW + timedelta(seconds=seconds)))
    deadline = NOW + timedelta(seconds=600)
    engine.advance(deadline - timedelta(microseconds=1))
    before = engine.snapshot
    assert not before.count_conflicts and not before.reliability_warning_occurrences
    assert all(p is not None for p in before.selected_paths)
    result = engine.advance(deadline)
    assert benchmark._health_deadline_qualified(before, result, deadline)
    if mutation == "no_warning":
        result = replace(result, snapshot=replace(
            result.snapshot, reliability_warning_occurrences=(),
        ))
    elif mutation == "early_warning":
        warning, = result.snapshot.reliability_warning_occurrences
        result = replace(result, snapshot=replace(
            result.snapshot, reliability_warning_occurrences=(replace(
                warning, first_observed_at=deadline - timedelta(microseconds=1),
            ),),
        ))
    elif mutation == "occupancy_degradation":
        result = replace(result, snapshot=replace(
            result.snapshot, episode_states=tuple(
                replace(e, health_warning=True, degradation_reason="count_conflict")
                if e.node_id == "target" else e for e in result.snapshot.episode_states
            ),
        ))
    elif mutation == "selection_changed":
        result = replace(result, snapshot=replace(
            result.snapshot, selected_paths=(None, None),
        ))
    elif mutation == "public_state_changed":
        result = replace(result, snapshot=replace(
            result.snapshot, policy_states=initial.policy_states,
        ))
    elif mutation == "wrong_frontier":
        result = replace(result, snapshot=replace(result.snapshot, updated_at=NOW))
    assert benchmark._health_deadline_qualified(
        before, result, deadline,
    ) is (mutation == "unchanged")


@pytest.fixture(scope="module")
def rejected_jump_measurement(
    predictive_map: PredictiveMap,
) -> MeasurementReports:
    return _checked_reports(
        benchmark._measure_rejected_jumps(predictive_map, iterations=2),
    )


def test_rejected_jump_is_complete_separate_diagnostic_workload(
    rejected_jump_measurement: MeasurementReports,
) -> None:
    assert ROUTINE_BENCHMARK_EVENTS == 100 and MAX_BENCHMARK_EVENTS == 1000
    assert set(rejected_jump_measurement) == {"rejected_jump"}
    trace = rejected_jump_measurement["rejected_jump"]
    assert trace["supersedes"] == "missed_edge"
    assert trace["occupants"] == 2
    assert trace["fixture_kind"] == "synthetic_observations"
    assert trace["registered_entity_count"] == 34
    assert trace["update_subscriber_count"] == 18
    assert trace["requested_count"] == trace["attempt_count"] == 2
    assert trace["sample_count"] == 2
    for key in ("prior_off", "remained_off", "rejection", "warning", "qualified",
                "selection_unchanged", "no_acquired", "fanout"):
        assert trace[f"{key}_count"] == 2
    assert trace["on_write_count"] == trace["acquired_event_count"] == 0
    assert trace["outcome"] == "rejected" and trace["failure_reasons"] == []
    gates = benchmark._negative_workload_gates(rejected_jump_measurement, 2)
    assert all(value for gate, value in gates.items() if not gate.endswith("latency"))
    latency = {key: _checked_number(trace[key]) for key in ("p99_ms", "max_ms")}
    assert all(math.isfinite(latency[key]) and latency[key] >= 0
               for key in ("p99_ms", "max_ms"))


@pytest.mark.parametrize("iterations", (0, MAX_BENCHMARK_EVENTS + 1))
def test_rejected_jump_benchmark_enforces_iteration_bounds(
    predictive_map: PredictiveMap, iterations: int,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        benchmark._measure_rejected_jumps(predictive_map, iterations=iterations)


@pytest.mark.parametrize("mutation", (
    "unchanged", "no_warning", "wrong_warning", "cleared_warning", "early_warning",
    "no_authorization", "authorized", "wrong_target", "wrong_outcome", "no_decision",
    "prior_on", "target_on", "acquired", "selection_changed", "on_write",
))
def test_rejected_jump_qualifies_actual_result_not_just_silence(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    original: RejectionChecks = benchmark._rejected_jump_checks

    def mutate(
        before: ZoneModelSnapshot, result: ZoneModelResult,
        target_id: str, zone: str, at: datetime,
    ) -> dict[str, bool]:
        assert all(original(before, result, target_id, zone, at).values())
        if mutation in {
            "no_warning", "wrong_warning", "cleared_warning", "early_warning",
        }:
            warning, = result.snapshot.reliability_warning_occurrences
            warnings = () if mutation == "no_warning" else (replace(
                warning,
                reason="assertion_timeout"
                if mutation == "wrong_warning" else warning.reason,
                kind="suspected_stuck" if mutation == "wrong_warning" else warning.kind,
                cleared_at=at if mutation == "cleared_warning" else None,
                first_observed_at=at - timedelta(microseconds=1)
                if mutation == "early_warning" else at,
            ),)
            result = replace(result, snapshot=replace(
                result.snapshot, reliability_warning_occurrences=warnings,
            ))
        elif mutation == "no_authorization":
            result = replace(result, authorizations=())
        elif mutation in {"authorized", "wrong_target"}:
            result = replace(result, authorizations=(replace(
                result.authorizations[0], authorized=mutation == "authorized",
                reason="boundary_authorized" if mutation == "authorized"
                else result.authorizations[0].reason,
                track_confidence="provisional" if mutation == "authorized" else None,
                provenance_kind="boundary" if mutation == "authorized" else None,
                path_node_ids=(target_id,) if mutation == "authorized" else (),
                target_node_id="dining_sensor"
                if mutation == "wrong_target" else target_id,
            ),))
        elif mutation == "wrong_outcome":
            result = replace(result, disposition="duplicate")
        elif mutation == "no_decision":
            result = replace(result, policy_decisions=())
        elif mutation in {"prior_on", "target_on"}:
            snapshot = before if mutation == "prior_on" else result.snapshot
            active = next(p for p in snapshot.policy_states if p.active)
            snapshot = replace(snapshot, policy_states=tuple(
                replace(active, zone=zone) if p.zone == zone else p
                for p in snapshot.policy_states
            ))
            if mutation == "prior_on":
                before = snapshot
            else:
                result = replace(result, snapshot=snapshot)
        elif mutation == "acquired":
            from custom_components.predictive_controls.zone_model.types import (
                PolicyEvent,
            )

            result = replace(result, policy_events=(PolicyEvent(
                kind="acquired", event_at=at, zone=zone, episode_id="mutated",
                belief=1.0, authorization_reason="selected_path",
                policy_reason="acquired",
            ),))
        elif mutation == "selection_changed":
            result = replace(result, snapshot=replace(
                result.snapshot, selected_paths=(None, None),
            ))
        return _checked_flags(original(before, result, target_id, zone, at))

    monkeypatch.setattr(benchmark, "_rejected_jump_checks", mutate)
    if mutation == "on_write":
        types = benchmark._runtime_publication_types()
        original_is_on = types[3].is_on.fget
        original_write = benchmark._BenchmarkBinarySensorEntity.async_write_ha_state

        def is_on(self: Any) -> bool:
            return bool(getattr(self, "_benchmark_during_write", False)
                        or original_is_on(self))

        def write(self: Any) -> None:
            self._benchmark_during_write = True
            try:
                original_write(self)
            finally:
                self._benchmark_during_write = False

        monkeypatch.setattr(types[3], "is_on", property(is_on))
        monkeypatch.setattr(benchmark._BenchmarkBinarySensorEntity,
                            "async_write_ha_state", write)
        monkeypatch.setattr(benchmark, "_runtime_publication_types", lambda: types)
    measurements = benchmark._measure_rejected_jumps(predictive_map, iterations=1)
    gates = benchmark._negative_workload_gates(measurements, 1)
    trace = measurements["rejected_jump"]
    # Failed correctness never hides a returned sample.
    assert gates["samples_complete"]
    assert gates["correctness"] is (mutation == "unchanged")
    assert (trace["outcome"] == "rejected") is (mutation == "unchanged")


@pytest.mark.parametrize("mutation", (
    "unchanged", "missing_workload", "renamed_workload", "partial_samples",
    "partial_attempts", "missing_warning", "wrong_outcome", "on_write", "acquired",
    "prior_on", "target_on", "missing_rejection", "p99_over", "hard_equal",
    "missing_latency", "nonfinite_latency",
))
def test_negative_workload_gates_top_level_and_cli(
    rejected_jump_measurement: MeasurementReports,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    # Isolate the new gate from unrelated positive-path failures/wall-time jitter;
    # these are explicitly component report mutations, not live ON qualification.
    workloads = deepcopy(rejected_jump_measurement)
    trace = workloads["rejected_jump"]
    trace.update(p99_ms=FAST_PATH_P99_MS, max_ms=FAST_PATH_HARD_MS - 0.001)
    if mutation == "missing_workload":
        workloads.clear()
    elif mutation == "renamed_workload":
        workloads["not_rejected_jump"] = workloads.pop("rejected_jump")
    else:
        changes: dict[str, tuple[str, object]] = {
            "partial_samples": ("sample_count", 1),
            "partial_attempts": ("attempt_count", 1),
            "missing_warning": ("warning_count", 1),
            "wrong_outcome": ("outcome", "acquired"),
            "on_write": ("on_write_count", 1),
            "acquired": ("acquired_event_count", 1),
            "prior_on": ("prior_off_count", 1),
            "target_on": ("remained_off_count", 1),
            "missing_rejection": ("rejection_count", 1),
            "p99_over": ("p99_ms", FAST_PATH_P99_MS + 0.001),
            "hard_equal": ("max_ms", FAST_PATH_HARD_MS),
            "missing_latency": ("p99_ms", None),
            "nonfinite_latency": ("max_ms", float("inf")),
        }
        if mutation in changes:
            key, value = changes[mutation]
            trace[key] = value
    _stub_complete_reports(monkeypatch, 2)
    monkeypatch.setattr(benchmark, "_measure_rejected_jumps", lambda *a, **k: workloads)
    report = run_benchmark(MAP_PATH, event_count=2)
    assert report["passed"] is (mutation == "unchanged")
    assert report["negative_workloads"] == workloads
    assert all(report["negative_gates"].values()) is (mutation == "unchanged")
    output = tmp_path / "negative-report.json"
    monkeypatch.setattr("sys.argv", [
        "benchmark", "--events", "2", "--output", str(output),
    ])
    if mutation == "unchanged":
        main()
    else:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == (2 if mutation == "nonfinite_latency" else 1)
    captured = capsys.readouterr()
    if mutation == "nonfinite_latency":
        # Nonfinite report values additionally fail strict JSON serialization.
        assert not output.exists() and captured.out == ""
        assert json.loads(captured.err)["passed"] is False
        return
    rendered = output.read_text()
    assert captured.out == ""
    assert captured.err == ("" if mutation == "unchanged" else rendered)
    assert json.loads(rendered)["passed"] is (mutation == "unchanged")


def test_rejected_jump_times_complete_dispatch_with_fresh_prepared_runtime(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch,
) -> None:
    types = benchmark._runtime_publication_types()
    observe = types[0].observe_entity
    qualify: RejectionChecks = benchmark._rejected_jump_checks
    order: list[str] = []
    runtimes: list[Any] = []
    times = iter((1_000_000, 3_000_000, 5_000_000, 8_000_000))
    target = next(iter(predictive_map.nodes["gym_sensor"].entities.values()))

    def clock() -> int:
        order.append("clock")
        return next(times)

    def dispatch(self: Any, entity: str, *args: Any, **kwargs: Any) -> None:
        if entity != target:
            observe(self, entity, *args, **kwargs)
            return
        assert all(self is not previous for previous in runtimes)
        runtimes.append(self)
        assert len(self.map.nodes) == 17 and len(self.map.zones()) == 16
        order.append("dispatch")
        observe(self, entity, *args, **kwargs)
        assert self.confidence._last_result.snapshot.reliability_warning_occurrences
        order.append("returned")

    def checked(
        before: ZoneModelSnapshot, result: ZoneModelResult,
        target_id: str, zone: str, at: datetime,
    ) -> dict[str, bool]:
        order.append("qualified")
        return _checked_flags(qualify(before, result, target_id, zone, at))

    monkeypatch.setattr(types[0], "observe_entity", dispatch)
    monkeypatch.setattr(benchmark, "_runtime_publication_types", lambda: types)
    monkeypatch.setattr(benchmark, "perf_counter_ns", clock)
    monkeypatch.setattr(benchmark, "_rejected_jump_checks", checked)
    measurements = benchmark._measure_rejected_jumps(predictive_map, iterations=2)
    assert len(runtimes) == 2
    assert order == ["clock", "dispatch", "returned", "clock", "qualified"] * 2
    assert measurements["rejected_jump"]["max_ms"] == 3.0
    assert measurements["rejected_jump"]["p99_ms"] == benchmark._percentile(
        [2.0, 3.0], 0.99,
    )
    assert all(benchmark._negative_workload_gates(measurements, 2).values())


@pytest.fixture(scope="module")
def semantic_captures(predictive_map: PredictiveMap) -> dict[str, dict[str, Any]]:
    return {
        profile: {
            "schema_version": 1,
            "trace_profile": profile,
            "metadata": {"map_fingerprint": target_map_fingerprint(predictive_map)},
            "counts": {
                "2": _capture_workload(
                    predictive_map,
                    _build_workload(
                        predictive_map,
                        event_count=20,
                        started_at=NOW,
                        occupants=2,
                        trace_profile=profile,
                    ),
                ),
            },
        }
        for profile in TRACE_PROFILES
    }


def test_semantic_fixture_covers_exactly_all_five_profiles(
    semantic_captures: dict[str, dict[str, Any]],
) -> None:
    assert set(semantic_captures) == set(TRACE_PROFILES)
    assert len(semantic_captures) == 5


@pytest.mark.parametrize("profile", TRACE_PROFILES)
def test_semantic_selected_only_capture_keeps_pending_learning_empty(
    semantic_captures: dict[str, dict[str, Any]], profile: str,
) -> None:
    """Integration control: real selected authorizations never queue learning."""

    capture = semantic_captures[profile]
    rows = capture["counts"]["2"]["events"]
    assert len(rows) == capture["counts"]["2"]["event_count"] == 20
    assert all(row["diagnostics"]["pending_prediction_learning"] == [] for row in rows)
    authorized = [
        item for row in rows for item in row["result"]["authorizations"]
        if item["authorized"]
    ]
    assert authorized
    assert {item["reason"] for item in authorized} == {"selected_path"}
    assert {item["provenance_kind"] for item in authorized} == {"selected_path"}
    assert compare_semantic(capture, capture)["passed"]


@pytest.mark.parametrize("profile", TRACE_PROFILES)
def test_semantic_repeat_is_byte_equal_and_captures_every_result_field(
    predictive_map: PredictiveMap,
    semantic_captures: dict[str, dict[str, Any]],
    profile: str,
) -> None:
    before = semantic_captures[profile]
    workload = _build_workload(
        predictive_map, event_count=20, started_at=NOW, occupants=2,
        trace_profile=profile,
    )
    repeated = {**before, "counts": {"2": _capture_workload(predictive_map, workload)}}
    assert _render_json(before).encode() == _render_json(repeated).encode()
    assert compare_semantic(before, repeated)["passed"]
    captured = before["counts"]["2"]
    assert captured["started_at"] == NOW.isoformat()
    assert captured["bootstrap_at"] == workload.bootstrap_at.isoformat()
    assert captured["passed"]
    engine = ZoneModelEngine(predictive_map, 2, workload.bootstrap_at)
    for event, received_at, row in zip(
        workload.events, workload.receive_at, captured["events"], strict=True
    ):
        assert row["event"] == _semantic_value(event)
        assert row["received_at"] == received_at.isoformat()
        actual = engine.observe(event, processing_at=received_at)
        assert row["result"] == _semantic_value(actual)
        assert set(row["result"]) == {field.name for field in fields(ZoneModelResult)}
        assert set(row["result"]["snapshot"]) == {
            field.name for field in fields(ZoneModelSnapshot)
        }
        persisted = serialize_target_state(predictive_map, engine)
        assert persisted.pop("map_fingerprint") == before["metadata"]["map_fingerprint"]
        assert row["state"] == persisted
        assert row["state"]["snapshot"] == row["result"]["snapshot"]
        assert row["state"]["prediction"] == engine.prediction_manager.serialize()
        assert row["diagnostics"] == {
            "counters": engine.diagnostic_counters,
            "latest_support_transition": _semantic_value(
                engine.latest_support_transition
            ),
            "pending_prediction_learning": _semantic_value(
                engine._pending_prediction_learning
            ),
        }
        assert row["restore"] == {
            "continuation_differences": [], "state_differences": [], "passed": True,
        }


def test_semantic_public_event_mutation_fails_at_exact_event_path(
    semantic_captures: dict[str, dict[str, Any]],
) -> None:
    before = semantic_captures["deterministic"]
    after = deepcopy(before)
    index = next(
        index for index, row in enumerate(after["counts"]["2"]["events"])
        if row["result"]["policy_events"]
    )
    event = after["counts"]["2"]["events"][index]["result"]["policy_events"][0]
    original = event["kind"]
    event["kind"] = "deliberately_mutated_public_event"
    result = compare_semantic(before, after)
    assert result["passed"] is False
    assert result["differences"] == [{
        "path": f"/counts/2/events/{index}/result/policy_events/0/kind",
        "before": original, "after": "deliberately_mutated_public_event",
    }]
    assert result["fingerprints_equal"]


def test_semantic_fingerprint_is_separate_and_inputs_are_not_mutated(
    semantic_captures: dict[str, dict[str, Any]],
) -> None:
    before = semantic_captures["deterministic"]
    frozen = _render_json(before)
    after = deepcopy(before)
    after["metadata"]["map_fingerprint"] = "planned-new-fingerprint"
    result = compare_semantic(before, after)
    assert result["passed"] and result["differences"] == []
    assert result["fingerprints_equal"] is False
    assert result["fingerprints"]["after"] == "planned-new-fingerprint"
    assert _render_json(before) == frozen
    assert after["metadata"]["map_fingerprint"] == "planned-new-fingerprint"
    after["metadata"]["other_meaningful_metadata"] = "not exempt"
    assert compare_semantic(before, after)["passed"] is False


@pytest.fixture(params=(
    ("result", "authorizations"),
    ("diagnostics", "pending_prediction_learning"),
))
def authorization_location(request: pytest.FixtureRequest) -> tuple[str, str]:
    parent, array = request.param
    return parent, array


@pytest.fixture
def authorization_capture(
    semantic_captures: dict[str, dict[str, Any]],
    authorization_location: tuple[str, str],
) -> dict[str, Any]:
    """COMPONENT document, not evidence of runtime authorization or learning.

    Reuse one complete capture envelope, but explicitly populate both comparator
    locations with a representative confirmed authorization. Validate its types
    before the tests deliberately create malformed operands; those mutations
    exercise comparison, not production authorization decoding or restoration.
    """

    from custom_components.predictive_controls.zone_model.types import (
        AuthorizationUse,
        TraversalToken,
    )

    capture = semantic_captures["deterministic"]
    workload = capture["counts"]["2"]
    component = deepcopy({
        **capture,
        "metadata": {**capture["metadata"], "fixture_kind": "COMPONENT"},
        "counts": {"2": {
            **workload, "event_count": 1, "events": workload["events"][:1],
        }},
    })
    row = component["counts"]["2"]["events"][0]
    at = datetime.fromisoformat(row["event"]["event_at"])
    target_episode_id = f"component_target:1:{at.isoformat()}"
    source = TraversalToken(
        token_id="token:component_source",
        node_id="component_source",
        zone="component_source_zone",
        role="transition",
        profile_name="transition_fast",
        episode_id=f"component_source:1:{NOW.isoformat()}",
        accepted_at=NOW,
        valid_until=NOW + timedelta(seconds=180),
        track_confidence="confirmed",
        path_node_ids=("component_origin", "component_middle", "component_source"),
        provenance_kind="adjacent",
        equivalent_confirmed_strength=False,
        continuity_reopened_at=None,
    )
    authorization = _semantic_value(TraversalAuthorization(
        target_node_id="component_target",
        target_zone="component_target_zone",
        target_episode_id=target_episode_id,
        authorized_at=at,
        authorized=True,
        reason="adjacent_authorized",
        source_tokens=(source,),
        new_uses=(AuthorizationUse(
            token_id=source.token_id,
            target_episode_id=target_episode_id,
            reason="adjacent_authorized",
            authorized_at=at,
        ),),
        track_confidence="confirmed",
        path_node_ids=("component_middle", "component_source", "component_target"),
        provenance_kind="adjacent",
        equivalent_confirmed_strength=False,
        settled_handoff=None,
        selected_source_episode_ids=(),
    ))
    row["result"]["authorizations"] = [deepcopy(authorization)]
    row["diagnostics"]["pending_prediction_learning"] = [deepcopy(authorization)]
    parent, array = authorization_location
    assert set(row[parent][array][0]) == {
        field.name for field in fields(TraversalAuthorization)
    }
    assert source.accepted_at < at < source.valid_until
    assert compare_semantic(component, deepcopy(component))["passed"]
    return component


@pytest.mark.parametrize("reverse", (False, True))
def test_semantic_optional_handoff_absent_null_is_symmetric_and_copy_only(
    authorization_capture: dict[str, Any], reverse: bool,
    authorization_location: tuple[str, str],
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    before["counts"]["2"]["events"][0][parent][array][0].pop(
        "settled_handoff", None,
    )
    after = deepcopy(before)
    after["counts"]["2"]["events"][0][parent][array][0][
        "settled_handoff"
    ] = None
    assert _semantic_differences(before, after) == [{
        "path": f"/counts/2/events/0/{parent}/{array}/0/settled_handoff",
        "before_present": False, "after_present": True,
        "before": None, "after": None,
    }]
    after["metadata"]["map_fingerprint"] = "changed-fingerprint"
    if reverse:
        before, after = after, before
    frozen = (_render_json(before), _render_json(after))
    report = compare_semantic(before, after)
    assert report["passed"] and report["differences"] == []
    assert not report["fingerprints_equal"]
    assert report["fingerprints"] == {
        "before": before["metadata"]["map_fingerprint"],
        "after": after["metadata"]["map_fingerprint"],
    }
    assert report["normalization_rules"] == [
        "ABSENT equals explicit null only at "
        "/counts/{count}/events/{event_index}/result/authorizations/"
        "{authorization_index}/settled_handoff and "
        "/counts/{count}/events/{event_index}/diagnostics/"
        "pending_prediction_learning/{authorization_index}/settled_handoff "
        "on paired authorization "
        "objects in arrays; nonnull values and all other fields remain exact."
    ]
    assert (_render_json(before), _render_json(after)) == frozen


@pytest.mark.parametrize("original", ("absent", "null", "nonnull"))
@pytest.mark.parametrize(
    "payload", ({"source_updated_at": "changed"}, {}, [], 0, False, ""),
)
def test_semantic_nonnull_handoff_mutations_remain_lossless_in_both_directions(
    authorization_capture: dict[str, Any], original: str, payload: Any,
    authorization_location: tuple[str, str],
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    authorization = before["counts"]["2"]["events"][0][parent][array][0]
    authorization.pop("settled_handoff", None)
    if original != "absent":
        authorization["settled_handoff"] = (
            None if original == "null" else {"source_updated_at": NOW.isoformat()}
        )
    after = deepcopy(before)
    after["counts"]["2"]["events"][0][parent][array][0][
        "settled_handoff"
    ] = payload
    for left, right in ((before, after), (after, before)):
        report = compare_semantic(left, right)
        assert not report["passed"]
        assert report["fingerprints_equal"]
        assert report["differences"] == _semantic_differences(left, right)


@pytest.mark.parametrize("location", (
    "root", "metadata", "initial_state", "event", "diagnostics", "state",
    "result", "snapshot", "authorization", "handoff_payload",
))
@pytest.mark.parametrize("field", ("settled_handoff", "unknown", "reason"))
@pytest.mark.parametrize("lookalike", (
    "authorizations", "pending_prediction_learning",
))
def test_semantic_unrelated_missing_null_and_nested_lookalikes_are_not_normalized(
    authorization_capture: dict[str, Any], location: str, field: str,
    authorization_location: tuple[str, str], lookalike: str,
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    workload = before["counts"]["2"]
    row = workload["events"][0]
    authorization = row[parent][array][0]
    authorization["settled_handoff"] = {"support_id": "retained-support"}
    containers = {
        "root": before, "metadata": before["metadata"],
        "initial_state": workload["initial_state"], "event": row,
        "diagnostics": row["diagnostics"], "state": row["state"],
        "result": row["result"], "snapshot": row["result"]["snapshot"],
        "authorization": authorization,
        "handoff_payload": authorization["settled_handoff"],
    }
    # An unknown subtree must not gain special treatment just because it has
    # authorization-shaped children, even inside a real authorization/payload.
    containers[location]["lookalike"] = {lookalike: [{}]}
    after = deepcopy(before)
    containers[location]["lookalike"][lookalike][0][field] = None
    for left, right in ((before, after), (after, before)):
        report = compare_semantic(left, right)
        assert not report["passed"]
        assert report["differences"] == _semantic_differences(left, right)


@pytest.mark.parametrize(("old", "new"), (
    ({"0": {}}, {"0": {"settled_handoff": None}}),
    ({}, []),
    (None, []),
    (False, []),
    (0, []),
    ("", []),
    ([None], [{"settled_handoff": None}]),
    ([[]], [{"settled_handoff": None}]),
    ([False], [{"settled_handoff": None}]),
    ([0], [{"settled_handoff": None}]),
    ([""], [{"settled_handoff": None}]),
    ([], [{"settled_handoff": None}]),
    ([{}], [{"unknown": None}]),
    ([{}], [{"reason": None}]),
))
def test_semantic_authorization_shape_and_other_direct_fields_remain_exact(
    authorization_capture: dict[str, Any], old: Any, new: Any,
    authorization_location: tuple[str, str],
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    after = deepcopy(before)
    before["counts"]["2"]["events"][0][parent][array] = old
    after["counts"]["2"]["events"][0][parent][array] = new
    for left, right in ((before, after), (after, before)):
        report = compare_semantic(left, right)
        assert not report["passed"]
        assert report["differences"] == _semantic_differences(left, right)


@pytest.mark.parametrize("representation", ("absent", "null", "nonnull"))
def test_semantic_equal_handoff_representations_stay_equal(
    authorization_capture: dict[str, Any],
    authorization_location: tuple[str, str], representation: str,
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    item = before["counts"]["2"]["events"][0][parent][array][0]
    item.pop("settled_handoff", None)
    if representation != "absent":
        item["settled_handoff"] = (
            None if representation == "null" else {"support_id": "retained"}
        )
    after = deepcopy(before)
    frozen = _render_json(before)
    assert compare_semantic(before, after)["passed"]
    assert _render_json(before) == _render_json(after) == frozen


@pytest.mark.parametrize("field", tuple(
    field.name for field in fields(TraversalAuthorization)
    if field.name != "settled_handoff"
))
def test_semantic_every_authorization_field_survives_handoff_normalization(
    authorization_capture: dict[str, Any],
    authorization_location: tuple[str, str], field: str,
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    item = before["counts"]["2"]["events"][0][parent][array][0]
    item.pop("settled_handoff", None)
    after = deepcopy(before)
    changed = after["counts"]["2"]["events"][0][parent][array][0]
    changed[field] = {"semantic_mutation": item[field]}
    expected = (
        _semantic_differences(before, after), _semantic_differences(after, before),
    )
    changed["settled_handoff"] = None
    for (left, right), differences in zip(
        ((before, after), (after, before)), expected, strict=True,
    ):
        report = compare_semantic(left, right)
        assert not report["passed"]
        assert report["differences"] == differences


@pytest.mark.parametrize("mutation", ("append", "reorder"))
def test_semantic_authorization_cardinality_and_order_remain_exact(
    authorization_capture: dict[str, Any],
    authorization_location: tuple[str, str], mutation: str,
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    items = before["counts"]["2"]["events"][0][parent][array]
    first = deepcopy(items[0])
    first.pop("settled_handoff", None)
    second = {**first, "target_episode_id": "distinct-episode"}
    items[:] = [first, second]
    after = deepcopy(before)
    changed = after["counts"]["2"]["events"][0][parent][array]
    if mutation == "append":
        changed.append({"settled_handoff": None})
    else:
        changed.reverse()
    expected = (
        _semantic_differences(before, after), _semantic_differences(after, before),
    )
    for item in changed[:2]:
        item["settled_handoff"] = None
    for (left, right), differences in zip(
        ((before, after), (after, before)), expected, strict=True,
    ):
        report = compare_semantic(left, right)
        assert not report["passed"]
        assert report["differences"] == differences


@pytest.mark.parametrize("value", (None, [], [{"settled_handoff": None}]))
def test_semantic_authorization_array_presence_is_not_normalized(
    authorization_capture: dict[str, Any],
    authorization_location: tuple[str, str], value: Any,
) -> None:
    parent, array = authorization_location
    before = authorization_capture
    del before["counts"]["2"]["events"][0][parent][array]
    after = deepcopy(before)
    after["counts"]["2"]["events"][0][parent][array] = value
    for left, right in ((before, after), (after, before)):
        if parent == "result":
            with pytest.raises(ValueError, match="Invalid semantic event result"):
                compare_semantic(left, right)
        else:
            report = compare_semantic(left, right)
            assert not report["passed"]
            assert report["differences"] == _semantic_differences(left, right)


@pytest.mark.parametrize("value", (None, [], False, 0, ""))
def test_semantic_malformed_authorization_parent_is_not_normalized(
    authorization_capture: dict[str, Any],
    authorization_location: tuple[str, str], value: Any,
) -> None:
    parent, _ = authorization_location
    before = authorization_capture
    after = deepcopy(before)
    after["counts"]["2"]["events"][0][parent] = value
    for left, right in ((before, after), (after, before)):
        if parent == "result":
            with pytest.raises(ValueError, match="Invalid semantic event result"):
                compare_semantic(left, right)
        else:
            report = compare_semantic(left, right)
            assert not report["passed"]
            assert report["differences"] == _semantic_differences(left, right)


@pytest.mark.parametrize("mutation", ("profile", "count", "receipt", "prediction"))
def test_semantic_profile_count_receipt_and_prediction_mismatches_fail(
    semantic_captures: dict[str, dict[str, Any]], mutation: str,
) -> None:
    before = semantic_captures["deterministic"]
    after = deepcopy(before)
    if mutation == "profile":
        after["trace_profile"] = "maximum_lag"
    elif mutation == "count":
        after["counts"]["1"] = deepcopy(after["counts"]["2"])
        after["counts"]["1"]["occupants"] = 1
    elif mutation == "receipt":
        after["counts"]["2"]["events"][0]["received_at"] = NOW.isoformat()
    else:
        after["counts"]["2"]["events"][0]["state"]["prediction"]["counts"] = {
            "unexpected": {"route": 1.0},
        }
    result = compare_semantic(before, after)
    assert not result["passed"]
    assert result["differences"]


@pytest.mark.parametrize(
    ("before", "after", "path"),
    [
        ({"a/b~": None}, {}, "/a~1b~0"),
        ({}, {"x": None}, "/x"),
        ([1], [1, None], "/1"),
        ([1, None], [1], "/1"),
        (True, 1, ""),
        (1, 1.0, ""),
        ([], {}, ""),
        ("old", "new", ""),
    ],
)
def test_semantic_diff_preserves_types_presence_and_pointer_escaping(
    before: Any, after: Any, path: str,
) -> None:
    differences = _semantic_differences(before, after)
    assert len(differences) == 1
    assert differences[0]["path"] == path
    assert _semantic_differences(after, before)
    assert _semantic_differences(before, before) == []


@pytest.mark.parametrize("value", (object(), float("nan"), float("inf"), {1: "x"}))
def test_semantic_encoding_rejects_lossy_values(value: Any) -> None:
    with pytest.raises(TypeError):
        _semantic_value(value)


def test_semantic_encoding_preserves_time_and_policy_duration() -> None:
    assert _semantic_value(NOW) == NOW.isoformat()
    assert _semantic_value(timedelta(seconds=120)) == 120.0
    with pytest.raises(ValueError, match="aware UTC"):
        _semantic_value(NOW.replace(tzinfo=None))


@pytest.mark.parametrize("mutation", (
    "root", "schema", "profile", "metadata", "fingerprint", "empty_fingerprint",
    "counts", "workload", "occupants", "event_count", "event_bound", "events",
    "length", "initial_state", "row", "receipt", "result", "disposition",
))
def test_semantic_malformed_artifacts_fail_closed(
    semantic_captures: dict[str, dict[str, Any]], mutation: str,
) -> None:
    payload: Any = deepcopy(semantic_captures["deterministic"])
    workload = payload["counts"]["2"]
    row = workload["events"][0]
    if mutation == "root":
        payload = []
    elif mutation == "schema":
        payload["schema_version"] = True
    elif mutation == "profile":
        del payload["trace_profile"]
    elif mutation == "metadata":
        payload["metadata"] = []
    elif mutation == "fingerprint":
        payload["metadata"]["map_fingerprint"] = None
    elif mutation == "empty_fingerprint":
        payload["metadata"]["map_fingerprint"] = ""
    elif mutation == "counts":
        payload["counts"] = {}
    elif mutation == "workload":
        payload["counts"]["2"] = []
    elif mutation == "occupants":
        workload["occupants"] = 1
    elif mutation == "event_count":
        workload["event_count"] = False
    elif mutation == "event_bound":
        workload["event_count"] = 1001
    elif mutation == "events":
        workload["events"] = {}
    elif mutation == "length":
        workload["events"].pop()
    elif mutation == "initial_state":
        del workload["initial_state"]
    elif mutation == "row":
        workload["events"][0] = None
    elif mutation == "receipt":
        del row["received_at"]
    elif mutation == "result":
        row["result"] = []
    else:
        del row["result"]["disposition"]
    with pytest.raises(ValueError, match="Invalid semantic"):
        compare_semantic(payload, payload)


def test_identical_failed_restore_artifacts_do_not_pass_comparison(
    semantic_captures: dict[str, dict[str, Any]],
) -> None:
    good = semantic_captures["deterministic"]
    failed = deepcopy(good)
    failed["counts"]["2"]["passed"] = False
    assert compare_semantic(failed, failed)["passed"] is False
    assert compare_semantic(good, failed)["passed"] is False


def test_semantic_empty_workload_uses_deterministic_timed_bootstrap(
    predictive_map: PredictiveMap,
) -> None:
    workload = _build_workload(
        predictive_map, event_count=0, started_at=NOW, occupants=2,
        trace_profile="deterministic",
    )
    core, engine = _measure_core(predictive_map, workload)
    captured = _capture_workload(predictive_map, workload)
    assert core["event_count"] == 0
    assert captured["bootstrap_at"] == engine.snapshot.updated_at.isoformat()
    assert engine.snapshot.updated_at == NOW
    assert captured["events"] == [] and captured["passed"]
    assert captured == _capture_workload(predictive_map, workload)


def test_semantic_restore_mismatch_is_retained(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = restore_target_state

    def changed_restore(*args: Any, **kwargs: Any) -> ZoneModelEngine:
        engine = original(*args, **kwargs)
        observe = engine.observe

        def changed_observe(*args: Any, **kwargs: Any) -> ZoneModelResult:
            return replace(observe(*args, **kwargs), disposition="changed-by-restore")

        monkeypatch.setattr(engine, "observe", changed_observe)
        return engine

    monkeypatch.setattr(benchmark, "restore_target_state", changed_restore)
    workload = _build_workload(
        predictive_map, event_count=1, started_at=NOW, occupants=2,
        trace_profile="deterministic",
    )
    captured = _capture_workload(predictive_map, workload)
    assert captured["passed"] is False
    restore = captured["events"][0]["restore"]
    assert restore["continuation_differences"][0]["path"] == "/result/disposition"
    assert restore["state_differences"] == []


def test_capture_occurs_after_all_timed_work_and_uses_same_workload_objects(
    predictive_map: PredictiveMap, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[str] = []
    measured: list[Any] = []
    original_measure = benchmark._measure_core
    original_capture = benchmark._capture_workload

    def measure(model: PredictiveMap, workload: Any) -> Any:
        calls.append("measure")
        measured.append(workload)
        return original_measure(model, workload)

    def capture(model: PredictiveMap, workload: Any) -> Any:
        calls.append("capture")
        assert workload is measured.pop(0)
        return original_capture(model, workload)

    _stub_complete_reports(monkeypatch, 2)
    monkeypatch.setattr(benchmark, "_measure_core", measure)
    monkeypatch.setattr(benchmark, "_capture_workload", capture)
    path = tmp_path / "semantic.json"
    result = run_benchmark(
        MAP_PATH, event_count=2, target_counts=(1, 2), semantic_output=path,
    )
    assert result["passed"]
    assert calls == ["measure", "measure", "capture", "capture"]
    semantic = json.loads(path.read_text())
    assert set(semantic["counts"]) == {"1", "2"}
    assert "fast_paths" not in semantic and "counts" in result


@pytest.mark.parametrize("events", (-1, 1001))
def test_all_benchmark_entry_bounds(events: int, predictive_map: PredictiveMap) -> None:
    with pytest.raises(ValueError, match="must not exceed 1000"):
        _build_workload(
            predictive_map, event_count=events, started_at=NOW, occupants=2,
            trace_profile="deterministic",
        )
    with pytest.raises(ValueError, match="must not exceed 1000"):
        run_benchmark(MAP_PATH, event_count=events)


def test_workload_rejects_unknown_profile_and_empty_map(
    predictive_map: PredictiveMap,
) -> None:
    with pytest.raises(ValueError, match="Unknown trace profile"):
        _build_workload(
            predictive_map, event_count=1, started_at=NOW, occupants=2,
            trace_profile="missing",
        )
    with pytest.raises(ValueError, match="Unknown trace profile"):
        run_benchmark(MAP_PATH, trace_profile="missing")
    with pytest.raises(ValueError, match="no sensor bindings"):
        _build_workload(
            replace(predictive_map, nodes={}), event_count=1,
            started_at=NOW, occupants=2, trace_profile="deterministic",
        )
    for counts in ((), (2, 2)):
        with pytest.raises(ValueError, match="distinct occupant counts"):
            run_benchmark(MAP_PATH, target_counts=counts)


@pytest.mark.parametrize("passed", (True, False))
@pytest.mark.parametrize("file_output", (True, False))
def test_benchmark_cli_preserves_complete_report_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], passed: bool, file_output: bool,
) -> None:
    result = {"passed": passed, "complete": {"evidence": [1, 2]}}
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *a, **k: result)
    output = tmp_path / "aggregate.json"
    args = ["benchmark", *(["--output", str(output)] if file_output else [])]
    monkeypatch.setattr("sys.argv", args)
    if passed:
        main()
    else:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    captured = capsys.readouterr()
    rendered = _render_json(result)
    assert captured.out == ("" if file_output else rendered)
    assert captured.err == (rendered if file_output and not passed else "")
    if file_output:
        assert output.read_text() == rendered


@pytest.mark.parametrize("mismatch", (False, True))
@pytest.mark.parametrize("file_output", (False, True))
def test_compare_cli_status_and_report_contract(
    semantic_captures: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    mismatch: bool, file_output: bool,
) -> None:
    before = semantic_captures["deterministic"]
    after = deepcopy(before)
    if mismatch:
        after["counts"]["2"]["events"][0]["result"]["policy_events"].append(
            {"kind": "deliberate-public-mutation"}
        )
    paths = [tmp_path / name for name in ("before.json", "after.json", "diff.json")]
    for path, payload in zip(paths[:2], (before, after), strict=True):
        path.write_text(_render_json(payload))
    monkeypatch.setattr("sys.argv", [
        "benchmark", "--compare-semantic", str(paths[0]), str(paths[1]),
        *(["--output", str(paths[2])] if file_output else []),
    ])
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *a, **k: pytest.fail(
        "Comparison must not run a benchmark"
    ))
    if mismatch:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    else:
        main()
    captured = capsys.readouterr()
    report = paths[2].read_text() if file_output else captured.out
    assert json.loads(report)["passed"] is not mismatch
    assert captured.out == ("" if file_output else report)
    assert captured.err == (report if mismatch and file_output else "")


@pytest.mark.parametrize("failure", (
    "missing_input", "malformed_json", "invalid_utf8", "invalid_capture",
    "missing_profile", "same_outputs", "overwrite_input", "capture_and_compare",
    "write_report", "write_semantic", "too_many_events", "negative_events",
))
def test_cli_io_and_validation_errors_are_stderr_only(
    semantic_captures: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    before = tmp_path / "before.json"
    before.write_text(_render_json(semantic_captures["deterministic"]))
    broken = tmp_path / "broken.json"
    output = tmp_path / "report.json"
    output.write_text("previous-report")
    args = ["benchmark", "--compare-semantic", str(before), str(before)]
    if failure == "missing_input":
        args[-1] = str(broken)
    elif failure == "malformed_json":
        broken.write_text("{")
        args[-1] = str(broken)
    elif failure == "invalid_utf8":
        broken.write_bytes(b"\xff")
        args[-1] = str(broken)
    elif failure == "invalid_capture":
        broken.write_text("[]")
        args[-1] = str(broken)
    elif failure == "missing_profile":
        payload = deepcopy(semantic_captures["deterministic"])
        del payload["trace_profile"]
        broken.write_text(_render_json(payload))
        args[-1] = str(broken)
    elif failure == "same_outputs":
        args = ["benchmark", "--semantic-output", str(output)]
    elif failure == "overwrite_input":
        output = before
    elif failure == "capture_and_compare":
        args += ["--semantic-output", str(broken)]
    elif failure == "write_report":
        output = tmp_path / "missing-directory" / "report.json"
    elif failure == "write_semantic":
        args = ["benchmark", "--events", "1", "--semantic-output", str(tmp_path)]
        _stub_complete_reports(monkeypatch, 1)
    else:
        args = ["benchmark", "--events",
                "1001" if failure == "too_many_events" else "-1"]
    args += ["--output", str(output)]
    original = before.read_bytes()
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["passed"] is False
    assert json.loads(captured.err)["error"]
    assert before.read_bytes() == original
    if output.name == "report.json" and output.exists():
        assert output.read_text() == "previous-report"


@pytest.mark.parametrize("args", (
    ["--trace-profile", "unknown"], ["--compare-semantic", "only-one"],
))
def test_cli_argument_errors_keep_argparse_stderr_contract(
    args: list[str], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["benchmark", *args])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error:" in captured.err
