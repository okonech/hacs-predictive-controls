from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from custom_components.predictive_controls.confidence import ZoneState
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.markov import Prediction
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


def make_zone_state() -> ZoneState:
    return ZoneState(
        zone="living_room",
        confidence=0.91,
        status="confirmed",
        last_evidence_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
        last_clear_at=datetime(2026, 6, 7, 11, tzinfo=UTC),
        last_node_id="living_left",
        reason="still_target active at living_left; confidence is confirmed",
    )


def make_event() -> OccupancyEvent:
    return OccupancyEvent(
        entity_id="binary_sensor.living_still",
        node_id="living_left",
        zone="living_room",
        floor="first_floor",
        role="anchor_sensor",
        signal_type="still_target",
        state="on",
        event_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
        reliability=0.9,
    )


def test_zone_state_payload_serializes_datetimes_and_empty_values() -> None:
    assert zone_state_payload(make_zone_state()) == {
        "confidence": 0.91,
        "status": "confirmed",
        "last_evidence_at": "2026-06-07T12:00:00+00:00",
        "last_clear_at": "2026-06-07T11:00:00+00:00",
        "last_node_id": "living_left",
        "reason": "still_target active at living_left; confidence is confirmed",
    }
    assert zone_state_payload(ZoneState(zone="empty")) == {
        "confidence": 0.0,
        "status": "rejected",
        "last_evidence_at": None,
        "last_clear_at": None,
        "last_node_id": None,
        "reason": "no evidence",
    }


def test_occupancy_event_payload_serializes_event() -> None:
    assert occupancy_event_payload(make_event()) == {
        "entity_id": "binary_sensor.living_still",
        "node_id": "living_left",
        "zone": "living_room",
        "floor": "first_floor",
        "role": "anchor_sensor",
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

    without_prediction = FakeRuntime(
        zone_states={},
        recent_occupancy_events=(),
        last_source_node=None,
        last_prediction=None,
        probabilities={},
    )

    assert runtime_status_payload(without_prediction)["last_prediction"] is None
