from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_20_isolated_gym_assertion_never_activates() -> None:
    incident_at = datetime(2026, 8, 20, 17, 0, 30, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "master_entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.master_entrance"},
                    "adjacent": ["top"],
                },
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.top"},
                    "adjacent": [
                        "master_entrance",
                        "shaila_office",
                        "bottom",
                        "alex_office",
                    ],
                },
                "shaila_office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.shaila_office"},
                    "adjacent": ["top"],
                },
                "gym": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.gym"},
                    "adjacent": ["dining"],
                },
                "foyer": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.foyer"},
                    "adjacent": ["dining", "bottom"],
                },
                "dining": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.dining"},
                    "adjacent": ["foyer", "kitchen", "gym"],
                },
                "kitchen": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.kitchen"},
                    "adjacent": ["dining"],
                },
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.bottom"},
                    "adjacent": ["foyer", "top"],
                },
                "alex_office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.alex_office"},
                    "adjacent": ["top"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 2, incident_at)
    for entity_id, state, event_at in (
        ("binary_sensor.master_entrance", "on", "2026-08-20T17:00:33.807835+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:00:34.599475+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:00:41.725395+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:00:46.629097+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:03:17.804091+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:03:35.927390+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:04:30.862924+00:00"),
        ("binary_sensor.gym", "on", "2026-08-20T17:06:39.497066+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:07:44.661861+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:08:15.062751+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:08:20.189974+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:09.242269+00:00"),
        ("binary_sensor.dining", "on", "2026-08-20T17:09:09.656182+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:09:13.675459+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:09:25.715140+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:30.817675+00:00"),
        ("binary_sensor.kitchen", "off", "2026-08-20T17:09:36.007613+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:09:40.741138+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:45.986312+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:09:48.629758+00:00"),
        ("binary_sensor.bottom", "on", "2026-08-20T17:09:49.026000+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:09:53.153332+00:00"),
        ("binary_sensor.dining", "off", "2026-08-20T17:09:57.848001+00:00"),
        ("binary_sensor.alex_office", "on", "2026-08-20T17:09:59.684850+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:10:01.671418+00:00"),
        ("binary_sensor.bottom", "off", "2026-08-20T17:10:05.522066+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:12.091060+00:00"),
        ("binary_sensor.alex_office", "off", "2026-08-20T17:10:19.851787+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:10:23.948782+00:00"),
        ("binary_sensor.alex_office", "on", "2026-08-20T17:10:27.919616+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:34.562183+00:00"),
        ("binary_sensor.kitchen", "off", "2026-08-20T17:10:38.013203+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:10:42.146287+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:10:48.139304+00:00"),
    ):
        engine.observe(SensorInput(entity_id, state, datetime.fromisoformat(event_at)))

    result = engine.advance(datetime(2026, 8, 20, 17, 11, 14, tzinfo=UTC))
    gym_episode = next(
        state for state in result.snapshot.episode_states if state.zone == "gym"
    )
    shaila_policy = next(
        state
        for state in result.snapshot.policy_states
        if state.zone == "shaila_office"
    )
    alex_policy = next(
        state for state in result.snapshot.policy_states if state.zone == "alex_office"
    )
    gym_policy = next(
        state for state in result.snapshot.policy_states if state.zone == "gym"
    )

    assert shaila_policy.active
    assert alex_policy.active
    assert gym_policy.active is False
    assert not gym_episode.health_warning
    assert gym_episode.degradation_reason is None
    assert not any(
        event.zone == "gym" and event.kind == "released"
        for event in result.policy_events
    )

    decayed = engine.advance(datetime(2026, 8, 20, 18, 0, tzinfo=UTC))
    final_gym_policy = next(
        state for state in decayed.snapshot.policy_states if state.zone == "gym"
    )
    gym_events = tuple(
        event
        for event in (*result.policy_events, *decayed.policy_events)
        if event.zone == "gym"
    )
    assert final_gym_policy.active is False
    assert not gym_events
