"""Synthetic public requirements for selected paths, not new incident captures."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 12, tzinfo=UTC) + timedelta(seconds=seconds)


def graph() -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        name: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"mmwave": f"binary_sensor.{name}"},
            "adjacent": neighbors, "initial_weight": 1.0,
        }
        for name, neighbors in (("a", ["b"]), ("b", ["a", "c"]), ("c", ["b"]))
    }})


@pytest.mark.parametrize("count", (1, 2))
def test_selected_path_late_pair(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(180))
        assert replay.edges_for("b") == (ActiveEdge(at(180), "b", True),)
        assert not replay.view().active("a")


@pytest.mark.parametrize("count", (1, 2))
def test_selected_path_endpoint_retention(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(2))
        replay.send("binary_sensor.b", "off", at(3))
        replay.advance(at(7200))
        assert replay.edges_for("b") == (ActiveEdge(at(2), "b", True),)


@pytest.mark.parametrize("count", (1, 2))
def test_path_health_unsupported_on_boundary(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        replay.send("binary_sensor.a", "on", at(0))
        for seconds, expected in ((599, False), (600, True), (601, True)):
            replay.advance(at(seconds))
            warnings = (
                replay.runtime.confidence.diagnostics.reliability_warning_occurrences
            )
            assert any(
                item.node_id == "a" and item.cleared_at is None
                for item in warnings
            ) is expected
        assert not replay.edges
