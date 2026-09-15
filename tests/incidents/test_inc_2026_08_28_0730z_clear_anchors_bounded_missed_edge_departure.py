"""User-reported issue: original wording unavailable in the retained source.
User expected: source lighting releases after departure (fixture reconstruction).
Observed: retained kitchen-to-foyer missed-edge regression protects a stuck source.
Source: frozen original in /tmp/black-box-migration-baseline.json; Section 16(25).
Test scope: public source acquisition and one OFF by the original checkpoint, not
physical actuation. Token/authorization/decay-context prerequisites are removed
under the 2026-09-12 boundary migration; recorded inputs and deadlines are intact.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


@pytest.mark.scenario
@pytest.mark.target_model
def test_inc_2026_08_28_0730z_clear_anchors_bounded_missed_edge_departure() -> None:
    bridge_at = datetime(2026, 8, 28, 7, 30, 59, 556832, tzinfo=UTC)
    source_at = datetime(2026, 8, 28, 7, 31, 2, 613621, tzinfo=UTC)
    source_clear_at = datetime(2026, 8, 28, 7, 32, 8, 624443, tzinfo=UTC)
    destination_at = datetime(2026, 8, 28, 7, 32, 16, 417206, tzinfo=UTC)
    observed_at = datetime(2026, 8, 28, 7, 51, 5, 472961, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bridge"},
                    "adjacent": ["source", "destination"],
                    "transition_seconds": {"source": 15, "destination": 15},
                },
                "source": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.source"},
                    "adjacent": ["bridge"],
                    "transition_seconds": {"bridge": 15},
                },
                "destination": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.destination"},
                    "adjacent": ["bridge"],
                    "transition_seconds": {"bridge": 15},
                },
            }
        }
    )
    expected_inputs = (
        SensorInput("binary_sensor.bridge", "on", bridge_at),
        SensorInput("binary_sensor.source", "on", source_at),
        SensorInput("binary_sensor.source", "off", source_clear_at),
        SensorInput("binary_sensor.destination", "on", destination_at),
    )
    with RuntimeScenario(bridge_at - timedelta(seconds=1)) as scenario:
        replay = scenario.create(predictive_map, 2)
        states = [replay.observe(event) for event in expected_inputs]
        # Destination 07:32:16.417206 precedes this 07:32:18.624443 checkpoint.
        replay.advance(source_clear_at + timedelta(seconds=10))
        final = replay.advance(observed_at)

        assert replay.normalized_inputs == list(expected_inputs)
        assert states[1].active("source")
        assert replay.input_edges_for("source")[:1] == (
            ActiveEdge(source_at, "source", True),
        )
        assert not final.active("source")
        edges = replay.edges_for("source")
        assert len(edges) == 2, edges
        assert edges[0] == ActiveEdge(source_at, "source", True)
        # Full captured history, not a forced callback at the old advance time.
        assert not edges[1].active and edges[1].at <= observed_at
