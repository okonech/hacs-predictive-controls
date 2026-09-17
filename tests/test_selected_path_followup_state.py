"""Synthetic state-frontier qualifications, not new captured HA incidents.

PATH-STATE001/EVID003: no-ON mixed aliases must round-trip before the second
alias's OFF repairs the state. No fake clear or presence protection is allowed.

PATH001..005/STATE001/008/009: public entity inverses and atomic persistence
qualifications follow docs/spec/selected-path-followup.md sections 6-7.
Learned counts below are an explicit storage fixture, not selected-path learning.
"""

import json
from copy import deepcopy

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from tests.overlap_retirement_fixture import retired_prefix_inputs, retired_prefix_map
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario
from tests.test_presence_gated_departure import (
    at,
    belief,
    gate_map,
    observe,
    retired,
    roundtrip,
)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("continuation", ("off", "on", "unknown"))
def test_mixed_alias_first_off_roundtrips_before_any_repair(
    count: int, continuation: str,
) -> None:
    predictive_map = gate_map(aliases=True)
    live = retired(predictive_map, count)
    observe(live, "c", "off", 100)
    state = next(s for s in live.snapshot.episode_states if s.node_id == "c")
    assert state.status == "unavailable"
    assert state.clear_deadline is None and not state.clear_emitted
    assert not belief(live).physical_hold
    restored = roundtrip(live, predictive_map)
    assert state.traversal_valid_until is None
    for model in (live, restored):
        observe(model, "c", "off", 100)  # Exact duplicate adds no evidence.
        observe(model, "c_alias", continuation, 101)
        model.advance(at(112))
        roundtrip(model, predictive_map)
    assert live.snapshot == restored.snapshot


def send(replay: RuntimeReplay, node: str, state: str, seconds: float) -> None:
    replay.send(f"binary_sensor.{node}", state, at(seconds))


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("seconds", (109.999999, 110, 110.000001))
def test_public_prior_branch_clear_boundary_and_callback_writer(
    count: int, seconds: float,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count)
        for index, node in enumerate(("a", "b", "c")):
            send(replay, node, "on", index)
        send(replay, "b", "off", 3)
        send(replay, "a", "off", 100)
        assert not replay.view().active("a")
        captured: list[dict[str, object]] = []
        entity = replay.entities["a"]
        write = entity.async_write_ha_state

        def capture() -> None:
            if entity.is_on:
                payload = json.loads(json.dumps(replay.checkpoint(), allow_nan=False))
                restore_target_state(replay.map, payload, scenario.clock.now)
                captured.append(payload)
            write()

        scenario.patch.setattr(entity, "async_write_ha_state", capture)
        send(replay, "a", "on", seconds)  # Equal-time timers run before input.
        expected = (ActiveEdge(at(seconds), "a", True),) if seconds < 110 else ()
        assert replay.edges_for("a") == replay.input_edges_for("a") == expected
        assert replay.view().active("a") is bool(expected)
        # Supplementary writer proof: no later operation repairs callback state.
        payload = json.loads(json.dumps(replay.checkpoint(), allow_nan=False))
        restore_target_state(replay.map, payload, at(seconds))
        assert len(captured) == len(expected)
        if captured:
            assert captured[0]["snapshot"] == payload["snapshot"]


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("selected", (False, True))
def test_public_consumed_origin_cannot_reseed_but_selected_visit_continues(
    count: int, selected: bool,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count)
        send(replay, "a", "on", 0)
        send(replay, "b", "on", 1)
        assert replay.edges_for("b") == (ActiveEdge(at(1), "b", True),)
        replay.send("sensor.replay_people", str(count if selected else 0), at(2))
        replay.send("sensor.replay_people", str(count), at(3))
        send(replay, "b", "on", 3.5)  # Duplicate cannot rearm consumed provenance.
        send(replay, "c", "on", 4)
        expected = (ActiveEdge(at(4), "c", True),) if selected else ()
        assert replay.input_edges_for("c") == expected
        for index, node in enumerate(("a", "b", "c"), 5):
            send(replay, node, "off", index)
        replay.advance(at(900))
        assert replay.edges_for("c") == expected
        assert replay.view().active("c") is selected


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("source", ("ordinary", "bootstrap", "unknown", "unavailable"))
def test_public_only_live_available_origin_authorizes_neighbor(
    count: int, source: str,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count, initial_states=(
            {"binary_sensor.a": "on"} if source == "bootstrap" else None
        ))
        if source != "bootstrap":
            send(replay, "a", "on", 0)
        send(replay, "a", source if source in {"unknown", "unavailable"} else "on", 3)
        send(replay, "x", "on", 4)
        expected = (ActiveEdge(at(4), "x", True),) if source == "ordinary" else ()
        assert replay.input_edges_for("x") == expected
        replay.advance(at(200))
        assert replay.edges_for("x") == expected
        assert replay.view().active("x") is bool(expected)
        assert replay.edges_for("a") == ()  # No retroactive source acquisition.


@pytest.mark.parametrize("count", (1, 2))
def test_public_retired_branch_fresh_presence_does_not_reacquire(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(gate_map(), count)
        for index, node in enumerate(("a", "b", "c", "x")):
            send(replay, node, "on", index)
        for index, node in enumerate(("a", "b", "c", "x"), 4):
            send(replay, node, "off", index)  # Remove every physical hold mask.
        replay.advance(at(900))
        assert replay.view().active("x") and not replay.view().active("c")
        before = replay.edges_for("c")
        assert tuple(edge.active for edge in before) == (True, False)
        send(replay, "c", "on", 901)
        replay.advance(at(1200))
        assert replay.edges_for("c") == before
        assert not replay.view().active("c")


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("endpoint_available", (False, True))
def test_public_competing_endpoint_precedes_return_branch(
    count: int, endpoint_available: bool,
) -> None:
    mapping = PredictiveMap.from_mapping({"nodes": {
        node: {"role": "room_occupancy", "occupancy_behavior": "sustained",
               "entities": {"mmwave": f"binary_sensor.{node}"}, "adjacent": adjacent}
        for node, adjacent in (("a", ["b", "c"]), ("b", ["a", "c"]),
                               ("c", ["a", "b", "y"]), ("y", ["c"]))
    }})
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(mapping, count)
        for index, node in enumerate(("a", "b", "c")):
            send(replay, node, "on", index)
        send(replay, "b", "off", 3)
        send(replay, "a", "off", 100)
        if not endpoint_available:
            send(replay, "c", "unavailable", 103)
        send(replay, "a", "on", 104)
        assert replay.input_edges_for("a") == (ActiveEdge(at(104), "a", True),)
        path, = (p for p in replay.inference_snapshot().selected_paths if p)
        assert tuple(visit.node_id for visit in path.route) == (
            ("a", "b", "c", "a") if endpoint_available else ("a", "a")
        )
        authorization = replay.runtime.confidence.diagnostics.authorizations[-1]
        source = f"c:1:{at(2).isoformat()}" if endpoint_available else (
            f"a:1:{at(0).isoformat()}"
        )
        assert authorization.selected_source_episode_ids == (source,)
        # Y alone cannot distinguish endpoint priority from saved-tip recovery.
        send(replay, "y", "on", 105)
        expected = (ActiveEdge(at(105), "y", True),) if endpoint_available else ()
        assert replay.input_edges_for("y") == replay.edges_for("y") == expected
        assert replay.view().active("y") is endpoint_available


@pytest.mark.parametrize("count", (1, 2))
def test_corrupt_null_restore_preserves_nonempty_runtime_and_continuation(
    count: int,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        mapping = retired_prefix_map(gate_map())
        donor = scenario.create(mapping, 3 - count)
        live, control = (scenario.create(mapping, count) for _ in range(2))
        for replay in (live, control):
            # Explicit nonzero learned-store fixture, below prediction maturity.
            assert replay.runtime.confidence.prediction_chain.observe("c", "y", 2.0)
        for index, event in enumerate(retired_prefix_inputs(at(0))):
            donor.send(event.entity_id, event.state, event.event_at)
            if index < 2:
                for replay in (live, control):
                    send(replay, ("c", "y")[index], "on", index)
        corrupted = json.loads(json.dumps(donor.checkpoint(), allow_nan=False))
        restore_target_state(donor.map, corrupted, at(3))  # Writer is valid first.
        raw_c = next(row for row in corrupted["snapshot"]["belief_states"]
                     if row["zone"] == "c")
        assert raw_c["path_displaced_at"] == at(3).isoformat()
        raw_c["path_displaced_at"] = None
        incoming = deepcopy(corrupted)
        donor.close()
        before = live.checkpoint()
        public = (live.view(), tuple(live.edges), live.writes, live.deliveries)
        learned = live.runtime.transition_counts
        assert live.edges_for("y") == (ActiveEdge(at(1), "y", True),)
        assert live.view().active("y")
        assert learned["c"]["y"] == 2.0
        with pytest.raises(
            AssertionError, match="Runtime rejected its replay checkpoint",
        ):
            live.restore(corrupted)  # False becomes AssertionError, not ValueError.
        assert corrupted == incoming
        assert live.checkpoint() == before == control.checkpoint()
        for replay in (live, control):
            assert replay.runtime.expected_occupants == count
            assert replay.runtime.transition_counts == learned
            assert (replay.view(), tuple(replay.edges), replay.writes,
                    replay.deliveries) == public
        for node, state, seconds in (
            ("c", "off", 10), ("y", "off", 11), ("y", "on", 901),
        ):
            for replay in (live, control):
                send(replay, node, state, seconds)
        live.advance(at(920))
        assert live.view() == control.view()
        assert live.edges == control.edges == [ActiveEdge(at(1), "y", True)]
        assert live.writes == control.writes and live.deliveries == control.deliveries
        assert live.checkpoint() == control.checkpoint()
