"""User-reported issue: original message unavailable; retained-test reconstruction.
User expected: a cleared source releases after a valid outward path.
Observed: the Aug28 source fixture records hall/source/destination edges and a
still-active release-check frontier at 07:51:05.472961Z; no actuator is simulated.
Source: /tmp/black-box-migration-baseline.json, Aug28 0725Z original source.
Test scope: original generic physical map, count 2, -1-second synthetic baseline,
six inputs and old clear/final checkpoints, all with effective reliability 1.0.
Public source ON must occur on the exact detection; capture exactly one OFF by
the original deadline, not necessarily during the old sparse advance callback.
Internal authorization/token/context assertions are retired, not prerequisites.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, InputDelivery, RuntimeScenario


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_08_28_0725z_valid_outward_path_releases_cleared_source() -> None:
    hall_first_at = datetime(2026, 8, 28, 7, 25, 49, 850011, tzinfo=UTC)
    source_at = datetime(2026, 8, 28, 7, 25, 56, 665640, tzinfo=UTC)
    hall_first_clear_at = datetime(2026, 8, 28, 7, 26, 0, 816503, tzinfo=UTC)
    hall_return_at = datetime(2026, 8, 28, 7, 26, 53, 550848, tzinfo=UTC)
    destination_at = datetime(2026, 8, 28, 7, 26, 58, 118373, tzinfo=UTC)
    source_clear_at = datetime(2026, 8, 28, 7, 27, 5, 936116, tzinfo=UTC)
    observed_at = datetime(2026, 8, 28, 7, 51, 5, 472961, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["source", "destination"],
                },
                "source": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.source"},
                    "adjacent": ["hall"],
                },
                "destination": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.destination"},
                    "adjacent": ["hall"],
                },
            }
        }
    )
    with RuntimeScenario(hall_first_at - timedelta(seconds=1)) as scenario:
        replay = scenario.create(predictive_map, 2)
        replay.observe(SensorInput("binary_sensor.hall", "on", hall_first_at))
        acquired = replay.observe(SensorInput("binary_sensor.source", "on", source_at))
        replay.observe(SensorInput("binary_sensor.hall", "off", hall_first_clear_at))
        replay.advance(hall_first_clear_at + timedelta(seconds=5))
        replay.observe(SensorInput("binary_sensor.hall", "on", hall_return_at))
        replay.observe(SensorInput("binary_sensor.destination", "on", destination_at))
        replay.observe(SensorInput("binary_sensor.source", "off", source_clear_at))
        replay.advance(source_clear_at + timedelta(seconds=10))
        final = replay.advance(observed_at)

        expected_inputs = tuple(SensorInput(
            entity, state, datetime.fromisoformat(at), reliability=1.0,
        ) for entity, state, at in (
            ("binary_sensor.hall", "on", "2026-08-28T07:25:49.850011+00:00"),
            ("binary_sensor.source", "on", "2026-08-28T07:25:56.665640+00:00"),
            ("binary_sensor.hall", "off", "2026-08-28T07:26:00.816503+00:00"),
            ("binary_sensor.hall", "on", "2026-08-28T07:26:53.550848+00:00"),
            ("binary_sensor.destination", "on", "2026-08-28T07:26:58.118373+00:00"),
            ("binary_sensor.source", "off", "2026-08-28T07:27:05.936116+00:00"),
        ))
        assert replay.deliveries == tuple(InputDelivery(
            event.entity_id, event.state, event.event_at, event.event_at,
            event.event_at, event, event, False, True,
        ) for event in expected_inputs)
        on_edge = ActiveEdge(source_at, "source", True)
        assert acquired.active("source")
        assert on_edge in replay.input_edges_for("source")
        edges = replay.edges_for("source")
        assert not final.active("source"), edges
        assert tuple(edge.active for edge in edges) == (True, False), edges
        assert edges[0] == on_edge
        assert source_at < edges[1].at <= observed_at
