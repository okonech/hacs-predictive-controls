"""Synthetic public cutover proofs, not additional production incident captures.

REQ-PATH-001/002, REQ-PATH-STATE-001 and REQ-HEALTH-001..003: expose bounded
selection including U, report only qualified current warnings, and keep accepted
callback failures persistable. Existing incident inputs/expectations are untouched.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
    TrackerDiagnostics,
)
from custom_components.predictive_controls.status import (
    runtime_status_payload,
    tracker_diagnostics_payload,
)
from custom_components.predictive_controls.zone_model.path_health import PathHealthState
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPath,
    SelectedSource,
)
from tests.runtime_replay import RuntimeReplay, RuntimeScenario


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 12, tzinfo=UTC) + timedelta(seconds=seconds)


def graph() -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"mmwave": f"binary_sensor.{node}"},
            "adjacent": neighbors, "initial_weight": 1.0,
        }
        for node, neighbors in (
            ("a", ["b"]), ("b", ["a", "c"]), ("c", ["b", "d", "f"]),
            ("d", ["c", "e"]), ("e", ["d"]), ("f", ["c"]), ("g", []),
        )
    }})


def payload(replay: RuntimeReplay) -> dict[str, Any]:
    result = runtime_status_payload(replay.runtime)["occupancy_diagnostics"]
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert isinstance(result, dict)
    return result


@contextmanager
def problem_sensor(
    replay: RuntimeReplay,
) -> Iterator[tuple[Any, list[tuple[datetime, bool]]]]:
    """Capture the real Problem entity's dispatcher-driven public writes."""
    scenario = replay.scenario
    entity = scenario.binary_module.PredictiveControlsProblemSensor(
        replay.runtime, "diagnostics",
    )
    entity.hass = replay.hass
    writes: list[tuple[datetime, bool]] = []
    scenario.patch.setattr(entity, "async_write_ha_state", lambda: writes.append(
        (scenario.clock.now, bool(entity.is_on)),
    ))
    asyncio.run(entity.async_added_to_hass())
    try:
        yield entity, writes
    finally:
        for remove in entity.remove_callbacks:
            remove()


@pytest.mark.parametrize("count", (0, 1, 2))
def test_selected_diagnostics_defaults_and_explicit_unlocated_slots(count: int) -> None:
    appended = fields(TrackerDiagnostics)[-3:]
    assert [field.name for field in appended] == [
        "selected_paths", "selected_sources", "path_health",
    ]
    assert all(field.default == () for field in appended)
    tracker = OccupancyTracker(graph(), TrackerConfig(count))
    assert tracker.diagnostics.selected_paths == ()
    assert tracker.diagnostics.selected_sources == ()
    assert tracker.diagnostics.path_health == ()
    tracker.ensure_state(at(0))
    diagnostics = tracker.diagnostics
    assert diagnostics.selected_paths == (None,) * count
    assert len(diagnostics.selected_sources) == len(graph().nodes)
    assert all(
        isinstance(item, SelectedSource) for item in diagnostics.selected_sources
    )
    assert all(isinstance(item, PathHealthState) for item in diagnostics.path_health)
    result = tracker_diagnostics_payload(diagnostics)
    assert result["selected_paths"] == [None] * count
    assert result["unlocated_count"] == count
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("count", (1, 2))
def test_selected_path_projection_bounds_branch_and_source_witness(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        for seconds, node in enumerate(("a", "b", "c", "d", "e", "f")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        diagnostics = replay.runtime.confidence.diagnostics
        selected = diagnostics.selected_paths[0]
        assert isinstance(selected, SelectedPath)
        result = payload(replay)
        path = result["selected_paths"][0]
        assert len(result["selected_paths"]) == count
        assert result["selected_paths"][1:] == [None] * (count - 1)
        assert result["unlocated_count"] == count - 1
        assert [visit["node_id"] for visit in path["visits"]] == ["c", "d", "e", "f"]
        assert [visit["node_id"] for visit in path["route"]] == ["b", "c", "f"]
        for key in ("route", "visits"):
            assert 1 <= len(path[key]) <= 4
            assert all(set(visit) == {
                "node_id", "zone", "episode_id", "at", "kind", "branch_active",
            } for visit in path[key])
        assert path["endpoint"] == path["route"][-1]
        assert path["endpoint_eligible"] is True
        assert path["updated_at"] == path["spatial_at"] == at(5).isoformat()
        assert path["covered_node_ids"] == path["eligible_node_ids"] == ["b", "c", "f"]
        assert path["covered_zones"] == ["b", "c", "f"]
        authorization = result["authorizations"][-1]
        assert authorization["reason"] == "selected_path"
        assert authorization["source_token_ids"] == []
        assert authorization["selected_source_episode_ids"] == [
            path["route"][-2]["episode_id"],
        ]
        source = next(
            row for row in result["selected_sources"] if row["node_id"] == "a"
        )
        assert source == {
            "node_id": "a", "episode_id": f"a:1:{at(0).isoformat()}",
            "at": at(0).isoformat(), "origin": "ordinary", "consumed": True,
        }

        replay.send("binary_sensor.b", "off", at(6))
        replay.send("binary_sensor.f", "off", at(7))
        replay.advance(at(60))
        result = payload(replay)
        path = result["selected_paths"][0]
        assert [visit["node_id"] for visit in path["route"]] == ["b", "c", "f"]
        assert [visit["branch_active"] for visit in path["route"]] == [
            False, True, False,
        ]
        assert path["endpoint_eligible"] is True
        assert path["eligible_node_ids"] == path["covered_node_ids"] == ["c", "f"]
        assert next(row for row in result["path_health"] if row["node_id"] == "f")[
            "phase"
        ] == "off"
        before = replay.checkpoint()
        assert payload(replay) == result
        assert replay.checkpoint() == before  # Projection never mutates inference.


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("recovery", ("off", "unknown", "unavailable", "support"))
def test_problem_unsupported_on_threshold_and_recovery(
    count: int, recovery: str,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        with problem_sensor(replay) as (entity, writes):
            replay.send("binary_sensor.a", "on", at(0))
            replay.advance(at(599))
            assert not entity.is_on
            assert payload(replay)["health_warnings"] == []
            assert writes == []
            replay.advance(at(600))
            assert entity.is_on
            assert writes == [(at(600), True)]
            assert replay.runtime.problem_reasons == ("sensor_health_degraded",)
            assert replay.runtime.problem_sources == ("physical_sensor_episode",)
            assert entity.extra_state_attributes["explanation"] == (
                "Active problems: sensor_health_degraded"
            )
            replay.advance(at(601))
            result = payload(replay)
            assert result["health_warnings"] == ["a"]
            assert result["reliability_warnings"][0]["kind"] == "suspected_stuck"
            occurrence = result["reliability_warning_occurrences"][0]
            assert occurrence["first_observed_at"] == at(600).isoformat()
            assert not any(row["health_warning"] for row in result["episodes"])
            assert not replay.edges
            replay.send(
                "binary_sensor.b" if recovery == "support" else "binary_sensor.a",
                "on" if recovery == "support" else recovery, at(602),
            )
            result = payload(replay)
            assert not entity.is_on
            assert writes[-1] == (at(602), False)
            assert replay.runtime.problem_reasons == ()
            assert replay.runtime.problem_sources == ()
            assert result["health_warnings"] == result["reliability_warnings"] == []
            assert result["reliability_warning_occurrences"][0]["cleared_at"] == (
                at(602).isoformat()
            )
            if recovery != "support":
                assert not replay.edges


@pytest.mark.parametrize("on_at, published_at", ((0, 600), (1, 605)))
def test_problem_warning_publishes_and_saves_at_next_registered_timer(
    on_at: int, published_at: int,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1)
        with problem_sensor(replay) as (_entity, writes):
            replay.send("binary_sensor.a", "on", at(on_at))
            saves: list[datetime] = []
            scenario.patch.setattr(
                replay.runtime, "schedule_transition_count_save",
                lambda: saves.append(scenario.clock.now),
            )
            replay.advance(at(published_at - 1))
            assert writes == []
            saves.clear()
            replay.advance(at(published_at))
            assert writes == [(at(published_at), True)]
            assert saves == [at(published_at)]
            assert payload(replay)["reliability_warning_occurrences"][0][
                "first_observed_at"
            ] == at(on_at + 600).isoformat()
            saves.clear()
            replay.advance(at(720))
            assert saves == []  # Advancing last_observed_at is not a warning edge.


@pytest.mark.parametrize("count", (0, 1, 2))
def test_problem_six_quick_cycles_only_and_rolling_recovery(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        with problem_sensor(replay) as (entity, writes):
            for cycle in range(6):
                replay.send("binary_sensor.a", "on", at(cycle * 10))
                assert not entity.is_on
                replay.send("binary_sensor.a", "off", at(cycle * 10 + 1))
                assert bool(entity.is_on) is (cycle == 5)
                result = payload(replay)
                assert result["health_warnings"] == []  # Stuck-only legacy summary.
                if cycle < 5:
                    assert result["reliability_warnings"] == []
                    assert writes == []
            assert writes == [(at(51), True)]
            assert replay.runtime.problem_reasons == ("sensor_health_degraded",)
            assert result["reliability_warnings"][0]["kind"] == "flapping"
            assert result["path_health"][0]["completed_cycles"] == [
                at(cycle * 10 + 1).isoformat() for cycle in range(6)
            ]
            replay.advance(at(3600))
            assert entity.is_on
            replay.advance(at(3605))
            assert not entity.is_on
            assert writes == [(at(51), True), (at(3605), False)]
            result = payload(replay)
            assert result["reliability_warnings"] == []
            assert result["reliability_warning_occurrences"][0]["cleared_at"] == (
                at(3601).isoformat()
            )
            assert not replay.edges


@pytest.mark.parametrize("count", (1, 2))
def test_selected_and_health_projection_survives_matching_restore(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count)
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(1))
        replay.send("binary_sensor.g", "on", at(2))
        replay.advance(at(605))
        before = payload(replay)
        restored = scenario.create(graph(), count)
        assert payload(restored)["selected_paths"] == [None] * count
        restored.restore(json.loads(json.dumps(replay.checkpoint())))
        keys = (
            "selected_paths", "selected_sources", "path_health", "unlocated_count",
            "health_warnings", "reliability_warnings",
            "reliability_warning_occurrences",
        )
        after = payload(restored)
        assert {key: after[key] for key in keys} == {key: before[key] for key in keys}
        assert restored.runtime.problem_reasons == replay.runtime.problem_reasons == (
            "sensor_health_degraded",
        )
        for branch in (replay, restored):
            branch.send("binary_sensor.g", "off", at(606))
        after = payload(restored)
        before = payload(replay)
        assert {key: after[key] for key in keys} == {key: before[key] for key in keys}
        assert restored.runtime.problem_reasons == ()


def test_legacy_episode_warning_flags_do_not_leak_into_current_summary() -> None:
    tracker = OccupancyTracker(graph(), TrackerConfig(1))
    tracker.ensure_state(at(0))
    diagnostics = tracker.diagnostics
    # Deliberately inconsistent projection-only fixture, never restored as inference.
    old_flags = replace(diagnostics, episode_states=tuple(
        replace(state, health_warning=True)
        for state in diagnostics.episode_states
    ))
    assert tracker_diagnostics_payload(old_flags)["health_warnings"] == []


@pytest.mark.parametrize("failure_call", (1, 2))
def test_accepted_publication_failure_rearms_and_saves(failure_call: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 2)
        replay.send("binary_sensor.a", "on", at(0))
        calls: list[str] = []
        saved: list[dict[str, object]] = []
        original = replay.runtime._dispatch_update
        publications = 0

        def dispatch() -> None:
            nonlocal publications
            publications += 1
            # A subscriber can serialize a coherent, strictly restorable frontier.
            current = replay.checkpoint()
            snapshot = restore_target_state(graph(), current, at(1)).snapshot
            assert snapshot.selected_paths[0] is not None
            assert snapshot.selected_paths[0].endpoint.node_id == "b"
            if publications == failure_call:
                raise RuntimeError("publication failed after acceptance")
            original()

        def rearm(now: datetime) -> None:
            assert now == at(1)
            calls.append("rearm")

        def save() -> None:
            calls.append("save")
            saved.append(replay.checkpoint())

        scenario.patch.setattr(replay.runtime, "_dispatch_update", dispatch)
        scenario.patch.setattr(replay.runtime, "_schedule_prediction_deadline", rearm)
        scenario.patch.setattr(replay.runtime, "schedule_transition_count_save", save)
        with pytest.raises(RuntimeError, match="publication failed after acceptance"):
            replay.send("binary_sensor.b", "on", at(1))
        assert calls == ["rearm", "save"]
        assert len(saved) == 1
        snapshot = restore_target_state(graph(), saved[0], at(1)).snapshot
        assert snapshot.selected_paths[0] is not None
        assert snapshot.selected_paths[0].endpoint.node_id == "b"
        assert snapshot.selected_paths[1] is None
        policy = next(state for state in snapshot.policy_states if state.zone == "b")
        assert policy.active
