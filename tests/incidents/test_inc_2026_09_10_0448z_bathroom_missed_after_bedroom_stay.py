"""Retain the 0448Z route preceding the 05:03 bathroom missed acquisition.

Provenance: approved HA history/status/diagnostics/trace captures, 2026-09-10,
Homelab ignored tmp/inc-2026-09-10-{history,route-history,status,trace}.json.
Production count was 2; count 1 is an inverse, not another observed incident.
Generic foyer/bottom/top/entrance/bedroom/bathroom names preserve the mapped
physical adjacency, roles, reliability, material timestamps and ordering.

The baseline is explicitly fixture-only: complete historical filter/support
snapshots were not retained. Production bathroom belief at detection was
0.050688018106151735 -> 0.5720114122771038, track_bootstrap_pending, active off.
The observed physical press at 05:03:19.774000Z caused the later active edge
05:03:19.776202Z and light-on 05:03:19.779768Z (sleep remained off). It must not
satisfy this regression's acquisition BEFORE that press. Trace run ID:
c5e49d3c63a4238f792667cbe4fc3b57.

Unchanged reconstruction loses settled bedroom support at 04:49:36.062159
through off-path linked outward context. Historical support loss is reconstructed,
not directly observed; public rejection and its event inputs are retained facts.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput

WEIGHTS = {
    "foyer": 0.85,
    "bottom": 0.85,
    "top": 0.85,
    "entrance": 0.8,
    "bedroom": 0.8,
    "bathroom": 0.7,
}


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-10T{time}+00:00")


def _map() -> PredictiveMap:
    adjacent = {
        "foyer": ["bottom"],
        "bottom": ["foyer", "top"],
        "top": ["bottom", "entrance"],
        "entrance": ["top", "bedroom"],
        "bedroom": ["entrance", "bathroom"],
        "bathroom": ["bedroom"],
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": (
                    "subzone_occupancy" if node == "bedroom"
                    else "room_occupancy" if node == "bathroom"
                    else "transition_gate"
                ),
                "occupancy_behavior": (
                    "sustained" if node == "bedroom"
                    else "sticky" if node == "bathroom"
                    else "transient"
                ),
                "entities": {
                    "motion" if node in {"foyer", "entrance"} else "mmwave":
                    f"binary_sensor.{node}",
                },
                "adjacent": neighbors,
                "initial_weight": WEIGHTS[node],
            }
            for node, neighbors in adjacent.items()
        },
    })


@pytest.mark.target_model
@pytest.mark.parametrize("count", (2, 1))
def test_inc_2026_09_10_0448z_bathroom_missed_after_bedroom_stay(
    count: int,
) -> None:
    # Unobserved initialization is not a fabricated earlier occupancy route.
    engine = ZoneModelEngine(_map(), count, _at("04:48:00"))
    for time, node, state in (
        ("04:48:03.665448", "foyer", "on"),
        ("04:48:07.884542", "bottom", "on"),
        ("04:48:17.127033", "top", "on"),
        ("04:48:28.242172", "foyer", "off"),
        ("04:48:32.356610", "bottom", "off"),
        ("04:48:35.262957", "entrance", "on"),
        ("04:48:38.633464", "bedroom", "on"),
        ("04:48:42.767145", "top", "off"),
        ("04:48:47.721943", "top", "on"),
        ("04:49:00.081669", "top", "off"),
        ("04:49:01.069477", "entrance", "off"),
        ("04:49:26.062159", "bedroom", "off"),
        ("04:50:04.803929", "top", "on"),
        ("04:50:09.712860", "entrance", "on"),
        ("04:50:11.336643", "bedroom", "on"),
        ("04:50:18.138846", "top", "off"),
        ("04:50:25.216283", "entrance", "off"),
        ("04:52:35.811662", "bedroom", "off"),
        ("04:52:52.284775", "bedroom", "on"),
    ):
        engine.observe(SensorInput(
            f"binary_sensor.{node}", state, _at(time),
            reliability=WEIGHTS[node],
        ))

    target_at = _at("05:03:13.938160")
    press_at = _at("05:03:19.774000")
    assert press_at - target_at == timedelta(seconds=5, microseconds=835840)
    assert not next(
        policy for policy in engine.snapshot.policy_states
        if policy.zone == "bathroom"
    ).active
    arrival = engine.observe(SensorInput(
        "binary_sensor.bathroom", "on", target_at, reliability=0.7,
    ))
    policy = next(
        policy for policy in arrival.snapshot.policy_states
        if policy.zone == "bathroom"
    )
    assert policy.active, (
        "Bathroom must acquire at detected entry before the manual press",
        arrival.authorizations,
    )
    assert [
        (event.zone, event.kind, event.event_at)
        for event in arrival.policy_events if event.zone == "bathroom"
    ] == [("bathroom", "acquired", target_at)]
    before_press = engine.advance(press_at - timedelta(microseconds=1))
    assert next(
        policy for policy in before_press.snapshot.policy_states
        if policy.zone == "bathroom"
    ).active
