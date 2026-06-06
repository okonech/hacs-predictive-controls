from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custom_components.predictive_controls.entity_catalog import (
    candidate_from_state,
    is_motion_candidate,
    serialize_candidates,
)


@dataclass(frozen=True)
class FakeState:
    entity_id: str
    state: str = "off"
    attributes: Any = None


def test_motion_candidate_matches_binary_sensor_device_classes() -> None:
    assert is_motion_candidate("binary_sensor.foo", {"device_class": "motion"})
    assert is_motion_candidate("binary_sensor.foo", {"device_class": "occupancy"})
    assert is_motion_candidate("binary_sensor.foo", {"device_class": "presence"})


def test_motion_candidate_matches_entity_id_hints() -> None:
    assert is_motion_candidate("binary_sensor.kitchen_radar_target", {})
    assert is_motion_candidate("binary_sensor.mmwave_zone", {})


def test_motion_candidate_rejects_other_domains_and_plain_binary_sensors() -> None:
    assert not is_motion_candidate("sensor.motion_level", {"device_class": "motion"})
    assert not is_motion_candidate("binary_sensor.window", {"device_class": "opening"})


def test_candidate_from_state_serializes_friendly_name_and_device_class() -> None:
    candidate = candidate_from_state(
        FakeState(
            entity_id="binary_sensor.entry_motion",
            state="on",
            attributes={"friendly_name": "Entry Motion", "device_class": "motion"},
        )
    )

    assert candidate is not None
    assert candidate.entity_id == "binary_sensor.entry_motion"
    assert candidate.name == "Entry Motion"
    assert candidate.state == "on"
    assert candidate.device_class == "motion"


def test_candidate_from_state_rejects_non_mapping_attributes() -> None:
    assert candidate_from_state(FakeState("binary_sensor.entry_motion")) is None


def test_candidate_from_state_falls_back_for_non_string_attributes() -> None:
    candidate = candidate_from_state(
        FakeState(
            entity_id="binary_sensor.entry_motion",
            attributes={"friendly_name": 123, "device_class": 456},
        )
    )

    assert candidate is not None
    assert candidate.name == "binary_sensor.entry_motion"
    assert candidate.device_class is None


def test_serialize_candidates_filters_and_sorts() -> None:
    serialized = serialize_candidates(
        [
            FakeState("binary_sensor.z_motion", attributes={}),
            FakeState("sensor.a_motion", attributes={"device_class": "motion"}),
            FakeState("binary_sensor.a_motion", attributes={}),
        ]
    )

    assert serialized == [
        {
            "entity_id": "binary_sensor.a_motion",
            "name": "binary_sensor.a_motion",
            "state": "off",
            "device_class": None,
        },
        {
            "entity_id": "binary_sensor.z_motion",
            "name": "binary_sensor.z_motion",
            "state": "off",
            "device_class": None,
        },
    ]
