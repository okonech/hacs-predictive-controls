from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.status import runtime_status_payload
from tests.test_confidence import event
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def runtime_with_target_state() -> SimpleNamespace:
    predictive_map = target_map()
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    confidence.observe(event("hall", "hall", "on", NOW))
    confidence.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))
    states = confidence.states
    return SimpleNamespace(
        confidence=confidence,
        zone_states=states,
        recent_occupancy_events=confidence.recent_events,
        last_source_node=None,
        last_prediction=None,
        probabilities={},
        transition_counts=confidence.prediction_chain.counts,
        expected_occupants=1,
        expected_occupants_entity="",
        authoritative_count_available=True,
        problem_reasons=(),
        latency_metrics={"sample_count": 2, "p95_ms": 1.0},
    )


def test_runtime_status_payload_exposes_only_target_model_diagnostics() -> None:
    payload = runtime_status_payload(runtime_with_target_state())
    diagnostics = payload["occupancy_diagnostics"]

    assert diagnostics["model"] == "zone_belief"
    assert diagnostics["policy"]["room"]["active"] is True
    assert diagnostics["beliefs"]["room"] >= 0.7
    assert diagnostics["authorizations"][-1]["reason"] == (
        "provisional_track_acquired"
    )
    assert diagnostics["recent_policy_events"][-1]["kind"] == "acquired"
    assert "joint" not in diagnostics
    assert "zone_model_shadow" not in payload


def test_runtime_status_payload_serializes_bounded_audit_and_prediction() -> None:
    payload = runtime_status_payload(runtime_with_target_state())
    diagnostics = payload["occupancy_diagnostics"]

    assert diagnostics["policy_audit"]
    assert diagnostics["processing"]["zone_count"] == 2
    assert diagnostics["prediction"] == {"probabilities": {}, "leases": []}
    assert payload["latency"]["sample_count"] == 2


def test_runtime_status_omits_unavailable_latency() -> None:
    runtime = runtime_with_target_state()
    del runtime.latency_metrics
    assert "latency" not in runtime_status_payload(runtime)
