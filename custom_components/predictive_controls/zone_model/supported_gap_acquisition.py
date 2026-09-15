"""REQ-TRAV-021: bounded target-only acquisition, never inferred traversal."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from ..model import PredictiveMap
from .profiles import SHARED_PROFILES
from .types import (
    AnonymousOccupancySupport,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    SupportTokenBinding,
    TraversalToken,
)

MISSING_FORWARD_EDGE_SECONDS = 15.0
MAX_GAP_SECONDS = 30.0


def gap_geometry_valid(
    predictive_map: PredictiveMap,
    nodes: Mapping[str, PhysicalNode],
    source_id: str,
    target_id: str,
    source_at: datetime,
    at: datetime,
) -> bool:
    """Check historical geometry/time without requiring live source ownership."""

    source = nodes.get(source_id)
    target = nodes.get(target_id)
    if (
        source is None
        or target is None
        or source_id == target_id
        or source.zone == target.zone
        or source.interaction_aliases
        or target.interaction_aliases
        or SHARED_PROFILES[source.profile_name].role != "transition"
        or target_id in predictive_map.neighbors(source_id)
    ):
        return False
    profile = SHARED_PROFILES[source.profile_name]
    original_until = source_at + min(
        profile.traversal_context_window, profile.assertion_trust_horizon
    )
    elapsed = (at - source_at).total_seconds()
    if not 0 < elapsed < MAX_GAP_SECONDS or at >= original_until:
        return False
    # Do not use first-hit BFS: a shorter first route may fail while another fits.
    for middle_id in sorted(predictive_map.neighbors(source_id)):
        middle = nodes.get(middle_id)
        if (
            middle is None
            or middle.interaction_aliases
            or SHARED_PROFILES[middle.profile_name].role != "transition"
            or target_id not in predictive_map.neighbors(middle_id)
        ):
            continue
        durations = tuple(
            MISSING_FORWARD_EDGE_SECONDS if seconds is None else seconds
            for seconds in (
                predictive_map.transition_seconds_between_nodes(source_id, middle_id),
                predictive_map.transition_seconds_between_nodes(middle_id, target_id),
            )
        )
        if all(math.isfinite(value) and value > 0 for value in durations) and (
            elapsed < min(MAX_GAP_SECONDS, sum(durations))
        ):
            return True
    return False


def original_handoff_valid(
    predictive_map: PredictiveMap,
    nodes: Mapping[str, PhysicalNode],
    token: TraversalToken,
    at: datetime,
    *,
    historical: bool = False,
) -> bool:
    """Prove original handoff authority; only later reopening is history-safe."""

    source = nodes.get(token.node_id)
    path = token.path_node_ids
    if (
        source is None
        or source.interaction_aliases
        or token.zone != source.zone
        or token.profile_name != source.profile_name
        or token.role != "transition"
        or SHARED_PROFILES[source.profile_name].role != "transition"
        or token.token_id != f"{token.node_id}:{token.episode_id}"
        or token.provenance_kind != "settled_adjacent_transfer"
        or token.track_confidence != "provisional"
        or not token.equivalent_confirmed_strength
        or len(path) != 2
        or path[-1] != token.node_id
        or path[0] not in nodes
        or nodes[path[0]].zone == source.zone
        or nodes[path[0]].interaction_aliases
        or SHARED_PROFILES[nodes[path[0]].profile_name].role != "stay"
        or token.node_id not in predictive_map.neighbors(path[0])
    ):
        return False
    profile = SHARED_PROFILES[source.profile_name]
    original_until = token.accepted_at + min(
        profile.traversal_context_window, profile.assertion_trust_horizon
    )
    reopened = token.continuity_reopened_at
    return bool(
        token.accepted_at < at < original_until
        and (
            (reopened is None and token.valid_until == original_until)
            or (historical and reopened is not None and reopened > at)
        )
    )


def select_supported_gap_source(
    predictive_map: PredictiveMap,
    nodes: Mapping[str, PhysicalNode],
    target: EpisodeState,
    effect: EpisodeEffect,
    count: CountState,
    tokens: Sequence[TraversalToken],
    episodes: Sequence[EpisodeState],
    supports: Sequence[AnonymousOccupancySupport],
    bindings: Sequence[SupportTokenBinding],
) -> TraversalToken | None:
    """Read the same event frontier only after ordinary authority has failed."""

    node = nodes.get(target.node_id)
    at = effect.at
    if (
        count.expected_count <= 0
        or node is None
        or node.interaction_aliases
        or target.zone != node.zone
        or target.profile_name != node.profile_name
        or effect.kind not in {"positive", "correlated_positive"}
        or (effect.kind == "correlated_positive" and not target.cadence_correlated)
        or effect.node_id != target.node_id
        or effect.zone != target.zone
        or effect.episode_id != target.episode_id
        or target.started_at != at
        or target.status != "asserted"
        or not target.known_on
        or target.health_warning
        or target.cadence_warning
        or target.traversal_valid_until is None
        or target.traversal_valid_until != at + min(
            SHARED_PROFILES[node.profile_name].traversal_context_window,
            SHARED_PROFILES[node.profile_name].assertion_trust_horizon,
        )
        or target.traversal_valid_until <= at
        or not 0 < effect.reliability <= 1
    ):
        return None
    states = {state.node_id: state for state in episodes}
    supported = {support.support_id: support for support in supports}
    bound = {binding.token_id: binding.support_id for binding in bindings}
    eligible: dict[str, TraversalToken] = {}
    for token in tokens:
        source = states.get(token.node_id)
        support = supported.get(bound.get(token.token_id, ""))
        if (
            not original_handoff_valid(predictive_map, nodes, token, at)
            or source is None
            or source.episode_id != token.episode_id
            or source.zone != token.zone
            or source.profile_name != token.profile_name
            or source.started_at != token.accepted_at
            or source.traversal_valid_until != token.valid_until
            or source.status != "asserted"
            or not source.known_on
            or source.health_warning
            or source.cadence_warning
            or support is None
            or support.state != "moving"
            or support.current_node_id != token.node_id
            or support.current_zone != token.zone
            or support.current_episode_id != token.episode_id
            or support.path_node_ids != token.path_node_ids
            or support.provenance_kind != token.provenance_kind
            or support.updated_at != token.accepted_at
            or support.valid_until != token.valid_until
            or not gap_geometry_valid(
                predictive_map, nodes, token.node_id, target.node_id,
                token.accepted_at, at,
            )
        ):
            continue
        eligible[token.token_id] = token
    return next(iter(eligible.values())) if len(eligible) == 1 else None
