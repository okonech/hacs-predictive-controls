from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.status import (
    runtime_status_payload,
    tracker_diagnostics_payload,
)
from tests.test_confidence import event
from tests.test_zone_model_count import conflict_map
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


def test_support_diagnostics_keep_only_exact_legacy_id_aliases() -> None:
    predictive_map = conflict_map()
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    for node_id, seconds in (
        ("target_source", 0),
        ("target", 1),
        ("a", 2),
        ("am", 3),
        ("as", 4),
        ("d", 5),
        ("dm", 6),
        ("ds", 7),
    ):
        node = predictive_map.nodes[node_id]
        confidence.observe(
            OccupancyEvent(
                f"binary_sensor.{node_id}",
                node_id,
                node.occupancy_zone,
                node.floor,
                node.role,
                predictive_map.occupancy_behavior_for_node(node),
                "motion",
                "on",
                NOW + timedelta(seconds=seconds),
                node.reliability,
            )
        )
    deadline = confidence.diagnostics.count_conflicts[0].deadline
    confidence.refresh_active(deadline)

    diagnostics = tracker_diagnostics_payload(confidence.diagnostics)

    assert "strong_fronts" not in diagnostics
    assert len(diagnostics["anonymous_supports"]) == 2
    assert diagnostics["support_token_bindings"]
    conflict = diagnostics["count_conflicts"][0]
    assert conflict["strong_front_ids"] == conflict["support_ids"]
    conflict_row = next(
        row
        for row in diagnostics["policy_audit"]
        if row["reason"] == "stuck_count_conflict"
    )
    assert conflict_row["count_conflict_front_ids"] == conflict_row[
        "count_conflict_support_ids"
    ]
    counters = diagnostics["lifecycle_counters"]
    assert set(counters) == {
        "support_created",
        "support_transferred",
        "support_coalesced",
        "support_expired",
        "support_stale_binding_ignored",
        "count_conflict_started",
        "count_conflict_canceled",
        "count_conflict_degraded",
        "restore_rejected",
    }
    assert counters["support_created"] == 2
    assert counters["count_conflict_degraded"] == 1
    assert all(0 <= value <= 2**31 - 1 for value in counters.values())
