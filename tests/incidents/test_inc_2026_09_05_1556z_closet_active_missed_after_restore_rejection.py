from datetime import UTC, datetime

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


def _incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["top", "closet"],
                    "initial_weight": 0.8,
                },
                "closet": {
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.8,
                },
                "background": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.background"},
                    "adjacent": [],
                    "initial_weight": 0.8,
                },
            }
        }
    )


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_1556z_closet_active_missed_after_restore_rejection(
    authoritative_count: int,
) -> None:
    predictive_map = _incident_map()
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        _at("2026-09-05T01:16:29Z"),
    )
    for entity_id, state, event_at in (
        ("binary_sensor.top", "on", "2026-09-05T01:16:30.919930Z"),
        ("binary_sensor.entrance", "on", "2026-09-05T01:16:40.028350Z"),
        ("binary_sensor.closet", "on", "2026-09-05T01:16:41.843671Z"),
        ("binary_sensor.closet", "off", "2026-09-05T01:20:19.951114Z"),
    ):
        engine.observe(SensorInput(entity_id, state, _at(event_at)))
    released = engine.advance(_at("2026-09-05T02:11:41.735890Z"))

    closet_policy = next(
        state for state in released.snapshot.policy_states if state.zone == "closet"
    )
    assert closet_policy.active is False
    assert [
        (support.current_node_id, support.current_zone, support.state)
        for support in released.snapshot.anonymous_supports
    ] == [("closet", "closet", "settled")]

    engine.observe(
        SensorInput("binary_sensor.background", "on", _at("2026-09-05T07:53:40Z"))
    )
    engine.observe(
        SensorInput(
            "binary_sensor.background",
            "off",
            _at("2026-09-05T07:53:41Z"),
        )
    )
    engine.advance(_at("2026-09-05T07:53:46Z"))
    unavailable = engine.observe(
        SensorInput(
            "binary_sensor.background",
            "unavailable",
            _at("2026-09-05T07:53:47Z"),
        )
    )
    background = next(
        state
        for state in unavailable.snapshot.episode_states
        if state.node_id == "background"
    )
    assert background.status == "unavailable"

    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        _at("2026-09-05T07:54:05.919458Z"),
    )
    incident_results = []
    for state, event_at in (
        ("on", "2026-09-05T15:55:09.320493Z"),
        ("off", "2026-09-05T15:56:13.538504Z"),
        ("on", "2026-09-05T15:56:54.026176Z"),
    ):
        incident_results.append(
            restored.observe(
                SensorInput("binary_sensor.closet", state, _at(event_at))
            )
        )
    sleep_off = restored.advance(_at("2026-09-05T15:57:28.615217Z"))

    acquisitions = [
        event
        for result in incident_results
        for event in result.policy_events
        if event.zone == "closet" and event.kind == "acquired"
    ]
    assert len(acquisitions) == 1
    assert acquisitions[0].event_at == _at("2026-09-05T15:55:09.320493Z")
    sleep_off_policy = next(
        state
        for state in sleep_off.snapshot.policy_states
        if state.zone == "closet"
    )
    assert sleep_off_policy.active is True
    assert sleep_off.snapshot.updated_at == _at("2026-09-05T15:57:28.615217Z")
    assert sleep_off.snapshot.updated_at < _at("2026-09-05T15:57:50.057472Z")
