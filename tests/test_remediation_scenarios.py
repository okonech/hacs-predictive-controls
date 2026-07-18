from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def test_r03_restart_midway_through_departure_matches_uninterrupted() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))
    engine.advance(NOW + timedelta(minutes=5))
    payload = serialize_target_state(target_map(), engine)

    uninterrupted = engine.advance(NOW + timedelta(minutes=12))
    restored = restore_target_state(target_map(), payload, NOW + timedelta(minutes=12))

    assert restored.snapshot == uninterrupted.snapshot


def test_r05_ambiguous_source_authorization_learns_no_prediction_edge() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "left": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.left"},
                    "adjacent": ["target"],
                },
                "right": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.right"},
                    "adjacent": ["target"],
                },
                "target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.target"},
                    "adjacent": ["left", "right"],
                },
            }
        }
    )
    tracker = OccupancyTracker(predictive_map, TrackerConfig(2))
    from custom_components.predictive_controls.events import event_from_entity

    for entity, offset in (
        ("binary_sensor.left", 0),
        ("binary_sensor.right", 1),
        ("binary_sensor.target", 2),
    ):
        observed = event_from_entity(
            predictive_map, entity, "on", NOW + timedelta(seconds=offset)
        )
        assert observed is not None
        tracker.observe(observed)

    assert all(
        count == 0.0
        for targets in tracker.prediction_chain.counts.values()
        for count in targets.values()
    )


def test_r07_nonreciprocal_graph_declaration_is_rejected() -> None:
    with pytest.raises(ValueError, match="reciprocal"):
        PredictiveMap.from_mapping(
            {
                "nodes": {
                    "a": {"adjacent": ["b"]},
                    "b": {"adjacent": []},
                }
            }
        )


def test_r09_dynamic_count_three_is_ignored_and_reported() -> None:
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))

    tracker.reconcile_expected_occupants(3, NOW)

    assert tracker.config.expected_occupants == 1
    assert tracker.diagnostics.requested_occupants == 3
    assert tracker.diagnostics.unsupported_count == 3
