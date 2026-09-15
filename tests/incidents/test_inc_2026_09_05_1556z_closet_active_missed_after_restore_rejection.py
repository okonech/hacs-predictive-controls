"""User-reported issue: closet missed after restore rejection; wording unavailable.
User expected (approved amended acceptance): retained ON through sleep-off.
Observed: fixture reconstructs background unavailability before a later closet miss.
Source: frozen original in /tmp/black-box-migration-baseline.json; Section 17
REQ-GOV-005's 2026-09-11 amendment requires retained ON, not timeout/reacquisition.
Test scope: independent public continuous-ON live/restore branches, not actuation
or disk durability. Support/status/snapshot assertions are removed under the
2026-09-12 boundary migration. Save 07:53:47 and restore 07:54:05.919458 stay distinct.
"""

from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["top", "closet"],
                    "initial_weight": 0.8,
                },
                "closet": {
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.8,
                },
                "background": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.background"},
                    "adjacent": [],
                    "initial_weight": 0.8,
                },
            }
        }
    )


@pytest.mark.scenario
@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_1556z_closet_active_missed_after_restore_rejection(
    authoritative_count: int,
) -> None:
    predictive_map = _incident_map()
    initial_inputs = tuple(SensorInput(entity_id, state, _at(event_at)) for (
        entity_id, state, event_at
    ) in (
        ("binary_sensor.top", "on", "2026-09-05T01:16:30.919930Z"),
        ("binary_sensor.entrance", "on", "2026-09-05T01:16:40.028350Z"),
        ("binary_sensor.closet", "on", "2026-09-05T01:16:41.843671Z"),
        ("binary_sensor.closet", "off", "2026-09-05T01:20:19.951114Z"),
    ))
    background_inputs = tuple(SensorInput(
        "binary_sensor.background", state, _at(event_at),
    ) for state, event_at in (
        ("on", "2026-09-05T07:53:40Z"),
        ("off", "2026-09-05T07:53:41Z"),
        ("unavailable", "2026-09-05T07:53:47Z"),
    ))
    incident_inputs = tuple(SensorInput(
        "binary_sensor.closet", state, _at(event_at),
    ) for state, event_at in (
        ("on", "2026-09-05T15:55:09.320493Z"),
        ("off", "2026-09-05T15:56:13.538504Z"),
        ("on", "2026-09-05T15:56:54.026176Z"),
    ))
    expected_inputs = (*initial_inputs, *background_inputs, *incident_inputs)
    closet_at = initial_inputs[2].event_at
    # Preserve the exact origin (not top_on minus one second), default unobserved
    # startup, map and historical SensorInput reliability 1.0 in both branches.
    with RuntimeScenario(_at("2026-09-05T01:16:29Z")) as scenario:
        live = scenario.create(predictive_map, authoritative_count)
        restored = scenario.create(predictive_map, authoritative_count)
        branches = (live, restored)
        states = {replay: [replay.view()] for replay in branches}
        for event in initial_inputs:
            for replay in branches:
                states[replay].append(replay.observe(event))
        live.advance(_at("2026-09-05T02:11:41.735890Z"))
        for replay in branches:
            states[replay].append(replay.view())
        for event in background_inputs[:2]:
            for replay in branches:
                states[replay].append(replay.observe(event))
        live.advance(_at("2026-09-05T07:53:46Z"))
        for replay in branches:
            states[replay].append(replay.view())
        for replay in branches:
            states[replay].append(replay.observe(background_inputs[2]))

        # Capture exactly at 07:53:47, NOT at the later restore timestamp.
        payload = live.checkpoint()
        live.advance(_at("2026-09-05T07:54:05.919458Z"))
        prefix_lengths = {replay: len(replay.edges) for replay in branches}
        restored.restore(payload)
        for replay in branches:
            states[replay].append(replay.view())
        for event in incident_inputs:
            for replay in branches:
                states[replay].append(replay.observe(event))
        live.advance(_at("2026-09-05T15:57:28.615217Z"))
        for replay in branches:
            states[replay].append(replay.view())

        for replay in branches:
            assert replay.normalized_inputs == list(expected_inputs)
            assert replay.input_edges_for("closet")[:1] == (
                ActiveEdge(closet_at, "closet", True),
            )
            for state in states[replay][3:]:
                assert state.active("closet"), (state.at, replay.edges_for("closet"))
            assert replay.edges_for("closet") == (
                ActiveEdge(closet_at, "closet", True),
            )
            assert states[replay][-1].at == _at("2026-09-05T15:57:28.615217Z")
            assert states[replay][-1].at < _at("2026-09-05T15:57:50.057472Z")
        assert states[restored] == states[live]
        assert restored.edges[prefix_lengths[restored]:] == (
            live.edges[prefix_lengths[live]:]
        )
