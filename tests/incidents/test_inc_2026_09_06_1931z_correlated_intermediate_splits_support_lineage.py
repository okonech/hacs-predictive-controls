"""User-reported issue: original quote unavailable; retained replay reconstruction.
User expected: valid office arrivals without a false Alex count-conflict warning
(inferred from retained assertions and approved public-boundary migration).
Observed: the old replay describes split support lineage and a later Alex warning;
it is not independent evidence of physical light actuation.
Source: frozen September 6 incident source; original report/capture unavailable here.
Test scope: Shaila/Alex public input-phase ON and sampled Reliability rows.
Legacy disposition: support/token/path/prediction prerequisites are replaced by
public outcomes; no private seed was present. All synthetic setup inputs remain.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "fixture_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_entry"},
                    "adjacent": ["fixture_bridge"],
                },
                "fixture_bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_bridge"},
                    "adjacent": [
                        "fixture_entry",
                        "master_bathroom_light_motion",
                    ],
                },
                "fixture_lower_route": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_lower_route"},
                    "adjacent": ["top_of_staircase_motion"],
                },
                "master_bathroom_light_motion": {
                    "zone": "master_bathroom",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.master_bathroom"},
                    "adjacent": [
                        "fixture_bridge",
                        "master_bedroom_closet",
                    ],
                    "initial_weight": 0.7,
                },
                "master_bedroom_closet": {
                    "role": "subzone_occupancy",
                    "entities": {"mmwave": "binary_sensor.master_bedroom_closet"},
                    "adjacent": [
                        "master_bathroom_light_motion",
                        "master_bedroom_entrance",
                    ],
                    "initial_weight": 0.8,
                },
                "master_bedroom_entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.master_bedroom_entrance"},
                    "adjacent": [
                        "master_bedroom_closet",
                        "top_of_staircase_motion",
                    ],
                    "initial_weight": 0.8,
                },
                "top_of_staircase_motion": {
                    "zone": "upstairs_hallway",
                    "role": "transition_gate",
                    "entities": {"mmwave": "binary_sensor.top_of_staircase"},
                    "adjacent": [
                        "fixture_lower_route",
                        "master_bedroom_entrance",
                        "shaila_office_fan_light",
                        "alex_office_motion",
                    ],
                    "initial_weight": 0.85,
                },
                "shaila_office_fan_light": {
                    "zone": "shaila_office",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.shaila_office"},
                    "adjacent": ["top_of_staircase_motion"],
                    "initial_weight": 0.75,
                },
                "alex_office_motion": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.alex_office"},
                    "adjacent": ["top_of_staircase_motion"],
                    "initial_weight": 0.75,
                },
            }
        }
    )


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_09_06_1931z_correlated_intermediate_splits_support_lineage(
) -> None:
    started_at = datetime(2026, 9, 6, 19, 22, 39, tzinfo=UTC)
    shaila_at = datetime.fromisoformat("2026-09-06T19:33:07.660283+00:00")
    shaila_clear_at = datetime.fromisoformat("2026-09-06T19:33:43.664305+00:00")
    alex_at = datetime.fromisoformat("2026-09-06T23:21:13.297739+00:00")
    degraded_at = datetime.fromisoformat("2026-09-06T23:23:16.265017+00:00")
    inputs = [
        # Historical SensorInput default was 1.0, NOT each node's map weight.
        SensorInput(f"binary_sensor.{node}", state, datetime.fromisoformat(at))
        for node, state, at in (
            # Fixture-only closet cadence and bathroom-support provenance.
            ("master_bedroom_closet", "on", "2026-09-06T19:22:40Z"),
            ("master_bedroom_closet", "off", "2026-09-06T19:22:54.617693+00:00"),
            ("fixture_entry", "on", "2026-09-06T19:31:56Z"),
            ("fixture_bridge", "on", "2026-09-06T19:31:57Z"),
            ("master_bathroom", "on", "2026-09-06T19:31:58.382096+00:00"),
            ("master_bedroom_closet", "off", "2026-09-06T19:32:26.372683+00:00"),
            ("master_bedroom_closet", "on", "2026-09-06T19:32:54.617692+00:00"),
            ("master_bedroom_entrance", "on", "2026-09-06T19:33:00.366187+00:00"),
            ("top_of_staircase", "on", "2026-09-06T19:33:00.967080+00:00"),
            ("shaila_office", "on", "2026-09-06T19:33:07.660283+00:00"),
            ("master_bathroom", "off", "2026-09-06T19:33:25.596498+00:00"),
            ("master_bedroom_closet", "off", "2026-09-06T19:33:34.928445+00:00"),
            ("shaila_office", "off", "2026-09-06T19:33:43.664305+00:00"),
            # Fixture-only clear/lower route; do not invent earlier route inputs.
            ("top_of_staircase", "off", "2026-09-06T19:33:44+00:00"),
            ("fixture_lower_route", "on", "2026-09-06T23:21:07+00:00"),
            ("top_of_staircase", "on", "2026-09-06T23:21:08.125213+00:00"),
            ("alex_office", "on", "2026-09-06T23:21:13.297739+00:00"),
        )
    ]
    with RuntimeScenario(started_at) as scenario:
        replay = scenario.create(incident_map(), 2).watch_reliability()
        views = {event.event_at: replay.observe(event) for event in inputs}
        after_alex = replay.advance(alex_at + timedelta(microseconds=1))
        final = replay.advance(degraded_at)

        assert replay.normalized_inputs == inputs
        assert views[shaila_at].active("shaila_office")
        shaila_edge = (ActiveEdge(shaila_at, "shaila_office", True),)
        assert replay.input_edges_for("shaila_office")[:1] == shaila_edge
        assert tuple(
            edge for edge in replay.edges_for("shaila_office")
            if edge.at <= shaila_clear_at
        ) == shaila_edge
        assert views[alex_at].active("alex_office")
        alex_edge = (ActiveEdge(alex_at, "alex_office", True),)
        assert replay.input_edges_for("alex_office") == alex_edge
        assert replay.edges_for("alex_office") == alex_edge
        assert after_alex.active("alex_office") and final.active("alex_office")

        # Actual 30s Reliability publications only, never a forced final refresh.
        attributes = replay.reliability_attributes
        assert attributes is not None  # Never-published is not published-empty.
        assert replay.reliability_writes[-1].at == (
            started_at + (degraded_at - started_at) // timedelta(seconds=30)
            * timedelta(seconds=30)
        )
        warnings = cast(list[dict[str, object]], attributes["warnings"])
        assert not any(
            row["node_id"] == "alex_office_motion"
            and row["active"]
            and "count_conflict" in cast(list[str], row["active_reasons"])
            for row in warnings
        )
