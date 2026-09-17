"""Real runtime producer -> TypeScript decoder -> shipped DOM, not mirrored mocks.

Synthetic counts and observations exercise producer contracts independently of
the retained live panel incident. Never replace inference or snapshot fields.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import runtime_status_payload
from custom_components.predictive_controls.yaml_config import (
    dump_yaml_document,
    load_predictive_map,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPath,
    SelectedVisit,
)
from tests.runtime_replay import RuntimeScenario
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 9, 15, 21, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("count", (0, 1, 2))
def test_real_status_producer_decodes_renders_and_recovers(count: int) -> None:
    mapping = target_map()
    # Config transport uses YAML mappings, not dataclass-only keys/None defaults.
    # Preserve the ACTUAL producer graph and prove normalization is lossless.
    wire_map = json.loads(json.dumps({
        "nodes": {
            key: {name: value for name, value in asdict(node).items()
                  if name != "node_id" and value is not None}
            for key, node in mapping.nodes.items()
        },
        "zones": {
            key: {name: value for name, value in asdict(zone).items()
                  if name != "zone_id" and value is not None}
            for key, zone in mapping.zone_configs.items()
        },
    }))
    document = dump_yaml_document(wire_map)
    assert PredictiveMap.from_mapping(wire_map) == mapping
    assert load_predictive_map(document) == mapping
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(mapping, count)
        replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        payload = runtime_status_payload(replay.runtime)
        assert payload["occupancy_diagnostics"]["unsupported_count"] is None
        assert len(payload["occupancy_diagnostics"]["selected_paths"]) == count
        if count:
            assert payload["occupancy_diagnostics"]["policy"]["room"]["active"]
        cases = [{"status": payload, "recover": True}]
        # HA authoritative-state parsing accepts only 0..5; larger direct
        # diagnostic values are tested independently at the decoder boundary.
        for seconds, unsupported in enumerate((3, 5), 3):
            replay.send("sensor.replay_people", str(unsupported),
                        NOW + timedelta(seconds=seconds))
            rejected = runtime_status_payload(replay.runtime)
            assert rejected["expected_occupants"] == count
            assert rejected["occupancy_diagnostics"]["unsupported_count"] == unsupported
            cases.append({"status": rejected})
        replay.send("sensor.replay_people", str(count), NOW + timedelta(seconds=5))
        recovered = runtime_status_payload(replay.runtime)
        assert recovered["occupancy_diagnostics"]["unsupported_count"] is None
        cases.append({"status": recovered})
        for case in cases:
            case["map"] = wire_map
            case["map_yaml"] = document
        result = subprocess.run(
            ["node", str(ROOT / "tests/frontend/support/status_contract.mjs")],
            input=json.dumps(cases), text=True, capture_output=True,
            cwd=ROOT, timeout=30, check=False, start_new_session=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Validated 4 source-decoder/shipped-panel" in result.stdout


@pytest.mark.parametrize("eligible,active", (
    (True, True), (True, False), (False, False), (False, True),
))
def test_backend_endpoint_wire_boundary(eligible: bool, active: bool) -> None:
    """Actual constructor qualifies the frontend's three valid flag controls."""
    first = SelectedVisit("hall", "hall", f"hall:1:{NOW.isoformat()}",
                          NOW, "positive", False)
    end = SelectedVisit("room", "room", f"room:1:{NOW.isoformat()}",
                        NOW, "positive", active)
    valid = SelectedPath((first, end), (first, end), NOW)
    if not eligible and active:
        with pytest.raises(ValueError, match="Revoked endpoint"):
            replace(valid, endpoint_eligible=eligible)
    else:
        assert replace(valid, endpoint_eligible=eligible).endpoint == end


@pytest.mark.parametrize("node,older,newer", (
    ("hall", 1, 2), ("hall", 9, 10),
    ("hall", 9007199254740992, 9007199254740993), ("node:with:colons", 1, 2),
))
def test_backend_equal_time_generation_wire_boundary(
    node: str, older: int, newer: int,
) -> None:
    """Equal-time SAME-node reversal is invalid; no input-order tie exemption."""
    first = SelectedVisit(node, "hall", f"{node}:{older}:{NOW.isoformat()}",
                          NOW, "positive", False)
    end = SelectedVisit(node, "hall", f"{node}:{newer}:{NOW.isoformat()}",
                        NOW, "positive", False)
    valid = SelectedPath((first, end), (first, end), NOW,
                         endpoint_eligible=False)
    assert valid.visits == (first, end)
    with pytest.raises(ValueError, match="same-node generations are out of order"):
        replace(valid, visits=(end, first), route=(end, first))
