from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.profiles import (
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supports import (
    DIAGNOSTIC_COUNTER_LIMIT,
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    EpisodeState,
    OutwardContext,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def support_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["source", "room", "hall2"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.room"},
                    "adjacent": ["hall", "hall2"],
                },
                "hall2": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall2"},
                    "adjacent": ["hall", "room", "room2"],
                },
                "room2": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.room2"},
                    "adjacent": ["hall2"],
                },
                "other_source": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.other_source"},
                    "adjacent": ["other_hall"],
                },
                "other_hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.other_hall"},
                    "adjacent": ["other_source", "other_room"],
                },
                "other_room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.other_room"},
                    "adjacent": ["other_hall"],
                },
            }
        }
    )


def tracker(*, support_limit: int = 2) -> AnonymousSupportTracker:
    predictive_map = support_map()
    build = build_physical_nodes(predictive_map)
    assert not build.errors
    return AnonymousSupportTracker(
        predictive_map,
        build.nodes,
        support_limit=support_limit,
    )


def episode(
    node_id: str,
    *,
    profile_name: str,
    zone: str | None = None,
    at: datetime = NOW,
    status: str = "asserted",
) -> EpisodeState:
    episode_id = f"{node_id}:episode"
    return EpisodeState(
        node_id,
        node_id if zone is None else zone,
        profile_name,
        ((f"binary_sensor.{node_id}", "on"),),
        generation=1,
        episode_id=episode_id,
        status=status,
        started_at=at,
        last_event_at=at,
        advanced_at=at,
        hold_until=at + timedelta(seconds=10),
        assertion_trust_until=at + timedelta(minutes=30),
        traversal_valid_until=at + timedelta(minutes=2),
    )


def belief(state: EpisodeState, *, probability: float = 0.9) -> ZoneBeliefState:
    assert state.episode_id is not None
    return ZoneBeliefState(
        state.zone,
        state.profile_name,
        math.log(probability / (1.0 - probability)),
        state.last_event_at or NOW,
        "asserted",
        state.episode_id,
        state.episode_id,
    )


def token(
    state: EpisodeState,
    at: datetime,
    path: tuple[str, ...],
    *,
    confidence: str = "confirmed",
) -> TraversalToken:
    assert state.episode_id is not None
    return TraversalToken(
        f"{state.node_id}:{state.episode_id}",
        state.node_id,
        state.zone,
        "stay" if state.profile_name == "stay_presence" else "transition",
        state.profile_name,
        state.episode_id,
        at,
        at + timedelta(minutes=2),
        confidence,
        path,
        "adjacent",
    )


def authorization(
    target: TraversalToken,
    sources: tuple[TraversalToken, ...] = (),
) -> TraversalAuthorization:
    return TraversalAuthorization(
        target.node_id,
        target.zone,
        target.episode_id,
        target.accepted_at,
        True,
        "track_confirmed",
        sources,
        (),
        target.track_confidence,
        target.path_node_ids,
        target.provenance_kind,
        target.equivalent_confirmed_strength,
    )


def apply_token(
    support_tracker: AnonymousSupportTracker,
    target: TraversalToken,
    states: tuple[EpisodeState, ...],
    beliefs: tuple[ZoneBeliefState, ...],
    *,
    sources: tuple[TraversalToken, ...] = (),
    active_tokens: tuple[TraversalToken, ...] | None = None,
    retained_tokens: tuple[TraversalToken, ...] = (),
) -> None:
    support_tracker.apply(
        target.accepted_at,
        EpisodeEffect(
            target.node_id,
            target.zone,
            target.episode_id,
            "positive",
            target.accepted_at,
        ),
        authorization(target, sources),
        target,
        states,
        beliefs,
        (*sources, target) if active_tokens is None else active_tokens,
        retained_tokens,
    )


def test_confirmed_stay_creates_one_settled_support_and_survives_token_expiry() -> None:
    support_tracker = tracker()
    room = episode(
        "room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=2),
    )
    room_token = token(
        room,
        NOW + timedelta(seconds=2),
        ("source", "hall", "room"),
    )

    apply_token(support_tracker, room_token, (room,), (belief(room),))

    support = support_tracker.supports[0]
    assert support.support_id == f"support:{room_token.token_id}"
    assert support.state == "settled"
    assert support.current_node_id == "room"
    assert support.valid_until is None
    assert support_tracker.bindings[0].token_id == room_token.token_id
    assert support_tracker.count_supports()[0].endpoint_zone == "room"

    support_tracker.advance(
        room_token.valid_until,
        (room,),
        (belief(room),),
        (),
        (),
    )
    assert support_tracker.supports == (support,)
    assert support_tracker.bindings == ()


def test_support_tracker_rejects_invalid_construction_restore_and_frontiers() -> None:
    predictive_map = support_map()
    build = build_physical_nodes(predictive_map)
    assert not build.errors
    with pytest.raises(ValueError, match="limit must be positive"):
        AnonymousSupportTracker(predictive_map, build.nodes, support_limit=0)
    with pytest.raises(ValueError, match="physical nodes are incompatible"):
        AnonymousSupportTracker(predictive_map, (*build.nodes, build.nodes[0]))

    source = tracker()
    assert source.support_limit == 2
    room = episode("room", profile_name="stay_presence", at=NOW + timedelta(seconds=2))
    room_token = token(room, room.started_at or NOW, ("source", "hall", "room"))
    apply_token(source, room_token, (room,), (belief(room),))
    support = source.supports[0]
    duplicate = replace(support, support_id="support:duplicate")

    bounded = tracker(support_limit=1)
    with pytest.raises(ValueError, match="exceeds its bound"):
        bounded.restore((duplicate, support), (), support.updated_at)
    with pytest.raises(ValueError, match="restore is incompatible"):
        bounded.restore(
            (replace(support, path_node_ids=("source", "room")),),
            (),
            support.updated_at,
        )
    with pytest.raises(ValueError, match="endpoint is incompatible"):
        bounded.restore(
            (replace(support, current_zone="other_room"),),
            (),
            support.updated_at,
        )
    moving = replace(
        support,
        state="moving",
        valid_until=support.updated_at + timedelta(seconds=1),
        last_transition="advanced",
    )
    with pytest.raises(ValueError, match="expired at restore"):
        bounded.restore((moving,), (), moving.valid_until or support.updated_at)

    bounded.restore((support,), (), support.updated_at)
    with pytest.raises(ValueError, match="cannot move backward"):
        bounded.advance(
            support.updated_at - timedelta(microseconds=1),
            (room,),
            (belief(room),),
            (),
            (),
        )
    with pytest.raises(ValueError, match="inputs must be unique"):
        bounded.advance(
            support.updated_at,
            (room, room),
            (belief(room),),
            (),
            (),
        )
    with pytest.raises(ValueError, match="inputs must be unique"):
        bounded.advance(
            support.updated_at,
            (room,),
            (belief(room),),
            (room_token,),
            (room_token,),
        )


def test_support_tracker_covers_atomic_validation_and_coalescence_boundaries() -> None:
    support_tracker = tracker()
    room = episode("room", profile_name="stay_presence", at=NOW + timedelta(seconds=2))
    room_token = token(room, room.started_at or NOW, ("source", "hall", "room"))
    apply_token(support_tracker, room_token, (room,), (belief(room),))
    support = support_tracker.supports[0]
    effect = EpisodeEffect(
        room.node_id,
        room.zone,
        room.episode_id or "",
        "positive",
        room_token.accepted_at + timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="inputs are inconsistent"):
        support_tracker._validate_application(  # noqa: SLF001
            effect,
            authorization(room_token),
            room_token,
            room_token.accepted_at,
        )
    rebound = replace(
        room,
        episode_id="room:tokenless-rebind",
        started_at=support.updated_at + timedelta(microseconds=1),
        last_event_at=support.updated_at + timedelta(microseconds=1),
        advanced_at=support.updated_at + timedelta(microseconds=1),
    )
    support_tracker.apply(
        rebound.started_at or support.updated_at,
        EpisodeEffect(
            rebound.node_id,
            rebound.zone,
            rebound.episode_id or "",
            "positive",
            rebound.started_at or support.updated_at,
        ),
        None,
        None,
        (rebound,),
        (belief(rebound),),
        (),
        (),
    )
    assert support_tracker.supports[0].current_episode_id == rebound.episode_id
    with pytest.raises(ValueError, match="requires a current support"):
        support_tracker._coalesce(  # noqa: SLF001
            ("support:missing",),
            {},
            {},
            support.updated_at,
            "test",
        )
    with pytest.raises(ValueError, match="exceeds its bound"):
        tracker(support_limit=1)._transition(  # noqa: SLF001
            {support.support_id: support, "support:duplicate": replace(
                support, support_id="support:duplicate"
            )},
            {},
            None,
        )

    duplicate = replace(support, support_id="support:duplicate")
    room2 = episode(
        "room2",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=3),
    )
    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=3),
    )
    first_token = replace(
        room_token,
        token_id="a",
        path_node_ids=("source",),
        provenance_kind="boundary",
        equivalent_confirmed_strength=True,
    )
    second_token = replace(
        token(room2, room2.started_at or NOW, ("room", "hall2", "room2")),
        token_id="b",
        path_node_ids=("room2",),
        provenance_kind="boundary",
        equivalent_confirmed_strength=True,
    )
    bridge_token = replace(
        token(hall2, hall2.started_at or NOW, ("hall", "room", "hall2")),
        token_id="c",
        provenance_kind="boundary",
        equivalent_confirmed_strength=True,
    )
    connected_supports, _bindings, connected = (
        support_tracker._coalesce_current_components(  # noqa: SLF001
            {support.support_id: support, duplicate.support_id: duplicate},
            {
                first_token.token_id: support.support_id,
                second_token.token_id: duplicate.support_id,
                bridge_token.token_id: support.support_id,
            },
            (first_token, second_token, bridge_token),
            support.updated_at,
            None,
        )
    )
    assert len(connected_supports) == 1
    assert connected is not None and connected.reason == "connected_component"

    coalesce_at = rebound.started_at or support.updated_at
    support_tracker.restore((duplicate, support), (), coalesce_at)
    support_tracker.advance(
        coalesce_at,
        (room,),
        (belief(room),),
        (),
        (),
    )
    assert len(support_tracker.supports) == 1
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "same_zone"

    support_tracker._counters["support_created"] = DIAGNOSTIC_COUNTER_LIMIT  # noqa: SLF001
    support_tracker._increment_counter("support_created", 1)  # noqa: SLF001
    assert support_tracker.counters["support_created"] == DIAGNOSTIC_COUNTER_LIMIT


@pytest.mark.parametrize(
    ("state_update", "belief_update", "expected"),
    (
        (None, None, "unavailable"),
        ({"status": "unavailable"}, None, "unavailable"),
        ({"health_warning": True}, None, "health_warning"),
        ({}, {"health_warning": True}, "health_warning"),
        ({"cadence_warning": True}, None, "cadence_warning"),
        ({"status": "clear"}, None, "outward_clear"),
        ({"status": "clear"}, {"context": "cleared_with_outward"}, "outward_clear"),
        ({"status": "dormant"}, None, "belief_below_threshold"),
        ({}, None, "belief_below_threshold"),
    ),
)
def test_settled_support_removal_reasons_are_deterministic(
    state_update: dict[str, object] | None,
    belief_update: dict[str, object] | None,
    expected: str,
) -> None:
    support_tracker = tracker()
    room = episode("room", profile_name="stay_presence")
    room_token = token(room, NOW, ("source", "hall", "room"))
    apply_token(support_tracker, room_token, (room,), (belief(room),))
    state_by_node = (
        {}
        if state_update is None
        else {room.node_id: replace(room, **cast(Any, state_update))}
    )
    belief_by_zone = (
        {}
        if belief_update is None
        else {room.zone: replace(belief(room), **cast(Any, belief_update))}
    )
    assert (
        support_tracker._settled_removal_reason(  # noqa: SLF001
            support_tracker.supports[0],
            state_by_node,
            belief_by_zone,
        )
        == expected
    )


def test_provisional_isolated_and_timer_only_inputs_create_no_support() -> None:
    support_tracker = tracker()
    room = episode("room", profile_name="stay_presence")
    provisional = token(room, NOW, ("hall", "room"), confidence="provisional")
    apply_token(support_tracker, provisional, (room,), (belief(room),))
    assert not support_tracker.supports

    rejected = TraversalAuthorization(
        room.node_id,
        room.zone,
        room.episode_id or "",
        NOW + timedelta(seconds=1),
        False,
        "track_bootstrap_pending",
    )
    support_tracker.apply(
        NOW + timedelta(seconds=1),
        EpisodeEffect(
            room.node_id,
            room.zone,
            room.episode_id or "",
            "positive",
            NOW + timedelta(seconds=1),
        ),
        rejected,
        None,
        (room,),
        (belief(room),),
        (),
        (),
    )
    support_tracker.advance(
        NOW + timedelta(seconds=2),
        (room,),
        (belief(room),),
        (),
        (),
    )
    assert not support_tracker.supports


def test_support_transfers_to_one_moving_then_settled_endpoint() -> None:
    support_tracker = tracker()
    room = episode(
        "room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=2),
    )
    room_token = token(
        room,
        NOW + timedelta(seconds=2),
        ("source", "hall", "room"),
    )
    apply_token(support_tracker, room_token, (room,), (belief(room),))
    support_id = support_tracker.supports[0].support_id

    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=3),
    )
    hall2_token = token(
        hall2,
        NOW + timedelta(seconds=3),
        ("hall", "room", "hall2"),
    )
    apply_token(
        support_tracker,
        hall2_token,
        (room, hall2),
        (belief(room), belief(hall2)),
        sources=(room_token,),
    )
    moving = support_tracker.supports[0]
    assert moving.support_id == support_id
    assert moving.state == "moving"
    assert moving.current_node_id == "hall2"
    assert moving.valid_until == hall2_token.valid_until

    room2 = episode(
        "room2",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=4),
    )
    room2_token = token(
        room2,
        NOW + timedelta(seconds=4),
        ("room", "hall2", "room2"),
    )
    apply_token(
        support_tracker,
        room2_token,
        (room, hall2, room2),
        (belief(room), belief(hall2), belief(room2)),
        sources=(hall2_token,),
        active_tokens=(room_token, hall2_token, room2_token),
    )
    settled = support_tracker.supports[0]
    assert settled.support_id == support_id
    assert settled.state == "settled"
    assert settled.current_node_id == "room2"
    assert all(item.current_node_id != "room" for item in support_tracker.supports)
    assert support_tracker.counters == {
        "support_created": 1,
        "support_transferred": 2,
        "support_coalesced": 0,
        "support_expired": 0,
    }


def test_source_set_merge_coalesces_before_transfer_and_split_cannot_clone() -> None:
    support_tracker = tracker()
    room = episode(
        "room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=2),
    )
    room_token = token(
        room,
        NOW + timedelta(seconds=2),
        ("source", "hall", "room"),
    )
    apply_token(support_tracker, room_token, (room,), (belief(room),))

    other_room = episode(
        "other_room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=3),
    )
    other_token = token(
        other_room,
        NOW + timedelta(seconds=3),
        ("other_source", "other_hall", "other_room"),
    )
    apply_token(
        support_tracker,
        other_token,
        (room, other_room),
        (belief(room), belief(other_room)),
        active_tokens=(room_token, other_token),
    )
    original_ids = tuple(item.support_id for item in support_tracker.supports)
    assert len(original_ids) == 2

    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=4),
    )
    target = token(
        hall2,
        NOW + timedelta(seconds=4),
        ("hall", "room", "hall2"),
    )
    apply_token(
        support_tracker,
        target,
        (room, other_room, hall2),
        (belief(room), belief(other_room), belief(hall2)),
        sources=(room_token, other_token),
        active_tokens=(target,),
        retained_tokens=(room_token, other_token),
    )

    assert len(support_tracker.supports) == 1
    assert support_tracker.supports[0].support_id == min(original_ids)
    assert support_tracker.supports[0].current_node_id == "hall2"
    assert {item.support_id for item in support_tracker.bindings} == {
        min(original_ids)
    }
    assert support_tracker.counters["support_coalesced"] == 1

    remote = replace(
        other_token,
        token_id="other_room:remote",
        episode_id="remote",
        accepted_at=NOW + timedelta(seconds=5),
        valid_until=NOW + timedelta(minutes=2, seconds=5),
    )
    support_tracker.apply(
        remote.accepted_at,
        EpisodeEffect(
            remote.node_id,
            remote.zone,
            remote.episode_id,
            "positive",
            remote.accepted_at,
        ),
        authorization(remote),
        remote,
        (room, other_room, hall2),
        (belief(room), belief(other_room), belief(hall2)),
        (target, remote),
        (),
    )
    assert len(support_tracker.supports) == 1


def test_stable_clear_moving_expiry_cap_and_count_zero_are_conservative() -> None:
    support_tracker = tracker(support_limit=1)
    room = episode(
        "room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=2),
    )
    room_token = token(
        room,
        NOW + timedelta(seconds=2),
        ("source", "hall", "room"),
    )
    apply_token(support_tracker, room_token, (room,), (belief(room),))

    other_room = episode(
        "other_room",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=3),
    )
    other_token = token(
        other_room,
        NOW + timedelta(seconds=3),
        ("other_source", "other_hall", "other_room"),
    )
    apply_token(
        support_tracker,
        other_token,
        (room, other_room),
        (belief(room), belief(other_room)),
        active_tokens=(room_token, other_token),
    )
    assert len(support_tracker.supports) == 1
    assert support_tracker.supports[0].current_node_id == "room"

    clearing = replace(room, status="clearing")
    support_tracker.advance(
        NOW + timedelta(seconds=4),
        (clearing, other_room),
        (belief(room), belief(other_room)),
        (room_token, other_token),
        (),
    )
    assert len(support_tracker.supports) == 1

    cleared = replace(room, status="clear")
    support_tracker.advance(
        NOW + timedelta(seconds=5),
        (cleared, other_room),
        (belief(room), belief(other_room)),
        (room_token, other_token),
        (),
    )
    retained_id = support_tracker.supports[0].support_id
    assert support_tracker.supports[0].current_episode_id == room.episode_id

    rebound = replace(
        room,
        episode_id="room:rebound",
        started_at=NOW + timedelta(seconds=5, microseconds=1),
        last_event_at=NOW + timedelta(seconds=5, microseconds=1),
        advanced_at=NOW + timedelta(seconds=5, microseconds=1),
    )
    rebound_token = replace(
        room_token,
        token_id="room:rebound",
        episode_id=rebound.episode_id or "",
        accepted_at=NOW + timedelta(seconds=5, microseconds=1),
        valid_until=NOW + timedelta(minutes=2, seconds=5, microseconds=1),
    )
    support_tracker.apply(
        NOW + timedelta(seconds=5, microseconds=1),
        EpisodeEffect(
            rebound.node_id,
            rebound.zone,
            rebound.episode_id or "",
            "positive",
            NOW + timedelta(seconds=5, microseconds=1),
        ),
        None,
        rebound_token,
        (rebound, other_room),
        (belief(rebound), belief(other_room)),
        (room_token, other_token, rebound_token),
        (),
    )
    assert support_tracker.supports[0].support_id == retained_id
    assert support_tracker.supports[0].current_episode_id == rebound.episode_id
    assert any(
        binding.token_id == rebound_token.token_id
        for binding in support_tracker.bindings
    )

    outward_belief = replace(
        belief(rebound),
        context="cleared_with_outward",
        outward_context=OutwardContext(
            rebound.episode_id or "",
            NOW + timedelta(seconds=30),
        ),
    )
    support_tracker.advance(
        NOW + timedelta(seconds=5, microseconds=2),
        (replace(rebound, status="clear"), other_room),
        (outward_belief, belief(other_room)),
        (room_token, other_token),
        (),
    )
    assert not support_tracker.supports
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "outward_clear"

    later_other_token = replace(
        other_token,
        accepted_at=NOW + timedelta(seconds=6),
        valid_until=NOW + timedelta(minutes=2, seconds=6),
    )
    apply_token(
        support_tracker,
        later_other_token,
        (other_room,),
        (belief(other_room),),
    )
    moving = replace(
        support_tracker.supports[0],
        state="moving",
        valid_until=NOW + timedelta(seconds=10),
        last_transition="advanced",
    )
    support_tracker.restore(
        (moving,),
        support_tracker.bindings,
        NOW + timedelta(seconds=6),
    )
    support_tracker.advance(
        NOW + timedelta(seconds=10),
        (other_room,),
        (belief(other_room),),
        (),
        (),
    )
    assert support_tracker.supports == ()
    assert support_tracker.counters["support_expired"] == 1

    apply_token(
        support_tracker,
        replace(
            other_token,
            accepted_at=NOW + timedelta(seconds=11),
            valid_until=NOW + timedelta(minutes=2, seconds=11),
        ),
        (other_room,),
        (belief(other_room),),
    )
    support_tracker.clear(NOW + timedelta(seconds=12))
    assert support_tracker.supports == ()
    assert support_tracker.bindings == ()
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "count_zero"
