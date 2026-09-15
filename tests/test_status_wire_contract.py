"""Real runtime producer -> TypeScript decoder -> shipped DOM, not mirrored mocks.

Synthetic counts and observations exercise producer contracts independently of
the retained live panel incident. Never replace inference or snapshot fields.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.predictive_controls.status import runtime_status_payload
from tests.runtime_replay import RuntimeScenario
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 9, 15, 21, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("count", (0, 1, 2))
def test_real_status_producer_decodes_renders_and_recovers(count: int) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), count)
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
        result = subprocess.run(
            ["node", str(ROOT / "tests/frontend/support/status_contract.mjs")],
            input=json.dumps(cases), text=True, capture_output=True,
            cwd=ROOT, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Validated 4 source-decoder/shipped-panel" in result.stdout
