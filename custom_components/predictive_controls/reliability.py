from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .occupancy_state import PolicyAuditEntry

RELIABILITY_FLAP_WINDOW = timedelta(seconds=30)
RELIABILITY_REPEAT_MINIMUM = 2


@dataclass(frozen=True, slots=True)
class RejectedMotionCaptureSummary:
    """Repeated positive observations that did not establish ownership."""

    entity_id: str
    zone: str
    capture_count: int
    last_capture_at: datetime
    reason_counts: tuple[tuple[str, int], ...]
    max_occupied_marginal: float | None


@dataclass(frozen=True, slots=True)
class LowConfidenceFlapSummary:
    """Repeated short pulses whose positive edges failed the occupied gate."""

    entity_id: str
    zone: str
    pulse_count: int
    last_flap_at: datetime
    shortest_pulse_seconds: float
    max_occupied_marginal: float | None


@dataclass(frozen=True, slots=True)
class PolicyReliabilitySummary:
    """Bounded reliability review derived from retained policy decisions."""

    observed_event_count: int
    oldest_event_at: datetime | None
    newest_event_at: datetime | None
    rejected_motion_captures: tuple[RejectedMotionCaptureSummary, ...]
    low_confidence_flaps: tuple[LowConfidenceFlapSummary, ...]


@dataclass(frozen=True, slots=True)
class _ObservedEvent:
    event_id: str
    entity_id: str
    zone: str
    state: str
    decision_at: datetime
    entry: PolicyAuditEntry


def summarize_policy_reliability(
    audit: tuple[PolicyAuditEntry, ...],
) -> PolicyReliabilitySummary:
    """Summarize repeated rejected captures without expanding audit contexts."""

    events = _observed_events(audit)
    rejected_by_source: dict[tuple[str, str], list[_ObservedEvent]] = defaultdict(
        list
    )
    for event in events:
        if _is_rejected_motion_capture(event):
            rejected_by_source[(event.entity_id, event.zone)].append(event)

    rejected = tuple(
        sorted(
            (
                _rejected_capture_summary(key, captures)
                for key, captures in rejected_by_source.items()
                if len(captures) >= RELIABILITY_REPEAT_MINIMUM
            ),
            key=lambda item: (-item.capture_count, item.entity_id, item.zone),
        )
    )
    flaps = _low_confidence_flaps(events)
    return PolicyReliabilitySummary(
        observed_event_count=len(events),
        oldest_event_at=None if not events else events[0].decision_at,
        newest_event_at=None if not events else events[-1].decision_at,
        rejected_motion_captures=rejected,
        low_confidence_flaps=flaps,
    )


def _observed_events(
    audit: tuple[PolicyAuditEntry, ...],
) -> tuple[_ObservedEvent, ...]:
    selected: dict[tuple[str, str, datetime, str], _ObservedEvent] = {}
    for entry in audit:
        entity_id = entry.trigger_entity_id
        zone = entry.trigger_zone
        state = entry.trigger_state
        if (
            not entry.trigger_event_id
            or entity_id is None
            or zone is None
            or state is None
            or entry.decision.zone != zone
            or entry.decision.action not in {"activate", "observe"}
        ):
            continue
        key = (entry.trigger_event_id, entity_id, entry.decision_at, state)
        event = _ObservedEvent(
            entry.trigger_event_id,
            entity_id,
            zone,
            state,
            entry.decision_at,
            entry,
        )
        existing = selected.get(key)
        if existing is None or entry.decision.action == "activate":
            selected[key] = event
    return tuple(
        sorted(
            selected.values(),
            key=lambda event: (
                event.decision_at,
                event.entity_id,
                event.event_id,
            ),
        )
    )


def _is_rejected_motion_capture(event: _ObservedEvent) -> bool:
    entry = event.entry
    return (
        event.state == "on"
        and not entry.decision.accepted
        and not entry.previous_keep_on
        and not entry.current_keep_on
    )


def _rejected_capture_summary(
    key: tuple[str, str],
    captures: list[_ObservedEvent],
) -> RejectedMotionCaptureSummary:
    reason_counts = Counter(
        capture.entry.decision.reason_code for capture in captures
    )
    return RejectedMotionCaptureSummary(
        entity_id=key[0],
        zone=key[1],
        capture_count=len(captures),
        last_capture_at=max(capture.decision_at for capture in captures),
        reason_counts=tuple(sorted(reason_counts.items())),
        max_occupied_marginal=_maximum_occupied_marginal(captures),
    )


def _low_confidence_flaps(
    events: tuple[_ObservedEvent, ...],
) -> tuple[LowConfidenceFlapSummary, ...]:
    events_by_source: dict[tuple[str, str], list[_ObservedEvent]] = defaultdict(
        list
    )
    for event in events:
        events_by_source[(event.entity_id, event.zone)].append(event)

    summaries: list[LowConfidenceFlapSummary] = []
    for key, source_events in events_by_source.items():
        pending_on: _ObservedEvent | None = None
        pulses: list[tuple[_ObservedEvent, _ObservedEvent, float]] = []
        for event in source_events:
            if event.state == "on":
                if _is_low_confidence_positive(event):
                    pending_on = event
                elif event.entry.decision.action == "activate":
                    pending_on = None
                continue
            if event.state == "off" and pending_on is not None:
                duration = (event.decision_at - pending_on.decision_at).total_seconds()
                if 0.0 <= duration <= RELIABILITY_FLAP_WINDOW.total_seconds():
                    pulses.append((pending_on, event, duration))
                pending_on = None
        if len(pulses) < RELIABILITY_REPEAT_MINIMUM:
            continue
        summaries.append(
            LowConfidenceFlapSummary(
                entity_id=key[0],
                zone=key[1],
                pulse_count=len(pulses),
                last_flap_at=max(off.decision_at for _, off, _ in pulses),
                shortest_pulse_seconds=min(duration for _, _, duration in pulses),
                max_occupied_marginal=_maximum_occupied_marginal(
                    [on for on, _, _ in pulses]
                ),
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (-item.pulse_count, item.entity_id, item.zone),
        )
    )


def _is_low_confidence_positive(event: _ObservedEvent) -> bool:
    return (
        _is_rejected_motion_capture(event)
        and event.entry.decision.action == "activate"
        and event.entry.decision.reason_code == "occupied_gate_failed"
    )


def _maximum_occupied_marginal(
    events: list[_ObservedEvent],
) -> float | None:
    values: list[float] = []
    for event in events:
        value = event.entry.decision.gate_values.get("occupied_marginal")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            values.append(float(value))
    return max(values, default=None)
