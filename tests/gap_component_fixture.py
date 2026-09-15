"""Validated synthetic REQ-TRAV-021 inputs, never engine/public acceptance.

Like handoff_component_fixture.handoff_proposal, declare a settled component
support from a real confirmed three-node origin, then authorize, issue and commit
the real REQ-TRAV-018 handoff. Do not inject inference into ZoneModelEngine or
claim that selected-path production creates these retired support/token records.

The gap suite retains its assertion ASTs: its local name ``engine`` and read-only
``_map``/``_nodes``/``snapshot`` spellings therefore remain. GapComponents is only
an immutable input bundle, with no engine, policy, prediction or lifecycle API.
Physical states come from observations and pass actual component restore checks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supported_gap_acquisition import (
    select_supported_gap_source,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    SensorInput,
    SupportTokenBinding,
    TraversalToken,
)


@dataclass(frozen=True)
class GapComponentSnapshot:
    """Only selector inputs; not a serializable whole-model snapshot."""

    count_state: CountState
    traversal_tokens: tuple[TraversalToken, ...]
    episode_states: tuple[EpisodeState, ...]
    anonymous_supports: tuple[AnonymousOccupancySupport, ...]
    support_token_bindings: tuple[SupportTokenBinding, ...]


@dataclass(frozen=True)
class GapComponents:
    """Explicit component values with assertion-compatible projection names."""

    _map: PredictiveMap
    _nodes: tuple[PhysicalNode, ...]
    snapshot: GapComponentSnapshot


def _validate(components: GapComponents, at: datetime) -> PhysicalEpisodes:
    """Restore real components, including the moving token/binding prerequisite."""
    snapshot = components.snapshot
    episodes = PhysicalEpisodes(components._nodes)
    episodes.restore_snapshot(snapshot.episode_states)
    frontier = TraversalFrontier(components._map, components._nodes)
    frontier.restore_snapshot(
        snapshot.traversal_tokens,
        tuple(token.token_id for token in snapshot.traversal_tokens), (), at,
    )
    tracker = AnonymousSupportTracker(components._map, components._nodes)
    tracker.restore(
        snapshot.anonymous_supports, snapshot.support_token_bindings, at,
    )
    # A structural restore alone does not prove moving support has a live token.
    tracker.advance(at, episodes.states, (), frontier.tokens, ())
    assert tracker.supports == snapshot.anonymous_supports
    assert tracker.bindings == snapshot.support_token_bindings
    return episodes


def _require_selected(
    components: GapComponents, target: EpisodeState, effect: EpisodeEffect,
) -> None:
    """Positive control before any test mutation can reach a negative guard."""
    snapshot = components.snapshot
    source, = snapshot.traversal_tokens
    selected = select_supported_gap_source(
        components._map, {node.node_id: node for node in components._nodes},
        target, effect, snapshot.count_state, snapshot.traversal_tokens,
        snapshot.episode_states, snapshot.anonymous_supports,
        snapshot.support_token_bindings,
    )
    assert selected == source


def gap_source_components(
    predictive_map: PredictiveMap, origin: datetime, *, source_id: str = "source",
    stay_id: str = "stay",
) -> GapComponents:
    """Real component handoff at origin+200s; original token expires at +245s.

    ``source_id``/``stay_id`` also permit an independently qualified alternative
    with a distinct observed origin, never two timestamps for one generation.
    This remains component composition, not selected-engine reachability.
    """
    def at(seconds: float) -> datetime:
        return origin + timedelta(seconds=seconds)

    def observation(node: str, state: str, seconds: float) -> SensorInput:
        return SensorInput(f"binary_sensor.{node}", state, at(seconds))

    build = build_physical_nodes(predictive_map)
    assert not build.errors
    episodes = PhysicalEpisodes(build.nodes)
    filters = {
        node.zone: ZoneBeliefFilter(
            node.zone, BELIEF_PROFILES[node.profile_name], origin,
        ) for node in build.nodes
    }
    frontier = TraversalFrontier(predictive_map, build.nodes)
    for seconds, node_id in enumerate(("seed", "bridge", stay_id)):
        update = episodes.observe(observation(node_id, "on", seconds))
        positive, = update.effects
        filters[node_id].apply_positive(positive.episode_id, positive.at)
        authorization = frontier.authorize(update.state, positive.at, count=None)
        if authorization.authorized:
            frontier.issue(update.state, positive, authorization)
            filters[node_id].apply_arrival_transition(positive.episode_id, positive.at)
    origin_token = next(token for token in frontier.tokens if token.node_id == stay_id)
    assert origin_token.track_confidence == "confirmed"
    assert origin_token.path_node_ids == ("seed", "bridge", stay_id)
    settled = AnonymousOccupancySupport(
        f"support:{origin_token.token_id}", "settled", at(2), at(2),
        origin_token.episode_id, stay_id, stay_id, origin_token.path_node_ids,
        origin_token.provenance_kind, None, "created",
    )
    episodes.observe(observation("seed", "off", 10))
    episodes.observe(observation("bridge", "off", 11))
    for update in episodes.advance(at(200)):
        for clear in update.effects:
            assert clear.kind == "stable_clear"
            filters[clear.zone].apply_stable_clear(clear.episode_id, clear.at)
    frontier.advance(at(200))
    assert not frontier.tokens and not frontier.pending_candidates
    tracker = AnonymousSupportTracker(predictive_map, build.nodes)
    tracker.restore(
        (settled,), tuple(
            SupportTokenBinding(token.token_id, settled.support_id)
            for token in frontier.retained_tokens
        ), at(200),
    )

    source = episodes.observe(observation(source_id, "on", 200))
    effect, = source.effects
    assert effect.kind == "positive"
    filters[source_id].apply_positive(effect.episode_id, effect.at)
    filters[source_id].apply_arrival_transition(effect.episode_id, effect.at)
    beliefs = tuple(filters[zone].advance(effect.at) for zone in sorted(filters))
    selection = tracker.settled_adjacent_for(
        source.state, effect, episodes.states, beliefs,
    )
    assert selection is not None
    authorization = frontier.authorize(
        source.state, effect.at, count=None, handoff_resolver=lambda: selection,
    )
    assert authorization.reason == "settled_adjacent_transfer"
    token = frontier.issue(source.state, effect, authorization)
    prepared = tracker.prepare_handoff(
        effect.at, effect, authorization, token, episodes.states, beliefs,
        frontier.tokens,
    )
    applied = tracker.apply(
        effect.at, effect, authorization, token, episodes.states, beliefs,
        frontier.tokens, frontier.retained_tokens, prepared_handoff=prepared,
    )
    assert applied == prepared
    moving, = tracker.supports
    assert moving.support_id == settled.support_id
    assert moving.created_at == settled.created_at
    assert moving.state == "moving" and moving.current_node_id == source_id
    assert moving.current_episode_id == token.episode_id == source.state.episode_id
    assert moving.path_node_ids == token.path_node_ids == (stay_id, source_id)
    assert moving.provenance_kind == token.provenance_kind == authorization.reason
    assert moving.updated_at == token.accepted_at == source.state.started_at == at(200)
    assert moving.valid_until == token.valid_until == source.state.traversal_valid_until
    assert token.valid_until == at(245) and token.continuity_reopened_at is None
    assert token.track_confidence == "provisional"
    assert token.equivalent_confirmed_strength
    assert tracker.bindings == (SupportTokenBinding(token.token_id, moving.support_id),)
    for state in beliefs:
        restored = ZoneBeliefFilter.restore(BELIEF_PROFILES[state.profile_name], state)
        assert restored.state == state
    TraversalFrontier(predictive_map, build.nodes).restore_snapshot(
        frontier.tokens, frontier.current_token_ids, frontier.uses, effect.at,
        frontier.pending_candidates, frontier.retained_tokens,
    )
    components = GapComponents(predictive_map, build.nodes, GapComponentSnapshot(
        CountState(2), frontier.tokens, episodes.states,
        tracker.supports, tracker.bindings,
    ))
    # Isolated microsecond target proves a valid source even for short directed
    # budgets. It is never installed into the returned source component states.
    probe = _validate(components, effect.at)
    target = probe.observe(observation("target", "on", 200.000001))
    positive, = target.effects
    _require_selected(components, target.state, positive)
    return components


def gap_target_components(
    predictive_map: PredictiveMap, origin: datetime,
) -> tuple[GapComponents, EpisodeState, EpisodeEffect]:
    """Ordinary observed target at +212s, validated before negative mutations."""
    components = gap_source_components(predictive_map, origin)
    at = origin + timedelta(seconds=212)
    episodes = _validate(components, at)
    episodes.advance(at)
    target = episodes.observe(SensorInput("binary_sensor.target", "on", at))
    effect, = target.effects
    assert effect.kind == "positive" and not target.state.cadence_correlated
    components = replace(components, snapshot=replace(
        components.snapshot, episode_states=episodes.states,
    ))
    _validate(components, at)
    _require_selected(components, target.state, effect)
    return components, target.state, effect
