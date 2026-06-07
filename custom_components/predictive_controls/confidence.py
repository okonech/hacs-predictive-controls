from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .events import OccupancyEvent
from .model import PredictiveMap

CONFIDENCE_STATUSES = ("rejected", "suspect", "possible", "probable", "confirmed")


@dataclass(frozen=True)
class ZoneState:
    """Current inferred occupancy confidence for one zone."""

    zone: str
    confidence: float = 0.0
    status: str = "rejected"
    last_evidence_at: datetime | None = None
    last_clear_at: datetime | None = None
    last_node_id: str | None = None
    reason: str = "no evidence"


@dataclass(frozen=True)
class ZoneUpdate:
    """Result of applying one occupancy event to zone confidence."""

    event: OccupancyEvent
    previous: ZoneState
    current: ZoneState


class ZoneConfidenceEngine:
    """Confidence state machine for mapped occupancy zones."""

    def __init__(self, predictive_map: PredictiveMap) -> None:
        self._states = {
            zone: ZoneState(zone=zone)
            for zone in predictive_map.zones()
        }
        self._recent_events: list[OccupancyEvent] = []

    @property
    def states(self) -> dict[str, ZoneState]:
        return self._states.copy()

    @property
    def recent_events(self) -> tuple[OccupancyEvent, ...]:
        return tuple(self._recent_events)

    def state_for_zone(self, zone: str) -> ZoneState:
        return self._states.get(zone, ZoneState(zone=zone))

    def observe(self, event: OccupancyEvent) -> ZoneUpdate:
        previous = self.state_for_zone(event.zone)
        confidence = self._confidence_after_event(previous.confidence, event)
        current = replace(
            previous,
            confidence=confidence,
            status=status_for_confidence(confidence),
            last_evidence_at=event.event_at
            if event.state == "on"
            else previous.last_evidence_at,
            last_clear_at=event.event_at
            if event.state == "off"
            else previous.last_clear_at,
            last_node_id=event.node_id,
            reason=reason_for_event(event, confidence),
        )
        self._states[event.zone] = current
        self._recent_events = [*self._recent_events[-24:], event]
        return ZoneUpdate(event=event, previous=previous, current=current)

    def _confidence_after_event(
        self,
        current_confidence: float,
        event: OccupancyEvent,
    ) -> float:
        if event.state == "off":
            return round(current_confidence * clear_factor_for_event(event), 3)

        floor = on_confidence_floor(event)
        if current_confidence < floor:
            return floor
        return min(1.0, round(current_confidence + 0.08 * event.reliability, 3))


def status_for_confidence(confidence: float) -> str:
    if confidence < 0.05:
        return "rejected"
    if confidence < 0.35:
        return "suspect"
    if confidence < 0.60:
        return "possible"
    if confidence < 0.85:
        return "probable"
    return "confirmed"


def on_confidence_floor(event: OccupancyEvent) -> float:
    base = 0.65
    if event.role == "transition_gate":
        base = 0.55
    elif event.role == "ambiguous_open_plan":
        base = 0.58
    elif event.role == "subzone_occupancy":
        base = 0.60
    elif event.role == "anchor_sensor":
        base = 0.75

    if event.signal_type == "still_target":
        base = max(base, 0.90)
    elif event.signal_type in {"target", "zone_occupancy"}:
        base = max(base, 0.74)
    elif event.signal_type == "moving_target":
        base = max(base, 0.62)

    reliability_factor = 0.75 + min(event.reliability, 1.0) / 4
    return round(min(1.0, base * reliability_factor), 3)


def clear_factor_for_event(event: OccupancyEvent) -> float:
    if event.role == "transition_gate":
        return 0.25
    if event.role == "ambiguous_open_plan":
        return 0.55
    if event.role == "anchor_sensor":
        return 0.80 if event.signal_type == "still_target" else 0.65
    if event.role in {"room_occupancy", "subzone_occupancy"}:
        return 0.70
    return 0.60


def reason_for_event(event: OccupancyEvent, confidence: float) -> str:
    status = status_for_confidence(confidence)
    if event.state == "off":
        return (
            f"{event.signal_type} cleared at {event.node_id}; "
            f"confidence decayed to {status}"
        )
    return f"{event.signal_type} active at {event.node_id}; confidence is {status}"
