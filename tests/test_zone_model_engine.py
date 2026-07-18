from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)

NOW = datetime(2026, 7, 18, 22, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def target_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def test_engine_composes_transition_authorization_and_policy_acquisition() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    hall = engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    room = engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    assert hall.policy_events == ()
    assert room.authorizations[0].reason == "adjacent_current"
    assert [(event.zone, event.kind) for event in room.policy_events] == [
        ("room", "acquired")
    ]
    assert {state.zone: state.active for state in room.snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }


def test_engine_count_zero_resets_beliefs_frontier_and_active_state() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    zero_at = NOW + timedelta(seconds=3)
    result = engine.observe_count(CountInput("count:zero", 0, True, zero_at))

    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("room", "released")
    ]
    assert result.snapshot.traversal_tokens == ()
    assert all(not state.active for state in result.snapshot.policy_states)
    assert all(
        state.generation_episode_id is None for state in result.snapshot.belief_states
    )


def test_engine_timer_degrades_transition_but_preserves_held_room() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    direct = engine.advance(NOW + timedelta(minutes=20))

    states = {state.zone: state for state in direct.snapshot.policy_states}
    assert states["room"].active is True
    assert ("room", "released") not in {
        (event.zone, event.kind) for event in direct.policy_events
    }
    episodes = {state.node_id: state for state in direct.snapshot.episode_states}
    assert episodes["hall"].health_warning
    assert not episodes["room"].health_warning


def test_engine_bootstrap_projects_current_stay_assertion_without_public_edge() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    snapshot = engine.bootstrap_sensor_snapshot(
        (
            SensorInput("binary_sensor.hall", "off", NOW),
            SensorInput("binary_sensor.room", "on", NOW),
        ),
        NOW,
    )

    assert {state.zone: state.active for state in snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }
    assert engine.audit_rows == ()
    assert snapshot.traversal_tokens == ()

    empty_house = ZoneModelEngine(target_map(), 0, NOW)
    empty_snapshot = empty_house.bootstrap_sensor_snapshot(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )
    assert all(not state.active for state in empty_snapshot.policy_states)


def test_engine_direct_stay_assertion_can_acquire_without_a_hallway_edge() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    result = engine.observe(SensorInput("binary_sensor.room", "on", NOW))

    assert result.authorizations[0].authorized
    assert result.authorizations[0].reason == "source_free_corroborated"
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("room", "acquired")
    ]


def test_engine_rejects_ambiguous_behavior_or_mixed_profile_zones() -> None:
    ambiguous = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unknown": {
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": "binary_sensor.unknown"},
                }
            }
        }
    )
    with pytest.raises(ValueError, match="ambiguous occupancy metadata"):
        ZoneModelEngine(ambiguous, 1, NOW)

    mixed = PredictiveMap.from_mapping(
        {
            "nodes": {
                "pir": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.pir"},
                },
                "presence": {
                    "zone": "room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.presence"},
                },
            }
        }
    )
    with pytest.raises(ValueError, match="one shared profile"):
        ZoneModelEngine(mixed, 1, NOW)


def test_engine_snapshot_restore_is_atomic_and_emits_no_bootstrap_edge() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))
    snapshot = engine.snapshot

    restored = ZoneModelEngine.restore(
        target_map(),
        snapshot,
        engine.audit_rows,
        room_at + timedelta(seconds=1),
    )

    assert restored.snapshot.policy_states == tuple(
        sorted(restored.snapshot.policy_states, key=lambda state: state.zone)
    )
    assert {state.zone: state.active for state in restored.snapshot.policy_states}[
        "room"
    ] is True
    assert restored.snapshot.current_token_ids
