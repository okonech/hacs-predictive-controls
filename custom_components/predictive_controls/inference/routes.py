"""Exact graph route alternatives for one positive endpoint."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta

from ..model import PredictiveMap
from .association import DifferenceBoundMatrix
from .state_space import StateSpace
from .types import (
    DifferenceConstraint,
    EndpointAlternative,
    EndpointToken,
    RouteEpisodeInterval,
    TemporalInterval,
)

DEFAULT_EDGE_DURATION = timedelta(seconds=30)


class RouteCandidateBuilder:
    """Build every exact direct and open-gate route into one endpoint."""

    __slots__ = (
        "_map",
        "_space",
        "censored_log_weight",
        "default_edge_duration",
        "direct_log_weight",
    )

    def __init__(
        self,
        predictive_map: PredictiveMap,
        space: StateSpace,
        *,
        direct_log_weight: float,
        censored_log_weight: float,
        default_edge_duration: timedelta = DEFAULT_EDGE_DURATION,
    ) -> None:
        if set(space.zones) != set(predictive_map.zones()):
            raise ValueError("Route builder state-space zones must match the map")
        if default_edge_duration <= timedelta(0):
            raise ValueError("Default edge duration must be positive")
        if not math.isfinite(direct_log_weight) or not math.isfinite(
            censored_log_weight
        ):
            raise ValueError("Route log weights must be finite")
        self._map = predictive_map
        self._space = space
        self.direct_log_weight = direct_log_weight
        self.censored_log_weight = censored_log_weight
        self.default_edge_duration = default_edge_duration

    def build(
        self,
        endpoint: EndpointToken,
        target_zone: str,
        sources: Sequence[RouteEpisodeInterval],
        gates: Sequence[RouteEpisodeInterval] = (),
    ) -> tuple[EndpointAlternative, ...]:
        if target_zone not in self._space.zones:
            raise ValueError("Route target zone is not in the state space")
        target_node = self._map.nodes.get(endpoint.node_id)
        if target_node is None or target_node.occupancy_zone != target_zone:
            raise ValueError("Route target does not match its map node")
        _validate_unique_episodes(sources, "source")
        _validate_unique_episodes(gates, "gate")

        alternatives: list[EndpointAlternative] = []
        for source in sorted(sources, key=_episode_key):
            source_node = self._map.nodes.get(source.node_id)
            if source_node is None or source_node.occupancy_zone != source.zone:
                raise ValueError("Route source does not match its map node")
            if source.zone == target_zone:
                continue
            source_index = self._space.location_index(source.zone)
            if endpoint.node_id in self._map.neighbors(source.node_id):
                deadline = self._direct_deadline(source, endpoint)
                if deadline is not None:
                    alternatives.append(
                        EndpointAlternative(
                            f"direct:{source.episode_id}:{endpoint.token_id}",
                            "graph_valid",
                            source_index,
                            source.node_id,
                            (source.node_id, endpoint.node_id),
                            self.direct_log_weight,
                            deadline,
                            _evidence_ids(source, endpoint),
                        )
                    )
            for gate in sorted(gates, key=_episode_key):
                deadline = self._censored_deadline(source, gate, endpoint)
                if deadline is None:
                    continue
                alternatives.append(
                    EndpointAlternative(
                        (
                            f"censored:{source.episode_id}:{gate.episode_id}:"
                            f"{endpoint.token_id}"
                        ),
                        "censored_graph_path",
                        source_index,
                        source.node_id,
                        (source.node_id, gate.node_id, endpoint.node_id),
                        self.censored_log_weight,
                        deadline,
                        _evidence_ids(source, endpoint, gate),
                    )
                )
        return tuple(
            sorted(
                alternatives,
                key=lambda alternative: alternative.alternative_id,
            )
        )

    def _direct_deadline(
        self,
        source: RouteEpisodeInterval,
        endpoint: EndpointToken,
    ) -> datetime | None:
        duration = self._edge_duration(source.node_id, endpoint.node_id)
        latest_target = source.valid_until + duration
        if latest_target < endpoint.event_at:
            return None
        matrix = DifferenceBoundMatrix.solve(
            ("source", "target"),
            (
                TemporalInterval("source", source.valid_from, source.valid_until),
                TemporalInterval("target", endpoint.event_at, latest_target),
            ),
            (
                DifferenceConstraint("source", "target", timedelta(0)),
                DifferenceConstraint("target", "source", duration),
            ),
        )
        return None if matrix is None else matrix.upper_bound("target")

    def _censored_deadline(
        self,
        source: RouteEpisodeInterval,
        gate: RouteEpisodeInterval,
        endpoint: EndpointToken,
    ) -> datetime | None:
        gate_node = self._map.nodes.get(gate.node_id)
        if gate_node is None or gate_node.occupancy_zone != gate.zone:
            raise ValueError("Route gate does not match its map node")
        if (
            len({source.node_id, gate.node_id, endpoint.node_id}) != 3
            or not gate.current_positive
            or gate.endpoint_blocked_until is None
            or endpoint.event_at > gate.endpoint_blocked_until
            or (
                self._map.occupancy_behavior_for_node(gate_node) != "transient"
                and gate_node.role != "transition_gate"
            )
            or gate.node_id not in self._map.neighbors(source.node_id)
            or endpoint.node_id not in self._map.neighbors(gate.node_id)
        ):
            return None
        source_to_gate = self._edge_duration(source.node_id, gate.node_id)
        gate_to_target = self._edge_duration(gate.node_id, endpoint.node_id)
        latest_target = min(
            source.valid_until + source_to_gate + gate_to_target,
            gate.valid_until + gate_to_target,
            gate.endpoint_blocked_until,
        )
        if latest_target < endpoint.event_at:
            return None
        matrix = DifferenceBoundMatrix.solve(
            ("source", "gate", "target"),
            (
                TemporalInterval("source", source.valid_from, source.valid_until),
                TemporalInterval("gate", gate.valid_from, gate.valid_until),
                TemporalInterval("target", endpoint.event_at, latest_target),
            ),
            (
                DifferenceConstraint("source", "gate", timedelta(0)),
                DifferenceConstraint("gate", "source", source_to_gate),
                DifferenceConstraint("gate", "target", timedelta(0)),
                DifferenceConstraint("target", "gate", gate_to_target),
            ),
        )
        return None if matrix is None else matrix.upper_bound("target")

    def _edge_duration(self, source_node_id: str, target_node_id: str) -> timedelta:
        configured = self._map.transition_seconds_between_nodes(
            source_node_id,
            target_node_id,
        )
        return (
            self.default_edge_duration
            if configured is None
            else timedelta(seconds=configured)
        )


def _validate_unique_episodes(
    episodes: Sequence[RouteEpisodeInterval],
    label: str,
) -> None:
    episode_ids = tuple(episode.episode_id for episode in episodes)
    if len(set(episode_ids)) != len(episode_ids):
        raise ValueError(f"Route {label} episode IDs must be unique")


def _episode_key(episode: RouteEpisodeInterval) -> tuple[object, ...]:
    return episode.valid_from, episode.node_id, episode.episode_id


def _evidence_ids(
    source: RouteEpisodeInterval,
    endpoint: EndpointToken,
    gate: RouteEpisodeInterval | None = None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *source.evidence_ids,
                *(gate.evidence_ids if gate is not None else ()),
                endpoint.token_id,
            }
        )
    )
