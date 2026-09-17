"""Synthetic selected-path cutover boundaries, not new production incidents.

Source: user test-only handoff on 2026-09-12 and independent review artifact
e7a3f717-c59f-468f-8161-3fdacd9a69cc/
call_6FWvehmHGMSxcI9UN9HdY7jK__vscode-1789016631596/content.txt, blockers 1-3.
Desired: fresh prior-branch return acquires before stable clear; a contradictory
displacement marker rejects strictly; startup OFF immediately revokes old branch
authority. Review observed missing A ON, accepted corrupt state, and false X ON.
Additional synthetic inverses cover startup ON/unknown/post-clear and all six
clear orders at counts 1/2. They are not additional user-reported light failures.
REQ-PATH-001..004, REQ-PATH-STATE-001, REQ-STATE-001/002/008/009. Real engine and
runtime APIs supply inference; only the existing fake HA clock/transport is used.
Public active writes prove control signals, not hardware actuation. Failures are
deliberately retained for handoff: no xfail, production fixes, or model patches.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import permutations
from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from custom_components.predictive_controls.zone_model.types import ZoneModelSnapshot
from tests.overlap_retirement_fixture import retired_prefix_inputs, retired_prefix_map
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 12, tzinfo=UTC) + timedelta(seconds=seconds)


@pytest.fixture
def predictive_map() -> PredictiveMap:
    """One local graph: A-B-C plus X adjacent only to A; no A-C shortcut."""
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"mmwave": f"binary_sensor.{node}"},
            "adjacent": neighbors, "initial_weight": 1.0,
        }
        for node, neighbors in (
            ("a", ["b", "x"]), ("b", ["a", "c"]),
            ("c", ["b"]), ("x", ["a"]),
        )
    }})


def walk_to_c(replay: RuntimeReplay) -> None:
    for seconds, node in enumerate(("a", "b", "c")):
        replay.send(f"binary_sensor.{node}", "on", at(seconds))
    assert replay.edges == [ActiveEdge(at(1), "b", True),
                            ActiveEdge(at(2), "c", True)]


def assert_one_retained_chain(snapshot: ZoneModelSnapshot, count: int) -> None:
    """Supplement public retention with no invented edge, visit, or occupant."""
    assert len(snapshot.selected_paths) == count
    assert snapshot.selected_paths[1:] == (None,) * (count - 1)
    path = snapshot.selected_paths[0]
    assert path is not None
    assert tuple(visit.node_id for visit in path.route) == ("a", "b", "c")
    assert tuple(visit.node_id for visit in path.visits) == ("a", "b", "c")
    assert tuple(visit.at for visit in path.route) == (at(0), at(1), at(2))
    assert path.endpoint.node_id == "c"
    assert path.spatial_at == path.updated_at == at(2)


def restored_startup(
    scenario: RuntimeScenario, predictive_map: PredictiveMap, count: int,
    a_state: str,
) -> RuntimeReplay:
    live = scenario.create(predictive_map, count)
    walk_to_c(live)
    payload = json.loads(json.dumps(live.checkpoint()))
    live.close()
    scenario.clock.advance(at(20))
    restored = scenario.create(predictive_map, count)
    # The harness initially starts an empty runtime. Stop its real subscriptions
    # before supplying raw HA levels and executing production restore -> start.
    asyncio.run(restored.runtime.async_stop())
    restored.hass.values.update({
        f"binary_sensor.{node}": SimpleNamespace(state=state)
        for node, state in (("a", a_state), ("b", "off"), ("c", "on"), ("x", "off"))
    })
    restored.restore(payload)
    restored.runtime.start()
    assert restored.normalized_inputs == []  # Startup is not a movement replay.
    assert scenario.clock.pending_count == 3
    assert restored.view().active("c")
    assert not restored.edges_for("a")
    assert not restored.edges_for("x")
    assert_one_retained_chain(restored.inference_snapshot(), count)
    return restored


@pytest.mark.parametrize("count", (1, 2))
def test_runtime_prior_branch_return_acquires_before_stable_clear(
    predictive_map: PredictiveMap, count: int,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(predictive_map, count)
        walk_to_c(replay)
        replay.send("binary_sensor.b", "off", at(3))
        replay.send("binary_sensor.a", "off", at(100))
        snapshot = replay.inference_snapshot()
        assert_one_retained_chain(snapshot, count)
        source = next(state for state in snapshot.episode_states
                  if state.node_id == "a")
        assert source.status == "clearing"
        assert source.clear_deadline == at(110)
        assert not replay.edges_for("a")
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)

        replay.send("binary_sensor.a", "on", at(104))
        # A fresh generation must inherit its still-valid prior-branch authority.
        assert replay.edges_for("a") == (ActiveEdge(at(104), "a", True),)
        assert replay.view().active("a")
        assert not replay.edges_for("x")
        restored = replay.inference_snapshot()
        assert len([path for path in restored.selected_paths if path is not None]) == 1


@pytest.mark.parametrize("count", (1, 2))
def test_strict_restore_rejects_null_displacement_for_retired_c(
    predictive_map: PredictiveMap, count: int,
) -> None:
    predictive_map = retired_prefix_map(predictive_map)
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(predictive_map, count)
        for event in retired_prefix_inputs(at(0)):
            replay.send(event.entity_id, event.state, event.event_at)
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)
        assert replay.edges_for("x") == (ActiveEdge(at(3), "x", True),)
        payload = json.loads(json.dumps(replay.checkpoint()))
        valid = restore_target_state(predictive_map, payload, at(3))
        path = valid.snapshot.selected_paths[0]
        assert path is not None
        assert tuple(visit.node_id for visit in path.route) == ("b", "a", "x")
        assert all(visit.node_id != "c" for visit in path.visits)
        retired = next(visit for visit in path.occurrences if visit.node_id == "c")
        assert not retired.branch_active
        assert tuple(visit.node_id for visit in path.branch_routes[0]) == (
            "b", "c", "retirement_inner", "retirement_tip",
        )
        c_belief = next(state for state in valid.snapshot.belief_states
                if state.zone == "c")
        assert c_belief.generation_episode_id == retired.episode_id
        assert c_belief.path_displaced_at == at(3)
        assert next(state for state in valid.snapshot.episode_states
                    if state.node_id == "c").known_on

        # PATH005 approved control: real C presence retains already-acquired ON,
        # without restoring retired branch authority or clearing displacement.
        valid.advance(at(7200))
        replay.advance(at(7200))
        assert next(state for state in valid.snapshot.policy_states
                        if state.zone == "c").active
        assert replay.view().active("c")
        assert tuple(edge.active for edge in replay.edges_for("c")) == (True,)

        corrupted = deepcopy(payload)
        raw_snapshot = cast(dict[str, Any], corrupted["snapshot"])
        raw_c = next(state for state in raw_snapshot["belief_states"]
                     if state["zone"] == "c")
        assert raw_c["path_displaced_at"] == at(3).isoformat()
        # Mutate this one leaf only, leaving the retired visit and every other
        # field intact. Acceptance is the defect, not ordinary writer data loss.
        raw_c["path_displaced_at"] = None
        with pytest.raises(ValueError):
            restore_target_state(predictive_map, corrupted, at(3))


@pytest.mark.parametrize("count", (1, 2))
def test_runtime_restored_off_mismatch_revokes_branch_immediately(
    predictive_map: PredictiveMap, count: int,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = restored_startup(scenario, predictive_map, count, "off")
        replay.send("binary_sensor.x", "on", at(21))
        assert replay.edges_for("x") == (), "Startup OFF must revoke A before 30s"
        assert not replay.view().active("x")
        assert replay.edges_for("c") == (ActiveEdge(at(20), "c", True),)
        assert_one_retained_chain(replay.inference_snapshot(), count)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("a_state,arrival_at,acquires", (
    pytest.param("on", 21, True, id="matching-on"),
    pytest.param("unknown", 21, False, id="unknown-before-clear"),
    pytest.param("off", 31, False, id="off-after-clear"),
))
def test_runtime_restored_branch_boundary_controls(
    predictive_map: PredictiveMap, count: int, a_state: str,
    arrival_at: int, acquires: bool,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = restored_startup(scenario, predictive_map, count, a_state)
        replay.send("binary_sensor.x", "on", at(arrival_at))
        assert replay.edges_for("x") == (
            (ActiveEdge(at(arrival_at), "x", True),) if acquires else ()
        )
        assert replay.view().active("x") is acquires
        snapshot = replay.inference_snapshot()
        assert len(snapshot.selected_paths) == count
        assert len([path for path in snapshot.selected_paths if path is not None]) == 1
        if not acquires:
            assert replay.edges_for("c") == (ActiveEdge(at(20), "c", True),)
            assert_one_retained_chain(snapshot, count)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("clear_order", tuple(permutations(("a", "b", "c"))),
                         ids=lambda order: "-".join(order))
def test_runtime_all_clear_orders_retain_latest_c_and_strict_restore(
    predictive_map: PredictiveMap, count: int, clear_order: tuple[str, ...],
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(predictive_map, count)
        walk_to_c(replay)
        cleared: set[str] = set()
        for index, node in enumerate(clear_order):
            seconds = 10 + index * 15
            replay.send(f"binary_sensor.{node}", "off", at(seconds))
            assert_one_retained_chain(replay.inference_snapshot(), count)
            replay.advance(at(seconds + 10))  # Real scheduled stable-clear boundary.
            cleared.add(node)
            snapshot = replay.inference_snapshot()
            assert_one_retained_chain(snapshot, count)
            assert next(state for state in snapshot.episode_states
                        if state.node_id == node).status == "clear"
            path = snapshot.selected_paths[0]
            assert path is not None
            assert {visit.node_id for visit in path.route if visit.branch_active} == (
                {"a", "b", "c"} - cleared
            )
            assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)
            assert not replay.edges_for("a")
            assert not replay.edges_for("x")

        replay.advance(at(60))
        payload = json.loads(json.dumps(replay.checkpoint()))
        strict = restore_target_state(predictive_map, payload, at(60))
        assert_one_retained_chain(strict.snapshot, count)
        restored = scenario.create(predictive_map, count)
        assert restored.checkpoint()["snapshot"] != payload["snapshot"]
        asyncio.run(restored.runtime.async_stop())
        restored.hass.values.update({
            entity: SimpleNamespace(state=value.state)
            for entity, value in replay.hass.values.items()
        })
        restored.restore(payload)
        assert restored.checkpoint()["snapshot"] == payload["snapshot"]
        # Inference restore alone does not publish an unchanged active value on
        # a five-second tick. Real startup publishes the restored HA state.
        restored.runtime.start()
        assert replay.view() == restored.view()
        assert restored.edges_for("c") == (ActiveEdge(at(60), "c", True),)

        replay.advance(at(7200))
        assert replay.view() == restored.view()
        assert {zone for zone, active in replay.view().zones if active} == {"c"}
        assert replay.edges_for("c") == (ActiveEdge(at(2), "c", True),)
        assert restored.edges_for("c") == (ActiveEdge(at(60), "c", True),)
        # B may release after losing coverage, but cannot chatter or reacquire.
        assert tuple(edge.active for edge in replay.edges_for("b")) == (True, False)
        for branch in (replay, restored):
            assert not branch.edges_for("a")
            assert not branch.edges_for("x")
            assert_one_retained_chain(branch.inference_snapshot(), count)
        assert replay.checkpoint()["snapshot"] == restored.checkpoint()["snapshot"]
