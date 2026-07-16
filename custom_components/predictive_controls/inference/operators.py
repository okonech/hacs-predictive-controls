"""Complete indexed one-occupant transition operators."""

from __future__ import annotations

import math
from array import array
from collections.abc import Mapping
from dataclasses import dataclass

from .state_space import CompactLogPosterior, CompactPosterior, StateSpace


@dataclass(frozen=True)
class OneOccupantMoveOperator:
    """Indexed successors for moving one anonymous occupant between locations."""

    source_index: int
    target_index: int
    successors: array[int]
    source_multiplicities: array[int]

    @classmethod
    def build(
        cls,
        space: StateSpace,
        source_index: int,
        target_index: int,
    ) -> OneOccupantMoveOperator:
        if not 0 <= source_index < len(space.locations):
            raise IndexError("Source location index is out of range")
        if not 0 <= target_index < len(space.locations):
            raise IndexError("Target location index is out of range")
        if source_index == target_index:
            raise ValueError("Move source and target must differ")
        successors = array("i", [-1]) * len(space)
        multiplicities = array("B", [0]) * len(space)
        for rank, configuration in enumerate(space.configurations):
            source_count = configuration[source_index]
            multiplicities[rank] = source_count
            if source_count == 0:
                continue
            successor = list(configuration)
            successor[source_index] -= 1
            successor[target_index] += 1
            successors[rank] = space.rank(successor)
        return cls(
            source_index,
            target_index,
            successors,
            multiplicities,
        )

    @property
    def storage_bytes(self) -> int:
        return (
            self.successors.buffer_info()[1] * self.successors.itemsize
            + self.source_multiplicities.buffer_info()[1]
            * self.source_multiplicities.itemsize
        )


class CompleteMoveOperators:
    """All ordered one-occupant moves for one exact state space."""

    __slots__ = ("_operators", "space")

    def __init__(self, space: StateSpace) -> None:
        self.space = space
        self._operators = {
            (source_index, target_index): OneOccupantMoveOperator.build(
                space,
                source_index,
                target_index,
            )
            for source_index in range(len(space.locations))
            for target_index in range(len(space.locations))
            if source_index != target_index
        }

    def __len__(self) -> int:
        return len(self._operators)

    @property
    def storage_bytes(self) -> int:
        return sum(operator.storage_bytes for operator in self._operators.values())

    def operator(
        self,
        source_index: int,
        target_index: int,
    ) -> OneOccupantMoveOperator:
        try:
            return self._operators[(source_index, target_index)]
        except KeyError as exc:
            raise KeyError(
                f"No move operator for {source_index} -> {target_index}"
            ) from exc

    def transition(
        self,
        posterior: CompactPosterior,
        move_weights: Mapping[tuple[int, int], float],
        *,
        stay_weight: float = 1.0,
    ) -> CompactPosterior:
        if posterior.space is not self.space:
            raise ValueError("Posterior and operators must share a state space")
        if not math.isfinite(stay_weight) or stay_weight < 0.0:
            raise ValueError("Stay weight must be finite and non-negative")
        weighted_operators: list[tuple[OneOccupantMoveOperator, float]] = []
        for move, weight in move_weights.items():
            if not math.isfinite(weight) or weight < 0.0:
                raise ValueError("Move weights must be finite and non-negative")
            if weight > 0.0:
                weighted_operators.append((self.operator(*move), weight))
        output = array("d", [0.0]) * len(self.space)
        for predecessor_rank, predecessor_probability in enumerate(posterior):
            if predecessor_probability == 0.0:
                continue
            output[predecessor_rank] += predecessor_probability * stay_weight
            for operator, weight in weighted_operators:
                successor_rank = operator.successors[predecessor_rank]
                if successor_rank < 0:
                    continue
                output[successor_rank] += (
                    predecessor_probability
                    * weight
                    * operator.source_multiplicities[predecessor_rank]
                )
        return CompactPosterior(self.space, output)

    def transition_log(
        self,
        posterior: CompactLogPosterior,
        move_log_weights: Mapping[tuple[int, int], float],
        *,
        stay_log_weight: float = 0.0,
    ) -> CompactLogPosterior:
        if posterior.space is not self.space:
            raise ValueError("Posterior and operators must share a state space")
        if math.isnan(stay_log_weight) or stay_log_weight == math.inf:
            raise ValueError("Stay log weight must be finite or negative infinity")
        weighted_operators: list[tuple[OneOccupantMoveOperator, float]] = []
        for move, log_weight in move_log_weights.items():
            if math.isnan(log_weight) or log_weight == math.inf:
                raise ValueError("Move log weights must be finite or negative infinity")
            if log_weight != -math.inf:
                weighted_operators.append((self.operator(*move), log_weight))
        output = array("d", [-math.inf]) * len(self.space)
        for predecessor_rank, predecessor_log_probability in enumerate(posterior):
            if predecessor_log_probability == -math.inf:
                continue
            if stay_log_weight != -math.inf:
                output[predecessor_rank] = _logaddexp(
                    output[predecessor_rank],
                    predecessor_log_probability + stay_log_weight,
                )
            for operator, log_weight in weighted_operators:
                successor_rank = operator.successors[predecessor_rank]
                if successor_rank < 0:
                    continue
                output[successor_rank] = _logaddexp(
                    output[successor_rank],
                    predecessor_log_probability
                    + log_weight
                    + math.log(operator.source_multiplicities[predecessor_rank]),
                )
        return CompactLogPosterior(self.space, output)


def _logaddexp(first: float, second: float) -> float:
    if first == -math.inf:
        return second
    maximum = max(first, second)
    return maximum + math.log(math.exp(first - maximum) + math.exp(second - maximum))
