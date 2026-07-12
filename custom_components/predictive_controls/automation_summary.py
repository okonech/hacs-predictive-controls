from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    activation_plausible: bool
    keep_on: bool
    prelight_plausible: bool
    diagnostic_entry_path_plausible: bool
    prediction_probability: float


@dataclass(frozen=True)
class AutomationSummary:
    """Stable automation contract derived from live occupancy diagnostics."""

    expected_inside_count: int
    probable_inside_count: int
    possible_inside_count: int
    probable_occupied_zones: tuple[str, ...]
    possible_occupied_zones: tuple[str, ...]
    activation_plausible_zones: tuple[str, ...]
    keep_on_zones: tuple[str, ...]
    diagnostic_entry_path_plausible_zones: tuple[str, ...]
    active_movement_corridor: tuple[str, ...]
    prelight_plausible_zones: tuple[str, ...]
    diagnostic_predicted_next_zone: str | None
    diagnostic_predicted_next_probability: float | None
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
    joint_authoritative = bool(getattr(diagnostics, "joint_posterior", ()))
    prediction_hints = dict(
        getattr(diagnostics, "joint_prediction_hints", {})
        if joint_authoritative
        else getattr(diagnostics, "prediction_hints", {})
    )
    joint_marginals = dict(
        getattr(diagnostics, "joint_occupied_marginals", {})
        if joint_authoritative
        else {}
    )
    joint_policy_states = dict(
        getattr(diagnostics, "joint_policy_states", {})
        if joint_authoritative
        else {}
    )
    movement_corridor = tuple(sorted(getattr(diagnostics, "protected_corridor", ())))
    entry_path_plausible_zones_from_diagnostics = _active_plausibility_zones(
        diagnostics,
        getattr(runtime, "last_occupancy_event", None),
        "entry_plausibilities",
    )
    activation_plausible_zones_from_diagnostics = _active_plausibility_zones(
        diagnostics,
        getattr(runtime, "last_occupancy_event", None),
        "activation_plausibilities",
    )
    departed_zones = {
        str(departure.zone)
        for departure in getattr(diagnostics, "inferred_departures", ())
    }
    zones = {
        zone: _zone_automation_state(
            zone,
            states.get(zone),
            prediction_hints.get(zone, 0.0),
            activation_plausible_zones_from_diagnostics,
            entry_path_plausible_zones_from_diagnostics,
            departed_zones,
            prediction_threshold,
            joint_marginals.get(zone),
            joint_policy_states.get(zone),
            getattr(getattr(runtime, "last_occupancy_event", None), "event_at", None),
        )
        for zone in zone_ids
    }
    probable_occupied_zones = tuple(
        zone for zone, state in zones.items() if state.probable_occupancy
    )
    possible_occupied_zones = tuple(
        zone for zone, state in zones.items() if state.possible_occupancy
    )
    activation_plausible_zones = tuple(
        zone for zone, state in zones.items() if state.activation_plausible
    )
    keep_on_zones = tuple(
        zone for zone, state in zones.items() if state.keep_on
    )
    diagnostic_entry_path_plausible_zones = tuple(
        zone for zone, state in zones.items() if state.diagnostic_entry_path_plausible
    )
    prelight_plausible_zones = tuple(
        zone for zone, state in zones.items() if state.prelight_plausible
    )
    diagnostic_predicted_next_zone, diagnostic_predicted_next_probability = (
        _top_prediction(prediction_hints)
    )
    return AutomationSummary(
        expected_inside_count=int(getattr(runtime, "expected_occupants", 0) or 0),
        probable_inside_count=(
            int(getattr(runtime, "expected_occupants", 0) or 0)
            if joint_authoritative
            else _track_count(diagnostics, PROBABLE_CONFIDENCE)
        ),
        possible_inside_count=(
            int(getattr(runtime, "expected_occupants", 0) or 0)
            if joint_authoritative
            else _track_count(diagnostics, POSSIBLE_CONFIDENCE)
        ),
        probable_occupied_zones=probable_occupied_zones,
        possible_occupied_zones=possible_occupied_zones,
        activation_plausible_zones=activation_plausible_zones,
        keep_on_zones=keep_on_zones,
        diagnostic_entry_path_plausible_zones=diagnostic_entry_path_plausible_zones,
        active_movement_corridor=movement_corridor,
        prelight_plausible_zones=prelight_plausible_zones,
        diagnostic_predicted_next_zone=diagnostic_predicted_next_zone,
        diagnostic_predicted_next_probability=diagnostic_predicted_next_probability,
        explanation=_explanation(
            probable_occupied_zones,
            diagnostic_predicted_next_zone,
            diagnostic_predicted_next_probability,
        ),
        zones=zones,
    )


def _zone_automation_state(
    zone: str,
    state: Any,
    prediction_probability: float,
    activation_plausible_zones: set[str],
    entry_path_plausible_zones: set[str],
    departed_zones: set[str],
    prediction_threshold: float,
    joint_marginal: float | None = None,
    joint_policy_state: Any = None,
    event_at: datetime | None = None,
) -> ZoneAutomationState:
    if joint_marginal is None:
        confidence = float(
            getattr(state, "confidence", 0.0) if state is not None else 0.0
        )
        status = str(
            getattr(state, "status", "rejected") if state is not None else "rejected"
        )
    else:
        confidence = float(joint_marginal)
        status = _joint_status(confidence)
    probable_occupancy = status in PROBABLE_STATUSES
    possible_occupancy = status in POSSIBLE_STATUSES
    prelight_plausible = prediction_probability >= prediction_threshold
    if joint_policy_state is None:
        keep_on = possible_occupancy and zone not in departed_zones
        activation_plausible = zone in activation_plausible_zones
    else:
        keep_on = bool(getattr(joint_policy_state, "keep_on", False))
        expires_at = getattr(joint_policy_state, "activation_expires_at", None)
        activation_plausible = bool(
            isinstance(expires_at, datetime)
            and (not isinstance(event_at, datetime) or expires_at > event_at)
        )
    diagnostic_entry_path_plausible = zone in entry_path_plausible_zones
    return ZoneAutomationState(
        zone=zone,
        confidence=confidence,
        status=status,
        probable_occupancy=probable_occupancy,
        possible_occupancy=possible_occupancy,
        activation_plausible=activation_plausible,
        keep_on=keep_on,
        prelight_plausible=prelight_plausible,
        diagnostic_entry_path_plausible=diagnostic_entry_path_plausible,
        prediction_probability=float(prediction_probability),
    )


def _active_plausibility_zones(
    diagnostics: Any,
    last_event: Any,
    attribute: str,
) -> set[str]:
    event_at = getattr(last_event, "event_at", None)
    zones: set[str] = set()
    for plausibility in getattr(diagnostics, attribute, ()):
        expires_at = getattr(plausibility, "expires_at", None)
        if isinstance(event_at, datetime) and isinstance(expires_at, datetime):
            if expires_at < event_at:
                continue
        zone = getattr(plausibility, "zone", None)
        if isinstance(zone, str):
            zones.add(zone)
    return zones


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


def _joint_status(confidence: float) -> str:
    if confidence >= 0.85:
        return "confirmed"
    if confidence >= PROBABLE_CONFIDENCE:
        return "probable"
    if confidence >= POSSIBLE_CONFIDENCE:
        return "possible"
    if confidence > 0.0:
        return "suspect"
    return "rejected"
