"""Independent COUNT-011 proofs; no production incident fixture is modified."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.test_zone_model_supports import (
    NOW,
    apply_token,
    belief,
    episode,
    seeded_support,
    token,
)

pytestmark = pytest.mark.target_model


def test_outward_belief_clear_retains_same_settled_support_id() -> None:
    supports, hall, _hall_token, room, _room_token = seeded_support()
    original = supports.supports[0]
    at = NOW + timedelta(seconds=30)
    clear = replace(
        room, status="clear", clear_emitted=True,
        alias_states=(("binary_sensor.room", "off"),),
        traversal_valid_until=None, last_event_at=at, advanced_at=at,
    )
    outward = replace(
        belief(clear, probability=0.2), context="cleared_with_outward",
        asserted_episode_id=None,
    )
    supports.advance(at, (hall, clear), (belief(hall), outward), (), ())
    assert supports.supports == (original,)
    supports.advance(at + timedelta(seconds=1), (clear,), (outward,), (), ())
    assert supports.supports == (original,)


@pytest.mark.parametrize("source_evicted", (False, True))
def test_on_path_transfer_preserves_id_through_outward_and_token_pruning(
    source_evicted: bool,
) -> None:
    supports, hall, _hall_token, room, room_token = seeded_support()
    original = supports.supports[0]
    at = NOW + timedelta(seconds=30)
    clear = replace(
        room, status="clear", clear_emitted=True,
        alias_states=(("binary_sensor.room", "off"),),
        traversal_valid_until=None, last_event_at=at, advanced_at=at,
    )
    outward = replace(
        belief(clear), context="cleared_with_outward", asserted_episode_id=None,
    )
    target = episode("hall2", profile_name="transition_fast", at=at)
    target_token = token(target, at, ("hall", "room", "hall2"))
    apply_token(
        supports, target_token, (hall, clear, target),
        (belief(hall), outward, belief(target)), sources=(room_token,),
        active_tokens=(target_token,) if source_evicted else (room_token, target_token),
    )
    assert len(supports.supports) == 1
    moved = supports.supports[0]
    assert moved.support_id == original.support_id
    assert moved.created_at == original.created_at
    assert moved.current_node_id == "hall2"
    assert moved.state == "moving"
    assert supports.counters["support_created"] == 1
    assert supports.counters["support_transferred"] == 1
    assert all(
        binding.token_id in {
            target_token.token_id,
            *(() if source_evicted else (room_token.token_id,)),
        }
        for binding in supports.bindings
    )
