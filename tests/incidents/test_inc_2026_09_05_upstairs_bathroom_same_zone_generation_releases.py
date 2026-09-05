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
def test_inc_2026_09_05_upstairs_bathroom_same_zone_generation_releases(
    authoritative_count: int,
) -> None:
    hall_first_at = _at("2026-09-05T06:26:40.995428Z")
    bathroom_at = _at("2026-09-05T06:26:49.205190Z")
    hall_first_clear_at = _at("2026-09-05T06:26:53.208478Z")
    interaction_at = _at("2026-09-05T06:26:55.250000Z")
    bathroom_first_clear_at = _at("2026-09-05T06:27:22.803942Z")
    bathroom_return_at = _at("2026-09-05T06:27:44.895862Z")
    hall_return_at = _at("2026-09-05T06:28:15.338213Z")
    office_at = _at("2026-09-05T06:28:20.373595Z")
    bathroom_final_clear_at = _at("2026-09-05T06:28:36.102232Z")
    stable_clear_at = bathroom_final_clear_at + timedelta(seconds=10)
    observed_at = _at("2026-09-05T07:11:04.674406Z")
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": [
                        "bathroom_presence",
                        "bathroom_interaction",
                        "office",
                    ],
                    "initial_weight": 0.85,
                },
                "bathroom_presence": {
                    "zone": "bathroom",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.bathroom"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.7,
                },
                "bathroom_interaction": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"interaction_scene_002": "event.bathroom_scene"},
                    "adjacent": ["hall"],
                    "initial_weight": 1.0,
                },
                "office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.office"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.75,
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        hall_first_at - timedelta(seconds=1),
    )

    engine.observe(SensorInput("binary_sensor.hall", "on", hall_first_at))
    acquired = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", bathroom_at)
    )
    engine.observe(
        SensorInput("binary_sensor.hall", "off", hall_first_clear_at)
    )
    engine.observe(SensorInput("event.bathroom_scene", "pressed", interaction_at))
    engine.observe(
        SensorInput("binary_sensor.bathroom", "off", bathroom_first_clear_at)
    )
    returned = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", bathroom_return_at)
    )
    before_outward = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        engine.snapshot.updated_at,
    )
    departed = engine.observe(
        SensorInput("binary_sensor.hall", "on", hall_return_at)
    )
    restored_departed = before_outward.observe(
        SensorInput("binary_sensor.hall", "on", hall_return_at)
    )
    after_outward_payload = serialize_target_state(predictive_map, engine)

    engines = (engine, before_outward)
    for item in engines:
        item.observe(SensorInput("binary_sensor.office", "on", office_at))
        item.observe(
            SensorInput(
                "binary_sensor.bathroom",
                "off",
                bathroom_final_clear_at,
            )
        )
    cleared = tuple(item.advance(stable_clear_at) for item in engines)
    final = tuple(item.advance(observed_at) for item in engines)

    assert [(event.zone, event.kind) for event in acquired.policy_events] == [
        ("bathroom", "acquired")
    ]
    assert returned.authorizations[0].reason == "same_zone_authorized"
    predecessor = returned.authorizations[0].source_tokens[0]
    generation = next(
        state
        for state in returned.snapshot.belief_states
        if state.zone == "bathroom"
    ).generation_episode_id
    assert any(
        use.token_id == predecessor.token_id
        and use.target_episode_id == generation
        and use.reason == "same_zone_authorized"
        for use in returned.snapshot.authorization_uses
    )
    assert any(
        token.token_id == predecessor.token_id
        for token in departed.authorizations[0].source_tokens
    )
    assert restored_departed.snapshot == departed.snapshot
    bathroom_belief = next(
        state for state in cleared[0].snapshot.belief_states if state.zone == "bathroom"
    )
    assert bathroom_belief.context == "cleared_with_outward"
    assert cleared[1].snapshot == cleared[0].snapshot
    bathroom_policy = next(
        state for state in final[0].snapshot.policy_states if state.zone == "bathroom"
    )
    assert bathroom_policy.active is False
    assert final[1].snapshot == final[0].snapshot
    assert [(event.zone, event.kind) for event in final[0].policy_events].count(
        ("bathroom", "released")
    ) == 1

    after_outward = restore_target_state(
        predictive_map,
        after_outward_payload,
        hall_return_at,
    )
    after_outward.observe(SensorInput("binary_sensor.office", "on", office_at))
    after_outward.observe(
        SensorInput(
            "binary_sensor.bathroom",
            "off",
            bathroom_final_clear_at,
        )
    )
    after_outward_cleared = after_outward.advance(stable_clear_at)
    after_outward_final = after_outward.advance(observed_at)
    assert after_outward_cleared.snapshot == cleared[0].snapshot
    assert after_outward_final.snapshot == final[0].snapshot
