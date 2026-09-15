"""Approved selected prediction execution, independently of selected learning.

Source: 2026-09-13 delegated follow-up and retained test_runtime maturity cases.
Expected: mature living ON at kitchen arrival, one nonrenewing ten-second lease.
Observed before repair: selected authorization was filtered and living stayed OFF.
These are synthetic public/control and strict-state qualifications, not HA actuation
or reconstructed production incidents. Learned rows are explicit compatible inputs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import episodes as episode_module
from custom_components.predictive_controls.zone_model import persistence as state_module
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.prediction import (
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.profiles import (
    SHARED_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)
from tests.runtime_replay import ActiveEdge, RuntimeScenario
from tests.test_prediction import NOW, make_map


@pytest.mark.parametrize("count", (1, 2))
def test_selected_mature_prediction_public_timeline(count: int) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(make_map(), count)
        for _ in range(5):
            assert live.runtime.chain.observe("kitchen", "living")
        counts = live.runtime.chain.counts
        live.send("binary_sensor.office", "on", NOW)
        live.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        live.send("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
        assert live.view().active("living")
        assert live.input_edges_for("living") == (
            ActiveEdge(NOW + timedelta(seconds=2), "living", True),
        )
        assert live.attributes["living"]["phase"] == "predicted"
        assert live.runtime.chain.counts == counts
        live.inference_snapshot()  # Strict completed writer, not the public oracle.
        restored = scenario.create(make_map(), count)
        restored.restore(live.checkpoint())
        live.send("binary_sensor.kitchen", "on", NOW + timedelta(seconds=3))
        live.advance(NOW + timedelta(seconds=11, microseconds=999999))
        assert live.view().active("living")
        live.advance(NOW + timedelta(seconds=12))
        assert not live.view().active("living")
        assert not restored.runtime.confidence.policy_states["living"].active
        assert live.edges_for("living") == (
            ActiveEdge(NOW + timedelta(seconds=2), "living", True),
            ActiveEdge(NOW + timedelta(seconds=12), "living", False),
        )
        assert live.runtime.chain.counts == counts


def graph(*, peers: int = 0, targets: int = 1) -> PredictiveMap:
    """Synthetic connected approach with physically distinct same-zone peers."""
    adjacent = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
    for i in range(targets):
        adjacent[f"t{i:02}"] = ["c"]
        adjacent["c"].append(f"t{i:02}")
    for i in range(peers):
        adjacent[f"p{i}"] = []
    return PredictiveMap.from_mapping({"nodes": {
        node: {"zone": "c" if node.startswith("p") else node,
               "entities": {"motion": f"binary_sensor.{node}"},
               "adjacent": neighbors}
        for node, neighbors in adjacent.items()
    }})


def observe(engine: ZoneModelEngine, node: str, state: str, seconds: float) -> Any:
    return engine.observe(SensorInput(
        f"binary_sensor.{node}", state, NOW + timedelta(seconds=seconds),
    ))


def prepared(
    predictive_map: PredictiveMap | None = None, *, count: int = 1, support: int = 5,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    predictive_map = graph() if predictive_map is None else predictive_map
    engine = ZoneModelEngine(predictive_map, count, NOW)
    for _ in range(support):
        assert engine.prediction_manager.chain.observe("c", "t00")
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    observe(engine, "c", "on", 2)
    return predictive_map, engine


def roundtrip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> ZoneModelEngine:
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == payload
    return restored


@pytest.mark.parametrize("count", (1, 2))
def test_selected_grant_outlives_four_visit_eviction(count: int) -> None:
    predictive_map, engine = prepared(graph(peers=5), count=count)
    original = engine.snapshot.selected_prediction_grants
    assert len(original) == 1
    counts = deepcopy(engine.prediction_manager.chain.counts)
    for i in range(5):
        observe(engine, f"p{i}", "on", 3 + i)
        assert engine.snapshot.selected_prediction_grants == original
        roundtrip(predictive_map, engine)
    assert all(
        visit.node_id != "c" for path in engine.snapshot.selected_paths
        if path is not None for visit in path.visits
    )
    restored = roundtrip(predictive_map, engine)
    for item in (engine, restored):
        item.advance(NOW + timedelta(seconds=12))
        assert item.snapshot.selected_prediction_grants == ()
        assert item.prediction_manager.leases == ()
        assert item.prediction_manager.chain.counts == counts


def test_hardware_hold_does_not_renew_original_deadline() -> None:
    # First C was learned arrival from B. Its clear does not depart C; returning
    # inside hardware hold remains the same physical episode, even after clear.
    predictive_map, engine = prepared()
    original = engine.snapshot.selected_prediction_grants[0]
    observe(engine, "c", "off", 2.1)
    engine.advance(NOW + timedelta(seconds=7.1))
    result = observe(engine, "c", "on", 7.2)
    assert result.authorizations == ()
    assert next(s for s in result.snapshot.episode_states
                if s.node_id == "c").episode_id == original.key[-1]
    assert engine.snapshot.selected_prediction_grants == (original,)
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("state", ("on", "off", "unknown", "unavailable"))
def test_target_cancellation_rejects_reinserted_lease_but_preserves_other_target(
    state: str,
) -> None:
    predictive_map, engine = prepared(graph(targets=2), support=0)
    before: Any = serialize_target_state(predictive_map, engine)
    canceled = next(lease for lease in before["prediction"]["leases"]
                    if lease["target_node_id"] == "t00")
    # Unknown baseline is duplicate: establish known OFF before issuance separately.
    if state == "unknown":
        observe(engine, "t00", "off", 2)
        before = serialize_target_state(predictive_map, engine)
        assert all(g.prediction_target_node_id != "t00"
                   for g in engine.snapshot.selected_prediction_grants)
    observe(engine, "t00", state, 3)
    assert any(g.prediction_target_node_id == "t01"
               for g in engine.snapshot.selected_prediction_grants) == (state != "on")
    # ON is a confirmed departure from C and cancels both outgoing pairs.
    assert all(g.prediction_target_node_id != "t00"
               for g in engine.snapshot.selected_prediction_grants)
    payload: Any = serialize_target_state(predictive_map, engine)
    roundtrip(predictive_map, engine)
    payload["prediction"]["leases"].append(canceled)
    unchanged = deepcopy(payload)
    with pytest.raises(ValueError, match="selected grant"):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    assert payload == unchanged


@pytest.mark.parametrize("count", (1, 2))
def test_same_timestamp_target_before_and_after_issuance(count: int) -> None:
    predictive_map = graph()
    engine = ZoneModelEngine(predictive_map, count, NOW)
    for _ in range(5):
        engine.prediction_manager.chain.observe("c", "t00")
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    observe(engine, "t00", "off", 2)
    observe(engine, "c", "on", 2)
    assert len(engine.snapshot.selected_prediction_grants) == 1
    roundtrip(predictive_map, engine)
    observe(engine, "t00", "unknown", 2)
    canceled = engine.snapshot
    assert canceled.selected_prediction_grants == ()
    assert not next(p for p in engine.snapshot.policy_states if p.zone == "t00").active
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("event_state", ("on", "off"))
def test_exact_expiry_precedes_duplicate_or_target_input(event_state: str) -> None:
    predictive_map, engine = prepared()
    result = observe(engine, "c" if event_state == "on" else "t00", event_state, 12)
    assert engine.snapshot.selected_prediction_grants == ()
    assert [(event.zone, event.kind) for event in result.policy_events
            if event.zone == "t00"] == [("t00", "released")]
    roundtrip(predictive_map, engine)


@pytest.mark.parametrize("mode", ("source", "recovery", "departure", "zero"))
def test_revocation_is_permanent_and_reinsertion_rejects(mode: str) -> None:
    predictive_map, engine = prepared()
    old: Any = serialize_target_state(predictive_map, engine)
    if mode in {"source", "recovery"}:
        observe(engine, "c", "unavailable", 3)
        if mode == "recovery":
            observe(engine, "c", "on", 4)
    elif mode == "departure":
        observe(engine, "t00", "on", 3)
    else:
        engine.observe_count(CountInput("zero", 0, True, NOW + timedelta(seconds=3)))
    roundtrip(predictive_map, engine)
    current: Any = serialize_target_state(predictive_map, engine)
    assert old["snapshot"]["selected_prediction_grants"][0] not in (
        current["snapshot"]["selected_prediction_grants"]
    )
    bad: Any = serialize_target_state(predictive_map, engine)
    bad["prediction"]["leases"].extend(old["prediction"]["leases"])
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, bad, engine.snapshot.updated_at)


@pytest.mark.parametrize("mutation", (
    "missing_grants", "missing_authority", "orphan_grant", "orphan_lease",
    "duplicate_grant", "duplicate_lease", "oversized", "expired", "mixed",
    "effect", "path", "episode", "source", "expiry", "support", "probability",
    "string_support", "bool_support", "string_probability", "fake_token",
))
def test_selected_prediction_corruption_rejects_atomically(mutation: str) -> None:
    predictive_map, engine = prepared(support=0 if mutation == "bool_support" else 5)
    payload: Any = serialize_target_state(predictive_map, engine)
    grant = payload["snapshot"]["selected_prediction_grants"][0]
    lease = payload["prediction"]["leases"][0]
    if mutation == "missing_grants":
        del payload["snapshot"]["selected_prediction_grants"]
    elif mutation == "missing_authority":
        del lease["authority_kind"]
    elif mutation == "orphan_grant":
        payload["prediction"]["leases"] = []
    elif mutation == "orphan_lease":
        payload["snapshot"]["selected_prediction_grants"] = []
    elif mutation == "duplicate_grant":
        payload["snapshot"]["selected_prediction_grants"].append(deepcopy(grant))
    elif mutation == "duplicate_lease":
        payload["prediction"]["leases"].append(deepcopy(lease))
    elif mutation == "oversized":
        payload["prediction"]["leases"] = [deepcopy(lease) for _ in range(65)]
    elif mutation == "expired":
        engine.advance(NOW + timedelta(seconds=12))
        payload = serialize_target_state(predictive_map, engine)
        payload["prediction"]["leases"] = [lease]
    elif mutation == "mixed":
        lease["authority_kind"] = "token"
    elif mutation == "effect":
        grant["effect_kind"] = "correlated_positive"
    elif mutation == "path":
        grant["authorization"]["path_node_ids"][0] = "missing"
    elif mutation == "episode":
        grant["authorization"]["target_episode_id"] = "c:999:" + NOW.isoformat()
    elif mutation == "source":
        grant["authorization"]["selected_source_episode_ids"] = []
    elif mutation == "expiry":
        grant["expires_at"] = (NOW + timedelta(seconds=13)).isoformat()
    elif mutation == "support":
        lease["support"] = 6.0
    elif mutation == "probability":
        lease["probability"] = .99
    elif mutation == "string_support":
        lease["support"] = "5.0"
    elif mutation == "bool_support":
        lease["support"] = False
    elif mutation == "string_probability":
        lease["probability"] = str(lease["probability"])
    else:
        grant["authorization"]["source_tokens"] = [{}]
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert payload == before
    roundtrip(predictive_map, engine)


def test_publication_callbacks_have_complete_strict_pairs() -> None:
    predictive_map = graph()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    for _ in range(5):
        engine.prediction_manager.chain.observe("c", "t00")
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    calls = []

    def capture(*args: Any) -> None:
        roundtrip(predictive_map, engine)
        calls.append(args[0].zone)

    engine.observe(SensorInput("binary_sensor.c", "on", NOW + timedelta(seconds=2)),
                   decision_callback=capture)
    assert set(calls) == {"c", "t00"}


@pytest.mark.parametrize("source_state", ("off", "unavailable"))
def test_startup_source_reconciliation_remains_strict(source_state: str) -> None:
    predictive_map, engine = prepared()
    expected = engine.snapshot.selected_prediction_grants
    events = tuple(SensorInput(
        f"binary_sensor.{state.node_id}",
        source_state if state.node_id == "c" else dict(state.alias_states)[
            f"binary_sensor.{state.node_id}"
        ], NOW + timedelta(seconds=3),
    ) for state in engine.snapshot.episode_states)
    engine.reconcile_restored_asserted_contexts(events, NOW + timedelta(seconds=3))
    assert engine.snapshot.selected_prediction_grants == (
        expected if source_state == "off" else ()
    )
    roundtrip(predictive_map, engine)


def test_direct_snapshot_restore_must_not_return_orphan_grants() -> None:
    predictive_map, engine = prepared()
    with pytest.raises(ValueError, match="prediction"):
        ZoneModelEngine.restore(predictive_map, engine.snapshot, engine.audit_rows,
                                engine.snapshot.updated_at)


def test_equal_time_selected_history_roundtrips() -> None:
    predictive_map, engine = prepared()
    observe(engine, "c", "unavailable", 2)
    roundtrip(predictive_map, engine)
    observe(engine, "c", "on", 2)
    roundtrip(predictive_map, engine)


def test_equal_time_selected_history_roundtrips_after_visit_eviction() -> None:
    predictive_map, engine = prepared()
    for _ in range(6):
        observe(engine, "c", "unavailable", 2)
        roundtrip(predictive_map, engine)
        observe(engine, "c", "on", 2)
        roundtrip(predictive_map, engine)


def test_evicted_grant_previous_source_cannot_be_rearmed() -> None:
    predictive_map, engine = prepared(graph(peers=5))
    for i in range(5):
        observe(engine, f"p{i}", "on", 3 + i)
    payload: Any = serialize_target_state(predictive_map, engine)
    source = next(source for source in payload["snapshot"]["selected_sources"]
                  if source["node_id"] == "b")
    assert source["consumed"] is True
    source["consumed"] = False
    with pytest.raises(ValueError, match="generation"):
        restore_target_state(predictive_map, payload, engine.snapshot.updated_at)


def branch_graph() -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        node: {"entities": {"motion": f"binary_sensor.{node}"}, "adjacent": neighbors}
        for node, neighbors in {
            "a": ["b", "d"], "b": ["a", "c", "e"], "c": ["b", "t00"],
            "d": ["a", "t01"], "e": ["b"], "t00": ["c"], "t01": ["d"],
        }.items()
    }})


def test_inherited_confirmed_short_suffix_does_not_cancel_displaced_source() -> None:
    predictive_map, engine = prepared(branch_graph())
    original = engine.snapshot.selected_prediction_grants[0]
    for _ in range(5):
        engine.prediction_manager.chain.observe("d", "t01")
    result = observe(engine, "d", "on", 3)
    authorization = result.authorizations[-1]
    assert authorization.path_node_ids == ("a", "d")
    assert authorization.track_confidence == "confirmed"
    assert original in engine.snapshot.selected_prediction_grants
    newer = next(g for g in engine.snapshot.selected_prediction_grants
                 if g.authorization.target_node_id == "d")
    assert newer.authorization == authorization
    assert {
        p.zone for p in engine.snapshot.policy_states if p.phase == "predicted"
    } == {
        "t00", "t01",
    }
    roundtrip(predictive_map, engine)


def test_distinct_generation_grants_with_explicit_short_hold_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Synthetic component calibration, not deployed hardware evidence. Real
    # PhysicalEpisodes still emits every ID/effect. Five-second clear is unchanged.
    profiles = dict(SHARED_PROFILES)
    profiles["stay_pir"] = replace(
        profiles["stay_pir"], hardware_hold_interval=timedelta(0),
    )
    monkeypatch.setattr(episode_module, "SHARED_PROFILES", profiles)
    monkeypatch.setattr(state_module, "SHARED_PROFILES", profiles)
    predictive_map, engine = prepared(branch_graph())
    original = engine.snapshot.selected_prediction_grants[0]
    observe(engine, "c", "off", 2.1)
    observe(engine, "e", "on", 3)  # Actual B departure, not C departure.
    result = observe(engine, "c", "on", 7.2)
    assert result.authorizations[-1].path_node_ids[-2:] == ("b", "c")
    grants = tuple(g for g in engine.snapshot.selected_prediction_grants
                   if g.prediction_target_node_id == "t00")
    assert len(grants) == 2 and original in grants
    assert {g.expires_at for g in grants} == {
        NOW + timedelta(seconds=12), NOW + timedelta(seconds=17.2),
    }
    restored = roundtrip(predictive_map, engine)
    for item in (engine, restored):
        item.advance(NOW + timedelta(seconds=12))
        remaining = tuple(g for g in item.snapshot.selected_prediction_grants
                          if g.prediction_target_node_id == "t00")
        assert len(remaining) == 1
        assert remaining[0].expires_at == NOW + timedelta(seconds=17.2)
        # A newer diagnostic candidate does not renew the old active phase.
        assert not next(
            p for p in item.snapshot.policy_states if p.zone == "t00"
        ).active
        roundtrip(predictive_map, item)


@pytest.mark.parametrize("learned,competing,active", (
    (16.0, 2.0, True), (16.0, 2.000001, False), (4.0, 0.0, False), (5.0, 0.0, True),
))
def test_full_row_exact_maturity_boundary(
    learned: float, competing: float, active: bool,
) -> None:
    predictive_map = graph()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    counts = engine.prediction_manager.chain.counts
    counts["c"]["t00"] = learned
    counts["c"]["b"] = competing
    engine.prediction_manager.chain.restore_counts(counts)
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    observe(engine, "c", "on", 2)
    lease = engine.prediction_manager.leases[0]
    assert lease.probability == pytest.approx((learned + 1) / (learned + competing + 2))
    assert lease.support == learned
    assert next(
        p for p in engine.snapshot.policy_states if p.zone == "t00"
    ).active is active
    roundtrip(predictive_map, engine)


def test_execution_requires_operation_proof_and_does_not_learn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = graph()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    capture: dict[str, Any] = {}
    original = engine.prediction_manager.prepare

    def record(*args: Any, **kwargs: Any) -> Any:
        capture.update(args=args, kwargs=kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine.prediction_manager, "prepare", record)
    observe(engine, "a", "on", 0)
    observe(engine, "b", "on", 1)
    observe(engine, "c", "on", 2)
    manager = TargetPredictionManager(predictive_map)
    for _ in range(5):
        manager.chain.observe("c", "t00")
    counts = manager.chain.counts
    args, kwargs = capture["args"], capture["kwargs"]
    assert manager.prepare(*args) == ()
    assert manager.leases == ()
    assert manager.grants == ()
    assert len(manager.prepare(*args, **kwargs)) == 1
    frozen = manager.leases, manager.grants
    assert manager.prepare(*args, **kwargs) == ()
    assert (manager.leases, manager.grants) == frozen
    manager.commit(args[3])
    engine.commit_prediction_learning()
    assert manager.chain.counts == counts
    assert engine._pending_prediction_learning == []  # noqa: SLF001


def test_two_same_zone_slots_cancel_by_physical_source() -> None:
    adjacent = {
        "a": ["b"], "b": ["a", "c"], "c": ["b", "t00"], "t00": ["c"],
        "x": ["y"], "y": ["x", "p"], "p": ["y", "t01"], "t01": ["p"],
    }
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        node: {"zone": "c" if node == "p" else node,
               "entities": {"motion": f"binary_sensor.{node}"}, "adjacent": neighbors}
        for node, neighbors in adjacent.items()
    }})
    _, engine = prepared(predictive_map, count=2)
    for _ in range(5):
        engine.prediction_manager.chain.observe("p", "t01")
    for second, node in enumerate(("x", "y", "p"), 3):
        observe(engine, node, "on", second)
    assert [path.endpoint.zone for path in engine.snapshot.selected_paths
            if path is not None] == ["c", "c"]
    assert {
        g.authorization.target_node_id
        for g in engine.snapshot.selected_prediction_grants
    } == {
        "c", "p",
    }
    observe(engine, "c", "unavailable", 6)
    assert {
        g.authorization.target_node_id
        for g in engine.snapshot.selected_prediction_grants
    } == {"p"}
    roundtrip(predictive_map, engine)


def test_capacity_eviction_cannot_publish_or_restore_evicted_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = graph(targets=65)
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(predictive_map, 1)
        for _ in range(1000):
            live.runtime.chain.observe("c", "t00")
        engine = live.runtime.confidence._engine  # noqa: SLF001
        assert engine is not None
        manager = engine.prediction_manager
        capture: dict[str, Any] = {}
        original = manager._enforce_bound  # noqa: SLF001

        def before_eviction() -> None:
            if len(manager.leases) > 64:
                capture.update(manager.serialize())
            original()

        monkeypatch.setattr(manager, "_enforce_bound", before_eviction)
        live.send("binary_sensor.a", "on", NOW)
        live.send("binary_sensor.b", "on", NOW + timedelta(seconds=1))
        live.send("binary_sensor.c", "on", NOW + timedelta(seconds=2))
        assert len(manager.leases) == len(manager.grants) == 64
        assert not live.view().active("t00")
        assert live.edges_for("t00") == ()
        live.inference_snapshot()
        evicted = next(
            lease for lease in capture["leases"] if lease["target_node_id"] == "t00"
        )
        assert evicted["mature"] is True
        payload: Any = live.checkpoint()
        # Keep collection bound valid: remove one complete other pair, reinsert
        # the actually evicted lease without fabricating its absent grant.
        payload["prediction"]["leases"].pop()
        payload["snapshot"]["selected_prediction_grants"].pop()
        payload["prediction"]["leases"].append(evicted)
        with pytest.raises(ValueError, match="selected grant"):
            restore_target_state(predictive_map, payload, NOW + timedelta(seconds=2))


def test_runtime_failed_restore_preserves_nonempty_state_and_continuation() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(make_map(), 1)
        for _ in range(5):
            live.runtime.chain.observe("kitchen", "living")
        for second, node in enumerate(("office", "hall", "kitchen")):
            live.send(f"binary_sensor.{node}", "on", NOW + timedelta(seconds=second))
        good = live.checkpoint()
        baseline = deepcopy(good)
        bad: Any = deepcopy(good)
        bad["snapshot"]["selected_prediction_grants"] = []
        unchanged = deepcopy(bad)
        edges = tuple(live.edges)
        assert not live.runtime.restore_stored_state(bad, scenario.clock.now)
        assert bad == unchanged
        assert live.checkpoint() == baseline
        assert tuple(live.edges) == edges
        live.advance(NOW + timedelta(seconds=12))
        assert live.edges_for("living") == (
            ActiveEdge(NOW + timedelta(seconds=2), "living", True),
            ActiveEdge(NOW + timedelta(seconds=12), "living", False),
        )


def test_legacy_token_component_branch_preserves_real_provenance() -> None:
    # Independent legacy-component qualification, NOT selected route learning.
    # Real physical reducer and traversal frontier generate every episode/token.
    predictive_map = graph()
    nodes = build_physical_nodes(predictive_map).nodes
    episodes = episode_module.PhysicalEpisodes(nodes, diagnostic_warnings=False)
    frontier = TraversalFrontier(predictive_map, nodes)
    manager = TargetPredictionManager(predictive_map)
    for _ in range(5):
        manager.chain.observe("c", "t00")
    for second, node in enumerate(("a", "b", "c")):
        at = NOW + timedelta(seconds=second)
        episodes.advance(at)
        update = episodes.observe(SensorInput(f"binary_sensor.{node}", "on", at))
        authorization = frontier.authorize(update.state, at, count=None)
        if authorization.authorized:
            frontier.issue(update.state, update.effects[-1], authorization)
        manager.prepare(at, 1, episodes.states, (authorization,))
        manager.commit((authorization,))
    assert authorization.provenance_kind == "adjacent"
    assert authorization.track_confidence == "confirmed"
    assert manager.chain.counts["b"]["c"] == 1
    assert manager.leases[0].authority_kind == "token"
    assert manager.grants == ()
    restored = TargetPredictionManager.restored(
        predictive_map, manager.serialize(), at, strict_frontier=True,
    )
    assert restored.leases == manager.leases
    _, engine = prepared(predictive_map)
    with pytest.raises(ValueError, match="confirmed traversal provenance"):
        engine._validate_prediction_consistency(restored)  # noqa: SLF001
    engine._frontier = frontier  # noqa: SLF001
    engine._validate_prediction_consistency(restored)  # noqa: SLF001
    altered: Any = deepcopy(manager.serialize())
    altered["leases"][0]["authority_kind"] = "selected_prediction_grant"
    with pytest.raises(ValueError, match="selected grant"):
        restored.restore(altered, at)
    assert restored.leases == manager.leases


def test_selected_prediction_fingerprint_is_current_only() -> None:
    predictive_map, engine = prepared()
    payload = state_module._target_map_fingerprint_payload(predictive_map)  # noqa: SLF001
    assert type(payload["selected_prediction_execution_version"]) is int
    assert payload["selected_prediction_execution_version"] == 1
    historical = state_module._target_map_fingerprint_payload(  # noqa: SLF001
        predictive_map, pre_feature=True,
    )
    assert "selected_prediction_execution_version" not in historical
    del payload["selected_prediction_execution_version"]
    stored = serialize_target_state(predictive_map, engine)
    stored["map_fingerprint"] = state_module._fingerprint(payload)  # noqa: SLF001
    with pytest.raises(ValueError, match="fingerprint"):
        restore_target_state(predictive_map, stored, engine.snapshot.updated_at)


@pytest.mark.parametrize("action", ("source_unavailable", "target_unavailable", "zero"))
def test_public_prediction_cancellation_is_immediate(action: str) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(make_map(), 2)
        for _ in range(5):
            live.runtime.chain.observe("kitchen", "living")
        for second, node in enumerate(("office", "hall", "kitchen")):
            live.send(f"binary_sensor.{node}", "on", NOW + timedelta(seconds=second))
        if action == "zero":
            live.send("sensor.replay_people", "0", NOW + timedelta(seconds=3))
        else:
            node = "kitchen" if action == "source_unavailable" else "living"
            live.send(
                f"binary_sensor.{node}", "unavailable", NOW + timedelta(seconds=3),
            )
        assert live.edges_for("living") == (
            ActiveEdge(NOW + timedelta(seconds=2), "living", True),
            ActiveEdge(NOW + timedelta(seconds=3), "living", False),
        )
        live.inference_snapshot()


def test_public_correlated_confirmation_never_learns_or_reacquires() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(make_map(living_presence=True), 1)
        for _ in range(5):
            live.runtime.chain.observe("kitchen", "living")
        counts = live.runtime.chain.counts
        live.send("binary_sensor.living", "on", NOW)
        live.send("binary_sensor.living", "off", NOW + timedelta(seconds=20))
        for second, node in enumerate(("office", "hall", "kitchen"), 40):
            live.send(f"binary_sensor.{node}", "on", NOW + timedelta(seconds=second))
        assert live.attributes["living"]["phase"] == "predicted"
        live.send("binary_sensor.living", "on", NOW + timedelta(seconds=45))
        confirmed = dict(live.attributes["living"])
        assert confirmed["phase"] == "active"
        assert live.edges_for("living") == (
            ActiveEdge(NOW + timedelta(seconds=42), "living", True),
        )
        assert live.runtime.chain.counts == counts
        assert live.inference_snapshot().selected_prediction_grants == ()


def test_prediction_confirmation_cannot_chain_another_mature_prediction() -> None:
    mapping = {"a": ["b"], "b": ["a", "c"], "c": ["b", "t00"],
               "t00": ["c", "z"], "z": ["t00"]}
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        node: {"entities": {"motion": f"binary_sensor.{node}"}, "adjacent": adjacent}
        for node, adjacent in mapping.items()
    }})
    _, engine = prepared(predictive_map)
    for _ in range(5):
        engine.prediction_manager.chain.observe("t00", "z")
    counts = engine.prediction_manager.chain.counts
    observe(engine, "t00", "on", 3)
    assert next(
        p for p in engine.snapshot.policy_states if p.zone == "t00"
    ).phase == "active"
    assert not next(p for p in engine.snapshot.policy_states if p.zone == "z").active
    assert engine.snapshot.selected_prediction_grants == ()
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts == counts
    roundtrip(predictive_map, engine)


def test_equal_time_prediction_confirmation_history_roundtrips() -> None:
    predictive_map, engine = prepared()
    observe(engine, "t00", "on", 3)
    assert next(p for p in engine.snapshot.policy_states
                if p.zone == "t00").activation_reason == "prediction_confirmed"
    roundtrip(predictive_map, engine)
    observe(engine, "t00", "unavailable", 3)
    roundtrip(predictive_map, engine)
    observe(engine, "t00", "on", 3)
    roundtrip(predictive_map, engine)
