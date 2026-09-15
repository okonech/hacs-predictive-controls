"""User-reported issue: original message unavailable; retained-test reconstruction.
User expected: a physical press acquires bathroom ON; qualified departure releases.
Observed: the retained fixture anchors the press at 2026-08-22T07:28:36.046Z;
it supplies no complete production trace or original physical-light outcome.
Source: /tmp/black-box-migration-baseline.json, Aug22 0728Z original source.
Test scope: generic map and +1-minute outward input are synthetic qualification;
preserve both original independent branches and their -5-second baseline origins.
The 2026-09-11 approved no-outward amendment retains ON through +70 minutes, while
outward must release by +40 minutes. All inputs have effective reliability 1.0.
Private ceiling/context checks are retired; ISO press transport is normalized by
the real runtime. Public signals do not prove downstream physical actuation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, InputDelivery, RuntimeScenario


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_08_22_0728z_physical_press_acquires_then_decays_normally() -> None:
    press_at = datetime(2026, 8, 22, 7, 28, 36, 46000, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bathroom_interaction": {
                    "zone": "bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_002": "event.bathroom_scene_002"
                    },
                    "adjacent": ["closet"],
                },
                "closet": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["bathroom_interaction"],
                },
            }
        }
    )

    closet_at = press_at + timedelta(minutes=1)
    release_check_at = press_at + timedelta(minutes=40)
    # Independent contexts retain both origins without rewinding a shared clock.
    with RuntimeScenario(press_at - timedelta(seconds=5)) as scenario:
        with_outward = scenario.create(predictive_map, 1)
        acquired = with_outward.observe(
            SensorInput("event.bathroom_scene_002", "pressed", press_at)
        )
        with_outward.observe(SensorInput("binary_sensor.closet", "on", closet_at))
        released = with_outward.advance(release_check_at)

    with RuntimeScenario(press_at - timedelta(seconds=5)) as scenario:
        without_outward = scenario.create(predictive_map, 1)
        other_acquired = without_outward.observe(
            SensorInput("event.bathroom_scene_002", "pressed", press_at)
        )
        slow_decay = without_outward.advance(release_check_at)
        retained = without_outward.advance(press_at + timedelta(minutes=70))

    # Literal original-input expansion checks raw ISO transport as well as the
    # normalized pressed state. No explicit processing delays were retained.
    expected_press = SensorInput(
        "event.bathroom_scene_002", "pressed",
        datetime.fromisoformat("2026-08-22T07:28:36.046000+00:00"),
        reliability=1.0,
    )
    expected_closet = SensorInput(
        "binary_sensor.closet", "on",
        datetime.fromisoformat("2026-08-22T07:29:36.046000+00:00"),
        reliability=1.0,
    )
    press_delivery = InputDelivery(
        expected_press.entity_id, "2026-08-22T07:28:36.046000+00:00",
        expected_press.event_at, expected_press.event_at, expected_press.event_at,
        expected_press, expected_press, False, True,
    )
    assert with_outward.deliveries == (press_delivery, InputDelivery(
        expected_closet.entity_id, "on", expected_closet.event_at,
        expected_closet.event_at, expected_closet.event_at,
        expected_closet, expected_closet, False, True,
    ))
    assert without_outward.deliveries == (press_delivery,)
    on_edge = ActiveEdge(press_at, "bathroom", True)
    assert acquired.active("bathroom") and other_acquired.active("bathroom")
    assert on_edge in with_outward.input_edges_for("bathroom")
    assert without_outward.input_edges_for("bathroom") == (on_edge,)
    outward_edges = with_outward.edges_for("bathroom")
    assert not released.active("bathroom"), outward_edges
    assert tuple(edge.active for edge in outward_edges) == (True, False)
    assert outward_edges[0] == on_edge
    assert press_at < outward_edges[1].at <= release_check_at

    # Explicitly approved 2026-09-11: time-only decay is not departure from a
    # settled interaction endpoint (REQ-POLICY-013 / REQ-GOV-005). Preserve the
    # original checkpoint and the qualified-outward release branch above.
    assert slow_decay.active("bathroom") and retained.active("bathroom")
    assert without_outward.edges_for("bathroom") == (on_edge,)
