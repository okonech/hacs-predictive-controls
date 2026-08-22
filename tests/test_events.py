from __future__ import annotations

from datetime import UTC, datetime

from custom_components.predictive_controls.events import event_from_entity
from custom_components.predictive_controls.model import PredictiveMap


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "living_left": {
                    "floor": "first_floor",
                    "zone": "living_room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "still_target": "binary_sensor.living_still",
                        "moving_target": "binary_sensor.living_moving",
                    },
                    "initial_weight": 0.9,
                }
            }
        }
    )


def test_event_from_entity_normalizes_mapped_binary_state() -> None:
    now = datetime(2026, 6, 7, tzinfo=UTC)

    event = event_from_entity(make_map(), "binary_sensor.living_still", "on", now)

    assert event is not None
    assert event.entity_id == "binary_sensor.living_still"
    assert event.node_id == "living_left"
    assert event.zone == "living_room"
    assert event.floor == "first_floor"
    assert event.role == "anchor_sensor"
    assert event.occupancy_behavior == "sticky"
    assert event.signal_type == "still_target"
    assert event.state == "on"
    assert event.event_at == now
    assert event.reliability == 0.9


def test_event_from_entity_preserves_health_states_and_rejects_junk() -> None:
    predictive_map = make_map()
    now = datetime(2026, 6, 7, tzinfo=UTC)

    assert event_from_entity(predictive_map, "binary_sensor.missing", "on", now) is None
    unknown = event_from_entity(
        predictive_map, "binary_sensor.living_still", "unknown", now
    )
    unavailable = event_from_entity(
        predictive_map, "binary_sensor.living_still", "unavailable", now
    )
    assert unknown is not None and unknown.state == "unknown"
    assert unavailable is not None and unavailable.state == "unavailable"
    assert (
        event_from_entity(predictive_map, "binary_sensor.living_still", "junk", now)
        is None
    )
    normalized = event_from_entity(
        predictive_map,
        "binary_sensor.living_still",
        "junk",
        now,
        allow_unsupported_state=True,
    )
    assert normalized is not None and normalized.state == "unknown"


def test_event_from_entity_normalizes_live_interaction_but_not_startup_state() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bathroom_switch": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_002": "event.bathroom_scene_002"
                    },
                }
            }
        }
    )
    now = datetime(2026, 8, 22, 7, 28, 36, 46000, tzinfo=UTC)
    retained_timestamp = "2026-08-22T07:28:36.046+00:00"

    live = event_from_entity(
        predictive_map,
        "event.bathroom_scene_002",
        retained_timestamp,
        now,
    )
    startup = event_from_entity(
        predictive_map,
        "event.bathroom_scene_002",
        retained_timestamp,
        now,
        allow_unsupported_state=True,
    )
    unavailable = event_from_entity(
        predictive_map,
        "event.bathroom_scene_002",
        "unavailable",
        now,
    )

    assert live is not None and live.state == "pressed"
    assert startup is not None and startup.state == "unknown"
    assert unavailable is not None and unavailable.state == "unavailable"
