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
def test_inc_2026_08_20_mmwave_room_reassertion_retains_active() -> None:
    incident_at = datetime(2026, 8, 20, 17, 9, 40, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bottom"},
                    "adjacent": ["top"],
                },
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["bottom", "room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.room"},
                    "adjacent": ["top"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 2, incident_at)
    observations = []
    for entity_id, state, event_at in (
        ("binary_sensor.bottom", "on", "2026-08-20T17:09:49.026000+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:09:53.153332+00:00"),
        ("binary_sensor.room", "on", "2026-08-20T17:09:59.684850+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:12.091060+00:00"),
        ("binary_sensor.room", "off", "2026-08-20T17:10:19.851787+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:10:23.948782+00:00"),
        ("binary_sensor.room", "on", "2026-08-20T17:10:27.919616+00:00"),
    ):
        observations.append(
            engine.observe(
                SensorInput(entity_id, state, datetime.fromisoformat(event_at))
            )
        )

    final = engine.advance(datetime(2026, 8, 20, 17, 12, tzinfo=UTC))
    room_policy = next(
        state for state in final.snapshot.policy_states if state.zone == "room"
    )
    room_episode = next(
        state for state in final.snapshot.episode_states if state.zone == "room"
    )

    assert any(
        event.zone == "room" and event.kind == "acquired"
        for event in observations[2].policy_events
    )
    assert any(
        event.zone == "room" and event.kind == "refreshed"
        for event in observations[-1].policy_events
    )
    assert room_episode.profile_name == "stay_presence"
    assert room_episode.cadence_warning is False
    assert room_policy.active is True
    assert not any(
        event.zone == "room" and event.kind == "released"
        for observation in (*observations, final)
        for event in observation.policy_events
    )


@pytest.mark.target_model
def test_inc_2026_08_20_stale_gym_assertion_releases_normally() -> None:
    incident_at = datetime(2026, 8, 20, 17, 0, 30, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "master_entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.master_entrance"},
                    "adjacent": ["top"],
                },
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.top"},
                    "adjacent": [
                        "master_entrance",
                        "shaila_office",
                        "bottom",
                        "alex_office",
                    ],
                },
                "shaila_office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.shaila_office"},
                    "adjacent": ["top"],
                },
                "gym": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.gym"},
                    "adjacent": ["dining"],
                },
                "foyer": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.foyer"},
                    "adjacent": ["dining", "bottom"],
                },
                "dining": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.dining"},
                    "adjacent": ["foyer", "kitchen", "gym"],
                },
                "kitchen": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.kitchen"},
                    "adjacent": ["dining"],
                },
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.bottom"},
                    "adjacent": ["foyer", "top"],
                },
                "alex_office": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.alex_office"},
                    "adjacent": ["top"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 2, incident_at)
    for entity_id, state, event_at in (
        ("binary_sensor.master_entrance", "on", "2026-08-20T17:00:33.807835+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:00:34.599475+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:00:41.725395+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:00:46.629097+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:03:17.804091+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:03:35.927390+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:04:30.862924+00:00"),
        ("binary_sensor.gym", "on", "2026-08-20T17:06:39.497066+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:07:44.661861+00:00"),
        ("binary_sensor.shaila_office", "off", "2026-08-20T17:08:15.062751+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:08:20.189974+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:09.242269+00:00"),
        ("binary_sensor.dining", "on", "2026-08-20T17:09:09.656182+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:09:13.675459+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:09:25.715140+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:30.817675+00:00"),
        ("binary_sensor.kitchen", "off", "2026-08-20T17:09:36.007613+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:09:40.741138+00:00"),
        ("binary_sensor.foyer", "on", "2026-08-20T17:09:45.986312+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:09:48.629758+00:00"),
        ("binary_sensor.bottom", "on", "2026-08-20T17:09:49.026000+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:09:53.153332+00:00"),
        ("binary_sensor.dining", "off", "2026-08-20T17:09:57.848001+00:00"),
        ("binary_sensor.alex_office", "on", "2026-08-20T17:09:59.684850+00:00"),
        ("binary_sensor.foyer", "off", "2026-08-20T17:10:01.671418+00:00"),
        ("binary_sensor.bottom", "off", "2026-08-20T17:10:05.522066+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:12.091060+00:00"),
        ("binary_sensor.alex_office", "off", "2026-08-20T17:10:19.851787+00:00"),
        ("binary_sensor.top", "on", "2026-08-20T17:10:23.948782+00:00"),
        ("binary_sensor.alex_office", "on", "2026-08-20T17:10:27.919616+00:00"),
        ("binary_sensor.top", "off", "2026-08-20T17:10:34.562183+00:00"),
        ("binary_sensor.kitchen", "off", "2026-08-20T17:10:38.013203+00:00"),
        ("binary_sensor.shaila_office", "on", "2026-08-20T17:10:42.146287+00:00"),
        ("binary_sensor.kitchen", "on", "2026-08-20T17:10:48.139304+00:00"),
    ):
        engine.observe(SensorInput(entity_id, state, datetime.fromisoformat(event_at)))

    result = engine.advance(datetime(2026, 8, 20, 17, 11, 14, tzinfo=UTC))
    gym_episode = next(
        state for state in result.snapshot.episode_states if state.zone == "gym"
    )
    shaila_policy = next(
        state
        for state in result.snapshot.policy_states
        if state.zone == "shaila_office"
    )
    alex_policy = next(
        state for state in result.snapshot.policy_states if state.zone == "alex_office"
    )
    gym_policy = next(
        state for state in result.snapshot.policy_states if state.zone == "gym"
    )

    assert shaila_policy.active
    assert alex_policy.active
    assert gym_policy.active is False
    assert gym_episode.health_warning
    assert gym_episode.degradation_reason == "count_conflict"
    assert not any(
        event.zone == "gym" and event.kind == "released"
        for event in result.policy_events
    )

    decayed = engine.advance(datetime(2026, 8, 20, 18, 0, tzinfo=UTC))
    gym_belief = next(
        state for state in decayed.snapshot.belief_states if state.zone == "gym"
    )
    gym_events = tuple(
        event
        for event in (*result.policy_events, *decayed.policy_events)
        if event.zone == "gym"
    )
    assert gym_belief.probability < 0.3
    assert not gym_events


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
