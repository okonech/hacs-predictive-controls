from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .model import PredictiveMap

MARKOV_COUNT_LIMIT = 1_000_000.0


@dataclass(frozen=True)
class Prediction:
    """One Markov prediction."""

    node_id: str
    probability: float


class MarkovChain:
    """First-order Markov chain constrained by a predictive node graph."""

    def __init__(self, predictive_map: PredictiveMap, smoothing: float = 1.0) -> None:
        if smoothing < 0:
            raise ValueError("smoothing must be non-negative")
        self._map = predictive_map
        self._smoothing = smoothing
        self._counts: dict[str, dict[str, float]] = {
            source: dict.fromkeys(node.adjacent, 0.0)
            for source, node in predictive_map.nodes.items()
        }

    @property
    def counts(self) -> dict[str, dict[str, float]]:
        return {source: targets.copy() for source, targets in self._counts.items()}

    def restore_counts(self, counts: Mapping[str, Mapping[str, object]]) -> None:
        for source, targets in counts.items():
            if source not in self._counts:
                continue
            for target, count in targets.items():
                if target not in self._counts[source]:
                    continue
                if not isinstance(count, int | float | str):
                    continue
                try:
                    parsed_count = float(count)
                except (TypeError, ValueError):
                    continue
                if (
                    math.isfinite(parsed_count)
                    and 0 <= parsed_count <= MARKOV_COUNT_LIMIT
                ):
                    self._counts[source][target] = parsed_count

    def observe(self, source: str, target: str, weight: float = 1.0) -> bool:
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("weight must be finite and positive")
        if target not in self._counts.get(source, {}):
            return False
        self._counts[source][target] = min(
            MARKOV_COUNT_LIMIT,
            self._counts[source][target] + weight,
        )
        return True

    def probabilities(self, source: str) -> dict[str, float]:
        targets = self._counts.get(source)
        if not targets:
            return {}

        weighted = {
            target: count
            + self._smoothing * self._map.nodes[target].route_prior_weight
            for target, count in targets.items()
        }
        total = sum(weighted.values())
        if total == 0:
            equal_probability = 1.0 / len(weighted)
            return dict.fromkeys(weighted, equal_probability)

        return {target: value / total for target, value in weighted.items()}

    def predict(
        self, distribution: Mapping[str, float], horizon: int = 1
    ) -> dict[str, float]:
        if horizon < 1:
            raise ValueError("horizon must be at least 1")

        current = self._normalize_distribution(distribution)
        for _ in range(horizon):
            current = self._step(current)
        return current

    def top_prediction(
        self, distribution: Mapping[str, float], horizon: int = 1
    ) -> Prediction | None:
        probabilities = self.predict(distribution, horizon=horizon)
        if not probabilities:
            return None
        node_id, probability = max(probabilities.items(), key=lambda item: item[1])
        return Prediction(node_id=node_id, probability=probability)

    @staticmethod
    def _normalize_distribution(distribution: Mapping[str, float]) -> dict[str, float]:
        filtered = {node: value for node, value in distribution.items() if value > 0}
        total = sum(filtered.values())
        if total == 0:
            return {}
        return {node: value / total for node, value in filtered.items()}

    def _step(self, distribution: Mapping[str, float]) -> dict[str, float]:
        next_distribution: dict[str, float] = {}
        for source, source_probability in distribution.items():
            for target, target_probability in self.probabilities(source).items():
                next_distribution[target] = next_distribution.get(target, 0.0) + (
                    source_probability * target_probability
                )
        return self._normalize_distribution(next_distribution)
