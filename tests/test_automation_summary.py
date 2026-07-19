from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from tests.test_confidence import event
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_automation_summary_is_derived_from_target_belief_and_policy() -> None:
    predictive_map = target_map()
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    confidence.observe(event("hall", "hall", "on", NOW))
    confidence.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))
    runtime = SimpleNamespace(
        confidence=confidence,
        map=predictive_map,
        expected_occupants=1,
    )

    summary = runtime_automation_summary(runtime)

    assert summary.expected_inside_count == 1
    assert summary.keep_on_zones == ("room",)
    assert summary.activation_plausible_zones == ("room",)
    assert summary.zones["room"].confidence >= 0.7
    assert summary.zones["room"].keep_on is True
    assert "Probably occupied" in summary.explanation


def test_automation_summary_keeps_prediction_downstream_only() -> None:
    predictive_map = target_map()
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    runtime = SimpleNamespace(
        confidence=confidence,
        map=predictive_map,
        expected_occupants=1,
    )

    summary = runtime_automation_summary(runtime)

    assert summary.keep_on_zones == ()
    assert summary.prelight_plausible_zones == ()
    assert summary.diagnostic_predicted_next_zone is None


def test_automation_summary_avoids_audit_and_caches_per_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = target_map()
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    confidence.observe(event("hall", "hall", "on", NOW))
    confidence.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))
    runtime = SimpleNamespace(
        confidence=confidence,
        map=predictive_map,
        expected_occupants=1,
        _automation_summary_cache={},
    )

    def fail_audit_materialization(_engine: ZoneModelEngine) -> tuple[object, ...]:
        raise AssertionError("entity summary materialized retained policy audit")

    monkeypatch.setattr(
        ZoneModelEngine,
        "audit_rows",
        property(fail_audit_materialization),
    )

    first = runtime_automation_summary(runtime)
    second = runtime_automation_summary(runtime)

    assert second is first
    assert first.keep_on_zones == ("room",)
