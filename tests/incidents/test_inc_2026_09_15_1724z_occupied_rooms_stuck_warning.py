"""User-reported issue: "These are not stuck, it's the rooms Shaila adn I are in."
User expected: legitimate long presence must not be falsely presented as stuck.
Observed: Guest Bedroom/Alex Office showed80% belief, Inactive, suspected stuck.
Source: 2026-09-15 screenshot/report and approved read-only HA diagnostics/history.
Test scope: public Reliability wording for the post-reset observation sequence,
not a physical light test, full restart reproduction, or new occupancy authority.

Same-day clarification allows a temporary post-restart notice; the requested
oracle is non-fault wording, not suppressing diagnostics or inventing paths.
This proposed DIAG007 presentation acceptance currently fails under HEALTH001's
existing suspected_stuck label. No old scenario or production rule is changed.

Evidence: homelab/tmp/occupied-room-warning-20260915/diagnostics.json SHA256
cc7d089dd4acd91d60ca82e2d8688d9eb826ce7759ea459f9272d18db7529162;
history.json SHA256
4a0fd2a1069504ae7cb1e16b87a7216df2a8cb7fb08006963752f6b35ca9529f.
The test has no runtime dependency on these private, ignored captures.

Live: count2,U/U; restore rejected with incompatible map fingerprint; rooms
already ON before reset. Recorder query17:15 is a clamped baseline, NOT arrival.
Public active went OFF at17:24:15.201095/.201855, warning count became2 at
17:34:43.862797. Runtime audit positives below are observation frontiers, NOT
new physical entrances. No old checkpoint was retained or fabricated here.

Nine-node induced causal slice keeps every immediate room authorization boundary,
interaction aliases and exact relevant input order. Full31 nodes/40 reconstructed
inputs and this slice12 inputs gave identical public warnings,600s frontiers and
U/U. Omitted Shaila-office/right-fireplace positives never crossed these boundary
nodes. No untracked_expired timer audit row is replayed as an ON observation.
Reliability comes from captured episodes (.75/.85/.9/1); device timing/prior
settings are not exposed by the capture. Beliefs/full config are not asserted
equivalent. Fake registered timer phase is not the measured HA scheduler phase.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from tests.runtime_replay import RuntimeScenario

_GUEST = "binary_sensor.guest_bedroom_guest_bedroom_motion_motion_detection"
_OFFICE = "binary_sensor.alex_office_alex_office_motion_motion_detection"
_TOP = "binary_sensor.top_of_staircase_motion_motion_detection"
_BOTTOM = "binary_sensor.bottom_of_staircase_motion_motion_detection"
_FIREPLACE = "binary_sensor.apollo_msr_2_2cb8b0_radar_"


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-15T{time}+00:00")


def _incident_map() -> PredictiveMap:
    """Frozen local topology, not a dependency on the changing home map."""
    nodes: dict[str, dict[str, object]] = {
        "guest_bedroom_motion": {
            "zone": "guest_bedroom", "floor": "first_floor",
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "reliability": 0.75, "entities": {"mmwave": _GUEST},
            "adjacent": ["bottom_of_staircase_motion",
                         "bottom_of_staircase_motion_interaction",
                         "living_room_fireplace_left"],
        },
        "alex_office_motion": {
            "zone": "alex_office", "floor": "second_floor",
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "reliability": 0.75, "entities": {"mmwave": _OFFICE},
            "adjacent": ["top_of_staircase_motion",
                         "top_of_staircase_motion_interaction"],
        },
        "top_of_staircase_motion": {
            "zone": "upstairs_hallway", "floor": "second_floor",
            "role": "transition_gate", "occupancy_behavior": "transient",
            "reliability": 0.85, "entities": {"mmwave": _TOP},
            "adjacent": ["bottom_of_staircase_motion",
                         "bottom_of_staircase_motion_interaction",
                         "alex_office_motion", "alex_office_motion_interaction"],
        },
        "bottom_of_staircase_motion": {
            "zone": "staircase_bottom", "floor": "first_floor",
            "role": "transition_gate", "occupancy_behavior": "transient",
            "reliability": 0.85, "entities": {"mmwave": _BOTTOM},
            "adjacent": ["guest_bedroom_motion", "guest_bedroom_motion_interaction",
                         "top_of_staircase_motion",
                         "top_of_staircase_motion_interaction"],
        },
        "living_room_fireplace_left": {
            "zone": "living_room_left", "floor": "first_floor",
            "role": "anchor_sensor", "occupancy_behavior": "sticky",
            "reliability": 0.9,
            "entities": {signal: _FIREPLACE + signal for signal in (
                "target", "moving_target", "still_target", "zone_3_occupancy",
            )},
            "adjacent": ["guest_bedroom_motion", "guest_bedroom_motion_interaction"],
        },
    }
    # Each interaction is a separate physical node in the captured configuration.
    for node, entity_prefix, adjacent in (
        ("guest_bedroom_motion", "guest_bedroom_guest_bedroom_motion",
         ["bottom_of_staircase_motion", "living_room_fireplace_left"]),
        ("alex_office_motion", "alex_office_alex_office_motion",
         ["top_of_staircase_motion"]),
        ("top_of_staircase_motion", "top_of_staircase_motion",
         ["bottom_of_staircase_motion", "alex_office_motion"]),
        ("bottom_of_staircase_motion", "bottom_of_staircase_motion",
         ["guest_bedroom_motion", "top_of_staircase_motion"]),
    ):
        source = nodes[node]
        nodes[f"{node}_interaction"] = {
            "zone": source["zone"], "floor": source["floor"],
            "role": source["role"], "reliability": 1.0,
            "occupancy_behavior": (
                "sticky" if source["role"] == "room_occupancy" else "transient"
            ),
            "entities": {
                f"interaction_scene_{number:03}":
                f"event.{entity_prefix}_scene_{number:03}"
                for number in (1, 2, 3)
            },
            "adjacent": adjacent,
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


# event time, entity, level, audit processing time. OFF levels are corroborated
# by recorder history; unavailable/clear alias times are retained runtime events.
_INPUTS = (
    ("17:24:15.626734", _TOP, "off", "17:24:15.626751"),
    ("17:24:15.648418", _BOTTOM, "off", "17:24:15.648434"),
    ("17:24:15.769618", _GUEST, "on", "17:24:15.769635"),
    ("17:24:15.791089", _OFFICE, "on", "17:24:15.791104"),
    ("17:24:15.835427", _FIREPLACE + "zone_3_occupancy", "unavailable",
     "17:24:15.835437"),
    ("17:24:15.838410", _FIREPLACE + "target", "unavailable", "17:24:15.838423"),
    ("17:24:15.841198", _FIREPLACE + "moving_target", "unavailable",
     "17:24:15.841211"),
    ("17:24:15.843884", _FIREPLACE + "still_target", "unavailable",
     "17:24:15.843896"),
    ("17:24:16.033897", _FIREPLACE + "zone_3_occupancy", "off", "17:24:16.033907"),
    ("17:24:16.036876", _FIREPLACE + "target", "off", "17:24:16.036884"),
    ("17:24:16.039422", _FIREPLACE + "moving_target", "off", "17:24:16.039430"),
    ("17:24:16.041899", _FIREPLACE + "still_target", "off", "17:24:16.041908"),
)


@pytest.mark.scenario
def test_inc_2026_09_15_1724z_occupied_rooms_stuck_warning() -> None:
    """Unlocated post-reset presence is a notice, not a demonstrated stuck sensor."""
    with RuntimeScenario(_at("17:24:15.377673")) as scenario:
        replay = scenario.create(_incident_map(), 2).watch_reliability()
        for at, entity, state, processed in _INPUTS:
            replay.send(entity, state, _at(at), processing_at=_at(processed))
        assert len(replay.deliveries) == 12
        assert replay.runtime.confidence.diagnostics.selected_paths == (None, None)

        # No repeated ON deliveries or inserted movement during the stationary stay.
        replay.advance(_at("17:34:15.769617"))
        assert replay.reliability_writes
        assert all(write.attributes["active_count"] == 0
                   for write in replay.reliability_writes)
        replay.advance(_at("17:44:34.610632"))  # Retained capture, before stair ONs.
        assert len(replay.deliveries) == 12
        attributes = replay.reliability_attributes
        assert attributes is not None
        assert attributes["active_count"] == 2  # Do not "fix" by deleting diagnostics.
        rows = attributes["warnings"]
        assert isinstance(rows, list)
        assert {row["node_id"]: row["first_observed_at"] for row in rows} == {
            "guest_bedroom_motion": _at("17:34:15.769618").isoformat(),
            "alex_office_motion": _at("17:34:15.791089").isoformat(),
        }
        assert all(row["active"] and row["reasons"] == ["assertion_timeout"]
                   for row in rows)
        summaries = [write.attributes["active_summary"]
                     for write in replay.reliability_writes
                     if write.attributes["active_count"] == 2]
        assert summaries
        assert all(isinstance(text, str)
                   and "guest_bedroom" in text and "alex_office" in text
                   for text in summaries)
        # User-facing acceptance. Both rooms currently fail this assertion.
        assert all(isinstance(text, str) and "stuck" not in text.casefold()
                   for text in summaries), attributes["active_summary"]
