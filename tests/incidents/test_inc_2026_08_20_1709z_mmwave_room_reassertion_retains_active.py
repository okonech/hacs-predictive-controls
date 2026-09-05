from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_20_1709z_mmwave_room_reassertion_retains_active() -> None:
    incident_at = datetime(2026, 8, 20, 17, 9, 40, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bottom"},
                    "adjacent": ["top"],
                },
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["bottom", "room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.room"},
                    "adjacent": ["top"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 2, incident_at)
    observations = []
    for entity_id, state, event_at in (
        ("binary_sensor.bottom", "on", "2026-08-20T17:09:49.026000+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:09:53.153332+00:00"),
        ("binary_sensor.room", "on", "2026-08-20T17:09:59.684850+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:12.091060+00:00"),
        ("binary_sensor.room", "off", "2026-08-20T17:10:19.851787+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:10:23.948782+00:00"),
        ("binary_sensor.room", "on", "2026-08-20T17:10:27.919616+00:00"),
    ):
        observations.append(
            engine.observe(
                SensorInput(entity_id, state, datetime.fromisoformat(event_at))
            )
        )

    final = engine.advance(datetime(2026, 8, 20, 17, 12, tzinfo=UTC))
    room_policy = next(
        state for state in final.snapshot.policy_states if state.zone == "room"
    )
    room_episode = next(
        state for state in final.snapshot.episode_states if state.zone == "room"
    )

    assert any(
        event.zone == "room" and event.kind == "acquired"
        for event in observations[2].policy_events
    )
    assert any(
        event.zone == "room" and event.kind == "refreshed"
        for event in observations[-1].policy_events
    )
    assert room_episode.profile_name == "stay_presence"
    assert room_episode.cadence_warning is False
    assert room_policy.active is True
    assert not any(
        event.zone == "room" and event.kind == "released"
        for observation in (*observations, final)
        for event in observation.policy_events
    )
