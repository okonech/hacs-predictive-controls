from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .events import OccupancyEvent

CONFIDENCE_STATUSES = ("rejected", "suspect", "possible", "probable", "confirmed")


class ZoneStateView(Protocol):
    @property
    def zone(self) -> str: ...

    @property
    def confidence(self) -> float: ...

    @property
    def occupancy_behavior(self) -> str: ...


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


def event_confidence(current_confidence: float, event: OccupancyEvent) -> float:
    if event.state == "off":
        return round(current_confidence * clear_factor_for_event(event), 3)

    floor = on_confidence_floor(event)
    if current_confidence < floor:
        return floor
    return min(1.0, round(current_confidence + 0.08 * event.reliability, 3))


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


def passive_decay_half_life_seconds(occupancy_behavior: str) -> float:
    return {
        "transient": 90.0,
        "ambiguous": 300.0,
        "sustained": 900.0,
        "sticky": 1800.0,
    }.get(occupancy_behavior, 600.0)


def passive_confidence_for_duration(
    occupancy_behavior: str,
    inactive_for: timedelta,
    current_confidence: float,
    half_life_seconds: float | None = None,
) -> float:
    seconds = max(0.0, inactive_for.total_seconds())
    if seconds == 0 or current_confidence <= 0:
        return current_confidence
    half_life = half_life_seconds or passive_decay_half_life_seconds(occupancy_behavior)
    confidence = current_confidence * (0.5 ** (seconds / half_life))
    return 0.0 if confidence < 0.01 else round(confidence, 3)


def conflict_confidence(current_confidence: float) -> float:
    confidence = current_confidence * 0.35
    return 0.0 if confidence < 0.01 else round(confidence, 3)


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


def reason_for_inactive_decay(
    previous: ZoneStateView, confidence: float, inactive_for: timedelta
) -> str:
    status = status_for_confidence(confidence)
    inactive_minutes = max(0, int(inactive_for.total_seconds() // 60))
    return (
        f"inactive for {inactive_minutes} min; "
        f"{previous.occupancy_behavior} confidence decayed to {status}"
    )


def reason_for_conflict_decay(
    previous: ZoneStateView, confidence: float, protected_tracks: tuple[str, ...]
) -> str:
    status = status_for_confidence(confidence)
    tracks = ", ".join(protected_tracks)
    return (
        f"competed with stronger occupied tracks ({tracks}); "
        f"confidence decayed to {status}"
    )


def reason_for_departure_decay(
    previous: ZoneStateView,
    confidence: float,
    via_zone: str,
    destination_zone: str,
) -> str:
    status = status_for_confidence(confidence)
    return (
        f"departure inferred via {via_zone} toward {destination_zone}; "
        f"confidence decayed to {status}"
    )


def reason_for_clear_transition_decay(
    previous: ZoneStateView,
    confidence: float,
    via_zone: str,
    destination_zone: str,
) -> str:
    status = status_for_confidence(confidence)
    return (
        f"cleared after adjacent transition via {via_zone} while "
        f"{destination_zone} had stronger active evidence; "
        f"confidence decayed to {status}"
    )
