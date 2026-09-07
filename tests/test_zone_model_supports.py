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
    AnonymousOccupancySupport,
    EpisodeEffect,
    EpisodeState,
    OutwardContext,
    SupportTokenBinding,
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


def seeded_support(
    *,
    support_limit: int = 2,
) -> tuple[
    AnonymousSupportTracker,
    EpisodeState,
    TraversalToken,
    EpisodeState,
    TraversalToken,
]:
    support_tracker = tracker(support_limit=support_limit)
    hall = episode(
        "hall",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=1),
    )
    hall_token = token(
        hall,
        NOW + timedelta(seconds=1),
        ("source", "hall"),
        confidence="provisional",
    )
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
    apply_token(
        support_tracker,
        room_token,
        (hall, room),
        (belief(hall), belief(room)),
        sources=(hall_token,),
    )
    return support_tracker, hall, hall_token, room, room_token


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


def test_low_belief_settled_endpoint_survives_only_without_outward_context() -> None:
    support_tracker, hall, hall_token, room, room_token = seeded_support()
    clear_at = NOW + timedelta(minutes=3)
    clear_room = replace(
        room,
        status="clear",
        alias_states=(("binary_sensor.room", "off"),),
        last_event_at=clear_at,
        advanced_at=clear_at,
        traversal_valid_until=None,
    )
    low_probability = 0.2
    low_belief = replace(
        belief(room),
        log_odds=math.log(low_probability / (1.0 - low_probability)),
        last_updated_at=clear_at,
        context="cleared_without_outward",
        asserted_episode_id=None,
    )

    support_tracker.advance(
        clear_at,
        (hall, clear_room),
        (belief(hall), low_belief),
        (),
        (),
    )

    assert support_tracker.supports
    exact_target = episode(
        "room",
        profile_name="stay_presence",
        at=clear_at + timedelta(seconds=1),
    )
    other_target = episode(
        "room2",
        profile_name="stay_presence",
        at=clear_at + timedelta(seconds=1),
    )
    assert support_tracker.settled_endpoint_for(exact_target) is not None
    assert support_tracker.settled_endpoint_for(other_target) is None
    assert (
        support_tracker.settled_endpoint_for(
            replace(exact_target, status="unavailable")
        )
        is None
    )

    outward_belief = replace(low_belief, context="cleared_with_outward")
    support_tracker.advance(
        clear_at + timedelta(seconds=1),
        (hall, clear_room),
        (belief(hall), outward_belief),
        (),
        (),
    )
    assert support_tracker.supports == ()
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "outward_clear"


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
    support_tracker._counters[  # noqa: SLF001
        "support_stale_binding_ignored"
    ] = DIAGNOSTIC_COUNTER_LIMIT
    support_tracker._increment_counter(  # noqa: SLF001
        "support_stale_binding_ignored",
        1,
    )
    assert (
        support_tracker.counters["support_stale_binding_ignored"]
        == DIAGNOSTIC_COUNTER_LIMIT
    )


@pytest.mark.parametrize(
    ("state_update", "belief_update", "expected"),
    (
        (None, None, "unavailable"),
        ({"status": "unavailable"}, None, "unavailable"),
        ({"health_warning": True}, None, "health_warning"),
        ({}, {"health_warning": True}, "health_warning"),
        (
            {
                "cadence_warning": True,
                "cadence_warning_reason": "impossible_cadence",
            },
            None,
            "cadence_warning",
        ),
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
        "support_stale_binding_ignored": 0,
    }


def test_correlated_continuation_transfers_existing_support_only() -> None:
    support_tracker, _hall, _hall_token, room, room_token = seeded_support()
    original_support_id = support_tracker.supports[0].support_id
    target_at = NOW + timedelta(seconds=3)
    room2 = episode("room2", profile_name="stay_presence", at=target_at)
    room2_token = token(room2, target_at, ("room", "hall2", "room2"))
    target_authorization = authorization(room2_token, (room_token,))
    states = (room, room2)
    beliefs = (belief(room), belief(room2))
    support_tracker.advance(target_at, states, beliefs, (room_token,), ())

    assert support_tracker.has_transfer_authority(target_authorization)
    support_tracker.apply(
        target_at,
        EpisodeEffect(
            room2.node_id,
            room2.zone,
            room2.episode_id or "",
            "correlated_positive",
            target_at,
        ),
        target_authorization,
        room2_token,
        states,
        beliefs,
        (room_token, room2_token),
        (),
    )

    assert len(support_tracker.supports) == 1
    assert support_tracker.supports[0].support_id == original_support_id
    assert support_tracker.supports[0].current_node_id == "room2"
    assert support_tracker.counters["support_created"] == 1


@pytest.mark.parametrize("case", ("unbound", "stale", "off_path"))
def test_correlated_continuation_without_eligible_source_cannot_create_support(
    case: str,
) -> None:
    expected_supports: tuple[AnonymousOccupancySupport, ...]
    if case == "unbound":
        support_tracker = tracker()
        room = episode("room", profile_name="stay_presence")
        room_token = token(room, NOW, ("source", "hall", "room"))
        expected_supports = ()
    else:
        support_tracker, _hall, _hall_token, room, room_token = seeded_support()
        expected_supports = support_tracker.supports
    target_at = NOW + timedelta(seconds=3)
    room2 = episode("room2", profile_name="stay_presence", at=target_at)
    path = (
        ("hall", "hall2", "room2")
        if case == "off_path"
        else ("room", "hall2", "room2")
    )
    room2_token = token(room2, target_at, path)
    source_token = (
        replace(
            room_token,
            accepted_at=room_token.accepted_at - timedelta(microseconds=1),
        )
        if case == "stale"
        else room_token
    )
    target_authorization = authorization(room2_token, (source_token,))
    states = (room, room2)
    beliefs = (belief(room), belief(room2))
    support_tracker.advance(target_at, states, beliefs, (source_token,), ())

    assert not support_tracker.has_transfer_authority(target_authorization)
    support_tracker.apply(
        target_at,
        EpisodeEffect(
            room2.node_id,
            room2.zone,
            room2.episode_id or "",
            "correlated_positive",
            target_at,
        ),
        target_authorization,
        room2_token,
        states,
        beliefs,
        (source_token, room2_token),
        (),
    )

    assert support_tracker.supports == expected_supports
    assert all(item.current_node_id != "room2" for item in support_tracker.supports)


@pytest.mark.parametrize(
    ("offset", "expected_support", "expected_stale"),
    ((-1, None, True), (0, "current", False), (1, "current", False)),
)
def test_binding_authority_uses_support_mutation_frontier(
    offset: int,
    expected_support: str | None,
    expected_stale: bool,
) -> None:
    support_tracker, _hall, _hall_token, _room, room_token = seeded_support()
    support = support_tracker.supports[0]
    candidate = replace(
        room_token,
        accepted_at=support.updated_at + timedelta(microseconds=offset),
    )

    support_id, stale = support_tracker._binding_authority(  # noqa: SLF001
        candidate,
        {support.support_id: support},
        {candidate.token_id: support.support_id},
    )

    assert support_id == (
        support.support_id if expected_support == "current" else None
    )
    assert stale is expected_stale


def test_stale_on_path_binding_cannot_transfer_or_rebind_at_capacity() -> None:
    support_tracker, _hall, hall_token, room, _room_token = seeded_support(
        support_limit=1
    )
    original = support_tracker.supports[0]
    room2 = episode(
        "room2",
        profile_name="stay_presence",
        at=NOW + timedelta(seconds=3),
    )
    room2_token = token(
        room2,
        NOW + timedelta(seconds=3),
        ("hall", "hall2", "room2"),
    )

    apply_token(
        support_tracker,
        room2_token,
        (room, room2),
        (belief(room), belief(room2)),
        sources=(hall_token,),
    )

    assert support_tracker.supports == (original,)
    assert {item.token_id for item in support_tracker.bindings} >= {
        hall_token.token_id
    }
    assert room2_token.token_id not in {
        item.token_id for item in support_tracker.bindings
    }
    assert support_tracker.counters["support_stale_binding_ignored"] == 1


def test_fresh_on_path_binding_transfers_without_stale_linked_source() -> None:
    support_tracker, _hall, hall_token, room, room_token = seeded_support()
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
        sources=(hall_token, room_token),
    )

    assert support_tracker.supports[0].current_node_id == "hall2"
    assert support_tracker.counters["support_transferred"] == 1
    assert support_tracker.counters["support_stale_binding_ignored"] == 1


def test_mixed_stale_and_fresh_supports_transfer_only_the_fresh_support() -> None:
    support_tracker, _hall, hall_token, room, room_token = seeded_support()
    retained = support_tracker.supports[0]
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
        active_tokens=(other_token,),
        retained_tokens=(hall_token, room_token),
    )
    moving_id = next(
        support.support_id
        for support in support_tracker.supports
        if support.current_node_id == "other_room"
    )
    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=4),
    )
    target = token(
        hall2,
        NOW + timedelta(seconds=4),
        ("hall", "other_room", "hall2"),
    )

    apply_token(
        support_tracker,
        target,
        (room, other_room, hall2),
        (belief(room), belief(other_room), belief(hall2)),
        sources=(hall_token, other_token),
        retained_tokens=(room_token,),
    )

    assert next(
        support
        for support in support_tracker.supports
        if support.support_id == retained.support_id
    ) == retained
    moved = next(
        support
        for support in support_tracker.supports
        if support.support_id == moving_id
    )
    assert moved.current_node_id == "hall2"
    assert support_tracker.counters["support_coalesced"] == 0
    assert support_tracker.counters["support_stale_binding_ignored"] == 1
    binding_by_token = {
        binding.token_id: binding.support_id
        for binding in support_tracker.bindings
    }
    assert binding_by_token[hall_token.token_id] == retained.support_id
    assert binding_by_token[target.token_id] == moving_id


def test_stale_loser_binding_remaps_only_after_independent_coalescence() -> None:
    support_tracker, _hall, hall_token, room, _room_token = seeded_support()
    winner = support_tracker.supports[0]
    loser = replace(
        winner,
        support_id="support:zz-duplicate",
        updated_at=NOW + timedelta(seconds=3),
    )
    support_tracker.restore(
        (winner, loser),
        (SupportTokenBinding(hall_token.token_id, loser.support_id),),
        loser.updated_at,
    )

    support_tracker.advance(
        loser.updated_at,
        (room,),
        (belief(room),),
        (hall_token,),
        (),
    )

    assert tuple(item.support_id for item in support_tracker.supports) == (
        winner.support_id,
    )
    assert support_tracker.bindings == (
        SupportTokenBinding(hall_token.token_id, winner.support_id),
    )
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "same_zone"

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
        (room, hall2),
        (belief(room), belief(hall2)),
        sources=(hall_token,),
    )

    assert support_tracker.supports[0].current_node_id == "room"
    assert target.token_id not in {
        binding.token_id for binding in support_tracker.bindings
    }
    assert support_tracker.counters["support_stale_binding_ignored"] == 1


def test_fresh_off_path_linked_binding_cannot_transfer_or_rebind() -> None:
    support_tracker, _hall, _hall_token, room, room_token = seeded_support(
        support_limit=1
    )
    original = support_tracker.supports[0]
    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=3),
    )
    hall2_token = token(
        hall2,
        NOW + timedelta(seconds=3),
        ("source", "hall", "hall2"),
    )

    apply_token(
        support_tracker,
        hall2_token,
        (room, hall2),
        (belief(room), belief(hall2)),
        sources=(room_token,),
    )

    assert support_tracker.supports == (original,)
    assert hall2_token.token_id not in {
        item.token_id for item in support_tracker.bindings
    }
    assert support_tracker.counters["support_stale_binding_ignored"] == 0


def test_stale_active_binding_cannot_drive_component_coalescence() -> None:
    support_tracker, _hall, hall_token, room, room_token = seeded_support()
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
        active_tokens=(other_token,),
        retained_tokens=(hall_token, room_token),
    )
    connected_stale = replace(
        hall_token,
        path_node_ids=("other_hall", "hall"),
    )

    support_tracker.advance(
        NOW + timedelta(seconds=4),
        (room, other_room),
        (belief(room), belief(other_room)),
        (connected_stale, other_token),
        (room_token,),
    )

    assert len(support_tracker.supports) == 2
    assert support_tracker.counters["support_coalesced"] == 0
    assert support_tracker.counters["support_stale_binding_ignored"] == 0


def test_moving_expiry_at_target_time_removes_support_before_application() -> None:
    support_tracker, _hall, _hall_token, room, room_token = seeded_support()
    original_id = support_tracker.supports[0].support_id
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
    expiry = hall2_token.valid_until
    room2 = episode(
        "room2",
        profile_name="stay_presence",
        at=expiry,
    )
    room2_token = token(
        room2,
        expiry,
        ("hall", "hall2", "room2"),
    )

    apply_token(
        support_tracker,
        room2_token,
        (room, hall2, room2),
        (belief(room), belief(hall2), belief(room2)),
        sources=(hall2_token,),
    )

    assert len(support_tracker.supports) == 1
    replacement = support_tracker.supports[0]
    assert replacement.support_id != original_id
    assert replacement.current_node_id == "room2"
    assert support_tracker.counters["support_created"] == 2
    assert support_tracker.counters["support_expired"] == 1
    assert support_tracker.counters["support_stale_binding_ignored"] == 0
    assert {
        binding.token_id: binding.support_id
        for binding in support_tracker.bindings
    }[hall2_token.token_id] == replacement.support_id


def test_failed_application_commits_neither_supports_nor_counters() -> None:
    support_tracker, _hall, _hall_token, room, room_token = seeded_support()
    before_supports = support_tracker.supports
    before_bindings = support_tracker.bindings
    before_counters = support_tracker.counters
    before_transition = support_tracker.latest_transition
    hall2 = episode(
        "hall2",
        profile_name="transition_fast",
        at=NOW + timedelta(seconds=3),
    )
    target = token(
        hall2,
        NOW + timedelta(seconds=3),
        ("hall", "room", "hall2"),
    )
    invalid = replace(
        authorization(target, (room_token,)),
        authorized_at=target.accepted_at + timedelta(microseconds=1),
    )

    with pytest.raises(ValueError, match="inputs are inconsistent"):
        support_tracker.apply(
            target.accepted_at,
            EpisodeEffect(
                target.node_id,
                target.zone,
                target.episode_id,
                "positive",
                target.accepted_at,
            ),
            invalid,
            target,
            (room, hall2),
            (belief(room), belief(hall2)),
            (room_token, target),
            (),
        )

    assert support_tracker.supports == before_supports
    assert support_tracker.bindings == before_bindings
    assert support_tracker.counters == before_counters
    assert support_tracker.latest_transition == before_transition

    apply_token(
        support_tracker,
        target,
        (room, hall2),
        (belief(room), belief(hall2)),
        sources=(room_token,),
    )
    assert support_tracker.supports[0].current_node_id == "hall2"


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
        ("room", "other_room", "hall2"),
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
    current = support_tracker.supports[0]
    support_by_id = {current.support_id: current}
    binding_by_token = {
        binding.token_id: binding.support_id
        for binding in support_tracker.bindings
    }
    assert support_tracker._binding_authority(  # noqa: SLF001
        room_token,
        support_by_id,
        binding_by_token,
    ) == (None, True)
    assert support_tracker._binding_authority(  # noqa: SLF001
        rebound_token,
        support_by_id,
        binding_by_token,
    ) == (current.support_id, False)

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
    before_clear = support_tracker.counters
    support_tracker.clear(NOW + timedelta(seconds=12))
    assert support_tracker.supports == ()
    assert support_tracker.bindings == ()
    assert support_tracker.counters == before_clear
    assert support_tracker.latest_transition is not None
    assert support_tracker.latest_transition.reason == "count_zero"
