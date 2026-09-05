from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_1707z_office_light_reverted_after_correct_active_edge(
    authoritative_count: int,
) -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["office"],
                    "initial_weight": 0.85,
                },
                "office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.office"},
                    "adjacent": ["top"],
                    "initial_weight": 0.75,
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        _at("2026-09-05T17:06:59Z"),
    )

    stairs = engine.observe(
        SensorInput("binary_sensor.top", "on", _at("2026-09-05T17:07:00.146Z"))
    )
    office = engine.observe(
        SensorInput(
            "binary_sensor.office",
            "on",
            _at("2026-09-05T17:07:03.733305Z"),
        )
    )
    observed_light_off = engine.advance(_at("2026-09-05T17:07:09.857Z"))

    assert stairs.policy_events == ()
    assert [(event.zone, event.kind) for event in office.policy_events] == [
        ("office", "acquired")
    ]
    assert office.policy_events[0].event_at == _at("2026-09-05T17:07:03.733305Z")
    assert not any(
        event.zone == "office" and event.kind == "released"
        for event in observed_light_off.policy_events
    )
    office_policy = next(
        state
        for state in observed_light_off.snapshot.policy_states
        if state.zone == "office"
    )
    assert office_policy.active is True
    assert observed_light_off.snapshot.updated_at == _at("2026-09-05T17:07:09.857Z")
