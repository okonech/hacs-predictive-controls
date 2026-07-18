from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from benchmarks.occupancy_performance import (
    MAX_BENCHMARK_EVENTS,
    ROUTINE_BENCHMARK_EVENTS,
    TRACE_PROFILES,
    _build_workload,
    _measure_core,
    run_benchmark,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
MAP_PATH = Path(__file__).parents[1] / "benchmarks" / "reference-map.yaml"


@pytest.fixture(scope="module")
def predictive_map() -> PredictiveMap:
    return load_predictive_map(MAP_PATH.read_text())


@pytest.mark.parametrize("profile", TRACE_PROFILES)
def test_benchmark_workloads_cover_target_profiles(
    predictive_map: PredictiveMap,
    profile: str,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=ROUTINE_BENCHMARK_EVENTS,
        started_at=NOW,
        occupants=2,
        trace_profile=profile,
    )

    assert len(workload.events) == ROUTINE_BENCHMARK_EVENTS
    assert len(workload.events) == len(workload.receive_at)
    assert workload.trace_profile == profile
    if profile == "out_of_order":
        assert any(
            later.event_at < earlier.event_at
            for earlier, later in zip(
                workload.events, workload.events[1:], strict=False
            )
        )
    if profile == "all_episodes_active":
        assert len({event.entity_id for event in workload.events[:17]}) == 17


def test_benchmark_rejects_more_than_one_thousand_events() -> None:
    with pytest.raises(ValueError, match="must not exceed 1000"):
        run_benchmark(MAP_PATH, event_count=MAX_BENCHMARK_EVENTS + 1)


def test_target_benchmark_reports_required_bounded_metrics() -> None:
    result = run_benchmark(MAP_PATH, event_count=100, target_counts=(2,))
    count = result["counts"]["2"]
    core = count["core"]

    assert result["engine"] == "zone_belief"
    assert core["event_count"] == 100
    assert core["max_ms"] <= 100.0
    assert core["token_max"] <= core["token_limit"]
    assert core["audit_bytes"] <= 2 * 1024 * 1024
    assert core["persistence_bytes"] > 0
    assert core["persistence_byte_stable"] is True
    assert all(count["gates"].values())
    assert result["passed"] is True


def test_out_of_order_workload_is_model_neutral_and_within_budget(
    predictive_map: PredictiveMap,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=100,
        started_at=NOW,
        occupants=2,
        trace_profile="out_of_order",
    )

    result, engine = _measure_core(predictive_map, workload)

    assert result["stale_event_count"] > 0
    assert result["max_ms"] <= 100.0
    assert all(
        0.0 <= belief.probability <= 1.0 for belief in engine.snapshot.belief_states
    )
