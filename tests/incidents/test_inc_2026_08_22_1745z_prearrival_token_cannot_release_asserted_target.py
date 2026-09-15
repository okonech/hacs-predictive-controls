"""User-reported issue: original message unavailable; retained-test reconstruction.
User expected: the first asserted target stays ON when the second target arrives.
Observed: retained Aug22 source records a 17:54:58.884915Z false-release frontier;
it does not supply a complete physical-light trace or exact historical state.
Source: /tmp/black-box-migration-baseline.json, Aug22 1745Z original source.
Test scope: generic graph and +0.1/+0.2/+0.3-second independent path are synthetic
setup. Preserve both arrivals and all old checkpoints, including the +5-second
suffix. Effective SensorInput reliability is 1.0 even for the 0.75 map weight.
The old measured arrival q=0.7812030651163774 (tolerance 0.02) is provenance only;
support/token/q assertions are retired, not replaced with private prerequisites.
Public retained ON and second-target immediate ON remain binding, even when red.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, InputDelivery, RuntimeScenario


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_08_22_1745z_prearrival_token_cannot_release_asserted_target() -> None:
    bootstrap_at = datetime(2026, 8, 22, 17, 45, 13, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "independent_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.independent_entry"},
                    "adjacent": ["independent_transition"],
                },
                "independent_transition": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {
                        "motion": "binary_sensor.independent_transition"
                    },
                    "adjacent": ["independent_entry", "independent_stay"],
                },
                "independent_stay": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.independent_stay"},
                    "adjacent": ["independent_transition"],
                },
                "route_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.route_entry"},
                    "adjacent": ["shared_transition"],
                },
                "shared_transition": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.shared_transition"},
                    "adjacent": [
                        "route_entry",
                        "retained_target",
                        "second_target",
                    ],
                },
                "retained_target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.retained_target"},
                    "adjacent": ["shared_transition"],
                    "initial_weight": 0.75,
                },
                "second_target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.second_target"},
                    "adjacent": ["shared_transition"],
                },
            }
        }
    )
    retained_at = datetime(2026, 8, 22, 17, 45, 22, 409954, tzinfo=UTC)
    second_at = datetime(2026, 8, 22, 17, 45, 24, 33458, tzinfo=UTC)
    conflict_at = datetime(2026, 8, 22, 17, 47, 28, 212891, tzinfo=UTC)
    release_at = datetime(2026, 8, 22, 17, 54, 58, 884915, tzinfo=UTC)
    with RuntimeScenario(bootstrap_at) as scenario:
        replay = scenario.create(predictive_map, 2)
        for node, at in (
            ("independent_entry", bootstrap_at + timedelta(microseconds=100000)),
            ("independent_transition", bootstrap_at + timedelta(microseconds=200000)),
            ("independent_stay", bootstrap_at + timedelta(microseconds=300000)),
            ("route_entry", datetime(2026, 8, 22, 17, 45, 15, 291907, tzinfo=UTC)),
            ("shared_transition", datetime(
                2026, 8, 22, 17, 45, 16, 259573, tzinfo=UTC,
            )),
        ):
            replay.observe(SensorInput(f"binary_sensor.{node}", "on", at))
        retained = replay.observe(
            SensorInput("binary_sensor.retained_target", "on", retained_at)
        )
        second = replay.observe(
            SensorInput("binary_sensor.second_target", "on", second_at)
        )
        checkpoints = [retained, second, replay.advance(conflict_at)]
        timer_at = conflict_at + timedelta(seconds=5)
        while timer_at < release_at:
            checkpoints.append(replay.advance(timer_at))
            timer_at += timedelta(seconds=5)
        checkpoints.append(replay.advance(release_at))
        checkpoints.append(replay.advance(release_at + timedelta(seconds=5)))

        expected_inputs = tuple(SensorInput(
            entity, "on", datetime.fromisoformat(at), reliability=1.0,
        ) for entity, at in (
            ("binary_sensor.independent_entry", "2026-08-22T17:45:13.100000+00:00"),
              ("binary_sensor.independent_transition",
               "2026-08-22T17:45:13.200000+00:00"),
            ("binary_sensor.independent_stay", "2026-08-22T17:45:13.300000+00:00"),
            ("binary_sensor.route_entry", "2026-08-22T17:45:15.291907+00:00"),
            ("binary_sensor.shared_transition", "2026-08-22T17:45:16.259573+00:00"),
            ("binary_sensor.retained_target", "2026-08-22T17:45:22.409954+00:00"),
            ("binary_sensor.second_target", "2026-08-22T17:45:24.033458+00:00"),
        ))
        assert replay.deliveries == tuple(InputDelivery(
            event.entity_id, event.state, event.event_at, event.event_at,
            event.event_at, event, event, False, True,
        ) for event in expected_inputs)
        assert second.active("second_target")
        assert replay.input_edges_for("second_target") == (
            ActiveEdge(second_at, "second_target", True),
        )
        assert replay.input_edges_for("retained_target") == (
            ActiveEdge(retained_at, "retained_target", True),
        )
        assert all(view.active("retained_target") for view in checkpoints), (
            "Retained target must remain ON at every original checkpoint",
            tuple((edge.at.isoformat(), edge.active)
                  for edge in replay.edges_for("retained_target")),
        )
        assert replay.edges_for("retained_target") == (
            ActiveEdge(retained_at, "retained_target", True),
        )
