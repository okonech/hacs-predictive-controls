"""Explicit REQ-TRAV-018 component inputs, not selected-engine acceptance.

The settled support is a declared synthetic component premise. Physical episode
and filter transitions, traversal authorization/issuance, support restore and
handoff validation are real APIs, with unchanged profiles. This does not restore
legacy engine behavior, qualify publication ordering, or reconstruct an incident.
The caller retains those integration qualifications separately.
"""

from __future__ import annotations

from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    EpisodeEffect,
    EpisodeState,
    SettledAdjacentHandoff,
    SupportTokenBinding,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
)
from tests.test_zone_model_handoff import _at, _input, _map


def handoff_proposal(*, correlated: bool = False) -> tuple[
    AnonymousSupportTracker, EpisodeEffect, TraversalAuthorization, TraversalToken,
    tuple[EpisodeState, ...], tuple[ZoneBeliefState, ...], tuple[TraversalToken, ...],
]:
    """Return a valid uncommitted proposal with dormant and equal-time bindings.

    REQ-TRAV-018 owns selection, immutable source identity and idempotent transfer;
    REQ-COUNT-008 excludes dedicated tokens from generic support creation;
    REQ-STATE-009 supplies the target's ordinary half-open token lifetime.
    """
    predictive_map = _map()
    build = build_physical_nodes(predictive_map)
    assert not build.errors
    episodes = PhysicalEpisodes(build.nodes)
    filters = {
        node.zone: ZoneBeliefFilter(
            node.zone, BELIEF_PROFILES[node.profile_name], _at(-41),
        )
        for node in build.nodes
    }
    frontier = TraversalFrontier(predictive_map, build.nodes)
    if correlated:
        # Real independent target history, not a relabeled ordinary effect.
        primed = episodes.observe(_input("b", "on", -40))
        positive, = primed.effects
        filters["b"].apply_positive(positive.episode_id, positive.at)
        episodes.observe(_input("b", "off", -30))
        cleared = next(
            update for update in episodes.advance(_at(-20))
            if update.state.node_id == "b"
        )
        clear, = cleared.effects
        assert clear.kind == "stable_clear"
        filters["b"].apply_stable_clear(clear.episode_id, clear.at)

    # Compose component-owned provenance only; never run ZoneModelEngine/_seed.
    for seconds, node_id in enumerate(("x", "y", "a")):
        update = episodes.observe(_input(node_id, "on", seconds))
        positive, = update.effects
        filters[node_id].apply_positive(positive.episode_id, positive.at)
        source_authorization = frontier.authorize(
            update.state, positive.at, count=None,
        )
        if source_authorization.authorized:
            frontier.issue(update.state, positive, source_authorization)
            filters[node_id].apply_arrival_transition(positive.episode_id, positive.at)
    assert source_authorization.track_confidence == "confirmed"
    source_token = next(token for token in frontier.tokens if token.node_id == "a")
    assert source_token.path_node_ids == ("x", "y", "a")
    support = AnonymousOccupancySupport(
        f"support:{source_token.token_id}", "settled", _at(2), _at(2),
        source_token.episode_id, "a", "a", source_token.path_node_ids,
        source_token.provenance_kind, None, "created",
    )
    episodes.observe(_input("x", "off", 10))
    episodes.observe(_input("y", "off", 11))
    for update in episodes.advance(_at(302)):
        for clear in update.effects:
            assert clear.kind == "stable_clear"
            filters[clear.zone].apply_stable_clear(clear.episode_id, clear.at)
    frontier.advance(_at(302))
    assert not frontier.tokens and not frontier.pending_candidates
    retained = frontier.retained_tokens
    assert len(retained) == 3
    assert any(token.accepted_at < support.updated_at for token in retained)
    assert any(token.accepted_at == support.updated_at for token in retained)
    tracker = AnonymousSupportTracker(predictive_map, build.nodes)
    tracker.restore(
        (support,),
        tuple(
            SupportTokenBinding(token.token_id, support.support_id)
            for token in retained
        ),
        _at(302),
    )

    target = episodes.observe(_input("b", "on", 302))
    effect, = target.effects
    assert effect.kind == ("correlated_positive" if correlated else "positive")
    assert target.state.cadence_correlated is correlated
    if correlated:
        filters["b"].apply_correlated_positive(effect.episode_id, effect.at)
    else:
        filters["b"].apply_positive(effect.episode_id, effect.at)
    filters["b"].apply_arrival_transition(effect.episode_id, effect.at)
    beliefs = tuple(filters[zone].advance(effect.at) for zone in sorted(filters))

    def select() -> SettledAdjacentHandoff | None:
        return tracker.settled_adjacent_for(
            target.state, effect, episodes.states, beliefs,
        )

    if correlated:
        authorization = frontier.authorize_correlated_target(
            target.state, effect.at, handoff_resolver=select,
        )
        token = frontier.issue_correlated_continuation(
            target.state, effect, authorization, support_backed=True,
        )
    else:
        authorization = frontier.authorize(
            target.state, effect.at, count=None, handoff_resolver=select,
        )
        token = frontier.issue(target.state, effect, authorization)
    assert authorization.reason == "settled_adjacent_transfer"
    assert authorization.settled_handoff == select()
    assert not authorization.source_tokens and not authorization.new_uses
    assert token.track_confidence == "provisional"
    assert token.equivalent_confirmed_strength
    assert token.valid_until == target.state.traversal_valid_until == _at(482)
    assert tracker.supports == (support,) and len(tracker.bindings) == 3
    assert not any(tracker.counters.values())

    # Validate the unmutated fixture at genuine component restore boundaries.
    # These checks do not claim whole-engine persistence or public reachability.
    PhysicalEpisodes(build.nodes).restore_snapshot(episodes.states)
    for state in beliefs:
        restored = ZoneBeliefFilter.restore(BELIEF_PROFILES[state.profile_name], state)
        assert restored.state == state
    TraversalFrontier(predictive_map, build.nodes).restore_snapshot(
        frontier.tokens, frontier.current_token_ids, frontier.uses, effect.at,
        frontier.pending_candidates, retained,
    )
    return tracker, effect, authorization, token, episodes.states, beliefs, retained
