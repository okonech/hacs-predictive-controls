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
    assert event.signal_type == "still_target"
    assert event.state == "on"
    assert event.event_at == now
    assert event.reliability == 0.9


def test_event_from_entity_ignores_unmapped_or_unusable_states() -> None:
    predictive_map = make_map()
    now = datetime(2026, 6, 7, tzinfo=UTC)

    assert event_from_entity(predictive_map, "binary_sensor.missing", "on", now) is None
    assert (
        event_from_entity(predictive_map, "binary_sensor.living_still", "unknown", now)
        is None
    )
