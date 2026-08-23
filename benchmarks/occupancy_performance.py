"""Deterministic performance benchmark for the target zone-belief engine."""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from types import ModuleType
from typing import Any

from custom_components.predictive_controls.const import PRODUCT_MAX_OCCUPANTS
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.policy import PolicyAuditLog
from custom_components.predictive_controls.zone_model.traversal import TOKEN_LIMIT
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
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
    support_max = 0
    support_binding_max = 0
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
        hass._dispatch.setdefault(signal, []).append(handler)

        def unsubscribe() -> None:
            hass._dispatch[signal].remove(handler)

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


def _measure_fast_paths(
    predictive_map: PredictiveMap,
    *,
    iterations: int = ROUTINE_BENCHMARK_EVENTS,
) -> dict[str, dict[str, float | int | bool]]:
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
    missed_edge_map = _benchmark_map(
        predictive_map,
        transition_overrides={
            "entrance_sensor": {"dining_sensor": 10.0},
            "dining_sensor": {"gym_sensor": 10.0},
        },
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

    samples: dict[str, list[float]] = {
        "adjacent_pair": [],
        "boundary": [],
        "cadence_correlated_target": [],
        "confirmed_token": [],
        "correlated_continuity": [],
        "local_interaction": [],
        "missed_edge": [],
        "same_zone": [],
        "third_node_confirmation": [],
        "mature_prediction": [],
    }
    activations = dict.fromkeys(samples, 0)
    publications = dict.fromkeys(samples, 0)
    qualifications = dict.fromkeys(samples, 0)

    def measured_observe(
        name: str,
        runtime: Any,
        node_id: str,
        milliseconds: int,
        target_zone: str,
    ) -> Any:
        write_ns: list[int] = []
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
        target_entity._benchmark_write_callback = lambda: write_ns.append(
            perf_counter_ns()
        )

        async def add_entities() -> None:
            for entity in entities:
                await entity.async_added_to_hass()

        asyncio.run(add_entities())
        gc.collect()
        began = perf_counter_ns()
        observe(runtime, node_id, milliseconds)
        finished = perf_counter_ns()
        written = write_ns[0] if write_ns else finished
        samples[name].append((written - began) / 1_000_000)
        publications[name] += bool(write_ns)
        return runtime.confidence

    for _ in range(iterations):
        cadence = make_runtime(cadence_map, 2)
        observe(cadence, "living_left_sensor", 0)
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
        cadence_result = measured_observe(
            "cadence_correlated_target",
            cadence,
            cadence_entity_key,
            45_000,
            "guest_bedroom",
        )
        activations["cadence_correlated_target"] += any(
            policy.zone == "guest_bedroom" and policy.active
            for policy in cadence_result.policy_states.values()
        )
        qualifications["cadence_correlated_target"] += (
            any(
                state.node_id == cadence_node_id and state.cadence_correlated
                for state in cadence_result.episode_states
            )
            and any(
                authorization.target_node_id == cadence_node_id
                and authorization.authorized
                for authorization in cadence_result.authorizations
            )
        )

        interaction = make_runtime(interaction_map, 2)
        interaction_result = measured_observe(
            "local_interaction",
            interaction,
            interaction_node_id,
            1,
            "living_room",
        )
        activations["local_interaction"] += any(
            policy.zone == "living_room" and policy.active
            for policy in interaction_result.policy_states.values()
        )
        qualifications["local_interaction"] += any(
            item.reason == "local_interaction"
            and item.provenance_kind == "local_interaction"
            and item.equivalent_confirmed_strength
            for item in interaction_result.authorizations
        )

        pair = make_runtime(predictive_map, 2)
        observe(pair, "entrance_sensor", 1)
        pair_result = measured_observe(
            "adjacent_pair",
            pair,
            "bathroom_laundry_sensor",
            2,
            "bathroom_laundry",
        )
        activations["adjacent_pair"] += any(
            policy.zone == "bathroom_laundry" and policy.active
            for policy in pair_result.policy_states.values()
        )
        qualifications["adjacent_pair"] += any(
            item.reason == "provisional_track_acquired"
            for item in pair_result.authorizations
        )

        third = make_runtime(predictive_map, 2)
        observe(third, "dining_sensor", 1)
        observe(third, "foyer_sensor", 2)
        third_result = measured_observe(
            "third_node_confirmation",
            third,
            "stairs_bottom_sensor",
            3,
            "staircase_bottom",
        )
        activations["third_node_confirmation"] += any(
            policy.zone == "staircase_bottom" and policy.active
            for policy in third_result.policy_states.values()
        )
        qualifications["third_node_confirmation"] += any(
            item.reason == "track_confirmed" for item in third_result.authorizations
        )

        confirmed = make_runtime(predictive_map, 2)
        observe(confirmed, "dining_sensor", 1)
        observe(confirmed, "foyer_sensor", 2)
        observe(confirmed, "stairs_bottom_sensor", 3)
        confirmed_result = measured_observe(
            "confirmed_token",
            confirmed,
            "guest_bedroom_sensor",
            4,
            "guest_bedroom",
        )
        activations["confirmed_token"] += any(
            policy.zone == "guest_bedroom" and policy.active
            for policy in confirmed_result.policy_states.values()
        )
        qualifications["confirmed_token"] += any(
            item.reason == "adjacent_authorized"
            and item.track_confidence == "confirmed"
            for item in confirmed_result.authorizations
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
        continuity_result = measured_observe(
            "correlated_continuity",
            continuity,
            "upstairs_bathroom_sensor",
            52_402,
            "upstairs_bathroom",
        )
        activations["correlated_continuity"] += any(
            policy.zone == "upstairs_bathroom" and policy.active
            for policy in continuity_result.policy_states.values()
        )
        qualifications["correlated_continuity"] += any(
            item.reason == "track_confirmed"
            and item.path_node_ids
            == (
                "stairs_bottom_sensor",
                "stairs_top_sensor",
                "upstairs_bathroom_sensor",
            )
            for item in continuity_result.authorizations
        )

        prediction = make_runtime(predictive_map, 2)
        for _support in range(11):
            prediction.confidence.prediction_chain.observe(
                "stairs_bottom_sensor", "guest_bedroom_sensor"
            )
        observe(prediction, "dining_sensor", 1)
        observe(prediction, "foyer_sensor", 2)
        prediction_result = measured_observe(
            "mature_prediction",
            prediction,
            "stairs_bottom_sensor",
            3,
            "guest_bedroom",
        )
        activations["mature_prediction"] += any(
            policy.zone == "guest_bedroom"
            and policy.active
            and policy.phase == "predicted"
            for policy in prediction_result.policy_states.values()
        )
        qualifications["mature_prediction"] += any(
            item.zone == "guest_bedroom"
            and item.authorization_reason == "prediction_authorized"
            for item in prediction_result.policy_events
        )

        same_zone = make_runtime(predictive_map, 2)
        observe(same_zone, "dining_sensor", 1)
        observe(same_zone, "living_right_sensor", 2)
        same_zone_result = measured_observe(
            "same_zone",
            same_zone,
            "living_left_sensor",
            3,
            "living_room",
        )
        activations["same_zone"] += any(
            policy.zone == "living_room" and policy.active
            for policy in same_zone_result.policy_states.values()
        )
        qualifications["same_zone"] += any(
            item.reason == "same_zone_authorized"
            for item in same_zone_result.authorizations
        )

        boundary = make_runtime(boundary_map, 0)
        boundary.configured_expected_occupants = 2
        boundary.confidence.reconcile_expected_occupants(
            2,
            started_at + timedelta(milliseconds=1),
            evidence_id="benchmark-boundary-count",
        )
        boundary_result = measured_observe(
            "boundary",
            boundary,
            "entrance_sensor",
            2,
            "entrance_hallway",
        )
        activations["boundary"] += any(
            policy.zone == "entrance_hallway" and policy.active
            for policy in boundary_result.policy_states.values()
        )
        qualifications["boundary"] += any(
            item.reason == "boundary_authorized"
            for item in boundary_result.authorizations
        )

        missed = make_runtime(missed_edge_map, 2)
        observe(missed, "bathroom_laundry_sensor", 1)
        observe(missed, "entrance_sensor", 2)
        missed_result = measured_observe(
            "missed_edge",
            missed,
            "gym_sensor",
            3,
            "gym",
        )
        activations["missed_edge"] += any(
            policy.zone == "gym" and policy.active
            for policy in missed_result.policy_states.values()
        )
        qualifications["missed_edge"] += any(
            item.reason == "missed_edge_authorized"
            for item in missed_result.authorizations
        )

    return {
        name: {
            "sample_count": len(values),
            "p99_ms": _percentile(values, 0.99),
            "max_ms": max(values),
            "all_activated": activations[name] == iterations,
            "all_path_qualified": qualifications[name] == iterations,
            "all_publications_scheduled": publications[name] == iterations,
            "registered_entity_count": 2 + 2 * len(predictive_map.zones()),
            "update_subscriber_count": 2 + len(predictive_map.zones()),
            "p99_gate": _percentile(values, 0.99) <= FAST_PATH_P99_MS,
            "hard_gate": max(values) < FAST_PATH_HARD_MS,
        }
        for name, values in samples.items()
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


def _timer_conflict_map() -> PredictiveMap:
    """Build the finite graph used to benchmark count-conflict deadline work."""

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
    conflict_map = _timer_conflict_map()
    samples: dict[str, list[float]] = {
        "pending_expiry": [],
        "count_conflict": [],
    }
    completed: dict[str, int] = dict.fromkeys(samples, 0)

    for _ in range(iterations):
        pending = ZoneModelEngine(pending_map, 1, started_at)
        pending.observe(SensorInput("binary_sensor.isolated", "on", started_at))
        pending_deadline = pending.snapshot.pending_candidates[0].expires_at
        began = perf_counter_ns()
        pending_result = pending.advance(pending_deadline)
        samples["pending_expiry"].append((perf_counter_ns() - began) / 1_000_000)
        completed["pending_expiry"] += not pending_result.snapshot.pending_candidates

        conflict = ZoneModelEngine(conflict_map, 2, started_at)
        for node_id, seconds in (
            ("target_source", 0),
            ("target", 1),
            ("a", 2),
            ("am", 3),
            ("as", 4),
            ("d", 5),
            ("dm", 6),
            ("ds", 7),
        ):
            conflict.observe(
                SensorInput(
                    f"binary_sensor.{node_id}",
                    "on",
                    started_at + timedelta(seconds=seconds),
                )
            )
        conflict_deadline = conflict.snapshot.count_conflicts[0].deadline
        began = perf_counter_ns()
        conflict_result = conflict.advance(conflict_deadline)
        samples["count_conflict"].append((perf_counter_ns() - began) / 1_000_000)
        target = next(
            state
            for state in conflict_result.snapshot.episode_states
            if state.node_id == "target"
        )
        completed["count_conflict"] += (
            target.health_warning and target.degradation_reason == "count_conflict"
        )

    return {
        name: {
            "sample_count": len(values),
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
) -> dict[str, Any]:
    if event_count > MAX_BENCHMARK_EVENTS:
        raise ValueError("Benchmark event count must not exceed 1000")
    predictive_map = load_predictive_map(map_path.read_text())
    started_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    counts: dict[str, Any] = {}
    passed = True
    fast_paths = _measure_fast_paths(predictive_map, iterations=event_count or 1)
    timer_work = _measure_timer_work(iterations=event_count or 1)
    passed = passed and all(
        bool(trace[gate])
        for trace in fast_paths.values()
        for gate in (
            "all_activated",
            "all_path_qualified",
            "all_publications_scheduled",
            "p99_gate",
            "hard_gate",
        )
    )
    passed = passed and all(
        bool(trace[gate])
        for trace in timer_work.values()
        for gate in ("all_completed", "p95_gate", "hard_gate")
    )
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
            "bounded_supports": core["support_max"] <= core["support_limit"],
            "bounded_support_bindings": core["support_binding_max"]
            <= core["support_binding_limit"],
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
        "map": {
            "path": str(map_path),
            "nodes": len(predictive_map.nodes),
            "zones": len(predictive_map.zones()),
            "occupants": list(target_counts),
        },
        "counts": counts,
        "fast_paths": fast_paths,
        "timer_work": timer_work,
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
