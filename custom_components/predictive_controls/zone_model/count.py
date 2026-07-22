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
    CountUpdate,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    StrongTrackedFront,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    require_utc,
)

DIAGNOSTIC_LIMIT = 2**31 - 1
SEEN_EVENT_LIMIT = 32


class CountConflictTracker:
    """Build strong fronts and time bounded stuck-assertion contradictions."""

    def __init__(
        self,
        adjacency: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        connected: dict[str, set[str]] = {}
        for node_id, neighbors in (
            {} if adjacency is None else adjacency
        ).items():
            for neighbor in neighbors:
                connected.setdefault(node_id, set()).add(neighbor)
                connected.setdefault(neighbor, set()).add(node_id)
        self._adjacency = {
            node_id: frozenset(neighbors)
            for node_id, neighbors in connected.items()
        }
        self._fronts: tuple[StrongTrackedFront, ...] = ()
        self._conflicts: dict[str, CountConflictState] = {}
        self._last_count: int | None = None

    @property
    def fronts(self) -> tuple[StrongTrackedFront, ...]:
        return self._fronts

    @property
    def conflicts(self) -> tuple[CountConflictState, ...]:
        return tuple(self._conflicts[node_id] for node_id in sorted(self._conflicts))

    def restore(
        self,
        fronts: tuple[StrongTrackedFront, ...],
        conflicts: tuple[CountConflictState, ...],
        expected_count: int,
    ) -> None:
        if len({front.front_id for front in fronts}) != len(fronts):
            raise ValueError("Strong-front restore IDs must be unique")
        restored = {conflict.target_node_id: conflict for conflict in conflicts}
        if len(restored) != len(conflicts):
            raise ValueError("Count-conflict restore targets must be unique")
        self._fronts = tuple(sorted(fronts, key=lambda front: front.front_id))
        self._conflicts = restored
        self._last_count = expected_count

    def clear(self) -> None:
        self._fronts = ()
        self._conflicts.clear()
        self._last_count = 0

    def evaluate(
        self,
        at: datetime,
        count: int,
        nodes: tuple[PhysicalNode, ...],
        episode_states: tuple[EpisodeState, ...],
        belief_states: tuple[ZoneBeliefState, ...],
        tokens: tuple[TraversalToken, ...],
        release_dwells: Mapping[str, timedelta],
        *,
        local_effect: EpisodeEffect | None = None,
        authorization: TraversalAuthorization | None = None,
    ) -> tuple[CountConflictState, ...]:
        """Return conflicts that newly crossed their health-degrade deadline."""

        require_utc(at, "Count-conflict evaluation time")
        if count <= 0:
            self.clear()
            return ()
        count_changed = self._last_count is not None and self._last_count != count
        self._last_count = count
        state_by_node = {state.node_id: state for state in episode_states}
        belief_by_zone = {belief.zone: belief for belief in belief_states}
        self._fronts = self._stabilize_front_ids(
            self._fronts,
            self._build_fronts(at, state_by_node, belief_by_zone, tokens),
        )
        if count_changed:
            self._conflicts = {
                node_id: conflict
                for node_id, conflict in self._conflicts.items()
                if conflict.degraded_at is not None
            }
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
            ):
                eligible_nodes.add(target.node_id)
                self._conflicts[target.node_id] = replace(
                    existing, last_evaluated_at=at
                )
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
            if existing is not None and existing.degraded_at is not None:
                if existing.target_episode_id == target.episode_id:
                    eligible_nodes.add(target.node_id)
                    self._conflicts[target.node_id] = replace(
                        existing, last_evaluated_at=at
                    )
                continue
            if any(
                target.node_id in front.node_ids or target.zone in front.zones
                for front in self._fronts
            ):
                self._conflicts.pop(target.node_id, None)
                continue
            outside = tuple(
                front
                for front in self._fronts
                if target.zone not in front.zones
                and target.node_id not in front.node_ids
            )
            if len(outside) < count:
                self._conflicts.pop(target.node_id, None)
                continue
            eligible_nodes.add(target.node_id)
            front_ids = tuple(front.front_id for front in outside[:count])
            dwell = release_dwells[target.zone]
            if (
                existing is None
                or existing.target_episode_id != target.episode_id
                or existing.strong_front_ids != front_ids
            ):
                self._conflicts[target.node_id] = CountConflictState(
                    target.node_id,
                    target.zone,
                    target.episode_id,
                    at,
                    at,
                    at + dwell,
                    front_ids,
                )
                continue
            updated = replace(existing, last_evaluated_at=at)
            if at >= existing.deadline:
                updated = replace(updated, degraded_at=at)
                newly_degraded.append(updated)
            self._conflicts[target.node_id] = updated

        self._conflicts = {
            node_id: conflict
            for node_id, conflict in self._conflicts.items()
            if node_id in eligible_nodes
        }
        return tuple(newly_degraded)

    def _build_fronts(
        self,
        at: datetime,
        state_by_node: Mapping[str, EpisodeState],
        belief_by_zone: Mapping[str, ZoneBeliefState],
        tokens: Sequence[TraversalToken],
    ) -> tuple[StrongTrackedFront, ...]:
        candidates: list[TraversalToken] = []
        for token in tokens:
            state = state_by_node.get(token.node_id)
            belief = belief_by_zone.get(token.zone)
            confirmed = bool(
                (
                    token.track_confidence == "confirmed"
                    and token.provenance_kind == "adjacent"
                    and len(set(token.path_node_ids)) >= 3
                )
                or token.equivalent_confirmed_strength
            )
            if (
                not confirmed
                or token.valid_until <= at
                or state is None
                or state.episode_id != token.episode_id
                or SHARED_PROFILES[state.profile_name].role != "stay"
                or state.status not in {"asserted", "clearing", "clear"}
                or state.health_warning
                or state.cadence_warning
                or belief is None
                or belief.probability < 0.7
            ):
                continue
            candidates.append(token)
        groups: list[list[TraversalToken]] = []
        for token in sorted(candidates, key=lambda item: item.token_id):
            token_nodes = set(token.path_node_ids)
            overlaps = [
                index
                for index, group in enumerate(groups)
                if self._connected_node_sets(
                    token_nodes,
                    {
                        node_id
                        for item in group
                        for node_id in item.path_node_ids
                    },
                )
            ]
            if not overlaps:
                groups.append([token])
                continue
            first = overlaps[0]
            groups[first].append(token)
            for index in reversed(overlaps[1:]):
                groups[first].extend(groups.pop(index))
        fronts: list[StrongTrackedFront] = []
        for group in groups:
            token_ids = tuple(sorted(token.token_id for token in group))
            node_ids = tuple(
                sorted({node_id for token in group for node_id in token.path_node_ids})
            )
            zones = tuple(
                sorted(
                    {
                        state_by_node[node_id].zone
                        for node_id in node_ids
                        if node_id in state_by_node
                    }
                )
            )
            episode_ids = tuple(sorted(token.episode_id for token in group))
            fronts.append(
                StrongTrackedFront(
                    "|".join(token_ids),
                    token_ids,
                    node_ids,
                    zones,
                    episode_ids,
                    max(token.valid_until for token in group),
                )
            )
        return tuple(sorted(fronts, key=lambda front: front.front_id))

    def _connected_node_sets(self, left: set[str], right: set[str]) -> bool:
        if left & right:
            return True
        return any(
            self._adjacency.get(node_id, frozenset()) & right for node_id in left
        )

    def _stabilize_front_ids(
        self,
        previous: tuple[StrongTrackedFront, ...],
        current: tuple[StrongTrackedFront, ...],
    ) -> tuple[StrongTrackedFront, ...]:
        """Carry a front identity across connected token membership changes."""

        if not previous or not current:
            return current
        candidates: list[tuple[tuple[int, int, int, int], int, int]] = []
        for current_index, new in enumerate(current):
            new_nodes = set(new.node_ids)
            for previous_index, old in enumerate(previous):
                if not self._connected_node_sets(new_nodes, set(old.node_ids)):
                    continue
                score = (
                    len(set(new.token_ids) & set(old.token_ids)),
                    len(set(new.episode_ids) & set(old.episode_ids)),
                    len(new_nodes & set(old.node_ids)),
                    -previous_index,
                )
                candidates.append((score, current_index, previous_index))
        assigned_current: dict[int, str] = {}
        used_previous: set[int] = set()
        for _score, current_index, previous_index in sorted(
            candidates,
            key=lambda item: (item[0], -item[1]),
            reverse=True,
        ):
            if current_index in assigned_current or previous_index in used_previous:
                continue
            assigned_current[current_index] = previous[previous_index].front_id
            used_previous.add(previous_index)

        used_ids = set(assigned_current.values())
        stabilized: list[StrongTrackedFront] = []
        for index, front in enumerate(current):
            front_id = assigned_current.get(index, front.front_id)
            if front_id in used_ids and index not in assigned_current:
                suffix = 2
                while f"{front_id}#{suffix}" in used_ids:
                    suffix += 1
                front_id = f"{front_id}#{suffix}"
            used_ids.add(front_id)
            stabilized.append(replace(front, front_id=front_id))
        return tuple(sorted(stabilized, key=lambda front: front.front_id))


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
