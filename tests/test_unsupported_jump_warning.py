"""Synthetic REQ-PATH-006/HEALTH-004 proofs; no captured gap incident established.

Approved 2026-09-13: missing intermediate evidence must not acquire a target,
and must publish a distinct unsupported-jump warning, not a sensor fault.
Public oracles use the actual runtime, registered timers and sampled Reliability
entity. Internal assertions supplement, never replace, those public outcomes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import (
    project_reliability_warnings,
    runtime_status_payload,
)
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.profiles import (
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supported_gap_acquisition import (
    select_supported_gap_source,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.gap_component_fixture import gap_source_components
from tests.overlap_retirement_fixture import retirement_inputs
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario
from tests.test_zone_model_supported_gap_acquisition import gap_map


class _TraversalOptions(TypedDict, total=False):
    allow_missed_edge: bool


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 13, tzinfo=UTC) + timedelta(seconds=seconds)


def graph(*, aliases: bool = False) -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {
                "mmwave": f"binary_sensor.{node}",
                **({"presence": "binary_sensor.c_alias"}
                   if aliases and node == "c" else {}),
            },
            "adjacent": neighbors, "initial_weight": 1.0,
        }
        for node, neighbors in (
            ("a", ["b"]), ("b", ["a", "middle"]), ("middle", ["b", "c"]),
            ("c", ["middle", "d", "x"]), ("d", ["c"]), ("x", ["c"]),
        )
    }})


@pytest.mark.parametrize("count", (1, 2))
def test_public_unsupported_jump_warning(count: int) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count).watch_reliability()
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(1))
        replay.send("binary_sensor.c", "on", at(2))
        assert replay.edges_for("b") == (ActiveEdge(at(1), "b", True),)
        assert not replay.view().active("c")
        assert not replay.edges_for("c")
        replay.advance(at(30))
        attributes = replay.reliability_attributes
        assert attributes is not None
        assert attributes["warnings"] == [{
            "node_id": "c", "zone": "c", "kind": "unsupported_jump",
            "reasons": ["unsupported_jump"], "active_reasons": ["unsupported_jump"],
            "first_observed_at": at(2).isoformat(),
            "last_observed_at": at(2).isoformat(), "cleared_at": None, "active": True,
        }]
        assert attributes["active_count"] == 1
        assert "unsupported jump" in str(attributes["active_summary"])
        assert replay.runtime.problem_reasons == ("unsupported_spatial_jump",)
        assert replay.runtime.problem_sources == ("selected_path_evidence",)
        assert not any(
            item.health_warning or item.cadence_warning
            for item in replay.runtime.confidence.diagnostics.episode_states
        )


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("witness", ("middle", "x"))
def test_legitimate_connection_never_warns(count: int, witness: str) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count).watch_reliability()
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(1))
        replay.send(f"binary_sensor.{witness}", "on", at(2))
        replay.send("binary_sensor.c", "on", at(3))
        assert replay.edges_for("c") == (ActiveEdge(at(3), "c", True),)
        replay.advance(at(30))
        assert replay.reliability_attributes is not None
        assert replay.reliability_attributes["warnings"] == []


def jump(replay: RuntimeReplay, *, correlated: bool = False) -> None:
    if correlated:
        replay.send("binary_sensor.c", "on", at(0))
        replay.send("binary_sensor.c", "off", at(1))
    replay.send("binary_sensor.a", "on", at(20))
    replay.send("binary_sensor.b", "on", at(21))
    replay.send("binary_sensor.c", "on", at(22))


def rows(replay: RuntimeReplay) -> list[dict[str, Any]]:
    attributes = replay.reliability_attributes
    assert attributes is not None
    warnings = attributes["warnings"]
    assert isinstance(warnings, list)
    return [row for row in warnings if row["kind"] == "unsupported_jump"]


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("correlated", (False, True))
def test_rejected_target_pair_and_restore_continuation(
    count: int, correlated: bool,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), count).watch_reliability()
        jump(replay, correlated=correlated)
        replay.advance(at(30))
        assert rows(replay)[0]["first_observed_at"] == at(22).isoformat()
        assert not replay.edges_for("c")
        snapshot = replay.inference_snapshot()
        target = next(s for s in snapshot.episode_states if s.node_id == "c")
        assert target.cadence_correlated is correlated
        stored = json.loads(json.dumps(replay.checkpoint()))
        restored = scenario.create(graph(), count).watch_reliability()
        restored.restore(stored)
        assert restored.inference_snapshot() == snapshot
        learned = deepcopy(replay.runtime.chain.counts)
        for branch in (replay, restored):
            branch.send("binary_sensor.d", "on", at(31))
            assert branch.view().active("d") is (not correlated)
            assert not branch.view().active("c")
            assert not branch.edges_for("c")  # No retroactive activation of the origin.
        replay.advance(at(60))
        assert rows(replay)[0]["active"] is correlated
        assert rows(restored) == rows(replay)
        assert restored.inference_snapshot() == replay.inference_snapshot()
        assert replay.runtime.chain.counts == learned


@pytest.mark.parametrize("clear", ("off", "unknown", "unavailable"))
def test_alias_aggregate_lifecycle_and_event_only_timestamps(clear: str) -> None:
    predictive_map = graph(aliases=True)
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(predictive_map, 1).watch_reliability()
        jump(replay)
        replay.send("binary_sensor.c_alias", "on", at(23))
        replay.send("binary_sensor.c", "off", at(24))
        replay.send("binary_sensor.c_alias", "on", at(25))  # Duplicate.
        replay.send("binary_sensor.c", "on", at(21), processing_at=at(26))
        replay.advance(at(30))
        assert rows(replay)[0]["active"]
        assert rows(replay)[0]["last_observed_at"] == at(22).isoformat()
        replay.inference_snapshot()
        replay.send("binary_sensor.c_alias", clear, at(31))
        replay.advance(at(60))
        row, = rows(replay)
        assert row["first_observed_at"] == at(22).isoformat()
        assert row["last_observed_at"] == row["cleared_at"] == at(31).isoformat()
        assert not row["active"]
        attributes = replay.reliability_attributes
        assert attributes is not None
        assert attributes["active_count"] == 0
        assert runtime_status_payload(replay.runtime)["occupancy_diagnostics"][
            "reliability_warnings"
        ] == []  # Graph/active Reliability view never retains the cleared red row.
        replay.inference_snapshot()
        assert not replay.edges_for("c")


def test_count_zero_does_not_clear_an_existing_warning() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 2).watch_reliability()
        jump(replay)
        replay.send("sensor.replay_people", "0", at(23))
        replay.send("binary_sensor.d", "on", at(24))
        replay.advance(at(60))
        assert len(rows(replay)) == 1
        assert rows(replay)[0]["active"]
        assert rows(replay)[0]["last_observed_at"] == at(22).isoformat()
        assert not any(active for _, active in replay.view().zones)
        replay.inference_snapshot()


@pytest.mark.parametrize("mode", ("isolated", "three_hops", "unknown_source",
                                  "off_endpoint", "bootstrap", "zero"))
def test_warning_requires_eligible_selected_two_hop_source(mode: str) -> None:
    with RuntimeScenario(at(0)) as scenario:
        initial = {"binary_sensor.a": "on", "binary_sensor.b": "on"}
        replay = scenario.create(
            graph(), 0 if mode == "zero" else 1,
            initial_states=initial if mode == "bootstrap" else None,
        ).watch_reliability()
        if mode not in {"isolated", "bootstrap"}:
            replay.send("binary_sensor.a", "on", at(0))
            replay.send("binary_sensor.b", "on", at(1))
        if mode in {"unknown_source", "off_endpoint"}:
            replay.send("binary_sensor.b", "unknown" if mode == "unknown_source"
                        else "off", at(2))
        target = "d" if mode == "three_hops" else "c"
        replay.send(f"binary_sensor.{target}", "on", at(20))
        replay.advance(at(30))
        assert bool(rows(replay)) is (mode == "off_endpoint")
        assert not replay.edges_for(target)
        replay.inference_snapshot()


def prediction_graph() -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        node: {"role": "room_occupancy", "occupancy_behavior": "sustained",
               "entities": {"mmwave": f"binary_sensor.{node}"},
               "adjacent": neighbors}
        for node, neighbors in {
            "a": ["b"], "b": ["a", "c", "e"], "c": ["b", "t"],
            "e": ["b"], "t": ["c", "x"], "x": ["t"],
        }.items()
    }})


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("target_at", (4, 11.999999, 12))
def test_actual_prediction_confirmation_and_expiry_inverse(
    count: int, target_at: float,
) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(prediction_graph(), count).watch_reliability()
        for _ in range(5):
            assert replay.runtime.chain.observe("c", "t")
        learned = deepcopy(replay.runtime.chain.counts)
        for second, node in enumerate(("a", "b", "c", "e")):
            replay.send(f"binary_sensor.{node}", "on", at(second))
        for event in retirement_inputs(at(3), pair=("b", "e")):
            replay.send(event.entity_id, event.state, event.event_at)
        assert all(visit.node_id != "c"
                   for path in replay.inference_snapshot().selected_paths if path
                   for visit in path.occurrences)
        assert replay.attributes["t"]["phase"] == "predicted"
        replay.send("binary_sensor.t", "on", at(target_at))
        assert replay.view().active("t") is (target_at < 12)
        replay.advance(at(30))
        assert bool(rows(replay)) is (target_at == 12)
        assert replay.runtime.chain.counts == learned
        replay.inference_snapshot()


def test_unselected_mature_lease_does_not_suppress_warning() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(prediction_graph(), 1).watch_reliability()
        for _ in range(5):
            assert replay.runtime.chain.observe("c", "t")
        for second, node, state in (
            (0, "x", "on"), (1, "t", "on"), (2, "t", "off"),
            (100, "a", "on"), (101, "b", "on"), (102, "c", "on"), (103, "e", "on"),
        ):
            replay.send(f"binary_sensor.{node}", state, at(second))
        for event in retirement_inputs(at(103), pair=("b", "e")):
            replay.send(event.entity_id, event.state, event.event_at)
        assert all(visit.node_id != "c"
                   for path in replay.inference_snapshot().selected_paths if path
                   for visit in path.occurrences)
        # Actual evidence-active policy naturally prevents the mature lease from
        # acquiring. No policy/lease state is injected to manufacture this inverse.
        assert replay.attributes["t"]["phase"] == "active"
        assert any(lease.mature and lease.target_node_id == "t"
                   for lease in replay.runtime.confidence.diagnostics.prediction_leases)
        replay.inference_snapshot()
        replay.send("binary_sensor.t", "on", at(104))
        replay.advance(at(120))
        assert rows(replay)[0]["first_observed_at"] == at(104).isoformat()
        assert replay.edges_for("t") == (ActiveEdge(at(1), "t", True),)


def boundary_graph() -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        "b": {"role": "entry_boundary", "entities": {"contact": "binary_sensor.b"},
              "adjacent": ["middle"], "transition_seconds": {"middle": 15}},
        "middle": {"role": "transition_gate",
                   "entities": {"motion": "binary_sensor.middle"},
                   "adjacent": ["b", "c"], "transition_seconds": {"c": 15}},
        "c": {"role": "room_occupancy", "occupancy_behavior": "sustained",
              "entities": {"mmwave": "binary_sensor.c"}, "adjacent": ["middle"]},
    }})


@pytest.mark.parametrize("correlated", (False, True))
def test_real_boundary_token_cannot_use_engine_legacy_fallback(
    correlated: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = boundary_graph()
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(predictive_map, 0).watch_reliability()
        if correlated:
            replay.send("binary_sensor.c", "on", at(0))
            replay.send("binary_sensor.c", "off", at(1))
        replay.send("sensor.replay_people", "2", at(20))
        replay.send("binary_sensor.b", "on", at(21))
        before = replay.inference_snapshot()
        token, = before.traversal_tokens
        assert token.node_id == "b" and token.provenance_kind == "boundary"
        nodes = build_physical_nodes(predictive_map).nodes
        episodes = PhysicalEpisodes(nodes)
        episodes.restore_snapshot(before.episode_states)
        episodes.advance(at(22))
        update = episodes.observe(SensorInput("binary_sensor.c", "on", at(22)))
        assert update.state.cadence_correlated is correlated
        for enabled in (True, False):
            frontier = TraversalFrontier(predictive_map, nodes)
            frontier.restore_snapshot(
                before.traversal_tokens, before.current_token_ids,
                before.authorization_uses, at(21), before.pending_candidates,
                before.retained_traversal_tokens,
            )
            kwargs: _TraversalOptions = (
                {} if enabled else {"allow_missed_edge": False}
            )
            authorization = (
                frontier.authorize_correlated_target(update.state, at(22), **kwargs)
                if correlated else frontier.authorize(
                    update.state, at(22), count=None,
                    corroborating_states=episodes.states, **kwargs,
                )
            )
            assert authorization.authorized is enabled
            if enabled:
                assert authorization.reason == "missed_edge_authorized"

        engine = replay.runtime.confidence._engine
        assert engine is not None
        calls: list[dict[str, Any]] = []
        method = "authorize_correlated_target" if correlated else "authorize"
        original = getattr(engine._frontier, method)

        def capture(*args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return original(*args, **kwargs)

        def forbidden_gap(*args: Any) -> None:
            pytest.fail("Current engine called the retired supported-gap resolver")

        monkeypatch.setattr(engine._frontier, method, capture)
        monkeypatch.setattr(engine, "_supported_gap_source", forbidden_gap)
        replay.send("binary_sensor.c", "on", at(22))
        assert len(calls) == 1  # Reached legacy fallback, not selected acceptance.
        assert calls[0]["allow_missed_edge"] is False
        assert calls[0].get("gap_resolver") is None
        assert not replay.view().active("c") and not replay.edges_for("c")
        replay.advance(at(30))
        assert rows(replay)[0]["active"]
        replay.inference_snapshot()


@pytest.mark.parametrize("correlated", (False, True))
def test_dedicated_gap_component_positive_and_disabled_resolver(
    correlated: bool,
) -> None:
    """Real isolated legacy components, not synthetic engine inference injection."""
    predictive_map = gap_map()
    components = gap_source_components(predictive_map, at(0))
    nodes = build_physical_nodes(predictive_map).nodes
    episodes = PhysicalEpisodes(nodes)
    if correlated:
        episodes.observe(SensorInput("binary_sensor.target", "on", at(160)))
        episodes.observe(SensorInput("binary_sensor.target", "off", at(161)))
        episodes.advance(at(200))
        target = next(s for s in episodes.states if s.node_id == "target")
        episodes.restore_snapshot(tuple(
            target if s.node_id == "target" else s
            for s in components.snapshot.episode_states
        ))
    else:
        episodes.restore_snapshot(components.snapshot.episode_states)
    episodes.advance(at(212))
    update = episodes.observe(SensorInput("binary_sensor.target", "on", at(212)))
    effect, = update.effects
    assert update.state.cadence_correlated is correlated
    source = select_supported_gap_source(
        predictive_map, {n.node_id: n for n in nodes}, update.state, effect,
        components.snapshot.count_state, components.snapshot.traversal_tokens,
        episodes.states, components.snapshot.anonymous_supports,
        components.snapshot.support_token_bindings,
    )
    assert source is not None
    for enabled in (True, False):
        frontier = TraversalFrontier(predictive_map, nodes)
        frontier.restore_snapshot((source,), (source.token_id,), (), at(212))
        kwargs: dict[str, Any] = {"allow_missed_edge": False}
        if enabled:
            kwargs["gap_resolver"] = lambda: source
        authorization = (
            frontier.authorize_correlated_target(update.state, at(212), **kwargs)
            if correlated else frontier.authorize(
                update.state, at(212), count=None, **kwargs,
            )
        )
        assert authorization.authorized is enabled
        if enabled:
            assert authorization.reason == "supported_gap_acquisition"


@pytest.mark.parametrize("mutation", (
    "off", "unknown", "covered", "duplicate", "future", "kind", "reason",
    "type", "first_type", "last_refresh", "old_fingerprint",
))
def test_strict_restore_rejection_is_atomic(mutation: str) -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1)
        jump(replay)
        saved: Any = deepcopy(replay.checkpoint())
        original = deepcopy(saved["snapshot"]["reliability_warning_occurrences"][0])
        if mutation in {"off", "unknown", "covered"}:
            replay.send(
                "binary_sensor.d" if mutation == "covered" else "binary_sensor.c",
                "on" if mutation == "covered" else mutation, at(23),
            )
            saved = deepcopy(replay.checkpoint())
            saved["snapshot"]["reliability_warning_occurrences"] = [original]
        row = saved["snapshot"]["reliability_warning_occurrences"][0]
        if mutation == "duplicate":
            saved["snapshot"]["reliability_warning_occurrences"].append(deepcopy(row))
        elif mutation == "future":
            row["first_observed_at"] = row["last_observed_at"] = at(999).isoformat()
        elif mutation == "kind":
            row["kind"] = "flapping"
        elif mutation == "reason":
            row["reason"] = "not_a_reason"
        elif mutation == "type":
            row["kind"] = ["unsupported_jump"]
        elif mutation == "first_type":
            row["first_observed_at"] = 22
        elif mutation == "last_refresh":
            replay.advance(at(30))
            saved = deepcopy(replay.checkpoint())
            saved["snapshot"]["reliability_warning_occurrences"][0][
                "last_observed_at"
            ] = at(30).isoformat()
        elif mutation == "old_fingerprint":
            saved["map_fingerprint"] = "pre-unsupported-jump"
        before = deepcopy(replay.checkpoint())
        bad = deepcopy(saved)
        with pytest.raises(ValueError):
            restore_target_state(graph(), saved, scenario.clock.now)
        assert saved == bad
        assert not replay.runtime.restore_stored_state(saved, scenario.clock.now)
        assert replay.checkpoint() == before  # Nonempty live inference is unchanged.
        replay.inference_snapshot()


def test_coexisting_kinds_and_strict_day_projection() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1).watch_reliability()
        # Preserve the original six pairs and later warning/day frontiers;
        # four inserted real cycles meet the approved ten-cycle calibration.
        for start in (0, 10, 20, 30, 40, 50, 60, 70, 80, 100):
            replay.send("binary_sensor.c", "on", at(start))
            replay.send("binary_sensor.c", "off", at(start + 1))
        replay.send("binary_sensor.a", "on", at(120))
        replay.send("binary_sensor.b", "on", at(121))
        replay.send("binary_sensor.c", "on", at(122))
        replay.advance(at(750))
        assert replay.reliability_attributes is not None
        assert replay.reliability_attributes["active_count"] == 3
        assert rows(replay)[0]["last_observed_at"] == at(122).isoformat()
        active = runtime_status_payload(replay.runtime)["occupancy_diagnostics"][
            "reliability_warnings"
        ]
        assert {row["kind"] for row in active} == {
            "flapping", "suspected_stuck", "unsupported_jump",
        }
        assert replay.runtime.problem_reasons == (
            "sensor_health_degraded", "unsupported_spatial_jump",
        )
        engine = restore_target_state(graph(), replay.checkpoint(), at(750))
        engine.advance(at(90000))  # Sparse timer: active event survives a full day.
        assert any(row["kind"] == "unsupported_jump" for row in
                   project_reliability_warnings(
                       engine.snapshot.reliability_warning_occurrences, at(90000),
                   ))
        engine.observe(SensorInput("binary_sensor.c", "off", at(90001)))
        occurrences = engine.snapshot.reliability_warning_occurrences
        assert any(row["kind"] == "unsupported_jump" for row in
                   project_reliability_warnings(occurrences, at(176400.999999)))
        assert not any(row["kind"] == "unsupported_jump" for row in
                       project_reliability_warnings(occurrences, at(176401)))
        engine.advance(at(176401))
        payload = serialize_target_state(graph(), engine)
        assert restore_target_state(graph(), payload, at(176401)).snapshot == (
            engine.snapshot
        )  # Old cleared rows remain valid storage even when projection excludes them.


def test_publication_failure_sees_committed_warning_and_schedules_save() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1)
        replay.send("binary_sensor.a", "on", at(0))
        replay.send("binary_sensor.b", "on", at(1))
        saved: list[dict[str, object]] = []

        def publish() -> None:
            snapshot = restore_target_state(
                graph(), replay.checkpoint(), at(2),
            ).snapshot
            occurrence, = snapshot.reliability_warning_occurrences
            assert occurrence.kind == "unsupported_jump"
            assert occurrence.cleared_at is None
            assert not next(p for p in snapshot.policy_states if p.zone == "c").active
            raise RuntimeError("warning publication failure after commit")

        scenario.patch.setattr(replay.runtime, "_dispatch_update", publish)
        scenario.patch.setattr(replay.runtime, "schedule_transition_count_save",
                               lambda: saved.append(replay.checkpoint()))
        with pytest.raises(RuntimeError, match="warning publication failure"):
            replay.send("binary_sensor.c", "on", at(2))
        assert saved
        assert restore_target_state(graph(), saved[-1], at(2)).snapshot == (
            replay.inference_snapshot()
        )


def test_startup_reobservation_clears_without_reissuing_warning() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1)
        jump(replay)
        engine = restore_target_state(graph(), replay.checkpoint(), at(22))
        observations = tuple(
            SensorInput(alias, value, at(31))
            for episode in engine.snapshot.episode_states
            for alias, value in episode.alias_states
        )
        engine.reconcile_restored_asserted_contexts(observations, at(31))
        row, = project_reliability_warnings(
            engine.snapshot.reliability_warning_occurrences, at(31),
        )
        assert not row["active"] and row["cleared_at"] == at(31).isoformat()
        assert row["first_observed_at"] == at(22).isoformat()
        payload = serialize_target_state(graph(), engine)
        restored = scenario.create(graph(), 1).watch_reliability()
        scenario.clock.advance(at(31))
        restored.restore(payload)
        restored.advance(at(60))
        assert not rows(restored)[0]["active"]
        assert not restored.edges_for("c")
        restored.inference_snapshot()


def test_recurrence_replaces_only_latest_physical_target_reason() -> None:
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(graph(), 1).watch_reliability()
        jump(replay)
        replay.send("binary_sensor.c", "off", at(31))
        replay.send("binary_sensor.c", "on", at(52))
        replay.advance(at(60))
        row, = rows(replay)
        assert row["active"] and row["cleared_at"] is None
        assert row["first_observed_at"] == row["last_observed_at"] == (
            at(52).isoformat()
        )
        assert not replay.edges_for("c")
        replay.inference_snapshot()

