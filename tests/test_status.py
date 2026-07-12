from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from custom_components.predictive_controls.confidence import ZoneState
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.markov import Prediction
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
