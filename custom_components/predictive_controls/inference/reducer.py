"""Pure event fold for exact augmented occupancy inference."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from ..model import PredictiveMap
from .association import AugmentedLogMessage, EndpointFactor
from .episodes import EpisodeEmission, NodeEpisodeState, ObservationEpisodes
from .factor_chain import ExactFactorChain, ZoneLikelihoodStep
from .operators import CompleteMoveOperators
from .replay import RetainedObservation
from .routes import RouteCandidateBuilder
from .state_space import CompactLogPosterior, StateSpace
from .types import (
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    RouteEpisodeInterval,
    SupportEventAtom,
)

STAY_WEIGHT = 0.39
GRAPH_MOVEMENT_WEIGHT = 0.60
MISSED_MOVEMENT_WEIGHT = 0.01
UNLOCATED_MOVEMENT_WEIGHT = 0.65


@dataclass(frozen=True)
class InferenceReplayState:
    """Complete immutable result of one retained-input fold."""

    message: AugmentedLogMessage
    episode_states: tuple[NodeEpisodeState, ...]
    dispositions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FactorChainReplayState:
    """One deterministic replay result backed by a compact factor chain."""

    chain: ExactFactorChain
    episode_states: tuple[NodeEpisodeState, ...]
    dispositions: tuple[tuple[str, str], ...] = ()


class AugmentedEventReducer:
    """Rebuild exact episode and augmented state from a finalized base."""

    __slots__ = (
        "_map",
        "_operators",
        "_route_builder",
        "_space",
    )

    def __init__(
        self,
        predictive_map: PredictiveMap,
        space: StateSpace,
        operators: CompleteMoveOperators | None = None,
    ) -> None:
        if tuple(predictive_map.zones()) != space.zones:
            raise ValueError("Reducer state-space zones must match the map")
        self._map = predictive_map
        self._space = space
        if operators is not None and operators.space is not space:
            raise ValueError("Reducer and operators must share a state space")
        self._operators = operators or CompleteMoveOperators(space)
        self._route_builder = RouteCandidateBuilder(
            predictive_map,
            space,
            direct_log_weight=math.log(GRAPH_MOVEMENT_WEIGHT),
            censored_log_weight=math.log(GRAPH_MOVEMENT_WEIGHT),
        )

    def initial_state(
        self,
        posterior: CompactLogPosterior,
    ) -> InferenceReplayState:
        if posterior.space is not self._space:
            raise ValueError("Reducer posterior must use its exact state space")
        episodes = ObservationEpisodes(self._map)
        return InferenceReplayState(
            AugmentedLogMessage.from_posterior(posterior),
            episodes.states,
        )

    def reduce(
        self,
        base: InferenceReplayState,
        retained: tuple[RetainedObservation, ...],
    ) -> InferenceReplayState:
        if base.message.space is not self._space:
            raise ValueError("Replay base must use the reducer state space")
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(base.episode_states)
        message = base.message
        dispositions: list[tuple[str, str]] = []
        for item in retained:
            for frontier_update in episodes.advance(item.event.event_at):
                for emission in frontier_update.emissions:
                    message = self._apply_emission(
                        message,
                        emission,
                        item.event.event_at,
                        episodes.states,
                    )
            update = episodes.observe(item.event)
            for emission in update.emissions:
                message = self._apply_emission(
                    message,
                    emission,
                    item.event.event_at,
                    episodes.states,
                )
            dispositions.append((item.evidence_id, update.disposition))
        return InferenceReplayState(
            message,
            episodes.states,
            tuple(dispositions),
        )

    def advance(
        self,
        state: InferenceReplayState,
        through: datetime,
    ) -> tuple[InferenceReplayState, tuple[str, ...]]:
        """Advance deterministic episode and assignment frontiers without evidence."""

        if state.message.space is not self._space:
            raise ValueError("Frontier state must use the reducer state space")
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(state.episode_states)
        message = state.message
        for update in episodes.advance(through):
            for emission in update.emissions:
                message = self._apply_emission(
                    message,
                    emission,
                    through,
                    episodes.states,
                )
        before = _context_endpoint_ids(message)
        message = message.finalize(through).expire_support(through)
        consumed = tuple(sorted(before - _context_endpoint_ids(message)))
        return (
            InferenceReplayState(message, episodes.states, state.dispositions),
            consumed,
        )

    def _apply_emission(
        self,
        message: AugmentedLogMessage,
        emission: EpisodeEmission,
        event_at: datetime,
        episode_states: tuple[NodeEpisodeState, ...],
    ) -> AugmentedLogMessage:
        target_index = self._space.location_index(emission.zone)
        if emission.kind != "positive":
            return message.apply_zone_likelihood(
                target_index,
                empty_log_likelihood=emission.empty_log_likelihood,
                occupied_log_likelihood=emission.occupied_log_likelihood,
            )

        return self._endpoint_factor(emission, event_at, episode_states).apply(
            message,
            self._operators,
        )

    def _endpoint_factor(
        self,
        emission: EpisodeEmission,
        event_at: datetime,
        episode_states: tuple[NodeEpisodeState, ...],
    ) -> EndpointFactor:
        target_index = self._space.location_index(emission.zone)
        endpoint = EndpointToken(emission.episode_id, emission.node_id, event_at)
        intervals = tuple(
            interval
            for state in episode_states
            if (interval := _route_interval(state)) is not None
        )
        censored_sources = tuple(
            interval
            for state in episode_states
            if (
                interval := _censored_route_interval(
                    state,
                    event_at,
                    self._map.occupancy_behavior_for_node(
                        self._map.nodes[state.node_id]
                    ),
                )
            ) is not None
        )
        alternatives = [
            EndpointAlternative(
                f"stay:{endpoint.token_id}",
                "stay",
                None,
                None,
                (),
                math.log(STAY_WEIGHT),
                event_at,
                (emission.evidence_id,),
            ),
            *self._route_builder.build(
                endpoint,
                emission.zone,
                intervals,
                intervals,
                censored_sources=censored_sources,
            ),
            EndpointAlternative(
                f"unlocated:{endpoint.token_id}",
                "unlocated",
                self._space.unlocated_index,
                "unlocated",
                ("unlocated", emission.node_id),
                math.log(UNLOCATED_MOVEMENT_WEIGHT),
                event_at,
                (emission.evidence_id,),
            ),
        ]
        alternatives.extend(
            EndpointAlternative(
                f"missed:{source_zone}:{endpoint.token_id}",
                "missed_movement",
                source_index,
                f"zone:{source_zone}",
                (f"zone:{source_zone}", emission.node_id),
                math.log(MISSED_MOVEMENT_WEIGHT),
                event_at,
                (emission.evidence_id,),
            )
            for source_index, source_zone in enumerate(self._space.zones)
            if source_zone != emission.zone
        )
        return EndpointFactor(
            endpoint,
            target_index,
            emission.zone,
            tuple(alternatives),
            emission.empty_log_likelihood,
            emission.occupied_log_likelihood,
            frozenset(
                self._space.location_index(state.zone)
                for state in episode_states
                if state.current_positive
                and self._map.occupancy_behavior_for_node(
                    self._map.nodes[state.node_id]
                )
                == "sustained"
            ),
        )


class FactorChainEventReducer:
    """Pure retained-input fold over the exact compact factor chain."""

    __slots__ = ("_endpoint_builder", "_map", "_space")

    def __init__(
        self,
        predictive_map: PredictiveMap,
        space: StateSpace,
        operators: CompleteMoveOperators | None = None,
    ) -> None:
        self._endpoint_builder = AugmentedEventReducer(
            predictive_map,
            space,
            operators,
        )
        self._map = predictive_map
        self._space = space

    @property
    def operators(self) -> CompleteMoveOperators:
        return self._endpoint_builder._operators  # noqa: SLF001

    def initial_state(
        self,
        posterior: CompactLogPosterior,
    ) -> FactorChainReplayState:
        if posterior.space is not self._space:
            raise ValueError("Reducer posterior must use its exact state space")
        episodes = ObservationEpisodes(self._map)
        return FactorChainReplayState(ExactFactorChain(posterior), episodes.states)

    def reduce(
        self,
        base: FactorChainReplayState,
        retained: tuple[RetainedObservation, ...],
    ) -> FactorChainReplayState:
        if base.chain.space is not self._space:
            raise ValueError("Replay base must use the reducer state space")
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(base.episode_states)
        chain = base.chain
        dispositions: list[tuple[str, str]] = []
        for item in retained:
            chain = self._apply_chain_emissions(
                chain,
                tuple(
                    emission
                    for frontier_update in episodes.advance(item.event.event_at)
                    for emission in frontier_update.emissions
                ),
                item.event.event_at,
                episodes.states,
            )
            update = episodes.observe(item.event)
            chain = self._apply_chain_emissions(
                chain,
                update.emissions,
                item.event.event_at,
                episodes.states,
            )
            dispositions.append((item.evidence_id, update.disposition))
        return FactorChainReplayState(
            chain,
            episodes.states,
            tuple(dispositions),
        )

    def advance(
        self,
        state: FactorChainReplayState,
        through: datetime,
    ) -> tuple[FactorChainReplayState, tuple[str, ...]]:
        if state.chain.space is not self._space:
            raise ValueError("Frontier state must use the reducer state space")
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(state.episode_states)
        chain = state.chain
        chain = self._apply_chain_emissions(
            chain,
            tuple(
                emission
                for update in episodes.advance(through)
                for emission in update.emissions
            ),
            through,
            episodes.states,
        )
        chain, consumed = chain.compact(
            through,
            lambda factor, atom: self._finalization_support(
                factor,
                atom,
                through,
                episodes.states,
            ),
            current_sustained_episode_ids=frozenset(
                state.episode_id
                for state in episodes.states
                if state.current_positive
                and state.episode_id is not None
                and self._map.occupancy_behavior_for_node(
                    self._map.nodes[state.node_id]
                )
                == "sustained"
            ),
        )
        return (
            FactorChainReplayState(chain, episodes.states, state.dispositions),
            consumed,
        )

    def _finalization_support(
        self,
        factor: EndpointFactor,
        atom: EndpointAssignmentAtom,
        watermark: datetime,
        episode_states: tuple[NodeEpisodeState, ...],
    ) -> SupportEventAtom | None:
        source_index = atom.source_index
        support_id = (
            f"assignment:{atom.endpoint_id}:{atom.alternative_id}:"
            f"{atom.predecessor_rank}:{atom.successor_rank}"
        )
        if (
            source_index is not None
            and source_index != self._space.unlocated_index
            and atom.disposition
            in {"graph_valid", "censored_graph_path", "missed_movement"}
        ):
            return SupportEventAtom(
                support_id,
                atom.disposition,
                self._space.locations[source_index],
                factor.target_zone,
                atom.route_nodes,
                (atom.endpoint_id,),
                (),
                factor.endpoint.event_at,
                watermark,
                atom.disposition == "graph_valid",
            )
        if atom.disposition not in {"stay", "unlocated"}:
            return None
        if self._space.unrank(atom.successor_rank)[factor.target_index] == 0:
            return None
        target_state = next(
            (
                state
                for state in episode_states
                if state.node_id == factor.endpoint.node_id
            ),
            None,
        )
        if (
            target_state is None
            or not target_state.current_positive
            or target_state.episode_id != factor.endpoint.token_id
        ):
            return None
        return SupportEventAtom(
            support_id,
            "stay",
            factor.target_zone,
            factor.target_zone,
            (factor.endpoint.node_id,),
            (),
            (factor.endpoint.token_id,),
            target_state.started_at or factor.endpoint.event_at,
            watermark,
            False,
        )

    def _apply_chain_emission(
        self,
        chain: ExactFactorChain,
        emission: EpisodeEmission,
        event_at: datetime,
        episode_states: tuple[NodeEpisodeState, ...],
    ) -> ExactFactorChain:
        if emission.kind == "positive":
            return chain.apply_endpoint(
                self._endpoint_builder._endpoint_factor(  # noqa: SLF001
                    emission,
                    event_at,
                    episode_states,
                )
            )
        return chain.apply_zone_likelihood(
            self._space.location_index(emission.zone),
            empty_log_likelihood=emission.empty_log_likelihood,
            occupied_log_likelihood=emission.occupied_log_likelihood,
            event_at=event_at,
        )

    def _apply_chain_emissions(
        self,
        chain: ExactFactorChain,
        emissions: tuple[EpisodeEmission, ...],
        event_at: datetime,
        episode_states: tuple[NodeEpisodeState, ...],
    ) -> ExactFactorChain:
        pending: list[ZoneLikelihoodStep] = []
        for emission in emissions:
            if emission.kind != "positive":
                pending.append(
                    ZoneLikelihoodStep(
                        self._space.location_index(emission.zone),
                        emission.empty_log_likelihood,
                        emission.occupied_log_likelihood,
                        event_at,
                    )
                )
                continue
            chain = chain.apply_zone_likelihoods(tuple(pending))
            pending.clear()
            chain = self._apply_chain_emission(
                chain,
                emission,
                event_at,
                episode_states,
            )
        return chain.apply_zone_likelihoods(tuple(pending))


def _route_interval(
    state: NodeEpisodeState,
) -> RouteEpisodeInterval | None:
    if (
        state.episode_id is None
        or state.started_at is None
        or not state.positive_emitted
    ):
        return None
    if state.current_positive:
        valid_until = state.endpoint_valid_until or state.started_at
    else:
        valid_until = (
            state.finalized_at
            or state.latest_clear_at
            or state.last_event_at
            or state.started_at
        )
    return RouteEpisodeInterval(
        state.node_id,
        state.zone,
        state.episode_id,
        state.started_at,
        max(state.started_at, valid_until),
        (state.episode_id,),
        state.current_positive,
        state.endpoint_valid_until,
    )


def _censored_route_interval(
    state: NodeEpisodeState,
    event_at: datetime,
    occupancy_behavior: str,
) -> RouteEpisodeInterval | None:
    interval = _route_interval(state)
    if (
        interval is None
        or not state.current_positive
        or occupancy_behavior != "sustained"
    ):
        return interval
    return replace(interval, valid_until=max(interval.valid_until, event_at))


def _context_endpoint_ids(message: AugmentedLogMessage) -> set[str]:
    return {
        atom.endpoint_id
        for key, _ in message.entries
        for atom in key.contexts
    }
