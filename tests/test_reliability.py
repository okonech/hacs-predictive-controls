from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.test_zone_model_engine import target_map


def test_transition_health_is_bounded_without_discarding_held_room_evidence() -> None:
    """Synthetic supported-pair control under HEALTH001/003, not age degradation.

    Preserve both original positives and the two-hour held-room checkpoint.
    Warning qualification is retained in the separately named unsupported inverse.
    """
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    engine = ZoneModelEngine(target_map(), 1, now)
    engine.observe(SensorInput("binary_sensor.hall", "on", now))
    engine.observe(SensorInput("binary_sensor.room", "on", now + timedelta(seconds=2)))

    result = engine.advance(now + timedelta(hours=2))

    episodes = {state.node_id: state for state in result.snapshot.episode_states}
    policies = {state.zone: state for state in result.snapshot.policy_states}
    assert not episodes["hall"].health_warning
    assert not episodes["room"].health_warning
    assert result.snapshot.reliability_warning_occurrences == ()
    assert policies["room"].active


def test_unsupported_transition_warns_at_600_without_occupancy_degradation() -> None:
    """HEALTH001/003 inverse: omit only the synthetic room supporting positive."""
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    engine = ZoneModelEngine(target_map(), 1, now)
    engine.observe(SensorInput("binary_sensor.hall", "on", now))
    before = engine.advance(now + timedelta(seconds=599))
    assert before.snapshot.reliability_warning_occurrences == ()

    for seconds in (600, 610):
        result = engine.advance(now + timedelta(seconds=seconds))
        warning, = result.snapshot.reliability_warning_occurrences
        assert (warning.node_id, warning.kind, warning.reason) == (
            "hall", "suspected_stuck", "assertion_timeout",
        )
        assert warning.first_observed_at == now + timedelta(seconds=600)
        assert warning.cleared_at is None
        hall = next(s for s in result.snapshot.episode_states if s.node_id == "hall")
        assert hall.status == "asserted"
        assert not hall.health_warning
        assert all(not state.active for state in result.snapshot.policy_states)
        assert result.policy_events == ()

    recovered = engine.observe(
        SensorInput("binary_sensor.hall", "off", now + timedelta(seconds=611))
    )
    warning, = recovered.snapshot.reliability_warning_occurrences
    assert warning.cleared_at == now + timedelta(seconds=611)
    assert recovered.policy_events == ()
