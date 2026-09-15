"""User-reported issue: original quote unavailable; retained capture reconstruction.
User expected: bathroom activation on entry, before manual recovery (inferred).
Observed: bathroom detection did not activate the control signal until the press.
Source: September 10 approved captures listed below; original message unavailable.
Test scope: public active input edge and retention, not physical light actuation.
Legacy disposition: the entire seeded case remains in
tests/test_legacy_incident_2055_seeded.py; relocation is not a fix.

Approved captures: Homelab tmp/inc-2026-09-10-upstairs-{status,history,trace}.json.
Count 2 is observed; count 1 is synthetic. Generic hall--entrance--closet and
hall--bathroom preserve the material graph, profiles, reliability and ordering.
Office's clear is noncausal; its raw-on startup level is fixture-only, not an
invented earlier acquisition. The captured marginal is commentary, not an input;
this seedless replay is explicitly non-equivalent to the old latent-state fixture.

Observed bathroom ordinary positive at 20:55:51.806096Z raised belief from
0.22530608076879483 to 0.8792240073516933 but stayed unauthorized/pending.
Recovery press 20:55:56.215000Z produced HA active at 56.218314 and light-on
56.305799. Consumer control_upstairs_bathroom_light_by_motion correctly ran
trace 49b9b06141695ee14dc6d498a8ecbacc. The press must not satisfy this replay.
REQ-TRAV-020 preserves only original historical adjacency, never episode
validity, renewed authority, source refresh or evidence from the flap.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario

WEIGHTS = {"hall": 0.85, "entrance": 0.8, "closet": 0.8,
           "bathroom": 0.7, "office": 0.75}


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-10T{time}+00:00")


def _map() -> PredictiveMap:
    adjacency = {
        "hall": ["entrance", "bathroom", "office"],
        "entrance": ["hall", "closet"],
        "closet": ["entrance"],
        "bathroom": ["hall"],
        "office": ["hall"],
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": (
                    "transition_gate" if node in {"hall", "entrance"}
                    else "subzone_occupancy" if node == "closet"
                    else "room_occupancy"
                ),
                "occupancy_behavior": (
                    "transient" if node in {"hall", "entrance"}
                    else "sustained" if node == "closet" else "sticky"
                ),
                "entities": {
                    "motion" if node == "entrance" else "mmwave":
                    f"binary_sensor.{node}",
                },
                "initial_weight": WEIGHTS[node],
                "adjacent": neighbors,
            }
            for node, neighbors in adjacency.items()
        },
    })


@pytest.mark.target_model
@pytest.mark.scenario
@pytest.mark.parametrize("count", (2, 1))
def test_inc_2026_09_10_2055z_upstairs_bathroom_missed_after_hallway_flap(
    count: int,
) -> None:
    predictive_map = _map()
    target_at = _at("20:55:51.806096")
    press_at = _at("20:55:56.215000")
    inputs = [
        SensorInput(f"binary_sensor.{node}", state, _at(time), WEIGHTS[node])
        for time, node, state in (
            ("20:55:32.824275", "hall", "on"),
            ("20:55:36.229620", "entrance", "on"),
            ("20:55:39.457535", "closet", "on"),
            ("20:55:43.087332", "hall", "off"),
            ("20:55:43.938962", "hall", "on"),
            ("20:55:49.607010", "office", "off"),
            ("20:55:51.806096", "bathroom", "on"),
        )
    ]
    with RuntimeScenario(_at("20:55:00")) as scenario:
        replay = scenario.create(predictive_map, count, initial_states={
            f"binary_sensor.{node}": "on" if node == "office" else "off"
            for node in WEIGHTS
        })
        for event in inputs[:-1]:
            replay.observe(event)
        # Measured q=0.22530608076879483 -> 0.8792240073516933 is not
        # injectable evidence. No earlier observations replace that scalar seam.
        before_target = replay.advance(target_at)
        arrival = replay.observe(inputs[-1])
        before_press = replay.advance(press_at - timedelta(microseconds=1))

        assert replay.normalized_inputs == inputs
        # Preserve the old flap's no-hall-policy-event safety as a public guard.
        assert not any(
            edge.at == _at("20:55:43.938962") for edge in replay.edges_for("hall")
        )
        assert not before_target.active("bathroom")
        assert arrival.active("bathroom"), (
            "Bathroom must acquire on detection, not the recovery press",
            replay.edges_for("bathroom"),
        )
        expected = (ActiveEdge(target_at, "bathroom", True),)
        assert replay.input_edges_for("bathroom") == expected
        # The entire history catches timer-phase false OFF or duplicate ON.
        assert replay.edges_for("bathroom") == expected
        assert before_press.active("bathroom")
