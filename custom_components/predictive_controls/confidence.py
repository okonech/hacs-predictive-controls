from __future__ import annotations

from .model import PredictiveMap
from .occupancy_scoring import (
    CONFIDENCE_STATUSES,
    clear_factor_for_event,
    conflict_confidence,
    on_confidence_floor,
    passive_confidence_for_duration,
    reason_for_clear_transition_decay,
    reason_for_conflict_decay,
    reason_for_departure_decay,
    reason_for_event,
    reason_for_inactive_decay,
    reason_for_sustained_event,
    status_for_confidence,
    sustained_cap_for_event,
    sustained_confidence_for_duration,
    sustained_ramp_seconds,
)
from .occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
    ZoneState,
    ZoneUpdate,
)


class ZoneConfidenceEngine(OccupancyTracker):
    """Compatibility facade for the occupancy tracker used by runtime code."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        expected_occupants: int | None = None,
    ) -> None:
        config = TrackerConfig(expected_occupants=expected_occupants or 0)
        super().__init__(predictive_map, config=config)


__all__ = [
    "CONFIDENCE_STATUSES",
    "OccupancyTracker",
    "TrackerConfig",
    "ZoneConfidenceEngine",
    "ZoneState",
    "ZoneUpdate",
    "clear_factor_for_event",
    "conflict_confidence",
    "on_confidence_floor",
    "passive_confidence_for_duration",
    "reason_for_clear_transition_decay",
    "reason_for_conflict_decay",
    "reason_for_departure_decay",
    "reason_for_event",
    "reason_for_inactive_decay",
    "reason_for_sustained_event",
    "status_for_confidence",
    "sustained_cap_for_event",
    "sustained_confidence_for_duration",
    "sustained_ramp_seconds",
]
