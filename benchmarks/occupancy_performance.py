from __future__ import annotations

import argparse
import json
import math
import platform
import resource
import sys
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from types import ModuleType
from typing import Any


def _install_home_assistant_stubs() -> None:
    def callback(function: Callable[..., Any]) -> Callable[..., Any]:
        return function

    modules = {
        name: ModuleType(name)
        for name in (
            "homeassistant",
            "homeassistant.core",
            "homeassistant.helpers",
            "homeassistant.helpers.dispatcher",
            "homeassistant.helpers.event",
        )
    }
    modules["homeassistant.core"].Event = object
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.core"].callback = callback
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = lambda *_args: (
        None
    )
    modules["homeassistant.helpers.event"].async_track_state_change_event = (
        lambda *_args: lambda: None
    )
    modules["homeassistant.helpers.event"].async_track_time_interval = lambda *_args: (
        lambda: None
    )
    modules["homeassistant"].core = modules["homeassistant.core"]
    modules["homeassistant"].helpers = modules["homeassistant.helpers"]
    modules["homeassistant.helpers"].dispatcher = modules[
        "homeassistant.helpers.dispatcher"
    ]
    modules["homeassistant.helpers"].event = modules["homeassistant.helpers.event"]
    sys.modules.update(modules)


_install_home_assistant_stubs()

from custom_components.predictive_controls.confidence import (  # noqa: E402
    ZoneConfidenceEngine,
)
from custom_components.predictive_controls.events import OccupancyEvent  # noqa: E402
from custom_components.predictive_controls.model import PredictiveMap  # noqa: E402
from custom_components.predictive_controls.runtime import (  # noqa: E402
    RUNTIME_HARD_CEILING_MS,
    PredictiveControlsRuntime,
)
from custom_components.predictive_controls.yaml_config import (  # noqa: E402
    load_predictive_map,
)


@dataclass(frozen=True)
class _State:
    state: str


class _States:
    def __init__(self, values: dict[str, _State]) -> None:
        self._values = values

    def get(self, entity_id: str) -> _State | None:
        return self._values.get(entity_id)


class _Hass:
    def __init__(self, states: dict[str, _State]) -> None:
        self.states = _States(states)
        self.data: dict[str, object] = {}


def _event(
    predictive_map: PredictiveMap,
    entity_id: str,
    state: str,
    event_at: datetime,
) -> OccupancyEvent:
    binding = predictive_map.entity_binding_for_entity(entity_id)
    if binding is None:
        raise ValueError(f"Unmapped benchmark entity: {entity_id}")
    node = predictive_map.nodes[binding.node_id]
    return OccupancyEvent(
        entity_id=entity_id,
        node_id=node.node_id,
        zone=node.occupancy_zone,
        floor=node.floor,
        role=node.role,
        occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
        signal_type=binding.signal_type,
        state=state,
        event_at=event_at,
        reliability=node.initial_weight,
    )


def _snapshot(
    predictive_map: PredictiveMap,
    event_at: datetime,
) -> tuple[OccupancyEvent, ...]:
    return tuple(
        _event(predictive_map, entity_id, "off", event_at)
        for entity_id in predictive_map.entity_ids()
    )


def _trace(
    predictive_map: PredictiveMap,
    event_count: int,
    started_at: datetime,
) -> tuple[OccupancyEvent, ...]:
    entity_ids = predictive_map.entity_ids()
    return tuple(
        _event(
            predictive_map,
            entity_ids[index % len(entity_ids)],
            "on" if (index // len(entity_ids)) % 2 == 0 else "off",
            started_at + timedelta(milliseconds=index + 1),
        )
        for index in range(event_count)
    )


def _percentile(samples: list[float], quantile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _latencies(samples: list[float]) -> dict[str, float | int]:
    return {
        "event_count": len(samples),
        "p50_ms": _percentile(samples, 0.50),
        "p95_ms": _percentile(samples, 0.95),
        "p99_ms": _percentile(samples, 0.99),
        "max_ms": max(samples),
    }


def _measure_core(
    predictive_map: PredictiveMap,
    events: tuple[OccupancyEvent, ...],
    snapshot: tuple[OccupancyEvent, ...],
) -> tuple[dict[str, object], ZoneConfidenceEngine]:
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    tracker.bootstrap_joint_state(snapshot, cold_start=True)
    samples: list[float] = []
    max_expansions = 0
    max_contexts = 0
    total_compactions = 0
    for event in events:
        started_ns = perf_counter_ns()
        tracker.observe(event)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
        performance = tracker.diagnostics.joint_performance
        max_expansions = max(
            max_expansions,
            int(performance["last_candidate_expansions"]),
        )
        max_contexts = max(max_contexts, int(performance["context_count"]))
        total_compactions += int(performance["last_context_compactions"])
    return (
        {
            **_latencies(samples),
            "candidate_expansions_max": max_expansions,
            "configuration_count": len(tracker.diagnostics.joint_posterior),
            "context_count_max": max_contexts,
            "context_compactions": total_compactions,
            "pruned_probability": tracker.diagnostics.joint_pruned_probability,
        },
        tracker,
    )


def _measure_runtime(
    predictive_map: PredictiveMap,
    event_count: int,
) -> tuple[dict[str, object], PredictiveControlsRuntime]:
    states = {entity_id: _State("off") for entity_id in predictive_map.entity_ids()}
    runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        transition_window=30,
        expected_occupants=2,
    )
    runtime.start()
    events = _trace(
        predictive_map,
        event_count,
        datetime.now().astimezone() + timedelta(seconds=1),
    )
    samples: list[float] = []
    for event in events:
        started_ns = perf_counter_ns()
        runtime.observe_entity(event.entity_id, event.state, event.event_at)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
    return (
        {
            **_latencies(samples),
            "performance_budget_exceeded_count": runtime.latency_metrics[
                "performance_budget_exceeded_count"
            ],
        },
        runtime,
    )


def _measure_bootstrap(
    predictive_map: PredictiveMap,
    snapshot: tuple[OccupancyEvent, ...],
) -> dict[str, float | int]:
    cold = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    started_ns = perf_counter_ns()
    cold.bootstrap_joint_state(snapshot, cold_start=True)
    cold_ms = (perf_counter_ns() - started_ns) / 1_000_000
    payload = cold.occupancy_store_data(snapshot[0].event_at, {})

    restored = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    restored.restore_joint_state(
        __import__(
            "custom_components.predictive_controls.occupancy_persistence",
            fromlist=["restore_occupancy_state"],
        ).restore_occupancy_state(
            payload,
            predictive_map,
            2,
            snapshot[0].event_at,
        )
    )
    started_ns = perf_counter_ns()
    restored.bootstrap_joint_state(snapshot, cold_start=False)
    restored_ms = (perf_counter_ns() - started_ns) / 1_000_000

    states = {entity_id: _State("off") for entity_id in predictive_map.entity_ids()}
    cold_runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        30,
        expected_occupants=2,
    )
    started_ns = perf_counter_ns()
    cold_runtime.start()
    cold_setup_ms = (perf_counter_ns() - started_ns) / 1_000_000

    restored_runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        30,
        expected_occupants=2,
    )
    restored_runtime.restore_stored_state(
        payload,
        snapshot[0].event_at,
    )
    started_ns = perf_counter_ns()
    restored_runtime.start()
    restored_setup_ms = (perf_counter_ns() - started_ns) / 1_000_000
    return {
        "entity_count": len(snapshot),
        "cold_inference_ms": cold_ms,
        "restored_inference_ms": restored_ms,
        "cold_runtime_start_ms": cold_setup_ms,
        "restored_runtime_start_ms": restored_setup_ms,
    }


def _measure_peak_memory(
    predictive_map: PredictiveMap,
    events: tuple[OccupancyEvent, ...],
    snapshot: tuple[OccupancyEvent, ...],
) -> dict[str, int]:
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    tracker.bootstrap_joint_state(snapshot, cold_start=True)
    tracemalloc.start()
    for event in events:
        tracker.observe(event)
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "tracemalloc_current_bytes": current_bytes,
        "tracemalloc_peak_bytes": peak_bytes,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def run_benchmark(map_path: Path, event_count: int) -> dict[str, object]:
    predictive_map = load_predictive_map(map_path.read_text())
    started_at = datetime.now().astimezone()
    snapshot = _snapshot(predictive_map, started_at)
    events = _trace(
        predictive_map,
        event_count,
        started_at + timedelta(seconds=1),
    )
    bootstrap = _measure_bootstrap(predictive_map, snapshot)
    core, tracker = _measure_core(predictive_map, events, snapshot)
    runtime, runtime_instance = _measure_runtime(predictive_map, event_count)
    memory = _measure_peak_memory(predictive_map, events, snapshot)
    candidate_ceiling = len(tracker.diagnostics.joint_posterior) * (
        len(predictive_map.zones()) + 1
    )
    targets = {
        "core_percentiles_below_30_ms": bool(
            core["p50_ms"] <= 30.0 and core["p95_ms"] <= 30.0 and core["p99_ms"] <= 30.0
        ),
        "runtime_tail_below_30_ms": bool(
            runtime["p95_ms"] <= 30.0 and runtime["p99_ms"] <= 30.0
        ),
    }
    gates = {
        "PERF-001": core["max_ms"] <= RUNTIME_HARD_CEILING_MS,
        "PERF-002": bool(
            runtime["max_ms"] <= RUNTIME_HARD_CEILING_MS
            and runtime_instance.latency_metrics["performance_budget_exceeded_count"]
            == 0
        ),
        "PERF-003": bool(
            bootstrap["cold_inference_ms"] <= 100.0
            and bootstrap["restored_inference_ms"] <= 100.0
            and bootstrap["cold_runtime_start_ms"] <= 500.0
            and bootstrap["restored_runtime_start_ms"] <= 500.0
        ),
        "PERF-004": core["configuration_count"] == 153,
        "PERF-005": core["context_count_max"] <= 612,
        "PERF-006": core["candidate_expansions_max"] <= candidate_ceiling,
        "PERF-007": core["pruned_probability"] == 0.0,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "map": {
            "path": str(map_path),
            "zones": len(predictive_map.zones()),
            "nodes": len(predictive_map.nodes),
            "entities": len(predictive_map.entity_ids()),
            "occupants": 2,
        },
        "core": core,
        "runtime": runtime,
        "bootstrap": bootstrap,
        "memory": memory,
        "candidate_expansion_ceiling": candidate_ceiling,
        "targets": targets,
        "targets_met": all(targets.values()),
        "gates": gates,
        "passed": all(gates.values()),
    }


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--map",
        type=Path,
        default=repository / "benchmarks" / "reference-map.yaml",
    )
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=repository / "PERFORMANCE_RESULTS.json",
    )
    args = parser.parse_args()
    result = run_benchmark(args.map, args.events)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
