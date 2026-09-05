from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_28_clear_anchors_bounded_missed_edge_departure() -> None:
    bridge_at = datetime(2026, 8, 28, 7, 30, 59, 556832, tzinfo=UTC)
    source_at = datetime(2026, 8, 28, 7, 31, 2, 613621, tzinfo=UTC)
    source_clear_at = datetime(2026, 8, 28, 7, 32, 8, 624443, tzinfo=UTC)
    destination_at = datetime(2026, 8, 28, 7, 32, 16, 417206, tzinfo=UTC)
    observed_at = datetime(2026, 8, 28, 7, 51, 5, 472961, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bridge"},
                    "adjacent": ["source", "destination"],
                    "transition_seconds": {"source": 15, "destination": 15},
                },
                "source": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.source"},
                    "adjacent": ["bridge"],
                    "transition_seconds": {"bridge": 15},
                },
                "destination": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.destination"},
                    "adjacent": ["bridge"],
                    "transition_seconds": {"bridge": 15},
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        2,
        bridge_at - timedelta(seconds=1),
    )

    engine.observe(SensorInput("binary_sensor.bridge", "on", bridge_at))
    acquired = engine.observe(SensorInput("binary_sensor.source", "on", source_at))
    engine.observe(SensorInput("binary_sensor.source", "off", source_clear_at))
    departed = engine.observe(
        SensorInput("binary_sensor.destination", "on", destination_at)
    )
    cleared = engine.advance(source_clear_at + timedelta(seconds=10))
    final = engine.advance(observed_at)

    assert [(event.zone, event.kind) for event in acquired.policy_events] == [
        ("source", "acquired")
    ]
    authorization = departed.authorizations[0]
    assert authorization.authorized
    assert authorization.reason == "missed_edge_authorized"
    assert authorization.source_tokens[0].zone == "source"
    source_cleared = next(
        state for state in cleared.snapshot.belief_states if state.zone == "source"
    )
    assert source_cleared.context == "cleared_with_outward"
    source_policy = next(
        state for state in final.snapshot.policy_states if state.zone == "source"
    )
    assert source_policy.active is False
    assert [(event.zone, event.kind) for event in final.policy_events].count(
        ("source", "released")
    ) == 1
