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
    activation_plausible: bool
    keep_on: bool
    prelight_plausible: bool
    diagnostic_entry_path_plausible: bool
    prediction_probability: float


@dataclass(frozen=True)
class AutomationSummary:
    """Stable automation contract derived from target diagnostics."""

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
    """Build the public summary directly from zone-belief state."""

    diagnostics = runtime.confidence.diagnostics
    beliefs = dict(diagnostics.beliefs)
    policies = dict(diagnostics.policy_states)
    predictions = dict(diagnostics.prediction_probabilities)
    authorized = {
        item.target_zone for item in diagnostics.authorizations if item.authorized
    }
    boundary = {
        item.target_zone
        for item in diagnostics.authorizations
        if item.authorized and item.reason == "boundary_reacquisition"
    }
    zones = {
        zone: _zone_state(
            zone,
            beliefs.get(zone, 0.0),
            policies.get(zone),
            predictions.get(zone, 0.0),
            zone in authorized,
            zone in boundary,
            prediction_threshold,
        )
        for zone in runtime.map.zones()
    }
    probable = tuple(zone for zone, state in zones.items() if state.probable_occupancy)
    possible = tuple(zone for zone, state in zones.items() if state.possible_occupancy)
    active = tuple(zone for zone, state in zones.items() if state.keep_on)
    prelight = tuple(zone for zone, state in zones.items() if state.prelight_plausible)
    top_zone, top_probability = _top_prediction(predictions)
    return AutomationSummary(
        expected_inside_count=int(runtime.expected_occupants or 0),
        probable_inside_count=len(probable),
        possible_inside_count=len(possible),
        probable_occupied_zones=probable,
        possible_occupied_zones=possible,
        activation_plausible_zones=tuple(
            zone for zone, state in zones.items() if state.activation_plausible
        ),
        keep_on_zones=active,
        diagnostic_entry_path_plausible_zones=tuple(sorted(boundary)),
        active_movement_corridor=tuple(
            sorted({token.zone for token in diagnostics.traversal_tokens})
        ),
        prelight_plausible_zones=prelight,
        diagnostic_predicted_next_zone=top_zone,
        diagnostic_predicted_next_probability=top_probability,
        explanation=_explanation(probable, top_zone, top_probability),
        zones=zones,
    )


def _zone_state(
    zone: str,
    confidence: float,
    policy: object | None,
    prediction_probability: float,
    activation_plausible: bool,
    boundary_plausible: bool,
    prediction_threshold: float,
) -> ZoneAutomationState:
    status = _status(confidence)
    return ZoneAutomationState(
        zone=zone,
        confidence=confidence,
        status=status,
        probable_occupancy=status in PROBABLE_STATUSES,
        possible_occupancy=status in POSSIBLE_STATUSES,
        activation_plausible=activation_plausible,
        keep_on=bool(getattr(policy, "active", False)),
        prelight_plausible=prediction_probability >= prediction_threshold,
        diagnostic_entry_path_plausible=boundary_plausible,
        prediction_probability=prediction_probability,
    )


def _top_prediction(
    prediction_hints: dict[str, float],
) -> tuple[str | None, float | None]:
    if not prediction_hints:
        return None, None
    zone, probability = max(
        prediction_hints.items(), key=lambda item: (item[1], item[0])
    )
    return zone, float(probability)


def _explanation(
    probable_zones: tuple[str, ...],
    predicted_zone: str | None,
    predicted_probability: float | None,
) -> str:
    if probable_zones:
        labels = ", ".join(_label(zone) for zone in probable_zones[:3])
        suffix = "" if len(probable_zones) <= 3 else f" +{len(probable_zones) - 3} more"
        occupancy = f"Probably occupied: {labels}{suffix}."
    else:
        occupancy = "No zones are probably occupied."
    if predicted_zone is None or predicted_probability is None:
        return occupancy
    return (
        f"{occupancy} Next likely zone: {_label(predicted_zone)} "
        f"({round(predicted_probability * 100)}%)."
    )


def _label(zone: str) -> str:
    return zone.replace("_", " ").title()


def _status(confidence: float) -> str:
    if confidence >= 0.85:
        return "confirmed"
    if confidence >= PROBABLE_CONFIDENCE:
        return "probable"
    if confidence >= POSSIBLE_CONFIDENCE:
        return "possible"
    if confidence > 0.0:
        return "suspect"
    return "rejected"
