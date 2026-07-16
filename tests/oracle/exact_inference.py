"""Deliberately simple symbolic oracle for exact transition tests."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import product

CountVector = tuple[int, ...]
DecimalPosterior = dict[CountVector, Decimal]
DecimalEndpointKey = tuple[CountVector, CountVector, str]
DecimalAssignmentContext = tuple[str, CountVector, str]
DecimalAugmentedKey = tuple[CountVector, tuple[DecimalAssignmentContext, ...]]
DecimalProjectionRecord = tuple[int, tuple[str, ...], tuple[str, ...], Decimal]


def enumerate_configurations(
    location_count: int,
    occupants: int,
) -> tuple[CountVector, ...]:
    return tuple(
        candidate
        for candidate in product(range(occupants + 1), repeat=location_count)
        if sum(candidate) == occupants
    )


def transition(
    configurations: Sequence[CountVector],
    probabilities: Sequence[float],
    move_weights: Mapping[tuple[int, int], float],
    *,
    stay_weight: float,
) -> tuple[float, ...]:
    output = dict.fromkeys(configurations, 0.0)
    for configuration, probability in zip(
        configurations,
        probabilities,
        strict=True,
    ):
        output[configuration] += probability * stay_weight
        for (source_index, target_index), weight in move_weights.items():
            source_count = configuration[source_index]
            if source_count == 0:
                continue
            successor = list(configuration)
            successor[source_index] -= 1
            successor[target_index] += 1
            output[tuple(successor)] += probability * weight * source_count
    total = math.fsum(output.values())
    if total <= 0.0:
        raise ValueError("Oracle transition removed all probability mass")
    return tuple(output[configuration] / total for configuration in configurations)


def transition_decimal(
    posterior: Mapping[CountVector, Decimal],
    move_weights: Mapping[tuple[int, int], Decimal],
    *,
    stay_weight: Decimal,
) -> DecimalPosterior:
    output = dict.fromkeys(posterior, Decimal(0))
    for configuration, probability in posterior.items():
        output[configuration] += probability * stay_weight
        for (source_index, target_index), weight in move_weights.items():
            source_count = configuration[source_index]
            if source_count == 0 or weight == 0:
                continue
            successor = list(configuration)
            successor[source_index] -= 1
            successor[target_index] += 1
            key = tuple(successor)
            output[key] += probability * Decimal(source_count) * weight
    return _normalize_decimal(output)


def endpoint_factor_decimal(
    posterior: Mapping[CountVector, Decimal],
    target_index: int,
    alternatives: Sequence[tuple[str, int | None, Decimal]],
    *,
    empty_likelihood: Decimal,
    occupied_likelihood: Decimal,
) -> dict[DecimalEndpointKey, Decimal]:
    output: dict[DecimalEndpointKey, Decimal] = {}
    for predecessor, probability in posterior.items():
        for alternative_id, source_index, weight in alternatives:
            if weight == 0:
                continue
            if source_index is None:
                successor = predecessor
                multiplicity = 1
            else:
                multiplicity = predecessor[source_index]
                if multiplicity == 0:
                    continue
                successor_values = list(predecessor)
                successor_values[source_index] -= 1
                successor_values[target_index] += 1
                successor = tuple(successor_values)
            likelihood = (
                occupied_likelihood
                if successor[target_index] > 0
                else empty_likelihood
            )
            key = (successor, predecessor, alternative_id)
            output[key] = output.get(key, Decimal(0)) + (
                probability * Decimal(multiplicity) * weight * likelihood
            )
    total = sum(output.values(), Decimal(0))
    if total <= 0:
        raise ValueError("Decimal endpoint factor removed all probability mass")
    return {key: probability / total for key, probability in output.items()}


def augmented_endpoint_factor_decimal(
    posterior: Mapping[DecimalAugmentedKey, Decimal],
    endpoint_id: str,
    target_index: int,
    alternatives: Sequence[tuple[str, int | None, Decimal]],
    *,
    empty_likelihood: Decimal,
    occupied_likelihood: Decimal,
) -> dict[DecimalAugmentedKey, Decimal]:
    output: dict[DecimalAugmentedKey, Decimal] = {}
    for (predecessor, contexts), probability in posterior.items():
        for alternative_id, source_index, weight in alternatives:
            if weight == 0:
                continue
            if source_index is None:
                successor = predecessor
                multiplicity = 1
            else:
                multiplicity = predecessor[source_index]
                if multiplicity == 0:
                    continue
                successor_values = list(predecessor)
                successor_values[source_index] -= 1
                successor_values[target_index] += 1
                successor = tuple(successor_values)
            likelihood = (
                occupied_likelihood
                if successor[target_index] > 0
                else empty_likelihood
            )
            context = (endpoint_id, predecessor, alternative_id)
            key = (successor, tuple(sorted((*contexts, context))))
            output[key] = output.get(key, Decimal(0)) + (
                probability * Decimal(multiplicity) * weight * likelihood
            )
    total = sum(output.values(), Decimal(0))
    if total <= 0:
        raise ValueError("Decimal augmented endpoint factor removed all mass")
    return {key: probability / total for key, probability in output.items()}


def project_augmented_decimal(
    records: Sequence[DecimalProjectionRecord],
    expired_contexts: frozenset[str],
    replacements: Mapping[str, str | None],
) -> dict[tuple[int, tuple[str, ...], tuple[str, ...]], Decimal]:
    output: dict[tuple[int, tuple[str, ...], tuple[str, ...]], Decimal] = {}
    for occupancy_rank, contexts, supports, probability in records:
        retained = tuple(sorted(set(contexts) - expired_contexts))
        added_supports = tuple(
            replacement
            for context in contexts
            if context in expired_contexts
            for replacement in (replacements.get(context),)
            if replacement is not None
        )
        key = (
            occupancy_rank,
            retained,
            tuple(sorted((*supports, *added_supports))),
        )
        output[key] = output.get(key, Decimal(0)) + probability
    total = sum(output.values(), Decimal(0))
    return {key: probability / total for key, probability in output.items()}


def increase_count(
    configurations: Sequence[CountVector],
    probabilities: Sequence[float],
    arrival_prior: Sequence[float],
) -> tuple[tuple[CountVector, ...], tuple[float, ...]]:
    target = enumerate_configurations(
        len(configurations[0]),
        sum(configurations[0]) + 1,
    )
    output = dict.fromkeys(target, 0.0)
    prior_total = math.fsum(arrival_prior)
    for configuration, probability in zip(
        configurations,
        probabilities,
        strict=True,
    ):
        for location_index, weight in enumerate(arrival_prior):
            successor = list(configuration)
            successor[location_index] += 1
            output[tuple(successor)] += probability * weight / prior_total
    return target, tuple(output[configuration] for configuration in target)


def decrease_count(
    configurations: Sequence[CountVector],
    probabilities: Sequence[float],
    exit_weights: Sequence[float],
) -> tuple[tuple[CountVector, ...], tuple[float, ...]]:
    target = enumerate_configurations(
        len(configurations[0]),
        sum(configurations[0]) - 1,
    )
    output = dict.fromkeys(target, 0.0)
    for configuration, probability in zip(
        configurations,
        probabilities,
        strict=True,
    ):
        denominator = math.fsum(
            count * weight
            for count, weight in zip(configuration, exit_weights, strict=True)
        )
        for location_index, (count, weight) in enumerate(
            zip(configuration, exit_weights, strict=True)
        ):
            if count == 0:
                continue
            successor = list(configuration)
            successor[location_index] -= 1
            output[tuple(successor)] += probability * count * weight / denominator
    return target, tuple(output[configuration] for configuration in target)


def observe_decimal(
    posterior: Mapping[CountVector, Decimal],
    zone_index: int,
    empty_log_likelihood: float,
    occupied_log_likelihood: float,
) -> DecimalPosterior:
    empty = Decimal(str(empty_log_likelihood)).exp()
    occupied = Decimal(str(occupied_log_likelihood)).exp()
    weighted = {
        configuration: probability
        * (occupied if configuration[zone_index] > 0 else empty)
        for configuration, probability in posterior.items()
    }
    return _normalize_decimal(weighted)


def increase_count_decimal(
    posterior: Mapping[CountVector, Decimal],
    arrival_prior: Sequence[Decimal],
) -> DecimalPosterior:
    prior_total = sum(arrival_prior, Decimal(0))
    output: DecimalPosterior = {}
    for configuration, probability in posterior.items():
        for location_index, weight in enumerate(arrival_prior):
            successor = list(configuration)
            successor[location_index] += 1
            key = tuple(successor)
            output[key] = output.get(key, Decimal(0)) + (
                probability * weight / prior_total
            )
    return _normalize_decimal(output)


def decrease_count_decimal(
    posterior: Mapping[CountVector, Decimal],
    exit_weights: Sequence[Decimal],
) -> DecimalPosterior:
    output: DecimalPosterior = {}
    for configuration, probability in posterior.items():
        denominator = sum(
            (
                Decimal(count) * weight
                for count, weight in zip(
                    configuration,
                    exit_weights,
                    strict=True,
                )
            ),
            Decimal(0),
        )
        for location_index, (count, weight) in enumerate(
            zip(configuration, exit_weights, strict=True)
        ):
            if count == 0 or weight == 0:
                continue
            successor = list(configuration)
            successor[location_index] -= 1
            key = tuple(successor)
            output[key] = output.get(key, Decimal(0)) + (
                probability * Decimal(count) * weight / denominator
            )
    return _normalize_decimal(output)


def _normalize_decimal(
    posterior: Mapping[CountVector, Decimal],
) -> DecimalPosterior:
    total = sum(posterior.values(), Decimal(0))
    if total <= 0:
        raise ValueError("Decimal oracle removed all probability mass")
    return {
        configuration: probability / total
        for configuration, probability in posterior.items()
    }
