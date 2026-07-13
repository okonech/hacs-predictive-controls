from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .model import PredictiveMap


@dataclass(frozen=True)
class RouteMatch:
    """One deterministic variable-order route lookup result."""

    matched_prefix: tuple[str, ...]
    support: float
    backoff_level: int
    probabilities: Mapping[str, float]


class RouteModel:
    """Bounded anonymous route-prefix counts over graph-valid node paths."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        *,
        max_order: int = 4,
        minimum_support: float = 2.0,
        max_prefixes: int = 256,
        max_count: float = 64.0,
        decay: float = 0.995,
        maximum_boost: float = 0.25,
    ) -> None:
        if max_order < 2:
            raise ValueError("max_order must be at least two")
        if minimum_support <= 0.0:
            raise ValueError("minimum_support must be positive")
        if max_prefixes < 1:
            raise ValueError("max_prefixes must be positive")
        if max_count <= 0.0:
            raise ValueError("max_count must be positive")
        if not 0.0 < decay <= 1.0:
            raise ValueError("decay must be in the interval (0, 1]")
        if not 0.0 <= maximum_boost <= 1.0:
            raise ValueError("maximum_boost must be in the interval [0, 1]")
        self.map = predictive_map
        self.max_order = max_order
        self.minimum_support = minimum_support
        self.max_prefixes = max_prefixes
        self.max_count = max_count
        self.decay = decay
        self.maximum_boost = maximum_boost
        self._counts: dict[tuple[str, ...], dict[str, float]] = {}

    @property
    def counts(self) -> dict[tuple[str, ...], dict[str, float]]:
        return {
            prefix: self._counts[prefix].copy() for prefix in sorted(self._counts)
        }

    def observe(
        self,
        history: tuple[str, ...],
        target: str,
        *,
        weight: float,
    ) -> bool:
        """Discount old statistics and learn suffix prefixes for one edge."""

        if weight <= 0.0:
            raise ValueError("weight must be positive")
        source = self.map.nodes.get(history[-1]) if history else None
        if source is None or target not in source.adjacent:
            return False
        self._discount()
        learned = False
        for order in range(2, min(self.max_order, len(history)) + 1):
            prefix = history[-order:]
            if not self._valid_prefix(prefix):
                continue
            targets = self._counts.setdefault(prefix, {})
            targets[target] = min(
                self.max_count,
                targets.get(target, 0.0) + weight,
            )
            learned = True
        self._bound_prefixes()
        return learned

    def match(
        self,
        history: tuple[str, ...],
        candidates: tuple[str, ...],
    ) -> RouteMatch:
        """Use the longest promoted suffix and deterministically back off."""

        available_order = min(self.max_order, len(history))
        candidate_set = set(candidates)
        for order in range(available_order, 1, -1):
            prefix = history[-order:]
            targets = self._counts.get(prefix, {})
            eligible = {
                target: count
                for target, count in targets.items()
                if target in candidate_set and count > 0.0
            }
            support = math.fsum(eligible.values())
            if support < self.minimum_support:
                continue
            return RouteMatch(
                matched_prefix=prefix,
                support=support,
                backoff_level=available_order - order,
                probabilities={
                    target: eligible[target] / support for target in sorted(eligible)
                },
            )
        return RouteMatch(
            matched_prefix=(),
            support=0.0,
            backoff_level=max(0, available_order - 1),
            probabilities={},
        )

    def restore_counts(
        self,
        counts: Mapping[tuple[str, ...], Mapping[str, float]],
    ) -> None:
        """Restore only bounded graph-valid route statistics."""

        restored: dict[tuple[str, ...], dict[str, float]] = {}
        for prefix, targets in sorted(counts.items()):
            if not self._valid_prefix(prefix):
                continue
            valid_targets = {
                target: min(self.max_count, float(count))
                for target, count in sorted(targets.items())
                if target in self.map.nodes[prefix[-1]].adjacent
                and isinstance(count, int | float)
                and math.isfinite(count)
                and count > 0.0
            }
            if valid_targets:
                restored[prefix] = valid_targets
        self._counts = restored
        self._bound_prefixes()

    def _valid_prefix(self, prefix: tuple[str, ...]) -> bool:
        return (
            2 <= len(prefix) <= self.max_order
            and all(node_id in self.map.nodes for node_id in prefix)
            and all(
                target in self.map.nodes[source].adjacent
                for source, target in zip(prefix, prefix[1:], strict=False)
            )
        )

    def _discount(self) -> None:
        if self.decay == 1.0:
            return
        for prefix, targets in tuple(self._counts.items()):
            discounted = {
                target: count * self.decay
                for target, count in targets.items()
                if count * self.decay >= 1e-6
            }
            if discounted:
                self._counts[prefix] = discounted
            else:
                del self._counts[prefix]

    def _bound_prefixes(self) -> None:
        while len(self._counts) > self.max_prefixes:
            evicted = min(
                self._counts,
                key=lambda prefix: (
                    math.fsum(self._counts[prefix].values()),
                    prefix,
                ),
            )
            del self._counts[evicted]
