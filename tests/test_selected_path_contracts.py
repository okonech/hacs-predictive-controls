"""Non-scenario selected-record and reducer boundary contracts.

REQ-PATH-001..004/006, PATH-STATE-001 and STATE-001/002/008. These are
synthetic component qualifications, not captured incidents or public-light
scenarios. PhysicalEpisodes supplies real effects to SelectedPaths; corruptions
exercise the production record/restore owners, never a copied validator or an
invented engine state. See completion-selected-boundaries.md for the pre-edit
mapping, the unexecuted validation handoff and the redundant-origin analysis.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from re import escape

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

_NOW = datetime(2026, 9, 14, tzinfo=UTC)
type _Snapshot = tuple[
    tuple[SelectedPath | None, ...], tuple[SelectedSource, ...], datetime | None,
]


def _at(seconds: int) -> datetime:
    return _NOW + timedelta(seconds=seconds)


def _reconstruct_invalid[T: (SelectedVisit, SelectedPath)](
    record: T, changes: dict[str, object],
) -> T:
    """Send wrong-type init fields through the actual validating constructor.

    These records have only init fields. Preserve nested objects rather than
    using asdict, and never bypass __post_init__ with frozen-object mutation.
    Normal and type-correct malformed values use explicit replace fields instead.
    """
    values: dict[str, object] = {
        field.name: getattr(record, field.name) for field in fields(record)
    }
    values.update(changes)
    construct: Callable[..., T] = type(record)
    return construct(**values)


def _map(*, overlap: bool = False) -> PredictiveMap:
    edges = (
        ("a", "b"), ("b", "f"), ("f", "g"), ("g", "c"),
        ("x", "y"), ("y", "c"), ("c", "d"), ("c", "e"),
    ) if overlap else (
        ("a", "b"), ("b", "c"), ("c", "d"), ("a", "x"), ("x", "y"),
    )
    names = sorted({node for edge in edges for node in edge})
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "room_occupancy",
            "entities": {"mmwave": f"binary_sensor.{node}"},
            "adjacent": sorted({b if a == node else a for a, b in edges
                                if node in (a, b)}),
        } for node in names
    }})


def _snapshot(selected: SelectedPaths) -> _Snapshot:
    return selected.paths, selected.sources, selected._at


def _path(selected: SelectedPaths, endpoint: str | None = None) -> SelectedPath:
    return next(path for path in selected.paths if path is not None
                and (endpoint is None or path.endpoint.node_id == endpoint))


def _deliver(
    episodes: PhysicalEpisodes, reducers: tuple[SelectedPaths, ...],
    node: str, value: str, seconds: int,
) -> tuple[TraversalAuthorization | None, ...]:
    """Deliver one real physical input to independent component consumers."""
    episodes.advance(_at(seconds))
    before = episodes.states
    for selected in reducers:
        selected.reconcile(before, _at(seconds))
    update = episodes.observe(SensorInput(f"binary_sensor.{node}", value, _at(seconds)))
    results: list[TraversalAuthorization | None] = []
    for selected in reducers:
        authorization = None
        for effect in update.effects:
            if effect.kind in {"positive", "correlated_positive", "interaction"}:
                authorization = selected.observe(
                    effect, update.state, episodes.states, before=before,
                )
        selected.reconcile(episodes.states, _at(seconds))
        results.append(authorization)
    return tuple(results)


class _Owners:
    """Local physical/selection owners, with no engine or shared-harness changes."""

    def __init__(
        self, mapping: PredictiveMap | None = None, *, count: int = 2,
    ) -> None:
        self.map = _map() if mapping is None else mapping
        built = build_physical_nodes(self.map)
        assert not built.errors
        self.nodes = built.nodes
        self.episodes = PhysicalEpisodes(self.nodes)
        self.selected = SelectedPaths(self.map, self.nodes, count)

    def send(
        self, node: str, value: str, seconds: int,
    ) -> TraversalAuthorization | None:
        return _deliver(self.episodes, (self.selected,), node, value, seconds)[0]

    def clone(self, seconds: int) -> SelectedPaths:
        clone = SelectedPaths(self.map, self.nodes, len(self.selected.paths))
        clone.restore(self.selected.paths, self.selected.sources, _at(seconds))
        return clone


def _pair() -> _Owners:
    owners = _Owners()
    assert owners.send("a", "on", 0) is None
    authorization = owners.send("b", "on", 1)
    assert authorization is not None and authorization.path_node_ids == ("a", "b")
    return owners


def _overlap(*, rebind: bool = True) -> _Owners:
    owners = _Owners(_map(overlap=True))
    for node, value, seconds in (
        ("a", "on", 0), ("b", "on", 1), ("x", "on", 2), ("y", "on", 3),
        ("c", "on", 4), ("c", "off", 5), ("f", "on", 20), ("g", "on", 21),
        ("c", "on", 22), ("d", "on", 23), ("d", "unavailable", 24),
        ("c", "off", 25),
    ):
        owners.send(node, value, seconds)
    if rebind:
        authorization = owners.send("c", "on", 40)
        assert authorization is not None
        assert authorization.selected_source_episode_ids == (
            f"c:1:{_at(4).isoformat()}",
        )
    return owners


def _wire_visit(visit: SelectedVisit) -> dict[str, object]:
    return {
        "node_id": visit.node_id, "zone": visit.zone,
        "episode_id": visit.episode_id, "at": visit.at.isoformat(),
        "kind": visit.kind, "branch_active": visit.branch_active,
    }


def _wire(
    paths: tuple[SelectedPath | None, ...], sources: tuple[SelectedSource, ...],
) -> tuple[list[object], list[object]]:
    """Only JSON projection; production decoders own every validation decision."""
    raw_paths: list[object] = [None if path is None else {
        "visits": [_wire_visit(visit) for visit in path.visits],
        "route": [_wire_visit(visit) for visit in path.route],
        "spatial_at": path.spatial_at.isoformat(),
        "track_confidence": path.track_confidence,
        "endpoint_eligible": path.endpoint_eligible,
        "branch_routes": [[_wire_visit(visit) for visit in witness]
                  for witness in path.branch_routes],
    } for path in paths]
    raw_sources: list[object] = [{
        "node_id": source.node_id, "episode_id": source.episode_id,
        "at": None if source.at is None else source.at.isoformat(),
        "origin": source.origin, "consumed": source.consumed,
    } for source in sources]
    return raw_paths, raw_sources


def _occurrence(
    visit: SelectedVisit, seconds: int, generation: int | None = None,
) -> SelectedVisit:
    if generation is None:
        number = visit.episode_id.split(":", 2)[1]
    else:
        number = str(generation)
    return replace(
        visit, at=_at(seconds),
        episode_id=f"{visit.node_id}:{number}:{_at(seconds).isoformat()}",
    )


def _replace_visit(
    path: SelectedPath, original: SelectedVisit, changed: SelectedVisit,
) -> SelectedPath:
    """One occurrence edit must retain its shared route/history/spatial identity."""
    return replace(
        path,
        visits=tuple(changed if visit == original else visit for visit in path.visits),
        route=tuple(changed if visit == original else visit for visit in path.route),
        spatial_at=changed.at if path.spatial_at == original.at else path.spatial_at,
    )


def _replace_path(
    selected: SelectedPaths, original: SelectedPath, changed: SelectedPath,
) -> tuple[SelectedPath | None, ...]:
    return tuple(changed if path == original else path for path in selected.paths)


def _assert_next_input(
    receiver: _Owners, control: SelectedPaths, node: str, seconds: int,
) -> None:
    first, second = _deliver(
        receiver.episodes, (receiver.selected, control), node, "on", seconds,
    )
    assert first is not None and first.authorized
    assert first == second
    assert _snapshot(receiver.selected) == _snapshot(control)
    assert _snapshot(receiver.clone(seconds)) == _snapshot(receiver.selected)


def _assert_restore_rejected(
    donor: _Owners, paths: tuple[SelectedPath | None, ...], message: str,
) -> None:
    original = _snapshot(donor.selected)
    baseline = _wire(donor.selected.paths, donor.selected.sources)
    baseline_copy = deepcopy(baseline)
    accepted = SelectedPaths(donor.map, donor.nodes, 2)
    accepted.restore(decode_paths(baseline[0]), decode_sources(baseline[1]), _at(50))
    assert accepted.paths == donor.selected.paths
    assert accepted.sources == donor.selected.sources
    assert baseline == baseline_copy

    incoming = _wire(paths, donor.selected.sources)
    incoming_copy = deepcopy(incoming)
    # Decode first: malformed leaves must not mask the intended restore guard.
    decoded_paths = decode_paths(incoming[0])
    decoded_sources = decode_sources(incoming[1])
    assert decoded_paths == paths and decoded_sources == donor.selected.sources
    decoded_before = deepcopy((decoded_paths, decoded_sources))
    receiver = _Owners(donor.map)
    assert receiver.send("a", "on", 100) is None
    assert receiver.send("b", "on", 101) is not None
    control = receiver.clone(101)
    before = _snapshot(receiver.selected)
    physical_before = receiver.episodes.states
    assert before != original  # Neither empty nor the donor's installed state.
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        receiver.selected.restore(decoded_paths, decoded_sources, _at(50))
    assert _snapshot(receiver.selected) == before == _snapshot(control)
    assert receiver.episodes.states == physical_before
    assert (decoded_paths, decoded_sources) == decoded_before
    assert incoming == incoming_copy
    assert _snapshot(donor.selected) == original
    next_node = "f" if "f" in donor.map.nodes else "c"
    _assert_next_input(receiver, control, next_node, 103)


@pytest.mark.parametrize("defect", (
    "empty-node", "nontext-zone", "foreign-episode", "nonselected-kind",
    "integer-branch",
))
def test_visit_record_rejects_identity_or_kind_corruption(defect: str) -> None:
    visit = _path(_pair().selected).endpoint
    assert replace(visit) == visit
    before = deepcopy(visit)
    changes: dict[str, object]
    if defect == "empty-node":
        changes = {"node_id": ""}
        message = "Selected identity must be a nonempty string"
    elif defect == "nontext-zone":
        changes = {"zone": 1}
        message = "Selected identity must be a nonempty string"
    elif defect == "foreign-episode":
        changes = {"episode_id": f"a:1:{visit.at.isoformat()}"}
        message = "Selected episode belongs to another node"
    else:
        changes = {"kind": "stable_clear"} if defect == "nonselected-kind" else {
            "branch_active": 1,
        }
        message = "Selected visit kind or branch flag is invalid"
    changes_before = deepcopy(changes)
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        if defect == "empty-node":
            replace(visit, node_id="")
        elif defect == "foreign-episode":
            replace(visit, episode_id=f"a:1:{visit.at.isoformat()}")
        elif defect == "nonselected-kind":
            replace(visit, kind="stable_clear")
        else:
            _reconstruct_invalid(visit, changes)
    assert changes == changes_before and visit == before


@pytest.mark.parametrize("defect", (
    "integer-endpoint", "invalid-history-record", "invalid-route-record",
    "duplicate-history", "duplicate-route",
))
def test_path_record_rejects_structural_corruption(defect: str) -> None:
    path = _path(_pair().selected)
    assert replace(path) == path
    before = deepcopy(path)
    changes: dict[str, object]
    if defect == "integer-endpoint":
        changes = {"endpoint_eligible": 1}
        message = "Selected endpoint eligibility must be boolean"
    else:
        field = "visits" if "history" in defect else "route"
        if defect.startswith("invalid"):
            changes = {field: ("torn-record", path.endpoint)}
            message = "Selected path contains an invalid visit"
        else:
            changes = {field: (path.visits[0], path.visits[0], path.endpoint)}
            message = "Selected path repeats an observation"
    changes_before = deepcopy(changes)
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        if defect == "duplicate-history":
            replace(path, visits=(path.visits[0], path.visits[0], path.endpoint))
        elif defect == "duplicate-route":
            replace(path, route=(path.visits[0], path.visits[0], path.endpoint))
        else:
            _reconstruct_invalid(path, changes)
    assert path == before and changes == changes_before


def test_history_and_route_cannot_retime_one_generation() -> None:
    owners = _overlap()
    assert owners.send("e", "on", 41) is not None
    path = _path(owners.selected, "e")
    old = next(visit for visit in path.visits if visit.at == _at(4))
    assert old in path.route and not old.branch_active
    assert path.spatial_at == _at(41)
    assert owners.clone(41).paths == owners.selected.paths
    before = _snapshot(owners.selected)
    history = tuple(_occurrence(visit, 5) if visit == old else visit
                    for visit in path.visits)
    incoming_before = deepcopy(history)
    with pytest.raises(
        ValueError, match="^Selected generation has conflicting occurrences$",
    ):
        replace(path, visits=history)
    assert history == incoming_before and _snapshot(owners.selected) == before
    control = owners.clone(41)
    _assert_next_input(owners, control, "d", 42)


def test_retired_history_cannot_regain_branch_authority() -> None:
    owners = _pair()
    assert owners.send("c", "on", 2) is not None
    assert owners.send("x", "on", 3) is not None
    # A supported overlap is not corruption; first truly revoke this C tip.
    assert owners.send("c", "unavailable", 3) is None
    path = _path(owners.selected)
    assert tuple(visit.node_id for visit in path.route) == ("a", "x")
    retired = next(visit for visit in path.visits if visit.node_id == "c")
    assert not retired.branch_active and retired not in path.route
    assert owners.clone(3).paths == owners.selected.paths
    before = _snapshot(owners.selected)
    history = tuple(replace(visit, branch_active=True) if visit == retired else visit
                    for visit in path.visits)
    incoming_before = deepcopy(history)
    with pytest.raises(
        ValueError, match="^Retired history cannot retain branch authority$",
    ):
        replace(path, visits=history)
    assert history == incoming_before and _snapshot(owners.selected) == before
    _assert_next_input(owners, owners.clone(3), "y", 4)


@pytest.mark.parametrize("defect", (
    "unobserved-episode", "unobserved-time", "unobserved-consumed",
    "ordinary-without-episode", "ordinary-without-time",
))
def test_source_record_rejects_incomplete_provenance(defect: str) -> None:
    observed = _pair().selected.sources[0]
    assert observed.origin == "ordinary" and observed.consumed
    source = observed
    if defect.startswith("unobserved"):
        source = SelectedSource(observed.node_id)
    assert replace(source) == source
    before = deepcopy(source)
    changes: dict[str, object]
    if defect == "unobserved-episode":
        changes = {"episode_id": observed.episode_id}
    elif defect == "unobserved-time":
        changes = {"at": observed.at}
    elif defect == "unobserved-consumed":
        changes = {"consumed": True}
    elif defect == "ordinary-without-episode":
        changes = {"episode_id": None}
    else:
        changes = {"at": None}
    message = "An unobserved source cannot carry provenance" if defect.startswith(
        "unobserved",
    ) else "Observed source requires its episode and occurrence"
    changes_before = deepcopy(changes)
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        if defect == "unobserved-episode":
            replace(source, episode_id=observed.episode_id)
        elif defect == "unobserved-time":
            replace(source, at=observed.at)
        elif defect == "unobserved-consumed":
            replace(source, consumed=True)
        elif defect == "ordinary-without-episode":
            replace(source, episode_id=None)
        else:
            replace(source, at=None)
    assert source == before and changes == changes_before


@pytest.mark.parametrize("count", (
    pytest.param(-1, id="negative"), pytest.param(3, id="above-two"),
    pytest.param(True, id="true"), pytest.param(False, id="false"),
))
def test_constructor_rejects_invalid_count(count: int) -> None:
    owners = _Owners()
    before = deepcopy(owners.nodes)
    for valid in (0, 1, 2):
        assert SelectedPaths(owners.map, owners.nodes, valid).paths == (None,) * valid
    with pytest.raises(
        ValueError, match=r"^Selected count must be an integer in \[0, 2\]$",
    ):
        SelectedPaths(owners.map, owners.nodes, count)
    assert owners.nodes == before
    assert owners.selected.paths == (None, None)


@pytest.mark.parametrize("defect", (
    "missing-node", "duplicate-node", "foreign-node", "wrong-zone", "wrong-alias",
))
def test_constructor_requires_exact_physical_map(defect: str) -> None:
    owners = _pair()
    original = owners.nodes
    assert SelectedPaths(owners.map, original, 2).paths == (None, None)
    if defect == "missing-node":
        nodes = original[1:]
    elif defect == "duplicate-node":
        nodes = (*original, original[0])
    elif defect == "foreign-node":
        nodes = (replace(original[0], node_id="foreign"), *original[1:])
    elif defect == "wrong-zone":
        nodes = (replace(original[0], zone="wrong"), *original[1:])
    else:
        nodes = (replace(original[0], aliases=("binary_sensor.wrong",)), *original[1:])
    before = deepcopy(nodes)
    receiver_before = _snapshot(owners.selected)
    message = "Selected physical node disagrees with its map" if defect.startswith(
        "wrong",
    ) else "Selected nodes must exactly match the physical map"
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        SelectedPaths(owners.map, nodes, 2)
    assert nodes == before and owners.nodes == original
    assert _snapshot(owners.selected) == receiver_before


def test_stale_reconcile_cannot_revoke_current_selection() -> None:
    owners = _Owners()
    old_baseline = owners.episodes.states
    assert owners.send("a", "on", 0) is None
    assert owners.send("b", "on", 1) is not None
    owners.episodes.advance(_at(10))
    owners.selected.reconcile(owners.episodes.states, _at(10))
    control = owners.clone(10)
    before = _snapshot(owners.selected)
    incoming_before = deepcopy(old_baseline)
    owners.selected.reconcile(old_baseline, _at(0))
    assert _snapshot(owners.selected) == before
    assert old_baseline == incoming_before
    _assert_next_input(owners, control, "c", 11)


@pytest.mark.parametrize("defect", (
    "duplicate-node", "future-start", "future-event", "future-advance",
))
def test_reconcile_rejects_torn_physical_snapshot(defect: str) -> None:
    owners = _pair()
    owners.episodes.advance(_at(10))
    current = owners.episodes.states
    owners.selected.reconcile(current, _at(10))  # Equality is accepted first.
    control = owners.clone(10)
    if defect == "duplicate-node":
        incoming = (*current, current[0])
        message = "Selected reconciliation repeats a physical node"
    else:
        if defect == "future-start":
            changed = replace(current[0], started_at=_at(20))
        elif defect == "future-event":
            changed = replace(current[0], last_event_at=_at(20))
        else:
            changed = replace(current[0], advanced_at=_at(20))
        incoming = (changed, *current[1:])
        message = "Selected reconciliation cannot use future episode state"
    incoming_before = deepcopy(incoming)
    before = _snapshot(owners.selected)
    with pytest.raises(ValueError, match=f"^{escape(message)}$"):
        owners.selected.reconcile(incoming, _at(10))
    assert incoming == incoming_before
    assert owners.episodes.states == current
    assert _snapshot(owners.selected) == before
    _assert_next_input(owners, control, "c", 11)


def _fresh_target(
    owners: _Owners,
) -> tuple[EpisodeEffect, EpisodeState, tuple[EpisodeState, ...]]:
    owners.episodes.advance(_at(3))
    before = owners.episodes.states
    owners.selected.reconcile(before, _at(3))
    update = owners.episodes.observe(SensorInput("binary_sensor.c", "on", _at(3)))
    effects = tuple(effect for effect in update.effects if effect.kind == "positive")
    assert len(effects) == 1
    return effects[0], update.state, before


def test_observe_rejects_generation_disagreement_without_consuming_input() -> None:
    owners = _pair()
    effect, state, basis = _fresh_target(owners)
    current = owners.episodes.states
    control = owners.clone(3)
    accepted = control.observe(effect, state, current, before=basis)
    assert accepted is not None and accepted.path_node_ids == ("a", "b", "c")
    malformed = replace(state, generation=state.generation + 1)
    incoming = tuple(malformed if item == state else item for item in current)
    incoming_before = deepcopy((effect, malformed, incoming, basis))
    before = _snapshot(owners.selected)
    assert owners.selected.observe(effect, malformed, incoming, before=basis) is None
    assert _snapshot(owners.selected) == before
    assert (effect, malformed, incoming, basis) == incoming_before
    assert owners.episodes.states == current
    assert owners.selected.observe(effect, state, current, before=basis) == accepted
    assert _snapshot(owners.selected) == _snapshot(control)
    assert owners.selected.observe(effect, state, current) is None
    assert _snapshot(owners.selected) == _snapshot(control)
    _assert_next_input(owners, control, "d", 4)


@pytest.mark.parametrize("defect", (
    "missing-target", "duplicate-target", "different-target",
))
def test_observe_requires_complete_current_target(defect: str) -> None:
    owners = _pair()
    effect, state, basis = _fresh_target(owners)
    current = owners.episodes.states
    control = owners.clone(3)
    accepted = control.observe(effect, state, current, before=basis)
    assert accepted is not None and accepted.path_node_ids == ("a", "b", "c")
    if defect == "missing-target":
        incoming = tuple(item for item in current if item.node_id != state.node_id)
    elif defect == "duplicate-target":
        incoming = (*current, state)
    else:
        incoming = tuple(replace(item, generation=item.generation + 1)
                         if item == state else item for item in current)
    incoming_before = deepcopy((effect, state, incoming, basis))
    before = _snapshot(owners.selected)
    with pytest.raises(
        ValueError, match="^Selected observation requires the current target state$",
    ):
        owners.selected.observe(effect, state, incoming, before=basis)
    assert _snapshot(owners.selected) == before
    assert (effect, state, incoming, basis) == incoming_before
    assert owners.episodes.states == current
    assert owners.selected.observe(effect, state, current, before=basis) == accepted
    assert _snapshot(owners.selected) == _snapshot(control)
    _assert_next_input(owners, control, "d", 4)


def test_retained_endpoint_rebind_preserves_newer_source_ledger() -> None:
    owners = _overlap(rebind=False)
    retained = _path(owners.selected, "c")
    assert retained.endpoint.episode_id == f"c:1:{_at(4).isoformat()}"
    assert not retained.endpoint_eligible and not retained.endpoint.branch_active
    latest = next(source for source in owners.selected.sources if source.node_id == "c")
    assert latest.episode_id == f"c:2:{_at(22).isoformat()}" and latest.consumed
    other = _path(owners.selected, "d")
    assert not other.endpoint_eligible
    restored = owners.clone(25)
    first, second = _deliver(
        owners.episodes, (owners.selected, restored), "c", "on", 40,
    )
    assert first is not None and first == second
    assert first.selected_source_episode_ids == (retained.endpoint.episode_id,)
    assert first.target_episode_id == f"c:3:{_at(40).isoformat()}"
    current = next(source for source in owners.selected.sources
                   if source.node_id == "c")
    assert current.episode_id == first.target_episode_id and current.consumed
    assert len(tuple(path for path in owners.selected.paths if path is not None)) == 2
    assert _path(owners.selected, "d").route == tuple(
        replace(visit, branch_active=False) if visit.node_id == "c" else visit
        for visit in other.route
    )
    assert _snapshot(owners.selected) == _snapshot(restored)
    assert _snapshot(owners.clone(40)) == _snapshot(restored)
    _assert_next_input(owners, restored, "e", 41)


@pytest.mark.parametrize("defect", ("future-path", "interaction-on-presence"))
def test_restore_rejects_path_corruption_atomically(defect: str) -> None:
    owners = _pair()
    path = _path(owners.selected)
    if defect == "future-path":
        changed = _occurrence(path.endpoint, 200)
        message = "Selected path occurs after restore"
    else:
        changed = replace(path.endpoint, kind="interaction")
        message = "Selected visit physical class disagrees with map"
    malformed = _replace_visit(path, path.endpoint, changed)
    _assert_restore_rejected(
        owners, _replace_path(owners.selected, path, malformed), message,
    )


@pytest.mark.parametrize("defect", ("branch", "endpoint"))
def test_restore_rejects_superseded_authority(defect: str) -> None:
    owners = _overlap(rebind=defect == "branch")
    path = _path(owners.selected, "c")
    old = next(visit for visit in path.route if visit.at == _at(4))
    assert not old.branch_active
    if defect == "endpoint":
        assert path.endpoint == old and not path.endpoint_eligible
        malformed = replace(path, endpoint_eligible=True)
    else:
        assert path.endpoint != old
        malformed = _replace_visit(path, old, replace(old, branch_active=True))
    _assert_restore_rejected(
        owners, _replace_path(owners.selected, path, malformed),
        "Superseded generation cannot supply authority",
    )


@pytest.mark.parametrize("defect", ("conflicting-occurrence", "cross-path-chronology"))
def test_restore_rejects_cross_path_generation_corruption(defect: str) -> None:
    owners = _overlap()
    if defect == "conflicting-occurrence":
        path = _path(owners.selected, "d")
        old = next(visit for visit in path.route if visit.node_id == "c")
        assert old.episode_id == f"c:2:{_at(22).isoformat()}"
        changed = _occurrence(old, 22, generation=1)
        message = "Selected generation has conflicting occurrences"
    else:
        path = _path(owners.selected, "c")
        old = next(visit for visit in path.route if visit.at == _at(4))
        # Both local histories remain ordered: C1@23 precedes C3@40, whereas
        # the other path contains C2@22. Only cross-path chronology detects it.
        changed = _occurrence(old, 23)
        message = "Selected generation chronology differs across paths"
    assert not old.branch_active
    malformed = _replace_visit(path, old, changed)
    _assert_restore_rejected(
        owners, _replace_path(owners.selected, path, malformed), message,
    )
