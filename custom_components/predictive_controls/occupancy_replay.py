from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .events import OccupancyEvent, event_from_entity
from .model import PredictiveMap
from .occupancy_tracker import (
    OccupancyTracker,
    TrackerDiagnostics,
    ZoneState,
    ZoneUpdate,
)


@dataclass(frozen=True)
class ReplayStep:
    """One replayed event and the tracker state after applying it."""

    event: OccupancyEvent
    update: ZoneUpdate
    zone_states: dict[str, ZoneState]
    diagnostics: TrackerDiagnostics


@dataclass(frozen=True)
class ReplayResult:
    """Result of replaying a trace through an occupancy tracker."""

    steps: tuple[ReplayStep, ...]
    final_states: dict[str, ZoneState]
    final_diagnostics: TrackerDiagnostics


def replay_events(
    tracker: OccupancyTracker,
    events: Iterable[OccupancyEvent],
    *,
    refresh_before_events: bool = True,
) -> ReplayResult:
    steps: list[ReplayStep] = []
    for event in sorted(
        events,
        key=lambda item: (
            item.event_at,
            item.entity_id,
            item.node_id,
            item.signal_type,
            item.state,
        ),
    ):
        if refresh_before_events:
            tracker.refresh_active(event.event_at)
        update = tracker.observe(event)
        steps.append(
            ReplayStep(
                event=event,
                update=update,
                zone_states=tracker.states,
                diagnostics=tracker.diagnostics,
            )
        )
    return ReplayResult(
        steps=tuple(steps),
        final_states=tracker.states,
        final_diagnostics=tracker.diagnostics,
    )


def replay_history_states(
    predictive_map: PredictiveMap,
    tracker: OccupancyTracker,
    history_payload: Sequence[Any],
    *,
    refresh_before_events: bool = True,
) -> ReplayResult:
    """Import Home Assistant history rows and replay them through a tracker."""

    return replay_events(
        tracker,
        history_events_from_states(predictive_map, history_payload),
        refresh_before_events=refresh_before_events,
    )


def replay_summary(result: ReplayResult) -> dict[str, Any]:
    """Return a compact, serializable replay summary for tuning workflows."""

    return {
        "event_count": len(result.steps),
        "final_zones": {
            zone: {
                "confidence": state.confidence,
                "status": state.status,
                "reason": state.reason,
            }
            for zone, state in sorted(result.final_states.items())
            if state.confidence > 0
        },
        "active_zones": [
            zone
            for zone, state in sorted(result.final_diagnostics.policy_states.items())
            if state.active
        ],
        "traversal_token_count": len(result.final_diagnostics.traversal_tokens),
        "health_warning_count": sum(
            state.health_warning for state in result.final_diagnostics.episode_states
        ),
    }


def history_events_from_states(
    predictive_map: PredictiveMap,
    history_payload: Sequence[Any],
) -> tuple[OccupancyEvent, ...]:
    """Convert Home Assistant history response rows into occupancy events."""

    events: list[OccupancyEvent] = []
    for row in _flatten_history_rows(history_payload):
        entity_id = row.get("entity_id")
        state = row.get("state")
        changed_at = row.get("last_changed") or row.get("last_updated")
        if not isinstance(entity_id, str) or not isinstance(state, str):
            continue
        if not isinstance(changed_at, str):
            continue
        event_at = _parse_datetime(changed_at)
        event = event_from_entity(predictive_map, entity_id, state, event_at)
        if event is not None:
            events.append(event)
    return tuple(
        sorted(
            events,
            key=lambda item: (
                item.event_at,
                item.entity_id,
                item.node_id,
                item.signal_type,
                item.state,
            ),
        )
    )


def _flatten_history_rows(
    history_payload: Sequence[Any],
) -> Iterable[Mapping[str, Any]]:
    for item in history_payload:
        if isinstance(item, Mapping):
            yield item
        elif isinstance(item, Sequence) and not isinstance(item, str | bytes):
            yield from _flatten_history_rows(item)


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
