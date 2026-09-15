from __future__ import annotations

import json
from copy import deepcopy
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


def _t05_supported_transition_retains_without_age_warning(
    fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    """Named HEALTH001/003 + PATH002 equivalent for synthetic T05, approved Sep13.

    The archived JSON documents the old 60s warning and 10min timer-only OFF.
    Preserve its inputs, timestamps, topology, initial state and original test ID.
    Only those two superseded expectations change: a supported endpoint does not
    warn from age or release from time. The unsupported warning inverse below
    retains positive diagnostic coverage using the same map and hallway input.
    """
    assert fixture["scenario_id"] == "T05-stuck-transition-degrades"
    assert fixture["source"]["kind"] == "synthetic_target_contract"
    timeline: list[dict[str, Any]] = deepcopy(fixture["expected_public_timeline"])
    assert timeline[1]["at"] == "2026-07-18T16:01:02Z"
    assert timeline[1]["health_changes"] == {"hallway": True}
    assert timeline[2]["at"] == "2026-07-18T16:10:00Z"
    assert timeline[2]["active_changes"] == {"hallway": False}
    timeline[1]["health_changes"] = {"hallway": False}
    timeline[2]["active_changes"] = {}
    return timeline


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
    supported_transition = fixture["scenario_id"] == "T05-stuck-transition-degrades"
    timeline = (
        _t05_supported_transition_retains_without_age_warning(fixture)
        if supported_transition else fixture["expected_public_timeline"]
    )
    expected_by_at = {
        _at(item["at"]): item for item in timeline
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
        if supported_transition:
            # Unlike the generic legacy trace rule, no extra transition OFF is
            # permitted: every original post-acquisition checkpoint retains ON.
            assert active_changes == expected["active_changes"]
            assert result.snapshot.reliability_warning_occurrences == ()
            assert next(
                state for state in result.snapshot.policy_states
                if state.zone == "hallway"
            ).active


@pytest.mark.target_model
def test_t05_unsupported_transition_warns_at_600_without_activation() -> None:
    """Synthetic HEALTH001/003 inverse: omit only T05's supporting entry ON.

    This is not another incident or a changed replay. Keep its map/count and
    hallway ON occurrence, then check the approved unsupported warning frontier.
    """
    fixture = json.loads(
        (FIXTURE_DIR / "t05_stuck_transition_degrades.json").read_text()
    )
    predictive_map = _fixture_map(fixture)
    engine = ZoneModelEngine(
        predictive_map, fixture["authoritative_count"],
        _at(fixture["inputs"][0]["event_at"]),
    )
    hallway_input = fixture["inputs"][1]
    on_at = _at(hallway_input["event_at"])
    entity = fixture["topology"]["nodes"][hallway_input["node_id"]]["entity_id"]
    result = engine.observe(SensorInput(entity, hallway_input["state"], on_at))
    assert result.policy_events == ()
    before = engine.advance(on_at + timedelta(seconds=599))
    assert before.snapshot.reliability_warning_occurrences == ()
    assert before.policy_events == ()
    for seconds in (600, 610):
        result = engine.advance(on_at + timedelta(seconds=seconds))
        warning, = result.snapshot.reliability_warning_occurrences
        assert (warning.node_id, warning.kind, warning.reason) == (
            "hallway_motion", "suspected_stuck", "assertion_timeout",
        )
        assert warning.first_observed_at == on_at + timedelta(seconds=600)
        assert warning.cleared_at is None
        assert all(not state.active for state in result.snapshot.policy_states)
        assert result.policy_events == ()


@pytest.mark.target_model
def test_physical_press_does_not_bypass_authoritative_count_zero() -> None:
    now = datetime(2026, 8, 22, 8, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "room_interaction": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "entities": {
                        "interaction_scene_001": "event.room_scene_001"
                    },
                }
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 0, now)

    result = engine.observe(
        SensorInput("event.room_scene_001", "pressed", now + timedelta(seconds=1))
    )

    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    )
    assert result.disposition == "accepted_interaction"
    assert policy.active is False
    assert not any(event.kind == "acquired" for event in result.policy_events)
