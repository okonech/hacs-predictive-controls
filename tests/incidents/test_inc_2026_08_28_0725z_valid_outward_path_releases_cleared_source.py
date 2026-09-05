from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_28_0725z_valid_outward_path_releases_cleared_source() -> None:
    hall_first_at = datetime(2026, 8, 28, 7, 25, 49, 850011, tzinfo=UTC)
    source_at = datetime(2026, 8, 28, 7, 25, 56, 665640, tzinfo=UTC)
    hall_first_clear_at = datetime(2026, 8, 28, 7, 26, 0, 816503, tzinfo=UTC)
    hall_return_at = datetime(2026, 8, 28, 7, 26, 53, 550848, tzinfo=UTC)
    destination_at = datetime(2026, 8, 28, 7, 26, 58, 118373, tzinfo=UTC)
    source_clear_at = datetime(2026, 8, 28, 7, 27, 5, 936116, tzinfo=UTC)
    observed_at = datetime(2026, 8, 28, 7, 51, 5, 472961, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["source", "destination"],
                },
                "source": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.source"},
                    "adjacent": ["hall"],
                },
                "destination": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.destination"},
                    "adjacent": ["hall"],
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        2,
        hall_first_at - timedelta(seconds=1),
    )

    engine.observe(SensorInput("binary_sensor.hall", "on", hall_first_at))
    acquired = engine.observe(SensorInput("binary_sensor.source", "on", source_at))
    engine.observe(
        SensorInput("binary_sensor.hall", "off", hall_first_clear_at)
    )
    engine.advance(hall_first_clear_at + timedelta(seconds=5))
    departed = engine.observe(
        SensorInput("binary_sensor.hall", "on", hall_return_at)
    )
    engine.observe(
        SensorInput("binary_sensor.destination", "on", destination_at)
    )
    engine.observe(SensorInput("binary_sensor.source", "off", source_clear_at))
    cleared = engine.advance(source_clear_at + timedelta(seconds=10))
    final = engine.advance(observed_at)

    assert [(event.zone, event.kind) for event in acquired.policy_events] == [
        ("source", "acquired")
    ]
    assert departed.authorizations[0].authorized
    assert departed.authorizations[0].source_tokens[0].zone == "source"
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
