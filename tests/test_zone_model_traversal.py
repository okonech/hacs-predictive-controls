from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.count import (
    CountContext,
    CountInput,
)
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    AuthorizationUse,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    TraversalAuthorization,
    TraversalToken,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def graph() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "entry": {
                    "zone": "entry",
                    "role": "entry_boundary",
                    "entities": {"contact": "binary_sensor.entry"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "zone": "hall",
                    "floor": "downstairs",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": [
                        "entry",
                        "room_a",
                        "room_a_presence",
                        "room_b",
                        "middle",
                    ],
                    "transition_seconds": {"middle": 8},
                },
                "room_a": {
                    "zone": "room_a",
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.room_a"},
                    "adjacent": ["hall"],
                },
                "room_b": {
                    "zone": "room_b",
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.room_b"},
                    "adjacent": ["hall"],
                },
                "middle": {
                    "zone": "middle",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.middle"},
                    "adjacent": ["hall", "remote"],
                    "transition_seconds": {"remote": 8},
                },
                "remote": {
                    "zone": "remote",
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.remote"},
                    "adjacent": ["middle"],
                },
                "isolated": {
                    "zone": "isolated",
                    "floor": "upstairs",
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.isolated"},
                },
                "isolated_presence": {
                    "zone": "isolated",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.isolated_presence"},
                },
                "room_a_presence": {
                    "zone": "room_a",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.room_a_presence"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def node(node_id: str, zone: str, profile: str) -> PhysicalNode:
    return PhysicalNode(node_id, zone, (f"binary_sensor.{node_id}",), profile)


NODES = (
    node("entry", "entry", "entry_boundary"),
    node("hall", "hall", "transition_fast"),
    node("room_a", "room_a", "stay_pir"),
    node("room_b", "room_b", "stay_pir"),
    node("middle", "middle", "transition_fast"),
    node("remote", "remote", "stay_pir"),
    node("isolated", "isolated", "stay_pir"),
    node("isolated_presence", "isolated", "stay_presence"),
    node("room_a_presence", "room_a", "stay_presence"),
)


def episode(
    node_id: str,
    zone: str,
    profile: str,
    at: datetime,
    *,
    status: str = "asserted",
    valid_for: timedelta = timedelta(seconds=45),
) -> EpisodeState:
    episode_id = f"{node_id}:1:{at.isoformat()}"
    return EpisodeState(
        node_id,
        zone,
        profile,
        ((f"binary_sensor.{node_id}", "on"),),
        generation=1,
        episode_id=episode_id,
        status=status,
        started_at=at,
        last_event_at=at,
        advanced_at=at,
        traversal_valid_until=at + valid_for,
    )


def issue(frontier: TraversalFrontier, state: EpisodeState) -> TraversalToken:
    effect = EpisodeEffect(
        state.node_id,
        state.zone,
        state.episode_id or "",
        "positive",
        state.started_at or NOW,
    )
    authorization = TraversalAuthorization(
        state.node_id,
        state.zone,
        state.episode_id or "",
        state.started_at or NOW,
        True,
        "adjacent_authorized",
        track_confidence="provisional",
        path_node_ids=(state.node_id,),
        provenance_kind="test_seed",
    )
    return frontier.issue(state, effect, authorization)


def confirmed_departure_frontier() -> tuple[
    TraversalFrontier,
    EpisodeState,
    datetime,
]:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    assert not frontier.authorize(hall, NOW, count=None).authorized

    middle_at = NOW + timedelta(seconds=1)
    middle = episode("middle", "middle", "transition_fast", middle_at)
    middle_authorization = frontier.authorize(middle, middle_at, count=None)
    frontier.issue(
        middle,
        EpisodeEffect(
            "middle",
            "middle",
            middle.episode_id or "",
            "positive",
            middle_at,
        ),
        middle_authorization,
    )

    remote_at = NOW + timedelta(seconds=2)
    remote = episode(
        "remote",
        "remote",
        "stay_pir",
        remote_at,
        valid_for=timedelta(seconds=90),
    )
    remote_authorization = frontier.authorize(remote, remote_at, count=None)
    frontier.issue(
        remote,
        EpisodeEffect(
            "remote",
            "remote",
            remote.episode_id or "",
            "positive",
            remote_at,
        ),
        remote_authorization,
    )

    stable_clear_at = NOW + timedelta(seconds=8)
    frontier.advance(stable_clear_at)
    source = EpisodeState(
        "room_a",
        "room_a",
        "stay_pir",
        (("binary_sensor.room_a", "off"),),
        generation=1,
        episode_id="room_a:1:source",
        status="clear",
        started_at=NOW - timedelta(minutes=1),
        last_event_at=NOW + timedelta(seconds=3),
        advanced_at=stable_clear_at,
        clear_emitted=True,
    )
    return frontier, source, stable_clear_at


def test_interaction_authorization_requires_a_fresh_clearing_pulse() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    asserted = episode("room_a", "room_a", "stay_pir", NOW)

    with pytest.raises(ValueError, match="requires a fresh pulse"):
        frontier.authorize_interaction(asserted, NOW)


def test_confirmed_departure_lookup_requires_advanced_valid_clear() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode("room_a", "room_a", "stay_pir", NOW, status="clear")

    with pytest.raises(ValueError, match="requires an advanced frontier"):
        frontier.confirmed_departure_token(source, NOW)

    frontier.advance(NOW)
    assert (
        frontier.confirmed_departure_token(
            replace(source, started_at=None),
            NOW,
        )
        is None
    )
    assert frontier.confirmed_departure_token(source, NOW) is None


def test_confirmed_departure_lookup_requires_exact_authorization_chain() -> None:
    frontier, source, stable_clear_at = confirmed_departure_frontier()

    match = frontier.confirmed_departure_token(source, stable_clear_at)

    assert match is not None
    assert match.path_node_ids == ("hall", "middle", "remote")

    for removed_reason in {"provisional_track_acquired", "track_confirmed"}:
        restored = TraversalFrontier(graph(), NODES)
        restored.restore_snapshot(
            frontier.tokens,
            frontier.current_token_ids,
            tuple(use for use in frontier.uses if use.reason != removed_reason),
            stable_clear_at,
        )
        assert restored.confirmed_departure_token(source, stable_clear_at) is None


def test_confirmed_departure_lookup_rejects_timing_and_adjacency_inverses() -> None:
    frontier, source, stable_clear_at = confirmed_departure_frontier()

    assert (
        frontier.confirmed_departure_token(
            replace(source, started_at=NOW + timedelta(microseconds=1)),
            stable_clear_at,
        )
        is None
    )
    assert (
        frontier.confirmed_departure_token(
            replace(source, last_event_at=NOW + timedelta(seconds=1)),
            stable_clear_at,
        )
        is None
    )
    assert (
        frontier.confirmed_departure_token(
            replace(source, node_id="isolated", zone="isolated"),
            stable_clear_at,
        )
        is None
    )

    final_expiry = max(token.valid_until for token in frontier.tokens)
    frontier.advance(final_expiry)
    assert frontier.confirmed_departure_token(source, final_expiry) is None


def test_one_open_transition_authorizes_distinct_targets_once_each() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    token = issue(frontier, hall)
    frontier.sync(hall, NOW)
    room_a = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=2))
    room_b = episode("room_b", "room_b", "stay_pir", NOW + timedelta(seconds=5))

    first = frontier.authorize(room_a, room_a.started_at or NOW, count=None)
    duplicate = frontier.authorize(room_a, room_a.started_at or NOW, count=None)
    second = frontier.authorize(room_b, room_b.started_at or NOW, count=None)

    assert first.authorized and first.reason == "adjacent_authorized"
    assert second.authorized and second.reason == "adjacent_authorized"
    assert first.source_tokens == second.source_tokens == (token,)
    assert len(first.new_uses) == len(second.new_uses) == 1
    assert duplicate.authorized and duplicate.new_uses == ()
    assert len(frontier.tokens) == 1


def test_isolated_correlated_target_is_rejected_without_pending_authority() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = episode(
        "isolated_presence",
        "isolated",
        "stay_presence",
        NOW,
    )
    target = replace(
        target,
        cadence_run_started_at=NOW - timedelta(minutes=1),
        cadence_last_transition_at=NOW,
        cadence_cycle_count=2,
        cadence_correlated=True,
    )

    authorization = frontier.authorize_correlated_target(target, NOW)

    assert not authorization.authorized
    assert authorization.reason == "untracked_rejected"
    assert frontier.pending_candidates == ()
    assert frontier.tokens == ()
    assert frontier.uses == ()


def test_correlated_target_requires_current_trustworthy_episode() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = episode(
        "isolated_presence",
        "isolated",
        "stay_presence",
        NOW,
    )
    correlated = replace(
        target,
        cadence_run_started_at=NOW - timedelta(minutes=1),
        cadence_last_transition_at=NOW,
        cadence_cycle_count=1,
        cadence_correlated=True,
    )

    with pytest.raises(ValueError, match="current episode"):
        frontier.authorize_correlated_target(
            replace(correlated, cadence_correlated=False),
            NOW,
        )
    untrusted = replace(
        correlated,
        traversal_valid_until=NOW,
    )
    authorization = frontier.authorize_correlated_target(untrusted, NOW)
    assert not authorization.authorized
    assert authorization.reason == "untracked_rejected"


def test_adjacent_source_authorizes_correlated_target_without_target_authority(
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    source = issue(frontier, hall)
    frontier.sync(hall, NOW)
    target_at = NOW + timedelta(seconds=2)
    target = episode(
        "room_a_presence",
        "room_a",
        "stay_presence",
        target_at,
    )
    target = replace(
        target,
        cadence_run_started_at=NOW - timedelta(minutes=1),
        cadence_last_transition_at=target_at,
        cadence_cycle_count=2,
        cadence_correlated=True,
        cadence_warning=True,
        cadence_warning_reason="sustained_flapping",
    )

    authorization = frontier.authorize_correlated_target(target, target_at)

    assert authorization.authorized
    assert authorization.reason == "adjacent_authorized"
    assert authorization.source_tokens == (source,)
    assert len(authorization.new_uses) == 1
    assert frontier.pending_candidates == ()
    assert frontier.tokens == (source,)
    assert all(token.node_id != target.node_id for token in frontier.tokens)


def test_support_backed_correlated_continuation_issues_one_bounded_token() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    frontier.sync(hall, NOW)
    target_at = NOW + timedelta(seconds=2)
    target = replace(
        episode("room_a_presence", "room_a", "stay_presence", target_at),
        cadence_run_started_at=NOW - timedelta(minutes=1),
        cadence_last_transition_at=target_at,
        cadence_cycle_count=2,
        cadence_correlated=True,
    )
    authorization = frontier.authorize_correlated_target(target, target_at)
    effect = EpisodeEffect(
        target.node_id,
        target.zone,
        target.episode_id or "",
        "correlated_positive",
        target_at,
    )

    with pytest.raises(ValueError, match="authorized current positive episode"):
        frontier.issue(target, effect, authorization)
    with pytest.raises(ValueError, match="support-backed graph authority"):
        frontier.issue_correlated_continuation(
            target,
            effect,
            authorization,
            support_backed=False,
        )

    issued = frontier.issue_correlated_continuation(
        target,
        effect,
        authorization,
        support_backed=True,
    )
    duplicate = frontier.issue_correlated_continuation(
        target,
        effect,
        authorization,
        support_backed=True,
    )

    assert issued == duplicate
    assert issued.valid_until == target.traversal_valid_until
    assert sum(token.episode_id == target.episode_id for token in frontier.tokens) == 1


def test_recent_same_zone_missed_edge_and_disconnected_authorization() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    frontier.sync(replace(hall, status="clear"), NOW + timedelta(seconds=1))
    room_a = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=2))
    assert frontier.authorize(room_a, room_a.started_at or NOW, count=None).reason == (
        "adjacent_authorized"
    )

    room_a_token = issue(frontier, room_a)
    presence = episode(
        "room_a_presence", "room_a", "stay_presence", NOW + timedelta(seconds=3)
    )
    same_zone = frontier.authorize(presence, presence.started_at or NOW, count=None)
    assert same_zone.reason == "same_zone_authorized"
    assert room_a_token in same_zone.source_tokens

    remote = episode("remote", "remote", "stay_pir", NOW + timedelta(seconds=10))
    missed = frontier.authorize(remote, remote.started_at or NOW, count=None)
    assert missed.authorized and missed.reason == "missed_edge_authorized"

    isolated = episode("isolated", "isolated", "stay_pir", NOW + timedelta(seconds=11))
    rejected = frontier.authorize(isolated, isolated.started_at or NOW, count=None)
    assert rejected.authorized is False
    assert rejected.reason == "track_bootstrap_pending"


@pytest.mark.parametrize(
    ("elapsed_after_clear", "expected_authorized"),
    [
        (timedelta(seconds=15, microseconds=999999), True),
        (timedelta(seconds=16), True),
        (timedelta(seconds=16, microseconds=1), False),
    ],
)
def test_missed_edge_clear_anchor_obeys_directed_budget_boundary(
    elapsed_after_clear: timedelta,
    expected_authorized: bool,
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, source)
    clear_at = NOW + timedelta(seconds=20)
    cleared = replace(
        source,
        status="clear",
        last_event_at=clear_at,
        advanced_at=clear_at,
    )
    frontier.sync(cleared, clear_at)
    target_at = clear_at + elapsed_after_clear
    target = episode("remote", "remote", "stay_pir", target_at)

    authorization = frontier.authorize(
        target,
        target_at,
        count=None,
        corroborating_states=(cleared,),
    )

    assert authorization.authorized is expected_authorized
    assert authorization.reason == (
        "missed_edge_authorized"
        if expected_authorized
        else "track_bootstrap_pending"
    )


@pytest.mark.parametrize(
    "source_variant",
    [
        "missing",
        "mismatched",
        "asserted",
        "degraded",
        "unavailable",
        "stale",
        "future",
    ],
)
def test_missed_edge_nonmatching_clear_state_preserves_acceptance_timing(
    source_variant: str,
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, source)
    clear_at = NOW + timedelta(seconds=20)
    target_at = clear_at + timedelta(seconds=10)
    cleared = replace(
        source,
        status="clear",
        last_event_at=clear_at,
        advanced_at=clear_at,
    )
    variants = {
        "mismatched": replace(cleared, episode_id="other-episode"),
        "asserted": replace(cleared, status="asserted"),
        "degraded": replace(cleared, status="degraded"),
        "unavailable": replace(cleared, status="unavailable"),
        "stale": replace(cleared, last_event_at=NOW),
        "future": replace(
            cleared,
            last_event_at=target_at + timedelta(microseconds=1),
        ),
    }
    corroborating_states = (
        () if source_variant == "missing" else (variants[source_variant],)
    )
    target = episode("remote", "remote", "stay_pir", target_at)

    authorization = frontier.authorize(
        target,
        target_at,
        count=None,
        corroborating_states=corroborating_states,
    )

    assert not authorization.authorized
    assert authorization.reason == "track_bootstrap_pending"


def test_missed_edge_rejects_duplicate_source_identity() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    source = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, source)
    target_at = NOW + timedelta(seconds=10)
    target = episode("remote", "remote", "stay_pir", target_at)

    with pytest.raises(ValueError, match="duplicate identity"):
        frontier.authorize(
            target,
            target_at,
            count=None,
            corroborating_states=(source, source),
        )


def test_missed_edge_requires_timing_for_both_directed_hops() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["middle"],
                    "transition_seconds": {"middle": 8},
                },
                "middle": {
                    "zone": "middle",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.middle"},
                    "adjacent": ["hall", "remote"],
                },
                "remote": {
                    "zone": "remote",
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.remote"},
                    "adjacent": ["middle"],
                },
            }
        }
    )
    frontier = TraversalFrontier(
        predictive_map,
        tuple(
            physical_node
            for physical_node in NODES
            if physical_node.node_id in {"hall", "middle", "remote"}
        ),
    )
    source = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, source)
    clear_at = NOW + timedelta(seconds=20)
    cleared = replace(
        source,
        status="clear",
        last_event_at=clear_at,
        advanced_at=clear_at,
    )
    frontier.sync(cleared, clear_at)
    target_at = clear_at + timedelta(seconds=10)
    target = episode("remote", "remote", "stay_pir", target_at)

    authorization = frontier.authorize(
        target,
        target_at,
        count=None,
        corroborating_states=(cleared,),
    )

    assert not authorization.authorized
    assert authorization.reason == "track_bootstrap_pending"


def test_expiry_degradation_unavailable_and_self_authorization_are_bounded() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    assert frontier.authorize(hall, NOW, count=None).authorized is False

    frontier.advance(NOW + timedelta(seconds=44, microseconds=999999))
    assert len(frontier.tokens) == 1
    frontier.advance(NOW + timedelta(seconds=45))
    assert not frontier.tokens

    later = episode("hall", "hall", "transition_fast", NOW + timedelta(minutes=1))
    issue(frontier, later)
    frontier.sync(
        replace(later, status="degraded", health_warning=True),
        NOW + timedelta(minutes=1, seconds=1),
    )
    assert not frontier.tokens

    unavailable = episode("hall", "hall", "transition_fast", NOW + timedelta(minutes=2))
    issue(frontier, unavailable)
    frontier.sync(
        replace(unavailable, status="unavailable", traversal_valid_until=None),
        NOW + timedelta(minutes=2, seconds=1),
    )
    assert not frontier.tokens


def test_authorized_correlated_reassertion_reopens_bounded_path_continuity() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = replace(
        episode("hall", "hall", "transition_fast", NOW),
        hold_until=NOW + timedelta(seconds=15),
        assertion_trust_until=NOW + timedelta(seconds=60),
    )
    effect = EpisodeEffect("hall", "hall", hall.episode_id or "", "positive", NOW)
    authorization = TraversalAuthorization(
        "hall",
        "hall",
        hall.episode_id or "",
        NOW,
        True,
        "adjacent_authorized",
        track_confidence="provisional",
        path_node_ids=("entry", "hall"),
        provenance_kind="adjacent",
    )
    original = frontier.issue(hall, effect, authorization)
    frontier.advance(NOW + timedelta(seconds=45))

    assert not frontier.tokens
    assert len(frontier.retained_tokens) == 1
    assert frontier.retained_tokens[0] == original

    reasserted_at = NOW + timedelta(seconds=46)
    reasserted = replace(
        hall,
        last_event_at=reasserted_at,
        advanced_at=reasserted_at,
    )
    flap = EpisodeEffect(
        "hall",
        "hall",
        hall.episode_id or "",
        "correlated_flap_ignored",
        reasserted_at,
    )

    assert frontier.reopen_authorized_continuity(reasserted, flap)
    reopened_tokens = frontier.tokens
    assert len(reopened_tokens) == 1
    reopened = reopened_tokens[0]
    assert not frontier.retained_tokens
    assert reopened.token_id == original.token_id
    assert reopened.accepted_at == original.accepted_at
    assert reopened.path_node_ids == ("entry", "hall")
    assert reopened.continuity_reopened_at == reasserted_at
    assert reopened.valid_until == NOW + timedelta(seconds=60)

    room = episode(
        "room_a",
        "room_a",
        "stay_pir",
        NOW + timedelta(seconds=52),
    )
    result = frontier.authorize(room, room.started_at or NOW, count=None)
    assert result.authorized
    assert result.reason == "track_confirmed"
    assert result.track_confidence == "confirmed"
    assert result.path_node_ids == ("entry", "hall", "room_a")

    frontier.advance(NOW + timedelta(seconds=60))
    assert not frontier.tokens
    assert not frontier.retained_tokens
    assert not frontier.reopen_authorized_continuity(
        replace(
            reasserted,
            last_event_at=NOW + timedelta(seconds=60),
            advanced_at=NOW + timedelta(seconds=60),
        ),
        replace(flap, at=NOW + timedelta(seconds=60)),
    )


def test_correlated_reassertion_without_authorized_lineage_remains_ignored() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    reasserted_at = NOW + timedelta(seconds=46)
    hall = replace(
        episode("hall", "hall", "transition_fast", NOW),
        last_event_at=reasserted_at,
        advanced_at=reasserted_at,
        hold_until=NOW + timedelta(seconds=15),
        assertion_trust_until=NOW + timedelta(seconds=60),
    )
    flap = EpisodeEffect(
        "hall",
        "hall",
        hall.episode_id or "",
        "correlated_flap_ignored",
        reasserted_at,
    )

    assert not frontier.reopen_authorized_continuity(hall, flap)
    assert frontier.tokens == ()
    assert frontier.retained_tokens == ()
    assert not frontier.reopen_authorized_continuity(
        replace(
            hall,
            cadence_warning=True,
            cadence_warning_reason="impossible_cadence",
        ),
        replace(
            flap,
            kind="impossible_cadence",
            warning_reason="impossible_cadence",
        ),
    )


def test_authorized_reassertion_preserves_a_still_valid_token() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = replace(
        episode("hall", "hall", "transition_fast", NOW),
        hold_until=NOW + timedelta(seconds=15),
        assertion_trust_until=NOW + timedelta(seconds=60),
    )
    original = issue(frontier, hall)
    reasserted_at = NOW + timedelta(seconds=20)
    reasserted = replace(
        hall,
        last_event_at=reasserted_at,
        advanced_at=reasserted_at,
    )
    flap = EpisodeEffect(
        "hall",
        "hall",
        hall.episode_id or "",
        "correlated_flap_ignored",
        reasserted_at,
    )

    assert frontier.reopen_authorized_continuity(reasserted, flap)
    assert frontier.tokens == (original,)
    assert frontier.current_token_ids == (original.token_id,)


def test_retained_authorized_lineage_round_trips_before_reassertion() -> None:
    source = TraversalFrontier(graph(), NODES)
    hall = replace(
        episode("hall", "hall", "transition_fast", NOW),
        hold_until=NOW + timedelta(seconds=15),
        assertion_trust_until=NOW + timedelta(seconds=60),
    )
    issue(source, hall)
    at = NOW + timedelta(seconds=45)
    source.advance(at)

    restored = TraversalFrontier(graph(), NODES)
    restored.restore_snapshot(
        source.tokens,
        source.current_token_ids,
        source.uses,
        at,
        source.pending_candidates,
        source.retained_tokens,
    )

    assert restored.tokens == ()
    assert restored.retained_tokens == source.retained_tokens


def test_boundary_and_same_zone_pending_require_fresh_support() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    count_context = CountContext(0)
    count = count_context.observe(CountInput("count-1", 1, True, NOW))
    entry = episode("entry", "entry", "entry_boundary", NOW + timedelta(seconds=1))
    boundary = frontier.authorize(entry, entry.started_at or NOW, count=count.state)
    assert boundary.authorized and boundary.reason == "boundary_authorized"

    for seconds in (30, 31):
        expired_entry = episode(
            "entry", "entry", "entry_boundary", NOW + timedelta(seconds=seconds)
        )
        assert (
            frontier.authorize(
                expired_entry, expired_entry.started_at or NOW, count=count.state
            ).authorized
            is False
        )

    corroborating = episode(
        "isolated_presence",
        "isolated",
        "stay_presence",
        NOW + timedelta(seconds=32),
    )
    pending = frontier.authorize(
        corroborating,
        corroborating.started_at or NOW,
        count=count.state,
    )
    isolated = episode("isolated", "isolated", "stay_pir", NOW + timedelta(seconds=33))
    same_zone = frontier.authorize(
        isolated,
        isolated.started_at or NOW,
        count=count.state,
    )
    assert not pending.authorized
    assert same_zone.authorized and same_zone.reason == "same_zone_authorized"


def test_authorization_registers_outward_context_for_each_source_zone() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    target = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=2))
    authorization = frontier.authorize(target, target.started_at or NOW, count=None)
    hall_filter = ZoneBeliefFilter("hall", BELIEF_PROFILES["transition_fast"], NOW)
    hall_filter.apply_positive(hall.episode_id or "", NOW)

    registrations = frontier.apply_outward_context(
        authorization, {"hall": hall_filter}, target.started_at or NOW
    )

    assert registrations == (("hall", hall.episode_id),)
    assert hall_filter.state.outward_context is not None
    assert hall_filter.state.outward_context.source_episode_id == hall.episode_id
    with pytest.raises(ValueError, match="no belief filter"):
        frontier.apply_outward_context(authorization, {}, target.started_at or NOW)

    rejected = frontier.authorize(
        episode("isolated", "isolated", "stay_pir", NOW + timedelta(seconds=3)),
        NOW + timedelta(seconds=3),
        count=None,
    )
    assert (
        frontier.apply_outward_context(rejected, {}, NOW + timedelta(seconds=3)) == ()
    )


def test_settled_endpoint_authorizes_only_its_exact_target_without_source_use() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    support = AnonymousOccupancySupport(
        "support:room_a",
        "settled",
        NOW,
        NOW,
        "room_a:prior",
        "room_a",
        "room_a",
        ("hall", "room_a"),
        "adjacent",
        None,
        "settled",
    )
    target_at = NOW + timedelta(seconds=1)
    target = episode("room_a", "room_a", "stay_pir", target_at)

    authorized = frontier.authorize(
        target,
        target_at,
        count=None,
        settled_support=support,
    )

    assert authorized.authorized
    assert authorized.reason == "settled_endpoint_reacquired"
    assert authorized.source_tokens == ()
    assert authorized.new_uses == ()
    assert frontier.uses == ()
    different = episode(
        "room_b",
        "room_b",
        "stay_pir",
        target_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="does not match traversal target"):
        frontier.authorize(
            different,
            different.started_at or target_at,
            count=None,
            settled_support=support,
        )


def test_same_zone_predecessor_lookup_requires_exact_live_use_row() -> None:
    predecessor_state = episode(
        "room_a",
        "room_a",
        "stay_pir",
        NOW,
        valid_for=timedelta(seconds=90),
    )
    predecessor = TraversalToken(
        f"room_a:{predecessor_state.episode_id}",
        "room_a",
        "room_a",
        "stay",
        "stay_pir",
        predecessor_state.episode_id or "",
        NOW,
        predecessor_state.traversal_valid_until or NOW,
        "provisional",
        ("room_a",),
        "same_zone",
    )
    generation_at = NOW + timedelta(seconds=1)
    generation = episode(
        "room_a_presence",
        "room_a",
        "stay_presence",
        generation_at,
    )
    use = AuthorizationUse(
        predecessor.token_id,
        generation.episode_id or "",
        "same_zone_authorized",
        generation_at,
    )
    outward_at = NOW + timedelta(seconds=2)
    outward = episode("hall", "hall", "transition_fast", outward_at)
    authorization = TraversalAuthorization(
        outward.node_id,
        outward.zone,
        outward.episode_id or "",
        outward_at,
        True,
        "adjacent_authorized",
        (predecessor,),
        track_confidence="provisional",
        path_node_ids=("room_a", "hall"),
        provenance_kind="adjacent",
    )
    unadvanced = TraversalFrontier(graph(), NODES)
    with pytest.raises(ValueError, match="requires an advanced frontier"):
        unadvanced.same_zone_predecessor_for_outward(
            authorization,
            generation,
            outward_at,
        )
    frontier = TraversalFrontier(graph(), NODES)
    frontier.restore_snapshot((predecessor,), (), (use,), outward_at)

    assert (
        frontier.same_zone_predecessor_for_outward(
            authorization,
            generation,
            outward_at,
        )
        == predecessor
    )

    mismatched = TraversalFrontier(graph(), NODES)
    mismatched.restore_snapshot(
        (predecessor,),
        (),
        (replace(use, reason="adjacent_authorized"),),
        outward_at,
    )
    assert (
        mismatched.same_zone_predecessor_for_outward(
            authorization,
            generation,
            outward_at,
        )
        is None
    )

    frontier.advance(predecessor.valid_until)
    expired_authorization = replace(
        authorization,
        authorized_at=predecessor.valid_until,
    )
    assert (
        frontier.same_zone_predecessor_for_outward(
            expired_authorization,
            generation,
            predecessor.valid_until,
        )
        is None
    )


def test_frontier_enforces_deterministic_token_and_use_bounds() -> None:
    token_frontier = TraversalFrontier(graph(), NODES, token_limit=1)
    hall = episode("hall", "hall", "transition_fast", NOW)
    hall_token = issue(token_frontier, hall)
    assert issue(token_frontier, hall) == hall_token
    room_a = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=1))
    room_a_token = issue(token_frontier, room_a)
    assert token_frontier.tokens == (room_a_token,)

    retention_frontier = TraversalFrontier(graph(), NODES, token_limit=1)
    retained_hall_token = issue(retention_frontier, hall)
    retention_frontier.advance(NOW + timedelta(seconds=45))
    dormant_tokens = retention_frontier.tokens
    dormant_retained = retention_frontier.retained_tokens
    assert dormant_tokens == ()
    assert dormant_retained == (retained_hall_token,)
    middle = episode(
        "middle",
        "middle",
        "transition_fast",
        NOW + timedelta(seconds=46),
    )
    middle_token = issue(retention_frontier, middle)
    active_tokens = retention_frontier.tokens
    active_retained = retention_frontier.retained_tokens
    assert active_tokens == (middle_token,)
    assert active_retained == ()

    use_frontier = TraversalFrontier(graph(), NODES, use_limit=1)
    issue(use_frontier, hall)
    first = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=2))
    second = episode("room_b", "room_b", "stay_pir", NOW + timedelta(seconds=3))
    use_frontier.authorize(first, first.started_at or NOW, count=None)
    use_frontier.authorize(second, second.started_at or NOW, count=None)
    assert len(use_frontier.uses) == 1
    assert use_frontier.uses[0].target_episode_id == second.episode_id


def test_frontier_rejects_invalid_configuration_and_episode_contracts() -> None:
    predictive_map = graph()
    with pytest.raises(ValueError, match="bounds"):
        TraversalFrontier(predictive_map, NODES, token_limit=0)
    with pytest.raises(ValueError, match="unique"):
        TraversalFrontier(predictive_map, (*NODES, NODES[0]))
    with pytest.raises(ValueError, match="absent"):
        TraversalFrontier(
            predictive_map,
            (*NODES, node("missing", "missing", "stay_pir")),
        )

    frontier = TraversalFrontier(predictive_map, NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    positive = EpisodeEffect("hall", "hall", hall.episode_id or "", "positive", NOW)
    invalid_effects = (
        replace(positive, kind="stable_clear"),
        replace(positive, node_id="room_a"),
        replace(positive, episode_id="other"),
    )
    for effect in invalid_effects:
        with pytest.raises(ValueError, match="current positive"):
            frontier.issue(
                hall,
                effect,
                TraversalAuthorization(
                    hall.node_id,
                    hall.zone,
                    hall.episode_id or "",
                    NOW,
                    True,
                    "adjacent_authorized",
                    track_confidence="provisional",
                    path_node_ids=(hall.node_id,),
                    provenance_kind="test_seed",
                ),
            )
    for state in (
        replace(hall, status="baseline"),
        replace(hall, traversal_valid_until=None),
        replace(hall, traversal_valid_until=NOW),
    ):
        with pytest.raises(ValueError, match="current positive"):
            frontier.issue(
                state,
                positive,
                TraversalAuthorization(
                    hall.node_id,
                    hall.zone,
                    hall.episode_id or "",
                    NOW,
                    True,
                    "adjacent_authorized",
                    track_confidence="provisional",
                    path_node_ids=(hall.node_id,),
                    provenance_kind="test_seed",
                ),
            )

    for state in (
        replace(hall, node_id="missing"),
        replace(hall, zone="wrong"),
        replace(hall, profile_name="stay_pir"),
    ):
        with pytest.raises(ValueError, match="incompatible"):
            frontier.authorize(state, NOW, count=None)
    with pytest.raises(ValueError, match="current positive"):
        frontier.authorize(replace(hall, status="baseline"), NOW, count=None)
    with pytest.raises(ValueError, match="current positive"):
        frontier.authorize(replace(hall, episode_id=None), NOW, count=None)

    frontier.sync(hall, NOW)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        frontier.advance(NOW.replace(tzinfo=None))
    frontier.advance(NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="cannot move backward"):
        frontier.advance(NOW)


@pytest.mark.parametrize(
    "target_change",
    [
        {"health_warning": True},
        {"started_at": None},
        {"traversal_valid_until": None},
        {"started_at": NOW + timedelta(seconds=1)},
        {"traversal_valid_until": NOW},
    ],
)
def test_untrustworthy_target_cannot_create_pending_candidate(
    target_change: dict[str, object],
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = replace(
        episode("isolated", "isolated", "stay_pir", NOW),
        **target_change,  # type: ignore[arg-type]
    )
    result = frontier.authorize(
        target,
        NOW,
        count=CountState(1),
    )
    assert result.authorized is False


def test_positive_count_never_authorizes_isolated_episode() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = episode("isolated", "isolated", "stay_pir", NOW)
    result = frontier.authorize(target, NOW, count=CountState(1))
    assert not result.authorized
    assert result.reason == "track_bootstrap_pending"
    assert frontier.pending_candidates[0].episode_id == target.episode_id

    frontier.advance(NOW + timedelta(seconds=89, microseconds=999999))
    assert len(frontier.pending_candidates) == 1
    frontier.advance(NOW + timedelta(seconds=90))
    assert not frontier.pending_candidates


def test_traversal_value_types_reject_invalid_identity_and_time() -> None:
    token = TraversalToken(
        "token",
        "hall",
        "hall",
        "transition",
        "transition_fast",
        "episode",
        NOW,
        NOW + timedelta(seconds=1),
        path_node_ids=("hall",),
    )
    with pytest.raises(ValueError, match="identifiers"):
        replace(token, token_id="")
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        replace(token, accepted_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="must follow"):
        replace(token, valid_until=NOW)
    with pytest.raises(ValueError, match="continuity reopening"):
        replace(token, continuity_reopened_at=NOW)

    use = AuthorizationUse("token", "target", "adjacent_current", NOW)
    with pytest.raises(ValueError, match="identifiers"):
        replace(use, reason="")
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        replace(use, authorized_at=NOW.replace(tzinfo=None))


def test_restore_rejects_each_bounded_snapshot_incompatibility() -> None:
    source = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    token = issue(source, hall)
    target = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=1))
    source.authorize(target, target.started_at or NOW, count=None)
    at = NOW + timedelta(seconds=1)

    invalid: tuple[
        tuple[
            tuple[TraversalToken, ...],
            tuple[str, ...],
            tuple[AuthorizationUse, ...],
            str,
        ],
        ...,
    ] = (
        ((token, token), (), (), "duplicated"),
        ((replace(token, zone="wrong"),), (), (), "token snapshot"),
        ((token,), (token.token_id, token.token_id), (), "Current"),
        ((token,), (), (source.uses[0], source.uses[0]), "use snapshot"),
        (
            (token,),
            (),
            (replace(source.uses[0], token_id="missing"),),
            "use snapshot",
        ),
    )
    for tokens, current, uses, message in invalid:
        restored = TraversalFrontier(graph(), NODES)
        with pytest.raises(ValueError, match=message):
            restored.restore_snapshot(tokens, current, uses, at)

    invalid_continuity = replace(
        token,
        valid_until=NOW + timedelta(seconds=50),
        continuity_reopened_at=NOW + timedelta(seconds=10),
    )
    with pytest.raises(ValueError, match="token snapshot"):
        TraversalFrontier(graph(), NODES).restore_snapshot(
            (invalid_continuity,), (), (), NOW + timedelta(seconds=20)
        )

    retained_source = TraversalFrontier(graph(), NODES)
    retained_hall = episode("hall", "hall", "transition_fast", NOW)
    issue(retained_source, retained_hall)
    retained_at = NOW + timedelta(seconds=45)
    retained_source.advance(retained_at)
    retained = retained_source.retained_tokens[0]
    with pytest.raises(ValueError, match="Retained traversal"):
        TraversalFrontier(graph(), NODES).restore_snapshot(
            (),
            (),
            (),
            retained_at,
            retained_tokens=(replace(retained, zone="wrong"),),
        )

    pending_source = TraversalFrontier(graph(), NODES)
    isolated = episode("isolated", "isolated", "stay_pir", NOW)
    pending_source.authorize(isolated, NOW, count=CountState(1))
    pending = pending_source.pending_candidates[0]
    with pytest.raises(ValueError, match="duplicated"):
        TraversalFrontier(graph(), NODES).restore_snapshot(
            (), (), (), NOW, (pending, pending)
        )
    with pytest.raises(ValueError, match="candidate snapshot"):
        TraversalFrontier(graph(), NODES).restore_snapshot(
            (), (), (), NOW, (replace(pending, node_id="missing"),)
        )

    issued = pending_source._issue_pending_token(pending, "hall")  # noqa: SLF001
    assert (
        pending_source._issue_pending_token(pending, "hall")  # noqa: SLF001
        is issued
    )
