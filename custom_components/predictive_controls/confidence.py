from __future__ import annotations

from .markov import MarkovChain
from .model import PredictiveMap
from .occupancy_tracker import OccupancyTracker, TrackerConfig, ZoneState, ZoneUpdate

CONFIDENCE_STATUSES = (
    "rejected",
    "suspect",
    "possible",
    "probable",
    "confirmed",
)


class ZoneConfidenceEngine(OccupancyTracker):
    """Runtime facade for authoritative graph-local zone belief."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        expected_occupants: int | None = None,
        chain: MarkovChain | None = None,
        **_legacy_options: object,
    ) -> None:
        super().__init__(
            predictive_map,
            config=TrackerConfig(expected_occupants or 0),
            chain=chain,
        )


__all__ = [
    "CONFIDENCE_STATUSES",
    "OccupancyTracker",
    "TrackerConfig",
    "ZoneConfidenceEngine",
    "ZoneState",
    "ZoneUpdate",
]
