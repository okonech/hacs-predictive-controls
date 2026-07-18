from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput

NOW = datetime(2026, 7, 18, 11, 0, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def corridor_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["room_a", "room_b"],
                },
                "room_a": {
                    "zone": "room_a",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room_a"},
                    "adjacent": ["hall"],
                },
                "room_b": {
                    "zone": "room_b",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room_b"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def test_open_hallway_backtracking_authorizes_both_fresh_room_episodes() -> None:
    engine = ZoneModelEngine(corridor_map(), 2, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    first = engine.observe(
        SensorInput("binary_sensor.room_a", "on", NOW + timedelta(seconds=2))
    )
    engine.observe(
        SensorInput("binary_sensor.room_a", "off", NOW + timedelta(seconds=30))
    )
    second = engine.observe(
        SensorInput("binary_sensor.room_b", "on", NOW + timedelta(seconds=40))
    )

    assert [(event.zone, event.kind) for event in first.policy_events] == [
        ("room_a", "acquired")
    ]
    assert [(event.zone, event.kind) for event in second.policy_events] == [
        ("room_b", "acquired")
    ]


def test_out_of_order_callbacks_are_diagnosed_and_model_neutral() -> None:
    engine = ZoneModelEngine(corridor_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=5)))
    before = engine.snapshot

    stale = engine.observe(SensorInput("binary_sensor.hall", "off", NOW))

    assert stale.disposition == "stale"
    assert stale.snapshot == before


def test_prediction_is_not_an_authorization_or_active_input() -> None:
    engine = ZoneModelEngine(corridor_map(), 1, NOW)

    result = engine.advance(NOW + timedelta(minutes=1))

    assert result.policy_events == ()
    assert all(not state.active for state in result.snapshot.policy_states)


def test_s03_asserted_transition_supports_second_occupant_route() -> None:
    test_open_hallway_backtracking_authorizes_both_fresh_room_episodes()
