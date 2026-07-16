"""Exact layered factor chain without materialized assignment paths."""

from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from .association import AugmentedLogMessage, EndpointFactor
from .operators import CompleteMoveOperators
from .state_space import CompactLogPosterior
from .types import (
    AssignmentIdentity,
    EndpointAlternative,
    EndpointAssignmentAtom,
    FinalizationSupport,
    SupportEventAtom,
    require_utc,
)


@dataclass(frozen=True)
class ZoneLikelihoodStep:
    zone_index: int
    empty_log_likelihood: float
    occupied_log_likelihood: float
    event_at: datetime

    def __post_init__(self) -> None:
        if self.zone_index < 0:
            raise ValueError("Likelihood zone index must be non-negative")
        if not math.isfinite(self.empty_log_likelihood) or not math.isfinite(
            self.occupied_log_likelihood
        ):
            raise ValueError("Likelihood values must be finite")
        require_utc(self.event_at, "Likelihood event time")


type FactorStep = ZoneLikelihoodStep | EndpointFactor
type SupportCertificateFactory = Callable[
    [EndpointFactor, EndpointAssignmentAtom],
    SupportEventAtom | None,
]
_LOG_MULTIPLICITY = tuple(
    -math.inf if count == 0 else math.log(count) for count in range(6)
)


class ExactFactorChain:
    """A chain-structured exact joint model with compact forward messages."""

    __slots__ = (
        "_base",
        "_base_message",
        "_endpoint_prefixes",
        "_operators",
        "_posterior",
        "_steps",
        "space",
    )

    def __init__(
        self,
        base: CompactLogPosterior,
        steps: tuple[FactorStep, ...] = (),
        operators: CompleteMoveOperators | None = None,
        *,
        base_message: AugmentedLogMessage | None = None,
    ) -> None:
        self.space = base.space
        self._base = base
        self._base_message = base_message or AugmentedLogMessage.from_posterior(base)
        self._validate_base_message()
        if operators is not None and operators.space is not self.space:
            raise ValueError("Factor chain and operators must share a state space")
        self._operators = operators or CompleteMoveOperators(self.space)
        self._steps = steps
        posterior = base
        endpoint_prefixes: dict[str, CompactLogPosterior] = {}
        endpoint_ids: set[str] = set()
        pending_likelihoods: list[ZoneLikelihoodStep] = []
        for step in steps:
            if isinstance(step, ZoneLikelihoodStep):
                pending_likelihoods.append(step)
                continue
            posterior = self._apply_likelihood_steps(
                posterior,
                pending_likelihoods,
            )
            pending_likelihoods.clear()
            if step.endpoint.token_id in endpoint_ids:
                raise ValueError("Endpoint is duplicated in factor chain")
            endpoint_ids.add(step.endpoint.token_id)
            endpoint_prefixes[step.endpoint.token_id] = posterior
            posterior = self._apply_step(posterior, step)
        posterior = self._apply_likelihood_steps(posterior, pending_likelihoods)
        self._endpoint_prefixes = endpoint_prefixes
        self._posterior = posterior

    @property
    def base(self) -> CompactLogPosterior:
        return self._base

    @property
    def base_message(self) -> AugmentedLogMessage:
        return self._base_message

    @property
    def steps(self) -> tuple[FactorStep, ...]:
        return self._steps

    @property
    def posterior(self) -> CompactLogPosterior:
        return self._posterior

    @property
    def operators(self) -> CompleteMoveOperators:
        return self._operators

    @property
    def unresolved_endpoint_count(self) -> int:
        return sum(isinstance(step, EndpointFactor) for step in self._steps)

    def apply_zone_likelihood(
        self,
        zone_index: int,
        *,
        empty_log_likelihood: float,
        occupied_log_likelihood: float,
        event_at: datetime,
    ) -> ExactFactorChain:
        step = ZoneLikelihoodStep(
            zone_index,
            empty_log_likelihood,
            occupied_log_likelihood,
            event_at,
        )
        return self._from_parts(
            self._base,
            (*self._steps, step),
            self._apply_step(self._posterior, step),
            self._operators,
            self._base_message,
            self._endpoint_prefixes,
        )

    def apply_zone_likelihoods(
        self,
        steps: tuple[ZoneLikelihoodStep, ...],
    ) -> ExactFactorChain:
        if not steps:
            return self
        posterior = self._posterior.apply_zone_likelihoods(
            tuple(
                (
                    step.zone_index,
                    step.empty_log_likelihood,
                    step.occupied_log_likelihood,
                )
                for step in steps
            )
        )
        return self._from_parts(
            self._base,
            (*self._steps, *steps),
            posterior,
            self._operators,
            self._base_message,
            self._endpoint_prefixes,
        )

    def apply_endpoint(self, factor: EndpointFactor) -> ExactFactorChain:
        if any(
            isinstance(step, EndpointFactor)
            and step.endpoint.token_id == factor.endpoint.token_id
            for step in self._steps
        ):
            raise ValueError("Endpoint is already present in factor chain")
        endpoint_prefixes = dict(self._endpoint_prefixes)
        endpoint_prefixes[factor.endpoint.token_id] = self._posterior
        return self._from_parts(
            self._base,
            (*self._steps, factor),
            self._apply_step(self._posterior, factor),
            self._operators,
            self._base_message,
            endpoint_prefixes,
        )

    def assignment_probability(
        self,
        endpoint_id: str,
        predicate: Callable[[EndpointAssignmentAtom], bool],
    ) -> float:
        return self.assignment_and_terminal_probability(
            endpoint_id,
            predicate,
            lambda _configuration: True,
        )

    def assignment_and_terminal_probability(
        self,
        endpoint_id: str,
        assignment_predicate: Callable[[EndpointAssignmentAtom], bool],
        terminal_predicate: Callable[[tuple[int, ...]], bool],
    ) -> float:
        return self.assignment_and_terminal_probabilities(
            endpoint_id,
            ((assignment_predicate, terminal_predicate),),
        )[0]

    def terminal_alternative_and_configuration_probabilities(
        self,
        endpoint_id: str,
        queries: Sequence[
            tuple[
                Callable[[EndpointAlternative], bool],
                Callable[[tuple[int, ...]], bool],
            ]
        ],
    ) -> tuple[float, ...]:
        if not endpoint_id:
            raise ValueError("Endpoint ID must be non-empty")
        if not queries:
            return ()
        if not self._steps or not isinstance(self._steps[-1], EndpointFactor):
            raise ValueError("Terminal endpoint query requires a final endpoint")
        factor = self._steps[-1]
        if factor.endpoint.token_id != endpoint_id:
            if any(
                isinstance(step, EndpointFactor)
                and step.endpoint.token_id == endpoint_id
                for step in self._steps
            ):
                raise ValueError("Endpoint is not the final factor-chain step")
            raise KeyError(f"Endpoint is not retained: {endpoint_id}")
        forward = self._endpoint_prefixes.get(endpoint_id)
        if forward is None:
            raise RuntimeError("Endpoint prefix cache is incomplete")
        compiled: list[
            tuple[
                EndpointAlternative,
                array[int] | None,
                tuple[int, ...],
            ]
        ] = []
        for alternative in factor.alternatives:
            if alternative.log_weight == -math.inf:
                continue
            source_index = alternative.source_index
            successors = (
                None
                if source_index is None
                else self._operators.operator(
                    source_index,
                    factor.target_index,
                ).successors
            )
            matching_queries = tuple(
                index
                for index, (predicate, _) in enumerate(queries)
                if predicate(alternative)
            )
            compiled.append((alternative, successors, matching_queries))
        selected = [-math.inf] * len(queries)
        cached_total = self._posterior.input_log_normalizer
        total = -math.inf if cached_total is None else cached_total
        configurations = self.space.configurations
        for predecessor_rank, (predecessor_mass, predecessor) in enumerate(
            zip(forward, configurations, strict=True)
        ):
            if predecessor_mass == -math.inf:
                continue
            for alternative, successors, matching_queries in compiled:
                source_index = alternative.source_index
                if source_index is None:
                    successor_rank = predecessor_rank
                    multiplicity = 0.0
                else:
                    count = predecessor[source_index]
                    if count == 0:
                        continue
                    assert successors is not None
                    successor_rank = successors[predecessor_rank]
                    multiplicity = _LOG_MULTIPLICITY[count]
                likelihood = (
                    factor.occupied_log_likelihood
                    if source_index is not None
                    or predecessor[factor.target_index] > 0
                    else factor.empty_log_likelihood
                )
                joint = (
                    predecessor_mass
                    + alternative.log_weight
                    + multiplicity
                    + likelihood
                )
                if cached_total is None:
                    total = _logaddexp(total, joint)
                successor = configurations[successor_rank]
                for query_index in matching_queries:
                    if queries[query_index][1](successor):
                        selected[query_index] = _logaddexp(
                            selected[query_index],
                            joint,
                        )
        return tuple(
            _checked_probability(selected_mass, total)
            for selected_mass in selected
        )

    def assignment_and_terminal_probabilities(
        self,
        endpoint_id: str,
        queries: Sequence[
            tuple[
                Callable[[EndpointAssignmentAtom], bool],
                Callable[[tuple[int, ...]], bool],
            ]
        ],
    ) -> tuple[float, ...]:
        if not endpoint_id:
            raise ValueError("Endpoint ID must be non-empty")
        if not queries:
            return ()
        target = next(
            (
                index
                for index, step in enumerate(self._steps)
                if isinstance(step, EndpointFactor)
                and step.endpoint.token_id == endpoint_id
            ),
            None,
        )
        if target is None:
            raise KeyError(f"Endpoint is not retained: {endpoint_id}")
        forward = self._endpoint_prefixes.get(endpoint_id)
        if forward is None:
            raise RuntimeError("Endpoint prefix cache is incomplete")
        selected_backwards = tuple(
            array(
                "d",
                (
                    0.0 if terminal_predicate(configuration) else -math.inf
                    for configuration in self.space.configurations
                ),
            )
            for _, terminal_predicate in queries
        )
        total_backward = array("d", [0.0]) * len(self.space)
        for step in reversed(self._steps[target + 1 :]):
            selected_backwards, total_backward = self._backward_steps(
                selected_backwards,
                total_backward,
                step,
            )
        factor = self._steps[target]
        assert isinstance(factor, EndpointFactor)
        selected = [-math.inf] * len(queries)
        total = -math.inf
        for predecessor_rank, predecessor_mass in enumerate(forward):
            if predecessor_mass == -math.inf:
                continue
            for alternative, successor_rank, log_potential in self._factor_transitions(
                factor,
                predecessor_rank,
            ):
                joint = (
                    predecessor_mass
                    + log_potential
                    + total_backward[successor_rank]
                )
                total = _logaddexp(total, joint)
                assignment = self._assignment_atom(
                    factor,
                    alternative,
                    predecessor_rank,
                    successor_rank,
                )
                for query_index, (assignment_predicate, _) in enumerate(queries):
                    if assignment_predicate(assignment):
                        selected[query_index] = _logaddexp(
                            selected[query_index],
                            predecessor_mass
                            + log_potential
                            + selected_backwards[query_index][successor_rank],
                        )
        if total == -math.inf:
            raise ValueError("Factor-chain joint event has no finite total mass")
        return tuple(
            _checked_probability(selected_mass, total)
            for selected_mass in selected
        )

    def compact(
        self,
        watermark: datetime,
        support_factory: SupportCertificateFactory | None = None,
    ) -> tuple[ExactFactorChain, tuple[str, ...]]:
        require_utc(watermark, "Factor-chain compaction watermark")
        base_message = self._base_message.expire_support(watermark)
        through = 0
        consumed: list[str] = []
        for step in self._steps:
            if isinstance(step, ZoneLikelihoodStep):
                if watermark <= step.event_at:
                    break
            else:
                if any(watermark <= alt.deadline for alt in step.alternatives):
                    break
                consumed.append(step.endpoint.token_id)
            through += 1
        if through == 0 and base_message.entries == self._base_message.entries:
            return self, ()
        for step in self._steps[:through]:
            if isinstance(step, ZoneLikelihoodStep):
                base_message = base_message.apply_zone_likelihood(
                    step.zone_index,
                    empty_log_likelihood=step.empty_log_likelihood,
                    occupied_log_likelihood=step.occupied_log_likelihood,
                )
                continue
            applied = step.apply(base_message, self._operators)
            atoms: dict[AssignmentIdentity, EndpointAssignmentAtom] = {}
            for key, _ in applied.entries:
                for atom in key.contexts:
                    identity = _assignment_identity(atom)
                    atoms.setdefault(identity, atom)
            declarations = tuple(
                FinalizationSupport(
                    identity,
                    None
                    if support_factory is None
                    else support_factory(step, atoms[identity]),
                )
                for identity in sorted(atoms, key=_identity_sort_key)
            )
            base_message = applied.finalize(watermark, declarations)
            if any(key.contexts for key, _ in base_message.entries):
                raise ValueError("Compacted support base retained assignment context")
        base_message = base_message.expire_support(watermark)
        base = base_message.occupancy_posterior()
        compacted = ExactFactorChain(
            base,
            self._steps[through:],
            self._operators,
            base_message=base_message,
        )
        if any(
            abs(math.exp(actual) - math.exp(expected)) > 1e-12
            for actual, expected in zip(
                compacted.posterior,
                self._posterior,
                strict=True,
            )
        ):
            raise ValueError("Support compaction changed the factor-chain posterior")
        return compacted.with_persisted_posterior(self._posterior), tuple(consumed)

    def finalized_support_message(self) -> AugmentedLogMessage:
        """Condition finalized support strata through retained unary factors."""

        if any(isinstance(step, EndpointFactor) for step in self._steps):
            raise ValueError(
                "Finalized support is unavailable with unresolved endpoint"
            )
        message = self._base_message
        for step in self._steps:
            assert isinstance(step, ZoneLikelihoodStep)
            message = message.apply_zone_likelihood(
                step.zone_index,
                empty_log_likelihood=step.empty_log_likelihood,
                occupied_log_likelihood=step.occupied_log_likelihood,
            )
        return message

    def with_persisted_posterior(
        self,
        posterior: CompactLogPosterior,
        *,
        tolerance: float = 1e-12,
    ) -> ExactFactorChain:
        if posterior.space is not self.space:
            raise ValueError("Persisted posterior must use the factor-chain space")
        if any(
            abs(math.exp(actual) - math.exp(expected)) > tolerance
            for actual, expected in zip(self._posterior, posterior, strict=True)
        ):
            raise ValueError("Persisted factor-chain posterior does not reconstruct")
        return self._from_parts(
            self._base,
            self._steps,
            posterior,
            self._operators,
            self._base_message,
            self._endpoint_prefixes,
        )

    @classmethod
    def _from_parts(
        cls,
        base: CompactLogPosterior,
        steps: tuple[FactorStep, ...],
        posterior: CompactLogPosterior,
        operators: CompleteMoveOperators,
        base_message: AugmentedLogMessage,
        endpoint_prefixes: dict[str, CompactLogPosterior],
    ) -> ExactFactorChain:
        instance = cls.__new__(cls)
        instance.space = base.space
        instance._base = base
        instance._base_message = base_message
        instance._endpoint_prefixes = endpoint_prefixes
        instance._operators = operators
        instance._steps = steps
        instance._posterior = posterior
        return instance

    def _validate_base_message(self) -> None:
        if self._base_message.space is not self.space:
            raise ValueError("Factor-chain support base must use its exact state space")
        if any(key.contexts for key, _ in self._base_message.entries):
            raise ValueError("Factor-chain support base must not contain contexts")
        projected = self._base_message.occupancy_posterior()
        if any(
            abs(math.exp(actual) - math.exp(expected)) > 1e-12
            for actual, expected in zip(projected, self._base, strict=True)
        ):
            raise ValueError("Factor-chain support base does not project to base")

    def _apply_step(
        self,
        posterior: CompactLogPosterior,
        step: FactorStep,
    ) -> CompactLogPosterior:
        if isinstance(step, ZoneLikelihoodStep):
            return posterior.apply_zone_likelihood(
                step.zone_index,
                empty_log_likelihood=step.empty_log_likelihood,
                occupied_log_likelihood=step.occupied_log_likelihood,
            )
        if not 0 <= step.target_index < len(self.space.zones):
            raise IndexError("Endpoint target zone index is out of range")
        compiled = tuple(
            (
                alternative,
                None
                if alternative.source_index is None
                else self._operators.operator(
                    alternative.source_index,
                    step.target_index,
                ).successors,
            )
            for alternative in step.alternatives
            if alternative.log_weight != -math.inf
        )
        output = array("d", [-math.inf]) * len(self.space)
        for predecessor_rank, (predecessor_mass, predecessor) in enumerate(
            zip(posterior, self.space.configurations, strict=True)
        ):
            if predecessor_mass == -math.inf:
                continue
            for alternative, successors in compiled:
                source_index = alternative.source_index
                if source_index is None:
                    successor_rank = predecessor_rank
                    multiplicity = 0.0
                else:
                    count = predecessor[source_index]
                    if count == 0:
                        continue
                    assert successors is not None
                    successor_rank = successors[predecessor_rank]
                    multiplicity = _LOG_MULTIPLICITY[count]
                likelihood = (
                    step.occupied_log_likelihood
                    if source_index is not None
                    or predecessor[step.target_index] > 0
                    else step.empty_log_likelihood
                )
                output[successor_rank] = _logaddexp(
                    output[successor_rank],
                    predecessor_mass
                    + alternative.log_weight
                    + multiplicity
                    + likelihood,
                )
        return CompactLogPosterior(self.space, output)

    def _apply_likelihood_steps(
        self,
        posterior: CompactLogPosterior,
        steps: list[ZoneLikelihoodStep],
    ) -> CompactLogPosterior:
        if not steps:
            return posterior
        return posterior.apply_zone_likelihoods(
            tuple(
                (
                    step.zone_index,
                    step.empty_log_likelihood,
                    step.occupied_log_likelihood,
                )
                for step in steps
            )
        )

    def _backward_step(self, successor: array[float], step: FactorStep) -> array[float]:
        predecessor = array("d", [-math.inf]) * len(self.space)
        if isinstance(step, ZoneLikelihoodStep):
            for rank, configuration in enumerate(self.space.configurations):
                likelihood = (
                    step.occupied_log_likelihood
                    if configuration[step.zone_index] > 0
                    else step.empty_log_likelihood
                )
                predecessor[rank] = likelihood + successor[rank]
            return predecessor
        for rank in range(len(self.space)):
            for _, successor_rank, log_potential in self._factor_transitions(
                step,
                rank,
            ):
                predecessor[rank] = _logaddexp(
                    predecessor[rank],
                    log_potential + successor[successor_rank],
                )
        return predecessor

    def _backward_steps(
        self,
        selected_successors: tuple[array[float], ...],
        total_successor: array[float],
        step: FactorStep,
    ) -> tuple[tuple[array[float], ...], array[float]]:
        selected_predecessors = tuple(
            array("d", [-math.inf]) * len(self.space)
            for _ in selected_successors
        )
        total_predecessor = array("d", [-math.inf]) * len(self.space)
        if isinstance(step, ZoneLikelihoodStep):
            for rank, configuration in enumerate(self.space.configurations):
                likelihood = (
                    step.occupied_log_likelihood
                    if configuration[step.zone_index] > 0
                    else step.empty_log_likelihood
                )
                total_predecessor[rank] = likelihood + total_successor[rank]
                for query_index, selected_successor in enumerate(
                    selected_successors
                ):
                    selected_predecessors[query_index][rank] = (
                        likelihood + selected_successor[rank]
                    )
            return selected_predecessors, total_predecessor
        if not 0 <= step.target_index < len(self.space.zones):
            raise IndexError("Endpoint target zone index is out of range")
        compiled: list[tuple[EndpointAlternative, array[int] | None]] = []
        for alternative in step.alternatives:
            if alternative.log_weight == -math.inf:
                continue
            source_index = alternative.source_index
            if source_index is None:
                successors = None
            else:
                if not 0 <= source_index < len(self.space.locations):
                    raise IndexError("Endpoint source location index is out of range")
                if source_index == step.target_index:
                    raise ValueError("Endpoint movement source and target must differ")
                successors = self._operators.operator(
                    source_index,
                    step.target_index,
                ).successors
            compiled.append((alternative, successors))
        for rank, configuration in enumerate(self.space.configurations):
            for alternative, successors in compiled:
                source_index = alternative.source_index
                if source_index is None:
                    successor_rank = rank
                    multiplicity = 0.0
                else:
                    count = configuration[source_index]
                    if count == 0:
                        continue
                    assert successors is not None
                    successor_rank = successors[rank]
                    multiplicity = _LOG_MULTIPLICITY[count]
                likelihood = (
                    step.occupied_log_likelihood
                    if source_index is not None
                    or configuration[step.target_index] > 0
                    else step.empty_log_likelihood
                )
                log_potential = (
                    alternative.log_weight + multiplicity + likelihood
                )
                total_predecessor[rank] = _logaddexp(
                    total_predecessor[rank],
                    log_potential + total_successor[successor_rank],
                )
                for query_index, selected_successor in enumerate(
                    selected_successors
                ):
                    selected_predecessors[query_index][rank] = _logaddexp(
                        selected_predecessors[query_index][rank],
                        log_potential + selected_successor[successor_rank],
                    )
        return selected_predecessors, total_predecessor

    def _factor_transitions(
        self,
        factor: EndpointFactor,
        predecessor_rank: int,
    ) -> tuple[tuple[EndpointAlternative, int, float], ...]:
        if not 0 <= factor.target_index < len(self.space.zones):
            raise IndexError("Endpoint target zone index is out of range")
        predecessor = self.space.unrank(predecessor_rank)
        transitions: list[tuple[EndpointAlternative, int, float]] = []
        for alternative in factor.alternatives:
            if alternative.log_weight == -math.inf:
                continue
            source_index = alternative.source_index
            if source_index is None:
                successor_rank = predecessor_rank
                multiplicity = 0.0
            else:
                if not 0 <= source_index < len(self.space.locations):
                    raise IndexError("Endpoint source location index is out of range")
                if source_index == factor.target_index:
                    raise ValueError("Endpoint movement source and target must differ")
                count = predecessor[source_index]
                if count == 0:
                    continue
                successor_rank = self._operators.operator(
                    source_index,
                    factor.target_index,
                ).successors[predecessor_rank]
                multiplicity = _LOG_MULTIPLICITY[count]
            likelihood = (
                factor.occupied_log_likelihood
                if source_index is not None
                or predecessor[factor.target_index] > 0
                else factor.empty_log_likelihood
            )
            transitions.append(
                (
                    alternative,
                    successor_rank,
                    alternative.log_weight + multiplicity + likelihood,
                )
            )
        return tuple(transitions)

    def _assignment_atom(
        self,
        factor: EndpointFactor,
        alternative: EndpointAlternative,
        predecessor_rank: int,
        successor_rank: int,
    ) -> EndpointAssignmentAtom:
        return EndpointAssignmentAtom(
            factor.endpoint.token_id,
            alternative.alternative_id,
            alternative.disposition,
            predecessor_rank,
            successor_rank,
            alternative.source_index,
            factor.target_index,
            alternative.source_node_id,
            factor.endpoint.node_id,
            alternative.route_nodes,
            alternative.deadline,
            alternative.evidence_ids,
        )


def _logaddexp(first: float, second: float) -> float:
    if first == -math.inf:
        return second
    if second == -math.inf:
        return first
    maximum = max(first, second)
    return maximum + math.log(math.exp(first - maximum) + math.exp(second - maximum))


def _checked_probability(selected_mass: float, total_mass: float) -> float:
    probability = (
        0.0
        if selected_mass == -math.inf
        else math.exp(selected_mass - total_mass)
    )
    if probability < -1e-12 or probability > 1.0 + 1e-12:
        raise ValueError("Factor-chain joint-event probability is out of range")
    return min(1.0, max(0.0, probability))


def _assignment_identity(atom: EndpointAssignmentAtom) -> AssignmentIdentity:
    return AssignmentIdentity(
        atom.endpoint_id,
        atom.alternative_id,
        atom.predecessor_rank,
        atom.successor_rank,
    )


def _identity_sort_key(identity: AssignmentIdentity) -> tuple[object, ...]:
    return (
        identity.endpoint_id,
        identity.alternative_id,
        identity.predecessor_rank,
        identity.successor_rank,
    )
