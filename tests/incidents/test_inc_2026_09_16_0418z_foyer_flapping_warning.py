"""User-reported issue: "The flapping warning is a bit overzealous. Maybe we
tighten the flapping to say 10 flaps in 20 minutes for the warning?"
User expected: explicitly approved ten completed short ON/OFF cycles in20minutes,
not six sparse cycles in an hour; no occupancy behavior change.
Observed: Foyer5%/inactive/flapping screenshot. Read-only status at
2026-09-16T05:40:32.801267Z retained six OFFs spanning48m16.944002s, warning
first05:32:26.113086Z, count2; only two completions in the latest20minutes.
Source: Sep16 screenshots; approved ha-history-context/ha-ws-readonly captures in
homelab/tmp/foyer-flapping-20260916/. History SHA256
5307463b23f65ba82003b8172e67a349a6a533c8b011dce845981f3d49b14ded; status SHA256
7d5cd76082a87090b57ce3b4ca35046b02f17f1890e2e4c2d919899952423b55.
Test scope: exact18 logbook transitions, first04:18:01.614430Z, with real sampled
Reliability publications. Map is the causal one-node slice (transition/0.85).
Uncaptured receipt ordering uses the harness convention; no reconstructed paths,
neighbors, posterior equality, or physical-light actuation is claimed.
"""

from datetime import datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import RuntimeScenario

HISTORY = (
    ("on", "2026-09-16T04:18:01.614430+00:00"),
    ("off", "2026-09-16T04:18:14.287885+00:00"),
    ("on", "2026-09-16T04:19:21.788043+00:00"),
    ("off", "2026-09-16T04:19:34.343858+00:00"),
    ("on", "2026-09-16T04:19:57.617915+00:00"),
    ("off", "2026-09-16T04:20:12.404391+00:00"),
    ("on", "2026-09-16T04:43:43.837749+00:00"),
    ("off", "2026-09-16T04:44:09.169084+00:00"),
    ("on", "2026-09-16T04:44:52.943614+00:00"),
    ("off", "2026-09-16T04:45:03.973533+00:00"),
    ("on", "2026-09-16T04:46:11.163932+00:00"),
    ("off", "2026-09-16T04:46:23.110889+00:00"),
    ("on", "2026-09-16T04:47:19.365309+00:00"),
    ("off", "2026-09-16T04:47:34.233190+00:00"),
    ("on", "2026-09-16T05:30:49.814723+00:00"),
    ("off", "2026-09-16T05:31:08.734111+00:00"),
    ("on", "2026-09-16T05:32:05.216964+00:00"),
    ("off", "2026-09-16T05:32:26.113086+00:00"),
)
ENTITY = "binary_sensor.foyer_pir_motion_motion_detection"


@pytest.mark.scenario
def test_inc_2026_09_16_0418z_foyer_flapping_warning() -> None:
    predictive_map = PredictiveMap.from_mapping({"nodes": {"foyer_pir_motion": {
        "zone": "foyer", "role": "transition_gate",
        "entities": {"motion": ENTITY}, "initial_weight": 0.85,
    }}})
    events = [SensorInput(ENTITY, state, datetime.fromisoformat(timestamp),
                          reliability=0.85) for state, timestamp in HISTORY]
    with RuntimeScenario(events[0].event_at) as scenario:
        replay = scenario.create(predictive_map, 2).watch_reliability()
        for event in events:
            replay.observe(event)
        replay.advance(datetime.fromisoformat("2026-09-16T05:40:32.801267+00:00"))
        assert replay.normalized_inputs == events
        assert replay.reliability_writes
        for publication in replay.reliability_writes:
            assert publication.value == 0, (
                publication.at, publication.attributes["warnings"],
            )
            assert publication.attributes["warnings"] == []
