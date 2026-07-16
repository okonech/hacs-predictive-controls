"""Exact exchangeable authoritative occupant-count transition kernels."""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence

from .association import AugmentedLogMessage
from .state_space import (
    MAX_OCCUPANTS,
    CompactLogPosterior,
    CompactPosterior,
    StateSpace,
)
from .types import AugmentedStateKey, SupportEventAtom


def _normalized_weights(
    values: Sequence[float],
    expected_length: int,
    label: str,
) -> tuple[float, ...]:
    if len(values) != expected_length:
        raise ValueError(f"{label} dimension does not match locations")
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError(f"{label} must be finite and non-negative")
    total = math.fsum(values)
    if total <= 0.0:
        raise ValueError(f"{label} must contain positive weight")
    return tuple(value / total for value in values)


class CountTransitionKernel:
    """Apply exact one-person kernels between complete count state spaces."""

    @staticmethod
    def increase(
        posterior: CompactPosterior,
        arrival_prior: Sequence[float] | None = None,
    ) -> CompactPosterior:
        source = posterior.space
        if source.occupants >= MAX_OCCUPANTS:
            raise ValueError("Cannot increase beyond maximum supported count")
        target = StateSpace(source.zones, source.occupants + 1)
        if arrival_prior is None:
            arrival_prior = (0.0,) * len(source.zones) + (1.0,)
        normalized_prior = _normalized_weights(
            arrival_prior,
            len(source.locations),
            "Arrival prior",
        )
        output = array("d", [0.0]) * len(target)
        for configuration, probability in zip(
            source.configurations,
            posterior,
            strict=True,
        ):
            for location_index, location_probability in enumerate(normalized_prior):
                if location_probability == 0.0:
                    continue
                successor = list(configuration)
                successor[location_index] += 1
                output[target.rank(successor)] += probability * location_probability
        return CompactPosterior(target, output)

    @staticmethod
    def decrease(
        posterior: CompactPosterior,
        exit_weights: Sequence[float] | None = None,
    ) -> CompactPosterior:
        source = posterior.space
        if source.occupants == 0:
            raise ValueError("Cannot decrease an empty authoritative count")
        target = StateSpace(source.zones, source.occupants - 1)
        if exit_weights is None:
            exit_weights = (1.0,) * len(source.locations)
        weights = _normalized_weights(
            exit_weights,
            len(source.locations),
            "Exit weights",
        )
        output = array("d", [0.0]) * len(target)
        for configuration, probability in zip(
            source.configurations,
            posterior,
            strict=True,
        ):
            denominator = math.fsum(
                count * weight
                for count, weight in zip(configuration, weights, strict=True)
            )
            if denominator <= 0.0:
                raise ValueError(
                    "Exit weights exclude every occupied location in a predecessor"
                )
            for location_index, (count, weight) in enumerate(
                zip(configuration, weights, strict=True)
            ):
                if count == 0 or weight == 0.0:
                    continue
                successor = list(configuration)
                successor[location_index] -= 1
                output[target.rank(successor)] += (
                    probability * count * weight / denominator
                )
        return CompactPosterior(target, output)

    @classmethod
    def reconcile(
        cls,
        posterior: CompactPosterior,
        target_count: int,
        *,
        arrival_prior: Sequence[float] | None = None,
        exit_weights: Sequence[float] | None = None,
    ) -> CompactPosterior:
        if not 0 <= target_count <= MAX_OCCUPANTS:
            raise ValueError(f"Target count must be between 0 and {MAX_OCCUPANTS}")
        reconciled = posterior
        while reconciled.space.occupants < target_count:
            reconciled = cls.increase(reconciled, arrival_prior)
        while reconciled.space.occupants > target_count:
            reconciled = cls.decrease(reconciled, exit_weights)
        return reconciled


class LogCountTransitionKernel:
    """Log-domain equivalent of the exact exchangeable count kernels."""

    @staticmethod
    def increase(
        posterior: CompactLogPosterior,
        arrival_prior: Sequence[float] | None = None,
    ) -> CompactLogPosterior:
        source = posterior.space
        if source.occupants >= MAX_OCCUPANTS:
            raise ValueError("Cannot increase beyond maximum supported count")
        target = StateSpace(source.zones, source.occupants + 1)
        if arrival_prior is None:
            arrival_prior = (0.0,) * len(source.zones) + (1.0,)
        normalized_prior = _normalized_weights(
            arrival_prior,
            len(source.locations),
            "Arrival prior",
        )
        output = array("d", [-math.inf]) * len(target)
        for configuration, log_probability in zip(
            source.configurations,
            posterior,
            strict=True,
        ):
            if log_probability == -math.inf:
                continue
            for location_index, location_probability in enumerate(normalized_prior):
                if location_probability == 0.0:
                    continue
                successor = list(configuration)
                successor[location_index] += 1
                rank = target.rank(successor)
                output[rank] = _logaddexp(
                    output[rank],
                    log_probability + math.log(location_probability),
                )
        return CompactLogPosterior(target, output)

    @staticmethod
    def decrease(
        posterior: CompactLogPosterior,
        exit_weights: Sequence[float] | None = None,
    ) -> CompactLogPosterior:
        source = posterior.space
        if source.occupants == 0:
            raise ValueError("Cannot decrease an empty authoritative count")
        target = StateSpace(source.zones, source.occupants - 1)
        if exit_weights is None:
            exit_weights = (1.0,) * len(source.locations)
        weights = _normalized_weights(
            exit_weights,
            len(source.locations),
            "Exit weights",
        )
        output = array("d", [-math.inf]) * len(target)
        for configuration, log_probability in zip(
            source.configurations,
            posterior,
            strict=True,
        ):
            if log_probability == -math.inf:
                continue
            denominator = math.fsum(
                count * weight
                for count, weight in zip(configuration, weights, strict=True)
            )
            if denominator <= 0.0:
                raise ValueError(
                    "Exit weights exclude every occupied location in a predecessor"
                )
            for location_index, (count, weight) in enumerate(
                zip(configuration, weights, strict=True)
            ):
                if count == 0 or weight == 0.0:
                    continue
                successor = list(configuration)
                successor[location_index] -= 1
                rank = target.rank(successor)
                output[rank] = _logaddexp(
                    output[rank],
                    log_probability + math.log(count * weight / denominator),
                )
        return CompactLogPosterior(target, output)

    @classmethod
    def reconcile(
        cls,
        posterior: CompactLogPosterior,
        target_count: int,
        *,
        arrival_prior: Sequence[float] | None = None,
        exit_weights: Sequence[float] | None = None,
    ) -> CompactLogPosterior:
        if not 0 <= target_count <= MAX_OCCUPANTS:
            raise ValueError(f"Target count must be between 0 and {MAX_OCCUPANTS}")
        reconciled = posterior
        while reconciled.space.occupants < target_count:
            reconciled = cls.increase(reconciled, arrival_prior)
        while reconciled.space.occupants > target_count:
            reconciled = cls.decrease(reconciled, exit_weights)
        return reconciled

    @classmethod
    def reconcile_augmented(
        cls,
        message: AugmentedLogMessage,
        target_count: int,
        *,
        arrival_prior: Sequence[float] | None = None,
        exit_weights: Sequence[float] | None = None,
    ) -> AugmentedLogMessage:
        """Apply count kernels independently within each valid support stratum."""

        grouped: dict[tuple[SupportEventAtom, ...], dict[int, float]] = {}
        for key, log_mass in message.entries:
            ranks = grouped.setdefault(key.supports, {})
            ranks[key.occupancy_rank] = _logaddexp(
                ranks.get(key.occupancy_rank, -math.inf),
                log_mass,
            )

        output: list[tuple[AugmentedStateKey, float]] = []
        for supports, ranks in grouped.items():
            group_mass = _logsumexp(tuple(ranks.values()))
            posterior = CompactLogPosterior(
                message.space,
                (
                    ranks.get(rank, -math.inf) - group_mass
                    for rank in range(len(message.space))
                ),
            )
            reconciled = cls.reconcile(
                posterior,
                target_count,
                arrival_prior=arrival_prior,
                exit_weights=exit_weights,
            )
            output.extend(
                (
                    AugmentedStateKey(rank, supports=supports),
                    log_mass + group_mass,
                )
                for rank, log_mass in enumerate(reconciled)
                if log_mass != -math.inf
            )
        return AugmentedLogMessage(
            StateSpace(message.space.zones, target_count),
            output,
        )


def _logaddexp(first: float, second: float) -> float:
    if first == -math.inf:
        return second
    maximum = max(first, second)
    return maximum + math.log(math.exp(first - maximum) + math.exp(second - maximum))


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values, default=-math.inf)
    if maximum == -math.inf:
        return maximum
    return maximum + math.log(math.fsum(math.exp(value - maximum) for value in values))
