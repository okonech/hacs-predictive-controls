from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.occupancy_tracker import TrackerDiagnostics
from custom_components.predictive_controls.status import (
    project_reliability_warnings,
    reliability_warning_summary,
    runtime_status_payload,
    tracker_diagnostics_payload,
)
from custom_components.predictive_controls.zone_model.types import (
    ReliabilityWarningOccurrence,
    SensorInput,
)
from tests.endpoint_count_fixture import advance_count_components, observe_count_sensor
from tests.persistence_component_fixture import PersistenceComponents
from tests.runtime_replay import ActiveEdge, RuntimeScenario
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
    """PATH001..004/DIAG001: actual selected pair, never a renamed legacy token."""
    payload = runtime_status_payload(runtime_with_target_state())
    diagnostics = payload["occupancy_diagnostics"]

    assert diagnostics["model"] == "zone_belief"
    assert diagnostics["policy"]["room"]["active"] is True
    assert diagnostics["beliefs"]["room"] >= 0.7
    authorization = diagnostics["authorizations"][-1]
    assert authorization["reason"] == "selected_path"
    assert authorization["provenance_kind"] == "selected_path"
    assert authorization["track_confidence"] == "provisional"
    assert authorization["path_node_ids"] == ["hall", "room"]
    source = next(state for state in diagnostics["episodes"]
                  if state["node_id"] == "hall")
    assert source["episode_id"] is not None
    assert authorization["selected_source_episode_ids"] == [source["episode_id"]]
    assert authorization["authorized_at"] == (NOW + timedelta(seconds=2)).isoformat()
    assert diagnostics["policy"]["hall"]["active"] is False
    assert diagnostics["recent_policy_events"][-1]["kind"] == "acquired"
    assert diagnostics["recent_policy_events"][-1]["episode_id"] == (
        authorization["target_episode_id"]
    )
    assert "joint" not in diagnostics
    assert "zone_model_shadow" not in payload


def test_runtime_status_payload_serializes_bounded_audit_and_prediction() -> None:
    payload = runtime_status_payload(runtime_with_target_state())
    diagnostics = payload["occupancy_diagnostics"]

    assert diagnostics["policy_audit"]
    assert diagnostics["processing"]["zone_count"] == 2
    assert diagnostics["prediction"] == {"probabilities": {}, "leases": []}
    assert payload["latency"]["sample_count"] == 2


def test_reliability_warning_projection_groups_reasons_at_exact_cutoff() -> None:
    occurrences = (
        ReliabilityWarningOccurrence(
            "office",
            "office",
            "suspected_stuck",
            "assertion_timeout",
            NOW - timedelta(hours=23, minutes=30),
            NOW - timedelta(hours=23),
            NOW - timedelta(hours=23),
        ),
        ReliabilityWarningOccurrence(
            "room",
            "room",
            "flapping",
            "impossible_cadence",
            NOW - timedelta(hours=30),
            NOW - timedelta(hours=25),
        ),
        ReliabilityWarningOccurrence(
            "room",
            "room",
            "flapping",
            "sustained_flapping",
            NOW - timedelta(hours=4),
            NOW - timedelta(hours=2),
            NOW - timedelta(hours=2),
        ),
        ReliabilityWarningOccurrence(
            "room",
            "room",
            "suspected_stuck",
            "count_conflict",
            NOW - timedelta(hours=25),
            NOW - timedelta(hours=24),
            NOW - timedelta(hours=24),
        ),
    )

    rows = project_reliability_warnings(occurrences, NOW)

    assert [(row["node_id"], row["kind"]) for row in rows] == [
        ("office", "suspected_stuck"),
        ("room", "flapping"),
    ]
    room = rows[1]
    assert room["reasons"] == ["impossible_cadence", "sustained_flapping"]
    assert room["active_reasons"] == ["impossible_cadence"]
    assert room["active"] is True
    assert room["cleared_at"] is None
    assert reliability_warning_summary(rows) == (
        "office: suspected stuck [assertion_timeout]; "
        "room: flapping [impossible_cadence, sustained_flapping] (active)"
    )


def test_reliability_warning_projection_rejects_malformed_groups() -> None:
    first = ReliabilityWarningOccurrence(
        "node",
        "first",
        "flapping",
        "impossible_cadence",
        NOW,
        NOW,
    )
    second = ReliabilityWarningOccurrence(
        "node",
        "second",
        "flapping",
        "sustained_flapping",
        NOW,
        NOW,
    )

    with pytest.raises(ValueError, match="inconsistent zones"):
        project_reliability_warnings((first, second), NOW)
    with pytest.raises(ValueError, match="reasons are invalid"):
        reliability_warning_summary(
            ({"zone": "first", "kind": "flapping", "reasons": (), "active": True},)
        )


def test_status_exposes_current_warning_and_bounded_occurrence() -> None:
    """Historical ID; original single synthetic cycle is now the no-warning case.

    HEALTH002/003 warning projection remains covered by the separately named
    six-completed-cycle equivalent below, not removed with this obsolete threshold.
    """
    runtime = runtime_with_target_state()
    runtime.confidence.observe(
        event("room", "room", "off", NOW + timedelta(seconds=10))
    )
    runtime.confidence.observe(
        event("room", "room", "on", NOW + timedelta(seconds=12))
    )

    diagnostics = runtime_status_payload(runtime)["occupancy_diagnostics"]

    room = next(
        item for item in diagnostics["episodes"] if item["node_id"] == "room"
    )
    assert room["cadence_warning"] is False
    assert room["cadence_warning_reason"] is None
    assert diagnostics["health_warnings"] == []
    assert diagnostics["reliability_warnings"] == []
    assert diagnostics["reliability_warning_occurrences"] == []
    assert diagnostics["policy"]["room"]["active"] is True


def test_status_six_completed_quick_cycles_warn_without_occupancy_degradation() -> None:
    """HEALTH002/003: extend the original synthetic one-cycle input, not an incident.

    Five completed physical cycles cannot warn. The sixth OFF qualifies one
    bounded diagnostic occurrence, without degrading or releasing the room.
    """
    runtime = runtime_with_target_state()
    runtime.confidence.observe(
        event("room", "room", "off", NOW + timedelta(seconds=10))
    )
    runtime.confidence.observe(
        event("room", "room", "on", NOW + timedelta(seconds=12))
    )
    for seconds in (20, 30, 40, 50):
        runtime.confidence.observe(
            event("room", "room", "off", NOW + timedelta(seconds=seconds))
        )
        diagnostics = runtime_status_payload(runtime)["occupancy_diagnostics"]
        assert diagnostics["reliability_warnings"] == []
        assert diagnostics["reliability_warning_occurrences"] == []
        assert diagnostics["policy"]["room"]["active"] is True
        runtime.confidence.observe(
            event("room", "room", "on", NOW + timedelta(seconds=seconds + 2))
        )

    runtime.confidence.observe(
        event("room", "room", "off", NOW + timedelta(seconds=60))
    )
    diagnostics = runtime_status_payload(runtime)["occupancy_diagnostics"]
    row, = diagnostics["reliability_warnings"]
    assert (row["node_id"], row["kind"], row["active_reasons"]) == (
        "room", "flapping", ["sustained_flapping"],
    )
    assert row["first_observed_at"] == (NOW + timedelta(seconds=60)).isoformat()
    assert row["active"] is True
    occurrence, = diagnostics["reliability_warning_occurrences"]
    assert occurrence["reason"] == "sustained_flapping"
    assert occurrence["first_observed_at"] == row["first_observed_at"]
    assert occurrence["active"] is True
    assert diagnostics["health_warnings"] == []
    assert all(not episode["health_warning"] for episode in diagnostics["episodes"])
    assert diagnostics["policy"]["room"]["active"] is True
    assert diagnostics["policy"]["room"]["pending_release_since"] is None

    runtime.confidence.refresh_active(NOW + timedelta(seconds=3609))
    assert runtime_status_payload(runtime)["occupancy_diagnostics"][
        "reliability_warning_occurrences"
    ][0]["active"] is True
    runtime.confidence.refresh_active(NOW + timedelta(seconds=3610))
    recovered = runtime_status_payload(runtime)["occupancy_diagnostics"]
    occurrence, = recovered["reliability_warning_occurrences"]
    assert occurrence["active"] is False
    assert occurrence["cleared_at"] == (NOW + timedelta(seconds=3610)).isoformat()
    assert recovered["policy"]["room"]["active"] is True


def test_runtime_status_omits_unavailable_latency() -> None:
    runtime = runtime_with_target_state()
    del runtime.latency_metrics
    assert "latency" not in runtime_status_payload(runtime)


def test_support_diagnostics_keep_only_exact_legacy_id_aliases() -> None:
    """DIAG005: authentic legacy components, not selected engine count authority.

    Original observations, supports, deadline and nonempty aliases remain. The
    diagnostic envelope is a component specimen, never current-reader inference.
    The separate current-runtime test below covers HEALTH003 on the same inputs.
    """
    predictive_map = conflict_map()
    components = PersistenceComponents(predictive_map, 2, NOW)
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
        observe_count_sensor(
            components,
            SensorInput(
                f"binary_sensor.{node_id}",
                "on",
                NOW + timedelta(seconds=seconds),
                reliability=node.reliability,
            )
        )
    pending, = components.conflicts.conflicts
    assert pending.started_at == NOW + timedelta(seconds=7)
    deadline = pending.deadline
    assert deadline == NOW + timedelta(seconds=67)
    result = advance_count_components(components, deadline)
    snapshot = components.snapshot
    specimen = TrackerDiagnostics(
        expected_occupants=2,
        requested_occupants=2,
        unsupported_count=None,
        beliefs={state.zone: state.probability for state in snapshot.belief_states},
        policy_states={state.zone: state for state in snapshot.policy_states},
        policy_decisions=result.policy_decisions,
        policy_events=result.policy_events,
        authorizations=result.authorizations,
        episode_states=snapshot.episode_states,
        traversal_tokens=snapshot.traversal_tokens,
        retained_traversal_tokens=snapshot.retained_traversal_tokens,
        pending_candidates=snapshot.pending_candidates,
        anonymous_supports=snapshot.anonymous_supports,
        support_token_bindings=snapshot.support_token_bindings,
        latest_support_transition=components.supports.latest_transition,
        count_conflicts=snapshot.count_conflicts,
        reliability_warning_occurrences=snapshot.reliability_warning_occurrences,
        sensor_reliability={
            node.node_id: node.reliability for node in components.nodes
        },
        prediction_leases=components.prediction_manager.leases,
        prediction_probabilities=components.prediction_manager.probabilities,
        policy_audit=components.audit_rows,
        event_disposition=result.disposition,
        restore_status="not_attempted",
        restore_reason=None,
        lifecycle_counters={**components.diagnostic_counters, "restore_rejected": 0},
    )

    diagnostics = tracker_diagnostics_payload(specimen)

    assert "strong_fronts" not in diagnostics
    assert len(diagnostics["anonymous_supports"]) == 2
    assert diagnostics["support_token_bindings"]
    conflict = diagnostics["count_conflicts"][0]
    assert conflict["strong_front_ids"] == conflict["support_ids"]
    expected_ids = [support.support_id for support in snapshot.anonymous_supports]
    assert len(expected_ids) == 2
    assert conflict["support_ids"] == expected_ids
    assert conflict["degraded_at"] == deadline.isoformat()
    conflict_row = next(
        row
        for row in diagnostics["policy_audit"]
        if row["reason"] == "stuck_count_conflict"
    )
    assert conflict_row["count_conflict_front_ids"] == conflict_row[
        "count_conflict_support_ids"
    ]
    assert conflict_row["count_conflict_support_ids"] == expected_ids
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


def test_current_selected_status_has_real_paths_without_legacy_count_degradation() -> (
    None
):
    """HEALTH003: same eight observations, actual runtime/public diagnostic output."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(conflict_map(), 2)
        for node_id, seconds in (
            ("target_source", 0), ("target", 1),
            ("a", 2), ("am", 3), ("as", 4),
            ("d", 5), ("dm", 6), ("ds", 7),
        ):
            replay.send(f"binary_sensor.{node_id}", "on",
                        NOW + timedelta(seconds=seconds))
        replay.advance(NOW + timedelta(seconds=67))
        diagnostics = runtime_status_payload(replay.runtime)["occupancy_diagnostics"]
        paths = diagnostics["selected_paths"]
        assert len(paths) == 2 and all(path is not None for path in paths)
        assert [path["endpoint"]["node_id"] for path in paths] == ["as", "ds"]
        assert all(path["track_confidence"] == "confirmed" for path in paths)
        assert diagnostics["unlocated_count"] == 0
        assert "strong_fronts" not in diagnostics
        assert diagnostics["anonymous_supports"] == []
        assert diagnostics["support_token_bindings"] == []
        assert diagnostics["count_conflicts"] == []
        assert diagnostics["health_warnings"] == []
        assert diagnostics["reliability_warning_occurrences"] == []
        assert len(diagnostics["episodes"]) == 8
        assert all(not episode["health_warning"] for episode in diagnostics["episodes"])
        assert diagnostics["policy_audit"]
        assert all(row["reason"] != "stuck_count_conflict"
                   for row in diagnostics["policy_audit"])
        assert diagnostics["lifecycle_counters"]["support_created"] == 0
        assert diagnostics["lifecycle_counters"]["count_conflict_degraded"] == 0
        assert replay.edges_for("target") == (
            ActiveEdge(NOW + timedelta(seconds=1), "target", True),
        )
        assert replay.view().active("target")
        assert replay.attributes["target"]["activation_provenance"] == "evidence"
        assert diagnostics["policy"]["target"]["active"] is True
