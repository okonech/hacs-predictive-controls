from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "zone_model"
FIXTURES = tuple(sorted(FIXTURE_DIR.glob("*.json")))
PROFILE_METADATA = {
    "transition_fast": ("transition_gate", "transient", "motion"),
    "stay_pir": ("room_occupancy", "sustained", "motion"),
    "stay_presence": ("anchor_sensor", "sticky", "presence"),
    "entry_boundary": ("boundary", "sustained", "motion"),
}


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _fixture_map(fixture: dict[str, Any]) -> PredictiveMap:
    nodes: dict[str, object] = {}
    for node_id, raw in fixture["topology"]["nodes"].items():
        role, behavior, signal = PROFILE_METADATA[raw["profile"]]
        nodes[node_id] = {
            "zone": raw["zone"],
            "role": role,
            "occupancy_behavior": behavior,
            "entities": {signal: raw["entity_id"]},
            "adjacent": raw["adjacent"],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


@pytest.mark.target_model
@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda path: path.stem)
def test_frozen_target_trace_matches_public_timeline(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text())
    predictive_map = _fixture_map(fixture)
    inputs = fixture["inputs"]
    bootstrap_at = min(_at(item["event_at"]) for item in inputs)
    engine = ZoneModelEngine(
        predictive_map,
        fixture["authoritative_count"],
        bootstrap_at,
    )
    entity_by_node = {
        node_id: raw["entity_id"]
        for node_id, raw in fixture["topology"]["nodes"].items()
    }
    expected_by_at = {
        _at(item["at"]): item for item in fixture["expected_public_timeline"]
    }

    for index, item in enumerate(inputs):
        event_at = _at(item["event_at"])
        received_at = _at(item["received_at"])
        if item["kind"] == "sensor":
            result = engine.observe(
                SensorInput(entity_by_node[item["node_id"]], item["state"], event_at),
                processing_at=received_at,
            )
        elif item["kind"] == "count":
            result = engine.observe_count(
                CountInput(
                    f"{fixture['scenario_id']}:count:{index}",
                    item["value"],
                    item.get("available", True),
                    event_at,
                ),
                processing_at=received_at,
            )
        else:
            result = engine.advance(event_at, processing_at=received_at)

        expected = expected_by_at.get(event_at)
        if expected is None:
            continue
        active_changes = {
            event.zone: event.kind == "acquired"
            for event in result.policy_events
            if event.kind in {"acquired", "released"}
        }
        arrivals = [
            {"zone": event.zone, "event_type": event.kind}
            for event in result.policy_events
            if event.kind in {"acquired", "refreshed"}
        ]
        current_health = {
            zone: any(
                state.zone == zone and state.health_warning
                for state in result.snapshot.episode_states
            )
            for zone in fixture["topology"]["zones"]
        }
        assert {
            zone: active_changes[zone] for zone in expected["active_changes"]
        } == expected["active_changes"]
        unexpected_changes = set(active_changes) - set(expected["active_changes"])
        assert all(
            not active_changes[zone]
            and any(
                raw["zone"] == zone and raw["profile"] == "transition_fast"
                for raw in fixture["topology"]["nodes"].values()
            )
            for zone in unexpected_changes
        )
        assert arrivals == expected["arrival_events"]
        assert {
            zone: current_health[zone] for zone in expected["health_changes"]
        } == expected["health_changes"]


@pytest.mark.target_model
@pytest.mark.parametrize(
    "incident_at",
    (
        datetime(2026, 7, 21, 6, 22, tzinfo=UTC),
        datetime(2026, 7, 21, 7, 33, tzinfo=UTC),
    ),
    ids=("2026-07-21-02-22-EDT", "2026-07-21-03-33-EDT"),
)
def test_inc_2026_07_21_isolated_master_closet_never_acquires(
    incident_at: datetime,
) -> None:
    """Freeze the two retained minute-precision production false activations."""
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "master_bedroom_entrance": {
                    "zone": "master_bedroom_entrance",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bedroom_entrance_pir_motion_"
                            "motion_detection"
                        )
                    },
                    "adjacent": ["master_bedroom_closet"],
                    "initial_weight": 0.8,
                },
                "master_bedroom_closet": {
                    "zone": "master_bedroom_closet",
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bedroom_closet_motion_"
                            "motion_detection"
                        )
                    },
                    "adjacent": [
                        "master_bedroom_entrance",
                        "master_bathroom_light_motion",
                    ],
                    "initial_weight": 0.8,
                },
                "master_bathroom_light_motion": {
                    "zone": "master_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "motion": (
                            "binary_sensor.master_bathroom_master_bathroom_"
                            "light_motion_motion_detection"
                        )
                    },
                    "adjacent": ["master_bedroom_closet"],
                    "initial_weight": 0.7,
                },
                "alex_office_approach": {
                    "zone": "alex_office_approach",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.alex_office_approach"},
                    "adjacent": ["alex_office_door"],
                },
                "alex_office_door": {
                    "zone": "alex_office_door",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.alex_office_door"},
                    "adjacent": ["alex_office_approach", "alex_office"],
                },
                "alex_office": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.alex_office"},
                    "adjacent": ["alex_office_door"],
                },
                "guest_bedroom_approach": {
                    "zone": "guest_bedroom_approach",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.guest_bedroom_approach"},
                    "adjacent": ["guest_bedroom_door"],
                },
                "guest_bedroom_door": {
                    "zone": "guest_bedroom_door",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.guest_bedroom_door"},
                    "adjacent": ["guest_bedroom_approach", "guest_bedroom"],
                },
                "guest_bedroom": {
                    "zone": "guest_bedroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.guest_bedroom"},
                    "adjacent": ["guest_bedroom_door"],
                },
            }
        }
    )
    engine = ZoneModelEngine(
        predictive_map,
        2,
        incident_at.replace(second=0) - timedelta(seconds=10),
    )
    observations = []
    for entity_id, offset in (
        ("binary_sensor.alex_office_approach", -10),
        ("binary_sensor.alex_office_door", -9),
        ("binary_sensor.alex_office", -8),
        ("binary_sensor.guest_bedroom_approach", -7),
        ("binary_sensor.guest_bedroom_door", -6),
        ("binary_sensor.guest_bedroom", -5),
    ):
        observations.append(
            engine.observe(
                SensorInput(
                    entity_id,
                    "on",
                    incident_at + timedelta(seconds=offset),
                )
            )
        )

    result = engine.observe(
        SensorInput(
            "binary_sensor.master_bedroom_closet_motion_motion_detection",
            "on",
            incident_at,
        )
    )
    observations.append(result)

    closet_state = next(
        state
        for state in result.snapshot.policy_states
        if state.zone == "master_bedroom_closet"
    )
    assert closet_state.active is False
    strong_fronts = result.snapshot.strong_fronts
    assert len(strong_fronts) == 2
    assert sum("alex_office" in front.zones for front in strong_fronts) == 1
    assert sum("guest_bedroom" in front.zones for front in strong_fronts) == 1
    assert not any(
        event.zone == "master_bedroom_closet" and event.kind == "acquired"
        for observation in observations
        for event in observation.policy_events
    )
    candidate = next(
        item
        for item in result.snapshot.pending_candidates
        if item.zone == "master_bedroom_closet"
    )
    expired = engine.advance(candidate.expires_at)
    assert not next(
        state
        for state in expired.snapshot.policy_states
        if state.zone == "master_bedroom_closet"
    ).active
    assert any(
        decision.zone == "master_bedroom_closet"
        and decision.reason == "untracked_expired"
        for decision in expired.policy_decisions
    )
