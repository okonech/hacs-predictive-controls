from datetime import datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


@pytest.mark.target_model
def test_inc_2026_08_22_1212z_shaila_office_sustained_flapping_stays_below_on_threshold(
) -> None:
    entity_id = "binary_sensor.target"
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": entity_id},
                    "initial_weight": 0.75,
                }
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        1,
        datetime.fromisoformat("2026-08-22T12:12:00.312303+00:00"),
    )
    retained_history = (
        ("2026-08-22T12:12:00.312303+00:00", "on"),
        ("2026-08-22T12:13:21.696150+00:00", "off"),
        ("2026-08-22T12:15:14.321496+00:00", "on"),
        ("2026-08-22T12:15:47.199246+00:00", "off"),
        ("2026-08-22T12:17:35.825838+00:00", "on"),
        ("2026-08-22T12:18:32.255483+00:00", "off"),
        ("2026-08-22T12:20:32.331074+00:00", "on"),
        ("2026-08-22T12:21:36.262743+00:00", "off"),
        ("2026-08-22T12:21:58.835773+00:00", "on"),
        ("2026-08-22T12:22:40.214191+00:00", "off"),
        ("2026-08-22T12:23:20.335658+00:00", "on"),
        ("2026-08-22T12:23:55.716778+00:00", "off"),
        ("2026-08-22T12:25:13.843043+00:00", "on"),
        ("2026-08-22T12:26:04.772062+00:00", "off"),
        ("2026-08-22T12:31:54.352277+00:00", "on"),
        ("2026-08-22T12:32:29.233070+00:00", "off"),
        ("2026-08-22T12:33:43.857402+00:00", "on"),
        ("2026-08-22T12:34:34.286213+00:00", "off"),
    )

    result = None
    for timestamp, state in retained_history:
        result = engine.observe(
            SensorInput(
                entity_id,
                state,
                datetime.fromisoformat(timestamp),
                reliability=0.75,
            )
        )

    assert result is not None
    target_belief = next(
        belief for belief in result.snapshot.belief_states if belief.zone == "target"
    )
    target_policy = next(
        policy for policy in result.snapshot.policy_states if policy.zone == "target"
    )
    assert target_belief.probability < 0.70
    assert not target_policy.active
    assert result.policy_events == ()
