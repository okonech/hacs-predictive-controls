"""User-reported issue: "I wallked from alex office to upstaris hallway and it
all shows unavailable. Please id and fix this".
User expected: display current occupancy and paths after the walk, not unavailable.
Observed: screenshot says "Expected a Boolean" and all cards lack status. Approved
read-only WebSocket capture succeeded with 17 zones, count2, two selected paths,
and unsupported_count=null at policy frontier2026-09-15T20:56:48.839419Z.
Source: September15 report; screenshot/movement onset time unknown, so receipt
20:56UTC supplies identity. homelab/tmp/panel-unavailable-20260915/status.json,
SHA256 901a1e1ca49366ab990c299bed788fcc1528ae236c0979616d56a5cd1088652d.
Test scope: exact consumed two-zone JSON slice through source decoder AND shipped
panel. Unrelated fields/path data omitted, not replaced by invented sensor events
or U slots. Layout is synthetic. Captured later hallway inactivity is not proof
it never activated. This proves UI rendering, not motion inference or actuation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAPTURED_STATUS = {
    "expected_occupants": 2,
    "zone_states": {
        "alex_office": {
            "confidence": 0.816069260847201,
            "status": "probable",
            "reason": "asserted_stay_hold",
            "occupancy_behavior": "sustained",
            "last_node_id": "alex_office_motion",
        },
        "upstairs_hallway": {
            "confidence": 0.050341895826638734,
            "status": "suspect",
            "reason": "inactive_below_on",
            "occupancy_behavior": "transient",
            "last_node_id": "top_of_staircase_motion",
        },
    },
    "occupancy_diagnostics": {
        "model": "zone_belief",
        "expected_occupants": 2,
        "unsupported_count": None,
        "beliefs": {
            "alex_office": 0.816069260847201,
            "upstairs_hallway": 0.050341895826638734,
        },
        "policy": {
            "alex_office": {
                "active": True, "profile": "stay_presence",
                "pending_release_since": None,
            },
            "upstairs_hallway": {
                "active": False, "profile": "transition_fast",
                "pending_release_since": None,
            },
        },
    },
}


@pytest.mark.scenario
def test_inc_2026_09_15_2056z_panel_status_unavailable() -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests/frontend/support/status_contract.mjs")],
        input=json.dumps([{"status": CAPTURED_STATUS}]), text=True,
        capture_output=True, cwd=ROOT, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validated 1 source-decoder/shipped-panel" in result.stdout
