"""User-reported issue: original quote unavailable; retained capture reconstruction.
User expected: living-room activation on entry before manual recovery (inferred).
Observed: both living-room active outputs stayed off at the right-radar detection.
Source: September 11 approved captures listed below; original message unavailable.
Test scope: the public active input edge and retention, not hardware actuation.
Legacy disposition: the entire seeded case remains in
tests/test_legacy_incident_0326_seeded.py; relocation is not a fix.

Approved Homelab captures: tmp/inc-2026-09-11-living-room-{status,history,
route-history,context,traces,trace,diagnostics}.json. The replay is self-contained;
it reads neither captures nor a live/sibling map. Count 2 is observed, 1 synthetic.
0326 is the first material cadence event, not a claimed occupant arrival time.

Generic names preserve entrance--dining--living-right, kitchen--entrance/dining,
foyer--dining, and guest--living-left. Four radar aliases are ONE physical lounge
node. The left radar stayed off. Map weights, profiles and the absence of directed
entry->passage->lounge timing are factual; empty startup is fixture-only.

03:42:19.506697 entrance acquires via kitchen-backed settled adjacent transfer.
03:42:32.109092 right radar is a trustworthy fresh correlated positive, but
untracked_rejected; observed q .14559229504345259 -> .16793252687103588 and both
living-room public active outputs remain off. The dining transition has been on
since03:39:48.881643: original45s token and60s health horizon expired. The fresh
entrance token is12.602395s old, but two edges away and provisional.

Manual recovery light-on03:43:37.707485 is unattributed in retained logbook,
consistent with the report, NOT a captured physical event pulse. Alex sleep off
and Shaila sleep on make the consumer's NOT(both asleep) guard permissive.
No active-on trace occurred at detection. Never feed the light state as evidence.
Expected acquisition requires a newly reviewed bounded contract; it must not
come from invented alias independence, expired passage authority or a timer.
The measured marginal remains commentary only: removing its scalar seed makes
this input-only replay explicitly non-equivalent to the old latent-state fixture.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-11T{time}+00:00")


def _map() -> PredictiveMap:
    adjacency = {
        "entry": ["passage", "stay"],
        "passage": ["entry", "stay", "foyer", "lounge"],
        "stay": ["entry", "passage"],
        "foyer": ["passage", "bottom"],
        "bottom": ["foyer", "guest"],
        "guest": ["bottom", "other_side"],
        "other_side": ["guest", "lounge"],
        "lounge": ["passage", "other_side"],
    }
    weights = {
        "entry": 0.75, "passage": 0.75, "stay": 0.8, "foyer": 0.85,
        "bottom": 0.85, "guest": 0.75, "other_side": 0.9, "lounge": 0.9,
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": (
                    "anchor_sensor" if node in {"lounge", "other_side"}
                    else "room_occupancy" if node in {"stay", "guest"}
                    else "transition_gate"
                ),
                "occupancy_behavior": (
                    "sticky" if node in {"lounge", "other_side"}
                    else "sustained" if node in {"stay", "guest"}
                    else "transient"
                ),
                "entities": (
                    {signal: f"binary_sensor.{node}_{alias}" for signal, alias in (
                        ("target", "target"), ("still_target", "still"),
                        ("moving_target", "moving"), ("zone_3_occupancy", "zone"),
                    )}
                    if node in {"lounge", "other_side"} else
                    {"motion" if node == "foyer" else "mmwave": f"binary_sensor.{node}"}
                ),
                "adjacent": neighbors,
                "initial_weight": weights[node],
                "transition_seconds": (
                    {"stay": 15, "foyer": 15} if node == "passage"
                    else {"passage": 15} if node in {"stay", "foyer"} else {}
                ),
            }
            for node, neighbors in adjacency.items()
        },
    })


EVENTS = (
    ("03:26:20.716997", "lounge_target", "on"),
    ("03:26:20.720525", "lounge_still", "on"),
    ("03:26:25.962230", "lounge_target", "off"),
    ("03:26:25.965546", "lounge_still", "off"),
    ("03:28:15.829137", "passage", "on"),
    ("03:28:25.704027", "passage", "off"),
    ("03:35:04.512882", "lounge_target", "on"),
    ("03:35:04.516210", "lounge_moving", "on"),
    ("03:35:05.513281", "lounge_moving", "off"),
    ("03:35:05.516724", "lounge_still", "on"),
    ("03:35:09.806851", "lounge_target", "off"),
    ("03:35:09.810259", "lounge_still", "off"),
    ("03:38:13.211815", "lounge_target", "on"),
    ("03:38:13.215339", "lounge_still", "on"),
    ("03:38:18.606532", "lounge_target", "off"),
    ("03:38:18.609795", "lounge_still", "off"),
    ("03:38:57.969102", "entry", "on"),
    ("03:39:03.659340", "guest", "on"),
    ("03:39:04.386957", "passage", "on"),
    ("03:39:05.070280", "stay", "on"),
    ("03:39:07.197953", "foyer", "on"),
    ("03:39:18.534318", "guest", "off"),
    ("03:39:18.955694", "foyer", "off"),
    ("03:39:28.474103", "foyer", "on"),
    ("03:39:39.994369", "foyer", "off"),
    ("03:39:43.224736", "passage", "off"),
    ("03:39:48.881643", "passage", "on"),
    ("03:40:11.172398", "foyer", "on"),
    ("03:40:22.047760", "entry", "off"),
    ("03:40:25.069714", "foyer", "off"),
    ("03:42:19.506697", "entry", "on"),
)


@pytest.mark.target_model
@pytest.mark.scenario
@pytest.mark.parametrize("count", (2, 1))
def test_inc_2026_09_11_0326z_living_room_missed_after_expired_passage(
    count: int,
) -> None:
    predictive_map = _map()
    entities = {
        entity: node
        for node in predictive_map.nodes.values() for entity in node.entities.values()
    }
    target_at = _at("03:42:32.109092")
    recovery_at = _at("03:43:37.707485")
    inputs = [
        SensorInput(
            f"binary_sensor.{alias}", state, _at(time),
            entities[f"binary_sensor.{alias}"].reliability,
        )
        for time, alias, state in EVENTS
    ]
    target = SensorInput("binary_sensor.lounge_target", "on", target_at, 0.9)
    aliases = [
        SensorInput(f"binary_sensor.lounge_{alias}", "on", _at(time), 0.9)
        for time, alias in (
            ("03:42:32.112873", "moving"), ("03:42:32.116631", "still"),
        )
    ]
    with RuntimeScenario(_at("03:26:00")) as scenario:
        replay = scenario.create(
            predictive_map, count, initial_states=dict.fromkeys(entities, "off"),
        )
        for event in inputs:
            replay.observe(event)
        # Captured q=0.14559229504345259 -> 0.16793252687103588 is not
        # a sensor input. The legacy qualification alone retains that seed.
        before_target = replay.advance(target_at)
        arrival = replay.observe(target)
        for event in aliases:
            replay.observe(event)
        before_recovery = replay.advance(recovery_at - timedelta(microseconds=1))

        assert replay.normalized_inputs == [*inputs, target, *aliases]
        assert not before_target.active("lounge")
        assert arrival.active("lounge"), (
            "Living room must acquire on detection, not 65.598393s later",
            replay.edges_for("lounge"),
        )
        expected = (ActiveEdge(target_at, "lounge", True),)
        assert replay.input_edges_for("lounge") == expected
        # Include every timer and same-device alias through the recovery frontier.
        assert replay.edges_for("lounge") == expected
        assert before_recovery.active("lounge")
