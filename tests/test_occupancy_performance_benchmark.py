from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benchmarks.occupancy_performance import (
    TRACE_PROFILES,
    _association_envelope,
    _build_workload,
    _configuration_count,
    _measure_core,
    run_benchmark,
)
from custom_components.predictive_controls.inference.engine import (
    MAX_ACCEPTED_LATENESS,
    MAX_COHERENT_ENDPOINTS,
)
from custom_components.predictive_controls.inference.policy import (
    POLICY_AUDIT_MAX_BYTES,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
MAP_PATH = Path(__file__).parents[1] / "benchmarks" / "reference-map.yaml"


@pytest.fixture(scope="module")
def predictive_map() -> PredictiveMap:
    return load_predictive_map(MAP_PATH.read_text())


@pytest.mark.parametrize("profile", TRACE_PROFILES)
@pytest.mark.parametrize("occupants", (2,))
def test_benchmark_workloads_cover_required_profiles(
    predictive_map: PredictiveMap,
    profile: str,
    occupants: int,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=64,
        started_at=NOW,
        occupants=occupants,
        trace_profile=profile,
    )

    assert workload.trace_profile == profile
    assert workload.occupants == occupants
    assert workload.events
    assert len(workload.events) == len(workload.receive_at)
    assert workload.expected_configuration_count == _configuration_count(
        predictive_map,
        occupants,
    )

    if profile == "correlated_burst":
        assert max(
            later.event_at - earlier.event_at
            for earlier, later in zip(
                workload.events,
                workload.events[1:],
                strict=False,
            )
        ) <= timedelta(milliseconds=10)
        assert len({event.entity_id for event in workload.events[:4]}) == 1
    elif profile == "maximum_lag":
        assert all(
            received - event.event_at
            == MAX_ACCEPTED_LATENESS - timedelta(microseconds=1)
            for event, received in zip(
                workload.events,
                workload.receive_at,
                strict=True,
            )
        )
    elif profile == "out_of_order":
        assert any(
            later.event_at < earlier.event_at
            for earlier, later in zip(
                workload.events,
                workload.events[1:],
                strict=False,
            )
        )
        assert list(workload.receive_at) == sorted(workload.receive_at)
    elif profile == "all_episodes_active":
        assert {
            event.node_id for event in workload.events if event.state == "on"
        } == set(predictive_map.nodes)
    elif profile == "overload":
        assert workload.max_coherent_endpoints == 0
        assert len(workload.events) > workload.max_coherent_endpoints


def test_benchmark_configuration_gate_depends_on_requested_count(
    predictive_map: PredictiveMap,
) -> None:
    assert _configuration_count(predictive_map, 2) == 153


def test_benchmark_routes_profile_and_count_through_every_layer() -> None:
    result = run_benchmark(
        MAP_PATH,
        event_count=1,
        target_counts=(2,),
        trace_profile="deterministic",
    )

    count = result["counts"]["2"]
    assert result["trace_profile"] == "deterministic"
    assert result["map"]["occupants"] == [2]
    assert count["workload"] == {
        "trace_profile": "deterministic",
        "event_count": 1,
        "receipt_time_profile": False,
        "max_coherent_endpoints": MAX_COHERENT_ENDPOINTS,
    }
    for layer in ("core", "runtime", "bootstrap", "memory"):
        assert count[layer]["occupants"] == 2
        assert count[layer]["trace_profile"] == "deterministic"
    assert count["core"]["configuration_count"] == 153
    assert count["exact_target"]["configuration_count"] == 153
    assert count["episode_target"]["configuration_count"] == 153
    assert count["gates"]["PERF-004"] is True
    assert count["core"]["policy_audit_bytes"] <= POLICY_AUDIT_MAX_BYTES
    assert count["core"]["policy_audit_persistence_bytes"] >= count["core"][
        "policy_audit_bytes"
    ]
    assert result["passed"] is True


def test_all_active_episodes_stay_within_hard_callback_budget() -> None:
    result = run_benchmark(
        MAP_PATH,
        event_count=17,
        target_counts=(2,),
        trace_profile="all_episodes_active",
    )

    count = result["counts"]["2"]
    assert count["episode_target"]["active_episode_max"] == 17
    assert count["episode_target"]["gates"]["hard_callback"] is True
    assert count["gates"]["PERF-001"] is True


def test_n2_out_of_order_replay_stays_within_hard_callback_budget(
    predictive_map: PredictiveMap,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=100,
        started_at=NOW,
        occupants=2,
        trace_profile="out_of_order",
    )

    with _association_envelope(workload):
        result, tracker = _measure_core(predictive_map, workload)

    assert tracker.diagnostics.joint_normalization == pytest.approx(1.0, abs=1e-12)
    assert result["max_ms"] <= 100.0


def test_n2_deterministic_audit_stays_bounded_through_first_failing_prefix(
    predictive_map: PredictiveMap,
) -> None:
    workload = _build_workload(
        predictive_map,
        event_count=797,
        started_at=NOW,
        occupants=2,
        trace_profile="deterministic",
    )
    failing_event = workload.events[-1]

    assert failing_event.event_at == NOW + timedelta(milliseconds=797)
    assert failing_event.entity_id == "binary_sensor.benchmark_living_right_still"
    assert failing_event.state == "on"

    with _association_envelope(workload):
        result, tracker = _measure_core(predictive_map, workload)

    assert tracker.diagnostics.joint_normalization == pytest.approx(1.0, abs=1e-12)
    assert result["policy_audit_bytes"] <= POLICY_AUDIT_MAX_BYTES
