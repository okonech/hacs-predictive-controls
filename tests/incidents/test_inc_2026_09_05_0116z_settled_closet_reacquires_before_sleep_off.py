"""User-reported issue: closet missed before sleep-off; original wording unavailable.
User expected (approved amended acceptance): continuous ON through the detections.
Observed: retained fixture records historical OFF checkpoints and thirteen cycles.
Source: frozen original in /tmp/black-box-migration-baseline.json; Section 17
REQ-GOV-005's explicit 2026-09-11 continuous-ON amendment for this incident.
Test scope: both public control-signal branches stay ON, not physical actuation.
2026-09-12 boundary migration removes only supplementary snapshot/support/token
checks; all 31 inputs, thirteen cycles, count variants and restore frontier remain.
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
def test_inc_2026_09_05_0116z_settled_closet_reacquires_before_sleep_off(
    authoritative_count: int,
) -> None:
    """Retain the capture; approved 2026-09-11 contract has no timeout-only off."""

    top_at = _at("2026-09-05T01:16:30.919930Z")
    entrance_at = _at("2026-09-05T01:16:40.028350Z")
    closet_at = _at("2026-09-05T01:16:41.843671Z")
    closet_clear_at = _at("2026-09-05T01:20:19.951114Z")
    # Historical observed/modeled release times are checkpoints, not departures.
    historical_observed_release_at = _at("2026-09-05T02:11:17.196879Z")
    historical_model_release_at = _at("2026-09-05T02:11:41.735890Z")
    final_positive_at = _at("2026-09-05T04:36:47.492407Z")
    sleep_off_at = _at("2026-09-05T04:36:57.807707Z")
    cycles = (
        ("2026-09-05T02:33:34.245790Z", "2026-09-05T02:34:11.705370Z"),
        ("2026-09-05T02:43:06.437320Z", "2026-09-05T02:43:37.183604Z"),
        ("2026-09-05T02:47:02.099069Z", "2026-09-05T02:47:47.365877Z"),
        ("2026-09-05T02:49:28.480235Z", "2026-09-05T02:49:58.897750Z"),
        ("2026-09-05T03:16:16.123061Z", "2026-09-05T03:16:55.657163Z"),
        ("2026-09-05T03:38:25.313667Z", "2026-09-05T03:38:58.715883Z"),
        ("2026-09-05T03:39:36.020506Z", "2026-09-05T03:40:33.419418Z"),
        ("2026-09-05T03:41:37.560492Z", "2026-09-05T03:42:16.338295Z"),
        ("2026-09-05T04:24:46.940438Z", "2026-09-05T04:25:40.600856Z"),
        ("2026-09-05T04:26:52.802550Z", "2026-09-05T04:27:24.293763Z"),
        ("2026-09-05T04:27:45.326833Z", "2026-09-05T04:28:44.373954Z"),
        ("2026-09-05T04:32:10.853858Z", "2026-09-05T04:32:41.255209Z"),
        ("2026-09-05T04:33:41.992391Z", "2026-09-05T04:34:42.398511Z"),
    )
    predictive_map = PredictiveMap.from_mapping(
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
            }
        }
    )
    # Original unobserved baseline, not an invented production startup snapshot.
    # Keep SensorInput's original 1.0 observation weights independently of map
    # initial_weight; the harness labels this retained-input compatibility seam.
    with RuntimeScenario(top_at - timedelta(seconds=1)) as scenario:
        live = scenario.create(predictive_map, authoritative_count)
        restored = scenario.create(predictive_map, authoritative_count)
        expected_inputs = []
        public_states = []
        initial_edges: tuple[ActiveEdge, ...] = ()
        for event in (
            SensorInput("binary_sensor.top", "on", top_at),
            SensorInput("binary_sensor.entrance", "on", entrance_at),
            SensorInput("binary_sensor.closet", "on", closet_at),
            SensorInput("binary_sensor.closet", "off", closet_clear_at),
        ):
            expected_inputs.append(event)
            edge_start = len(live.edges)
            for replay in (live, restored):
                state = replay.observe(event)
                if event.event_at >= closet_at:
                    public_states.append(state)
            if event.event_at == closet_at:
                initial_edges = tuple(live.edges[edge_start:])

        # Checkpoints observe timers/publication only; no extra model advance.
        for checkpoint_at in (
            historical_observed_release_at, historical_model_release_at,
        ):
            live.advance(checkpoint_at)
            public_states.extend((live.view(), restored.view()))
        for asserted_at, cleared_at in cycles:
            for event in (
                SensorInput("binary_sensor.closet", "on", _at(asserted_at)),
                SensorInput("binary_sensor.closet", "off", _at(cleared_at)),
            ):
                expected_inputs.append(event)
                for replay in (live, restored):
                    public_states.append(replay.observe(event))

        # Strict inference restore at the same original frontier. Both branches
        # keep their original timer phase; this is not an HA process restart.
        prefix_lengths = (len(live.edges), len(restored.edges))
        restored.restore(restored.checkpoint())
        final_event = SensorInput("binary_sensor.closet", "on", final_positive_at)
        expected_inputs.append(final_event)
        final_positive = live.observe(final_event)
        restored_final_positive = restored.observe(final_event)
        live.advance(sleep_off_at)
        sleep_off = live.view()
        restored_sleep_off = restored.view()

        assert live.normalized_inputs == restored.normalized_inputs == expected_inputs
        assert initial_edges == (ActiveEdge(closet_at, "closet", True),)
        for replay in (live, restored):
            assert replay.input_edges_for("closet")[:1] == (
                ActiveEdge(closet_at, "closet", True),
            )
        assert final_positive.active("closet")
        assert sleep_off.active("closet")
        assert restored_final_positive.active("closet")
        assert restored_sleep_off.active("closet")
        public_states.extend((
            final_positive, sleep_off, restored_final_positive, restored_sleep_off,
        ))
        for state in public_states:
            assert state.active("closet"), (state.at, live.edges_for("closet"))
        # All published edges, including between checkpoints: no hidden off/on.
        for replay in (live, restored):
            assert replay.edges_for("closet") == (
                ActiveEdge(closet_at, "closet", True),
            )
        assert restored_final_positive == final_positive
        assert restored_sleep_off == sleep_off
        assert restored.edges_for("closet") == live.edges_for("closet")
        assert restored.edges[prefix_lengths[1]:] == live.edges[prefix_lengths[0]:]
        # Context teardown cancels both branches even when retention is still red.

