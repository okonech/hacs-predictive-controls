"""User-reported issue: "I just walked from the basement up to the kitchen
and then up stairs to alex office, but the path was not detected. I had to
manually turn on alex office."
User expected: detect the walk and turn on Alex Office without a manual press;
same-input ON at office motion and uninterrupted ON through the press are the
hardened acceptance oracle, not additional quoted user wording.
Acceptance confirmed: on September17, after the detailed scenario description,
the user approved this motion-time ON and continuous-ON-through-press expectation.
Keep all46 recorded inputs, including the foyer reactivation and later press;
the cause of the foyer detection remains unknown. No existing oracle is relaxed.
Observed: office motion ON20:56:10.437899UTC did not activate the office. The
physical press occurred20:57:08.336000, recorder callback20:57:08.336333;
recorded active ON20:57:08.339399 and light ON20:57:08.428596 followed it.
Source: September16 user report, corrected to this earlier press, retained in
docs/spec/INC-2026-09-16-2054Z-office-overlap-arrival.md (hardened3/3).
Test scope: count2 cold-inference replica through actual runtime raw transport,
registered fake timers and public ZoneActiveSensor edges, not physical actuation,
person identity, direction, exact live posterior, or a full HA restart.

Approved cached evidence: sibling homelab/tmp/missed-office-path-20260917/.
The directory date is capture naming; first material input is September16,
20:54:10.059406UTC. There is no live HA or ignored-file dependency in this test.
SHA256 all-input-history.json:
9adcc7c50bae18182f6d4c7a19f7ed6e03ae03de256b99467f1d57d7d403431b
SHA256 path-history.json:
b426e831226cdfa611d0a849b5f89a976c2f7d744ccdef1f6e343374de9baa2a
SHA256 office-day-history.json:
4f69ed02bed45cc1e61e36a8b52d4f3b269400785cb1fb255d1fbefb27f6f8ca
SHA256 status.json:
96b969b36c8f68855ba2e9371fc979596cef552d293701e5993636207013fc4c
SHA256 homelab/home-assistant/predictive-controls-map.yaml:
7e5a2175442d11d5387f9917c952eb3abe91726a9a237170c5ec7a57853af96f

Freeze all46 actual changes across12 delivered entities in [20:54:10,20:57:09]
UTC, excluding each recorder group's clamped initial row and sorting last_changed.
Minimal-response rows inherit entity_id from their group's first row. All11
participating binary aliases were OFF immediately before the window. The retained
button timestamp is a neutral startup level, not another press. Other interaction
aliases remain mapped but have no delivery. The nine-node induced graph preserves
all aliases, roles, effective zone behaviors, reliabilities and directed timings;
no omitted node or graph shortcut is fabricated.

Configured/accepted count2 is available in status; count history is empty. No
exact pre-walk inference snapshot or full incident policy audit survives. Cold
startup at the retained interval boundary is explicit, not injected latent state.
Recorder last_changed supplies callback order; uncaptured receipt delay and HA
timer phase are not inferred. The button's raw occurrence and callback remain
distinct. Full31-node and nine-node exploratory replays agreed on missed motion
acquisition then press acquisition; their probabilities are replica-only facts.

Diagnosis (separate from the report): the later foyer input truncates the selected
route at bottom stairs, withdrawing still-observed top-stairs branch authority.
The arrival-time unsupported_jump diagnostic is supplementary; capture it BEFORE
the press can clear it, but assert the complete public timeline first. Governing
requirements: PATH001-006, GOAL004/005/008/009/011, EVID002/006/011, HEALTH004,
PUBLIC001/002, POLICY013/014 and GOV002/005. No mechanism is mocked or seeded.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import project_reliability_warnings
from tests.runtime_replay import ActiveEdge, RuntimeScenario

_GYM = "binary_sensor.gym_lights_motion_motion_detection"
_FOYER = "binary_sensor.foyer_pir_motion_motion_detection"
_DINING = "binary_sensor.dining_room_motion_motion_detection"
_KITCHEN = "binary_sensor.mmwave_dimmer_motion_detection_2"
_TARGET = "binary_sensor.island_monitor_radar_target"
_MOVING = "binary_sensor.island_monitor_radar_moving_target"
_STILL = "binary_sensor.island_monitor_radar_still_target"
_ZONE3 = "binary_sensor.island_monitor_radar_zone_3_occupancy"
_BOTTOM = "binary_sensor.bottom_of_staircase_motion_motion_detection"
_TOP = "binary_sensor.top_of_staircase_motion_motion_detection"
_OFFICE = "binary_sensor.alex_office_alex_office_motion_motion_detection"
_BUTTON = "event.alex_office_alex_office_motion_scene_002"
_PRESS_RAW = "2026-09-16T20:57:08.336+00:00"
_ARRIVAL = "20:56:10.437899"
_PRESS_CALLBACK = "20:57:08.336333"


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-16T{time}+00:00")


def _incident_map() -> PredictiveMap:
    """Exact induced model configuration; display positions are not model inputs."""
    return PredictiveMap.from_mapping({
        "zones": {
            "alex_office": {
                "role": "room_occupancy", "occupancy_behavior": "sustained",
            },
            "staircase_bottom": {
                "role": "transition_gate", "occupancy_behavior": "transient",
            },
            "dining_room": {
                "role": "transition_gate", "occupancy_behavior": "transient",
            },
            "foyer": {
                "role": "transition_gate", "occupancy_behavior": "transient",
            },
            "gym": {
                "role": "room_occupancy", "occupancy_behavior": "sustained",
            },
            "kitchen": {
                "role": "room_occupancy", "occupancy_behavior": "sustained",
            },
            "living_room_right": {
                "role": "anchor_sensor", "occupancy_behavior": "sticky",
            },
            "upstairs_hallway": {
                "role": "transition_gate", "occupancy_behavior": "transient",
            },
        },
        "nodes": {
            "alex_office_motion": {
                "label": "Alex Office Motion",
                "zone": "alex_office", "floor": "second_floor",
                "role": "room_occupancy", "initial_weight": 0.75,
                "entities": {"mmwave": _OFFICE},
                "adjacent": ["top_of_staircase_motion"],
            },
            "alex_office_motion_interaction": {
                "label": "Alex Office Motion Physical Controls",
                "zone": "alex_office", "floor": "second_floor",
                "role": "room_occupancy", "occupancy_behavior": "sticky",
                "initial_weight": 1.0,
                "entities": {
                    "interaction_scene_001":
                        "event.alex_office_alex_office_motion_scene_001",
                    "interaction_scene_002": _BUTTON,
                    "interaction_scene_003":
                        "event.alex_office_alex_office_motion_scene_003",
                },
                "adjacent": ["top_of_staircase_motion"],
            },
            "bottom_of_staircase_motion": {
                "label": "Bottom of Staircase Motion",
                "zone": "staircase_bottom", "floor": "first_floor",
                "role": "transition_gate", "initial_weight": 0.85,
                "entities": {"mmwave": _BOTTOM},
                "adjacent": ["foyer_pir_motion", "top_of_staircase_motion"],
            },
            "dining_room_motion": {
                "label": "Dining room motion",
                "zone": "dining_room", "floor": "first_floor",
                "role": "transition_gate", "initial_weight": 0.75,
                "entities": {"mmwave": _DINING},
                "adjacent": [
                    "kitchen_overhead_mmwave_dimmer", "living_room_fireplace_right",
                    "foyer_pir_motion", "gym_lights_motion",
                ],
                "transition_seconds": {
                    "kitchen_overhead_mmwave_dimmer": 15, "foyer_pir_motion": 15,
                },
            },
            "foyer_pir_motion": {
                "label": "Foyer PIR Motion",
                "zone": "foyer", "floor": "first_floor",
                "role": "transition_gate", "initial_weight": 0.85,
                "entities": {"motion": _FOYER},
                "adjacent": ["dining_room_motion", "bottom_of_staircase_motion"],
                "transition_seconds": {"dining_room_motion": 15},
            },
            "gym_lights_motion": {
                "label": "Gym Lights Motion",
                "zone": "gym", "floor": "basement",
                "role": "room_occupancy", "initial_weight": 0.75,
                "review_required": True,
                "entities": {"mmwave": _GYM},
                "adjacent": ["dining_room_motion"],
            },
            "kitchen_overhead_mmwave_dimmer": {
                "label": "Kitchen Overhead mmWave Dimmer",
                "zone": "kitchen", "floor": "first_floor",
                "role": "room_occupancy", "initial_weight": 0.8,
                "entities": {"mmwave": _KITCHEN},
                "adjacent": ["dining_room_motion"],
                "transition_seconds": {"dining_room_motion": 15},
            },
            "living_room_fireplace_right": {
                "label": "Fireplace Monitor Right",
                "zone": "living_room_right", "floor": "first_floor",
                "role": "anchor_sensor", "initial_weight": 0.9,
                "entities": {
                    "target": _TARGET, "moving_target": _MOVING,
                    "still_target": _STILL, "zone_3_occupancy": _ZONE3,
                },
                "adjacent": ["dining_room_motion"],
            },
            "top_of_staircase_motion": {
                "label": "Top of Staircase Motion",
                "zone": "upstairs_hallway", "floor": "second_floor",
                "role": "transition_gate", "initial_weight": 0.85,
                "entities": {"mmwave": _TOP},
                "adjacent": [
                    "bottom_of_staircase_motion", "alex_office_motion",
                    "alex_office_motion_interaction",
                ],
            },
        },
    })


_INITIAL_STATES = {
    _GYM: "off", _FOYER: "off", _DINING: "off", _KITCHEN: "off",
    _TARGET: "off", _MOVING: "off", _STILL: "off", _ZONE3: "off",
    _BOTTOM: "off", _TOP: "off", _OFFICE: "off",
    _BUTTON: "2026-09-15T02:43:02.506+00:00",
}

# Recorder callback time, actual entity, unmodified raw state. Binary occurrence
# uses the callback frontier; the final EventEntity carries its own occurrence.
_INPUTS = (
    ("20:54:10.059406", _GYM, "on"),
    ("20:54:23.730272", _FOYER, "on"),
    ("20:54:25.374829", _DINING, "on"),
    ("20:54:35.793315", _KITCHEN, "on"),
    ("20:54:40.192696", _FOYER, "off"),
    ("20:54:46.435432", _GYM, "off"),
    ("20:54:55.949526", _KITCHEN, "off"),
    ("20:54:58.199633", _DINING, "off"),
    ("20:55:03.781036", _KITCHEN, "on"),
    ("20:55:14.755216", _DINING, "on"),
    ("20:55:18.011830", _TARGET, "on"),
    ("20:55:18.019246", _STILL, "on"),
    ("20:55:18.023092", _ZONE3, "on"),
    ("20:55:19.690766", _MOVING, "on"),
    ("20:55:19.694411", _STILL, "off"),
    ("20:55:20.112063", _MOVING, "off"),
    ("20:55:20.115810", _STILL, "on"),
    ("20:55:20.118550", _ZONE3, "off"),
    ("20:55:21.120863", _ZONE3, "on"),
    ("20:55:23.216692", _MOVING, "on"),
    ("20:55:23.220200", _STILL, "off"),
    ("20:55:24.211828", _MOVING, "off"),
    ("20:55:24.215363", _STILL, "on"),
    ("20:55:27.221607", _MOVING, "on"),
    ("20:55:27.225207", _STILL, "off"),
    ("20:55:27.756781", _KITCHEN, "off"),
    ("20:55:28.312352", _ZONE3, "off"),
    ("20:55:29.313404", _ZONE3, "on"),
    ("20:55:30.315079", _MOVING, "off"),
    ("20:55:30.320123", _STILL, "on"),
    ("20:55:32.414228", _KITCHEN, "on"),
    ("20:55:35.603322", _TARGET, "off"),
    ("20:55:35.607695", _STILL, "off"),
    ("20:55:35.611161", _ZONE3, "off"),
    ("20:55:39.302965", _FOYER, "on"),
    ("20:55:42.178035", _BOTTOM, "on"),
    ("20:55:46.178141", _KITCHEN, "off"),
    ("20:55:49.981388", _DINING, "off"),
    ("20:55:54.319221", _FOYER, "off"),
    ("20:55:58.565082", _TOP, "on"),
    ("20:56:00.241805", _FOYER, "on"),
    ("20:56:10.348702", _FOYER, "off"),
    (_ARRIVAL, _OFFICE, "on"),
    ("20:56:12.412841", _BOTTOM, "off"),
    ("20:56:16.576440", _TOP, "off"),
    (_PRESS_CALLBACK, _BUTTON, _PRESS_RAW),
)


@pytest.mark.scenario
def test_inc_2026_09_16_2054z_office_overlap_arrival() -> None:
    """The complete count2 public timeline must acquire at motion, not the press."""
    predictive_map = _incident_map()
    assert len(predictive_map.nodes) == 9
    assert len(_INPUTS) == 46
    assert len({entity for _, entity, _ in _INPUTS}) == 12
    assert sum(entity.startswith("binary_sensor.") and state == "off"
               for entity, state in _INITIAL_STATES.items()) == 11
    assert tuple(at for at, _, _ in _INPUTS) == tuple(sorted(
        at for at, _, _ in _INPUTS
    ))

    with RuntimeScenario(_at("20:54:10")) as scenario:
        replay = scenario.create(
            predictive_map, 2, initial_states=dict(_INITIAL_STATES),
        )
        assert not replay.view().active("alex_office")
        assert not replay.deliveries  # Startup levels are not physical events.
        arrival_warnings: tuple[dict[str, object], ...] | None = None
        for callback, entity, raw_state in _INPUTS:
            replay.send(entity, raw_state, _at(callback))
            if callback == _ARRIVAL:
                # Read the exact arrival diagnostic now, not after the press
                # clears it. This snapshot never supplies inference or an oracle
                # prerequisite that could mask the full public-timeline failure.
                arrival_warnings = tuple(
                    row for row in project_reliability_warnings(
                        replay.runtime.confidence.reliability_warning_occurrences,
                        _at(callback),
                    )
                    if row["zone"] == "alex_office"
                    and row["kind"] == "unsupported_jump"
                )

        assert len(replay.deliveries) == len(replay.normalized_inputs) == 46
        assert tuple((delivery.callback_at, delivery.entity_id, delivery.raw_state)
                     for delivery in replay.deliveries) == tuple(
            (_at(callback), entity, raw_state)
            for callback, entity, raw_state in _INPUTS
        )
        assert all(delivery.delivered and not delivery.is_count
                   and delivery.retained_input is None
                   and delivery.processing_at == delivery.callback_at
                   for delivery in replay.deliveries)
        for delivery in replay.deliveries:
            normalized = delivery.normalized
            assert normalized is not None
            binding = predictive_map.entity_binding_for_entity(delivery.entity_id)
            assert binding is not None
            assert normalized.reliability == predictive_map.nodes[
                binding.node_id
            ].reliability  # No historical reliability override or normalizer mock.
            assert normalized.state == (
                "pressed" if delivery.entity_id == _BUTTON else delivery.raw_state
            )
            assert delivery.event_at == (
                datetime.fromisoformat(_PRESS_RAW)
                if delivery.entity_id == _BUTTON else delivery.callback_at
            )
        press = replay.deliveries[-1]
        assert press.raw_state == "2026-09-16T20:57:08.336+00:00"
        assert press.event_at == _at("20:57:08.336000")
        assert press.callback_at == _at("20:57:08.336333")
        assert scenario.clock.now == _at(_PRESS_CALLBACK)
        assert scenario.clock.executions  # Genuine registered timer work ran.

        office_edges = tuple(
            (edge.at.isoformat(), edge.active)
            for edge in replay.edges_for("alex_office")
        )
        # Primary oracle first: exactly one ON at motion, no early/timer ON,
        # OFF or reacquisition anywhere through all46 inputs including the press.
        assert office_edges == ((_at(_ARRIVAL).isoformat(), True),), (
            f"Complete office timeline through press: actual={office_edges!r}; "
            f"arrival_unsupported_jump={arrival_warnings!r}"
        )
        assert replay.input_edges_for("alex_office") == (
            ActiveEdge(_at(_ARRIVAL), "alex_office", True),
        )
        assert arrival_warnings == (), "Supported office arrival must not warn"
