from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_confirmed_track_before_source_clear_marks_outward(
    authoritative_count: int,
) -> None:
    source_on_at = _at("2026-09-05T05:30:12.426589Z")
    interaction_at = _at("2026-09-05T05:44:05.117000Z")
    closet_at = _at("2026-09-05T05:52:35.652266Z")
    entrance_at = _at("2026-09-05T05:52:40.023935Z")
    hallway_at = _at("2026-09-05T05:52:41.648837Z")
    source_clear_at = _at("2026-09-05T05:52:46.398577Z")
    stable_clear_at = source_clear_at + timedelta(seconds=10)
    observed_at = _at("2026-09-05T06:37:03.502170Z")
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bathroom_presence": {
                    "zone": "bathroom",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.bathroom_presence"},
                    "adjacent": ["closet"],
                },
                "bathroom_interaction": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_002": "event.bathroom_scene_002"
                    },
                    "adjacent": ["closet"],
                },
                "closet": {
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.closet"},
                    "adjacent": [
                        "bathroom_presence",
                        "bathroom_interaction",
                        "entrance",
                    ],
                },
                "entrance": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["closet", "hallway"],
                },
                "hallway": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hallway"},
                    "adjacent": ["entrance"],
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        source_on_at - timedelta(seconds=1),
    )

    engine.observe(
        SensorInput("binary_sensor.bathroom_presence", "on", source_on_at)
    )
    acquired = engine.observe(
        SensorInput("event.bathroom_scene_002", "pressed", interaction_at)
    )
    closet = engine.observe(SensorInput("binary_sensor.closet", "on", closet_at))
    engine.observe(SensorInput("binary_sensor.entrance", "on", entrance_at))
    hallway = engine.observe(
        SensorInput("binary_sensor.hallway", "on", hallway_at)
    )
    source_clear = engine.observe(
        SensorInput("binary_sensor.bathroom_presence", "off", source_clear_at)
    )
    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        source_clear.snapshot.updated_at,
    )
    cleared = engine.advance(stable_clear_at)
    restored_cleared = restored.advance(stable_clear_at)
    final = engine.advance(observed_at)
    restored_final = restored.advance(observed_at)

    assert [(event.zone, event.kind) for event in acquired.policy_events] == [
        ("bathroom", "acquired")
    ]
    assert closet.authorizations[0].reason == "track_bootstrap_pending"
    assert hallway.authorizations[0].reason == "track_confirmed"
    assert hallway.authorizations[0].path_node_ids == (
        "closet",
        "entrance",
        "hallway",
    )
    bathroom_belief = next(
        state for state in cleared.snapshot.belief_states if state.zone == "bathroom"
    )
    interaction = next(
        state
        for state in cleared.snapshot.episode_states
        if state.node_id == "bathroom_interaction"
    )
    assert bathroom_belief.generation_episode_id == interaction.episode_id
    assert bathroom_belief.context == "cleared_with_outward"
    assert restored_cleared.snapshot == cleared.snapshot
    bathroom_policy = next(
        state for state in final.snapshot.policy_states if state.zone == "bathroom"
    )
    assert bathroom_policy.active is False
    assert restored_final.snapshot == final.snapshot
    assert [(event.zone, event.kind) for event in final.policy_events].count(
        ("bathroom", "released")
    ) == 1
