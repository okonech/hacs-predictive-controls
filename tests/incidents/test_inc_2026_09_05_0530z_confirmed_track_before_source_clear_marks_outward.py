"""User-reported issue: original wording unavailable in the retained source.
User expected: bathroom lighting releases after departure (fixture reconstruction).
Observed: retained regression covers departure before bathroom presence clears.
Source: frozen original in /tmp/black-box-migration-baseline.json, exact 05:30Z
presence, physical press and closet/entrance/hallway sequence.
Test scope: public press acquisition and one OFF by the original deadline, with
opaque restore at source clear. Track, generation and decay-context checks are
removed under the 2026-09-12 boundary migration, not turned into light prerequisites.
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
def test_inc_2026_09_05_0530z_confirmed_track_before_source_clear_marks_outward(
    authoritative_count: int,
) -> None:
    source_on_at = _at("2026-09-05T05:30:12.426589Z")
    interaction_at = _at("2026-09-05T05:44:05.117000Z")
    closet_at = _at("2026-09-05T05:52:35.652266Z")
    entrance_at = _at("2026-09-05T05:52:40.023935Z")
    hallway_at = _at("2026-09-05T05:52:41.648837Z")
    source_clear_at = _at("2026-09-05T05:52:46.398577Z")
    stable_clear_at = source_clear_at + timedelta(seconds=10)
    observed_at = _at("2026-09-05T06:37:03.502170Z")
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bathroom_presence": {
                    "zone": "bathroom",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.bathroom_presence"},
                    "adjacent": ["closet"],
                },
                "bathroom_interaction": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_002": "event.bathroom_scene_002"
                    },
                    "adjacent": ["closet"],
                },
                "closet": {
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.closet"},
                    "adjacent": [
                        "bathroom_presence",
                        "bathroom_interaction",
                        "entrance",
                    ],
                },
                "entrance": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["closet", "hallway"],
                },
                "hallway": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hallway"},
                    "adjacent": ["entrance"],
                },
            }
        }
    )
    expected_inputs = (
        SensorInput("binary_sensor.bathroom_presence", "on", source_on_at),
        SensorInput("event.bathroom_scene_002", "pressed", interaction_at),
        SensorInput("binary_sensor.closet", "on", closet_at),
        SensorInput("binary_sensor.entrance", "on", entrance_at),
        SensorInput("binary_sensor.hallway", "on", hallway_at),
        SensorInput("binary_sensor.bathroom_presence", "off", source_clear_at),
    )
    # Both branches begin at the retained unobserved origin with reliability 1.0.
    # Mirroring inputs/publications is not copying model state or output feedback.
    with RuntimeScenario(source_on_at - timedelta(seconds=1)) as scenario:
        live = scenario.create(predictive_map, authoritative_count)
        restored = scenario.create(predictive_map, authoritative_count)
        branches = (live, restored)
        states = {replay: [replay.view()] for replay in branches}
        for event in expected_inputs:
            for replay in branches:
                states[replay].append(replay.observe(event))

        prefix_lengths = {replay: len(replay.edges) for replay in branches}
        restored.restore(live.checkpoint())  # Save/restore: source_clear_at exactly.
        for checkpoint_at in (stable_clear_at, observed_at):
            live.advance(checkpoint_at)
            for replay in branches:
                states[replay].append(replay.view())

        # Independently require each branch's public outcome before comparison.
        for replay in branches:
            assert replay.normalized_inputs == list(expected_inputs)
            assert states[replay][2].active("bathroom")
            assert replay.input_edges_for("bathroom")[:1] == (
                ActiveEdge(interaction_at, "bathroom", True),
            )
            assert not states[replay][-1].active("bathroom")
            edges = replay.edges_for("bathroom")
            assert len(edges) == 2, edges
            assert edges[0] == ActiveEdge(interaction_at, "bathroom", True)
            assert not edges[1].active and edges[1].at <= observed_at
        assert states[restored] == states[live]
        assert restored.edges[prefix_lengths[restored]:] == (
            live.edges[prefix_lengths[live]:]
        )
