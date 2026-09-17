"""Synthetic PATH007/008, PATH-STATE002 and DIAG011 backend qualifications.

These invented graphs/times are not captured incidents. The separate frozen
2054Z runtime replay owns the public office oracle. Here real reducer inputs,
physical clear deadlines, strict production codecs and engine continuation prove
bounded witnessed forks, revocation, ordering, coverage and atomic rejection.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, fields, replace

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import selected_path_payload
from custom_components.predictive_controls.zone_model import persistence
from custom_components.predictive_controls.zone_model import selected_paths as records
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPath,
    SelectedPaths,
    SelectedVisit,
    decode_paths,
)
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import RuntimeScenario
from tests.test_selected_paths import Scene, at, graph

pytestmark = pytest.mark.target_model


def _ids(visits: tuple[SelectedVisit, ...]) -> tuple[str, ...]:
    return tuple(v.node_id for v in visits)


def _fork(count: int = 1) -> Scene:
    scene = Scene(count, graph((
        ("a", "b"), ("b", "c"), ("c", "d"), ("a", "x"),
        ("x", "y"), ("y", "z"), ("c", "e"), ("d", "f"),
        ("u", "v"),
    )))
    for index, node in enumerate(("a", "b", "c", "d", "x")):
        scene.send(node, index)
    return scene


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return value


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _wire(scene: Scene) -> list[object]:
    raw: list[object] = json.loads(json.dumps(
        [None if path is None else asdict(path) for path in scene.reducer.paths],
        default=lambda value: value.isoformat(),
    ))
    return raw


def _engine_map() -> PredictiveMap:
    edges = (("a", "b"), ("b", "c"), ("c", "d"), ("a", "x"),
             ("x", "y"), ("y", "z"), ("c", "e"))
    names = sorted({name for edge in edges for name in edge})
    return PredictiveMap.from_mapping({"nodes": {
        name: {"zone": name, "role": "room_occupancy",
               "entities": {"motion": f"binary_sensor.{name}"},
               "adjacent": sorted({b if a == name else a for a, b in edges
                                   if name in (a, b)})}
        for name in names
    }})


def _send(engine: ZoneModelEngine, node: str, value: str, seconds: float) -> None:
    engine.observe(SensorInput(f"binary_sensor.{node}", value, at(seconds)))


def _roundtrip(engine: ZoneModelEngine, mapping: PredictiveMap) -> ZoneModelEngine:
    raw = serialize_target_state(mapping, engine)
    clone = restore_target_state(mapping, raw, engine.snapshot.updated_at)
    assert clone.snapshot == engine.snapshot
    assert serialize_target_state(mapping, clone) == raw
    return clone


@pytest.mark.parametrize("count", (0, 1, 2))
def test_count_bounds_three_tips_and_no_extra_occupant(count: int) -> None:
    scene = _fork(count)
    assert len(scene.reducer.paths) == count
    if not count:
        assert not scene.located and not scene.reducer.covered_nodes
        assert scene.send("e", 5) is None
        scene.restart(6)
        return
    path = scene.located[0]
    assert len(scene.located) == 1
    assert _ids(path.visits) == ("b", "c", "d", "x")
    assert _ids(path.route) == ("a", "x")
    assert tuple(_ids(w) for w in path.branch_routes) == (
        ("a", "b"), ("a", "b", "c"), ("a", "b", "c", "d"),
    )
    assert scene.reducer.covered_nodes == frozenset({"a", "b", "c", "d", "x"})
    assert len(path.occurrences) <= 20
    assert len(path.authoritative_visits) <= 7
    scene.restart(5)
    before = scene.reducer.paths
    scene.reducer.set_count(2, at(6))
    assert sum(p is not None for p in scene.reducer.paths) == 1
    scene.reducer.set_count(1, at(7))
    assert scene.reducer.paths == (before[0],)
    scene.reducer.set_count(0, at(8))
    scene.reducer.set_count(2, at(9))
    assert scene.send("e", 10) is None  # Count0 never banks the former C tip.


@pytest.mark.parametrize("count", (1, 2))
def test_oldest_tip_selects_before_append_evicts_it(count: int) -> None:
    scene = Scene(count)
    for index, node in enumerate(("a", "b", "c", "x", "y", "z")):
        scene.send(node, index)
    assert _ids(scene.located[0].visits) == ("c", "x", "y", "z")
    assert _ids(scene.located[0].branch_routes[0]) == ("a", "b", "c")
    scene.restart(6)
    auth = scene.send("d", 7)
    assert auth is not None
    assert auth.selected_source_episode_ids == (scene.states["c"].episode_id,)
    assert auth.path_node_ids == ("b", "c", "d")
    assert _ids(scene.located[0].route) == ("a", "b", "c", "d")
    assert "c" not in _ids(scene.located[0].visits)
    scene.restart(7)


def test_history_eviction_revokes_all_prefix_copies_before_promotion() -> None:
    scene = _fork()
    scene.send("y", 5)
    before = scene.located[0]
    assert "b" not in _ids(before.visits) and "b" not in _ids(before.route)
    assert tuple(w[-1].node_id for w in before.branch_routes) == ("c", "d")
    assert all(not v.branch_active for v in before.occurrences if v.node_id == "b")
    scene.restart(5)
    auth = scene.send("e", 6)
    assert auth is not None and auth.path_node_ids == ("b", "c", "e")
    path = scene.located[0]
    assert _ids(path.route) == ("a", "b", "c", "e")
    assert not path.route[1].branch_active
    assert "b" not in scene.reducer.covered_nodes
    assert all(not v.branch_active for v in path.occurrences if v.node_id == "b")
    scene.restart(7)


def test_capacity_trimmed_main_prefix_is_not_banked() -> None:
    scene = Scene(1)
    for index, node in enumerate(("a", "b", "c", "d", "e")):
        scene.send(node, index)
    assert _ids(scene.located[0].route) == ("b", "c", "d", "e")
    assert not scene.located[0].branch_routes
    assert scene.states["a"].known_on
    assert scene.send("x", 6) is None


def test_equal_time_saved_tip_rank_uses_input_order_not_tip_name() -> None:
    scene = Scene(1, graph((
        ("a", "b"), ("b", "z"), ("b", "c"), ("a", "y"),
        ("z", "x"), ("c", "x"),
    )))
    scene.send("a", 0)
    for node in ("b", "z", "c", "y"):
        scene.send(node, 1)
    assert _ids(scene.located[0].visits) == ("b", "z", "c", "y")
    assert tuple(w[-1].node_id for w in scene.located[0].branch_routes) == (
        "b", "c", "z",
    )
    scene.restart(1)
    auth = scene.send("x", 1)
    assert auth is not None and auth.path_node_ids == ("b", "c", "x")
    assert auth.selected_source_episode_ids == (scene.states["c"].episode_id,)
    scene.restart(1)


@pytest.mark.parametrize("status", ("clearing", "clear", "unavailable"))
def test_tip_clear_confirmation_and_unknown_revoke_only(status: str) -> None:
    scene = _fork()
    original = scene.states["c"]
    scene.clear("c", 5, status)
    assert ("c" in scene.reducer.covered_nodes) is (status == "clearing")
    scene.restart(5)
    scene.states["c"] = replace(original, last_event_at=at(6), advanced_at=at(6))
    scene.reducer.reconcile(scene.current, at(6))
    auth = scene.send("e", 7)
    assert (auth is not None) is (status == "clearing")
    scene.restart(8)


def test_correlated_selected_tip_continues_but_cannot_seed() -> None:
    scene = Scene(1)
    assert scene.send("a", 0, "correlated_positive") is None
    assert scene.send("b", 1) is None
    assert scene.send("c", 2, "correlated_positive") is not None
    assert scene.send("a", 3) is not None  # Actual new target from B.
    assert scene.located[0].branch_routes[-1][-1].kind == "correlated_positive"
    auth = scene.send("d", 4)
    assert auth is not None and auth.selected_source_episode_ids == (
        scene.states["c"].episode_id,
    )
    scene.restart(5)


def test_interaction_can_be_prefix_history_but_not_saved_tip() -> None:
    scene = Scene(1, graph((("a", "b"), ("b", "press"), ("a", "x"))))
    for index, (node, kind) in enumerate((
        ("a", "positive"), ("b", "positive"), ("press", "interaction"),
        ("x", "positive"),
    )):
        scene.send(node, index, kind)
    assert tuple(w[-1].node_id for w in scene.located[0].branch_routes) == ("b",)
    press = next(v for v in scene.located[0].visits if v.node_id == "press")
    assert not press.branch_active
    scene.restart(4)


def test_replacement_discards_overlap_without_rearming_consumption() -> None:
    scene = _fork()
    scene.send("u", 5)
    scene.send("v", 6)
    assert _ids(scene.located[0].route) == ("u", "v")
    assert not scene.located[0].branch_routes
    assert scene.send("e", 7) is None
    scene.restart(8)


def test_valid_shared_prefix_fork_roundtrips_and_projects_tips_only() -> None:
    scene = _fork()
    scene.send("y", 5)
    path = scene.located[0]
    assert decode_paths(_wire(scene)) == scene.reducer.paths
    payload = selected_path_payload(path)
    assert payload["covered_node_ids"] == payload["eligible_node_ids"] == [
        "a", "c", "d", "x", "y",
    ]
    assert "b" not in payload["covered_node_ids"]
    assert len(payload["branch_routes"]) == 2
    scene.restart(5)


@pytest.mark.parametrize("defect", (
    "missing", "duplicate_tip", "tip_on_main", "inactive_tip", "tip_kind",
    "copy_flag", "copy_kind", "tip_not_visited", "tip_order", "parent",
    "cycle", "edge", "ledger", "cross_slot",
))
def test_malformed_overlap_restore_is_atomic_with_real_continuation(
    defect: str,
) -> None:
    scene = _fork(2)
    raw = _wire(scene)
    path = _object(raw[0])
    branches = _array(path["branch_routes"])
    tip_route = _array(branches[-1])
    sources = scene.reducer.sources
    match defect:
        case "missing":
            del path["branch_routes"]
        case "duplicate_tip":
            branches[0] = deepcopy(branches[-1])
        case "tip_on_main":
            branches[-1] = deepcopy(path["route"])
        case "inactive_tip":
            _object(tip_route[-1])["branch_active"] = False
        case "tip_kind":
            _object(tip_route[-1])["kind"] = "interaction"
        case "copy_flag":
            _object(tip_route[0])["branch_active"] = False
        case "copy_kind":
            _object(tip_route[0])["kind"] = "correlated_positive"
        case "tip_not_visited":
            path["visits"] = _array(path["visits"])[1:]
        case "tip_order":
            branches.reverse()
        case "parent":
            # C still has predecessor B in the C witness, but A in the D witness.
            branches[-1] = [tip_route[0], tip_route[2], tip_route[3]]
        case "cycle":
            # Real equal-time donor, then reverse chronology of two sibling tips.
            scene = Scene(2, graph((("a", "b"), ("b", "c"), ("a", "x"))))
            for node in ("a", "b", "c", "x"):
                scene.send(node, 1)
            raw = _wire(scene)
            path = _object(raw[0])
            visits = _array(path["visits"])
            visits[1], visits[2] = visits[2], visits[1]
            sources = scene.reducer.sources
        case "edge":
            # A truncated root imposes no parent assertion, but A->D is not an edge.
            branches[-1] = [tip_route[0], tip_route[-1]]
        case "ledger":
            sources = tuple(replace(s, consumed=False) if s.node_id == "d" else s
                            for s in sources)
        case "cross_slot":
            raw[1] = deepcopy(raw[0])
    before = scene.reducer.paths, scene.reducer.sources, scene.reducer._at
    control = SelectedPaths(scene.map, scene.nodes, 2)
    control.restore(*before[:2], at(4))
    untouched = deepcopy(raw)
    with pytest.raises(ValueError):
        scene.reducer.restore(decode_paths(raw), sources, at(4))
    assert raw == untouched
    assert (scene.reducer.paths, scene.reducer.sources, scene.reducer._at) == before
    if defect != "cycle":
        physical_before = scene.current
        effect, state = scene.fact("e", 6)
        left = scene.reducer.observe(
            effect, state, scene.current, before=physical_before,
        )
        right = control.observe(effect, state, scene.current, before=physical_before)
        assert left == right and left is not None
        assert scene.reducer.paths == control.paths
        assert scene.reducer.sources == control.sources


@pytest.mark.parametrize("overflow", ("slots", "visits", "route", "branches", "prefix"))
def test_raw_bounds_precede_all_leaf_decoding(
    overflow: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = _fork()
    raw = _wire(scene)
    path = _object(raw[0])
    branches = _array(path["branch_routes"])
    match overflow:
        case "slots":
            raw.extend((None, None))
        case "visits" | "route":
            path[overflow] = [None] * 5
        case "branches":
            branches.append(None)
        case "prefix":
            branches[-1] = [None] * 5

    def forbidden(_value: object) -> SelectedVisit:
        raise AssertionError("Raw overflow reached a leaf decoder")

    monkeypatch.setattr(records, "_decode_visit", forbidden)
    with pytest.raises(ValueError, match="bounded|three|1..4"):
        decode_paths(raw)


@pytest.mark.parametrize("value", (None, [], (None,), ((),), ((None,),)))
def test_python_branch_shape_rejects_before_leaf_access(value: object) -> None:
    path = _fork().located[0]
    values: dict[str, object] = {field.name: getattr(path, field.name)
                                for field in fields(path)}
    values["branch_routes"] = value
    construct: Callable[..., SelectedPath] = SelectedPath
    with pytest.raises(ValueError):
        construct(**values)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("state", ("off", "unknown", "unavailable"))
def test_engine_overlap_removal_frontiers_roundtrip_without_invented_displacement(
    count: int, state: str,
) -> None:
    mapping = _engine_map()
    engine = ZoneModelEngine(mapping, count, at(0))
    for index, node in enumerate(("a", "b", "c", "d", "x")):
        _send(engine, node, "on", index)
        _roundtrip(engine, mapping)
    before = next(b for b in engine.snapshot.belief_states if b.zone == "c")
    assert before.path_displaced_at is None
    _send(engine, "c", state, 10)
    clone = _roundtrip(engine, mapping)
    for model in (engine, clone):
        model.advance(at(15))  # stay_pir's real stable-clear frontier is +5s.
        _roundtrip(model, mapping)
        displacement = next(b for b in model.snapshot.belief_states if b.zone == "c")
        assert displacement.path_displaced_at == at(15 if state == "off" else 10)
        _send(model, "e", "on", 16)
    assert engine.snapshot == clone.snapshot


def test_engine_main_stable_clear_has_real_delta_and_valid_null_endpoint() -> None:
    mapping = _engine_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    for index, node in enumerate(("a", "b", "c")):
        _send(engine, node, "on", index)
    _send(engine, "b", "off", 10)
    _send(engine, "c", "off", 10)
    engine.advance(at(15))
    beliefs = {b.zone: b for b in engine.snapshot.belief_states}
    assert beliefs["b"].path_displaced_at == at(15)
    assert beliefs["c"].path_displaced_at is None  # Retained main endpoint OFF.
    _roundtrip(engine, mapping)


def test_prefix_only_retirement_requires_displacement_and_atomic_reject() -> None:
    mapping = _engine_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    for index, node in enumerate(("a", "b", "c", "d", "x", "y")):
        _send(engine, node, "on", index)
        _roundtrip(engine, mapping)
    path = next(p for p in engine.snapshot.selected_paths if p is not None)
    assert "b" not in _ids(path.visits) and "b" not in _ids(path.route)
    assert any(v.node_id == "b" for v in path.occurrences)
    valid = serialize_target_state(mapping, engine)
    invalid = deepcopy(valid)
    beliefs = _array(_object(invalid["snapshot"])["belief_states"])
    b = next(_object(item) for item in beliefs if _object(item)["zone"] == "b")
    assert b["path_displaced_at"] == at(5).isoformat()
    b["path_displaced_at"] = None
    with pytest.raises(
        ValueError, match="Retired selected generation has no displacement",
    ):
        restore_target_state(mapping, invalid, at(5))
    assert serialize_target_state(mapping, engine) == valid
    clone = _roundtrip(engine, mapping)
    for model in (engine, clone):
        _send(model, "e", "on", 6)
        _roundtrip(model, mapping)
    assert engine.snapshot == clone.snapshot


def test_old_fingerprint_rejects_before_decoder_and_no_new_persisted_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _engine_map()
    engine = ZoneModelEngine(mapping, 1, at(0))
    payload = serialize_target_state(mapping, engine)
    assert payload["schema"] == "zone-belief-v4"
    assert "selected_path_version" not in payload
    fingerprint = persistence._target_map_fingerprint_payload(mapping)
    assert fingerprint["selected_path_version"] == 2
    fingerprint["selected_path_version"] = 1
    payload["map_fingerprint"] = persistence._fingerprint(fingerprint)

    def forbidden(_value: object) -> None:
        raise AssertionError("Old inference reached the snapshot decoder")

    monkeypatch.setattr(persistence, "_decode_snapshot", forbidden)
    with pytest.raises(ValueError, match="fingerprint"):
        restore_target_state(mapping, payload, at(0))


def test_real_status_producer_version_and_overlap_inventory() -> None:
    from custom_components.predictive_controls.status import runtime_status_payload

    mapping = _engine_map()
    with RuntimeScenario(at(0)) as scenario:
        replay = scenario.create(mapping, 2)
        for index, node in enumerate(("a", "b", "c", "d", "x", "y")):
            replay.send(f"binary_sensor.{node}", "on", at(index))
        payload = runtime_status_payload(replay.runtime)
        diagnostics = payload["occupancy_diagnostics"]
        assert diagnostics["selected_path_version"] == 2
        path = diagnostics["selected_paths"][0]
        assert len(path["branch_routes"]) == 2
        assert path["covered_node_ids"] == path["eligible_node_ids"] == [
            "a", "c", "d", "x", "y",
        ]
        assert diagnostics["selected_paths"][1] is None


def test_cross_slot_equal_time_generation_cycle_rejects_atomically() -> None:
    scene = Scene(2, graph((("a", "b"),)))
    a1 = SelectedVisit("a", "a", f"a:1:{at(1).isoformat()}", at(1), "positive", False)
    b1 = SelectedVisit("b", "b", f"b:1:{at(1).isoformat()}", at(1), "positive", False)
    a2 = replace(a1, episode_id=f"a:2:{at(1).isoformat()}", branch_active=True)
    b2 = replace(b1, episode_id=f"b:2:{at(1).isoformat()}", branch_active=True)
    # Each path is individually valid. Across slots A2->B1->B2->A1->A2 cycles.
    paths: tuple[SelectedPath, ...] = (
        SelectedPath((a2, b1), (a2, b1), at(1), endpoint_eligible=False),
        SelectedPath((b2, a1), (b2, a1), at(1), endpoint_eligible=False),
    )
    paths = tuple(sorted(paths, key=records._path_key))
    sources = tuple(
        records.SelectedSource(s.node_id, v.episode_id, v.at, "ordinary", True)
        if (v := {"a": a2, "b": b2}.get(s.node_id)) is not None else s
        for s in scene.reducer.sources
    )
    before = scene.reducer.paths, scene.reducer.sources, scene.reducer._at
    with pytest.raises(ValueError, match="causal order contains a cycle"):
        scene.reducer.restore(paths, sources, at(1))
    assert (scene.reducer.paths, scene.reducer.sources, scene.reducer._at) == before


@pytest.mark.parametrize("count", (1, 2))
def test_alias_on_preserves_tip_through_existing_clear_confirmation(count: int) -> None:
    mapping = _engine_map()
    # Work at the actual map/engine boundary, not by changing episode flags.
    nodes = dict(mapping.nodes)
    nodes["c"] = replace(nodes["c"], entities={
        "motion": "binary_sensor.c", "pir": "binary_sensor.c_alias",
    })
    predictive_map = replace(mapping, nodes=nodes)
    engine = ZoneModelEngine(predictive_map, count, at(0))
    for index, node in enumerate(("a", "b", "c", "d", "x")):
        _send(engine, node, "on", index)
    _send(engine, "c_alias", "on", 5)
    _send(engine, "c", "unknown", 6)
    assert "c" in engine._selected_paths.covered_nodes
    _roundtrip(engine, predictive_map)
    _send(engine, "c_alias", "off", 7)
    # Motion-only alias OFF uses the existing stay_pir five-second confirmation,
    # even with its peer unknown. No new timeout or immediate revocation rule.
    assert "c" in engine._selected_paths.covered_nodes
    _roundtrip(engine, predictive_map)
    engine.advance(at(11.999999))
    assert "c" in engine._selected_paths.covered_nodes
    _roundtrip(engine, predictive_map)
    engine.advance(at(12))
    assert "c" not in engine._selected_paths.covered_nodes
    _roundtrip(engine, predictive_map)


@pytest.mark.parametrize("count", (1, 2))
def test_promoted_tip_prediction_uses_actual_suffix_without_learning(
    count: int,
) -> None:
    mapping = PredictiveMap.from_mapping({"nodes": {
        name: {"entities": {"motion": f"binary_sensor.{name}"},
               "adjacent": adjacent}
        for name, adjacent in {
            "a": ["b", "x"], "b": ["a", "c"], "c": ["b", "d"],
            "d": ["c", "t"], "t": ["d"], "x": ["a"],
        }.items()
    }})
    engine = ZoneModelEngine(mapping, count, at(0))
    for _ in range(5):
        assert engine.prediction_manager.chain.observe("d", "t")
    counts = deepcopy(engine.prediction_manager.chain.counts)
    for index, node in enumerate(("a", "b", "c", "x")):
        _send(engine, node, "on", index)
    clone = _roundtrip(engine, mapping)
    for model in (engine, clone):
        _send(model, "d", "on", 4)
        grant = next(g for g in model.snapshot.selected_prediction_grants
                     if g.prediction_target_node_id == "t")
        assert grant.authorization.path_node_ids == ("b", "c", "d")
        assert grant.authorization.selected_source_episode_ids == (
            f"c:1:{at(2).isoformat()}",
        )
        assert grant.expires_at == at(14)
        assert next(p for p in model.snapshot.policy_states if p.zone == "t").active
        assert model.prediction_manager.chain.counts == counts
        _roundtrip(model, mapping)
    assert engine.snapshot == clone.snapshot


def test_supported_overlap_convergence_survives_other_slot_removal() -> None:
    scene = Scene(2, graph((
        ("a", "b"), ("b", "c"), ("b", "f"), ("f", "g"), ("g", "c"),
        ("x", "y"), ("y", "c"), ("c", "d"),
    )))
    for index, node in enumerate(("a", "b", "x", "y", "c", "f", "g", "c")):
        scene.send(node, index)
    assert sum(p.endpoint.zone == "c" for p in scene.located) == 2
    scene.send("d", 8)
    assert sum(p.endpoint.zone == "c" for p in scene.located) == 1
    scene.clear("c", 9)
    assert "c" in scene.reducer.covered_zones
    scene.restart(10)


