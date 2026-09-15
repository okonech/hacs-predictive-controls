"""User-reported issue: original quote unavailable; retained benchmark regression.
User expected: target ON with one publication at the cadence input (inferred).
Observed: original qualification reports redundant snapshot reads during publication;
no physical missed-light report or original capture is available in this source.
Source: frozen September 5 test, using its synthetic July 18 benchmark timeline.
Test scope: actual public target ON and exactly one input-phase write at 45s.
Legacy disposition: full subscriber/snapshot-read and metadata qualification remains
in tests/test_legacy_incident_publication.py; relocation does not fix its failures.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import RuntimeScenario


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_09_05_1910z_cadence_publication_reuses_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    benchmark = importlib.import_module("benchmarks.occupancy_performance")
    reference_map = load_predictive_map(
        (Path(__file__).parents[2] / "benchmarks/reference-map.yaml").read_text()
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

    started_at = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)
    entity_ids = {
        node_id: next(iter(cadence_map.nodes[node_id].entities.values()))
        for node_id in (
            "guest_bedroom_sensor",
            "living_left_sensor",
            "stairs_bottom_sensor",
        )
    }

    inputs = [
        # Original observe_entity used map-native reliability, not default 1.0.
        SensorInput(
            entity_ids[node_id], state,
            started_at + timedelta(milliseconds=milliseconds),
            cadence_map.nodes[node_id].reliability,
        )
        for node_id, state, milliseconds in (
            ("living_left_sensor", "on", 0),
            ("guest_bedroom_sensor", "on", 1),
            ("guest_bedroom_sensor", "off", 20_000),
            ("stairs_bottom_sensor", "on", 40_000),
            ("guest_bedroom_sensor", "on", 45_000),
        )
    ]
    target_at = started_at + timedelta(milliseconds=45_000)
    with RuntimeScenario(started_at) as scenario:
        replay = scenario.create(cadence_map, 2)
        for event in inputs[:3]:
            replay.observe(event)
        replay.advance(started_at + timedelta(milliseconds=30_000))
        replay.observe(inputs[3])
        before_target = replay.advance(target_at)
        prior_edges = replay.edges_for("guest_bedroom")
        arrival = replay.observe(inputs[4])

        assert replay.normalized_inputs == inputs
        assert arrival.active("guest_bedroom")
        target_writes = [
            write for write in replay.writes_for("guest_bedroom")
            if write.at == target_at and write.phase == "input"
        ]
        assert len(target_writes) == 1, replay.writes_for("guest_bedroom")
        assert target_writes[0].active
        # The original oracle requires a write/ON, not a new acquisition if
        # already ON. Every new edge at this input must still be input-phase ON.
        target_edges = replay.edges_for("guest_bedroom")[len(prior_edges):]
        assert all(
            edge.at == target_at and edge.active
            and edge in replay.input_edges_for("guest_bedroom")
            for edge in target_edges
        )
        assert len(target_edges) == (0 if before_target.active("guest_bedroom") else 1)
