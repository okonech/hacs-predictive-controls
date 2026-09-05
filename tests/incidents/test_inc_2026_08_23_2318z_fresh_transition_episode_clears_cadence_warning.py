from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import tracker_diagnostics_payload


def target_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def event(node: str, zone: str, state: str, at: datetime) -> OccupancyEvent:
    return OccupancyEvent(
        f"binary_sensor.{node}",
        node,
        zone,
        None,
        "transition_gate" if node == "hall" else "room_occupancy",
        "transient" if node == "hall" else "sustained",
        "motion",
        state,
        at,
        1.0,
    )


@pytest.mark.target_model
def test_inc_2026_08_23_2318z_fresh_transition_episode_clears_cadence_warning() -> None:
    confidence = ZoneConfidenceEngine(target_map(), expected_occupants=1)
    asserted_at = datetime(2026, 8, 23, 23, 18, 9, 318691, tzinfo=UTC)
    cleared_at = datetime(2026, 8, 23, 23, 18, 22, 409960, tzinfo=UTC)
    warned_at = datetime(2026, 8, 23, 23, 18, 23, 996249, tzinfo=UTC)
    final_clear_at = datetime(2026, 8, 23, 23, 18, 35, 938992, tzinfo=UTC)
    stable_clear_at = final_clear_at + timedelta(seconds=5)
    recovered_at = datetime(2026, 8, 23, 23, 19, 42, 568890, tzinfo=UTC)

    confidence.observe(event("hall", "hall", "on", asserted_at))
    confidence.observe(event("hall", "hall", "off", cleared_at))
    confidence.observe(event("hall", "hall", "on", warned_at))

    warned = tracker_diagnostics_payload(confidence.diagnostics)
    assert warned["reliability_warnings"] == [
        {
            "node_id": "hall",
            "zone": "hall",
            "kind": "flapping",
            "reasons": ["impossible_cadence"],
            "active_reasons": ["impossible_cadence"],
            "first_observed_at": warned_at.isoformat(),
            "last_observed_at": warned_at.isoformat(),
            "cleared_at": None,
            "active": True,
        }
    ]

    confidence.observe(event("hall", "hall", "off", final_clear_at))
    confidence.refresh_active(stable_clear_at)

    recovered = tracker_diagnostics_payload(confidence.diagnostics)
    assert recovered["reliability_warnings"] == []
    occurrence = recovered["reliability_warning_occurrences"][0]
    assert occurrence["active"] is False
    assert occurrence["cleared_at"] == stable_clear_at.isoformat()

    confidence.observe(event("hall", "hall", "on", recovered_at))
    assert tracker_diagnostics_payload(confidence.diagnostics)[
        "reliability_warnings"
    ] == []
