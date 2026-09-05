from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_07_21_0622z_isolated_master_closet_never_acquires() -> None:
    """Freeze the 06:22Z production false activation report."""
    incident_at = datetime(2026, 7, 21, 6, 22, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "master_bedroom_entrance": {
                    "zone": "master_bedroom_entrance",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bedroom_entrance_pir_motion_"
                            "motion_detection"
                        )
                    },
                    "adjacent": ["master_bedroom_closet"],
                    "initial_weight": 0.8,
                },
                "master_bedroom_closet": {
                    "zone": "master_bedroom_closet",
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bedroom_closet_motion_"
                            "motion_detection"
                        )
                    },
                    "adjacent": [
                        "master_bedroom_entrance",
                        "master_bathroom_light_motion",
                    ],
                    "initial_weight": 0.8,
                },
                "master_bathroom_light_motion": {
                    "zone": "master_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bathroom_master_bathroom_"
                            "light_motion_motion_detection"
                        )
                    },
                    "adjacent": ["master_bedroom_closet"],
                    "initial_weight": 0.7,
                },
                "alex_office_approach": {
                    "zone": "alex_office_approach",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.alex_office_approach"},
                    "adjacent": ["alex_office_door"],
                },
                "alex_office_door": {
                    "zone": "alex_office_door",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.alex_office_door"},
                    "adjacent": ["alex_office_approach", "alex_office"],
                },
                "alex_office": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.alex_office"},
                    "adjacent": ["alex_office_door"],
                },
                "guest_bedroom_approach": {
                    "zone": "guest_bedroom_approach",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.guest_bedroom_approach"},
                    "adjacent": ["guest_bedroom_door"],
                },
                "guest_bedroom_door": {
                    "zone": "guest_bedroom_door",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.guest_bedroom_door"},
                    "adjacent": ["guest_bedroom_approach", "guest_bedroom"],
                },
                "guest_bedroom": {
                    "zone": "guest_bedroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.guest_bedroom"},
                    "adjacent": ["guest_bedroom_door"],
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        2,
        incident_at.replace(second=0) - timedelta(seconds=10),
    )
    observations = []
    for entity_id, offset in (
        ("binary_sensor.alex_office_approach", -10),
        ("binary_sensor.alex_office_door", -9),
        ("binary_sensor.alex_office", -8),
        ("binary_sensor.guest_bedroom_approach", -7),
        ("binary_sensor.guest_bedroom_door", -6),
        ("binary_sensor.guest_bedroom", -5),
    ):
        observations.append(
            engine.observe(
                SensorInput(
                    entity_id,
                    "on",
                    incident_at + timedelta(seconds=offset),
                )
            )
        )

    result = engine.observe(
        SensorInput(
            "binary_sensor.master_bedroom_closet_motion_motion_detection",
            "on",
            incident_at,
        )
    )
    observations.append(result)

    closet_state = next(
        state
        for state in result.snapshot.policy_states
        if state.zone == "master_bedroom_closet"
    )
    assert closet_state.active is False
    assert not any(
        event.zone == "master_bedroom_closet" and event.kind == "acquired"
        for observation in observations
        for event in observation.policy_events
    )
    candidate = next(
        item
        for item in result.snapshot.pending_candidates
        if item.zone == "master_bedroom_closet"
    )
    expired = engine.advance(candidate.expires_at)
    assert not next(
        state
        for state in expired.snapshot.policy_states
        if state.zone == "master_bedroom_closet"
    ).active
    assert any(
        decision.zone == "master_bedroom_closet"
        and decision.reason == "untracked_expired"
        for decision in expired.policy_decisions
    )
