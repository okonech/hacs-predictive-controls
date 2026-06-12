from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POSSIBLE_STATUSES = frozenset({"possible", "probable", "confirmed"})
PROBABLE_STATUSES = frozenset({"probable", "confirmed"})
POSSIBLE_CONFIDENCE = 0.35
PROBABLE_CONFIDENCE = 0.60


@dataclass(frozen=True)
class ZoneAutomationState:
    """Automation-facing state for one configured occupancy zone."""

    zone: str
    confidence: float
    status: str
    probable_occupancy: bool
    possible_occupancy: bool
    motion_plausible: bool
    predicted_next: bool
    prediction_probability: float


@dataclass(frozen=True)
class AutomationSummary:
    """Stable automation contract derived from live occupancy diagnostics."""

    expected_inside_count: int
    probable_inside_count: int
    possible_inside_count: int
    probable_occupied_zones: tuple[str, ...]
    possible_occupied_zones: tuple[str, ...]
    motion_plausible_zones: tuple[str, ...]
    active_movement_corridor: tuple[str, ...]
    predicted_zones: tuple[str, ...]
    predicted_next_zone: str | None
    predicted_next_probability: float | None
    explanation: str
    zones: dict[str, ZoneAutomationState] = field(default_factory=dict)


def runtime_automation_summary(
    runtime: Any,
    prediction_threshold: float = PROBABLE_CONFIDENCE,
) -> AutomationSummary:
    """Build the automation-facing summary from a live runtime."""

    diagnostics = runtime.confidence.diagnostics
    zone_ids = tuple(runtime.map.zones())
    states = runtime.zone_states
    prediction_hints = dict(getattr(diagnostics, "prediction_hints", {}))
    movement_corridor = tuple(sorted(getattr(diagnostics, "protected_corridor", ())))
    movement_corridor_set = set(movement_corridor)
    zones = {
        zone: _zone_automation_state(
            zone,
            states.get(zone),
            prediction_hints.get(zone, 0.0),
            movement_corridor_set,
            prediction_threshold,
        )
        for zone in zone_ids
    }
    probable_occupied_zones = tuple(
        zone for zone, state in zones.items() if state.probable_occupancy
    )
    possible_occupied_zones = tuple(
        zone for zone, state in zones.items() if state.possible_occupancy
    )
    motion_plausible_zones = tuple(
        zone for zone, state in zones.items() if state.motion_plausible
    )
    predicted_zones = tuple(
        zone for zone, state in zones.items() if state.predicted_next
    )
    predicted_next_zone, predicted_next_probability = _top_prediction(prediction_hints)
    return AutomationSummary(
        expected_inside_count=int(getattr(runtime, "expected_occupants", 0) or 0),
        probable_inside_count=_track_count(diagnostics, PROBABLE_CONFIDENCE),
        possible_inside_count=_track_count(diagnostics, POSSIBLE_CONFIDENCE),
        probable_occupied_zones=probable_occupied_zones,
        possible_occupied_zones=possible_occupied_zones,
        motion_plausible_zones=motion_plausible_zones,
        active_movement_corridor=movement_corridor,
        predicted_zones=predicted_zones,
        predicted_next_zone=predicted_next_zone,
        predicted_next_probability=predicted_next_probability,
        explanation=_explanation(
            probable_occupied_zones,
            predicted_next_zone,
            predicted_next_probability,
        ),
        zones=zones,
    )


def _zone_automation_state(
    zone: str,
    state: Any,
    prediction_probability: float,
    movement_corridor: set[str],
    prediction_threshold: float,
) -> ZoneAutomationState:
    confidence = float(getattr(state, "confidence", 0.0) if state is not None else 0.0)
    status = str(
        getattr(state, "status", "rejected") if state is not None else "rejected"
    )
    probable_occupancy = status in PROBABLE_STATUSES
    possible_occupancy = status in POSSIBLE_STATUSES
    predicted_next = prediction_probability >= prediction_threshold
    return ZoneAutomationState(
        zone=zone,
        confidence=confidence,
        status=status,
        probable_occupancy=probable_occupancy,
        possible_occupancy=possible_occupancy,
        motion_plausible=(
            probable_occupancy or predicted_next or zone in movement_corridor
        ),
        predicted_next=predicted_next,
        prediction_probability=float(prediction_probability),
    )


def _track_count(diagnostics: Any, threshold: float) -> int:
    return sum(
        1
        for track in getattr(diagnostics, "tracks", ())
        if float(getattr(track, "confidence", 0.0)) >= threshold
    )


def _top_prediction(
    prediction_hints: dict[str, float],
) -> tuple[str | None, float | None]:
    if not prediction_hints:
        return None, None
    zone, probability = max(
        prediction_hints.items(),
        key=lambda item: (item[1], item[0]),
    )
    return zone, float(probability)


def _explanation(
    probable_zones: tuple[str, ...],
    predicted_zone: str | None,
    predicted_probability: float | None,
) -> str:
    parts: list[str] = []
    if probable_zones:
        labels = ", ".join(_label(zone) for zone in probable_zones[:3])
        suffix = "" if len(probable_zones) <= 3 else f" +{len(probable_zones) - 3} more"
        parts.append(f"Probably occupied: {labels}{suffix}.")
    else:
        parts.append("No zones are probably occupied.")
    if predicted_zone is not None and predicted_probability is not None:
        parts.append(
            f"Next likely zone: {_label(predicted_zone)} "
            f"({round(predicted_probability * 100)}%)."
        )
    return " ".join(parts)


def _label(zone: str) -> str:
    return zone.replace("_", " ").title()
