"""Authoritative count validation without room assignment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from ..const import PRODUCT_MAX_OCCUPANTS
from .filter import ZoneBeliefFilter
from .profiles import ENTRY_BOUNDARY, SHARED_PROFILES
from .traversal import TraversalFrontier
from .types import (
    CountConflictState,
    CountDiagnostics,
    CountInput,
    CountState,
    CountSupport,
    CountUpdate,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    TraversalAuthorization,
    require_utc,
)

DIAGNOSTIC_LIMIT = 2**31 - 1
SEEN_EVENT_LIMIT = 32


class CountConflictTracker:
    """Time bounded stuck-assertion contradictions from anonymous supports."""

    def __init__(self) -> None:
        self._supports: tuple[CountSupport, ...] = ()
        self._conflicts: dict[str, CountConflictState] = {}
        self._last_count: int | None = None
        self._counters = {
            "count_conflict_started": 0,
            "count_conflict_canceled": 0,
            "count_conflict_degraded": 0,
        }

    @property
    def conflicts(self) -> tuple[CountConflictState, ...]:
        return tuple(self._conflicts[node_id] for node_id in sorted(self._conflicts))

    @property
    def counters(self) -> dict[str, int]:
        return dict(self._counters)

    def restore(
        self,
        conflicts: tuple[CountConflictState, ...],
        expected_count: int,
    ) -> None:
        restored = {conflict.target_node_id: conflict for conflict in conflicts}
        if len(restored) != len(conflicts):
            raise ValueError("Count-conflict restore targets must be unique")
        self._supports = ()
        self._conflicts = restored
        self._last_count = expected_count
        self._counters = dict.fromkeys(self._counters, 0)

    def clear(self) -> None:
        previous = dict(self._conflicts)
        self._supports = ()
        self._conflicts.clear()
        self._last_count = 0
        self._record_counter_changes(previous)

    def evaluate(
        self,
        at: datetime,
        count: int,
        nodes: tuple[PhysicalNode, ...],
        episode_states: tuple[EpisodeState, ...],
        supports: Sequence[CountSupport],
        release_dwells: Mapping[str, timedelta],
        *,
        local_effect: EpisodeEffect | None = None,
        authorization: TraversalAuthorization | None = None,
    ) -> tuple[CountConflictState, ...]:
        """Return conflicts that newly crossed their health-degrade deadline."""

        require_utc(at, "Count-conflict evaluation time")
        previous = dict(self._conflicts)
        if count <= 0:
            self.clear()
            return ()
        support_ids = tuple(support.support_id for support in supports)
        if support_ids != tuple(sorted(set(support_ids))):
            raise ValueError("Count supports must be unique and sorted")
        self._supports = tuple(supports)
        count_changed = self._last_count is not None and self._last_count != count
        self._last_count = count
        if count_changed:
            self._conflicts = {
                node_id: conflict
                for node_id, conflict in self._conflicts.items()
                if conflict.degraded_at is not None
            }
            self._record_counter_changes(previous)
            return ()

        physical_by_node = {node.node_id: node for node in nodes}
        eligible_nodes: set[str] = set()
        newly_degraded: list[CountConflictState] = []
        for target in episode_states:
            physical = physical_by_node[target.node_id]
            profile = SHARED_PROFILES[physical.profile_name]
            existing = self._conflicts.get(target.node_id)
            if (
                existing is not None
                and existing.degraded_at is not None
                and existing.target_episode_id == target.episode_id
                and target.degradation_reason == "count_conflict"
                and target.status != "degraded"
            ):
                eligible_nodes.add(target.node_id)
                self._conflicts[target.node_id] = replace(
                    existing,
                    last_evaluated_at=at,
                )
                continue
            if (
                existing is not None
                and existing.degraded_at is not None
                and existing.target_episode_id != target.episode_id
            ):
                self._conflicts.pop(target.node_id, None)
                continue
            if (
                profile.role != "stay"
                or target.status not in {"asserted", "degraded"}
                or target.episode_id is None
            ):
                continue
            compatible_update = bool(
                (
                    local_effect is not None
                    and local_effect.node_id == target.node_id
                    and local_effect.episode_id == target.episode_id
                    and local_effect.kind in {"positive", "health_recovered"}
                )
                or (
                    authorization is not None
                    and authorization.authorized
                    and authorization.target_node_id == target.node_id
                    and authorization.target_episode_id == target.episode_id
                )
            )
            if compatible_update:
                self._conflicts.pop(target.node_id, None)
                continue
            if any(self._contains_target(support, target) for support in supports):
                self._conflicts.pop(target.node_id, None)
                continue
            outside = tuple(
                support
                for support in supports
                if not self._contains_target(support, target)
            )
            if len(outside) < count:
                self._conflicts.pop(target.node_id, None)
                continue
            eligible_nodes.add(target.node_id)
            selected_ids = tuple(support.support_id for support in outside[:count])
            dwell = release_dwells[target.zone]
            if (
                existing is not None
                and existing.degraded_at is not None
                and existing.target_episode_id == target.episode_id
                and existing.support_ids == selected_ids
                and target.degradation_reason == "count_conflict"
            ):
                self._conflicts[target.node_id] = replace(
                    existing,
                    last_evaluated_at=at,
                )
                continue
            if (
                existing is None
                or existing.target_episode_id != target.episode_id
                or existing.support_ids != selected_ids
                or existing.degraded_at is not None
            ):
                self._conflicts[target.node_id] = CountConflictState(
                    target.node_id,
                    target.zone,
                    target.episode_id,
                    at,
                    at,
                    at + dwell,
                    selected_ids,
                )
                continue
            if at >= existing.deadline:
                updated = replace(
                    existing,
                    last_evaluated_at=at,
                    degraded_at=at,
                )
                newly_degraded.append(updated)
            else:
                updated = replace(existing, last_evaluated_at=at)
            self._conflicts[target.node_id] = updated

        self._conflicts = {
            node_id: conflict
            for node_id, conflict in self._conflicts.items()
            if node_id in eligible_nodes
        }
        self._record_counter_changes(previous)
        return tuple(newly_degraded)

    def _record_counter_changes(
        self,
        previous: Mapping[str, CountConflictState],
    ) -> None:
        def identity(conflict: CountConflictState) -> tuple[object, ...]:
            return (
                conflict.target_episode_id,
                conflict.started_at,
                conflict.support_ids,
            )

        started = sum(
            target not in previous
            or identity(previous[target]) != identity(conflict)
            for target, conflict in self._conflicts.items()
        )
        canceled = sum(
            conflict.degraded_at is None
            and (
                target not in self._conflicts
                or identity(self._conflicts[target]) != identity(conflict)
            )
            for target, conflict in previous.items()
        )
        degraded = sum(
            conflict.degraded_at is not None
            and target in previous
            and previous[target].degraded_at is None
            and identity(previous[target]) == identity(conflict)
            for target, conflict in self._conflicts.items()
        )
        for name, amount in (
            ("count_conflict_started", started),
            ("count_conflict_canceled", canceled),
            ("count_conflict_degraded", degraded),
        ):
            self._counters[name] = min(
                DIAGNOSTIC_LIMIT,
                self._counters[name] + amount,
            )

    def support_ids_outside(self, zone: str, node_id: str) -> tuple[str, ...]:
        return tuple(
            support.support_id
            for support in self._supports
            if support.endpoint_zone != zone and node_id not in support.path_node_ids
        )

    @staticmethod
    def _contains_target(support: CountSupport, target: EpisodeState) -> bool:
        return bool(
            support.endpoint_zone == target.zone
            or target.node_id in support.path_node_ids
        )


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
        bounded = (*self._state.seen_event_ids, event_id)[-SEEN_EVENT_LIMIT:]
        accepted_id = self._state.last_event_id
        if accepted_id is None or accepted_id in bounded:
            return bounded
        return (accepted_id, *bounded[-(SEEN_EVENT_LIMIT - 1) :])

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
    "CountConflictTracker",
    "CountContext",
    "CountDiagnostics",
    "CountInput",
    "CountState",
    "CountUpdate",
    "apply_count_update",
]
