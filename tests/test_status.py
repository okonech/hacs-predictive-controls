from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.confidence import ZoneState
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.markov import Prediction
from custom_components.predictive_controls.occupancy_state import (
    MovementEvidence,
    ObservationProvenance,
    PackedPolicyAuditContext,
    PolicyAuditEntry,
    PolicyDecision,
    ReleaseCause,
)
from custom_components.predictive_controls.occupancy_tracker import (
    ActivationPlausibility,
    AnonymousTrack,
    EntryPlausibility,
    InferredDeparture,
    InferredJoinSlot,
    TrackerDiagnostics,
)
from custom_components.predictive_controls.status import (
    occupancy_event_payload,
    runtime_status_payload,
    zone_state_payload,
)


@dataclass(frozen=True)
class FakeRuntime:
    zone_states: dict[str, ZoneState]
    recent_occupancy_events: tuple[OccupancyEvent, ...]
    last_source_node: str | None
    last_prediction: Prediction | None
    probabilities: dict[str, float]
    transition_counts: dict[str, dict[str, float]]
    confidence: object
    latency_metrics: object | None = None


@dataclass(frozen=True)
class FakeConfidence:
    diagnostics: TrackerDiagnostics


def make_zone_state() -> ZoneState:
    return ZoneState(
        zone="living_room",
        confidence=0.91,
        status="confirmed",
        occupancy_behavior="sticky",
        active_since=datetime(2026, 6, 7, 10, tzinfo=UTC),
        last_evidence_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
        last_clear_at=datetime(2026, 6, 7, 11, tzinfo=UTC),
        last_node_id="living_left",
        reason="still_target active at living_left; confidence is confirmed",
        explanation={"type": "event", "active_signal_count": 1},
    )


def make_diagnostics() -> TrackerDiagnostics:
    return TrackerDiagnostics(
        expected_occupants=2,
        tracks=(
            AnonymousTrack(
                track_id="track_1",
                zone="living_room",
                confidence=0.91,
                active=True,
                last_evidence_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
                source_entities=("binary_sensor.living_still",),
            ),
        ),
        protected_tracks=("living_room",),
        protected_corridor=("kitchen", "living_room"),
        inferred_join_slots=(
            InferredJoinSlot(
                zone="living_room",
                source_zone="foyer",
                source_node_id="foyer_motion",
                event_at=datetime(2026, 6, 7, 12, 5, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 10, tzinfo=UTC),
            ),
        ),
        inferred_departures=(
            InferredDeparture(
                zone="office",
                via_zone="hall",
                via_node_id="hall_motion",
                destination_zone="kitchen",
                event_at=datetime(2026, 6, 7, 12, 6, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 11, tzinfo=UTC),
            ),
        ),
        prediction_hints={"kitchen": 0.72},
        dwell_seconds={"living_room": {"samples": 2, "average_seconds": 1800.0}},
        entry_plausibilities=(
            EntryPlausibility(
                zone="kitchen",
                source_zone="living_room",
                source_node_id="living_left",
                event_at=datetime(2026, 6, 7, 12, 7, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 7, 30, tzinfo=UTC),
            ),
        ),
        activation_plausibilities=(
            ActivationPlausibility(
                zone="kitchen",
                reason="fresh adjacent entry path before local detection",
                source_zone="living_room",
                source_node_id="living_left",
                event_at=datetime(2026, 6, 7, 12, 7, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 7, 5, tzinfo=UTC),
            ),
        ),
    )


def make_event() -> OccupancyEvent:
    return OccupancyEvent(
        entity_id="binary_sensor.living_still",
        node_id="living_left",
        zone="living_room",
        floor="first_floor",
        role="anchor_sensor",
        occupancy_behavior="sticky",
        signal_type="still_target",
        state="on",
        event_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
        reliability=0.9,
    )


def test_zone_state_payload_serializes_datetimes_and_empty_values() -> None:
    assert zone_state_payload(make_zone_state()) == {
        "confidence": 0.91,
        "status": "confirmed",
        "occupancy_behavior": "sticky",
        "active_since": "2026-06-07T10:00:00+00:00",
        "last_evidence_at": "2026-06-07T12:00:00+00:00",
        "last_clear_at": "2026-06-07T11:00:00+00:00",
        "last_node_id": "living_left",
        "reason": "still_target active at living_left; confidence is confirmed",
        "explanation": {"type": "event", "active_signal_count": 1},
    }
    assert zone_state_payload(ZoneState(zone="empty")) == {
        "confidence": 0.0,
        "status": "rejected",
        "occupancy_behavior": "sustained",
        "active_since": None,
        "last_evidence_at": None,
        "last_clear_at": None,
        "last_node_id": None,
        "reason": "no evidence",
        "explanation": {},
    }


def test_occupancy_event_payload_serializes_event() -> None:
    assert occupancy_event_payload(make_event()) == {
        "entity_id": "binary_sensor.living_still",
        "node_id": "living_left",
        "zone": "living_room",
        "floor": "first_floor",
        "role": "anchor_sensor",
        "occupancy_behavior": "sticky",
        "signal_type": "still_target",
        "state": "on",
        "event_at": "2026-06-07T12:00:00+00:00",
        "reliability": 0.9,
    }


def test_runtime_status_payload_serializes_prediction_and_without_prediction() -> None:
    runtime = FakeRuntime(
        zone_states={"living_room": make_zone_state()},
        recent_occupancy_events=(make_event(),),
        last_source_node="living_left",
        last_prediction=Prediction(node_id="dining_room", probability=0.72),
        probabilities={"dining_room": 0.72},
        transition_counts={"living_left": {"dining_room": 4.0}},
        confidence=FakeConfidence(make_diagnostics()),
        latency_metrics={"p95_ms": 1.5},
    )

    payload = runtime_status_payload(runtime)

    assert payload["zone_states"]["living_room"]["confidence"] == 0.91
    assert payload["recent_occupancy_events"][0]["signal_type"] == "still_target"
    assert payload["last_source_node"] == "living_left"
    assert payload["last_prediction"] == {
        "node_id": "dining_room",
        "probability": 0.72,
    }
    assert payload["probabilities"] == {"dining_room": 0.72}
    assert payload["transition_counts"] == {"living_left": {"dining_room": 4.0}}
    assert payload["latency"] == {"p95_ms": 1.5}
    assert payload["expected_occupants"] == 0
    assert payload["occupancy_diagnostics"] == {
        "expected_occupants": 2,
        "reliability": {
            "criteria": {
                "repeat_minimum": 2,
                "flap_window_seconds": 30,
            },
            "coverage": {
                "observed_event_count": 0,
                "oldest_event_at": None,
                "newest_event_at": None,
            },
            "rejected_motion_captures": [],
            "low_confidence_flaps": [],
        },
        "protected_tracks": ["living_room"],
        "protected_corridor": ["kitchen", "living_room"],
        "inferred_join_slots": [
            {
                "zone": "living_room",
                "source_zone": "foyer",
                "source_node_id": "foyer_motion",
                "event_at": "2026-06-07T12:05:00+00:00",
                "expires_at": "2026-06-07T12:10:00+00:00",
            }
        ],
        "inferred_departures": [
            {
                "zone": "office",
                "via_zone": "hall",
                "via_node_id": "hall_motion",
                "destination_zone": "kitchen",
                "event_at": "2026-06-07T12:06:00+00:00",
                "expires_at": "2026-06-07T12:11:00+00:00",
            }
        ],
        "entry_plausibilities": [
            {
                "zone": "kitchen",
                "source_zone": "living_room",
                "source_node_id": "living_left",
                "event_at": "2026-06-07T12:07:00+00:00",
                "expires_at": "2026-06-07T12:07:30+00:00",
            }
        ],
        "activation_plausibilities": [
            {
                "zone": "kitchen",
                "reason": "fresh adjacent entry path before local detection",
                "source_zone": "living_room",
                "source_node_id": "living_left",
                "event_at": "2026-06-07T12:07:00+00:00",
                "expires_at": "2026-06-07T12:07:05+00:00",
            }
        ],
        "prediction_hints": {"kitchen": 0.72},
        "dwell_seconds": {"living_room": {"samples": 2, "average_seconds": 1800.0}},
        "tracks": [
            {
                "track_id": "track_1",
                "zone": "living_room",
                "confidence": 0.91,
                "active": True,
                "last_evidence_at": "2026-06-07T12:00:00+00:00",
                "source_entities": ["binary_sensor.living_still"],
            }
        ],
    }

    without_prediction = FakeRuntime(
        zone_states={},
        recent_occupancy_events=(),
        last_source_node=None,
        last_prediction=None,
        probabilities={},
        transition_counts={},
        confidence=FakeConfidence(make_diagnostics()),
    )

    assert runtime_status_payload(without_prediction)["last_prediction"] is None


def test_runtime_status_payload_serializes_retained_policy_audit() -> None:
    packed_context = PackedPolicyAuditContext(
        zlib.compress(b'{"marker":"retained"}')
    )
    diagnostics = replace(
        make_diagnostics(),
        joint_movement_evidence=(
            MovementEvidence(
                path_key=("office", "office_motion", "kitchen_motion"),
                origin_zone="office",
                source_zone="office",
                target_zone="kitchen",
                coherent_probability=0.75,
                source_node_id="office_motion",
                target_node_id="kitchen_motion",
                evidence_ids=("office:on", "hall@episode", "kitchen:on"),
                disposition="censored_graph_path",
                via_zone="hall",
                via_node_id="hall_motion",
            ),
        ),
        joint_last_provenance=ObservationProvenance(
            event_id="office-motion",
            evidence_episode_id="office-motion:1",
            entity_id="binary_sensor.office",
            node_id="office_motion",
            zone="office",
            state="on",
            signal_type="motion",
            reliability=0.9,
            log_likelihood_by_count=(0.0,),
            disposition="accepted",
        ),
        joint_policy_audit=(
            PolicyAuditEntry(
                decision_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
                source="observation",
                trigger_event_id="office-motion",
                trigger_entity_id="binary_sensor.office",
                trigger_zone="office",
                trigger_state="on",
                trigger_disposition="accepted",
                decision=PolicyDecision(
                    zone="office",
                    action="release",
                    accepted=True,
                    reason_code="graph_departure",
                    gate_values={"origin_marginal": 0.05},
                    evidence_ids=("office-hall",),
                ),
                previous_keep_on=True,
                current_keep_on=False,
                previous_reason="trusted local occupancy established",
                current_reason="graph-valid final occupant departure",
                previous_release_cause=None,
                current_release_cause=ReleaseCause.GRAPH_DEPARTURE,
                context=packed_context,
            ),
        ),
    )
    runtime = FakeRuntime(
        zone_states={},
        recent_occupancy_events=(),
        last_source_node=None,
        last_prediction=None,
        probabilities={},
        transition_counts={},
        confidence=FakeConfidence(diagnostics),
    )

    joint = runtime_status_payload(runtime)["occupancy_diagnostics"]["joint"]
    audit = joint["policy_audit"]

    assert audit == [
        {
            "decision_at": "2026-06-07T12:00:00+00:00",
            "source": "observation",
            "trigger": {
                "event_id": "office-motion",
                "entity_id": "binary_sensor.office",
                "zone": "office",
                "state": "on",
                "disposition": "accepted",
            },
            "decision": {
                "zone": "office",
                "action": "release",
                "accepted": True,
                "reason_code": "graph_departure",
                "gate_values": {"origin_marginal": 0.05},
                "evidence_ids": ["office-hall"],
            },
            "previous": {
                "keep_on": True,
                "reason": "trusted local occupancy established",
                "release_cause": None,
            },
            "current": {
                "keep_on": False,
                "reason": "graph-valid final occupant departure",
                "release_cause": "graph_departure",
            },
            "context": {
                "encoding": "zlib-json-v1",
                "data": base64.b64encode(packed_context.compressed_json).decode(
                    "ascii"
                ),
            },
        }
    ]
    assert joint["policy_audit_retention"] == {
        "retention_hours": 12,
        "max_entries": 8192,
        "max_context_compressed_bytes": 12582912,
        "context_compressed_bytes": len(packed_context.compressed_json),
        "entry_count": 1,
        "oldest_decision_at": "2026-06-07T12:00:00+00:00",
        "newest_decision_at": "2026-06-07T12:00:00+00:00",
    }
    assert joint["movement_evidence"] == [
        {
            "path_key": ["office", "office_motion", "kitchen_motion"],
            "origin_zone": "office",
            "source_zone": "office",
            "target_zone": "kitchen",
            "coherent_probability": 0.75,
            "source_node_id": "office_motion",
            "target_node_id": "kitchen_motion",
            "via_zone": "hall",
            "via_node_id": "hall_motion",
            "evidence_ids": ["office:on", "hall@episode", "kitchen:on"],
            "disposition": "censored_graph_path",
        }
    ]


def test_runtime_status_payload_serializes_reliability_review() -> None:
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    def entry(
        event_id: str,
        decision_at: datetime,
        state: str,
        occupied_marginal: float | None,
    ) -> PolicyAuditEntry:
        return PolicyAuditEntry(
            decision_at=decision_at,
            source="observation",
            trigger_event_id=event_id,
            trigger_entity_id="binary_sensor.office_motion",
            trigger_zone="office",
            trigger_state=state,
            trigger_disposition="accepted",
            decision=PolicyDecision(
                zone="office",
                action="activate",
                accepted=False,
                reason_code=(
                    "occupied_gate_failed"
                    if state == "on"
                    else "non_positive_observation"
                ),
                gate_values={}
                if occupied_marginal is None
                else {"occupied_marginal": occupied_marginal},
                evidence_ids=(event_id,),
            ),
            previous_keep_on=False,
            current_keep_on=False,
            previous_reason="no trusted occupancy",
            current_reason="no trusted occupancy",
            previous_release_cause=None,
            current_release_cause=None,
        )

    diagnostics = replace(
        make_diagnostics(),
        joint_policy_audit=(
            entry("on-1", now, "on", 0.2),
            entry("off-1", now + timedelta(seconds=5), "off", None),
            entry("on-2", now + timedelta(seconds=10), "on", 0.3),
            entry("off-2", now + timedelta(seconds=14), "off", None),
        ),
    )
    runtime = FakeRuntime(
        zone_states={},
        recent_occupancy_events=(),
        last_source_node=None,
        last_prediction=None,
        probabilities={},
        transition_counts={},
        confidence=FakeConfidence(diagnostics),
    )

    reliability = runtime_status_payload(runtime)["occupancy_diagnostics"][
        "reliability"
    ]

    assert reliability == {
        "criteria": {
            "repeat_minimum": 2,
            "flap_window_seconds": 30,
        },
        "coverage": {
            "observed_event_count": 4,
            "oldest_event_at": "2026-06-07T12:00:00+00:00",
            "newest_event_at": "2026-06-07T12:00:14+00:00",
        },
        "rejected_motion_captures": [
            {
                "entity_id": "binary_sensor.office_motion",
                "zone": "office",
                "capture_count": 2,
                "last_capture_at": "2026-06-07T12:00:10+00:00",
                "reason_counts": {"occupied_gate_failed": 2},
                "max_occupied_marginal": 0.3,
            }
        ],
        "low_confidence_flaps": [
            {
                "entity_id": "binary_sensor.office_motion",
                "zone": "office",
                "pulse_count": 2,
                "last_flap_at": "2026-06-07T12:00:14+00:00",
                "shortest_pulse_seconds": 4.0,
                "max_occupied_marginal": 0.3,
            }
        ],
    }
