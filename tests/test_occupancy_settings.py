from __future__ import annotations

from custom_components.predictive_controls.occupancy_settings import (
    authoritative_occupants_from_state_value,
    expected_occupants_from_state_value,
    tracked_entity_ids,
)


def test_authoritative_occupant_count_requires_exact_zero_through_five() -> None:
    assert authoritative_occupants_from_state_value("0") == 0
    assert authoritative_occupants_from_state_value("5.0") == 5
    assert authoritative_occupants_from_state_value("home") == 1
    assert authoritative_occupants_from_state_value("away") == 0
    assert authoritative_occupants_from_state_value("2.9") is None
    assert authoritative_occupants_from_state_value("6") is None
    assert authoritative_occupants_from_state_value("unknown") is None


def test_expected_occupants_from_state_value_parses_common_states() -> None:
    assert expected_occupants_from_state_value("2", 1) == 2
    assert expected_occupants_from_state_value("2.9", 1) == 2
    assert expected_occupants_from_state_value("home", 2) == 1
    assert expected_occupants_from_state_value("on", 2) == 1
    assert expected_occupants_from_state_value("not_home", 2) == 0
    assert expected_occupants_from_state_value("off", 2) == 0
    assert expected_occupants_from_state_value("unknown", 2) == 2
    assert expected_occupants_from_state_value(None, 2) == 2
    assert expected_occupants_from_state_value("not a count", 2) == 2
    assert expected_occupants_from_state_value("-3", 2) == 0
    assert expected_occupants_from_state_value("", -1) == 0


def test_tracked_entity_ids_includes_optional_expected_occupants_helper() -> None:
    assert tracked_entity_ids(
        ("binary_sensor.office_motion",),
        "input_number.expected_occupants",
    ) == (
        "binary_sensor.office_motion",
        "input_number.expected_occupants",
    )
    assert tracked_entity_ids(("binary_sensor.office_motion",), "") == (
        "binary_sensor.office_motion",
    )
