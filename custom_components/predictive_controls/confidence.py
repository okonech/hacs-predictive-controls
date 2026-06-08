from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .events import OccupancyEvent
from .model import PredictiveMap

CONFIDENCE_STATUSES = ("rejected", "suspect", "possible", "probable", "confirmed")


@dataclass(frozen=True)
class ZoneState:
    """Current inferred occupancy confidence for one zone."""

    zone: str
    confidence: float = 0.0
    status: str = "rejected"
    occupancy_behavior: str = "sustained"
    active_since: datetime | None = None
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
            zone: ZoneState(
                zone=zone,
                occupancy_behavior=predictive_map.zone_occupancy_behavior(zone),
            )
            for zone in predictive_map.zones()
        }
        self._active_events: dict[str, dict[str, OccupancyEvent]] = {}
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
        self._track_active_event(event)
        confidence = self._confidence_after_event(previous.confidence, event)
        active_since = self._active_since(event.zone)
        current = replace(
            previous,
            confidence=confidence,
            status=status_for_confidence(confidence),
            occupancy_behavior=event.occupancy_behavior,
            active_since=active_since,
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

    def refresh_active(self, now: datetime) -> tuple[ZoneUpdate, ...]:
        updates: list[ZoneUpdate] = []
        for zone, active_events in self._active_events.items():
            if not active_events:
                continue
            active_event = min(active_events.values(), key=lambda event: event.event_at)
            previous = self.state_for_zone(zone)
            confidence = sustained_confidence_for_duration(
                active_event,
                max(timedelta(0), now - active_event.event_at),
                previous.confidence,
            )
            if confidence <= previous.confidence:
                continue
            current = replace(
                previous,
                confidence=confidence,
                status=status_for_confidence(confidence),
                occupancy_behavior=active_event.occupancy_behavior,
                active_since=active_event.event_at,
                last_node_id=active_event.node_id,
                reason=reason_for_sustained_event(active_event, confidence, now),
            )
            self._states[zone] = current
            updates.append(ZoneUpdate(active_event, previous, current))
        return tuple(updates)

    def _track_active_event(self, event: OccupancyEvent) -> None:
        zone_events = self._active_events.setdefault(event.zone, {})
        if event.state == "on":
            zone_events[event.entity_id] = event
        else:
            zone_events.pop(event.entity_id, None)

    def _active_since(self, zone: str) -> datetime | None:
        active_events = self._active_events.get(zone, {})
        if not active_events:
            return None
        return min(event.event_at for event in active_events.values())

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


def sustained_confidence_for_duration(
    event: OccupancyEvent,
    active_for: timedelta,
    current_confidence: float,
) -> float:
    floor = max(current_confidence, on_confidence_floor(event))
    seconds = max(0.0, active_for.total_seconds())
    cap = sustained_cap_for_event(event)
    ramp_seconds = sustained_ramp_seconds(event.occupancy_behavior)
    progress = min(1.0, seconds / ramp_seconds)
    confidence = floor + (cap - floor) * progress
    return round(max(current_confidence, min(cap, confidence)), 3)


def sustained_cap_for_event(event: OccupancyEvent) -> float:
    cap = {
        "transient": 0.70,
        "ambiguous": 0.85,
        "sustained": 0.96,
        "sticky": 0.98,
    }.get(event.occupancy_behavior, 0.90)
    if event.signal_type == "still_target":
        cap = max(cap, 0.99)
    elif event.signal_type in {"target", "zone_occupancy"}:
        cap = max(cap, 0.95)
    return cap


def sustained_ramp_seconds(occupancy_behavior: str) -> float:
    return {
        "transient": 180.0,
        "ambiguous": 600.0,
        "sustained": 480.0,
        "sticky": 300.0,
    }.get(occupancy_behavior, 600.0)


def clear_factor_for_event(event: OccupancyEvent) -> float:
    if event.occupancy_behavior == "transient":
        return 0.25
    if event.occupancy_behavior == "ambiguous":
        return 0.55
    if event.occupancy_behavior == "sticky":
        return 0.85 if event.signal_type == "still_target" else 0.80
    if event.occupancy_behavior == "sustained":
        return 0.70
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


def reason_for_sustained_event(
    event: OccupancyEvent, confidence: float, refreshed_at: datetime
) -> str:
    status = status_for_confidence(confidence)
    active_minutes = max(0, int((refreshed_at - event.event_at).total_seconds() // 60))
    return (
        f"{event.signal_type} active at {event.node_id} for {active_minutes} min; "
        f"{event.occupancy_behavior} confidence is {status}"
    )
