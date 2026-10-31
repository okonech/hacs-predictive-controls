"""User-reported issue: "when guests or cleaners are here the system gets confused
and lights go on and off"; user approved option 2a as a release toggle.
User expected: local motion turns lights on, held until Visitors is disabled.
Observed: reported cycling; original event times, count and trace unavailable.
Source: 2026-10-30 conversation; receipt minute 2026-10-31 00:00 UTC from host
clock (2026-10-30 20:00 EDT). No production sequence is reconstructed here.
Test scope: synthetic feature acceptance through real runtime/public active edges,
not physical lights or a diagnosis of the original normal-mode cycling.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.runtime_replay import RuntimeScenario
from tests.test_runtime import make_map

pytestmark = pytest.mark.scenario
ORIGIN = datetime(2026, 10, 31, tzinfo=UTC)


def test_inc_2026_10_31_0000z_visitors_motion_hold() -> None:
    with RuntimeScenario(ORIGIN) as scenario:
        visitors = scenario.create(make_map(), 2)
        normal = scenario.create(make_map(), 2)
        asyncio.run(visitors.runtime.async_set_visitors_mode(True))

        for replay in (visitors, normal):
            replay.send("binary_sensor.office", "on", ORIGIN)
        assert visitors.latest["office"] is True
        assert normal.latest["office"] is False
        assert visitors.latest["kitchen"] is False
        assert visitors.attributes["office"]["reason"] == "visitors_hold"

        for replay in (visitors, normal):
            replay.send("binary_sensor.office", "off", ORIGIN + timedelta(seconds=1))
        visitors.advance(ORIGIN + timedelta(minutes=2))
        assert visitors.latest["office"] is True
        assert visitors.inference_snapshot() == normal.inference_snapshot()

        asyncio.run(visitors.runtime.async_set_visitors_mode(False))
        visitors.advance(ORIGIN + timedelta(seconds=149, microseconds=999999))
        assert visitors.latest["office"] is True
        visitors.advance(ORIGIN + timedelta(seconds=150))
        assert visitors.latest["office"] is False
        assert [(edge.at, edge.active) for edge in visitors.edges_for("office")] == [
            (ORIGIN, True),
            (ORIGIN + timedelta(seconds=150), False),
        ]
