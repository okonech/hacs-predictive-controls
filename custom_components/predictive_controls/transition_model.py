from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import datetime

from .model import PredictiveMap
from .occupancy_graph import ZoneGraph
from .occupancy_state import (
    HypothesisKey,
    PositionState,
    Posterior,
    canonical_hypothesis,
    hypothesis_sort_key,
    log_sum_exp,
)


@dataclass(frozen=True)
class PositionTransition:
    """One weighted successor for an anonymous position."""

    position: PositionState
    log_probability: float
    movement: tuple[str, str] | None


@dataclass(frozen=True)
class TransitionPath:
    """One predecessor-specific path into a canonical joint configuration."""

    key: HypothesisKey
    log_probability: float
    movements: tuple[tuple[str, str], ...]
    predecessor_key: HypothesisKey | None = None


class TransitionModel:
    """Enumerate exact graph-constrained successors for a small joint state."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        *,
        missed_movement_probability: float = 0.01,
    ) -> None:
        if not 0.0 <= missed_movement_probability < 1.0:
            raise ValueError("missed_movement_probability must be in [0, 1)")
        self.map = predictive_map
        self.graph = ZoneGraph.from_map(predictive_map)
        self.missed_movement_probability = missed_movement_probability

    def propagate(
        self,
        posterior: Posterior,
        event_at: datetime,
        observed_zone: str,
    ) -> tuple[TransitionPath, ...]:
        """Enumerate all path-distinct successors in deterministic order."""

        paths: list[TransitionPath] = []
        for hypothesis in posterior.hypotheses:
            option_sets = tuple(
                self._position_options(position, observed_zone, event_at)
                for position in hypothesis.key.positions
            )
            predecessor_paths: list[TransitionPath] = []
            for combination in itertools.product(*option_sets):
                movements = tuple(
                    sorted(
                        transition.movement
                        for transition in combination
                        if transition.movement is not None
                    )
                )
                if len(movements) > 1:
                    continue
                predecessor_paths.append(
                    TransitionPath(
                        key=canonical_hypothesis(
                            transition.position for transition in combination
                        ),
                        log_probability=hypothesis.log_probability
                        + sum(transition.log_probability for transition in combination),
                        movements=movements,
                    )
                )
            total = log_sum_exp(path.log_probability for path in predecessor_paths)
            paths.extend(
                TransitionPath(
                    path.key,
                    path.log_probability - total + hypothesis.log_probability,
                    path.movements,
                )
                for path in predecessor_paths
            )
        return tuple(
            sorted(
                paths,
                key=lambda path: (
                    -path.log_probability,
                    hypothesis_sort_key(path.key),
                    path.movements,
                ),
            )
        )

    def _position_options(
        self,
        position: PositionState,
        observed_zone: str,
        event_at: datetime,
    ) -> tuple[PositionTransition, ...]:
        if position.zone is None:
            return _normalize_options(
                (
                    (PositionState(None), 0.35, None),
                    (PositionState(observed_zone, None, event_at), 0.65, None),
                )
            )

        current_zone = position.zone
        neighbors = tuple(sorted(self.graph.neighbors(current_zone)))
        raw: list[tuple[PositionState, float, tuple[str, str] | None]] = [
            (position, 0.70, None),
            (PositionState(None), 0.05, None),
        ]
        if neighbors:
            adjacent_weight = 0.24 / len(neighbors)
            raw.extend(
                (
                    PositionState(neighbor, current_zone, event_at),
                    adjacent_weight,
                    (current_zone, neighbor),
                )
                for neighbor in neighbors
            )
        else:
            raw[0] = (position, 0.94, None)

        if observed_zone != current_zone and observed_zone not in neighbors:
            raw.append(
                (
                    PositionState(observed_zone, current_zone, event_at),
                    self.missed_movement_probability,
                    (current_zone, observed_zone),
                )
            )
        return _normalize_options(tuple(raw))


def _normalize_options(
    raw: tuple[tuple[PositionState, float, tuple[str, str] | None], ...],
) -> tuple[PositionTransition, ...]:
    total = sum(weight for _, weight, _ in raw)
    return tuple(
        PositionTransition(position, math.log(weight / total), movement)
        for position, weight, movement in raw
    )
