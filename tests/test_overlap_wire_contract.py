"""Synthetic real-producer qualification for PATH007/008 and DIAG011.

Not the frozen September 16 incident, a latent-state reconstruction, HA service
test, or persistence qualification. Borrow the unchanged runtime/freezer harness;
all selection/episode/status records come from cold startup and real deliveries.
The same production-parsed YAML map goes to inference and the Node consumer.
No dataclass dump: optional None defaults are not fields in the config endpoint's
YAML document. No status fields are patched to manufacture positive specimens.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import runtime_status_payload
from custom_components.predictive_controls.yaml_config import (
    dump_yaml_document,
    load_predictive_map,
    load_yaml_document,
)
from tests.runtime_replay import RuntimeReplay, RuntimeScenario

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
pytestmark = pytest.mark.target_model


class Frame(TypedDict):
    name: str
    status: dict[str, object]
    routes: list[list[str] | None]
    overlaps: list[list[list[str]]]
    presence: list[str]
    history: list[str]
    candidates: list[str]
    corrupt: bool


def _map() -> tuple[PredictiveMap, str]:
    edges = (
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"),
        ("a", "x"), ("x", "y"), ("y", "z"), ("z", "w"), ("b", "h"),
    )
    rooms = {"c", "d", "e", "h", "w"}
    names = sorted({name for edge in edges for name in edge})
    document = dump_yaml_document({"nodes": {
        name: {
            "zone": name,
            "label": f"{'Room' if name in rooms else 'Transit'} {name.upper()}",
            "role": "room_occupancy" if name in rooms else "transition_gate",
            "entities": {"motion": f"binary_sensor.{name}"},
            "adjacent": sorted({
                b if a == name else a for a, b in edges if name in (a, b)
            }),
        }
        for name in names
    }})
    return load_predictive_map(document), document


def _at(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _send(replay: RuntimeReplay, node: str, state: str, seconds: int) -> None:
    replay.send(f"binary_sensor.{node}", state, _at(seconds))


def _capture(
    replay: RuntimeReplay, frames: list[Frame], name: str,
    routes: list[list[str] | None], overlaps: list[list[list[str]]],
    *, presence: str = "", history: str = "", candidates: str = "",
    corrupt: bool = False,
) -> None:
    # This is the actual WebSocket status producer, not a mirror of its schema.
    status = runtime_status_payload(replay.runtime)
    diagnostics = status["occupancy_diagnostics"]
    assert diagnostics["selected_path_version"] == 2
    assert diagnostics["unsupported_count"] is None
    paths = diagnostics["selected_paths"]
    assert len(paths) == len(routes) == status["expected_occupants"]
    assert [None if p is None else [v["node_id"] for v in p["route"]]
            for p in paths] == routes, name
    assert [[] if p is None else [
        [v["node_id"] for v in branch] for branch in p["branch_routes"]
    ] for p in paths] == overlaps, name
    # Observation chronology can contain C then X, but no configured C-X edge.
    assert "x" not in replay.map.neighbors("c")
    assert "c" not in replay.map.neighbors("x")
    frames.append({
        "name": name, "status": status, "routes": routes, "overlaps": overlaps,
        "presence": presence.split(), "history": history.split(),
        "candidates": candidates.split(), "corrupt": corrupt,
    })


def _consume(frames: list[Frame], mapping: PredictiveMap, document: str) -> None:
    # websocket._entry_payload uses load_yaml_document on this same map_yaml.
    # Preserve omission of floor/occupancy_behavior; do not serialize None as
    # strict frontend optional strings, or substitute a zone-only drawing map.
    wire_map = load_yaml_document(document)
    assert PredictiveMap.from_mapping(wire_map) == mapping
    assert all("floor" not in node and "occupancy_behavior" not in node
               for node in wire_map["nodes"].values())
    result = subprocess.run(
        ["node", str(ROOT / "tests/frontend/support/overlap_contract.mjs")],
        input=json.dumps({"map": wire_map, "map_yaml": document, "frames": frames}),
        text=True, capture_output=True, cwd=ROOT, timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["validated_frames"] == len(frames)
    assert report["corruption_checks"] == 2
    assert report["transport_recoveries"] == 1
    for relative, digest in report["artifacts"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    assert set(report["artifacts"]) == {
        "frontend/decoders.ts", "frontend/paths.ts",
        "custom_components/predictive_controls/frontend/panel-v0.2.6.js",
    }
    print(json.dumps(report, sort_keys=True))


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("ending", ("clear", "unknown", "eviction", "continuation"))
def test_real_overlap_producer_to_source_and_shipped_panel(
    count: int, ending: str,
) -> None:
    mapping, document = _map()
    frames: list[Frame] = []
    empty_slots: list[list[str] | None] = [None] * (count - 1)
    empty_overlaps: list[list[list[str]]] = [[] for _ in empty_slots]
    main = ["a", "x", "y", "z"]
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(
            mapping, count,
            initial_states=dict.fromkeys(mapping.entity_ids(), "off"),
        )
        _capture(replay, frames, "cold", [None] * count, [[] for _ in range(count)])
        for seconds, node in enumerate(("a", "b", "c"), 1):
            _send(replay, node, "on", seconds)
        _capture(
            replay, frames, "observed-abc", [["a", "b", "c"], *empty_slots],
            [[], *empty_overlaps], presence="a b c", candidates="d h x",
        )
        _send(replay, "x", "on", 4)
        _capture(
            replay, frames, "fork", [["a", "x"], *empty_slots],
            [[["a", "b"], ["a", "b", "c"]], *empty_overlaps],
            presence="a b c x", candidates="d h y", corrupt=True,
        )
        for seconds, node in enumerate(("y", "z"), 5):
            _send(replay, node, "on", seconds)
        _capture(
            replay, frames, "prefix-only-b", [main, *empty_slots],
            [[["a", "b", "c"]], *empty_overlaps],
            presence="a c x y z", history="b", candidates="d w",
        )
        before = replay.runtime.confidence.diagnostics
        selected = before.selected_paths[0]
        assert selected is not None
        assert [v.node_id for v in selected.visits] == ["c", "x", "y", "z"]
        assert not selected.branch_routes[0][1].branch_active
        old_c = selected.branch_routes[0][-1].episode_id
        assert next(s for s in before.path_health if s.node_id == "b").phase == "on"

        if ending == "continuation":
            # C is the oldest pre-input tip. D promotes the witnessed prefix
            # before C leaves last-four history, without rearming prefix-only B.
            _send(replay, "d", "on", 7)
            _capture(
                replay, frames, "tip-continues-before-history-eviction",
                [["a", "b", "c", "d"], *empty_slots],
                [[["a", "x"], ["a", "x", "y"], main], *empty_overlaps],
                presence="a c d x y z", history="b", candidates="e w",
            )
            current = replay.runtime.confidence.diagnostics.selected_paths[0]
            assert current is not None
            assert current.route[-2].episode_id == old_c
            assert all(v.node_id != "c" for v in current.visits)
            assert not current.route[1].branch_active
        else:
            if ending == "eviction":
                _send(replay, "w", "on", 7)
                main = ["x", "y", "z", "w"]
                current_presence, current_candidates = "x y z w", "a"
            else:
                _send(replay, "c", "off" if ending == "clear" else "unknown", 7)
                current_presence, current_candidates = "a x y z", "b w"
            if ending == "clear":
                _capture(
                    replay, frames, "clearing-tip-is-history-not-presence",
                    [main, *empty_slots], [[["a", "b", "c"]], *empty_overlaps],
                    presence="a x y z", history="b c", candidates="w",
                )
            else:
                _capture(
                    replay, frames, f"{ending}-removes-overlap", [main, *empty_slots],
                    [[], *empty_overlaps], presence=current_presence,
                    candidates=current_candidates,
                )
            # The existing runtime's five-second timer processes stable clear.
            replay.advance(_at(15))
            _capture(
                replay, frames, "timer-after-removal", [main, *empty_slots],
                [[], *empty_overlaps], presence=current_presence,
                candidates=current_candidates,
            )
            episode = next(
                s for s in replay.runtime.confidence.diagnostics.episode_states
                if s.node_id == "c"
            )
            assert episode.status == {
                "clear": "clear", "unknown": "unavailable", "eviction": "asserted",
            }[ending]
            _send(replay, "c", "on", 16)
            _capture(
                replay, frames, "raw-on-does-not-rearm-removed-tip",
                [main, *empty_slots], [[], *empty_overlaps], presence=current_presence,
                candidates=current_candidates,
            )
            # Separate fresh pair, not a restored old tip: allow the unchanged
            # hardware/correlation interval to pass following an actual OFF.
            _send(replay, "c", "off", 17)
            _send(replay, "c", "on", 70)
            _capture(
                replay, frames, "fresh-origin-is-not-yet-selected",
                [main, *empty_slots], [[], *empty_overlaps], presence=current_presence,
                candidates=current_candidates,
            )
            new_c = next(s for s in replay.runtime.confidence.diagnostics.episode_states
                         if s.node_id == "c").episode_id
            assert new_c != old_c
            _send(replay, "d", "on", 71)
            # N=1 replaces the old slot; N=2 locates its existing U slot. This
            # is a second real pair, never an extra slot created by overlap.
            _capture(
                replay, frames, "fresh-pair-recovery",
                [["c", "d"]] if count == 1 else [main, ["c", "d"]],
                [[] for _ in range(count)],
                presence="c d" if count == 1 else f"{current_presence} c d",
                candidates="b e" if count == 1 else f"{current_candidates} b e",
            )
            recovered = replay.runtime.confidence.diagnostics.selected_paths[-1]
            assert recovered is not None and recovered.route[0].episode_id == new_c

        replay.send("sensor.replay_people", "0", _at(72))
        _capture(replay, frames, "count-zero-no-fallback", [], [])
        assert all(d.delivered and d.retained_input is None for d in replay.deliveries)
        _consume(frames, mapping, document)
