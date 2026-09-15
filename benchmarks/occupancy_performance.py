"""Deterministic performance benchmark for the target zone-belief engine."""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from types import ModuleType
from typing import Any

from custom_components.predictive_controls.const import PRODUCT_MAX_OCCUPANTS
from custom_components.predictive_controls.markov import MARKOV_COUNT_LIMIT, MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.path_health import (
    QUICK_CYCLE_COUNT,
    UNSUPPORTED_ON_WINDOW,
)
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
    target_map_fingerprint,
)
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    PolicyAuditLog,
)
from custom_components.predictive_controls.zone_model.prediction import (
    LEASE_DURATION,
    MATURITY_PROBABILITY,
    MATURITY_SUPPORT,
    PredictionLease,
)
from custom_components.predictive_controls.zone_model.profiles import (
    SHARED_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.traversal import TOKEN_LIMIT
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    ZoneModelResult,
    ZoneModelSnapshot,
    ZonePolicyState,
)

MAX_BENCHMARK_EVENTS = 1000
ROUTINE_BENCHMARK_EVENTS = 100
PREFERRED_CALLBACK_MS = 50.0
HARD_CALLBACK_MS = 100.0
FAST_PATH_P99_MS = 5.0
FAST_PATH_HARD_MS = 10.0
MAX_ACCEPTED_LATENESS = timedelta(seconds=30)
TRACE_PROFILES = (
    "deterministic",
    "correlated_burst",
    "maximum_lag",
    "out_of_order",
    "all_episodes_active",
)

# REQ-PERF-001/007/008: only missed_edge moves out of the acquisition inventory
# into the mandatory rejected-jump workload. All other ON contracts remain.
FAST_PATH_EQUIVALENTS = {
    "adjacent_pair": "selected_adjacent_pair",
    "boundary": "boundary_selected_adoption",
    "cadence_correlated_target": "selected_cadence_correlated_target",
    "confirmed_token": "selected_confirmed_continuation",
    "correlated_continuity": "selected_correlated_continuity",
    "local_interaction": "selected_local_interaction",
    "same_zone": "selected_same_zone_pair",
    "third_node_confirmation": "selected_third_node_confirmation",
    "mature_prediction": "mature_prediction_execution",
    "settled_adjacent_transfer": "selected_asserted_endpoint",
    "correlated_settled_adjacent_transfer": "selected_correlated_asserted_branch",
}
TIMER_WORKLOAD_NAMES = frozenset({"pending_expiry", "unsupported_on_health_deadline"})
PredictionProof = tuple[
    PredictiveMap, tuple[PredictionLease, ...], Mapping[str, Mapping[str, float]],
]


@dataclass(frozen=True)
class BenchmarkWorkload:
    """One finite raw-input workload and its receipt frontier."""

    trace_profile: str
    occupants: int
    events: tuple[SensorInput, ...]
    receive_at: tuple[datetime, ...]
    started_at: datetime

    @property
    def bootstrap_at(self) -> datetime:
        """Use the timed engine's actual frontier, including an empty trace."""

        return min(
            (event.event_at for event in self.events), default=self.started_at
        )


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
        started_at,
    )


def _semantic_value(value: Any) -> Any:
    """Encode every field, using the persistence writer's UTC ISO convention."""

    if isinstance(value, datetime):
        if value.utcoffset() != timedelta(0):
            raise ValueError("Semantic timestamps must be aware UTC")
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if is_dataclass(value) and not isinstance(value, type):
        return _semantic_value(asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Semantic mapping keys must be strings")
        return {key: _semantic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_semantic_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"Unsupported semantic value: {type(value).__name__}")


def _render_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _semantic_differences(
    before: Any, after: Any, path: str = ""
) -> list[dict[str, Any]]:
    """Return lossless, type-sensitive differences addressed by JSON Pointer."""

    differences: list[dict[str, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                differences.append({
                    "path": child,
                    "before_present": key in before,
                    "after_present": key in after,
                    "before": before.get(key),
                    "after": after.get(key),
                })
            else:
                differences.extend(
                    _semantic_differences(before[key], after[key], child)
                )
    elif isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before) or index >= len(after):
                differences.append({
                    "path": child,
                    "before_present": index < len(before),
                    "after_present": index < len(after),
                    "before": before[index] if index < len(before) else None,
                    "after": after[index] if index < len(after) else None,
                })
            else:
                differences.extend(
                    _semantic_differences(before[index], after[index], child)
                )
    elif type(before) is not type(after) or before != after:
        differences.append({"path": path, "before": before, "after": after})
    return differences


def _capture_workload(
    predictive_map: PredictiveMap, workload: BenchmarkWorkload
) -> dict[str, Any]:
    """Replay independently, never inside a latency measurement.

    Keep full operation results and writer state (including audit and prediction).
    At every frontier validate strict restore, then compare its next operation
    with uninterrupted execution. Only the writer fingerprint moves to metadata.
    """

    engine = ZoneModelEngine(
        predictive_map, workload.occupants, workload.bootstrap_at
    )

    def state(model: ZoneModelEngine) -> dict[str, Any]:
        payload = serialize_target_state(predictive_map, model)
        del payload["map_fingerprint"]
        return _semantic_value(payload)  # type: ignore[no-any-return]

    initial = state(engine)
    restarted = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        engine.snapshot.updated_at,
    )
    initial_differences = _semantic_differences(initial, state(restarted))
    rows = []
    for event, received_at in zip(workload.events, workload.receive_at, strict=True):
        result = _semantic_value(engine.observe(event, processing_at=received_at))
        replayed = _semantic_value(
            restarted.observe(event, processing_at=received_at)
        )
        current = state(engine)
        continuation = _semantic_differences(
            {"result": result, "state": current},
            {"result": replayed, "state": state(restarted)},
        )
        restarted = restore_target_state(
            predictive_map,
            serialize_target_state(predictive_map, engine),
            engine.snapshot.updated_at,
        )
        restored = _semantic_differences(current, state(restarted))
        rows.append({
            "event": _semantic_value(event),
            "received_at": _semantic_value(received_at),
            "result": result,
            "state": current,
            "diagnostics": {
                "counters": _semantic_value(engine.diagnostic_counters),
                "latest_support_transition": _semantic_value(
                    engine.latest_support_transition
                ),
                "pending_prediction_learning": _semantic_value(
                    engine._pending_prediction_learning
                ),
            },
            "restore": {
                "continuation_differences": continuation,
                "state_differences": restored,
                "passed": not continuation and not restored,
            },
        })
    return {
        "occupants": workload.occupants,
        "started_at": _semantic_value(workload.started_at),
        "bootstrap_at": _semantic_value(workload.bootstrap_at),
        "event_count": len(workload.events),
        "initial_state": initial,
        "initial_restore_differences": initial_differences,
        "events": rows,
        "passed": not initial_differences
        and all(row["restore"]["passed"] for row in rows),
    }


def _validate_semantic_capture(payload: Any) -> None:
    """Reject missing profiles/counts/events rather than comparing empty reports."""

    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("trace_profile") not in TRACE_PROFILES
        or not isinstance(payload.get("metadata"), dict)
        or not isinstance(payload["metadata"].get("map_fingerprint"), str)
        or not payload["metadata"]["map_fingerprint"]
        or not isinstance(payload.get("counts"), dict)
        or not payload["counts"]
    ):
        raise ValueError("Invalid semantic capture schema, profile, or metadata")
    for count, workload in payload["counts"].items():
        if (
            not isinstance(workload, dict)
            or str(workload.get("occupants")) != count
            or type(workload.get("event_count")) is not int
            or not 0 <= workload["event_count"] <= MAX_BENCHMARK_EVENTS
            or not isinstance(workload.get("events"), list)
            or len(workload["events"]) != workload["event_count"]
            or not {"started_at", "bootstrap_at", "initial_state",
                    "initial_restore_differences", "passed"} <= workload.keys()
        ):
            raise ValueError("Invalid semantic workload or event count")
        for row in workload["events"]:
            if (
                not isinstance(row, dict)
                or not {"event", "received_at", "result", "state", "restore",
                    "diagnostics"}
                <= row.keys()
                or not isinstance(row["result"], dict)
                or not {"disposition", "snapshot", "authorizations",
                        "policy_events", "policy_decisions"} <= row["result"].keys()
            ):
                raise ValueError("Invalid semantic event result")


def _normalize_optional_handoff(before: Any, after: Any) -> None:
    """Align absent/null handoffs on result and pending-learning authorizations.

    Inputs are private comparison copies, not captures. Deliberately walk the
    capture schema rather than recursively matching field names. Nonnull values,
    including null-to-nonnull and absent-to-nonnull changes, remain untouched.
    """

    for count in before["counts"].keys() & after["counts"].keys():
        for old_row, new_row in zip(
            before["counts"][count]["events"],
            after["counts"][count]["events"],
            strict=False,
        ):
            for parent, array in (
                ("result", "authorizations"),
                ("diagnostics", "pending_prediction_learning"),
            ):
                old_parent, new_parent = old_row[parent], new_row[parent]
                if not isinstance(old_parent, dict) or not isinstance(new_parent, dict):
                    continue
                old_items, new_items = old_parent.get(array), new_parent.get(array)
                if not isinstance(old_items, list) or not isinstance(new_items, list):
                    continue
                for old, new in zip(old_items, new_items, strict=False):
                    if not isinstance(old, dict) or not isinstance(new, dict):
                        continue
                    key = "settled_handoff"
                    if key not in old and new.get(key) is None:
                        new.pop(key, None)
                    elif key not in new and old.get(key) is None:
                        old.pop(key, None)


def compare_semantic(before: Any, after: Any) -> dict[str, Any]:
    """Compare behavior with one explicitly approved schema representation rule.

    Only absent versus explicit null for optional settled_handoff directly on
    /counts/{count}/events/{event_index}/result/authorizations/{authorization_index}
    or /counts/{count}/events/{event_index}/diagnostics/pending_prediction_learning/
    {authorization_index} is equivalent. Preserve nonnull differences, other
    missing/null distinctions, unknown fields and nested lookalikes. Fingerprint
    changes are separately visible but not failures; capture and restore checks
    stay exact.
    """

    _validate_semantic_capture(before)
    _validate_semantic_capture(after)
    before = _semantic_value(before)
    after = _semantic_value(after)
    fingerprints = {
        "before": before["metadata"].pop("map_fingerprint"),
        "after": after["metadata"].pop("map_fingerprint"),
    }
    _normalize_optional_handoff(before, after)
    differences = _semantic_differences(before, after)
    return {
        "schema_version": 1,
        "normalization_rules": [
            "ABSENT equals explicit null only at "
            "/counts/{count}/events/{event_index}/result/authorizations/"
            "{authorization_index}/settled_handoff and "
            "/counts/{count}/events/{event_index}/diagnostics/"
            "pending_prediction_learning/{authorization_index}/settled_handoff "
            "on paired authorization "
            "objects in arrays; nonnull values and all other fields remain exact."
        ],
        "before_profile": before["trace_profile"],
        "after_profile": after["trace_profile"],
        "fingerprints": fingerprints,
        "fingerprints_equal": fingerprints["before"] == fingerprints["after"],
        "differences": differences,
        "passed": not differences
        and all(item["passed"] is True for item in before["counts"].values())
        and all(item["passed"] is True for item in after["counts"].values()),
    }


def _percentile(samples: list[float], quantile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _measure_core(
    predictive_map: PredictiveMap,
    workload: BenchmarkWorkload,
) -> tuple[dict[str, Any], ZoneModelEngine]:
    bootstrap_at = workload.bootstrap_at
    started_ns = perf_counter_ns()
    engine = ZoneModelEngine(predictive_map, workload.occupants, bootstrap_at)
    startup_ms = (perf_counter_ns() - started_ns) / 1_000_000
    samples: list[float] = []
    stale_events = 0
    policy_decisions = 0
    policy_events = 0
    token_max = 0
    support_max = 0
    support_binding_max = 0
    selected_slot_max = len(engine.snapshot.selected_paths)
    selected_path_max = 0
    selected_visit_max = 0
    selected_route_max = 0
    selected_source_max = len(engine.snapshot.selected_sources)
    health_state_max = len(engine.snapshot.path_health)
    health_cycle_max = 0
    for event, received_at in zip(workload.events, workload.receive_at, strict=True):
        started_ns = perf_counter_ns()
        result = engine.observe(event, processing_at=received_at)
        samples.append((perf_counter_ns() - started_ns) / 1_000_000)
        stale_events += result.disposition == "stale"
        policy_decisions += len(result.policy_decisions)
        policy_events += len(result.policy_events)
        token_max = max(token_max, len(result.snapshot.traversal_tokens))
        support_max = max(
            support_max,
            len(result.snapshot.anonymous_supports),
        )
        support_binding_max = max(
            support_binding_max,
            len(result.snapshot.support_token_bindings),
        )
        paths = [p for p in result.snapshot.selected_paths if p is not None]
        selected_slot_max = max(selected_slot_max, len(result.snapshot.selected_paths))
        selected_path_max = max(selected_path_max, len(paths))
        selected_visit_max = max(selected_visit_max,
                                 max((len(p.visits) for p in paths), default=0))
        selected_route_max = max(selected_route_max,
                                 max((len(p.route) for p in paths), default=0))
        selected_source_max = max(selected_source_max,
                                  len(result.snapshot.selected_sources))
        health_state_max = max(health_state_max, len(result.snapshot.path_health))
        health_cycle_max = max(health_cycle_max, max(
            (len(s.completed_cycles) for s in result.snapshot.path_health), default=0,
        ))
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
            "token_limit": TOKEN_LIMIT,
            "support_max": support_max,
            "support_limit": PRODUCT_MAX_OCCUPANTS,
            "support_binding_max": support_binding_max,
            "support_binding_limit": TOKEN_LIMIT,
            "selected_slot_max": selected_slot_max,
            "selected_path_max": selected_path_max,
            "selected_slot_limit": workload.occupants,
            "selected_visit_max": selected_visit_max,
            "selected_route_max": selected_route_max,
            "selected_history_limit": 4,
            "selected_source_max": selected_source_max,
            "selected_source_limit": len(predictive_map.nodes),
            "health_state_max": health_state_max,
            "health_state_limit": len(predictive_map.nodes),
            "health_cycle_max": health_cycle_max,
            "health_cycle_limit": QUICK_CYCLE_COUNT,
            "audit_entry_count": len(engine.audit_rows),
            "audit_bytes": audit_bytes,
            "persistence_bytes": len(encoded),
            "persistence_byte_stable": encoded == repeated,
        },
        engine,
    )


class _BenchmarkStates:
    """Minimal Home Assistant state registry for the publication benchmark."""

    def get(self, _entity_id: str) -> None:
        return None


class _BenchmarkHass:
    """Minimal host carrying the real runtime dispatch callbacks."""

    def __init__(self) -> None:
        self.states = _BenchmarkStates()
        self.data: dict[str, object] = {}
        self._dispatch: dict[str, list[Any]] = {}
        self._dispatch_counts: dict[str, dict[int, int]] = {}


class _BenchmarkBinarySensorEntity:
    """HA entity boundary whose write method timestamps the measured endpoint."""

    def async_on_remove(self, callback: Any) -> None:
        self._remove_callback = callback

    def async_write_ha_state(self) -> None:
        write_callback = getattr(self, "_benchmark_write_callback", None)
        if callable(write_callback):
            write_callback()


def _runtime_publication_types() -> tuple[
    type[Any],
    type[Any],
    type[Any],
    type[Any],
    type[Any],
]:
    """Load actual production runtime/entity types against finite HA boundaries."""

    module_names = (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.binary_sensor",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.dispatcher",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.event",
        "custom_components.predictive_controls.runtime",
        "custom_components.predictive_controls.binary_sensor",
    )
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in module_names}

    def callback(function: Any) -> Any:
        return function

    def connect(hass: _BenchmarkHass, signal: str, handler: Any) -> Any:
        counts = hass._dispatch_counts.setdefault(signal, {})

        def counted() -> None:
            counts[id(counted)] += 1
            handler()

        counts[id(counted)] = 0
        hass._dispatch.setdefault(signal, []).append(counted)

        def unsubscribe() -> None:
            hass._dispatch[signal].remove(counted)
            del counts[id(counted)]

        return unsubscribe

    def send(hass: _BenchmarkHass, signal: str) -> None:
        for handler in tuple(hass._dispatch.get(signal, ())):
            handler()

    def unsubscribe_factory(*_args: object, **_kwargs: object) -> Any:
        return lambda: None

    modules = {name: ModuleType(name) for name in module_names[:9]}
    modules["homeassistant.components.binary_sensor"].BinarySensorEntity = (  # type: ignore[attr-defined]
        _BenchmarkBinarySensorEntity
    )
    modules["homeassistant.config_entries"].ConfigEntry = object  # type: ignore[attr-defined]
    modules["homeassistant.core"].Event = object  # type: ignore[attr-defined]
    modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]
    modules["homeassistant.core"].callback = callback  # type: ignore[attr-defined]
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = (  # type: ignore[attr-defined]
        connect
    )
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = send  # type: ignore[attr-defined]
    modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = Any  # type: ignore[attr-defined]
    modules["homeassistant.helpers.event"].async_call_later = (  # type: ignore[attr-defined]
        unsubscribe_factory
    )
    modules["homeassistant.helpers.event"].async_track_state_change_event = (  # type: ignore[attr-defined]
        unsubscribe_factory
    )
    modules["homeassistant.helpers.event"].async_track_time_interval = (  # type: ignore[attr-defined]
        unsubscribe_factory
    )
    try:
        sys.modules.update(modules)
        sys.modules.pop("custom_components.predictive_controls.runtime", None)
        sys.modules.pop("custom_components.predictive_controls.binary_sensor", None)
        runtime_module = importlib.import_module(
            "custom_components.predictive_controls.runtime"
        )
        binary_sensor_module = importlib.import_module(
            "custom_components.predictive_controls.binary_sensor"
        )
        return (
            runtime_module.PredictiveControlsRuntime,
            binary_sensor_module.HomeActiveSensor,
            binary_sensor_module.PredictiveControlsProblemSensor,
            binary_sensor_module.ZoneActiveSensor,
            binary_sensor_module.ZoneDiagnosticEntryPathSensor,
        )
    finally:
        for name, prior in previous.items():
            if prior is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior  # type: ignore[assignment]


def _executed_fanout(hass: _BenchmarkHass, signal: str) -> bool:
    """Registration alone does not prove that preceding entity callbacks ran."""
    counts = hass._dispatch_counts.get(signal, {})
    return (bool(counts) and set(counts) == {
        id(handler) for handler in hass._dispatch.get(signal, ())
    } and min(counts.values()) > 0 and len(set(counts.values())) == 1)


def _handoff_fixture(
    predictive_map: PredictiveMap, started_at: datetime, *, correlated: bool,
) -> ZoneModelSnapshot:
    """REQ-PATH-002/003: two-hour observed source, initially inactive target.

    Both synthetic histories use only observations on the unchanged reference
    map. Ordinary continues the retained endpoint. Correlated first acquires and
    clears living-left, then branches from the still-asserted guest to stairs.
    Actual decay/dwell releases living before the measured correlated return.
    This is branch continuation, NOT a donor composite or a retired token transfer.
    """

    target_id = "living_left_sensor"
    event_at = started_at + timedelta(seconds=7203)
    frontier = event_at - timedelta(microseconds=1)

    def event(node_id: str, state: str, seconds: int) -> SensorInput:
        return SensorInput(
            next(iter(predictive_map.nodes[node_id].entities.values())),
            state, started_at + timedelta(seconds=seconds),
        )

    source = ZoneModelEngine(predictive_map, 2, started_at)
    route = (
        "dining_sensor", "foyer_sensor", "stairs_bottom_sensor",
        "guest_bedroom_sensor",
    )
    for seconds, node_id in enumerate(route):
        source.observe(event(node_id, "on", seconds))
    original_path, unlocated = source.snapshot.selected_paths
    assert original_path is not None and unlocated is None
    assert tuple(v.node_id for v in original_path.route) == route
    original_source = original_path.endpoint
    for seconds, node_id in enumerate(route[:-1], start=10):
        source.observe(event(node_id, "off", seconds))
    if correlated:
        # Initialize EVERY alias before ON: an unknown peer would make OFF
        # unavailable rather than clear and erase the cadence provenance.
        for alias in predictive_map.nodes[target_id].entities.values():
            source.observe(SensorInput(
                alias, "off", started_at + timedelta(seconds=6602),
            ))
        primed = source.observe(event(target_id, "on", 6603))
        assert any(e.zone == "living_room" and e.kind == "acquired"
                   for e in primed.policy_events)
        source.observe(event(target_id, "off", 6613))
        branch = source.observe(event("stairs_bottom_sensor", "on", 6630))
        assert branch.authorizations[0].selected_source_episode_ids == (
            original_source.episode_id,
        )
        releases: list[PolicyEvent] = []
        for seconds in range(6635, 7203, 5):
            releases.extend(source.advance(
                started_at + timedelta(seconds=seconds),
            ).policy_events)
        assert any(e.zone == "living_room" and e.kind == "released"
                   for e in releases)
    source.advance(frontier)
    snapshot = source.snapshot
    assert not source._pending_prediction_learning
    assert not snapshot.pending_candidates
    path, unlocated = snapshot.selected_paths
    assert path is not None and unlocated is None
    assert original_source in path.route
    payload = serialize_target_state(predictive_map, source)
    restored = restore_target_state(predictive_map, payload, frontier)
    assert restored.snapshot == snapshot
    assert serialize_target_state(predictive_map, restored) == payload
    _assert_handoff_source(predictive_map, snapshot)
    # Check the exact accepted frontier too, without counting a timer as evidence.
    advanced = restored.advance(event_at)
    assert not advanced.policy_events and not advanced.authorizations
    _assert_handoff_source(predictive_map, advanced.snapshot)
    return snapshot


def _assert_handoff_source(
    predictive_map: PredictiveMap, snapshot: ZoneModelSnapshot,
) -> None:
    """Fail setup closed unless every source predicate and isolation holds."""

    path, unlocated = snapshot.selected_paths
    assert path is not None and unlocated is None
    source = next(v for v in path.route if v.node_id == "guest_bedroom_sensor")
    node = next(
        n for n in build_physical_nodes(predictive_map).nodes
        if n.node_id == source.node_id
    )
    episode = next(s for s in snapshot.episode_states if s.node_id == node.node_id)
    belief = next(s for s in snapshot.belief_states if s.zone == node.zone)
    target = predictive_map.nodes["living_left_sensor"]
    assert snapshot.count_state.expected_count == 2
    assert source.branch_active and path.endpoint_eligible
    assert path.track_confidence == "confirmed"
    assert source.zone == node.zone != target.occupancy_zone
    assert node.node_id != target.node_id
    assert target.node_id in predictive_map.nodes[node.node_id].adjacent
    assert SHARED_PROFILES[node.profile_name].role == "stay"
    assert not node.interaction_aliases
    assert source.episode_id == episode.episode_id
    assert episode.episode_id is not None and episode.started_at is not None
    assert source.at == episode.started_at == episode.last_event_at
    assert snapshot.updated_at - source.at >= timedelta(hours=2, microseconds=-1)
    assert episode.status == "asserted" and episode.known_on
    assert not episode.health_warning and not episode.cadence_warning
    assert not belief.health_warning and belief.context == "asserted"
    assert (
        belief.generation_episode_id == belief.asserted_episode_id == episode.episode_id
    )
    assert belief.outward_context is None
    assert belief.probability >= POLICY_CALIBRATIONS[belief.profile_name].on_threshold
    assert episode.traversal_valid_until is not None
    assert episode.assertion_trust_until is not None
    assert (
        episode.traversal_valid_until
        < episode.assertion_trust_until < snapshot.updated_at
    )
    assert not snapshot.traversal_tokens and not snapshot.retained_traversal_tokens
    assert not snapshot.anonymous_supports
    assert not snapshot.support_token_bindings and not snapshot.authorization_uses
    assert all(p.node_id == target.node_id for p in snapshot.pending_candidates)
    assert not next(
        p for p in snapshot.policy_states if p.zone == target.occupancy_zone
    ).active


def _handoff_qualified(
    before: ZoneModelSnapshot, result: ZoneModelResult, *, correlated: bool,
) -> bool:
    """Qualify the real operation, not just a high belief or already-active seed."""

    event_at = before.updated_at + timedelta(microseconds=1)
    target_id, target_zone = "living_left_sensor", "living_room"
    return _selected_acquisition_qualified(
        before, result, target_id, target_zone, event_at,
        source_id="guest_bedroom_sensor",
        route=("stairs_bottom_sensor", "guest_bedroom_sensor", target_id),
        confidence="confirmed",
        disposition=(
            "accepted_correlated_positive" if correlated else "accepted_positive"
        ),
    )


def _acquisition_qualified(
    before: ZoneModelSnapshot, result: ZoneModelResult,
    target_zone: str, event_at: datetime,
    prediction: PredictionProof | None = None,
    *, require_prediction: bool = False,
) -> bool:
    """An ON level, refresh, wrong-zone event or absent decision is not an edge."""

    prior = next((p for p in before.policy_states if p.zone == target_zone), None)
    after = next((p for p in result.snapshot.policy_states
                  if p.zone == target_zone), None)
    events = [e for e in result.policy_events if e.zone == target_zone]
    decisions = [d for d in result.policy_decisions
                 if d.zone == target_zone and d.event_kind == "acquired"]
    if not (
        prior is not None and not prior.active and after is not None and after.active
        and result.disposition.startswith("accepted_")
        and result.snapshot.updated_at == event_at
        and len(events) == 1 and events[0].kind == "acquired"
        and events[0].event_at == event_at
        and len(decisions) == 1
    ):
        return False
    decision, = decisions
    if not (decision.event_at == event_at and not decision.active_before
            and decision.active_after and decision.authorization_authorized
            and decision.traversal_reason == events[0].authorization_reason):
        return False
    if require_prediction or after.phase == "predicted":
        return after.phase == "predicted" and prediction is not None and (
            _prediction_qualified(
                before, result, after, events[0], decision, prediction,
            )
        )
    return (
        decision.reason == "acquired" and decision.episode_id == events[0].episode_id
    )


def _prediction_qualified(
    before: ZoneModelSnapshot, result: ZoneModelResult, policy: ZonePolicyState,
    event: PolicyEvent, decision: PolicyDecision, proof: PredictionProof,
) -> bool:
    """PRED008: qualify independent post-timing state, not a fabricated episode."""
    model, leases, counts = proof
    matching = [lease for lease in leases if lease.target_zone == policy.zone
                and lease.source_episode_id == policy.prediction_source_episode_id]
    if len(matching) != 1:
        return False
    lease, = matching
    at = result.snapshot.updated_at
    grants = [grant for grant in result.snapshot.selected_prediction_grants
              if grant.key == (lease.source_node_id, lease.current_node_id,
                               lease.target_node_id, lease.source_episode_id)]
    if len(grants) != 1:
        return False
    grant, = grants
    authorization = grant.authorization
    current = next((e for e in result.snapshot.episode_states
                    if e.node_id == lease.current_node_id), None)
    source = next((e for e in before.episode_states
                   if e.node_id == lease.source_node_id), None)
    row = counts.get(lease.current_node_id)
    node = model.nodes.get(lease.current_node_id)
    target = model.nodes.get(lease.target_node_id)
    if (row is None or node is None or target is None
            or set(row) != set(node.adjacent)
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                   or v > MARKOV_COUNT_LIMIT
                   for v in row.values())):
        return False
    chain = MarkovChain(model)
    chain.restore_counts(counts)
    probability = chain.probabilities(lease.current_node_id).get(lease.target_node_id)
    return bool(
        result.disposition == "accepted_positive"
        and lease.authority_kind == "selected_prediction_grant" and lease.mature
        and lease.created_at == authorization.authorized_at == at
        and lease.expires_at == grant.expires_at == at + LEASE_DURATION
        and lease.expires_at == policy.prediction_expires_at
        and lease.probability == policy.prediction_probability == probability
        and lease.probability >= MATURITY_PROBABILITY
        and lease.support == policy.prediction_support == row.get(lease.target_node_id)
        and lease.support >= MATURITY_SUPPORT
        and target.occupancy_zone == policy.zone
        and lease.target_node_id in node.adjacent
        and grant.effect_kind == "positive"
        and authorization in result.authorizations and authorization.authorized
        and authorization.provenance_kind == authorization.reason == "selected_path"
        and authorization.track_confidence == "confirmed"
        and authorization.target_node_id == lease.current_node_id
        and authorization.target_episode_id == lease.source_episode_id
        and source is not None and source.episode_id is not None
        and source.episode_id in authorization.selected_source_episode_ids
        and current is not None and current.known_on and not current.cadence_correlated
        and current.episode_id == lease.source_episode_id
        and current.started_at == current.last_event_at == at
        and authorization.path_node_ids[-2:] == (
            lease.source_node_id, lease.current_node_id,
        )
        and any(p is not None and p.track_confidence == "confirmed"
                and p.endpoint.episode_id == lease.source_episode_id
            and tuple(v.node_id for v in p.route[-3:])
            == authorization.path_node_ids
                for p in result.snapshot.selected_paths)
        and policy.activation_provenance == "prediction"
        and event.episode_id == policy.prediction_source_episode_id
        and event.authorization_reason == decision.reason == "prediction_authorized"
        and event.policy_reason == "predicted"
        and decision.episode_id is None
        and decision.evidence_ids == (lease.source_episode_id,)
    )


def _selected_acquisition_qualified(
    before: ZoneModelSnapshot, result: ZoneModelResult,
    target_id: str, target_zone: str, event_at: datetime, *,
    source_id: str | None, route: tuple[str, ...], confidence: str,
    disposition: str = "accepted_positive",
) -> bool:
    """Check the selected ledger and observed source, not only a reason string."""

    if (not _acquisition_qualified(before, result, target_zone, event_at)
            or result.disposition != disposition or len(result.authorizations) != 1):
        return False
    authorization, = result.authorizations
    source = next((e for e in before.episode_states if e.node_id == source_id), None)
    paths = [p for p in result.snapshot.selected_paths if p is not None
             and p.endpoint.node_id == target_id and p.endpoint.at == event_at]
    if len(paths) != 1:
        return False
    path, = paths
    expected_kind = {"accepted_positive": "positive",
                     "accepted_correlated_positive": "correlated_positive",
                     "accepted_interaction": "interaction"}[disposition]
    if source_id is not None:
        if source is None or source.episode_id is None:
            return False
        # Independent time projection in the fixture test also checks belief.
        # Only advanced_at may change in the source's physical observation here.
        after_source = next(e for e in result.snapshot.episode_states
                            if e.node_id == source_id)
        if replace(after_source, advanced_at=source.advanced_at) != source:
            return False
        visit = next((v for v in path.route[:-1]
                      if v.episode_id == source.episode_id), None)
        if visit is None or visit.at != source.started_at:
            return False
        # The new route must continue an actual eligible prior occurrence, or
        # consume an ordinary live unlocated origin. A reason plus a target
        # endpoint cannot stand in for that lineage or preserve a fabricated slot.
        predecessors = [p for p in before.selected_paths if p is not None and any(
            v.episode_id == source.episode_id and (
                v.branch_active or (v == p.endpoint and p.endpoint_eligible)
            ) for v in p.route
        )]
        matching = [p for p in predecessors if any(
            v.episode_id == source.episode_id
            and (*p.route[:index + 1], path.endpoint)[-4:] == path.route
            for index, v in enumerate(p.route)
        )]
        if predecessors and not matching:
            return False
        if not predecessors:
            origin = next((s for s in before.selected_sources
                           if s.node_id == source_id), None)
            if (origin is None or origin.origin != "ordinary" or origin.consumed
                    or origin.episode_id != source.episode_id or not source.known_on
                    or path.route != (visit, path.endpoint)):
                return False
        old = matching[0] if matching else None
        remaining = tuple(
            p for p in before.selected_paths if p is not None and p != old
        )
        if remaining != tuple(
            p for p in result.snapshot.selected_paths if p is not None and p != path
        ):
            return False
    target = next(e for e in result.snapshot.episode_states if e.node_id == target_id)
    target_source = next((s for s in result.snapshot.selected_sources
                          if s.node_id == target_id), None)
    return bool(
        authorization.authorized and authorization.reason == "selected_path"
        and authorization.provenance_kind == "selected_path"
        and authorization.target_node_id == target_id
        and authorization.target_zone == target_zone
        and authorization.authorized_at == event_at
        and authorization.target_episode_id == path.endpoint.episode_id
        and authorization.selected_source_episode_ids == (
            () if source is None else (source.episode_id,)
        )
        and not authorization.source_tokens and not authorization.new_uses
        and authorization.settled_handoff is None
        and authorization.path_node_ids == route
        and tuple(v.node_id for v in path.route[-3:]) == route
        and path.track_confidence == authorization.track_confidence == confidence
        and path.endpoint.kind == expected_kind and path.endpoint.branch_active
        and path.updated_at == event_at and path.endpoint_eligible
        and target.episode_id == path.endpoint.episode_id
        and target.started_at == target.last_event_at == event_at
        and target.cadence_correlated == (expected_kind == "correlated_positive")
        and target_source is not None and target_source.consumed
        and target_source.episode_id == target.episode_id
        and target_source.at == event_at
        and before.selected_paths != result.snapshot.selected_paths
        and len(before.selected_paths) == len(result.snapshot.selected_paths) == 2
        and before.count_state == result.snapshot.count_state
        and not result.snapshot.traversal_tokens
        and not result.snapshot.anonymous_supports
        and not result.snapshot.support_token_bindings
    )


def _fast_path_qualified(
    name: str, before: ZoneModelSnapshot, result: ZoneModelResult,
    target_id: str, target_zone: str, at: datetime,
    prediction: PredictionProof | None = None,
) -> bool:
    """Requirement-mapped path checks, separate from publication scheduling."""

    if "settled_adjacent_transfer" in name:
        return _handoff_qualified(
            before, result, correlated=name.startswith("correlated_"),
        )
    if not _acquisition_qualified(
        before, result, target_zone, at, prediction,
        require_prediction=name == "mature_prediction",
    ):
        return False
    if name == "mature_prediction":
        return prediction is not None and any(
            lease.current_node_id == target_id and lease.target_zone == target_zone
            and lease.mature and lease.created_at == at
            for lease in prediction[1]
        )
    if name == "boundary":
        return any(a.authorized and a.target_node_id == target_id
                   and a.reason == "boundary_authorized"
                   for a in result.authorizations) and any(
            p is not None and p.endpoint.node_id == target_id
            and p.endpoint.at == at and len(p.route) == 1
            for p in result.snapshot.selected_paths
        )
    routes = {
        "adjacent_pair": ("entrance_sensor", "bathroom_laundry_sensor"),
        "third_node_confirmation": (
            "dining_sensor", "foyer_sensor", "stairs_bottom_sensor",
        ),
        "confirmed_token": (
            "foyer_sensor", "stairs_bottom_sensor", "guest_bedroom_sensor",
        ),
        "correlated_continuity": (
            "stairs_bottom_sensor", "stairs_top_sensor", "upstairs_bathroom_sensor",
        ),
        "cadence_correlated_target": ("stairs_bottom_sensor", "guest_bedroom_sensor"),
        "same_zone": ("living_right_sensor", "living_left_sensor"),
        "local_interaction": ("living_room_interaction",),
    }
    route = routes[name]
    return _selected_acquisition_qualified(
        before, result, target_id, target_zone, at,
        source_id=route[-2] if len(route) > 1 else None, route=route,
        confidence="confirmed" if len(route) == 3 else "provisional",
        disposition=("accepted_interaction" if name == "local_interaction" else
                     "accepted_correlated_positive"
                     if name == "cadence_correlated_target" else "accepted_positive"),
    )


def _measure_fast_paths(
    predictive_map: PredictiveMap,
    *,
    iterations: int = ROUTINE_BENCHMARK_EVENTS,
) -> dict[str, dict[str, Any]]:
    """Measure only the event that must schedule a supported active edge."""

    if not 1 <= iterations <= MAX_BENCHMARK_EVENTS:
        raise ValueError("Fast-path iterations must be between 1 and 1000")
    started_at = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)
    entities = {
        node_id: next(iter(predictive_map.nodes[node_id].entities.values()))
        for node_id in (
            "bathroom_laundry_sensor",
            "dining_sensor",
            "entrance_sensor",
            "foyer_sensor",
            "guest_bedroom_sensor",
            "gym_sensor",
            "living_left_sensor",
            "living_right_sensor",
            "stairs_bottom_sensor",
            "stairs_top_sensor",
            "upstairs_bathroom_sensor",
        )
    }
    boundary_map = _benchmark_map(
        predictive_map,
        role_overrides={"entrance_sensor": ("entry_boundary", "sustained")},
    )
    interaction_node_id = "living_room_interaction"
    interaction_map = _benchmark_map(
        predictive_map,
        additional_nodes={
            interaction_node_id: {
                "zone": "living_room",
                "role": "anchor_sensor",
                "occupancy_behavior": "sticky",
                "entities": {
                    "interaction_scene_001": "event.benchmark_bathroom_scene_001"
                },
                "reliability": 1.0,
            }
        },
    )
    entities[interaction_node_id] = next(
        iter(interaction_map.nodes[interaction_node_id].entities.values())
    )
    cadence_node_id = "guest_bedroom_sensor"
    cadence_entity_key = "cadence_guest_bedroom_sensor"
    cadence_map = _benchmark_map(
        predictive_map,
        entity_overrides={
            cadence_node_id: {
                "mmwave": "binary_sensor.benchmark_guest_bedroom_presence"
            },
        },
    )
    entities[cadence_entity_key] = next(
        iter(cadence_map.nodes[cadence_node_id].entities.values())
    )
    handoff_snapshots = {
        correlated: _handoff_fixture(predictive_map, started_at, correlated=correlated)
        for correlated in (False, True)
    }

    (
        runtime_type,
        home_entity_type,
        problem_entity_type,
        active_entity_type,
        diagnostic_entity_type,
    ) = _runtime_publication_types()

    def make_runtime(
        selected_map: PredictiveMap,
        occupants: int,
    ) -> Any:
        runtime = runtime_type(
            _BenchmarkHass(),
            selected_map,
            (),
            transition_window=30,
            expected_occupants=occupants,
        )
        runtime.confidence.ensure_state(started_at)
        return runtime

    def observe(runtime: Any, node_id: str, milliseconds: int) -> None:
        event_at = started_at + timedelta(milliseconds=milliseconds)
        entity_id = entities[node_id]
        runtime.observe_entity(
            entity_id,
            event_at.isoformat() if entity_id.startswith("event.") else "on",
            event_at,
        )

    samples: dict[str, list[float]] = {name: [] for name in FAST_PATH_EQUIVALENTS}
    activations = dict.fromkeys(samples, 0)
    publications = dict.fromkeys(samples, 0)
    qualifications = dict.fromkeys(samples, 0)
    public_writes = dict.fromkeys(samples, 0)
    preconditions = dict.fromkeys(samples, 0)
    fanouts = dict.fromkeys(samples, 0)
    callback_counts = dict.fromkeys(samples, 0)
    entity_counts: dict[str, tuple[int, int]] = {}

    def measured_observe(
        name: str,
        runtime: Any,
        node_id: str,
        milliseconds: int,
        target_zone: str,
    ) -> None:
        writes: list[tuple[int, bool]] = []
        before = runtime.confidence._current_snapshot()
        assert isinstance(before, ZoneModelSnapshot)
        zones = runtime.map.zones()
        target_entity = active_entity_type(runtime, "benchmark", target_zone)
        entities = [
            home_entity_type(runtime, "benchmark"),
            problem_entity_type(runtime, "benchmark"),
            *(
                target_entity
                if zone == target_zone
                else active_entity_type(runtime, "benchmark", zone)
                for zone in zones
            ),
            *(diagnostic_entity_type(runtime, "benchmark", zone) for zone in zones),
        ]
        for entity in entities:
            entity.hass = runtime.hass
        target_entity._benchmark_write_callback = lambda: writes.append(
            (perf_counter_ns(), target_entity.is_on)
        )

        async def add_entities() -> None:
            for entity in entities:
                await entity.async_added_to_hass()

        asyncio.run(add_entities())
        entity_counts[name] = (
            len(entities), len(runtime.hass._dispatch[target_entity.update_signal]),
        )
        prior_off = target_entity.is_on is False
        preconditions[name] += prior_off
        writes.clear()  # Platform registration is not an observation-caused ON.
        gc.collect()
        began = perf_counter_ns()
        observe(runtime, node_id, milliseconds)
        fanout = (
            entity_counts[name] == (2 + 2 * len(zones), 2 + len(zones))
            and _executed_fanout(runtime.hass, target_entity.update_signal)
        )
        fanouts[name] += fanout
        callback_counts[name] += sum(
            runtime.hass._dispatch_counts[target_entity.update_signal].values()
        )
        result = runtime.confidence._last_result
        at = started_at + timedelta(milliseconds=milliseconds)
        # Independent provenance is read only after the measured operation.
        proof: PredictionProof | None = None
        if name == "mature_prediction":
            proof = (runtime.map, runtime.confidence._engine.prediction_manager.leases,
                     runtime.confidence.prediction_chain.counts)
        acquired = prior_off and _acquisition_qualified(
            before, result, target_zone, at, proof,
            require_prediction=name == "mature_prediction",
        )
        qualified = acquired and fanout and _fast_path_qualified(
            name, before, result,
            cadence_node_id if node_id == cadence_entity_key else node_id,
            target_zone, at, *((proof,) if proof is not None else ()),
        )
        matching_write = acquired and len(writes) == 1 and writes[0][1] is True
        activations[name] += acquired
        qualifications[name] += qualified
        publications[name] += matching_write
        public_writes[name] += len(writes)
        if qualified and matching_write:
            samples[name].append((writes[0][0] - began) / 1_000_000)
        # No end-of-function/no-write fallback: rejected attempts are not latency.

    for _ in range(iterations):
        for correlated, snapshot in handoff_snapshots.items():
            name = (
                "correlated_settled_adjacent_transfer" if correlated
                else "settled_adjacent_transfer"
            )
            handoff = make_runtime(predictive_map, 2)
            seed = ZoneModelEngine.restore(
                predictive_map, snapshot, (), snapshot.updated_at,
            )
            payload = serialize_target_state(predictive_map, seed)
            assert handoff.restore_stored_state(payload, snapshot.updated_at)
            assert handoff.confidence.occupancy_store_data() == payload
            measured_observe(
                name, handoff, "living_left_sensor", 7_203_000, "living_room",
            )

        cadence = make_runtime(cadence_map, 2)
        # Isolated prime stays OFF; the later stairs origin authorizes acquisition.
        observe(cadence, cadence_entity_key, 1)
        cadence.observe_entity(
            entities[cadence_entity_key],
            "off",
            started_at + timedelta(milliseconds=20_000),
        )
        cadence.confidence.ensure_state(
            started_at + timedelta(milliseconds=30_000)
        )
        observe(cadence, "stairs_bottom_sensor", 40_000)
        measured_observe(
            "cadence_correlated_target",
            cadence,
            cadence_entity_key,
            45_000,
            "guest_bedroom",
        )

        interaction = make_runtime(interaction_map, 2)
        measured_observe(
            "local_interaction",
            interaction,
            interaction_node_id,
            1,
            "living_room",
        )

        pair = make_runtime(predictive_map, 2)
        observe(pair, "entrance_sensor", 1)
        measured_observe(
            "adjacent_pair",
            pair,
            "bathroom_laundry_sensor",
            2,
            "bathroom_laundry",
        )

        third = make_runtime(predictive_map, 2)
        observe(third, "dining_sensor", 1)
        observe(third, "foyer_sensor", 2)
        measured_observe(
            "third_node_confirmation",
            third,
            "stairs_bottom_sensor",
            3,
            "staircase_bottom",
        )

        confirmed = make_runtime(predictive_map, 2)
        observe(confirmed, "dining_sensor", 1)
        observe(confirmed, "foyer_sensor", 2)
        observe(confirmed, "stairs_bottom_sensor", 3)
        measured_observe(
            "confirmed_token",
            confirmed,
            "guest_bedroom_sensor",
            4,
            "guest_bedroom",
        )

        continuity = make_runtime(predictive_map, 2)
        observe(continuity, "stairs_bottom_sensor", 1)
        observe(continuity, "stairs_top_sensor", 2)
        continuity.observe_entity(
            entities["stairs_bottom_sensor"],
            "off",
            started_at + timedelta(milliseconds=20_000),
        )
        continuity.observe_entity(
            entities["stairs_top_sensor"],
            "off",
            started_at + timedelta(milliseconds=43_502),
        )
        observe(continuity, "stairs_top_sensor", 45_702)
        measured_observe(
            "correlated_continuity",
            continuity,
            "upstairs_bathroom_sensor",
            52_402,
            "upstairs_bathroom",
        )

        prediction = make_runtime(predictive_map, 2)
        for _support in range(11):
            prediction.confidence.prediction_chain.observe(
                "stairs_bottom_sensor", "guest_bedroom_sensor"
            )
        chain = prediction.confidence.prediction_chain
        assert chain.counts["stairs_bottom_sensor"]["guest_bedroom_sensor"] >= 5
        probability = chain.probabilities("stairs_bottom_sensor")[
            "guest_bedroom_sensor"
        ]
        assert probability >= 0.85
        observe(prediction, "dining_sensor", 1)
        observe(prediction, "foyer_sensor", 2)
        measured_observe(
            "mature_prediction",
            prediction,
            "stairs_bottom_sensor",
            3,
            "guest_bedroom",
        )

        same_zone = make_runtime(predictive_map, 2)
        # No dining approach: the first same-zone sensor is an unlocated origin,
        # not an already-ON living-room acquisition disguised as a refresh.
        observe(same_zone, "living_right_sensor", 2)
        measured_observe(
            "same_zone",
            same_zone,
            "living_left_sensor",
            3,
            "living_room",
        )

        boundary = make_runtime(boundary_map, 0)
        boundary.configured_expected_occupants = 2
        boundary.confidence.reconcile_expected_occupants(
            2,
            started_at + timedelta(milliseconds=1),
            evidence_id="benchmark-boundary-count",
        )
        measured_observe(
            "boundary",
            boundary,
            "entrance_sensor",
            2,
            "entrance_hallway",
        )

    return {
        name: {
            "current_equivalent": FAST_PATH_EQUIVALENTS[name],
            "fixture_kind": (
                "synthetic_learned_counts_and_observations"
                if name == "mature_prediction"
                else "synthetic_observations"
            ),
            "map_variant": (
                "synthetic_reference_derivative" if name in {
                    "boundary", "local_interaction", "cadence_correlated_target",
                } else "unchanged_reference"
            ),
            "requested_count": iterations,
            "attempt_count": iterations,
            "prior_off_count": preconditions[name],
            "failure_reasons": [reason for reason, passed in (
                ("target_not_initially_off", preconditions[name] == iterations),
                ("target_not_acquired", activations[name] == iterations),
                ("path_not_qualified", qualifications[name] == iterations),
                ("matching_on_write_missing", publications[name] == iterations),
                ("incomplete_fanout", fanouts[name] == iterations),
            ) if not passed],
            "sample_count": len(values),
            "activation_count": activations[name],
            "path_qualification_count": qualifications[name],
            "publication_count": publications[name],
            "public_write_count": public_writes[name],
            "fanout_count": fanouts[name],
            "dispatch_callback_count": callback_counts[name],
            "p99_ms": _percentile(values, 0.99) if values else None,
            "max_ms": max(values) if values else None,
            "all_activated": activations[name] == iterations,
            "all_path_qualified": qualifications[name] == iterations,
            "all_publications_scheduled": (
                publications[name] == iterations
                 and public_writes[name] == iterations
            ),
            "registered_entity_count": entity_counts[name][0],
            "update_subscriber_count": entity_counts[name][1],
            "p99_gate": (len(values) == iterations
                         and _percentile(values, 0.99) <= FAST_PATH_P99_MS),
            "hard_gate": len(values) == iterations and max(values) < FAST_PATH_HARD_MS,
        }
        for name, values in samples.items()
    }


def _rejected_jump_checks(
    before: ZoneModelSnapshot, result: ZoneModelResult,
    target_id: str, target_zone: str, at: datetime,
) -> dict[str, bool]:
    """Qualify actual rejection, not absence of an ON or a fabricated warning.

    Raw input is accepted_positive; traversal must explicitly reject it. This
    synthetic qualification replaces only the ordinary missed-edge benchmark.
    """

    authorizations = result.authorizations
    rejected = bool(
        result.disposition == "accepted_positive" and result.snapshot.updated_at == at
        and len(authorizations) == 1
        and authorizations[0].target_node_id == target_id
        and authorizations[0].target_zone == target_zone
        and authorizations[0].authorized_at == at
        and not authorizations[0].authorized
        and authorizations[0].reason == "track_bootstrap_pending"
        and any(
            d.zone == target_zone and d.node_id == target_id and d.event_at == at
            and d.episode_id == authorizations[0].target_episode_id
            and not d.authorization_authorized
            and d.traversal_reason == authorizations[0].reason
            and not d.active_before and not d.active_after and d.event_kind is None
            for d in result.policy_decisions
        )
    )
    return {
        "prior_off": any(p.zone == target_zone and not p.active
                         for p in before.policy_states),
        "remained_off": any(p.zone == target_zone and not p.active
                            for p in result.snapshot.policy_states),
        "rejection": rejected,
        "warning": any(
            w.node_id == target_id and w.zone == target_zone
            and w.kind == w.reason == "unsupported_jump" and w.cleared_at is None
            and w.first_observed_at == w.last_observed_at == at
            for w in result.snapshot.reliability_warning_occurrences
        ),
        "selection_unchanged": before.selected_paths == result.snapshot.selected_paths,
        "no_acquired": not any(e.kind == "acquired" for e in result.policy_events),
    }


def _measure_rejected_jumps(
    predictive_map: PredictiveMap, *, iterations: int = ROUTINE_BENCHMARK_EVENTS,
) -> dict[str, dict[str, Any]]:
    """Time complete runtime rejection/diagnostic dispatch, never an ON sample."""

    if not 1 <= iterations <= MAX_BENCHMARK_EVENTS:
        raise ValueError("Rejected-jump iterations must be between 1 and 1000")
    model = _benchmark_map(predictive_map, transition_overrides={
        "entrance_sensor": {"dining_sensor": 10.0},
        "dining_sensor": {"gym_sensor": 10.0},
    })
    started_at = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)
    at = started_at + timedelta(milliseconds=3)
    target_id, target_zone = "gym_sensor", "gym"
    target_input = next(iter(model.nodes[target_id].entities.values()))
    assert target_id not in model.nodes["entrance_sensor"].adjacent
    assert "dining_sensor" in model.nodes["entrance_sensor"].adjacent
    assert target_id in model.nodes["dining_sensor"].adjacent
    runtime_type, home_type, problem_type, active_type, diagnostic_type = (
        _runtime_publication_types()
    )
    samples: list[float] = []
    counts = dict.fromkeys((
        "prior_off", "remained_off", "rejection", "warning",
        "selection_unchanged", "no_acquired", "fanout",
    ), 0)
    attempts = qualified = on_writes = acquired_events = public_writes = callbacks = 0
    for _ in range(iterations):
        runtime = runtime_type(_BenchmarkHass(), model, (), transition_window=30,
                               expected_occupants=2)
        runtime.confidence.ensure_state(started_at)
        for ms, node_id in enumerate(("bathroom_laundry_sensor", "entrance_sensor"), 1):
            runtime.observe_entity(next(iter(model.nodes[node_id].entities.values())),
                                   "on", started_at + timedelta(milliseconds=ms))
        before = runtime.confidence._current_snapshot()
        assert isinstance(before, ZoneModelSnapshot)
        path, unlocated = before.selected_paths
        assert path is not None and unlocated is None
        assert tuple(v.node_id for v in path.route) == (
            "bathroom_laundry_sensor", "entrance_sensor",
        )
        # No unseen middle or target history is seeded into inference.
        assert all(e.generation == 0 for e in before.episode_states
                   if e.node_id in {"dining_sensor", target_id})
        assert not before.reliability_warning_occurrences
        target = active_type(runtime, "benchmark", target_zone)
        entities = [
            home_type(runtime, "benchmark"), problem_type(runtime, "benchmark"),
            *(target if zone == target_zone else active_type(runtime, "benchmark", zone)
              for zone in model.zones()),
            *(diagnostic_type(runtime, "benchmark", zone) for zone in model.zones()),
        ]
        writes: list[bool] = []
        target._benchmark_write_callback = lambda target=target, writes=writes: (
            writes.append(target.is_on)
        )

        async def add_entities(registered: list[Any], hass: Any) -> None:
            for entity in registered:
                entity.hass = hass
                await entity.async_added_to_hass()

        asyncio.run(add_entities(entities, runtime.hass))
        prior_off = target.is_on is False
        writes.clear()
        gc.collect()
        began = perf_counter_ns()
        runtime.observe_entity(target_input, "on", at)
        ended = perf_counter_ns()
        # Every returned attempt is timed, even if its correctness check fails.
        # Setup and qualification reads are outside this complete-dispatch interval.
        samples.append((ended - began) / 1_000_000)
        attempts += 1
        result = runtime.confidence._last_result
        assert isinstance(result, ZoneModelResult)
        checks = _rejected_jump_checks(before, result, target_id, target_zone, at)
        checks["prior_off"] = checks["prior_off"] and prior_off
        checks["remained_off"] = checks["remained_off"] and target.is_on is False
        checks["fanout"] = (
            len(entities) == 2 + 2 * len(model.zones())
            and len(runtime.hass._dispatch[target.update_signal])
            == 2 + len(model.zones())
            and _executed_fanout(runtime.hass, target.update_signal)
        )
        callbacks += sum(runtime.hass._dispatch_counts[target.update_signal].values())
        for key, value in checks.items():
            counts[key] += value
        on_writes += sum(writes)
        public_writes += len(writes)
        acquired_events += sum(e.kind == "acquired" for e in result.policy_events)
        qualified += all(checks.values()) and not any(writes)
    return {"rejected_jump": {
        "supersedes": "missed_edge",
        "fixture_kind": "synthetic_observations",
        "map_variant": "synthetic_reference_derivative",
        "occupants": 2,
        "requested_count": iterations,
        "attempt_count": attempts,
        "sample_count": len(samples),
        **{f"{key}_count": value for key, value in counts.items()},
        "qualified_count": qualified,
        "outcome": "rejected" if qualified == iterations else "failed",
        "on_write_count": on_writes,
        "public_write_count": public_writes,
        "dispatch_callback_count": callbacks,
        "acquired_event_count": acquired_events,
        "registered_entity_count": len(entities),
        "update_subscriber_count": len(runtime.hass._dispatch[target.update_signal]),
        "failure_reasons": [key for key, value in counts.items() if value != iterations]
        + (["target_on_write"] if on_writes else []),
        "p99_ms": _percentile(samples, 0.99),
        "max_ms": max(samples),
    }}


def _negative_workload_gates(
    workloads: dict[str, dict[str, Any]], iterations: int,
) -> dict[str, bool]:
    """Fail closed on absent/partial evidence, including forged summary flags."""

    trace = workloads.get("rejected_jump", {})
    p99, maximum = trace.get("p99_ms"), trace.get("max_ms")
    complete = _complete_counts(trace, iterations, (
        "requested_count", "attempt_count", "sample_count",
    ))
    return {
        "workload_present": set(workloads) == {"rejected_jump"},
        "samples_complete": complete,
        "correctness": complete and trace.get("outcome") == "rejected"
        and trace.get("failure_reasons") == []
        and _complete_counts(trace, iterations, (
            "prior_off_count", "remained_off_count", "rejection_count", "warning_count",
            "selection_unchanged_count", "no_acquired_count", "fanout_count",
            "qualified_count",
        ))
        and all(type(trace.get(key)) is int and trace[key] == 0
                for key in ("on_write_count", "acquired_event_count")),
        "p99_latency": complete and _finite_latency(p99, FAST_PATH_P99_MS),
        "hard_latency": complete and _finite_latency(
            maximum, FAST_PATH_HARD_MS, strict=True,
        ),
    }


def _complete_counts(trace: Mapping[str, Any], iterations: int,
                     keys: tuple[str, ...]) -> bool:
    return (1 <= iterations <= MAX_BENCHMARK_EVENTS and all(
        type(trace.get(key)) is int and trace[key] == iterations for key in keys
    ))


def _finite_latency(value: object, ceiling: float, *, strict: bool = False) -> bool:
    return (type(value) in (int, float) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0
            and (value < ceiling if strict else value <= ceiling))


def _positive_workload_gates(
    workloads: Mapping[str, Mapping[str, Any]], iterations: int, zones: int,
) -> dict[str, bool]:
    """Require the exact inventory and evidence, never all([]) or flags alone."""
    return {
        "workloads_present": set(workloads) == set(FAST_PATH_EQUIVALENTS),
        "samples_complete": bool(workloads) and all(_complete_counts(t, iterations, (
            "requested_count", "attempt_count", "sample_count", "prior_off_count",
            "activation_count", "path_qualification_count", "publication_count",
            "public_write_count", "fanout_count",
        )) for t in workloads.values()),
        "correctness": bool(workloads) and all(
            t.get("failure_reasons") == []
            and t.get("current_equivalent") == FAST_PATH_EQUIVALENTS.get(name)
            and t.get("registered_entity_count") == 2 + 2 * zones
            and t.get("update_subscriber_count") == 2 + zones
            and type(t.get("dispatch_callback_count")) is int
            and t["dispatch_callback_count"] >= iterations * (2 + zones)
            and all(t.get(key) is True for key in (
                "all_activated", "all_path_qualified", "all_publications_scheduled",
            )) for name, t in workloads.items()
        ),
        "p99_latency": bool(workloads) and all(
            _finite_latency(t.get("p99_ms"), FAST_PATH_P99_MS)
            and t.get("p99_gate") is True for t in workloads.values()
        ),
        "hard_latency": bool(workloads) and all(
            _finite_latency(t.get("max_ms"), FAST_PATH_HARD_MS, strict=True)
            and t.get("hard_gate") is True for t in workloads.values()
        ),
    }


def _timer_workload_gates(
    workloads: Mapping[str, Mapping[str, Any]], iterations: int,
) -> dict[str, bool]:
    return {
        "workloads_present": set(workloads) == TIMER_WORKLOAD_NAMES,
        "samples_complete": bool(workloads) and all(_complete_counts(t, iterations, (
            "requested_count", "attempt_count", "sample_count", "completion_count",
        )) for t in workloads.values()),
        "correctness": bool(workloads) and all(
            t.get("all_completed") is True for t in workloads.values()
        ),
        "p95_latency": bool(workloads) and all(
            _finite_latency(t.get("p95_ms"), PREFERRED_CALLBACK_MS)
            and t.get("p95_gate") is True for t in workloads.values()
        ),
        "hard_latency": bool(workloads) and all(
            _finite_latency(t.get("max_ms"), HARD_CALLBACK_MS)
            and t.get("hard_gate") is True for t in workloads.values()
        ),
    }


def _benchmark_map(
    predictive_map: PredictiveMap,
    *,
    role_overrides: dict[str, tuple[str, str]] | None = None,
    entity_overrides: dict[str, dict[str, str]] | None = None,
    transition_overrides: dict[str, dict[str, float]] | None = None,
    additional_nodes: dict[str, dict[str, object]] | None = None,
) -> PredictiveMap:
    """Clone the reference graph with one reviewed fast-path calibration."""

    role_overrides = {} if role_overrides is None else role_overrides
    entity_overrides = {} if entity_overrides is None else entity_overrides
    transition_overrides = {} if transition_overrides is None else transition_overrides
    additional_nodes = {} if additional_nodes is None else additional_nodes
    nodes: dict[str, dict[str, object]] = {}
    for node_id, node in predictive_map.nodes.items():
        role, behavior = role_overrides.get(
            node_id,
            (
                node.role,
                predictive_map.occupancy_behavior_for_node(node),
            ),
        )
        nodes[node_id] = {
            "label": node.label,
            "floor": node.floor,
            "zone": node.occupancy_zone,
            "role": role,
            "occupancy_behavior": behavior,
            "entities": entity_overrides.get(node_id, dict(node.entities)),
            "adjacent": list(node.adjacent),
            "transition_seconds": transition_overrides.get(
                node_id, node.transition_seconds
            ),
            "reliability": node.reliability,
            "route_prior_weight": node.route_prior_weight,
        }
    nodes.update(additional_nodes)
    return PredictiveMap.from_mapping({"nodes": nodes})


def _timer_health_map() -> PredictiveMap:
    """Synthetic unsupported target plus two independent selected paths (N=2)."""

    nodes: dict[str, object] = {
        "target_source": {
            "zone": "target_source",
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.target_source"},
            "adjacent": ["target"],
        },
        "target": {
            "zone": "target",
            "entities": {"motion": "binary_sensor.target"},
            "adjacent": ["target_source"],
        },
    }
    for prefix in ("a", "d"):
        first, middle, stay = prefix, f"{prefix}m", f"{prefix}s"
        nodes[first] = {
            "zone": first,
            "entities": {"motion": f"binary_sensor.{first}"},
            "adjacent": [middle],
        }
        nodes[middle] = {
            "zone": middle,
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": f"binary_sensor.{middle}"},
            "adjacent": [first, stay],
        }
        nodes[stay] = {
            "zone": stay,
            "entities": {"motion": f"binary_sensor.{stay}"},
            "adjacent": [middle],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


def _health_deadline_qualified(
    before: ZoneModelSnapshot, result: ZoneModelResult, deadline: datetime,
) -> bool:
    """REQ-HEALTH-001/003 replaces diagnostic count-conflict degradation."""

    ledger = next(s for s in before.path_health if s.node_id == "target")
    episode = next(s for s in before.episode_states if s.node_id == "target")
    target = next(s for s in result.snapshot.episode_states if s.node_id == "target")
    return bool(
        ledger.phase == "on" and ledger.unsupported_started_at is not None
        and ledger.unsupported_started_at + UNSUPPORTED_ON_WINDOW == deadline
        and before.updated_at == deadline - timedelta(microseconds=1)
        and not before.reliability_warning_occurrences
        and len(before.selected_paths) == 2
        and all(p is not None for p in before.selected_paths)
        and result.snapshot.updated_at == deadline
        and len(result.snapshot.reliability_warning_occurrences) == 1
        and any(w.node_id == "target" and w.reason == "assertion_timeout"
                and w.first_observed_at == w.last_observed_at == deadline
                and w.cleared_at is None
                for w in result.snapshot.reliability_warning_occurrences)
        and target.status == "asserted" and target.known_on
        and not target.health_warning and target.degradation_reason is None
        and replace(target, advanced_at=episode.advanced_at) == episode
        and before.selected_paths == result.snapshot.selected_paths
        and before.selected_sources == result.snapshot.selected_sources
        and before.count_state == result.snapshot.count_state
        and [(s.zone, s.active) for s in before.policy_states]
        == [(s.zone, s.active) for s in result.snapshot.policy_states]
        and not result.policy_events and not result.authorizations
        and not result.snapshot.count_conflicts
    )


def _measure_timer_work(
    *,
    iterations: int = ROUTINE_BENCHMARK_EVENTS,
) -> dict[str, dict[str, float | int | bool]]:
    """Measure bounded deadline work that intentionally follows fast publication."""

    if not 1 <= iterations <= MAX_BENCHMARK_EVENTS:
        raise ValueError("Timer-work iterations must be between 1 and 1000")
    started_at = datetime(2026, 7, 18, 14, 0, tzinfo=UTC)
    pending_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "isolated": {
                    "entities": {"motion": "binary_sensor.isolated"},
                }
            }
        }
    )
    health_map = _timer_health_map()
    samples: dict[str, list[float]] = {
        "pending_expiry": [],
        "unsupported_on_health_deadline": [],
    }
    completed: dict[str, int] = dict.fromkeys(samples, 0)

    for _ in range(iterations):
        pending = ZoneModelEngine(pending_map, 1, started_at)
        pending.observe(SensorInput("binary_sensor.isolated", "on", started_at))
        pending_deadline = pending.snapshot.pending_candidates[0].expires_at
        pending.advance(pending_deadline - timedelta(microseconds=1))
        assert len(pending.snapshot.pending_candidates) == 1
        began = perf_counter_ns()
        pending_result = pending.advance(pending_deadline)
        samples["pending_expiry"].append((perf_counter_ns() - began) / 1_000_000)
        completed["pending_expiry"] += (
            not pending_result.snapshot.pending_candidates
            and not pending_result.policy_events and not pending_result.authorizations
            and not any(p.active for p in pending_result.snapshot.policy_states)
        )

        health = ZoneModelEngine(health_map, 2, started_at)
        for node_id, seconds in (
            ("target", 0),
            ("a", 1),
            ("am", 2),
            ("as", 3),
            ("d", 4),
            ("dm", 5),
            ("ds", 6),
        ):
            health.observe(
                SensorInput(
                    f"binary_sensor.{node_id}",
                    "on",
                    started_at + timedelta(seconds=seconds),
                )
            )
        ledger = next(s for s in health.snapshot.path_health if s.node_id == "target")
        assert ledger.unsupported_started_at == started_at
        deadline = ledger.unsupported_started_at + UNSUPPORTED_ON_WINDOW
        health.advance(deadline - timedelta(microseconds=1))
        before = health.snapshot
        assert not before.reliability_warning_occurrences
        began = perf_counter_ns()
        result = health.advance(deadline)
        samples["unsupported_on_health_deadline"].append(
            (perf_counter_ns() - began) / 1_000_000,
        )
        completed["unsupported_on_health_deadline"] += _health_deadline_qualified(
            before, result, deadline,
        )

    return {
        name: {
            "requested_count": iterations,
            "attempt_count": len(values),
            "sample_count": len(values),
            "completion_count": completed[name],
            "p95_ms": _percentile(values, 0.95),
            "max_ms": max(values),
            "all_completed": completed[name] == iterations,
            "p95_gate": _percentile(values, 0.95) <= PREFERRED_CALLBACK_MS,
            "hard_gate": max(values) <= HARD_CALLBACK_MS,
        }
        for name, values in samples.items()
    }


def run_benchmark(
    map_path: Path,
    *,
    event_count: int = ROUTINE_BENCHMARK_EVENTS,
    target_counts: tuple[int, ...] = (2,),
    trace_profile: str = "deterministic",
    semantic_output: Path | None = None,
) -> dict[str, Any]:
    if not 0 <= event_count <= MAX_BENCHMARK_EVENTS:
        raise ValueError("Benchmark event count must not exceed 1000")
    if trace_profile not in TRACE_PROFILES:
        raise ValueError(f"Unknown trace profile: {trace_profile}")
    if not target_counts or len(set(target_counts)) != len(target_counts):
        raise ValueError("Benchmark requires distinct occupant counts")
    predictive_map = load_predictive_map(map_path.read_text())
    started_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    counts: dict[str, Any] = {}
    workloads: list[BenchmarkWorkload] = []
    passed = True
    fast_paths = _measure_fast_paths(predictive_map, iterations=event_count or 1)
    negative_workloads = _measure_rejected_jumps(
        predictive_map, iterations=event_count or 1,
    )
    negative_gates = _negative_workload_gates(negative_workloads, event_count or 1)
    timer_work = _measure_timer_work(iterations=event_count or 1)
    positive_gates = _positive_workload_gates(
        fast_paths, event_count or 1, len(predictive_map.zones()),
    )
    timer_gates = _timer_workload_gates(timer_work, event_count or 1)
    passed = passed and all(negative_gates.values())
    passed = passed and all(positive_gates.values()) and all(timer_gates.values())
    for occupants in target_counts:
        workload = _build_workload(
            predictive_map,
            event_count=event_count,
            started_at=started_at,
            occupants=occupants,
            trace_profile=trace_profile,
        )
        workloads.append(workload)
        core, _engine = _measure_core(predictive_map, workload)
        gates = {
            "preferred_callback": core["p95_ms"] <= PREFERRED_CALLBACK_MS,
            "hard_callback": core["max_ms"] <= HARD_CALLBACK_MS,
            "bounded_tokens": core["token_max"] <= core["token_limit"],
            "bounded_supports": core["support_max"] <= core["support_limit"],
            "bounded_support_bindings": core["support_binding_max"]
            <= core["support_binding_limit"],
            "bounded_selected_slots": core["selected_path_max"]
            <= core["selected_slot_max"] == core["selected_slot_limit"],
            "bounded_selected_history": max(
                core["selected_visit_max"], core["selected_route_max"],
            ) <= core["selected_history_limit"],
            "bounded_selected_sources": core["selected_source_max"]
            <= core["selected_source_limit"],
            "bounded_health_state": core["health_state_max"]
            <= core["health_state_limit"],
            "bounded_health_cycles": core["health_cycle_max"]
            <= core["health_cycle_limit"],
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
    if semantic_output is not None:
        semantic_counts = {
            str(workload.occupants): _capture_workload(predictive_map, workload)
            for workload in workloads
        }
        semantic = {
            "schema_version": 1,
            "trace_profile": trace_profile,
            "metadata": {"map_fingerprint": target_map_fingerprint(predictive_map)},
            "counts": semantic_counts,
        }
        _validate_semantic_capture(semantic)
        semantic_output.write_text(_render_json(semantic), encoding="utf-8")
        passed = passed and all(item["passed"] for item in semantic_counts.values())
    return {
        "schema_version": 3,
        "engine": "zone_belief",
        "trace_profile": trace_profile,
        "latency_endpoint": (
            "accepted runtime observation through the full registered binary-sensor "
            "dispatcher fanout and the corresponding ZoneActiveSensor projection "
            "to async_write_ha_state"
        ),
        "timer_latency_endpoint": (
            "ZoneModelEngine.advance at the declared deadline with setup excluded"
        ),
        "rejection_latency_endpoint": (
            "runtime.observe_entity dispatch through completed rejection, committed "
            "unsupported_jump diagnostic and full registered binary-sensor fanout; "
            "ends on return, excluding setup and qualification reads"
        ),
        "map": {
            "path": str(map_path),
            "nodes": len(predictive_map.nodes),
            "zones": len(predictive_map.zones()),
            "occupants": list(target_counts),
        },
        "counts": counts,
        "fast_paths": fast_paths,
        "positive_gates": positive_gates,
        "negative_workloads": negative_workloads,
        "negative_gates": negative_gates,
        "timer_work": timer_work,
        "timer_gates": timer_gates,
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
    parser.add_argument("--semantic-output", type=Path)
    parser.add_argument("--compare-semantic", type=Path, nargs=2,
                        metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    try:
        inputs = args.compare_semantic or [args.map]
        outputs = [path for path in (args.output, args.semantic_output)
                   if path is not None]
        resolved = [path.resolve() for path in outputs]
        if len(set(resolved)) != len(resolved) or any(
            path.resolve() in resolved for path in inputs
        ):
            raise ValueError("Output paths must be distinct from each other and inputs")
        if args.compare_semantic:
            if args.semantic_output is not None:
                raise ValueError("Comparison cannot also capture semantic output")
            before, after = (
                json.loads(path.read_text(encoding="utf-8"))
                for path in args.compare_semantic
            )
            result = compare_semantic(before, after)
        else:
            result = run_benchmark(
                args.map,
                event_count=args.events,
                trace_profile=args.trace_profile,
                semantic_output=args.semantic_output,
            )
        rendered = _render_json(result)
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.write_text(rendered, encoding="utf-8")
            if not result["passed"]:
                print(rendered, end="", file=sys.stderr)
    except (OSError, ValueError, TypeError) as error:
        print(_render_json({"passed": False, "error": str(error)}),
              end="", file=sys.stderr)
        raise SystemExit(2) from error
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
