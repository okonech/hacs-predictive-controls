"""Retain the separate 15:42 closet return followed by sleep-off report.

Provenance: approved HA captures in Homelab ignored tmp on 2026-09-10:
inc-2026-09-10-closet-{recent-history,status,diagnostics}.json and
inc-2026-09-10-sleep-trace.json, run 8defc734ffee946ce68f82ffd7505d63.
Count 2 is observed; count 1 is a synthetic inverse. Embedded generic topology
preserves the directly adjacent closet and bathroom physical presence nodes.

Production closet observations: 15:00:20 belief 0.05000007780798485 before full
positive; 15:28:22 full positive -> 0.9604627525663798 pending; 15:33:41
correlated -> 0.944709864291008 unauthorized. Bathroom at 15:39:57.952260 was
unsupported despite belief 0.8155935412751432. Closet return at 15:42:42.827832
was correlated, untracked_rejected, belief 0.9125177333896755, public active off.
At sleep-off 15:42:46.264052 the restoration automation consequently skipped
the closet light; its active guard read off at 15:42:46.309056.

Initial empty-baseline filters are fixture-only, not claimed exact production
snapshots. The measured positives/clears construct cadence rather than injecting
a correlated flag. Earlier expired circulation and unrelated history are omitted.
The full historical bathroom posterior and support snapshot are unavailable.
Public acquisition/retention, not manufactured posterior equality, is the oracle.
Sleep mode is an external consumer control, never occupancy evidence.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-10T{time}+00:00")


def _map() -> PredictiveMap:
    return PredictiveMap.from_mapping({
        "nodes": {
            "closet": {
                "role": "subzone_occupancy",
                "occupancy_behavior": "sustained",
                "entities": {"mmwave": "binary_sensor.closet"},
                "adjacent": ["bathroom"],
                "initial_weight": 0.8,
            },
            "bathroom": {
                "role": "room_occupancy",
                "occupancy_behavior": "sticky",
                "entities": {"mmwave": "binary_sensor.bathroom"},
                "adjacent": ["closet"],
                "initial_weight": 0.7,
            },
        },
    })


@pytest.mark.target_model
@pytest.mark.parametrize("count", (2, 1))
def test_inc_2026_09_10_1500z_closet_missed_before_sleep_off(count: int) -> None:
    observations = tuple(SensorInput(
        f"binary_sensor.{node}", state, _at(time),
        reliability=0.8 if node == "closet" else 0.7,
    ) for time, node, state in (
        ("15:00:20.634139", "closet", "on"),
        ("15:01:00.232817", "closet", "off"),
        ("15:28:22.804468", "closet", "on"),
        ("15:32:44.251033", "closet", "off"),
        ("15:33:41.366203", "closet", "on"),
        ("15:39:57.952260", "bathroom", "on"),
        ("15:40:33.617108", "closet", "off"),
    ))

    return_at = _at("15:42:42.827832")
    sleep_off_at = _at("15:42:46.264052")
    assert return_at - _at("15:39:57.952260") == timedelta(
        seconds=164, microseconds=875572,
    )
    assert return_at - _at("15:41:57.952260") == timedelta(
        seconds=44, microseconds=875572,
    )
    assert sleep_off_at - return_at == timedelta(seconds=3, microseconds=436220)
    # Original synthetic baseline; real runtime timers and active publications.
    with RuntimeScenario(_at("14:30:00")) as scenario:
        replay = scenario.create(_map(), count)
        for event in observations:
            replay.observe(event)
        assert not replay.view().active("closet")
        edge_start = len(replay.edges_for("closet"))
        final_event = SensorInput(
            "binary_sensor.closet", "on", return_at, reliability=0.8,
        )
        arrival = replay.observe(final_event)
        arrival_edges = replay.edges_for("closet")[edge_start:]
        sleep_off = replay.advance(sleep_off_at)
        assert replay.normalized_inputs == [*observations, final_event]
        assert (arrival.active("closet"), sleep_off.active("closet")) == (True, True), (
            "Closet must publish on at return and stay on through sleep-off",
            replay.edges_for("closet"), replay.attributes["closet"],
        )
        assert arrival_edges == (ActiveEdge(return_at, "closet", True),)
        assert replay.edges_for("closet")[edge_start:] == arrival_edges

