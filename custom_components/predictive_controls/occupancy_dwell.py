from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .occupancy_scoring import passive_decay_half_life_seconds


@dataclass(frozen=True)
class DwellStats:
    """Learned dwell-time summary for one occupancy zone."""

    samples: int = 0
    average_seconds: float = 0.0

    def learn(self, duration: timedelta) -> DwellStats:
        seconds = max(0.0, duration.total_seconds())
        if seconds <= 0:
            return self
        total = self.average_seconds * self.samples + seconds
        samples = self.samples + 1
        return DwellStats(samples=samples, average_seconds=round(total / samples, 3))


class DwellTimeModel:
    """Learns how long zones usually remain occupied after evidence appears."""

    def __init__(self, minimum_samples: int = 2) -> None:
        self.minimum_samples = minimum_samples
        self._stats: dict[str, DwellStats] = {}

    @property
    def stats(self) -> dict[str, DwellStats]:
        return self._stats.copy()

    def learn(self, zone: str, duration: timedelta) -> None:
        self._stats[zone] = self._stats.get(zone, DwellStats()).learn(duration)

    def average_seconds(self, zone: str) -> float | None:
        stats = self._stats.get(zone)
        if stats is None or stats.samples < self.minimum_samples:
            return None
        return stats.average_seconds

    def passive_half_life_seconds(self, zone: str, occupancy_behavior: str) -> float:
        default_half_life = passive_decay_half_life_seconds(occupancy_behavior)
        learned_average = self.average_seconds(zone)
        if learned_average is None:
            return default_half_life
        return max(default_half_life, learned_average / 2)

    def payload(self) -> dict[str, dict[str, float | int]]:
        return {
            zone: {
                "samples": stats.samples,
                "average_seconds": stats.average_seconds,
            }
            for zone, stats in self._stats.items()
        }
