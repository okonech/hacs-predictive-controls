"""Exact anonymous count-vector state enumeration and posterior storage."""

from __future__ import annotations

import hashlib
import math
from array import array
from collections.abc import Iterable, Iterator, Sequence

MAX_OCCUPANTS = 5
CountVector = tuple[int, ...]


def _weak_compositions(total: int, parts: int) -> Iterator[CountVector]:
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for remainder in _weak_compositions(total - first, parts - 1):
            yield (first, *remainder)


class StateSpace:
    """Complete deterministic count-vector space for one authoritative count."""

    __slots__ = (
        "_rank_by_configuration",
        "configurations",
        "locations",
        "occupants",
        "zones",
    )

    def __init__(self, zones: Sequence[str], occupants: int) -> None:
        canonical_zones = tuple(zones)
        if not canonical_zones:
            raise ValueError("State space requires at least one zone")
        if len(set(canonical_zones)) != len(canonical_zones):
            raise ValueError("State-space zones must be unique")
        if not 0 <= occupants <= MAX_OCCUPANTS:
            raise ValueError(f"Occupants must be between 0 and {MAX_OCCUPANTS}")
        self.zones = canonical_zones
        self.locations = (*canonical_zones, "unlocated")
        self.occupants = occupants
        self.configurations = tuple(
            _weak_compositions(occupants, len(self.locations))
        )
        self._rank_by_configuration = {
            configuration: rank
            for rank, configuration in enumerate(self.configurations)
        }
        expected_count = math.comb(len(canonical_zones) + occupants, occupants)
        assert len(self.configurations) == expected_count

    def __len__(self) -> int:
        return len(self.configurations)

    @property
    def unlocated_index(self) -> int:
        return len(self.zones)

    def location_index(self, location: str | None) -> int:
        if location is None or location == "unlocated":
            return self.unlocated_index
        try:
            return self.zones.index(location)
        except ValueError as exc:
            raise KeyError(location) from exc

    def rank(self, configuration: Sequence[int]) -> int:
        candidate = tuple(configuration)
        if len(candidate) != len(self.locations):
            raise ValueError("Configuration dimension does not match state space")
        if any(not isinstance(count, int) or count < 0 for count in candidate):
            raise ValueError("Configuration counts must be non-negative integers")
        if sum(candidate) != self.occupants:
            raise ValueError("Configuration does not conserve authoritative count")
        return self._rank_by_configuration[candidate]

    def unrank(self, rank: int) -> CountVector:
        if not 0 <= rank < len(self.configurations):
            raise IndexError(f"State rank out of range: {rank}")
        return self.configurations[rank]


class CompactPosterior:
    """Normalized exact posterior backed by a compact C-double array."""

    __slots__ = ("_probabilities", "space")

    def __init__(self, space: StateSpace, probabilities: Iterable[float]) -> None:
        values = array("d", probabilities)
        if len(values) != len(space):
            raise ValueError("Posterior dimension does not match state space")
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("Posterior values must be finite and non-negative")
        total = math.fsum(values)
        if total <= 0.0:
            raise ValueError("Posterior must contain positive probability mass")
        for index, value in enumerate(values):
            values[index] = value / total
        self.space = space
        self._probabilities = values

    @classmethod
    def certain(
        cls,
        space: StateSpace,
        configuration: Sequence[int],
    ) -> CompactPosterior:
        probabilities = array("d", [0.0]) * len(space)
        probabilities[space.rank(configuration)] = 1.0
        return cls(space, probabilities)

    @classmethod
    def uniform(cls, space: StateSpace) -> CompactPosterior:
        return cls(space, (1.0 for _ in space.configurations))

    def __len__(self) -> int:
        return len(self._probabilities)

    def __iter__(self) -> Iterator[float]:
        return iter(self._probabilities)

    def __getitem__(self, rank: int) -> float:
        return self._probabilities[rank]

    @property
    def normalization(self) -> float:
        return math.fsum(self._probabilities)

    @property
    def storage_bytes(self) -> int:
        return self._probabilities.buffer_info()[1] * self._probabilities.itemsize

    def count_marginals(self) -> tuple[tuple[float, ...], ...]:
        marginals = [
            [0.0] * (self.space.occupants + 1) for _ in self.space.locations
        ]
        for probability, configuration in zip(
            self._probabilities,
            self.space.configurations,
            strict=True,
        ):
            for location_index, count in enumerate(configuration):
                marginals[location_index][count] += probability
        return tuple(tuple(counts) for counts in marginals)

    def occupied_marginals(self) -> tuple[float, ...]:
        zone_counts = self.count_marginals()[: len(self.space.zones)]
        return tuple(
            1.0 - counts[0]
            for counts in zone_counts
        )


class CompactLogPosterior:
    """Complete normalized posterior retained as C-double log probabilities."""

    __slots__ = (
        "_exact_digest",
        "_input_log_normalizer",
        "_log_probabilities",
        "space",
    )

    def __init__(
        self,
        space: StateSpace,
        log_probabilities: Iterable[float],
    ) -> None:
        values = array("d", log_probabilities)
        if len(values) != len(space):
            raise ValueError("Posterior dimension does not match state space")
        if any(math.isnan(value) or value == math.inf for value in values):
            raise ValueError("Log posterior values must be finite or negative infinity")
        normalizer = _logsumexp(values)
        if normalizer == -math.inf:
            raise ValueError("Log posterior must contain finite probability mass")
        for index, value in enumerate(values):
            values[index] = value - normalizer
        self.space = space
        self._log_probabilities = values
        self._exact_digest: bytes | None = None
        self._input_log_normalizer: float | None = normalizer

    @classmethod
    def certain(
        cls,
        space: StateSpace,
        configuration: Sequence[int],
    ) -> CompactLogPosterior:
        values = array("d", [-math.inf]) * len(space)
        values[space.rank(configuration)] = 0.0
        return cls(space, values)

    @classmethod
    def from_normalized(
        cls,
        space: StateSpace,
        log_probabilities: Iterable[float],
    ) -> CompactLogPosterior:
        values = array("d", log_probabilities)
        if len(values) != len(space):
            raise ValueError("Posterior dimension does not match state space")
        if any(math.isnan(value) or value == math.inf for value in values):
            raise ValueError("Log posterior values must be finite or negative infinity")
        normalization = math.fsum(
            math.exp(value) for value in values if value != -math.inf
        )
        if abs(normalization - 1.0) > 1e-12:
            raise ValueError("Persisted log posterior must be normalized")
        instance = cls.__new__(cls)
        instance.space = space
        instance._log_probabilities = values
        instance._exact_digest = None
        instance._input_log_normalizer = None
        return instance

    @classmethod
    def uniform(cls, space: StateSpace) -> CompactLogPosterior:
        return cls(space, (0.0 for _ in space.configurations))

    def __len__(self) -> int:
        return len(self._log_probabilities)

    def __iter__(self) -> Iterator[float]:
        return iter(self._log_probabilities)

    def __getitem__(self, rank: int) -> float:
        return self._log_probabilities[rank]

    @property
    def normalization(self) -> float:
        return math.fsum(
            math.exp(value)
            for value in self._log_probabilities
            if value != -math.inf
        )

    @property
    def input_log_normalizer(self) -> float | None:
        return self._input_log_normalizer

    @property
    def storage_bytes(self) -> int:
        return (
            self._log_probabilities.buffer_info()[1]
            * self._log_probabilities.itemsize
        )

    def exact_digest(self) -> bytes:
        digest = self._exact_digest
        if digest is None:
            digest = hashlib.sha256(self._log_probabilities).digest()
            self._exact_digest = digest
        return digest

    def exact_values_equal(self, other: CompactLogPosterior) -> bool:
        return self._log_probabilities == other._log_probabilities

    def apply_zone_likelihood(
        self,
        zone_index: int,
        *,
        empty_log_likelihood: float,
        occupied_log_likelihood: float,
    ) -> CompactLogPosterior:
        return self.apply_zone_likelihoods(
            ((zone_index, empty_log_likelihood, occupied_log_likelihood),)
        )

    def apply_zone_likelihoods(
        self,
        likelihoods: Sequence[tuple[int, float, float]],
    ) -> CompactLogPosterior:
        if any(
            not 0 <= zone_index < len(self.space.zones)
            for zone_index, _, _ in likelihoods
        ):
            raise IndexError("Observation zone index is out of range")
        if any(
            not math.isfinite(value)
            for _, empty_log_likelihood, occupied_log_likelihood in likelihoods
            for value in (empty_log_likelihood, occupied_log_likelihood)
        ):
            raise ValueError("Observation log likelihoods must be finite")
        return CompactLogPosterior(
            self.space,
            (
                log_probability
                + sum(
                    occupied_log_likelihood
                    if configuration[zone_index] > 0
                    else empty_log_likelihood
                    for (
                        zone_index,
                        empty_log_likelihood,
                        occupied_log_likelihood,
                    ) in likelihoods
                )
                for log_probability, configuration in zip(
                    self._log_probabilities,
                    self.space.configurations,
                    strict=True,
                )
            ),
        )

    def count_marginals(self) -> tuple[tuple[float, ...], ...]:
        marginal_probabilities = [
            [0.0] * (self.space.occupants + 1)
            for _ in self.space.locations
        ]
        for log_probability, configuration in zip(
            self._log_probabilities,
            self.space.configurations,
            strict=True,
        ):
            probability = math.exp(log_probability)
            for location_index, count in enumerate(configuration):
                marginal_probabilities[location_index][count] += probability
        return tuple(
            tuple(counts) for counts in marginal_probabilities
        )

    def occupied_marginals(self) -> tuple[float, ...]:
        zone_counts = self.count_marginals()[: len(self.space.zones)]
        return tuple(math.fsum(counts[1:]) for counts in zone_counts)


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values, default=-math.inf)
    if maximum == -math.inf:
        return -math.inf
    return maximum + math.log(
        math.fsum(math.exp(value - maximum) for value in values)
    )
