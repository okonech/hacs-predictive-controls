"""Synthetic pure-reducer proofs for REQ-PATH-001..004/PATH-STATE-001.

These are not incident captures or public-light assertions. Effects explicitly
represent deduplicated real observations; bootstrap tests deliberately omit
observe. The frozen September 10 runtime replay remains a separate integration
gate. No engine, policy, token, persistence, or shared-type behavior is patched.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from itertools import permutations
from typing import Any

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.profiles import (
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPath,
    SelectedPaths,
    SelectedSource,
    SelectedVisit,
    decode_paths,
    decode_sources,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    EpisodeState,
    SensorInput,
    TraversalAuthorization,
)

pytestmark = pytest.mark.target_model
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def graph(
    edges: tuple[tuple[str, str], ...] = (
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"),
        ("a", "x"), ("x", "y"), ("y", "z"),
    ),
) -> PredictiveMap:
    names = {name for edge in edges for name in edge} | {"presence", "press"}
    return PredictiveMap.from_mapping({"nodes": {
        name: {
            "zone": "c" if name in {"presence", "press"} else name,
            "role": "room_occupancy",
            "entities": {"interaction": "event.press"} if name == "press"
            else {"mmwave": f"binary_sensor.{name}"},
            "adjacent": sorted({b if a == name else a for a, b in edges
                                if name in (a, b)}),
        } for name in sorted(names)
    }})


class Scene:
    """Explicit synthetic deduplicated effects, independent of elapsed profiles."""

    def __init__(
        self, count: int = 2, predictive_map: PredictiveMap | None = None,
    ) -> None:
        self.map = predictive_map or graph()
        self.nodes = build_physical_nodes(self.map).nodes
        self.reducer = SelectedPaths(self.map, self.nodes, count)
        self.states = {s.node_id: s for s in PhysicalEpisodes(self.nodes).states}

    @property
    def current(self) -> tuple[EpisodeState, ...]:
        return tuple(self.states[key] for key in sorted(self.states))

    @property
    def located(self) -> tuple[SelectedPath, ...]:
        return tuple(p for p in self.reducer.paths if p is not None)

    def fact(
        self, node: str, seconds: float, kind: str = "positive",
    ) -> tuple[EpisodeEffect, EpisodeState]:
        previous = self.states[node]
        generation = previous.generation + 1
        episode_id = f"{node}:{generation}:{at(seconds).isoformat()}"
        state = replace(
            previous, generation=generation, episode_id=episode_id,
            started_at=at(seconds), last_event_at=at(seconds), advanced_at=at(seconds),
            status="clearing" if kind == "interaction" else "asserted",
            alias_states=tuple((alias, "unknown" if kind == "interaction" else "on")
                               for alias, _ in previous.alias_states),
            clear_emitted=False, cadence_correlated=kind == "correlated_positive",
        )
        self.states[node] = state
        return EpisodeEffect(node, state.zone, episode_id, kind, at(seconds)), state

    def send(
        self, node: str, seconds: float, kind: str = "positive",
    ) -> TraversalAuthorization | None:
        effect, state = self.fact(node, seconds, kind)
        return self.reducer.observe(effect, state, self.current)

    def clear(self, node: str, seconds: float, status: str = "clear") -> None:
        self.states[node] = replace(
            self.states[node], status=status, clear_emitted=status == "clear",
            last_event_at=at(seconds), advanced_at=at(seconds),
            alias_states=tuple(
                (alias, "unavailable" if status == "unavailable" else "off")
                for alias, _ in self.states[node].alias_states
            ),
        )
        self.reducer.reconcile(self.current, at(seconds))

    def restart(self, seconds: float) -> None:
        raw_paths, raw_sources = wire(self.reducer)
        restored = SelectedPaths(self.map, self.nodes, len(self.reducer.paths))
        restored.restore(
            decode_paths(raw_paths), decode_sources(raw_sources), at(seconds),
        )
        assert restored.paths == self.reducer.paths
        assert restored.sources == self.reducer.sources
        self.reducer = restored
        self.reducer.reconcile(self.current, at(seconds))


def wire(reducer: SelectedPaths) -> tuple[list[Any], list[Any]]:
    raw = json.loads(json.dumps([
        [None if p is None else asdict(p) for p in reducer.paths],
        [asdict(s) for s in reducer.sources],
    ], default=lambda value: value.isoformat()))
    return raw[0], raw[1]


@pytest.mark.parametrize("count", (0, 1, 2))
def test_exact_slot_and_per_node_ledger_cardinality(count: int) -> None:
    scene = Scene(count)
    assert scene.reducer.paths == (None,) * count
    assert tuple(s.node_id for s in scene.reducer.sources) == tuple(sorted(
        scene.states,
    ))
    assert all(s.origin == "none" for s in scene.reducer.sources)
    assert scene.reducer.covered_nodes == scene.reducer.covered_zones == frozenset()
    scene.restart(0)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("age", (180, 300, 7200, 86400))
@pytest.mark.parametrize("restart", (False, True))
def test_ordinary_live_origin_pairs_without_ttl(
    count: int, age: int, restart: bool,
) -> None:
    scene = Scene(count)
    assert scene.send("a", 0) is None
    if restart:
        scene.restart(age)
    auth = scene.send("b", age, "correlated_positive")
    assert auth is not None and auth.authorized
    assert auth.reason == auth.provenance_kind == "selected_path"
    assert not auth.source_tokens and not auth.new_uses
    assert not auth.equivalent_confirmed_strength
    assert auth.path_node_ids == ("a", "b")
    assert auth.track_confidence == "provisional"
    assert auth.selected_source_episode_ids == (scene.states["a"].episode_id,)
    assert auth.target_episode_id == scene.states["b"].episode_id
    assert len(scene.located) == 1
    assert scene.reducer.covered_zones == frozenset({"a", "b"})
    # Coverage does not constitute retroactive source acquisition: only B gets auth.
    assert auth.target_zone == "b"
    scene.restart(age)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("order", tuple(permutations(("a", "b", "c"))))
def test_all_clear_orders_retain_endpoint_not_prior_branches(
    count: int, order: tuple[str, ...],
) -> None:
    scene = Scene(count)
    scene.send("a", 0)
    scene.send("b", 1)
    scene.send("c", 2)
    cleared: set[str] = set()
    for index, node in enumerate(order):
        scene.clear(node, 10 + 2 * index, "clearing")
        expected = frozenset(({"a", "b", "c"} - cleared) | {"c"})
        assert scene.reducer.covered_nodes == expected
        scene.clear(node, 11 + 2 * index)
        cleared.add(node)
        expected = frozenset(({"a", "b", "c"} - cleared) | {"c"})
        assert scene.reducer.covered_nodes == expected
        assert tuple(v.node_id for v in scene.located[0].route) == ("a", "b", "c")
    scene.restart(86400)
    assert scene.reducer.covered_nodes == frozenset({"c"})
    auth = scene.send("d", 86401)
    assert auth is not None and auth.path_node_ids == ("b", "c", "d")
    assert scene.reducer.covered_nodes == frozenset({"d"})


def test_middle_clear_does_not_invent_an_a_to_c_edge() -> None:
    scene = Scene(1)
    for seconds, node in enumerate(("a", "b", "c")):
        scene.send(node, seconds)
    scene.clear("b", 3)
    assert scene.reducer.covered_nodes == frozenset({"a", "c"})
    assert tuple(v.node_id for v in scene.located[0].route) == ("a", "b", "c")
    scene.restart(4)
    assert scene.send("x", 5) is not None
    assert tuple(v.node_id for v in scene.located[0].route) == ("a", "x")
    assert scene.reducer.covered_nodes == frozenset({"a", "x"})


def test_branch_truncation_retires_suffix_and_keeps_self_contained_route() -> None:
    scene = Scene(2)
    for seconds, node in enumerate(("a", "b", "c", "x", "y", "z")):
        scene.send(node, seconds)
    path = scene.located[0]
    assert tuple(v.node_id for v in path.visits) == ("c", "x", "y", "z")
    assert tuple(v.node_id for v in path.route) == ("a", "x", "y", "z")
    assert not path.visits[0].branch_active
    scene.restart(6)
    # D neighbors retired C only. C is still physically ON, but cannot reseed.
    assert scene.send("d", 7) is None
    assert len(scene.located) == 1
    # A's original occurrence remains an eligible self-contained route source.
    auth = scene.send("b", 8)
    assert auth is not None and auth.path_node_ids == ("a", "b")
    assert tuple(v.node_id for v in scene.located[0].route) == ("a", "b")
    assert scene.located[0].route[0].at == at(0)
    scene.restart(9)


def test_bounded_prefix_cannot_reseed_from_still_on_generation() -> None:
    scene = Scene(2)
    for seconds, node in enumerate(("a", "b", "c", "d", "e")):
        scene.send(node, seconds)
    assert tuple(v.node_id for v in scene.located[0].route) == ("b", "c", "d", "e")
    scene.restart(86400)
    assert scene.states["a"].known_on
    assert scene.send("x", 86401) is None
    assert len(scene.located) == 1


def test_endpoint_continuation_precedes_older_compatible_branch() -> None:
    scene = Scene(1, graph((("a", "b"), ("b", "c"), ("c", "d"), ("a", "d"))))
    for seconds, node in enumerate(("a", "b", "c", "d")):
        scene.send(node, seconds)
    assert tuple(v.node_id for v in scene.located[0].route) == ("a", "b", "c", "d")


@pytest.mark.parametrize("count", (1, 2))
def test_independent_paths_overlap_converge_then_only_one_splits(count: int) -> None:
    scene = Scene(count, graph((
        ("a", "b"), ("b", "c"), ("b", "f"), ("f", "g"), ("g", "c"),
        ("x", "y"), ("y", "c"), ("c", "d"),
    )))
    for seconds, node in enumerate(("a", "b", "x", "y", "c")):
        scene.send(node, seconds)
    assert len(scene.located) == count
    if count == 2:
        assert {p.endpoint.node_id for p in scene.located} == {"b", "c"}
    # Resident evidence must not manufacture another occupant in C.
    scene.send("presence", 5)
    assert len(scene.located) == count
    assert sum(p.endpoint.zone == "c" for p in scene.located) == 1
    # Independently newer movement approaches C from the other path at count2.
    scene.send("f", 6)
    scene.send("g", 7)
    scene.send("c", 8)
    assert sum(p.endpoint.zone == "c" for p in scene.located) == count
    scene.restart(8)
    before = scene.reducer.paths
    scene.send("d", 9)
    assert sum(p.endpoint.zone == "c" for p in scene.located) == count - 1
    assert sum(p.endpoint.zone == "d" for p in scene.located) == 1
    if count == 2:
        assert sum(p in before for p in scene.reducer.paths) == 1


def test_same_zone_interaction_and_presence_do_not_fill_unlocated_slot() -> None:
    scene = Scene(2)
    assert scene.send("press", 0, "interaction") is not None
    assert scene.send("presence", 1) is not None
    assert scene.send("c", 2) is not None
    assert len(scene.located) == 1 and scene.reducer.paths[-1] is None
    assert scene.located[0].track_confidence == "provisional"
    assert scene.located[0].spatial_at == at(0)
    assert scene.located[0].updated_at == at(2)
    assert all(s.consumed for s in scene.reducer.sources if s.origin != "none")


def test_distinct_same_zone_sensors_can_pair_but_not_confirm() -> None:
    scene = Scene(2)
    assert scene.send("presence", 0) is None
    auth = scene.send("c", 1)
    assert auth is not None and auth.path_node_ids == ("presence", "c")
    assert len(scene.located) == 1
    assert scene.send("press", 2, "interaction") is not None
    assert scene.located[0].track_confidence == "provisional"


def test_correlated_origins_never_seed_and_targets_never_promote() -> None:
    scene = Scene(2)
    assert scene.send("a", 0, "correlated_positive") is None
    assert scene.send("b", 1) is None
    assert not scene.located
    assert scene.send("c", 2, "correlated_positive") is not None
    auth = scene.send("d", 3, "correlated_positive")
    assert auth is not None and auth.track_confidence == "provisional"
    auth = scene.send("e", 4)
    assert auth is not None and auth.track_confidence == "confirmed"


def test_backtracking_duplicates_preserve_real_edges_without_confirmation() -> None:
    scene = Scene(1)
    for seconds in range(30):
        scene.send("a" if seconds % 2 == 0 else "b", seconds)
        if seconds:
            path = scene.located[0]
            assert path.track_confidence == "provisional"
            assert len(path.visits) <= 4 and len(path.route) <= 4
            assert path.endpoint.node_id == ("a" if seconds % 2 == 0 else "b")
            assert len({v.episode_id for v in path.route}) == len(path.route)
    assert tuple(v.node_id for v in scene.located[0].route) == ("a", "b", "a", "b")
    scene.restart(30)


@pytest.mark.parametrize("status", ("clear", "unavailable"))
def test_revoked_origin_cannot_recover_from_alias_or_timer(status: str) -> None:
    scene = Scene()
    scene.send("a", 0)
    original = scene.states["a"]
    scene.clear("a", 1, status)
    scene.states["a"] = replace(original, last_event_at=at(2))
    scene.reducer.reconcile(scene.current, at(2))
    scene.restart(3)
    assert scene.send("b", 4) is None
    assert not scene.located


def test_unknown_endpoint_stays_covered_but_cannot_authorize_neighbor() -> None:
    scene = Scene(1)
    scene.send("a", 0)
    scene.send("b", 1)
    scene.clear("a", 2)
    scene.clear("b", 3, "unavailable")
    assert scene.reducer.covered_nodes == frozenset({"b"})
    assert scene.send("c", 4) is None
    assert scene.send("b", 5) is not None  # Real new exact endpoint occurrence.
    assert scene.located[0].endpoint.at == at(5)


def test_mismatched_aliases_revoke_branches_but_preserve_endpoint() -> None:
    scene = Scene(1)
    scene.send("a", 0)
    scene.send("b", 1)
    for node in ("a", "b"):
        scene.states[node] = replace(
            scene.states[node], alias_states=(("binary_sensor.wrong", "on"),),
        )
    scene.reducer.reconcile(scene.current, at(2))
    assert scene.reducer.covered_nodes == frozenset({"b"})
    assert scene.send("c", 3) is None
    scene.restart(3)


@pytest.mark.parametrize("count", (1, 2))
def test_bootstrap_without_observe_never_creates_origin(count: int) -> None:
    scene = Scene(count)
    scene.fact("a", 0)  # Raw startup level is not sent to the reducer.
    scene.reducer.reconcile(scene.current, at(0))
    scene.restart(86400)
    assert all(s.origin == "none" for s in scene.reducer.sources)
    assert scene.send("b", 86401) is None
    assert not scene.located


def test_alias_flap_timer_duplicate_and_stale_inputs_cannot_add_visits() -> None:
    scene = Scene()
    effect, state = scene.fact("a", 0)
    assert scene.reducer.observe(effect, state, scene.current) is None
    before = scene.reducer.sources
    for kind in (
        "positive", "correlated_flap_ignored", "correlated_continuity_authorized",
    ):
        result = scene.reducer.observe(replace(effect, kind=kind), state, scene.current)
        assert result is None
    assert scene.reducer.sources == before
    scene.send("b", 1)
    before_paths = scene.reducer.paths
    before_sources = scene.reducer.sources
    scene.reducer.observe(effect, state, scene.current)
    scene.reducer.reconcile(scene.current, at(86400))
    assert scene.reducer.paths == before_paths
    assert scene.reducer.sources == before_sources


def test_real_episode_alias_callbacks_do_not_seed_an_extra_path() -> None:
    mapping = PredictiveMap.from_mapping({"nodes": {
        "a": {"entities": {"mmwave": "binary_sensor.a",
                   "presence": "binary_sensor.alias"},
              "adjacent": ["b"]},
        "b": {"entities": {"mmwave": "binary_sensor.b"}, "adjacent": ["a"]},
    }})
    nodes = build_physical_nodes(mapping).nodes
    episodes = PhysicalEpisodes(nodes)
    selected = SelectedPaths(mapping, nodes, 2)
    for seconds, alias in enumerate(("a", "alias", "b")):
        update = episodes.observe(SensorInput(
            f"binary_sensor.{alias}", "on", at(seconds),
        ))
        for effect in update.effects:
            selected.observe(effect, update.state, episodes.states)
    assert len([p for p in selected.paths if p is not None]) == 1
    assert selected.paths[-1] is None


def test_count_changes_add_u_remove_u_then_weakest_and_never_bank_zero() -> None:
    scene = Scene(1)
    scene.send("a", 0)
    scene.send("b", 1)
    path = scene.located[0]
    scene.reducer.set_count(2, at(2))
    assert tuple(scene.reducer.paths) == (path, None)
    scene.reducer.set_count(1, at(3))
    assert tuple(scene.reducer.paths) == (path,)
    for bad in (True, False, -1, 3, 1.5, None, "2"):
        scene.reducer.set_count(bad, at(4))  # type: ignore[arg-type]
        assert tuple(scene.reducer.paths) == (path,)
    scene.reducer.set_count(0, at(5))
    assert not scene.reducer.paths and not scene.reducer.covered_zones
    assert scene.send("c", 6) is None
    scene.restart(7)
    scene.reducer.set_count(2, at(8))
    assert tuple(scene.reducer.paths) == (None, None)
    assert scene.send("d", 9) is None  # Neither consumed B nor count0 C can seed.
    assert scene.send("e", 10) is not None
    assert len(scene.located) == 1


def test_independent_pair_replaces_weakest_oldest_not_lone_remote_ping() -> None:
    scene = Scene(2, graph((("a", "b"), ("b", "c"), ("x", "y"), ("y", "z"))))
    scene.send("a", 0)
    scene.send("b", 1)
    scene.send("c", 2)  # Confirmed, older slot.
    scene.send("x", 3)
    scene.send("y", 4)  # Provisional, newer slot.
    scene.reducer.set_count(1, at(5))
    assert scene.located[0].endpoint.node_id == "c"  # Strength before recency.
    # Retiring X/Y cannot rearm their still-on generations.
    assert scene.send("z", 6) is None
    assert scene.located[0].endpoint.node_id == "c"
    assert scene.send("y", 7) is not None  # A new independent pair Z->Y replaces it.
    assert scene.located[0].endpoint.node_id == "y"


def legacy(effect: EpisodeEffect, **changes: Any) -> TraversalAuthorization:
    return TraversalAuthorization(**{
        "target_node_id": effect.node_id, "target_zone": effect.zone,
        "target_episode_id": effect.episode_id, "authorized_at": effect.at,
        "authorized": True, "reason": "boundary_authorized",
        "track_confidence": "confirmed", "path_node_ids": ("x", "y", effect.node_id),
        "provenance_kind": "boundary", **changes,
    })


def test_adopt_records_only_actual_independently_authorized_target_once() -> None:
    scene = Scene()
    effect, state = scene.fact("a", 0)
    auth = legacy(effect)
    scene.reducer.adopt(effect, state, auth)
    assert not scene.located  # Observe must precede fallback.
    assert scene.reducer.observe(effect, state, scene.current) is None
    scene.reducer.adopt(effect, state, auth)
    assert tuple(v.node_id for v in scene.located[0].route) == ("a",)
    assert scene.located[0].track_confidence == "provisional"
    before = scene.reducer.paths, scene.reducer.sources
    scene.reducer.adopt(effect, state, auth)
    assert (scene.reducer.paths, scene.reducer.sources) == before
    scene.restart(1)
    scene.reducer.adopt(effect, state, auth)
    assert (scene.reducer.paths, scene.reducer.sources) == before


@pytest.mark.parametrize("kind", ("positive", "correlated_positive"))
def test_adoption_never_uses_prediction_or_correlated_seed(kind: str) -> None:
    scene = Scene()
    effect, state = scene.fact("a", 0, kind)
    scene.reducer.observe(effect, state, scene.current)
    auth = legacy(effect, reason="prediction_authorized", provenance_kind="prediction")
    scene.reducer.adopt(effect, state, auth)
    assert not scene.located
    if kind == "correlated_positive":
        scene.reducer.adopt(effect, state, legacy(effect))
        assert not scene.located


def populated() -> SelectedPaths:
    """Construct valid persistence proof without relying on auth integration."""
    scene = Scene()
    first = SelectedVisit("a", "a", f"a:1:{at(0).isoformat()}", at(0), "positive")
    last = SelectedVisit("b", "b", f"b:1:{at(1).isoformat()}", at(1), "positive")
    path = SelectedPath((first, last), (first, last), at(1))
    sources = tuple(
        SelectedSource(s.node_id, first.episode_id, first.at, "ordinary", True)
        if s.node_id == "a" else
        SelectedSource(s.node_id, last.episode_id, last.at, "ordinary", True)
        if s.node_id == "b" else s for s in scene.reducer.sources
    )
    scene.reducer.restore((path, None), sources, at(2))
    return scene.reducer


def test_json_roundtrip_is_byte_stable_and_reads_are_pure() -> None:
    original = populated()
    before = original.paths, original.sources
    raw_paths, raw_sources = wire(original)
    other = populated()
    other.restore(decode_paths(raw_paths), decode_sources(raw_sources), at(86400))
    assert wire(other) == (raw_paths, raw_sources)
    assert (original.paths, original.sources) == before
    assert other.paths == original.paths and other.sources == original.sources


@pytest.mark.parametrize("defect", (
    "path_count", "path_order", "duplicate_path", "source_missing", "source_duplicate",
    "source_order", "unknown_node", "wrong_zone", "disconnected", "missing_field",
    "extra_field", "naive", "non_utc", "datetime_leaf", "numeric_timestamp",
    "future", "generation_zero", "generation_bool", "generation_mismatch",
    "boolean_int", "consumption_int", "unconsumed", "origin_bootstrap",
    "source_future", "source_older", "source_unobserved", "correlated_unconsumed",
    "history_endpoint", "route_empty", "route_overlong", "history_overlong",
    "invalid_confidence", "history_route_disagree", "source_extra", "path_tuple",
))
def test_malformed_json_or_restore_is_atomic(defect: str) -> None:
    reducer = populated()
    before = reducer.paths, reducer.sources
    paths, sources = wire(reducer)
    match defect:
        case "path_count":
            paths.pop()
        case "path_order":
            paths.reverse()
        case "duplicate_path":
            paths[1] = paths[0]
        case "source_missing":
            sources.pop()
        case "source_duplicate":
            sources.insert(0, sources[0])
        case "source_order":
            sources.reverse()
        case "unknown_node" | "wrong_zone" | "disconnected":
            for key in ("visits", "route"):
                visit = paths[0][key][0]
                if defect == "wrong_zone":
                    visit["zone"] = "wrong"
                else:
                    name = "missing" if defect == "unknown_node" else "z"
                    visit.update(node_id=name, zone=name,
                                 episode_id=f"{name}:1:{at(0).isoformat()}")
            if defect == "disconnected":
                sources[-1].update(
                    episode_id=f"z:1:{at(0).isoformat()}",
                    at=at(0).isoformat(), origin="ordinary", consumed=True,
                )
        case "missing_field":
            del paths[0]["route"]
        case "extra_field":
            paths[0]["invented"] = True
        case "naive" | "non_utc" | "datetime_leaf" | "numeric_timestamp" | "future":
            paths[0]["spatial_at"] = {
                "naive": "2026-09-12T00:00:00", "non_utc": "2026-09-12T01:00:00+01:00",
                "datetime_leaf": at(1), "numeric_timestamp": 1,
                "future": at(20).isoformat(),
            }[defect]
        case "generation_zero" | "generation_bool" | "generation_mismatch":
            paths[0]["route"][0]["episode_id"] = {
                "generation_zero": f"a:0:{at(0).isoformat()}",
                "generation_bool": f"a:True:{at(0).isoformat()}",
                "generation_mismatch": f"a:1:{at(1).isoformat()}",
            }[defect]
        case "boolean_int":
            paths[0]["route"][0]["branch_active"] = 1
        case "consumption_int":
            sources[0]["consumed"] = 1
        case "unconsumed":
            sources[0]["consumed"] = False
        case "origin_bootstrap":
            sources[0]["origin"] = "bootstrap"
        case "source_future" | "source_older":
            seconds = 20 if defect == "source_future" else -1
            sources[0].update(at=at(seconds).isoformat(),
                              episode_id=f"a:1:{at(seconds).isoformat()}")
        case "source_unobserved":
            sources[0].update(episode_id=None, at=None, origin="none", consumed=False)
        case "correlated_unconsumed":
            sources[0].update(origin="correlated", consumed=False)
        case "history_endpoint":
            paths[0]["visits"].reverse()
        case "route_empty":
            paths[0]["route"] = []
        case "route_overlong" | "history_overlong":
            paths[0]["route" if defect == "route_overlong" else "visits"] *= 3
        case "invalid_confidence":
            paths[0]["track_confidence"] = "certain"
        case "history_route_disagree":
            paths[0]["visits"][0]["branch_active"] = False
        case "source_extra":
            sources[0]["bootstrap"] = False
        case "path_tuple":
            paths[0]["route"] = tuple(paths[0]["route"])
    with pytest.raises(ValueError):
        reducer.restore(decode_paths(paths), decode_sources(sources), at(10))
    assert (reducer.paths, reducer.sources) == before

@pytest.mark.parametrize("raw", (None, {}, "[]", (), 0, False))
def test_decoders_require_json_arrays(raw: object) -> None:
    with pytest.raises(ValueError):
        decode_paths(raw)
    with pytest.raises(ValueError):
        decode_sources(raw)


def test_map_count_and_future_restore_reject_atomically() -> None:
    reducer = populated()
    before = reducer.paths, reducer.sources
    with pytest.raises(ValueError):
        reducer.restore(reducer.paths, reducer.sources, at(0))
    assert (reducer.paths, reducer.sources) == before
    empty = Scene(0).reducer
    pending = replace(reducer.sources[0], consumed=False)
    with pytest.raises(ValueError):
        empty.restore((), (pending, *reducer.sources[1:]), at(10))
    assert not empty.paths and all(s.origin == "none" for s in empty.sources)


def test_equal_time_causal_order_survives_canonical_slot_order_and_restore() -> None:
    scene = Scene(2)
    scene.send("b", 0)
    scene.send("a", 0)
    assert tuple(v.node_id for v in scene.located[0].route) == ("b", "a")
    scene.restart(0)
    assert tuple(v.node_id for v in scene.located[0].route) == ("b", "a")
    # Actual input order is retained; lexical ordering is only a selection tie break.
    other = Scene(2)
    other.send("a", 0)
    other.send("b", 0)
    assert tuple(v.node_id for v in other.located[0].route) == ("a", "b")
    assert wire(other.reducer) != wire(scene.reducer)


def test_reconcile_unavailability_cannot_resurrect_endpoint_authority() -> None:
    scene = Scene(2)
    scene.reducer = populated()
    for node, seconds in (("a", 0), ("b", 1)):
        scene.fact(node, seconds)
    original = scene.states["b"]
    scene.clear("a", 3)
    scene.clear("b", 4, "unavailable")
    assert not scene.located[0].endpoint_eligible
    scene.states["b"] = replace(original, last_event_at=at(5), advanced_at=at(5))
    scene.reducer.reconcile(scene.current, at(5))
    scene.restart(6)
    assert scene.reducer.covered_nodes == frozenset({"b"})
    assert not scene.located[0].endpoint_eligible
    assert scene.send("c", 7) is None


def test_restore_rejects_reversed_same_node_generations_at_equal_time() -> None:
    first = SelectedVisit("a", "a", f"a:2:{NOW.isoformat()}", NOW, "positive")
    second = SelectedVisit("a", "a", f"a:1:{NOW.isoformat()}", NOW, "positive")
    with pytest.raises(ValueError, match="generations"):
        SelectedPath((first, second), (first, second), NOW)


def test_restore_rejects_disagreeing_equal_time_history_route_order() -> None:
    a, b, c = tuple(SelectedVisit(n, n, f"{n}:1:{NOW.isoformat()}", NOW, "positive")
                    for n in ("a", "b", "c"))
    with pytest.raises(ValueError, match="causal order"):
        SelectedPath((a, b, c), (b, a, c), NOW)


def test_restore_rejects_noninteraction_source_with_interaction_class() -> None:
    reducer = populated()
    before = reducer.paths, reducer.sources
    sources = tuple(replace(s, origin="interaction") if s.node_id == "a" else s
                    for s in reducer.sources)
    with pytest.raises(ValueError, match="physical class"):
        reducer.restore(reducer.paths, sources, at(10))
    assert (reducer.paths, reducer.sources) == before


def test_endpoint_off_retains_authority_but_removed_ordinary_origin_does_not() -> None:
    scene = Scene(2)
    scene.reducer = populated()
    for node, seconds in (("a", 0), ("b", 1)):
        scene.fact(node, seconds)
    scene.clear("b", 3)
    assert not scene.located[0].endpoint.branch_active
    assert scene.located[0].endpoint_eligible
    scene.restart(86400)
    assert scene.located[0].endpoint_eligible
    assert scene.reducer.covered_nodes == frozenset({"a", "b"})


def test_pure_path_transition_does_not_promote_from_older_correlated_triple() -> None:
    scene = Scene(1)
    visits = tuple(SelectedVisit(
        n, n, f"{n}:1:{at(i).isoformat()}", at(i),
        "positive" if i == 0 else "correlated_positive",
    ) for i, n in enumerate(("a", "b", "c")))
    path = SelectedPath(visits, visits, at(2))
    resident = SelectedVisit(
        "presence", "c", f"presence:1:{at(3).isoformat()}", at(3), "positive",
    )
    next_path = scene.reducer._advance_path(path, 2, resident)
    assert next_path.track_confidence == "provisional"
    assert next_path.spatial_at == at(2)


def test_pure_branch_relocation_updates_spatial_frontier_without_fake_visit() -> None:
    scene = Scene(1)
    visits = tuple(SelectedVisit(n, n, f"{n}:1:{at(i).isoformat()}", at(i), "positive")
                   for i, n in enumerate(("a", "b", "c")))
    path = SelectedPath(visits, visits, at(2), "confirmed")
    resident = SelectedVisit("a", "a", f"a:2:{at(3).isoformat()}", at(3), "positive")
    next_path = scene.reducer._advance_path(path, 0, resident)
    assert next_path.spatial_at == at(3)
    assert tuple(v.node_id for v in next_path.route) == ("a", "a")
    assert tuple(v.at for v in next_path.route) == (at(0), at(3))
    assert all(not v.branch_active for v in next_path.visits[1:3])


def test_pure_transition_keeps_both_bounds_over_long_observed_route() -> None:
    scene = Scene(1)
    first = SelectedVisit("a", "a", f"a:1:{NOW.isoformat()}", NOW, "positive")
    path = SelectedPath((first,), (first,), NOW)
    for seconds in range(1, 100):
        node = "a" if seconds % 2 == 0 else "b"
        generation = seconds // 2 + 1
        visit = SelectedVisit(
            node, node, f"{node}:{generation}:{at(seconds).isoformat()}",
            at(seconds), "positive",
        )
        path = scene.reducer._advance_path(path, len(path.route) - 1, visit)
        assert 1 <= len(path.visits) <= 4 and 1 <= len(path.route) <= 4
        assert path.endpoint == visit
        assert path.track_confidence == "provisional"


@pytest.mark.parametrize("defect", (
    "unobserved_spatial", "correlated_admission", "confirmed_singleton",
    "revoked_active_endpoint", "split_generation_chronology",
))
def test_restore_rejects_impossible_admission_and_frontiers(defect: str) -> None:
    reducer = populated()
    before = reducer.paths, reducer.sources
    paths, sources = wire(reducer)
    path = paths[0]
    match defect:
        case "unobserved_spatial":
            path["spatial_at"] = at(-1).isoformat()
        case "correlated_admission":
            for key in ("visits", "route"):
                path[key] = [path[key][-1]]
                path[key][0]["kind"] = "correlated_positive"
            sources[1]["origin"] = "correlated"
        case "confirmed_singleton":
            for key in ("visits", "route"):
                path[key] = [path[key][-1]]
            path["track_confidence"] = "confirmed"
        case "revoked_active_endpoint":
            path["endpoint_eligible"] = False
        case "split_generation_chronology":
            path["visits"][0].update(
                episode_id=f"a:2:{at(0).isoformat()}", branch_active=False,
            )
            path["route"][0].update(
                episode_id=f"a:1:{at(1).isoformat()}", at=at(1).isoformat(),
                branch_active=False,
            )
            sources[0].update(episode_id=f"a:3:{at(3).isoformat()}",
                              at=at(3).isoformat())
    with pytest.raises(ValueError):
        reducer.restore(decode_paths(paths), decode_sources(sources), at(10))
    assert (reducer.paths, reducer.sources) == before

