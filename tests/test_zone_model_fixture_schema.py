from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "zone_model"
REPOSITORY_ROOT = Path(__file__).parents[1]
SPECIFICATION_PATH = REPOSITORY_ROOT / "SPECIFICATION.md"
EXPECTED_FIXTURES = {
    "t01_open_hallway_backtracking.json",
    "t02_direct_arrival_quiet_stay.json",
    "t03_two_occupants_open_transition.json",
    "t04_probability_release_without_global_support.json",
    "t05_stuck_transition_degrades.json",
    "t06_stuck_stay_degrades.json",
    "t07_manual_off_refresh.json",
}
REQUIREMENT_PATTERN = re.compile(r"^- \*\*(REQ-[A-Z]+-[0-9]{3})", re.MULTILINE)
VALID_ROLES = {"stay", "transition", "entry", "hybrid"}
VALID_PROFILES = {
    "entry_boundary",
    "stay_pir",
    "stay_presence",
    "transition_fast",
}
VALID_INPUT_KINDS = {"external_output", "sensor", "timer"}
VALID_SENSOR_STATES = {"off", "on", "unavailable", "unknown"}
VALID_ARRIVAL_TYPES = {"acquired", "refreshed"}


def _mapping(value: object, field: str) -> Mapping[str, object]:
    assert isinstance(value, dict), f"{field} must be an object"
    return cast(Mapping[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    assert isinstance(value, list), f"{field} must be an array"
    return cast(list[object], value)


def _strings(value: object, field: str) -> list[str]:
    items = _sequence(value, field)
    assert all(isinstance(item, str) for item in items), f"{field} must contain strings"
    return cast(list[str], items)


def _utc_datetime(value: object, field: str) -> datetime:
    assert isinstance(value, str), f"{field} must be an ISO datetime"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"{field} must include a timezone"
    assert parsed.utcoffset() == UTC.utcoffset(parsed), f"{field} must be UTC"
    return parsed


def _validate_profile(name: str, raw_profile: object) -> None:
    profile = _mapping(raw_profile, f"hardware_timing.{name}")
    expected_fields = {
        "assertion_trust_seconds",
        "burst_correlation_seconds",
        "hardware_hold_seconds",
        "post_clear_residual",
        "stable_clear_seconds",
        "traversal_context_seconds",
    }
    assert set(profile) == expected_fields
    for field in expected_fields - {"post_clear_residual"}:
        value = profile[field]
        assert isinstance(value, (int, float)) and value >= 0, (
            f"hardware_timing.{name}.{field} must be non-negative"
        )
    residual = profile["post_clear_residual"]
    assert isinstance(residual, (int, float)) and 0 <= residual <= 1


def _validate_test_reference(reference: str) -> None:
    module_reference, separator, test_name = reference.partition("::")
    module_path = Path(module_reference)
    assert module_path.parts[:1] == ("tests",)
    assert module_path.name.startswith("test_") and module_path.suffix == ".py"
    absolute_path = REPOSITORY_ROOT / module_path
    assert absolute_path.is_file(), f"unknown related test module: {module_reference}"
    if separator:
        assert test_name.startswith("test_") and test_name.isidentifier()
        syntax_tree = ast.parse(absolute_path.read_text())
        function_names = {
            node.name
            for node in ast.walk(syntax_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert test_name in function_names, f"unknown related test: {reference}"


def _validate_fixture(path: Path, requirement_ids: set[str]) -> None:
    raw = json.loads(path.read_text())
    fixture = _mapping(raw, path.name)
    assert set(fixture) == {
        "authoritative_count",
        "expected_public_timeline",
        "expected_reason_classes",
        "hardware_timing",
        "initial_state",
        "inputs",
        "owning_phase",
        "requirement_ids",
        "scenario_id",
        "schema_version",
        "source",
        "topology",
    }
    assert fixture["schema_version"] == 1
    assert isinstance(fixture["scenario_id"], str)
    assert isinstance(fixture["owning_phase"], int)
    assert fixture["owning_phase"] in {4, 5}

    requirements = _strings(fixture["requirement_ids"], "requirement_ids")
    assert requirements
    assert set(requirements) <= requirement_ids

    source = _mapping(fixture["source"], "source")
    assert source["kind"] == "synthetic_target_contract"
    assert isinstance(source["description"], str) and source["description"]
    related_tests = _strings(source["related_tests"], "source.related_tests")
    assert related_tests
    for reference in related_tests:
        _validate_test_reference(reference)

    topology = _mapping(fixture["topology"], "topology")
    assert set(topology) == {"nodes", "zones"}
    zones = set(_strings(topology["zones"], "topology.zones"))
    assert zones
    nodes = _mapping(topology["nodes"], "topology.nodes")
    assert nodes
    entities: set[str] = set()
    used_profiles: set[str] = set()
    for node_id, raw_node in nodes.items():
        node = _mapping(raw_node, f"topology.nodes.{node_id}")
        assert set(node) == {"adjacent", "entity_id", "profile", "role", "zone"}
        assert node["zone"] in zones
        assert node["role"] in VALID_ROLES
        profile_name = node["profile"]
        assert isinstance(profile_name, str) and profile_name in VALID_PROFILES
        used_profiles.add(profile_name)
        entity_id = node["entity_id"]
        assert isinstance(entity_id, str) and entity_id.startswith("binary_sensor.")
        assert entity_id not in entities
        entities.add(entity_id)
        adjacent = _strings(node["adjacent"], f"topology.nodes.{node_id}.adjacent")
        assert set(adjacent) <= set(nodes)
    for node_id, raw_node in nodes.items():
        node = _mapping(raw_node, f"topology.nodes.{node_id}")
        for neighbor in _strings(
            node["adjacent"], f"topology.nodes.{node_id}.adjacent"
        ):
            neighbor_node = _mapping(nodes[neighbor], f"topology.nodes.{neighbor}")
            assert node_id in _strings(
                neighbor_node["adjacent"],
                f"topology.nodes.{neighbor}.adjacent",
            )

    timing = _mapping(fixture["hardware_timing"], "hardware_timing")
    assert set(timing) == used_profiles
    for profile_name, profile in timing.items():
        _validate_profile(profile_name, profile)

    count = fixture["authoritative_count"]
    assert isinstance(count, int) and 0 <= count <= 2
    initial = _mapping(fixture["initial_state"], "initial_state")
    assert set(initial) == {"active", "beliefs"}
    beliefs = _mapping(initial["beliefs"], "initial_state.beliefs")
    active = _mapping(initial["active"], "initial_state.active")
    assert set(beliefs) == zones
    assert set(active) == zones
    assert all(
        isinstance(value, (int, float)) and 0 <= value <= 1
        for value in beliefs.values()
    )
    assert all(isinstance(value, bool) for value in active.values())

    inputs = _sequence(fixture["inputs"], "inputs")
    assert inputs
    input_times: set[datetime] = set()
    last_event_at: datetime | None = None
    last_received_at: datetime | None = None
    for index, raw_input in enumerate(inputs):
        model_input = _mapping(raw_input, f"inputs[{index}]")
        kind = model_input["kind"]
        assert kind in VALID_INPUT_KINDS
        event_at = _utc_datetime(model_input["event_at"], f"inputs[{index}].event_at")
        received_at = _utc_datetime(
            model_input["received_at"], f"inputs[{index}].received_at"
        )
        assert event_at <= received_at
        if last_event_at is not None:
            assert event_at >= last_event_at
        if last_received_at is not None:
            assert received_at >= last_received_at
        last_event_at = event_at
        last_received_at = received_at
        input_times.add(event_at)
        assert isinstance(model_input["description"], str)
        if kind == "sensor":
            assert set(model_input) == {
                "description",
                "event_at",
                "kind",
                "node_id",
                "received_at",
                "state",
            }
            assert model_input["node_id"] in nodes
            assert model_input["state"] in VALID_SENSOR_STATES
        elif kind == "external_output":
            assert set(model_input) == {
                "description",
                "event_at",
                "kind",
                "received_at",
                "state",
                "zone",
            }
            assert model_input["zone"] in zones
            assert model_input["state"] in {"off", "on"}
        else:
            assert set(model_input) == {
                "description",
                "event_at",
                "kind",
                "received_at",
            }

    timeline = _sequence(
        fixture["expected_public_timeline"], "expected_public_timeline"
    )
    assert timeline
    last_timeline_at: datetime | None = None
    timeline_reasons: set[str] = set()
    for index, raw_row in enumerate(timeline):
        row = _mapping(raw_row, f"expected_public_timeline[{index}]")
        assert set(row) == {
            "active_changes",
            "arrival_events",
            "at",
            "health_changes",
            "reason",
        }
        at = _utc_datetime(row["at"], f"expected_public_timeline[{index}].at")
        assert at in input_times
        if last_timeline_at is not None:
            assert at >= last_timeline_at
        last_timeline_at = at
        changes = _mapping(row["active_changes"], "active_changes")
        health_changes = _mapping(row["health_changes"], "health_changes")
        assert set(changes) <= zones
        assert set(health_changes) <= zones
        assert all(isinstance(value, bool) for value in changes.values())
        assert all(isinstance(value, bool) for value in health_changes.values())
        acquired_zones: set[str] = set()
        for raw_arrival in _sequence(row["arrival_events"], "arrival_events"):
            arrival = _mapping(raw_arrival, "arrival_event")
            assert set(arrival) == {"event_type", "zone"}
            arrival_zone = arrival["zone"]
            assert isinstance(arrival_zone, str) and arrival_zone in zones
            assert arrival["event_type"] in VALID_ARRIVAL_TYPES
            if arrival["event_type"] == "acquired":
                assert changes.get(arrival_zone) is True
                acquired_zones.add(arrival_zone)
        assert {
            zone for zone, became_active in changes.items() if became_active is True
        } == acquired_zones
        reason = row["reason"]
        assert isinstance(reason, str) and reason
        timeline_reasons.add(reason)

    reasons = _strings(fixture["expected_reason_classes"], "expected_reason_classes")
    assert reasons
    assert len(reasons) == len(set(reasons))
    assert set(reasons) == timeline_reasons


def test_zone_model_phase_one_fixture_set_is_complete() -> None:
    fixture_paths = sorted(FIXTURE_DIRECTORY.glob("*.json"))
    assert {path.name for path in fixture_paths} == EXPECTED_FIXTURES
    scenario_ids = [
        json.loads(path.read_text())["scenario_id"] for path in fixture_paths
    ]
    assert len(scenario_ids) == len(set(scenario_ids))


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIRECTORY.glob("*.json")))
def test_zone_model_phase_one_fixture_schema(fixture_path: Path) -> None:
    requirement_ids = set(REQUIREMENT_PATTERN.findall(SPECIFICATION_PATH.read_text()))
    assert requirement_ids
    _validate_fixture(fixture_path, requirement_ids)
