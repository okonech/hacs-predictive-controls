from __future__ import annotations

import math
from dataclasses import dataclass
from types import SimpleNamespace

from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap


@dataclass(frozen=True)
class ZonePublicSnapshot:
    activation_plausible: bool
    keep_on: bool
    prelight_plausible: bool


@dataclass(frozen=True)
class PublicSnapshot:
    event: OccupancyEvent
    zones: dict[str, ZonePublicSnapshot]


def public_snapshot(
    tracker: ZoneConfidenceEngine,
    predictive_map: PredictiveMap,
    event: OccupancyEvent,
) -> PublicSnapshot:
    runtime = SimpleNamespace(
        map=predictive_map,
        zone_states=tracker.states,
        expected_occupants=tracker.config.expected_occupants,
        confidence=tracker,
        last_occupancy_event=event,
    )
    summary = runtime_automation_summary(runtime)
    return PublicSnapshot(
        event=event,
        zones={
            zone: ZonePublicSnapshot(
                activation_plausible=state.activation_plausible,
                keep_on=state.keep_on,
                prelight_plausible=state.prelight_plausible,
            )
            for zone, state in summary.zones.items()
        },
    )


def run_trace(
    tracker: ZoneConfidenceEngine,
    predictive_map: PredictiveMap,
    events: tuple[OccupancyEvent, ...],
) -> tuple[PublicSnapshot, ...]:
    snapshots: list[PublicSnapshot] = []
    for occupancy_event in sorted(
        events,
        key=lambda item: (item.event_at, item.entity_id, item.state),
    ):
        tracker.observe(occupancy_event)
        snapshots.append(public_snapshot(tracker, predictive_map, occupancy_event))
    return tuple(snapshots)


def assert_zone_timeline(
    snapshots: tuple[PublicSnapshot, ...],
    zone: str,
    *,
    activation: tuple[bool, ...],
    keep_on: tuple[bool, ...],
    prelight: tuple[bool, ...],
) -> None:
    assert (
        tuple(snapshot.zones[zone].activation_plausible for snapshot in snapshots)
        == activation
    )
    assert tuple(snapshot.zones[zone].keep_on for snapshot in snapshots) == keep_on
    assert (
        tuple(snapshot.zones[zone].prelight_plausible for snapshot in snapshots)
        == prelight
    )


def assert_normalized(tracker: ZoneConfidenceEngine) -> None:
    hypotheses = tracker.diagnostics.joint_posterior
    assert math.isclose(
        math.fsum(math.exp(item.log_probability) for item in hypotheses),
        1.0,
        abs_tol=1e-12,
    )


def assert_count_conserved(
    tracker: ZoneConfidenceEngine,
    expected_occupants: int,
) -> None:
    hypotheses = tracker.diagnostics.joint_posterior
    assert all(
        len(hypothesis.key.positions) == expected_occupants for hypothesis in hypotheses
    )
