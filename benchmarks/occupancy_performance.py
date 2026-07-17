from __future__ import annotations

import argparse
import contextlib
import json
import math
import platform
import resource
import sys
import tracemalloc
from array import array
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
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

import custom_components.predictive_controls.inference.engine as engine_module  # noqa: E402
from custom_components.predictive_controls.confidence import (  # noqa: E402
    ZoneConfidenceEngine,
)
from custom_components.predictive_controls.events import OccupancyEvent  # noqa: E402
from custom_components.predictive_controls.inference import (  # noqa: E402
    CompactPosterior,
    CompleteMoveOperators,
    StateSpace,
)
from custom_components.predictive_controls.inference.engine import (  # noqa: E402
    MAX_ACCEPTED_LATENESS,
    MAX_COHERENT_ENDPOINTS,
    ExactInferenceEngine,
)
from custom_components.predictive_controls.inference.episodes import (  # noqa: E402
    NodeEpisodeState,
)
from custom_components.predictive_controls.inference.policy import (  # noqa: E402
    POLICY_AUDIT_MAX_BYTES,
    POLICY_AUDIT_MAX_ENTRIES,
)
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


TRACE_PROFILES = (
    "deterministic",
    "correlated_burst",
    "maximum_lag",
    "out_of_order",
    "all_episodes_active",
    "overload",
)
MAX_BENCHMARK_EVENTS = 1_000


def _validate_event_count(event_count: int) -> None:
    if event_count > MAX_BENCHMARK_EVENTS:
        raise ValueError(
            f"event count must not exceed {MAX_BENCHMARK_EVENTS}"
        )


def _parse_event_count(value: str) -> int:
    event_count = int(value)
    try:
        _validate_event_count(event_count)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return event_count


@dataclass(frozen=True)
class BenchmarkWorkload:
    trace_profile: str
    occupants: int
    snapshot: tuple[OccupancyEvent, ...]
    events: tuple[OccupancyEvent, ...]
    receive_at: tuple[datetime, ...]
    expected_configuration_count: int
    max_coherent_endpoints: int = MAX_COHERENT_ENDPOINTS


def _configuration_count(
    predictive_map: PredictiveMap,
    occupants: int,
) -> int:
    return math.comb(len(predictive_map.zones()) + occupants, occupants)


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


def _build_workload(
    predictive_map: PredictiveMap,
    event_count: int,
    started_at: datetime,
    occupants: int,
    trace_profile: str,
) -> BenchmarkWorkload:
    if trace_profile not in TRACE_PROFILES:
        raise ValueError(f"Unknown benchmark trace profile: {trace_profile}")
    snapshot = _snapshot(predictive_map, started_at)
    entity_ids = predictive_map.entity_ids()
    effective_count = max(1, event_count)
    if trace_profile == "correlated_burst":
        entity_id = entity_ids[0]
        events = tuple(
            _event(
                predictive_map,
                entity_id,
                "on" if index % 2 == 0 else "off",
                started_at + timedelta(microseconds=index + 1),
            )
            for index in range(effective_count)
        )
        receive_at = tuple(event.event_at for event in events)
    elif trace_profile == "maximum_lag":
        events = _trace(predictive_map, effective_count, started_at)
        accepted_lag = MAX_ACCEPTED_LATENESS - timedelta(microseconds=1)
        receive_at = tuple(event.event_at + accepted_lag for event in events)
    elif trace_profile == "out_of_order":
        ordered = _trace(predictive_map, effective_count, started_at)
        events_list = list(ordered)
        for index in range(0, len(events_list) - 1, 2):
            events_list[index], events_list[index + 1] = (
                events_list[index + 1],
                events_list[index],
            )
        events = tuple(events_list)
        receive_at = tuple(
            started_at + timedelta(milliseconds=index + 3)
            for index in range(len(events))
        )
    elif trace_profile == "all_episodes_active":
        active_entities = tuple(
            sorted(node.entities.values())[0]
            for node in predictive_map.nodes.values()
        )
        minimum_events = tuple(
            _event(
                predictive_map,
                entity_id,
                "on",
                started_at + timedelta(milliseconds=index + 1),
            )
            for index, entity_id in enumerate(active_entities)
        )
        if effective_count <= len(minimum_events):
            events = minimum_events
        else:
            events = (
                *minimum_events,
                *_trace(
                    predictive_map,
                    effective_count - len(minimum_events),
                    started_at + timedelta(milliseconds=len(minimum_events)),
                ),
            )
        receive_at = tuple(event.event_at for event in events)
    elif trace_profile == "overload":
        entity_id = entity_ids[0]
        events = tuple(
            _event(
                predictive_map,
                entity_id,
                "on",
                started_at + timedelta(microseconds=index + 1),
            )
            for index in range(effective_count)
        )
        receive_at = tuple(event.event_at for event in events)
    else:
        events = _trace(predictive_map, effective_count, started_at)
        receive_at = tuple(event.event_at for event in events)
    return BenchmarkWorkload(
        trace_profile,
        occupants,
        snapshot,
        events,
        receive_at,
        _configuration_count(predictive_map, occupants),
        0 if trace_profile == "overload" else MAX_COHERENT_ENDPOINTS,
    )


@contextlib.contextmanager
def _association_envelope(workload: BenchmarkWorkload) -> Iterator[None]:
    previous = engine_module.MAX_COHERENT_ENDPOINTS
    engine_module.MAX_COHERENT_ENDPOINTS = workload.max_coherent_endpoints
    try:
        yield
    finally:
        engine_module.MAX_COHERENT_ENDPOINTS = previous


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
    workload: BenchmarkWorkload,
) -> tuple[dict[str, object], ZoneConfidenceEngine]:
    tracker = ZoneConfidenceEngine(
        predictive_map,
        expected_occupants=workload.occupants,
    )
    tracker.bootstrap_joint_state(workload.snapshot, cold_start=True)
    samples: list[float] = []
    max_factor_steps = 0
    max_unresolved_assignments = 0
    max_retained_inputs = 0
    overload_count = 0
    for event in workload.events:
        started_ns = perf_counter_ns()
        tracker.observe(event)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
        performance = tracker.diagnostics.joint_performance
        max_factor_steps = max(
            max_factor_steps,
            int(performance["factor_step_count"]),
        )
        max_unresolved_assignments = max(
            max_unresolved_assignments,
            int(performance["unresolved_assignment_count"]),
        )
        max_retained_inputs = max(
            max_retained_inputs,
            int(performance["retained_input_count"]),
        )
        overload_count += int(performance["overloaded"])
    policy_audit = tracker.diagnostics.joint_target_policy_audit
    payload = tracker.occupancy_store_data(workload.receive_at[-1], {})
    raw_policy = payload.get("policy")
    raw_audit = raw_policy.get("audit", []) if isinstance(raw_policy, dict) else []
    return (
        {
            **_latencies(samples),
            "occupants": workload.occupants,
            "trace_profile": workload.trace_profile,
            "receipt_time_supported": False,
            "factor_step_count_max": max_factor_steps,
            "configuration_count": len(
                tracker._engine._posterior.space  # noqa: SLF001
            ),
            "unresolved_assignment_count_max": max_unresolved_assignments,
            "retained_input_count_max": max_retained_inputs,
            "overload_count": overload_count,
            "pruned_probability": tracker.diagnostics.joint_pruned_probability,
            "policy_audit_entry_count": len(policy_audit),
            "policy_audit_bytes": tracker._joint_policy.retained_audit_bytes,  # noqa: SLF001
            "policy_audit_persistence_bytes": len(
                json.dumps(raw_audit, sort_keys=True, separators=(",", ":")).encode()
            ),
        },
        tracker,
    )


def _measure_runtime(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> tuple[dict[str, object], PredictiveControlsRuntime]:
    states = {entity_id: _State("off") for entity_id in predictive_map.entity_ids()}
    runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        transition_window=30,
        expected_occupants=workload.occupants,
    )
    runtime.start()
    samples: list[float] = []
    for event in workload.events:
        started_ns = perf_counter_ns()
        runtime.observe_entity(event.entity_id, event.state, event.event_at)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
    return (
        {
            **_latencies(samples),
            "occupants": workload.occupants,
            "trace_profile": workload.trace_profile,
            "receipt_time_supported": False,
            "performance_budget_exceeded_count": runtime.latency_metrics[
                "performance_budget_exceeded_count"
            ],
        },
        runtime,
    )


def _measure_bootstrap(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> dict[str, float | int]:
    snapshot = workload.snapshot
    cold = ZoneConfidenceEngine(
        predictive_map,
        expected_occupants=workload.occupants,
    )
    started_ns = perf_counter_ns()
    cold.bootstrap_joint_state(snapshot, cold_start=True)
    cold_ms = (perf_counter_ns() - started_ns) / 1_000_000
    payload = cold.occupancy_store_data(snapshot[0].event_at, {})

    restored = ZoneConfidenceEngine(
        predictive_map,
        expected_occupants=workload.occupants,
    )
    restored.restore_joint_state(payload)
    started_ns = perf_counter_ns()
    restored.bootstrap_joint_state(snapshot, cold_start=False)
    restored_ms = (perf_counter_ns() - started_ns) / 1_000_000

    states = {entity_id: _State("off") for entity_id in predictive_map.entity_ids()}
    cold_runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        30,
        expected_occupants=workload.occupants,
    )
    started_ns = perf_counter_ns()
    cold_runtime.start()
    cold_setup_ms = (perf_counter_ns() - started_ns) / 1_000_000

    restored_runtime = PredictiveControlsRuntime(
        _Hass(states),
        predictive_map,
        (),
        30,
        expected_occupants=workload.occupants,
    )
    restored_runtime.restore_stored_state(
        payload,
        snapshot[0].event_at,
    )
    started_ns = perf_counter_ns()
    restored_runtime.start()
    restored_setup_ms = (perf_counter_ns() - started_ns) / 1_000_000
    return {
        "occupants": workload.occupants,
        "trace_profile": workload.trace_profile,
        "entity_count": len(snapshot),
        "cold_inference_ms": cold_ms,
        "restored_inference_ms": restored_ms,
        "cold_runtime_start_ms": cold_setup_ms,
        "restored_runtime_start_ms": restored_setup_ms,
    }


def _measure_peak_memory(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> dict[str, int | str]:
    tracker = ZoneConfidenceEngine(
        predictive_map,
        expected_occupants=workload.occupants,
    )
    tracker.bootstrap_joint_state(workload.snapshot, cold_start=True)
    tracemalloc.start()
    for event in workload.events:
        tracker.observe(event)
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "occupants": workload.occupants,
        "trace_profile": workload.trace_profile,
        "tracemalloc_current_bytes": current_bytes,
        "tracemalloc_peak_bytes": peak_bytes,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def _measure_exact_target(
    predictive_map: PredictiveMap,
    event_count: int,
    occupants: int,
    trace_profile: str,
) -> dict[str, object]:
    zones = predictive_map.zones()
    started_ns = perf_counter_ns()
    space = StateSpace(zones, occupants)
    state_space_ms = (perf_counter_ns() - started_ns) / 1_000_000
    started_ns = perf_counter_ns()
    operators = CompleteMoveOperators(space)
    operator_build_ms = (perf_counter_ns() - started_ns) / 1_000_000

    tracemalloc.start()
    memory_space = StateSpace(zones, occupants)
    memory_operators = CompleteMoveOperators(memory_space)
    _, bootstrap_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del memory_operators, memory_space

    posterior = CompactPosterior.uniform(space)
    samples: list[float] = []
    location_count = len(space.locations)
    for event_index in range(event_count):
        target_index = (
            event_index % len(zones)
            if trace_profile == "deterministic"
            else (event_index // max(1, len(zones))) % len(zones)
        )
        move_weights = {
            (source_index, target_index): 0.1
            for source_index in range(location_count)
            if source_index != target_index
        }
        started_ns = perf_counter_ns()
        posterior = operators.transition(
            posterior,
            move_weights,
            stay_weight=1.0,
        )
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)

    started_ns = perf_counter_ns()
    serialized = array("d", posterior).tobytes()
    serialize_ms = (perf_counter_ns() - started_ns) / 1_000_000
    started_ns = perf_counter_ns()
    restored = CompactPosterior(space, array("d", serialized))
    restore_ms = (perf_counter_ns() - started_ns) / 1_000_000
    latencies = _latencies(samples)
    preferred = bool(
        latencies["p50_ms"] <= 50.0
        and latencies["p95_ms"] <= 50.0
        and latencies["p99_ms"] <= 50.0
    )
    gates = {
        "normalization": abs(restored.normalization - 1.0) <= 1e-12,
        "configuration_count": len(space)
        == math.comb(len(zones) + occupants, occupants),
        "zero_pruning": True,
        "preferred_callback": preferred,
        "hard_callback": latencies["max_ms"] <= RUNTIME_HARD_CEILING_MS,
        "operator_storage": operators.storage_bytes <= 32 * 1024 * 1024,
        "bootstrap_memory": bootstrap_peak_bytes <= 128 * 1024 * 1024,
        "startup": state_space_ms + operator_build_ms <= 2_500.0,
        "persistence": len(serialized) <= 200_000,
    }
    return {
        **latencies,
        "occupants": occupants,
        "trace_profile": trace_profile,
        "configuration_count": len(space),
        "candidate_operations_per_update": len(space) * (location_count - 1),
        "posterior_storage_bytes": posterior.storage_bytes,
        "operator_storage_bytes": operators.storage_bytes,
        "bootstrap_peak_bytes": bootstrap_peak_bytes,
        "state_space_ms": state_space_ms,
        "operator_build_ms": operator_build_ms,
        "serialize_ms": serialize_ms,
        "restore_ms": restore_ms,
        "serialized_bytes": len(serialized),
        "normalization": restored.normalization,
        "gates": gates,
        "passed": all(gates.values()),
    }


def _measure_episode_target(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> dict[str, object]:
    occupants = workload.occupants
    events = workload.events
    snapshot = workload.snapshot
    started_ns = perf_counter_ns()
    engine = ExactInferenceEngine(predictive_map, occupants)
    startup_ms = (perf_counter_ns() - started_ns) / 1_000_000
    started_ns = perf_counter_ns()
    engine.bootstrap(snapshot, cold_start=True)
    bootstrap_ms = (perf_counter_ns() - started_ns) / 1_000_000

    samples: list[float] = []
    active_episode_max = 0
    unresolved_assignment_max = 0
    factor_step_max = 0
    retained_input_max = 0
    consumed_endpoint_max = 0
    joint_forward_state_max = 0
    overload_count = 0
    for event, receive_at in zip(events, workload.receive_at, strict=True):
        started_ns = perf_counter_ns()
        diagnostics = engine.observe_received(
            event,
            receive_at=receive_at,
            emit_activation=False,
        )
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
        active_episode_max = max(
            active_episode_max,
            sum(
                isinstance(state, NodeEpisodeState) and state.current_positive
                for state in diagnostics.episode_states
            ),
        )
        unresolved_assignment_max = max(
            unresolved_assignment_max,
            diagnostics.unresolved_assignment_count,
        )
        factor_step_max = max(factor_step_max, diagnostics.factor_step_count)
        retained_input_max = max(
            retained_input_max,
            diagnostics.retained_input_count,
        )
        consumed_endpoint_max = max(
            consumed_endpoint_max,
            diagnostics.consumed_endpoint_count,
        )
        joint_forward_state_max = max(
            joint_forward_state_max,
            sum(log_mass != -math.inf for log_mass in engine._chain.posterior),  # noqa: SLF001
        )
        overload_count += diagnostics.overloaded

    persisted_at = workload.receive_at[-1] if events else snapshot[-1].event_at
    started_ns = perf_counter_ns()
    payload = engine.serialize(persisted_at, {})
    serialize_ms = (perf_counter_ns() - started_ns) / 1_000_000
    serialized_bytes = len(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    started_ns = perf_counter_ns()
    restored = ExactInferenceEngine(predictive_map, 0)
    restored.restore(payload)
    restore_ms = (perf_counter_ns() - started_ns) / 1_000_000

    tracemalloc.start()
    memory_engine = ExactInferenceEngine(predictive_map, occupants)
    memory_engine.bootstrap(snapshot, cold_start=True)
    for event, receive_at in zip(
        events[: len(predictive_map.entity_ids())],
        workload.receive_at[: len(predictive_map.entity_ids())],
        strict=True,
    ):
        memory_engine.observe_received(
            event,
            receive_at=receive_at,
            emit_activation=False,
        )
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    diagnostics = engine.diagnostics
    latencies = _latencies(samples)
    preferred = bool(
        latencies["p50_ms"] <= 50.0
        and latencies["p95_ms"] <= 50.0
        and latencies["p99_ms"] <= 50.0
    )
    configuration_count = math.comb(
        len(predictive_map.zones()) + occupants,
        occupants,
    )
    gates = {
        "normalization": abs(diagnostics.normalization - 1.0) <= 1e-12,
        "configuration_count": len(engine._posterior.space)  # noqa: SLF001
        == configuration_count,
        "zero_pruning": diagnostics.pruned_probability == 0.0,
        "preferred_callback": preferred,
        "hard_callback": latencies["max_ms"] <= RUNTIME_HARD_CEILING_MS,
        "active_episode_bound": active_episode_max <= len(predictive_map.nodes),
        "endpoint_envelope": bool(
            unresolved_assignment_max <= workload.max_coherent_endpoints
            or overload_count > 0
        ),
        "overload_explicit": overload_count == 0 or diagnostics.overloaded,
        "bootstrap_memory": peak_bytes <= 128 * 1024 * 1024,
        "startup": startup_ms + bootstrap_ms <= 2_500.0,
        "restart_determinism": bool(
            restored.diagnostics.arrival_supported_probabilities == {}
            and restored.diagnostics
            == replace(diagnostics, arrival_supported_probabilities={})
        ),
    }
    return {
        **latencies,
        "occupants": occupants,
        "trace_profile": workload.trace_profile,
        "receipt_time_supported": True,
        "configuration_count": configuration_count,
        "configuration_operations_per_update": configuration_count,
        "active_episode_max": active_episode_max,
        "unresolved_assignment_max": unresolved_assignment_max,
        "factor_step_max": factor_step_max,
        "retained_input_max": retained_input_max,
        "consumed_endpoint_max": consumed_endpoint_max,
        "joint_forward_state_max": joint_forward_state_max,
        "overload_count": overload_count,
        "endpoint_envelope": workload.max_coherent_endpoints,
        "physical_node_count": len(predictive_map.nodes),
        "startup_ms": startup_ms,
        "bootstrap_ms": bootstrap_ms,
        "serialize_ms": serialize_ms,
        "restore_ms": restore_ms,
        "serialized_bytes": serialized_bytes,
        "tracemalloc_peak_bytes": peak_bytes,
        "normalization": diagnostics.normalization,
        "pruned_probability": diagnostics.pruned_probability,
        "gates": gates,
        "passed": all(gates.values()),
    }


def run_benchmark(
    map_path: Path,
    event_count: int,
    target_counts: tuple[int, ...] = (2,),
    trace_profile: str = "deterministic",
) -> dict[str, object]:
    _validate_event_count(event_count)
    predictive_map = load_predictive_map(map_path.read_text())
    started_at = datetime.now(UTC)
    count_results: dict[str, dict[str, object]] = {}
    all_gates: dict[str, bool] = {}
    for occupants in target_counts:
        workload = _build_workload(
            predictive_map,
            event_count,
            started_at + timedelta(seconds=1),
            occupants,
            trace_profile,
        )
        with _association_envelope(workload):
            core, tracker = _measure_core(predictive_map, workload)
            runtime, runtime_instance = _measure_runtime(
                predictive_map,
                workload,
            )
            bootstrap = _measure_bootstrap(predictive_map, workload)
            memory = _measure_peak_memory(predictive_map, workload)
            episode_target = _measure_episode_target(
                predictive_map,
                workload,
            )
        exact_target = _measure_exact_target(
            predictive_map,
            len(workload.events),
            occupants,
            trace_profile,
        )
        factor_step_ceiling = workload.expected_configuration_count * (
            len(predictive_map.zones()) + 1
        )
        targets = {
            "core_preferred_callback": bool(
                core["p50_ms"] <= 50.0
                and core["p95_ms"] <= 50.0
                and core["p99_ms"] <= 50.0
            ),
            "runtime_preferred_callback": bool(
                runtime["p50_ms"] <= 50.0
                and runtime["p95_ms"] <= 50.0
                and runtime["p99_ms"] <= 50.0
            ),
        }
        gates = {
            "PERF-001": core["max_ms"] <= RUNTIME_HARD_CEILING_MS,
            "PERF-002": bool(
                runtime["max_ms"] <= RUNTIME_HARD_CEILING_MS
                and runtime_instance.latency_metrics[
                    "performance_budget_exceeded_count"
                ]
                == 0
            ),
            "PERF-003": bool(
                bootstrap["cold_inference_ms"] <= 2_500.0
                and bootstrap["restored_inference_ms"] <= 2_500.0
                and bootstrap["cold_runtime_start_ms"] <= 2_500.0
                and bootstrap["restored_runtime_start_ms"] <= 2_500.0
            ),
            "PERF-004": core["configuration_count"]
            == workload.expected_configuration_count,
            "PERF-005": bool(
                int(core["overload_count"]) > 0
                if trace_profile == "overload"
                else core["unresolved_assignment_count_max"]
                <= workload.max_coherent_endpoints
            ),
            "PERF-006": core["factor_step_count_max"] <= factor_step_ceiling,
            "PERF-007": core["pruned_probability"] == 0.0,
            "PERF-008": bool(
                core["policy_audit_entry_count"] <= POLICY_AUDIT_MAX_ENTRIES
                and core["policy_audit_bytes"] <= POLICY_AUDIT_MAX_BYTES
            ),
        }
        all_gates.update(
            {f"N{occupants}-{name}": passed for name, passed in gates.items()}
        )
        count_results[str(occupants)] = {
            "workload": {
                "trace_profile": workload.trace_profile,
                "event_count": len(workload.events),
                "receipt_time_profile": any(
                    event.event_at != received
                    for event, received in zip(
                        workload.events,
                        workload.receive_at,
                        strict=True,
                    )
                ),
                "max_coherent_endpoints": workload.max_coherent_endpoints,
            },
            "core": core,
            "runtime": runtime,
            "bootstrap": bootstrap,
            "memory": memory,
            "exact_target": exact_target,
            "episode_target": episode_target,
            "factor_step_ceiling": factor_step_ceiling,
            "targets": targets,
            "targets_met": all(targets.values()),
            "gates": gates,
            "passed": all(gates.values())
            and all(targets.values())
            and bool(exact_target["passed"])
            and bool(episode_target["passed"]),
        }
    primary = count_results[str(target_counts[0])]
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
            "occupants": list(target_counts),
        },
        "trace_profile": trace_profile,
        "counts": count_results,
        "core": primary["core"],
        "runtime": primary["runtime"],
        "bootstrap": primary["bootstrap"],
        "memory": primary["memory"],
        "exact_target": {
            count: result["exact_target"] for count, result in count_results.items()
        },
        "episode_target": {
            count: result["episode_target"] for count, result in count_results.items()
        },
        "workload_envelope": {
            "max_event_rate_hz": 10.0,
            "max_burst_events": len(predictive_map.entity_ids()),
            "max_active_episodes": len(predictive_map.nodes),
            "max_route_duration_seconds": 120.0,
            "max_accepted_lateness_seconds": 2.0,
        },
        "target_ceilings": {
            "callback_preferred_ms": 50.0,
            "callback_hard_ms": RUNTIME_HARD_CEILING_MS,
            "operator_storage_bytes": 32 * 1024 * 1024,
            "bootstrap_peak_bytes": 128 * 1024 * 1024,
            "startup_ms": 2_500.0,
            "serialized_posterior_bytes": 200_000,
        },
        "gates": all_gates,
        "passed": all(bool(result["passed"]) for result in count_results.values()),
    }


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--map",
        type=Path,
        default=repository / "benchmarks" / "reference-map.yaml",
    )
    parser.add_argument(
        "--events",
        type=_parse_event_count,
        default=MAX_BENCHMARK_EVENTS,
    )
    parser.add_argument(
        "--target-counts",
        type=int,
        nargs="+",
        choices=range(3),
        default=(2,),
    )
    parser.add_argument(
        "--trace-profile",
        choices=TRACE_PROFILES,
        default="deterministic",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repository / "PERFORMANCE_RESULTS.json",
    )
    args = parser.parse_args()
    result = run_benchmark(
        args.map,
        args.events,
        tuple(args.target_counts),
        args.trace_profile,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
