from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.test_zone_model_engine import target_map


def test_stuck_sensor_health_is_bounded_and_directly_observable() -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    engine = ZoneModelEngine(target_map(), 1, now)
    engine.observe(SensorInput("binary_sensor.hall", "on", now))
    engine.observe(SensorInput("binary_sensor.room", "on", now + timedelta(seconds=2)))

    result = engine.advance(now + timedelta(hours=2))

    assert any(state.health_warning for state in result.snapshot.episode_states)
    assert all(not state.active for state in result.snapshot.policy_states)
