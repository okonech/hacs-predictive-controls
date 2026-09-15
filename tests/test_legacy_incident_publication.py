# Legacy qualification, not public incident acceptance (REQ-GOV-005, 2026-09-12).
# Source: tests/incidents/
# test_inc_2026_09_05_1910z_cadence_publication_reuses_snapshot.py
# Real runtime publication; selected evidence must match its committed producer.
# Old three-ID component scope is retained separately, never imposed on selection.

from __future__ import annotations

import asyncio
import importlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    SensorInput,
    TraversalAuthorization,
    ZoneModelSnapshot,
)
from tests.legacy_qualification_fixture import correlated_policy_probe
from tests.persistence_component_fixture import PersistenceComponents


def test_legacy_incident_publication_snapshot_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    benchmark = importlib.import_module("benchmarks.occupancy_performance")
    reference_map = load_predictive_map(
        (Path(__file__).parents[1] / "benchmarks/reference-map.yaml").read_text()
    )
    cadence_map = benchmark._benchmark_map(
        reference_map,
        entity_overrides={
            "guest_bedroom_sensor": {
                "mmwave": "binary_sensor.benchmark_guest_bedroom_presence"
            }
        },
    )
    assert cadence_map.zones().index("guest_bedroom") == 6

    (
        runtime_type,
        home_entity_type,
        problem_entity_type,
        active_entity_type,
        diagnostic_entity_type,
    ) = benchmark._runtime_publication_types()
    started_at = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)
    runtime = runtime_type(
        benchmark._BenchmarkHass(),
        cadence_map,
        (),
        transition_window=30,
        expected_occupants=2,
    )
    runtime.confidence.ensure_state(started_at)

    entity_ids = {
        node_id: next(iter(cadence_map.nodes[node_id].entities.values()))
        for node_id in (
            "guest_bedroom_sensor",
            "living_left_sensor",
            "stairs_bottom_sensor",
        )
    }

    def observe(node_id: str, state: str, milliseconds: int) -> None:
        event_at = started_at + timedelta(milliseconds=milliseconds)
        runtime.observe_entity(entity_ids[node_id], state, event_at)

    observe("living_left_sensor", "on", 0)
    observe("guest_bedroom_sensor", "on", 1)
    observe("guest_bedroom_sensor", "off", 20_000)
    runtime.confidence.ensure_state(started_at + timedelta(milliseconds=30_000))
    observe("stairs_bottom_sensor", "on", 40_000)

    target_entity = active_entity_type(runtime, "benchmark", "guest_bedroom")
    entities = [
        home_entity_type(runtime, "benchmark"),
        problem_entity_type(runtime, "benchmark"),
        *(
            target_entity
            if zone == "guest_bedroom"
            else active_entity_type(runtime, "benchmark", zone)
            for zone in cadence_map.zones()
        ),
        *(
            diagnostic_entity_type(runtime, "benchmark", zone)
            for zone in cadence_map.zones()
        ),
    ]
    for entity in entities:
        entity.hass = runtime.hass

    async def add_entities() -> None:
        for entity in entities:
            await entity.async_added_to_hass()

    asyncio.run(add_entities())

    snapshot_property = inspect.getattr_static(ZoneModelEngine, "snapshot")
    assert isinstance(snapshot_property, property)
    original_snapshot = snapshot_property.fget
    assert original_snapshot is not None
    snapshot_reads = 0

    def counted_snapshot(engine: ZoneModelEngine) -> ZoneModelSnapshot:
        nonlocal snapshot_reads
        snapshot_reads += 1
        return cast(ZoneModelSnapshot, original_snapshot(engine))

    monkeypatch.setattr(ZoneModelEngine, "snapshot", property(counted_snapshot))
    publication_started_at = 0
    original_publish_update = runtime._publish_update

    def measured_publish_update() -> None:
        nonlocal publication_started_at
        publication_started_at = snapshot_reads
        original_publish_update()

    runtime._publish_update = measured_publish_update
    reads_at_write: list[int] = []
    attributes_at_write: list[dict[str, Any]] = []
    decisions_at_write: list[PolicyDecision] = []
    authorizations_at_write: list[TraversalAuthorization] = []

    def record_write() -> None:
        reads_at_write.append(snapshot_reads - publication_started_at)
        attributes_at_write.append(target_entity.extra_state_attributes)
        decisions_at_write.append(next(
            decision for decision in runtime.confidence.policy_decisions
            if decision.zone == "guest_bedroom"
        ))
        authorizations_at_write.append(next(
            authorization for authorization in runtime.confidence.authorizations
            if authorization.target_node_id == "guest_bedroom_sensor"
        ))

    target_entity._benchmark_write_callback = record_write
    observe("guest_bedroom_sensor", "on", 45_000)

    cadence_state = next(
        state
        for state in runtime.confidence.episode_states
        if state.node_id == "guest_bedroom_sensor"
    )
    assert cadence_state.cadence_correlated
    assert any(
        item.target_node_id == "guest_bedroom_sensor" and item.authorized
        for item in runtime.confidence.authorizations
    )
    assert target_entity.is_on
    assert len(attributes_at_write) == 1
    assert attributes_at_write[0]["reason"] == "asserted_stay_hold"
    assert attributes_at_write[0]["phase"] == "active"
    assert attributes_at_write[0]["track_confidence"] == "confirmed"
    decision, = decisions_at_write
    authorization, = authorizations_at_write
    assert authorization.authorized and authorization.reason == "selected_path"
    assert authorization.target_episode_id == cadence_state.episode_id
    assert authorization.selected_source_episode_ids
    assert decision.evidence_ids == (
        cadence_state.episode_id, *authorization.selected_source_episode_ids,
    )
    assert attributes_at_write[0]["evidence_ids"] == list(decision.evidence_ids)
    assert reads_at_write == [1]


def test_legacy_publication_three_id_component_provenance() -> None:
    """Retain old metadata scope without imposing legacy IDs on real entities."""
    benchmark = importlib.import_module("benchmarks.occupancy_performance")
    reference_map = load_predictive_map(
        (Path(__file__).parents[1] / "benchmarks/reference-map.yaml").read_text()
    )
    predictive_map = benchmark._benchmark_map(reference_map, entity_overrides={
        "guest_bedroom_sensor": {
            "mmwave": "binary_sensor.benchmark_guest_bedroom_presence",
        },
    })
    origin = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)
    components = PersistenceComponents(predictive_map, 2, origin)
    for milliseconds, node, state in (
        (0, "living_left_sensor", "on"),
        (1, "guest_bedroom_sensor", "on"),
        (20_000, "guest_bedroom_sensor", "off"),
        (40_000, "stairs_bottom_sensor", "on"),
    ):
        if milliseconds == 40_000:
            components.advance(origin + timedelta(milliseconds=30_000))
        components.observe(SensorInput(
            next(iter(predictive_map.nodes[node].entities.values())), state,
            origin + timedelta(milliseconds=milliseconds),
        ))
    result = correlated_policy_probe(components, SensorInput(
        "binary_sensor.benchmark_guest_bedroom_presence", "on",
        origin + timedelta(milliseconds=45_000),
    ))
    decision, = (d for d in result.policy_decisions if d.zone == "guest_bedroom")
    authorization, = result.authorizations
    assert authorization.reason == "adjacent_authorized"
    assert decision.evidence_ids == (
        "guest_bedroom_sensor:2:2026-07-18T13:00:45+00:00",
        "guest_bedroom_sensor:1:2026-07-18T13:00:00.001000+00:00",
        "stairs_bottom_sensor:1:2026-07-18T13:00:40+00:00",
    )
    assert decision.evidence_ids == (
        authorization.target_episode_id,
        *(token.episode_id for token in authorization.source_tokens),
    )
    assert len(authorization.source_tokens) == 2
