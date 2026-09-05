from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import LOG_ODDS_LIMIT
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_22_0728z_physical_press_acquires_then_decays_normally() -> None:
    press_at = datetime(2026, 8, 22, 7, 28, 36, 46000, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
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
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["bathroom_interaction"],
                },
            }
        }
    )

    with_outward = ZoneModelEngine(
        predictive_map,
        1,
        press_at - timedelta(seconds=5),
    )
    acquired = with_outward.observe(
        SensorInput("event.bathroom_scene_002", "pressed", press_at)
    )
    bathroom_belief = next(
        belief
        for belief in acquired.snapshot.belief_states
        if belief.zone == "bathroom"
    )

    assert bathroom_belief.log_odds == LOG_ODDS_LIMIT
    assert [(event.zone, event.kind) for event in acquired.policy_events] == [
        ("bathroom", "acquired")
    ]

    closet_at = press_at + timedelta(minutes=1)
    left_bathroom = with_outward.observe(
        SensorInput("binary_sensor.closet", "on", closet_at)
    )
    bathroom_after_departure = next(
        belief
        for belief in left_bathroom.snapshot.belief_states
        if belief.zone == "bathroom"
    )
    assert bathroom_after_departure.context == "cleared_with_outward"

    release_check_at = press_at + timedelta(minutes=40)
    released = with_outward.advance(release_check_at)
    bathroom_policy = next(
        policy
        for policy in released.snapshot.policy_states
        if policy.zone == "bathroom"
    )
    assert bathroom_policy.active is False
    assert any(
        event.zone == "bathroom" and event.kind == "released"
        for event in released.policy_events
    )

    without_outward = ZoneModelEngine(
        predictive_map,
        1,
        press_at - timedelta(seconds=5),
    )
    without_outward.observe(
        SensorInput("event.bathroom_scene_002", "pressed", press_at)
    )
    slow_decay = without_outward.advance(release_check_at)
    bathroom_policy = next(
        policy
        for policy in slow_decay.snapshot.policy_states
        if policy.zone == "bathroom"
    )
    assert bathroom_policy.active is True

    eventual_release = without_outward.advance(press_at + timedelta(minutes=70))
    bathroom_policy = next(
        policy
        for policy in eventual_release.snapshot.policy_states
        if policy.zone == "bathroom"
    )
    assert bathroom_policy.active is False
