"""Deterministic performance benchmark for the target zone-belief engine."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import PolicyAuditLog
from custom_components.predictive_controls.zone_model.types import SensorInput

MAX_BENCHMARK_EVENTS = 1000
ROUTINE_BENCHMARK_EVENTS = 100
PREFERRED_CALLBACK_MS = 50.0
HARD_CALLBACK_MS = 100.0
MAX_ACCEPTED_LATENESS = timedelta(seconds=30)
TRACE_PROFILES = (
    "deterministic",
    "correlated_burst",
    "maximum_lag",
    "out_of_order",
    "all_episodes_active",
)


@dataclass(frozen=True)
class BenchmarkWorkload:
    """One finite raw-input workload and its receipt frontier."""

    trace_profile: str
    occupants: int
    events: tuple[SensorInput, ...]
    receive_at: tuple[datetime, ...]


def _build_workload(
    predictive_map: PredictiveMap,
    *,
    event_count: int,
    started_at: datetime,
    occupants: int,
    trace_profile: str,
) -> BenchmarkWorkload:
    if not 0 <= event_count <= MAX_BENCHMARK_EVENTS:
        raise ValueError("Benchmark event count must not exceed 1000")
    if trace_profile not in TRACE_PROFILES:
        raise ValueError(f"Unknown trace profile: {trace_profile}")
    bindings = tuple(
        sorted(
            (entity_id, node.node_id)
            for node in predictive_map.nodes.values()
            for entity_id in node.entities.values()
        )
    )
    if not bindings:
        raise ValueError("Benchmark map has no sensor bindings")
    events: list[SensorInput] = []
    receive_at: list[datetime] = []
    for index in range(event_count):
        binding_index = index % len(bindings)
        if trace_profile == "correlated_burst" and index < 4:
            binding_index = 0
        entity_id, _node_id = bindings[binding_index]
        logical_index = index
        if trace_profile == "out_of_order" and index % 4 == 3:
            logical_index = index - 2
        event_at = started_at + timedelta(milliseconds=logical_index + 1)
        state = (
            "on"
            if index < len(predictive_map.nodes)
            and trace_profile == "all_episodes_active"
            else "on"
            if index % 2 == 0
            else "off"
        )
        events.append(SensorInput(entity_id, state, event_at))
        receipt = started_at + timedelta(milliseconds=index + 1)
        if trace_profile == "maximum_lag":
            receipt = event_at + MAX_ACCEPTED_LATENESS
        receive_at.append(max(receipt, event_at))
    return BenchmarkWorkload(
        trace_profile,
        occupants,
        tuple(events),
        tuple(receive_at),
    )


def _percentile(samples: list[float], quantile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _measure_core(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> tuple[dict[str, Any], ZoneModelEngine]:
    bootstrap_at = min(
        (event.event_at for event in workload.events),
        default=datetime.now(UTC),
    )
    started_ns = perf_counter_ns()
    engine = ZoneModelEngine(predictive_map, workload.occupants, bootstrap_at)
    startup_ms = (perf_counter_ns() - started_ns) / 1_000_000
    samples: list[float] = []
    stale_events = 0
    policy_decisions = 0
    policy_events = 0
    token_max = 0
    for event, received_at in zip(workload.events, workload.receive_at, strict=True):
        started_ns = perf_counter_ns()
        result = engine.observe(event, processing_at=received_at)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
        stale_events += result.disposition == "stale"
        policy_decisions += len(result.policy_decisions)
        policy_events += len(result.policy_events)
        token_max = max(token_max, len(result.snapshot.traversal_tokens))
    payload = serialize_target_state(predictive_map, engine)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    repeated = json.dumps(
        serialize_target_state(predictive_map, engine),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    audit_bytes = sum(PolicyAuditLog.encoded_size(row) for row in engine.audit_rows)
    return (
        {
            "occupants": workload.occupants,
            "trace_profile": workload.trace_profile,
            "event_count": len(workload.events),
            "startup_ms": startup_ms,
            "total_ms": sum(samples),
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "p99_ms": _percentile(samples, 0.99),
            "max_ms": max(samples, default=0.0),
            "stale_event_count": stale_events,
            "zone_decision_count": policy_decisions,
            "public_policy_event_count": policy_events,
            "token_max": token_max,
            "token_limit": 64,
            "audit_entry_count": len(engine.audit_rows),
            "audit_bytes": audit_bytes,
            "persistence_bytes": len(encoded),
            "persistence_byte_stable": encoded == repeated,
        },
        engine,
    )


def run_benchmark(
    map_path: Path,
    *,
    event_count: int = ROUTINE_BENCHMARK_EVENTS,
    target_counts: tuple[int, ...] = (2,),
    trace_profile: str = "deterministic",
) -> dict[str, Any]:
    if event_count > MAX_BENCHMARK_EVENTS:
        raise ValueError("Benchmark event count must not exceed 1000")
    predictive_map = load_predictive_map(map_path.read_text())
    started_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    counts: dict[str, Any] = {}
    passed = True
    for occupants in target_counts:
        workload = _build_workload(
            predictive_map,
            event_count=event_count,
            started_at=started_at,
            occupants=occupants,
            trace_profile=trace_profile,
        )
        core, _engine = _measure_core(predictive_map, workload)
        gates = {
            "preferred_callback": core["p95_ms"] <= PREFERRED_CALLBACK_MS,
            "hard_callback": core["max_ms"] <= HARD_CALLBACK_MS,
            "bounded_tokens": core["token_max"] <= core["token_limit"],
            "byte_stable_persistence": core["persistence_byte_stable"],
        }
        passed = passed and all(gates.values())
        counts[str(occupants)] = {
            "workload": {
                "trace_profile": trace_profile,
                "event_count": event_count,
                "receipt_time_profile": trace_profile
                in {"maximum_lag", "out_of_order"},
            },
            "core": core,
            "gates": gates,
        }
    return {
        "schema_version": 2,
        "engine": "zone_belief",
        "trace_profile": trace_profile,
        "map": {
            "path": str(map_path),
            "nodes": len(predictive_map.nodes),
            "zones": len(predictive_map.zones()),
            "occupants": list(target_counts),
        },
        "counts": counts,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--map",
        type=Path,
        default=Path(__file__).with_name("reference-map.yaml"),
    )
    parser.add_argument("--events", type=int, default=ROUTINE_BENCHMARK_EVENTS)
    parser.add_argument(
        "--trace-profile", choices=TRACE_PROFILES, default="deterministic"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(
        args.map,
        event_count=args.events,
        trace_profile=args.trace_profile,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
