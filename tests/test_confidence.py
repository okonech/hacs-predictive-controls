from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def event(node: str, zone: str, state: str, at: datetime) -> OccupancyEvent:
    return OccupancyEvent(
        f"binary_sensor.{node}",
        node,
        zone,
        None,
        "transition_gate" if node == "hall" else "room_occupancy",
        "transient" if node == "hall" else "sustained",
        "motion",
        state,
        at,
        1.0,
    )


def test_confidence_facade_projects_target_belief_policy_and_diagnostics() -> None:
    confidence = ZoneConfidenceEngine(target_map(), 1)
    assert confidence.policy_events == ()

    confidence.observe(event("hall", "hall", "on", NOW))
    update = confidence.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))

    assert update.current.confidence >= 0.7
    assert update.current.status in {"probable", "confirmed"}
    assert confidence.states["room"].reason == "acquired"
    policy_events = confidence.policy_events
    assert policy_events
    assert policy_events[-1].zone == "room"
    assert confidence.diagnostics.policy_states["room"].active is True
    assert confidence.diagnostics.authorizations[-1].reason == "adjacent_current"


def test_confidence_facade_ignores_unsupported_count_and_round_trips_target_state() -> (
    None
):
    confidence = ZoneConfidenceEngine(target_map(), 1)
    confidence.observe(event("hall", "hall", "on", NOW))
    confidence.reject_unsupported_count(3, NOW + timedelta(seconds=1))

    assert confidence.config.expected_occupants == 1
    assert confidence.diagnostics.unsupported_count == 3

    payload = confidence.occupancy_store_data(NOW + timedelta(seconds=1))
    restored = ZoneConfidenceEngine(target_map(), 1)
    assert restored.restore_state(payload, NOW + timedelta(seconds=1))
    assert restored.config.expected_occupants == 1
    assert restored.diagnostics.beliefs["hall"] < confidence.diagnostics.beliefs["hall"]
    assert payload["schema"] == "zone-belief-v2"


def test_public_state_projection_does_not_materialize_retained_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confidence = ZoneConfidenceEngine(target_map(), 1)
    confidence.observe(event("hall", "hall", "on", NOW))

    def fail_audit_materialization(_engine: ZoneModelEngine) -> tuple[object, ...]:
        raise AssertionError("public state projection materialized retained audit")

    monkeypatch.setattr(
        ZoneModelEngine,
        "audit_rows",
        property(fail_audit_materialization),
    )
    update = confidence.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))

    assert update.current.active_since == NOW + timedelta(seconds=2)
    assert confidence.states["room"].reason == "acquired"
    assert confidence.beliefs["room"] >= 0.7
    assert confidence.policy_states["room"].active
