"""Authoritative count validation without room assignment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ..const import PRODUCT_MAX_OCCUPANTS
from .filter import ZoneBeliefFilter
from .profiles import ENTRY_BOUNDARY
from .traversal import TraversalFrontier
from .types import CountDiagnostics, CountInput, CountState, CountUpdate

DIAGNOSTIC_LIMIT = 2**31 - 1
SEEN_EVENT_LIMIT = 32


class CountContext:
    """Retain the last valid authoritative count and transition frontier."""

    def __init__(self, initial_count: int) -> None:
        if not isinstance(initial_count, int) or isinstance(initial_count, bool):
            raise ValueError("Initial count must be an integer")
        if not 0 <= initial_count <= PRODUCT_MAX_OCCUPANTS:
            raise ValueError("Initial count is outside the supported range")
        self._state = CountState(initial_count)

    @property
    def state(self) -> CountState:
        return self._state

    @classmethod
    def restore(cls, state: CountState) -> CountContext:
        context = cls(state.expected_count)
        context._state = state
        return context

    def observe(self, event: CountInput) -> CountUpdate:
        if event.event_id in self._state.seen_event_ids:
            return self._diagnose("duplicate", 1)
        if not event.available:
            return self._diagnose("unavailable", 4, event.event_id)
        if (
            self._state.last_event_at is not None
            and event.event_at <= self._state.last_event_at
        ):
            return self._diagnose("stale", 2, event.event_id)
        if (
            not isinstance(event.value, int)
            or isinstance(event.value, bool)
            or not 0 <= event.value <= PRODUCT_MAX_OCCUPANTS
        ):
            return self._diagnose("invalid", 3, event.event_id)
        if event.value == self._state.expected_count:
            return self._diagnose("duplicate", 1, event.event_id)

        transition_at = None
        transition_until = None
        if self._state.expected_count == 0 and event.value > 0:
            transition_at = event.event_at
            transition_until = event.event_at + ENTRY_BOUNDARY.traversal_context_window
        self._state = replace(
            self._state,
            expected_count=event.value,
            last_event_at=event.event_at,
            last_event_id=event.event_id,
            positive_transition_at=transition_at,
            positive_transition_until=transition_until,
            seen_event_ids=self._append_seen(event.event_id),
            diagnostics=self._increment(self._state.diagnostics, 0),
        )
        return CountUpdate("accepted", self._state, event.value == 0)

    def diagnostics(self, evidence_cluster_count: int) -> CountDiagnostics:
        if evidence_cluster_count < 0:
            raise ValueError("Evidence cluster count must be non-negative")
        return CountDiagnostics(
            self._state.expected_count,
            evidence_cluster_count,
            evidence_cluster_count - self._state.expected_count,
        )

    def _diagnose(
        self,
        disposition: str,
        index: int,
        event_id: str | None = None,
    ) -> CountUpdate:
        self._state = replace(
            self._state,
            seen_event_ids=(
                self._state.seen_event_ids
                if event_id is None
                else self._append_seen(event_id)
            ),
            diagnostics=self._increment(self._state.diagnostics, index),
        )
        return CountUpdate(disposition, self._state)

    def _append_seen(self, event_id: str) -> tuple[str, ...]:
        return (*self._state.seen_event_ids, event_id)[-SEEN_EVENT_LIMIT:]

    @staticmethod
    def _increment(
        values: tuple[int, ...], index: int
    ) -> tuple[int, int, int, int, int]:
        updated = list(values)
        updated[index] = min(DIAGNOSTIC_LIMIT, updated[index] + 1)
        return (updated[0], updated[1], updated[2], updated[3], updated[4])


def apply_count_update(
    update: CountUpdate,
    filters: Mapping[str, ZoneBeliefFilter],
    frontier: TraversalFrontier,
) -> None:
    if update.disposition != "accepted" or not update.categorical_zero:
        return
    assert update.state.last_event_at is not None
    at = update.state.last_event_at
    frontier.validate_time(at)
    for filter_ in filters.values():
        if at < filter_.state.last_updated_at:
            raise ValueError("Count-zero frontier predates a zone belief")
    for filter_ in filters.values():
        filter_.apply_empty_baseline(at)
    frontier.clear(at)


__all__ = [
    "CountContext",
    "CountDiagnostics",
    "CountInput",
    "CountState",
    "CountUpdate",
    "apply_count_update",
]
