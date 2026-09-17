"""Synthetic PATH007/008 and PATH-STATE002 prefix-only authority boundary.

Actual reducer observations evict B from history while retaining its geometric
prefix. A consistent corruption of both copies must fail the constructor/codec,
not an earlier copy/history guard. This is not a captured incident replay.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPaths,
    decode_paths,
)
from tests.test_selected_paths import Scene, at, graph, wire

pytestmark = pytest.mark.target_model


@pytest.mark.parametrize("count", (1, 2))
def test_prefix_only_ancestor_cannot_retain_authority(count: int) -> None:
    scene = Scene(count, graph((
        ("a", "b"), ("b", "c"), ("c", "d"), ("a", "x"),
        ("x", "y"), ("c", "e"),
    )))
    for seconds, node in enumerate(("a", "b", "c", "d", "x", "y")):
        scene.send(node, seconds)
    path = scene.located[0]
    assert "b" not in {v.node_id for v in path.visits}
    assert "b" not in {v.node_id for v in path.authoritative_visits}
    ancestors = tuple(v for v in path.occurrences if v.node_id == "b")
    assert len(ancestors) == 2 and all(not v.branch_active for v in ancestors)
    assert replace(path) == path
    raw, _ = wire(scene.reducer)
    assert decode_paths(raw) == scene.reducer.paths
    before = scene.reducer.paths, scene.reducer.sources, scene.reducer._at
    control = SelectedPaths(scene.map, scene.nodes, count)
    control.restore(before[0], before[1], at(5))
    assert control.paths == before[0] and control.sources == before[1]

    # Alter ALL copies of only the prefix ancestor; valid tips/history stay exact.
    branches = tuple(tuple(replace(v, branch_active=True) if v.node_id == "b"
                           else v for v in prefix) for prefix in path.branch_routes)
    with pytest.raises(
        ValueError, match="^Retired history cannot retain branch authority$",
    ):
        replace(path, branch_routes=branches)
    malformed = deepcopy(raw)
    for prefix in malformed[0]["branch_routes"]:
        for visit in prefix:
            if visit["node_id"] == "b":
                visit["branch_active"] = True
    untouched = deepcopy(malformed)
    with pytest.raises(
        ValueError, match="^Retired history cannot retain branch authority$",
    ):
        scene.reducer.restore(decode_paths(malformed), before[1], at(5))
    assert malformed == untouched
    assert (scene.reducer.paths, scene.reducer.sources, scene.reducer._at) == before
    assert wire(scene.reducer)[0] == raw

    physical_before = scene.current
    effect, state = scene.fact("e", 6)
    actual = scene.reducer.observe(effect, state, scene.current, before=physical_before)
    expected = control.observe(effect, state, scene.current, before=physical_before)
    assert actual == expected and actual is not None
    assert actual.path_node_ids == ("b", "c", "e")
    assert scene.reducer.paths == control.paths
    assert scene.reducer.sources == control.sources
    assert all(not v.branch_active for v in scene.located[0].occurrences
               if v.node_id == "b")
    assert "b" not in scene.reducer.covered_nodes
    scene.restart(6)
