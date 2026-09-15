"""Typed current-engine/component composites; never historical incident inputs.

Real independent components donate only explicitly selected complete records.
Current selection, health, physical holds and both prediction tables are retained.
Every composite passes the unchanged strict reader before use.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    _json_value,
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    SensorInput,
    ZoneModelSnapshot,
)
from tests.persistence_component_fixture import PersistenceComponents
from tests.test_zone_model_persistence import structural_payload

START = datetime(2026, 9, 8, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def event(node: str, state: str, seconds: float) -> SensorInput:
    domain = "event" if state == "pressed" else "binary_sensor"
    return SensorInput(f"{domain}.{node}", state, at(seconds))


def graph(
    adjacent: Mapping[str, tuple[str, ...]], *,
    presence: frozenset[str] = frozenset(),
    interactions: frozenset[str] = frozenset(),
    zones: Mapping[str, str] | None = None,
    entries: frozenset[str] = frozenset(),
    sticky: frozenset[str] = frozenset(),
) -> PredictiveMap:
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "zone": node if zones is None else zones.get(node, node),
            "role": "household_boundary" if node in entries else "room_occupancy",
            "occupancy_behavior": "sticky" if node in sticky else "sustained",
            "entities": {
                "interaction" if node in interactions else
                "mmwave" if node in presence else "motion":
                f"event.{node}" if node in interactions else f"binary_sensor.{node}",
            },
            "adjacent": list(neighbors),
        } for node, neighbors in adjacent.items()
    }})


def chain(*nodes: str, presence: frozenset[str] = frozenset()) -> PredictiveMap:
    return graph({node: tuple(nodes[max(0, i - 1):i] + nodes[i + 1:i + 2])
                  for i, node in enumerate(nodes)}, presence=presence)


def roundtrip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> ZoneModelEngine:
    payload = serialize_target_state(predictive_map, engine)
    original = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == payload == original
    return restored


def snapshot_payload(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
    snapshot: ZoneModelSnapshot, *, audit: tuple[PolicyDecision, ...] | None = None,
) -> dict[str, object]:
    payload = serialize_target_state(predictive_map, engine)
    payload["snapshot"] = _json_value(asdict(snapshot))
    if audit is not None:
        payload["audit"] = [_json_value(asdict(row)) for row in audit]
    return payload


def compose(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
    snapshot: ZoneModelSnapshot, *, audit: tuple[PolicyDecision, ...] | None = None,
) -> ZoneModelEngine:
    payload = snapshot_payload(predictive_map, engine, snapshot, audit=audit)
    original = deepcopy(payload)
    restored = restore_target_state(predictive_map, payload, snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == payload == original
    return restored


def donate_frontier(
    engine: ZoneModelEngine, components: PersistenceComponents,
) -> ZoneModelSnapshot:
    donor = components.snapshot
    assert donor.updated_at == engine.snapshot.updated_at
    return replace(
        engine.snapshot,
        traversal_tokens=donor.traversal_tokens,
        retained_traversal_tokens=donor.retained_traversal_tokens,
        current_token_ids=donor.current_token_ids,
        authorization_uses=donor.authorization_uses,
        anonymous_supports=donor.anonymous_supports,
        support_token_bindings=donor.support_token_bindings,
    )


def correlated_ready() -> tuple[PredictiveMap, ZoneModelEngine]:
    """Exact independently reproduced source recipe, with actual mmWave T."""
    predictive_map = graph({
        "a": ("b",), "b": ("a", "c"), "c": ("b", "z", "t"),
        "x": ("y",), "y": ("x", "z"), "z": ("y", "c", "e"),
        "e": ("z",), "t": ("c", "u"), "u": ("t",),
    }, presence=frozenset({"t"}))
    inputs = tuple(event(node, state, seconds) for node, state, seconds in (
        ("t", "on", -40), ("t", "off", -5),
        ("a", "on", 0), ("b", "on", 1), ("c", "on", 2),
        ("c", "unavailable", 3), ("x", "on", 4), ("y", "on", 5),
        ("z", "on", 6), ("c", "on", 36),
    ))
    payload = structural_payload(predictive_map, inputs, count=2)
    engine = restore_target_state(predictive_map, payload, at(36))
    roundtrip(predictive_map, engine)
    engine.observe(event("e", "on", 37))
    roundtrip(predictive_map, engine)
    return predictive_map, engine


def bootstrap_pair(
    predictive_map: PredictiveMap, nodes: tuple[str, ...],
    *, active_seed: Mapping[str, bool] | None = None,
) -> tuple[ZoneModelEngine, PersistenceComponents]:
    """Current startup selection plus genuinely observed legacy provenance."""
    engine = ZoneModelEngine(predictive_map, 1, at(0), active_seed=active_seed)
    donor = PersistenceComponents(predictive_map, 1, at(0))
    for seconds, node in enumerate(nodes):
        input_ = event(node, "on", seconds)
        engine.bootstrap_sensor_snapshot((input_,), at(seconds))
        donor.observe(input_)
    return engine, donor
