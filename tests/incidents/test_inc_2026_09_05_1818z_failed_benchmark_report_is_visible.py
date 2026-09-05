from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def test_inc_2026_09_05_1818z_failed_benchmark_report_is_visible(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    occupancy_performance = importlib.import_module(
        "benchmarks.occupancy_performance"
    )
    failed_result: dict[str, object] = {
        "schema_version": 3,
        "fast_paths": {
            "local_interaction": {
                "p99_ms": 5.25,
                "p99_gate": False,
                "max_ms": 5.25,
                "hard_gate": True,
            }
        },
        "passed": False,
    }

    def run_failed_benchmark(*_args: object, **_kwargs: object) -> dict[str, object]:
        return failed_result

    output_path = tmp_path / "failed-performance.json"
    monkeypatch.setattr(occupancy_performance, "run_benchmark", run_failed_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        ["occupancy_performance.py", "--output", str(output_path)],
    )

    with pytest.raises(SystemExit) as raised:
        occupancy_performance.main()

    rendered = json.dumps(failed_result, indent=2, sort_keys=True) + "\n"
    captured = capsys.readouterr()
    assert raised.value.code == 1
    assert output_path.read_text() == rendered
    assert captured.out == ""
    assert captured.err == rendered


def test_successful_benchmark_output_remains_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    occupancy_performance = importlib.import_module(
        "benchmarks.occupancy_performance"
    )
    passed_result: dict[str, object] = {
        "schema_version": 3,
        "passed": True,
    }

    def run_passed_benchmark(*_args: object, **_kwargs: object) -> dict[str, object]:
        return passed_result

    output_path = tmp_path / "passed-performance.json"
    monkeypatch.setattr(occupancy_performance, "run_benchmark", run_passed_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        ["occupancy_performance.py", "--output", str(output_path)],
    )

    occupancy_performance.main()

    rendered = json.dumps(passed_result, indent=2, sort_keys=True) + "\n"
    captured = capsys.readouterr()
    assert output_path.read_text() == rendered
    assert captured.out == ""
    assert captured.err == ""
