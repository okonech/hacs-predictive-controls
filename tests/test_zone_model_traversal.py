from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import (
    traversal as traversal_module,
)
from custom_components.predictive_controls.zone_model.count import (
    CountContext,
    CountInput,
)
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    SHARED_PROFILES,
    STAY_PIR,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    AuthorizationUse,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
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
    return frontier.issue(state, effect)


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

    assert first.authorized and first.reason == "adjacent_current"
    assert second.authorized and second.reason == "adjacent_current"
    assert first.source_tokens == second.source_tokens == (token,)
    assert len(first.new_uses) == len(second.new_uses) == 1
    assert duplicate.authorized and duplicate.new_uses == ()
    assert len(frontier.tokens) == 1


def test_recent_same_zone_missed_edge_and_disconnected_authorization() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    frontier.sync(replace(hall, status="clear"), NOW + timedelta(seconds=1))
    room_a = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=2))
    assert frontier.authorize(room_a, room_a.started_at or NOW, count=None).reason == (
        "adjacent_recent"
    )

    room_a_token = issue(frontier, room_a)
    presence = episode(
        "room_a_presence", "room_a", "stay_presence", NOW + timedelta(seconds=3)
    )
    same_zone = frontier.authorize(presence, presence.started_at or NOW, count=None)
    assert same_zone.reason == "same_zone_other_node"
    assert room_a_token in same_zone.source_tokens

    remote = episode("remote", "remote", "stay_pir", NOW + timedelta(seconds=10))
    missed = frontier.authorize(remote, remote.started_at or NOW, count=None)
    assert missed.authorized and missed.reason == "bounded_missed_edge"

    isolated = episode("isolated", "isolated", "stay_pir", NOW + timedelta(seconds=11))
    rejected = frontier.authorize(isolated, isolated.started_at or NOW, count=None)
    assert rejected.authorized is False
    assert rejected.reason == "disconnected"


def test_expiry_degradation_unavailable_and_self_authorization_are_bounded() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    hall = episode("hall", "hall", "transition_fast", NOW)
    issue(frontier, hall)
    assert frontier.authorize(hall, NOW, count=None).authorized is False

    frontier.advance(NOW + timedelta(seconds=45))
    assert frontier.tokens == ()

    later = episode("hall", "hall", "transition_fast", NOW + timedelta(minutes=1))
    issue(frontier, later)
    frontier.sync(
        replace(later, status="degraded", health_warning=True),
        NOW + timedelta(minutes=1, seconds=1),
    )
    assert frontier.tokens == ()

    unavailable = episode("hall", "hall", "transition_fast", NOW + timedelta(minutes=2))
    issue(frontier, unavailable)
    frontier.sync(
        replace(unavailable, status="unavailable", traversal_valid_until=None),
        NOW + timedelta(minutes=2, seconds=1),
    )
    assert frontier.tokens == ()


def test_boundary_and_source_free_require_fresh_count_or_corroboration() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    count_context = CountContext(0)
    count = count_context.observe(CountInput("count-1", 1, True, NOW))
    entry = episode("entry", "entry", "entry_boundary", NOW + timedelta(seconds=1))
    boundary = frontier.authorize(entry, entry.started_at or NOW, count=count.state)
    assert boundary.authorized and boundary.reason == "boundary_reacquisition"

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

    isolated = episode("isolated", "isolated", "stay_pir", NOW + timedelta(seconds=31))
    corroborating = episode(
        "isolated_presence",
        "isolated",
        "stay_presence",
        NOW + timedelta(seconds=30),
    )
    source_free = frontier.authorize(
        isolated,
        isolated.started_at or NOW,
        count=count.state,
        corroborating_states=(corroborating,),
    )
    assert source_free.authorized and source_free.reason == "source_free_corroborated"


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


def test_frontier_enforces_deterministic_token_and_use_bounds() -> None:
    token_frontier = TraversalFrontier(graph(), NODES, token_limit=1)
    hall = episode("hall", "hall", "transition_fast", NOW)
    hall_token = issue(token_frontier, hall)
    assert issue(token_frontier, hall) == hall_token
    room_a = episode("room_a", "room_a", "stay_pir", NOW + timedelta(seconds=1))
    room_a_token = issue(token_frontier, room_a)
    assert token_frontier.tokens == (room_a_token,)

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
            frontier.issue(hall, effect)
    for state in (
        replace(hall, status="baseline"),
        replace(hall, traversal_valid_until=None),
        replace(hall, traversal_valid_until=NOW),
    ):
        with pytest.raises(ValueError, match="current positive"):
            frontier.issue(state, positive)

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
def test_source_free_rejects_untrustworthy_target(
    target_change: dict[str, object],
) -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = replace(
        episode("isolated", "isolated", "stay_pir", NOW),
        **target_change,  # type: ignore[arg-type]
    )
    corroborating = episode("isolated_presence", "isolated", "stay_presence", NOW)
    result = frontier.authorize(
        target,
        NOW,
        count=CountState(1),
        corroborating_states=(corroborating,),
    )
    assert result.authorized is False


@pytest.mark.parametrize(
    "corroborating_change",
    [
        {"node_id": "isolated"},
        {"zone": "wrong"},
        {"status": "baseline"},
        {"health_warning": True},
        {"started_at": None},
        {"started_at": NOW + timedelta(seconds=1)},
    ],
)
def test_source_free_rejects_untrustworthy_corroboration(
    corroborating_change: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles = dict(SHARED_PROFILES)
    profiles["stay_pir"] = replace(STAY_PIR, single_node_reacquisition=False)
    monkeypatch.setattr(traversal_module, "SHARED_PROFILES", profiles)
    frontier = TraversalFrontier(graph(), NODES)
    target = episode("isolated", "isolated", "stay_pir", NOW)
    corroborating = replace(
        episode("isolated_presence", "isolated", "stay_presence", NOW),
        **corroborating_change,  # type: ignore[arg-type]
    )
    result = frontier.authorize(
        target,
        NOW,
        count=CountState(1),
        corroborating_states=(corroborating,),
    )
    assert result.authorized is False


def test_reviewed_stay_profile_capability_enables_source_free() -> None:
    frontier = TraversalFrontier(graph(), NODES)
    target = episode("isolated", "isolated", "stay_pir", NOW)
    result = frontier.authorize(target, NOW, count=CountState(1))
    assert result.authorized and result.reason == "source_free_corroborated"


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
    )
    with pytest.raises(ValueError, match="identifiers"):
        replace(token, token_id="")
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        replace(token, accepted_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="must follow"):
        replace(token, valid_until=NOW)

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
