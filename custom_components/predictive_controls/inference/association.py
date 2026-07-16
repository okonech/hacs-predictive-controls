"""Bounded fixed-lag anonymous assignment model."""

from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from .operators import CompleteMoveOperators
from .state_space import CompactLogPosterior, CompactPosterior, StateSpace
from .types import (
    AssignmentIdentity,
    AugmentedStateKey,
    DifferenceConstraint,
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    FinalizationSupport,
    FinalizedAssignmentCertificate,
    SupportEventAtom,
    TemporalInterval,
    UnresolvedAssignment,
    assignment_atom_sort_key,
    require_utc,
    support_atom_sort_key,
)

_MICROSECONDS_PER_SECOND = 1_000_000
_MICROSECONDS_PER_DAY = 86_400 * _MICROSECONDS_PER_SECOND
_ZERO_CLOCK = "__zero_clock__"
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class DifferenceBoundMatrix:
    """Closed exact integer-microsecond difference constraints."""

    __slots__ = ("_bounds", "_index", "variables")

    def __init__(
        self,
        variables: tuple[str, ...],
        bounds: tuple[tuple[int | None, ...], ...],
    ) -> None:
        self.variables = variables
        self._index = {
            variable: index + 1 for index, variable in enumerate(variables)
        }
        self._bounds = bounds

    @classmethod
    def solve(
        cls,
        variables: Sequence[str],
        intervals: Sequence[TemporalInterval] = (),
        constraints: Sequence[DifferenceConstraint] = (),
    ) -> DifferenceBoundMatrix | None:
        if any(not variable for variable in variables):
            raise ValueError("Temporal variable IDs must be non-empty")
        if _ZERO_CLOCK in variables:
            raise ValueError("Temporal variables must not use the reserved zero clock")
        if len(set(variables)) != len(variables):
            raise ValueError("Temporal variable IDs must be unique")
        canonical_variables = tuple(sorted(variables))
        index = {
            _ZERO_CLOCK: 0,
            **{
                variable: variable_index + 1
                for variable_index, variable in enumerate(canonical_variables)
            },
        }
        dimension = len(canonical_variables) + 1
        bounds: list[list[int | None]] = [
            [None] * dimension for _ in range(dimension)
        ]
        for variable_index in range(dimension):
            bounds[variable_index][variable_index] = 0

        def add_bound(minuend: str, subtrahend: str, maximum: int) -> None:
            try:
                minuend_index = index[minuend]
                subtrahend_index = index[subtrahend]
            except KeyError as exc:
                raise ValueError(
                    f"Temporal constraint references undeclared variable: {exc.args[0]}"
                ) from exc
            current = bounds[minuend_index][subtrahend_index]
            if current is None or maximum < current:
                bounds[minuend_index][subtrahend_index] = maximum

        for interval in intervals:
            add_bound(
                interval.variable,
                _ZERO_CLOCK,
                _datetime_microseconds(interval.latest),
            )
            add_bound(
                _ZERO_CLOCK,
                interval.variable,
                -_datetime_microseconds(interval.earliest),
            )
        for constraint in constraints:
            add_bound(
                constraint.minuend,
                constraint.subtrahend,
                _timedelta_microseconds(constraint.maximum),
            )

        for intermediate in range(dimension):
            for source in range(dimension):
                source_to_intermediate = bounds[source][intermediate]
                if source_to_intermediate is None:
                    continue
                for target in range(dimension):
                    intermediate_to_target = bounds[intermediate][target]
                    if intermediate_to_target is None:
                        continue
                    candidate = source_to_intermediate + intermediate_to_target
                    current = bounds[source][target]
                    if current is None or candidate < current:
                        bounds[source][target] = candidate

        if any(
            cast(int, bounds[index][index]) < 0 for index in range(dimension)
        ):
            return None
        return cls(
            canonical_variables,
            tuple(tuple(row) for row in bounds),
        )

    def upper_bound(self, variable: str) -> datetime | None:
        bound = self._bounds[self._variable_index(variable)][0]
        if bound is None:
            return None
        return _UNIX_EPOCH + timedelta(microseconds=bound)

    def lower_bound(self, variable: str) -> datetime | None:
        bound = self._bounds[0][self._variable_index(variable)]
        if bound is None:
            return None
        return _UNIX_EPOCH + timedelta(microseconds=-bound)

    def maximum_difference(
        self,
        minuend: str,
        subtrahend: str,
    ) -> timedelta | None:
        bound = self._bounds[
            self._variable_index(minuend)
        ][self._variable_index(subtrahend)]
        if bound is None:
            return None
        return timedelta(microseconds=bound)

    def _variable_index(self, variable: str) -> int:
        try:
            return self._index[variable]
        except KeyError as exc:
            raise KeyError(f"Undeclared temporal variable: {variable}") from exc


def _datetime_microseconds(value: datetime) -> int:
    delta = value - _UNIX_EPOCH
    return _timedelta_microseconds(delta)


def _timedelta_microseconds(value: timedelta) -> int:
    return (
        value.days * _MICROSECONDS_PER_DAY
        + value.seconds * _MICROSECONDS_PER_SECOND
        + value.microseconds
    )


class AugmentedLogMessage:
    """Normalized exact log mass over occupancy and latent assignment context."""

    __slots__ = ("_entries", "space")

    def __init__(
        self,
        space: StateSpace,
        entries: Iterable[tuple[AugmentedStateKey, float]],
    ) -> None:
        combined: dict[AugmentedStateKey, float] = {}
        for key, log_mass in entries:
            if not 0 <= key.occupancy_rank < len(space):
                raise ValueError("Augmented occupancy rank is out of range")
            if math.isnan(log_mass) or log_mass == math.inf:
                raise ValueError(
                    "Augmented log mass must be finite or negative infinity"
                )
            if log_mass == -math.inf:
                continue
            canonical_key = AugmentedStateKey(
                key.occupancy_rank,
                tuple(sorted(key.contexts, key=assignment_atom_sort_key)),
                tuple(sorted(key.supports, key=support_atom_sort_key)),
            )
            combined[canonical_key] = _logaddexp(
                combined.get(canonical_key, -math.inf),
                log_mass,
            )
        normalizer = _logsumexp(combined.values())
        if normalizer == -math.inf:
            raise ValueError("Augmented message must contain finite probability mass")
        self.space = space
        self._entries = tuple(
            sorted(
                (
                    (key, log_mass - normalizer)
                    for key, log_mass in combined.items()
                ),
                key=lambda entry: _augmented_key_sort_key(entry[0]),
            )
        )

    @classmethod
    def from_posterior(
        cls,
        posterior: CompactLogPosterior,
    ) -> AugmentedLogMessage:
        return cls(
            posterior.space,
            (
                (AugmentedStateKey(rank), log_mass)
                for rank, log_mass in enumerate(posterior)
            ),
        )

    @property
    def entries(self) -> tuple[tuple[AugmentedStateKey, float], ...]:
        return self._entries

    @property
    def normalization(self) -> float:
        return math.fsum(math.exp(log_mass) for _, log_mass in self._entries)

    def has_endpoint(self, endpoint_id: str) -> bool:
        return any(
            any(atom.endpoint_id == endpoint_id for atom in key.contexts)
            or any(endpoint_id in atom.endpoint_ids for atom in key.supports)
            for key, _ in self._entries
        )

    def occupancy_posterior(self) -> CompactLogPosterior:
        output = array("d", [-math.inf]) * len(self.space)
        for key, log_mass in self._entries:
            output[key.occupancy_rank] = _logaddexp(
                output[key.occupancy_rank],
                log_mass,
            )
        return CompactLogPosterior(self.space, output)

    def apply_zone_likelihood(
        self,
        zone_index: int,
        *,
        empty_log_likelihood: float,
        occupied_log_likelihood: float,
    ) -> AugmentedLogMessage:
        if not 0 <= zone_index < len(self.space.zones):
            raise IndexError("Augmented likelihood zone index is out of range")
        if not math.isfinite(empty_log_likelihood) or not math.isfinite(
            occupied_log_likelihood
        ):
            raise ValueError("Augmented observation log likelihoods must be finite")
        return AugmentedLogMessage(
            self.space,
            (
                (
                    key,
                    log_mass
                    + (
                        occupied_log_likelihood
                        if self.space.unrank(key.occupancy_rank)[zone_index] > 0
                        else empty_log_likelihood
                    ),
                )
                for key, log_mass in self._entries
            ),
        )

    def finalize(
        self,
        watermark: datetime,
        support_by_assignment: Sequence[FinalizationSupport] = (),
    ) -> AugmentedLogMessage:
        require_utc(watermark, "Finalization watermark")
        declarations: dict[AssignmentIdentity, SupportEventAtom | None] = {}
        for declaration in support_by_assignment:
            if declaration.identity in declarations:
                raise ValueError("Finalization support identities must be unique")
            declarations[declaration.identity] = declaration.support
        consumed: set[AssignmentIdentity] = set()
        output: list[tuple[AugmentedStateKey, float]] = []
        for key, log_mass in self._entries:
            retained_contexts: list[EndpointAssignmentAtom] = []
            replacement_supports: list[SupportEventAtom] = []
            for atom in key.contexts:
                if watermark <= atom.deadline:
                    retained_contexts.append(atom)
                    continue
                identity = _assignment_identity(atom)
                if identity not in declarations:
                    continue
                consumed.add(identity)
                support = declarations[identity]
                if support is None:
                    continue
                if (
                    atom.endpoint_id not in support.endpoint_ids
                    and atom.endpoint_id not in support.episode_ids
                ):
                    raise ValueError(
                        "Finalization support does not contain assignment "
                        "endpoint token"
                    )
                if not support.valid_from <= atom.deadline <= support.valid_until:
                    raise ValueError(
                        "Finalization support does not contain assignment deadline"
                    )
                replacement_supports.append(support)
            output.append(
                (
                    AugmentedStateKey(
                        key.occupancy_rank,
                        tuple(retained_contexts),
                        (*key.supports, *replacement_supports),
                    ),
                    log_mass,
                )
            )
        unused = declarations.keys() - consumed
        if unused:
            raise ValueError("Finalization support declaration was not used")
        return AugmentedLogMessage(self.space, output)

    def expire_support(self, watermark: datetime) -> AugmentedLogMessage:
        require_utc(watermark, "Support expiration watermark")
        return AugmentedLogMessage(
            self.space,
            (
                (
                    AugmentedStateKey(
                        key.occupancy_rank,
                        key.contexts,
                        tuple(
                            support
                            for support in key.supports
                            if watermark <= support.valid_until
                        ),
                    ),
                    log_mass,
                )
                for key, log_mass in self._entries
            ),
        )

    def support_probability(
        self,
        predicate: Callable[[AugmentedStateKey], bool],
    ) -> float:
        return math.fsum(
            math.exp(log_mass)
            for key, log_mass in self._entries
            if predicate(key)
        )


@dataclass(frozen=True)
class EndpointFactor:
    """One categorical transition and observation factor for one endpoint."""

    endpoint: EndpointToken
    target_index: int
    target_zone: str
    alternatives: tuple[EndpointAlternative, ...]
    empty_log_likelihood: float
    occupied_log_likelihood: float

    def __post_init__(self) -> None:
        if self.target_index < 0 or not self.target_zone:
            raise ValueError("Endpoint factor requires a valid target")
        if not self.alternatives:
            raise ValueError("Endpoint factor requires alternatives")
        alternative_ids = {
            alternative.alternative_id for alternative in self.alternatives
        }
        if len(alternative_ids) != len(self.alternatives):
            raise ValueError("Endpoint alternative IDs must be unique")
        stay = tuple(
            alternative
            for alternative in self.alternatives
            if alternative.disposition == "stay"
        )
        if len(stay) != 1:
            raise ValueError("Endpoint factor requires exactly one stay alternative")
        if stay[0].log_weight == -math.inf:
            raise ValueError("Endpoint stay alternative must have finite weight")
        if any(
            alternative.deadline < self.endpoint.event_at
            for alternative in self.alternatives
        ):
            raise ValueError("Endpoint alternative deadline cannot precede endpoint")
        if any(
            not math.isfinite(value)
            for value in (
                self.empty_log_likelihood,
                self.occupied_log_likelihood,
            )
        ):
            raise ValueError("Endpoint observation log likelihoods must be finite")

    def apply(
        self,
        message: AugmentedLogMessage,
        operators: CompleteMoveOperators,
    ) -> AugmentedLogMessage:
        if message.space is not operators.space:
            raise ValueError("Augmented message and operators must share a state space")
        space = message.space
        if not 0 <= self.target_index < len(space.zones):
            raise IndexError("Endpoint target zone index is out of range")
        for alternative in self.alternatives:
            if alternative.source_index is None:
                continue
            if not 0 <= alternative.source_index < len(space.locations):
                raise IndexError("Endpoint source location index is out of range")
            if alternative.source_index == self.target_index:
                raise ValueError("Endpoint movement source and target must differ")
            if (
                alternative.disposition == "unlocated"
                and alternative.source_index != space.unlocated_index
            ):
                raise ValueError("Unlocated alternative must use unlocated source")
        if message.has_endpoint(self.endpoint.token_id):
            raise ValueError("Endpoint is already present in augmented state")

        output: list[tuple[AugmentedStateKey, float]] = []
        for predecessor_key, predecessor_log_mass in message.entries:
            predecessor_configuration = space.unrank(predecessor_key.occupancy_rank)
            for alternative in self.alternatives:
                if alternative.log_weight == -math.inf:
                    continue
                source_index = alternative.source_index
                if source_index is None:
                    successor_rank = predecessor_key.occupancy_rank
                    multiplicity_log_weight = 0.0
                else:
                    source_multiplicity = predecessor_configuration[source_index]
                    if source_multiplicity == 0:
                        continue
                    successor_rank = operators.operator(
                        source_index,
                        self.target_index,
                    ).successors[predecessor_key.occupancy_rank]
                    multiplicity_log_weight = math.log(source_multiplicity)
                successor_configuration = space.unrank(successor_rank)
                observation_log_likelihood = (
                    self.occupied_log_likelihood
                    if successor_configuration[self.target_index] > 0
                    else self.empty_log_likelihood
                )
                assignment = EndpointAssignmentAtom(
                    self.endpoint.token_id,
                    alternative.alternative_id,
                    alternative.disposition,
                    predecessor_key.occupancy_rank,
                    successor_rank,
                    source_index,
                    self.target_index,
                    alternative.source_node_id,
                    self.endpoint.node_id,
                    alternative.route_nodes,
                    alternative.deadline,
                    alternative.evidence_ids,
                )
                output.append(
                    (
                        AugmentedStateKey(
                            successor_rank,
                            (*predecessor_key.contexts, assignment),
                            predecessor_key.supports,
                        ),
                        predecessor_log_mass
                        + alternative.log_weight
                        + multiplicity_log_weight
                        + observation_log_likelihood,
                    )
                )
        return AugmentedLogMessage(space, output)


def _augmented_key_sort_key(key: AugmentedStateKey) -> tuple[object, ...]:
    return (
        key.occupancy_rank,
        tuple(assignment_atom_sort_key(atom) for atom in key.contexts),
        tuple(support_atom_sort_key(atom) for atom in key.supports),
    )


def _assignment_identity(atom: EndpointAssignmentAtom) -> AssignmentIdentity:
    return AssignmentIdentity(
        atom.endpoint_id,
        atom.alternative_id,
        atom.predecessor_rank,
        atom.successor_rank,
    )


def _logaddexp(first: float, second: float) -> float:
    if first == -math.inf:
        return second
    maximum = max(first, second)
    return maximum + math.log(math.exp(first - maximum) + math.exp(second - maximum))


def _logsumexp(values: Iterable[float]) -> float:
    collected = tuple(values)
    maximum = max(collected, default=-math.inf)
    if maximum == -math.inf:
        return -math.inf
    return maximum + math.log(
        math.fsum(math.exp(value - maximum) for value in collected)
    )


class FixedLagAssociationGraph:
    """Retain endpoints until a monotone event-time watermark finalizes them."""

    __slots__ = (
        "_consumed_endpoint_ids",
        "_pending",
        "max_lateness",
        "watermark",
    )

    def __init__(self, max_lateness: timedelta, watermark: datetime) -> None:
        if max_lateness < timedelta(0):
            raise ValueError("Maximum lateness must be non-negative")
        require_utc(watermark, "Initial watermark")
        self.max_lateness = max_lateness
        self.watermark = watermark
        self._pending: dict[str, UnresolvedAssignment] = {}
        self._consumed_endpoint_ids: set[str] = set()

    @property
    def pending(self) -> tuple[UnresolvedAssignment, ...]:
        return tuple(
            sorted(
                self._pending.values(),
                key=lambda candidate: (candidate.deadline, candidate.candidate_id),
            )
        )

    @property
    def consumed_endpoint_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._consumed_endpoint_ids))

    def add(self, candidate: UnresolvedAssignment) -> None:
        endpoint_id = candidate.endpoint.token_id
        if candidate.deadline < self.watermark:
            raise ValueError("Assignment is already behind the finalized watermark")
        if candidate.candidate_id in self._pending:
            raise ValueError("Assignment candidate ID is already pending")
        if endpoint_id in self._consumed_endpoint_ids or any(
            pending.endpoint.token_id == endpoint_id
            for pending in self._pending.values()
        ):
            raise ValueError("Endpoint token is already assigned")
        self._pending[candidate.candidate_id] = candidate

    def advance(
        self,
        receive_at: datetime,
        posterior: CompactPosterior,
        operators: CompleteMoveOperators,
    ) -> tuple[CompactPosterior, tuple[FinalizedAssignmentCertificate, ...]]:
        require_utc(receive_at, "Receive time")
        next_watermark = receive_at - self.max_lateness
        if next_watermark > self.watermark:
            self.watermark = next_watermark
        finalized: list[FinalizedAssignmentCertificate] = []
        current = posterior
        for candidate in self.pending:
            if self.watermark <= candidate.deadline:
                continue
            current = operators.transition(
                current,
                {
                    (alternative.source_index, alternative.target_index): (
                        alternative.weight
                    )
                    for alternative in candidate.alternatives
                },
                stay_weight=candidate.stay_weight,
            )
            finalized.append(
                FinalizedAssignmentCertificate(
                    candidate.candidate_id,
                    candidate.endpoint.token_id,
                    candidate.deadline,
                    candidate.alternatives,
                    candidate.evidence_ids,
                )
            )
            self._consumed_endpoint_ids.add(candidate.endpoint.token_id)
            del self._pending[candidate.candidate_id]
        return current, tuple(finalized)
