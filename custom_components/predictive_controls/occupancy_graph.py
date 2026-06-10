from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from .model import PredictiveMap


@dataclass(frozen=True)
class ZoneGraph:
    """Zone-level graph derived from the configured sensor adjacency map."""

    neighbors_by_zone: dict[str, frozenset[str]]

    @classmethod
    def from_map(cls, predictive_map: PredictiveMap) -> ZoneGraph:
        neighbors = {zone: set[str]() for zone in predictive_map.zones()}
        for source in predictive_map.nodes.values():
            source_zone = source.occupancy_zone
            neighbors.setdefault(source_zone, set())
            for target_id in source.adjacent:
                target = predictive_map.nodes.get(target_id)
                if target is None or target.occupancy_zone == source_zone:
                    continue
                target_zone = target.occupancy_zone
                neighbors.setdefault(target_zone, set())
                neighbors[source_zone].add(target_zone)
                neighbors[target_zone].add(source_zone)
        return cls(
            {
                zone: frozenset(sorted(zone_neighbors))
                for zone, zone_neighbors in neighbors.items()
            }
        )

    def zones(self) -> tuple[str, ...]:
        return tuple(sorted(self.neighbors_by_zone))

    def neighbors(self, zone: str) -> frozenset[str]:
        return self.neighbors_by_zone.get(zone, frozenset())

    def movement_corridor(
        self, zones: Iterable[str], radius: int = 1
    ) -> frozenset[str]:
        """Return zones close enough to explain movement around active tracks."""

        protected: set[str] = set()
        frontier = deque((zone, 0) for zone in zones)
        while frontier:
            zone, distance = frontier.popleft()
            if zone in protected or distance > radius:
                continue
            protected.add(zone)
            if distance == radius:
                continue
            for neighbor in self.neighbors(zone):
                frontier.append((neighbor, distance + 1))
        return frozenset(protected)

    def distance(
        self, source: str, target: str, max_depth: int | None = None
    ) -> int | None:
        """Return the shortest zone distance, or None when no path is known."""

        if source == target:
            return 0
        if source not in self.neighbors_by_zone or target not in self.neighbors_by_zone:
            return None

        seen = {source}
        frontier = deque([(source, 0)])
        while frontier:
            zone, distance = frontier.popleft()
            if max_depth is not None and distance >= max_depth:
                continue
            for neighbor in self.neighbors(zone):
                if neighbor == target:
                    return distance + 1
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append((neighbor, distance + 1))
        return None
