"""User-reported issue: original wording unavailable in the retained source.
User expected: upstairs bathroom releases after exit (fixture reconstruction).
Observed: retained regression covers a bathroom return/press followed by hall and
office detections, with a bathroom that must be OFF by 07:11:04.674406Z.
Source: frozen original in /tmp/black-box-migration-baseline.json.
Test scope: public acquisition and one release, independently in live and both
before/after-outward restore branches. Same-zone generation, token-use and context
assertions are removed by the 2026-09-12 black-box boundary migration.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


@pytest.mark.scenario
@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_0626z_upstairs_bathroom_same_zone_generation_releases(
    authoritative_count: int,
) -> None:
    hall_first_at = _at("2026-09-05T06:26:40.995428Z")
    bathroom_at = _at("2026-09-05T06:26:49.205190Z")
    hall_first_clear_at = _at("2026-09-05T06:26:53.208478Z")
    interaction_at = _at("2026-09-05T06:26:55.250000Z")
    bathroom_first_clear_at = _at("2026-09-05T06:27:22.803942Z")
    bathroom_return_at = _at("2026-09-05T06:27:44.895862Z")
    hall_return_at = _at("2026-09-05T06:28:15.338213Z")
    office_at = _at("2026-09-05T06:28:20.373595Z")
    bathroom_final_clear_at = _at("2026-09-05T06:28:36.102232Z")
    stable_clear_at = bathroom_final_clear_at + timedelta(seconds=10)
    observed_at = _at("2026-09-05T07:11:04.674406Z")
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": [
                        "bathroom_presence",
                        "bathroom_interaction",
                        "office",
                    ],
                    "initial_weight": 0.85,
                },
                "bathroom_presence": {
                    "zone": "bathroom",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.bathroom"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.7,
                },
                "bathroom_interaction": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"interaction_scene_002": "event.bathroom_scene"},
                    "adjacent": ["hall"],
                    "initial_weight": 1.0,
                },
                "office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.office"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.75,
                },
            }
        }
    )
    prefix_inputs = (
        SensorInput("binary_sensor.hall", "on", hall_first_at),
        SensorInput("binary_sensor.bathroom", "on", bathroom_at),
        SensorInput("binary_sensor.hall", "off", hall_first_clear_at),
        SensorInput("event.bathroom_scene", "pressed", interaction_at),
        SensorInput("binary_sensor.bathroom", "off", bathroom_first_clear_at),
        SensorInput("binary_sensor.bathroom", "on", bathroom_return_at),
    )
    departure = SensorInput("binary_sensor.hall", "on", hall_return_at)
    suffix_inputs = (
        SensorInput("binary_sensor.office", "on", office_at),
        SensorInput("binary_sensor.bathroom", "off", bathroom_final_clear_at),
    )
    expected_inputs = (*prefix_inputs, departure, *suffix_inputs)
    # Original SensorInput reliability 1.0 is independent of map initial weights.
    with RuntimeScenario(hall_first_at - timedelta(seconds=1)) as scenario:
        live = scenario.create(predictive_map, authoritative_count)
        before_outward = scenario.create(predictive_map, authoritative_count)
        after_outward = scenario.create(predictive_map, authoritative_count)
        branches = (live, before_outward, after_outward)
        states = {replay: [replay.view()] for replay in branches}
        for event in prefix_inputs:
            for replay in branches:
                states[replay].append(replay.observe(event))

        before_lengths = {replay: len(replay.edges) for replay in branches}
        before_outward.restore(live.checkpoint())  # 06:27:44.895862Z exactly.
        for replay in branches:
            states[replay].append(replay.observe(departure))
        after_lengths = {replay: len(replay.edges) for replay in branches}
        after_outward.restore(live.checkpoint())  # 06:28:15.338213Z exactly.

        # Merge by time, not by branch: neither fork misses an earlier input
        # while another branch's suffix advances the shared clock.
        for event in suffix_inputs:
            for replay in branches:
                states[replay].append(replay.observe(event))
        for checkpoint_at in (stable_clear_at, observed_at):
            live.advance(checkpoint_at)
            for replay in branches:
                states[replay].append(replay.view())

        for replay in branches:
            assert replay.normalized_inputs == list(expected_inputs)
            assert states[replay][2].active("bathroom")
            assert replay.input_edges_for("bathroom")[:1] == (
                ActiveEdge(bathroom_at, "bathroom", True),
            )
            assert not states[replay][-1].active("bathroom")
            edges = replay.edges_for("bathroom")
            assert len(edges) == 2, edges
            assert edges[0] == ActiveEdge(bathroom_at, "bathroom", True)
            assert not edges[1].active and edges[1].at <= observed_at
        assert states[before_outward] == states[live] == states[after_outward]
        assert before_outward.edges[before_lengths[before_outward]:] == (
            live.edges[before_lengths[live]:]
        )
        assert after_outward.edges[after_lengths[after_outward]:] == (
            live.edges[after_lengths[live]:]
        )
