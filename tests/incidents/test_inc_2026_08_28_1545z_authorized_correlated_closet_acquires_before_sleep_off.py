"""User-reported issue: closet missed before sleep-off; original wording unavailable.
User expected (fixture reconstruction): new ON at 15:48:00.349791Z, no OFF through
sleep-off; the original user wording is unavailable.
Observed: the retained seeded regression reconstructs a correlated closet miss.
Source: frozen original in /tmp/black-box-migration-baseline.json.
Test scope: same seven observations and public lighting deadline, no private seed.
The measured q=0.6424240878301262 is provenance, NOT an input; missing historical
latent state makes this seedless replay explicitly non-equivalent to that boundary.
The entire original is retained in tests/test_legacy_incident_aug28_seeded.py.
Token/support/refresh flags are not lighting acceptance: captured boolean edges
must show a new input-phase ON, never already-ON or a false OFF before sleep-off.
"""

from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario


def correlated_arrival_incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bottom"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.8,
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["bottom", "entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["hall", "closet"],
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


@pytest.mark.scenario
@pytest.mark.target_model
def test_inc_2026_08_28_1545z_authorized_correlated_closet_acquires_before_sleep_off(
) -> None:
    predictive_map = correlated_arrival_incident_map()
    expected_inputs = (
        SensorInput(
            "binary_sensor.closet",
            "on",
            datetime(2026, 8, 28, 15, 45, 6, 906293, tzinfo=UTC),
            0.8,
        ),
        SensorInput(
            "binary_sensor.closet",
            "off",
            datetime(2026, 8, 28, 15, 46, 48, 88053, tzinfo=UTC),
            0.8,
        ),
        SensorInput(
            "binary_sensor.bottom",
            "on",
            datetime(2026, 8, 28, 15, 47, 34, 3613, tzinfo=UTC),
            0.8,
        ),
        SensorInput(
            "binary_sensor.hall",
            "on",
            datetime(2026, 8, 28, 15, 47, 37, 229584, tzinfo=UTC),
            0.85,
        ),
        SensorInput(
            "binary_sensor.entrance",
            "on",
            datetime(2026, 8, 28, 15, 47, 56, 450011, tzinfo=UTC),
            0.8,
        ),
        SensorInput(
            "binary_sensor.closet",
            "on",
            datetime(2026, 8, 28, 15, 48, 0, 349791, tzinfo=UTC),
            0.8,
        ),
        SensorInput(
            "binary_sensor.closet",
            "off",
            datetime(2026, 8, 28, 15, 48, 51, 681142, tzinfo=UTC),
            0.8,
        ),
    )
    target_at = expected_inputs[5].event_at
    with RuntimeScenario(
        datetime(2026, 8, 28, 15, 45, 6, 906293, tzinfo=UTC),
    ) as scenario:
        replay = scenario.create(predictive_map, 2)
        for event in expected_inputs[:2]:
            replay.observe(event)
        replay.advance(datetime(2026, 8, 28, 15, 46, 58, 88053, tzinfo=UTC))
        for event in expected_inputs[2:5]:
            replay.observe(event)
        # Retain the old seed helper's time frontier, without injecting q.
        # Its post-local .676195601951254 and final .7838097800975627
        # probabilities remain qualified ONLY by the unchanged legacy test.
        before_target = replay.advance(target_at)
        target = replay.observe(expected_inputs[5])
        cleared = replay.observe(expected_inputs[6])
        sleep_off = replay.advance(
            datetime(2026, 8, 28, 15, 49, 16, 794454, tzinfo=UTC),
        )

        assert replay.normalized_inputs == list(expected_inputs)
        assert not before_target.active("closet")
        assert target.active("closet")
        assert cleared.active("closet")
        assert sleep_off.active("closet")
        assert replay.input_edges_for("closet") == (
            ActiveEdge(target_at, "closet", True),
        )
        assert replay.edges_for("closet") == (ActiveEdge(target_at, "closet", True),)
