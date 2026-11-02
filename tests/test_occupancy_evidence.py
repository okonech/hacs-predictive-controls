"""Synthetic PATH009/010 qualification, separate from frozen incident streams."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    OccupancyEvidence,
    OccupancyObservation,
    SensorInput,
    ZoneBeliefState,
)
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario


def at(seconds: float) -> datetime:
    return datetime(2026, 11, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def evidence_map(*, shared_head_zone: bool = False) -> PredictiveMap:
    neighbors = {
        "a": ["b"], "b": ["a", "room", "x"], "room": ["b"],
        "x": ["b", "y"], "y": ["x", "z"], "z": ["y", "w"], "w": ["z"],
        "d": ["e"], "e": ["d", "f"], "f": ["e"],
    }
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "zone": "outside" if shared_head_zone and node in {"w", "f"} else node,
            "role": "room_occupancy" if node == "room" else "transition_gate",
            "occupancy_behavior": "sticky" if node == "room" else "transient",
            "entities": {
                "mmwave" if node == "room" else "motion": f"binary_sensor.{node}",
            },
            "adjacent": peers,
        } for node, peers in neighbors.items()
    }})


def room_belief(replay: RuntimeReplay) -> ZoneBeliefState:
    return next(state for state in replay.inference_snapshot().belief_states
                if state.zone == "room")


def record(replay: RuntimeReplay) -> OccupancyEvidence:
    result = room_belief(replay).occupancy_evidence
    assert result is not None
    return result


def ambiguous(replay: RuntimeReplay) -> None:
    for seconds, node in enumerate(("a", "b", "room", "x", "y", "z")):
        replay.send(f"binary_sensor.{node}", "on", at(seconds))
    replay.send("binary_sensor.w", "on", at(5.5))
    replay.send("binary_sensor.room", "off", at(6))
    replay.advance(at(16))
    assert replay.view().active("room")
    assert not room_belief(replay).physical_hold


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("restart", (False, True))
@pytest.mark.parametrize("shared_head_zone", (False, True))
def test_count_complete_public_release_and_committed_restore(
    count: int, restart: bool, shared_head_zone: bool,
) -> None:
    mapping = evidence_map(shared_head_zone=shared_head_zone)
    with RuntimeScenario(at(0)) as scenario:
        live = scenario.create(mapping, count)
        ambiguous(live)
        if count == 2:
            assert record(live).resolved_at is None
            assert all(
                visit.node_id != "room"
                for path in live.inference_snapshot().selected_paths
                if path is not None for visit in path.occurrences
            )
            if restart:
                restored = scenario.create(mapping, count)
                restored.restore(live.checkpoint())
                assert restored.inference_snapshot() == live.inference_snapshot()
                live = restored
            for seconds, node in ((20, "d"), (21, "e"), (22, "f")):
                live.send(f"binary_sensor.{node}", "on", at(seconds))
            assert record(live).resolved_at == at(22)
            if shared_head_zone:
                assert {path.endpoint.zone
                        for path in live.inference_snapshot().selected_paths
                        if path is not None} == {"outside"}
        else:
            assert record(live).resolved_at == at(5)
        assert record(live).resolution_kind == "count_complete"
        saved = live.checkpoint()
        if restart:
            restored = scenario.create(mapping, count)
            restored.restore(saved)
            assert restored.inference_snapshot() == live.inference_snapshot()
            live = restored
        live.send("binary_sensor.w", "unknown", at(23))
        live.send("binary_sensor.f", "unknown", at(24))
        assert record(live).resolution_kind == "count_complete"
        live.advance(at(142))
        assert live.view().active("room")
        live.advance(at(1000))
        assert not live.view().active("room")
        edges = live.edges_for("room")
        assert sum(not edge.active for edge in edges) == 1
        assert edges[-1].at > at(142)


@pytest.mark.parametrize("failure", ("unlocated", "unknown", "expired"))
def test_incomplete_or_untrusted_outside_proof_retains(failure: str) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 2)
        ambiguous(replay)
        offset = 0
        if failure == "unknown":
            replay.send("binary_sensor.w", "unknown", at(17))
        if failure == "expired":
            offset = 1000
        if failure != "unlocated":
            for seconds, node in ((20, "d"), (21, "e"), (22, "f")):
                replay.send(f"binary_sensor.{node}", "on", at(seconds + offset))
        replay.advance(at(2000))
        assert record(replay).resolved_at is None
        assert replay.edges_for("room") == (ActiveEdge(at(2), "room", True),)
        restored = scenario.create(evidence_map(), 2)
        restored.restore(replay.checkpoint())
        assert restored.inference_snapshot() == replay.inference_snapshot()


def test_direct_departure_uses_latest_not_earlier_source() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 2)
        for seconds, node in enumerate(("a", "b", "room")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        replay.send("binary_sensor.room", "off", at(3))
        replay.advance(at(13))
        assert record(replay).resolved_at is None
        replay.send("binary_sensor.b", "off", at(14))
        replay.advance(at(19))
        replay.send("binary_sensor.b", "on", at(20))
        assert record(replay).resolution_kind == "direct_departure"
        assert record(replay).resolved_at == at(20)
        replay.advance(at(1000))
        assert not replay.view().active("room")


def test_count_changes_do_not_resolve_and_zero_clears() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 2)
        ambiguous(replay)
        original = record(replay)
        replay.send("sensor.replay_people", "1", at(20))
        assert record(replay) == original
        replay.send("sensor.replay_people", "2", at(21))
        assert record(replay) == original
        replay.send("sensor.replay_people", "0", at(22))
        assert room_belief(replay).occupancy_evidence is None
        assert not replay.view().active("room")
        replay.send("sensor.replay_people", "2", at(23))
        assert room_belief(replay).occupancy_evidence is None
        assert not replay.view().active("room")


def test_restore_rejects_reused_generation_at_different_occurrence() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 2)
        for seconds, node in enumerate(("a", "b", "room")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        replay.send("binary_sensor.room", "off", at(3))
        replay.advance(at(13))
        replay.send("binary_sensor.room", "on", at(20))
        original = replay.checkpoint()
        restore_target_state(replay.map, original, at(20))
        corrupted = json.loads(json.dumps(original))
        raw = next(item for item in corrupted["snapshot"]["belief_states"]
                   if item["zone"] == "room")["occupancy_evidence"]
        assert raw["admission"]["at"] == at(2).isoformat()
        assert raw["latest"]["at"] == at(20).isoformat()
        raw["latest"]["episode_id"] = f"room:1:{at(20).isoformat()}"
        with pytest.raises(ValueError, match="Occupancy"):
            restore_target_state(replay.map, corrupted, at(20))
        assert replay.checkpoint() == original


def observation(node: str = "room", generation: int = 1,
                seconds: float = 2) -> OccupancyObservation:
    return OccupancyObservation(
        node, f"{node}:{generation}:{at(seconds).isoformat()}", "positive", at(seconds),
    )


@pytest.mark.parametrize(("field", "value"), (
    ("at", None), ("at", at(2).replace(tzinfo=None)),
    ("kind", "interaction"), ("node_id", "other"),
    ("episode_id", "room:1:invalid"),
))
def test_observation_constructor_rejects_malformed_fields(
    field: str, value: object,
) -> None:
    fields: dict[str, object] = {
        "node_id": "room", "episode_id": observation().episode_id,
        "kind": "positive", "at": at(2),
    }
    fields[field] = value
    with pytest.raises(ValueError):
        OccupancyObservation(
            cast(str, fields["node_id"]), cast(str, fields["episode_id"]),
            cast(str, fields["kind"]), cast(datetime, fields["at"]),
        )


@pytest.mark.parametrize(("field", "value"), (
    ("admission", None), ("latest", None),
    ("latest", observation("room", 1, 3)),
    ("admission", observation(generation=2)),
    ("latest", observation("other", 1, 1)),
    ("authorization_reason", "local_interaction"),
    ("admission_probability", True), ("admission_probability", "0.8"),
    ("admission_probability", 0.0), ("admission_probability", 1.0),
    ("admission_probability", float("nan")),
    ("resolved_at", at(3)), ("resolution_kind", "count_complete"),
))
def test_evidence_constructor_rejects_malformed_fields(
    field: str, value: object,
) -> None:
    fields: dict[str, object] = {
        "admission": observation(), "latest": observation(),
        "authorization_reason": "selected_path", "admission_probability": 0.8,
        "resolved_at": None, "resolution_kind": None,
    }
    fields[field] = value
    with pytest.raises(ValueError):
        OccupancyEvidence(
            cast(OccupancyObservation, fields["admission"]),
            cast(OccupancyObservation, fields["latest"]),
            cast(str, fields["authorization_reason"]),
            cast(float, fields["admission_probability"]),
            cast(datetime | None, fields["resolved_at"]),
            cast(str | None, fields["resolution_kind"]),
        )


@pytest.mark.parametrize(("resolution", "kind"), (
    ("not a datetime", "count_complete"),
    (at(3).replace(tzinfo=None), "count_complete"),
    (at(1), "direct_departure"), (at(3), "invented"),
))
def test_resolution_constructor_rejects_malformed_pair(
    resolution: object, kind: str,
) -> None:
    with pytest.raises(ValueError):
        OccupancyEvidence(
            observation(), observation(), "selected_path", 0.8,
            cast(datetime, resolution), kind,
        )


def test_retention_lifetime_and_equal_time_generation_advance() -> None:
    first = observation()
    latest = observation(generation=2)
    evidence = OccupancyEvidence(first, latest, "selected_path", 0.8)
    assert evidence.retains(at(1), first.episode_id)
    assert evidence.retains(at(2), latest.episode_id)
    assert not evidence.retains(at(2), first.episode_id)
    assert not evidence.retains(at(3), latest.episode_id)
    assert not evidence.retains(None, None)
    assert not replace(evidence, resolved_at=at(3),
                       resolution_kind="count_complete").retains(at(1), None)
    belief = ZoneBeliefState("room", "stay_presence", 0.0, at(2), "asserted")
    with pytest.raises(ValueError, match="Occupancy evidence has invalid type"):
        replace(belief, occupancy_evidence=cast(OccupancyEvidence, "invalid"))


@pytest.mark.parametrize("mutation", (
    "inventory_missing", "inventory_duplicate", "field_missing", "record_extra",
    "observation_extra", "admission_unqualified", "wrong_zone", "future_latest",
    "future_resolution",
))
def test_malformed_record_restore_is_atomic(mutation: str) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 2)
        for seconds, node in enumerate(("a", "b", "room")):
            replay.send(f"binary_sensor.{node}", "on", at(seconds))
        original = replay.checkpoint()
        invalid = json.loads(json.dumps(original))
        rows = invalid["snapshot"]["belief_states"]
        raw = next(row for row in rows if row["zone"] == "room")
        occupancy = raw["occupancy_evidence"]
        if mutation == "inventory_missing":
            rows.pop()
        elif mutation == "inventory_duplicate":
            rows[0]["zone"] = rows[1]["zone"]
        elif mutation == "field_missing":
            del raw["occupancy_evidence"]
        elif mutation == "record_extra":
            occupancy["extra"] = True
        elif mutation == "observation_extra":
            occupancy["latest"]["extra"] = True
        elif mutation == "admission_unqualified":
            occupancy["admission_probability"] = 0.1
        elif mutation == "wrong_zone":
            occupancy["admission"] = {
                "node_id": "a", "episode_id": observation("a", 1, 0).episode_id,
                "kind": "positive", "at": at(0).isoformat(),
            }
        elif mutation == "future_latest":
            occupancy["latest"]["at"] = at(3).isoformat()
            occupancy["latest"]["episode_id"] = observation("room", 2, 3).episode_id
        else:
            occupancy["resolved_at"] = at(3).isoformat()
            occupancy["resolution_kind"] = "count_complete"
        incoming = deepcopy(invalid)
        public = (replay.view(), tuple(replay.edges), replay.writes, replay.deliveries)
        with pytest.raises(ValueError):
            restore_target_state(replay.map, invalid, at(2))
        with pytest.raises(AssertionError, match="replay checkpoint"):
            replay.restore(invalid)
        assert invalid == incoming
        assert replay.checkpoint() == original
        assert (replay.view(), tuple(replay.edges), replay.writes,
                replay.deliveries) == public


def test_real_local_support_rearms_without_recreating_movement() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(evidence_map(), 1)
        ambiguous(replay)
        before = record(replay)
        paths = replay.inference_snapshot().selected_paths
        assert before.resolved_at == at(5)
        replay.send("binary_sensor.room", "on", at(20))
        current = record(replay)
        assert current.admission == before.admission
        assert current.latest.at == at(20) and current.resolved_at is None
        assert replay.inference_snapshot().selected_paths == paths
        replay.advance(at(2000))
        assert replay.edges_for("room") == (ActiveEdge(at(2), "room", True),)


def test_count_complete_trust_boundary_and_zero_defense() -> None:
    engine = ZoneModelEngine(evidence_map(), 1, at(0))
    for seconds, node in enumerate(("a", "b", "room", "x", "y", "z", "w")):
        engine.observe(SensorInput(f"binary_sensor.{node}", "on", at(seconds)))
    head = next(state for state in engine.snapshot.episode_states
                if state.node_id == "w")
    assert head.assertion_trust_until is not None
    expiry = head.assertion_trust_until
    assert engine._count_complete_outside("room", at(2), expiry - timedelta(
        microseconds=1,
    ))
    assert not engine._count_complete_outside("room", at(2), expiry)
    empty = ZoneModelEngine(evidence_map(), 0, at(0))
    assert not empty._count_complete_outside("room", at(0), at(0))
