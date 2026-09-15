"""Strict benchmark evidence regressions from the 2026-09-14 source review.

Malformed current-row competitors and Boolean/float-zero report operands must
not certify success. Statistics and report operands are explicitly synthetic;
prediction acquisitions come from actual timestamped engine observations.
No live producer failure, physical incident or performance measurement is claimed.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from importlib import import_module
from typing import Literal, Protocol, runtime_checkable

import pytest

from custom_components.predictive_controls.markov import MARKOV_COUNT_LIMIT, MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
    ZoneModelResult,
    ZoneModelSnapshot,
)
from tests.test_occupancy_performance_benchmark import (
    NOW,
    AcquisitionPredicate,
    FastPathPredicate,
    MeasurementReports,
    PredictionProof,
    _checked_boolean,
    _checked_flags,
    _checked_reports,
    _complete_component_reports,
)
from tests.test_occupancy_performance_benchmark import (
    actual_mature_prediction_operation as actual_mature_prediction_operation,
)
from tests.test_occupancy_performance_benchmark import predictive_map as predictive_map

NegativeGatePredicate = Callable[[MeasurementReports, int], dict[str, bool]]
Entrypoint = Literal["fast_path", "acquisition"]
MatureOperation = tuple[
    ZoneModelSnapshot, ZoneModelResult, str, str, datetime, PredictionProof,
]
MISSING = object()
NEGATIVE_GATES = {
    "workload_present": True,
    "samples_complete": True,
    "correctness": True,
    "p99_latency": True,
    "hard_latency": True,
}


@runtime_checkable
class BenchmarkPredicates(Protocol):
    """Explicit callable shapes across the intentionally skipped benchmark import."""

    @property
    def _fast_path_qualified(self) -> FastPathPredicate: ...

    @property
    def _acquisition_qualified(self) -> AcquisitionPredicate: ...

    @property
    def _negative_workload_gates(self) -> NegativeGatePredicate: ...


@pytest.fixture(scope="module")
def benchmark_predicates() -> BenchmarkPredicates:
    module = import_module("benchmarks.occupancy_performance")
    assert isinstance(module, BenchmarkPredicates)
    return module


def _qualifies_prediction(
    api: BenchmarkPredicates, entrypoint: Entrypoint,
    operation: MatureOperation, proof: PredictionProof | None,
) -> bool:
    before, result, source, zone, at, _ = operation
    if entrypoint == "fast_path":
        return _checked_boolean(api._fast_path_qualified(
            "mature_prediction", before, result, source, zone, at, proof,
        ))
    return _checked_boolean(api._acquisition_qualified(
        before, result, zone, at, proof, require_prediction=True,
    ))


def _copy_prediction_counts(proof: PredictionProof) -> dict[str, dict[str, float]]:
    return {node: dict(row) for node, row in proof[2].items()}


def _learned_row_operation(
    model: PredictiveMap, target_count: float, competitor_count: float,
) -> MatureOperation:
    """Synthetic weighted statistics; unmodified engine-generated grants and edges."""
    engine = ZoneModelEngine(model, 2, NOW)
    source, zone = "stairs_bottom_sensor", "guest_bedroom"
    assert engine.prediction_manager.chain.observe(
        source, "guest_bedroom_sensor", weight=target_count,
    )
    if competitor_count:
        assert engine.prediction_manager.chain.observe(
            source, "stairs_top_sensor", weight=competitor_count,
        )
    for ms, node in enumerate(("dining_sensor", "foyer_sensor"), 1):
        engine.observe(SensorInput(
            next(iter(model.nodes[node].entities.values())), "on",
            NOW + timedelta(milliseconds=ms),
        ))
    before = engine.snapshot
    at = NOW + timedelta(milliseconds=3)
    result = engine.observe(SensorInput(
        next(iter(model.nodes[source].entities.values())), "on", at,
    ))
    proof = (model, engine.prediction_manager.leases,
             engine.prediction_manager.chain.counts)
    return before, result, source, zone, at, proof


def _valid_negative_report() -> MeasurementReports:
    """Complete component operands only; never invokes a measured workload."""
    _, _, negative = _complete_component_reports(2)
    reports = _checked_reports(negative)
    reports["rejected_jump"]["p99_ms"] = 0.0
    reports["rejected_jump"]["max_ms"] = 9.999
    return reports


@pytest.mark.parametrize("entrypoint", ("fast_path", "acquisition"))
@pytest.mark.parametrize("overflow", (
    MARKOV_COUNT_LIMIT + 1.0, math.nextafter(MARKOV_COUNT_LIMIT, math.inf),
), ids=("cap_plus_one", "first_float_above_cap"))
def test_prediction_competing_row_overflow_fails_closed(
    benchmark_predicates: BenchmarkPredicates,
    actual_mature_prediction_operation: MatureOperation,
    entrypoint: Entrypoint, overflow: float,
) -> None:
    """A dropped competing count must not reproduce the old probability as proof."""
    operation = actual_mature_prediction_operation
    proof = operation[5]
    assert _qualifies_prediction(benchmark_predicates, entrypoint, operation, proof)
    model, leases, _ = proof
    lease, = (lease for lease in leases if lease.target_zone == operation[3])
    assert lease.current_node_id == "stairs_bottom_sensor"
    assert lease.source_node_id == "foyer_sensor" != lease.current_node_id
    competitor = "stairs_top_sensor"
    assert competitor in model.nodes[lease.current_node_id].adjacent
    assert competitor != lease.target_node_id
    counts = _copy_prediction_counts(proof)
    assert counts[lease.current_node_id][competitor] == 0.0
    assert counts[lease.current_node_id][lease.target_node_id] == lease.support == 11.0
    counts[lease.current_node_id][competitor] = overflow
    restored = MarkovChain(model)
    restored.restore_counts(counts)
    assert restored.counts[lease.current_node_id][competitor] == 0.0
    assert restored.probabilities(lease.current_node_id)[
        lease.target_node_id
    ] == lease.probability
    assert proof[2][lease.current_node_id][competitor] == 0.0
    assert _qualifies_prediction(
        benchmark_predicates, entrypoint, operation, (model, leases, counts),
    ) is False


@pytest.mark.parametrize("entrypoint", ("fast_path", "acquisition"))
@pytest.mark.parametrize("mutation", (
    "missing_proof", "empty_counts", "missing_current_row", "missing_competitor",
    "missing_target", "false", "true", "negative", "nan", "infinity", "minus_infinity",
))
def test_prediction_row_evidence_fails_closed(
    benchmark_predicates: BenchmarkPredicates,
    actual_mature_prediction_operation: MatureOperation,
    entrypoint: Entrypoint, mutation: str,
) -> None:
    """Reject incomplete and malformed full rows independently of the overflow fix."""
    operation = actual_mature_prediction_operation
    original = operation[5]
    assert _qualifies_prediction(benchmark_predicates, entrypoint, operation, original)
    model, leases, _ = original
    counts = _copy_prediction_counts(original)
    proof: PredictionProof | None = (model, leases, counts)
    current = operation[2]
    if mutation == "missing_proof":
        proof = None
    elif mutation == "empty_counts":
        counts.clear()
    elif mutation == "missing_current_row":
        del counts[current]
    elif mutation == "missing_competitor":
        del counts[current]["stairs_top_sensor"]
    elif mutation == "missing_target":
        del counts[current]["guest_bedroom_sensor"]
    else:
        malformed: dict[str, float] = {
            "false": False, "true": True, "negative": -1.0,
            "nan": math.nan, "infinity": math.inf, "minus_infinity": -math.inf,
        }
        counts[current]["stairs_top_sensor"] = malformed[mutation]
    assert _qualifies_prediction(
        benchmark_predicates, entrypoint, operation, proof,
    ) is False
    assert _qualifies_prediction(benchmark_predicates, entrypoint, operation, original)


@pytest.mark.parametrize("entrypoint", ("fast_path", "acquisition"))
@pytest.mark.parametrize("competitor", (1.0, MARKOV_COUNT_LIMIT))
def test_prediction_uses_the_complete_competing_distribution(
    benchmark_predicates: BenchmarkPredicates,
    actual_mature_prediction_operation: MatureOperation,
    entrypoint: Entrypoint, competitor: float,
) -> None:
    """Legal competing counts, including the cap, must change the denominator."""
    operation = actual_mature_prediction_operation
    proof = operation[5]
    assert _qualifies_prediction(benchmark_predicates, entrypoint, operation, proof)
    model, leases, _ = proof
    counts = _copy_prediction_counts(proof)
    counts[operation[2]]["stairs_top_sensor"] = competitor
    restored = MarkovChain(model)
    restored.restore_counts(counts)
    assert restored.counts[operation[2]]["stairs_top_sensor"] == competitor
    lease = next(lease for lease in leases if lease.target_zone == operation[3])
    assert (
        restored.probabilities(operation[2])[lease.target_node_id] != lease.probability
    )
    assert _qualifies_prediction(
        benchmark_predicates, entrypoint, operation, (model, leases, counts),
    ) is False


@pytest.mark.parametrize("entrypoint", ("fast_path", "acquisition"))
@pytest.mark.parametrize(("target", "competitor", "mature"), (
    (11.0, 0.0, True), (11.5, 0.0, True), (MARKOV_COUNT_LIMIT, 0.0, True),
    (16.0, 1.0, True), (16.0, 1.000001, False),
), ids=("original", "fraction", "inclusive_cap", "exact_maturity", "below_maturity"))
def test_prediction_valid_row_boundaries_use_actual_events(
    benchmark_predicates: BenchmarkPredicates, predictive_map: PredictiveMap,
    entrypoint: Entrypoint, target: float, competitor: float, mature: bool,
) -> None:
    """Do not fake a mature flag or probability to prove legal evidence boundaries."""
    operation = _learned_row_operation(predictive_map, target, competitor)
    before, result, current, zone, at, proof = operation
    model, leases, counts = proof
    lease, = (lease for lease in leases if lease.target_zone == zone)
    row = counts[current]
    assert set(row) == set(model.nodes[current].adjacent)
    assert row[lease.target_node_id] == lease.support == target
    assert row["stairs_top_sensor"] == competitor
    weighted = {node: count + model.nodes[node].route_prior_weight
                for node, count in row.items()}
    probability = weighted[lease.target_node_id] / sum(weighted.values())
    assert lease.probability == probability
    assert lease.mature is mature
    assert (probability >= 0.85) is mature
    if target == 16.0 and competitor == 1.0:
        assert probability == 0.85
    assert lease.current_node_id == current
    assert lease.source_node_id == "foyer_sensor"
    assert lease.created_at == at
    grant, = (grant for grant in result.snapshot.selected_prediction_grants
              if grant.key == (lease.source_node_id, current, lease.target_node_id,
                               lease.source_episode_id))
    assert grant.authorization in result.authorizations
    assert grant.authorization.authorized
    assert grant.authorization.authorized_at == at
    assert grant.effect_kind == "positive"
    assert grant.expires_at == lease.expires_at == at + timedelta(seconds=10)
    assert not next(
        policy for policy in before.policy_states if policy.zone == zone
    ).active
    policy = next(
        policy for policy in result.snapshot.policy_states if policy.zone == zone
    )
    events = tuple(event for event in result.policy_events if event.zone == zone)
    if mature:
        event, = events
        assert event.kind == "acquired" and event.event_at == at
        assert event.authorization_reason == "prediction_authorized"
        assert policy.active and policy.phase == "predicted"
        assert policy.prediction_probability == probability
        assert policy.prediction_support == target
        assert policy.prediction_source_episode_id == lease.source_episode_id
    else:
        assert not events and not policy.active
        assert policy.phase != "predicted"
    assert _qualifies_prediction(
        benchmark_predicates, entrypoint, operation, proof,
    ) is mature


@pytest.mark.parametrize(("field", "gate"), (
    ("p99_ms", "p99_latency"), ("max_ms", "hard_latency"),
    ("on_write_count", "correctness"), ("acquired_event_count", "correctness"),
))
@pytest.mark.parametrize("value", (False, True))
def test_negative_report_rejects_boolean_numeric_evidence(
    benchmark_predicates: BenchmarkPredicates, field: str, gate: str, value: bool,
) -> None:
    """A Boolean must not masquerade as a measured latency or exact zero output."""
    reports = _valid_negative_report()
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == NEGATIVE_GATES
    reports["rejected_jump"][field] = value
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == {**NEGATIVE_GATES, gate: False}


@pytest.mark.parametrize("field", ("on_write_count", "acquired_event_count"))
@pytest.mark.parametrize(("value", "valid"), (
    (0, True), (0.0, False), (MISSING, False), (None, False),
    ("0", False), (1, False), (-1, False),
), ids=("integer_zero", "float_zero", "missing", "none", "string", "one", "negative"))
def test_negative_report_requires_integer_zero_outputs(
    benchmark_predicates: BenchmarkPredicates, field: str, value: object, valid: bool,
) -> None:
    """Reject noninteger zero, absence and output without changing other gates."""
    reports = _valid_negative_report()
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == NEGATIVE_GATES
    if value is MISSING:
        del reports["rejected_jump"][field]
    else:
        reports["rejected_jump"][field] = value
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == {**NEGATIVE_GATES, "correctness": valid}


@pytest.mark.parametrize("field", ("p99_ms", "max_ms"))
@pytest.mark.parametrize(("value", "valid"), (
    (0, True), (0.0, True), (MISSING, False), (None, False), ("0", False),
    (-1.0, False), (math.nan, False), (math.inf, False), (-math.inf, False),
    ("at_boundary", True), ("outside_boundary", False),
), ids=("integer_zero", "float_zero", "missing", "none", "string", "negative",
        "nan", "infinity", "minus_infinity", "at_boundary", "outside_boundary"))
def test_negative_report_latency_boundaries(
    benchmark_predicates: BenchmarkPredicates, field: str, value: object, valid: bool,
) -> None:
    """Preserve inclusive p99=5ms and exclusive maximum=10ms with exact float edges."""
    reports = _valid_negative_report()
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == NEGATIVE_GATES
    if value is MISSING:
        del reports["rejected_jump"][field]
    else:
        if value == "at_boundary":
            value = 5.0 if field == "p99_ms" else math.nextafter(10.0, -math.inf)
        elif value == "outside_boundary":
            value = math.nextafter(5.0, math.inf) if field == "p99_ms" else 10.0
        reports["rejected_jump"][field] = value
    gate = "p99_latency" if field == "p99_ms" else "hard_latency"
    assert _checked_flags(
        benchmark_predicates._negative_workload_gates(reports, 2),
    ) == {**NEGATIVE_GATES, gate: valid}
