"""Bounded, diagnostic-only physical health (REQ-HEALTH-001..003).

Only ``observe`` reads raw aliases. ``advance`` uses the stored aggregate and
never invents an edge. Coverage changes take effect at the supplied frontier,
after deadlines due there; they are never projected into the preceding interval.
An in-session restore retains unfinished runs. A subsequent bootstrap observation
explicitly breaks continuity across a restart gap, without completing a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import cast

from .types import EpisodeState, PhysicalNode, ReliabilityWarningOccurrence

UNSUPPORTED_ON_WINDOW = timedelta(seconds=600)
QUICK_CYCLE_WINDOW = timedelta(seconds=3600)
QUICK_CYCLE_MAX_ON = timedelta(seconds=60)
QUICK_CYCLE_COUNT = 6
_REASONS = {
    "assertion_timeout": "suspected_stuck", "sustained_flapping": "flapping",
    "unsupported_jump": "unsupported_jump",
}


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Path health time must be an aware UTC datetime")
    offset = value.utcoffset()
    if offset is None or offset != timedelta(0):
        raise ValueError("Path health time must be UTC")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Path health identity must be a nonempty string")
    return value


@dataclass(frozen=True)
class PathHealthState:
    """One physical aggregate, two independent counters, no inference flags.

    ``on_started_at=None`` with phase ON means its physical start is unknown
    (bootstrap); known observed duration can still begin an unsupported run.
    ``completed_cycles`` contains only the latest six quick OFF frontiers.
    """

    node_id: str
    zone: str
    phase: str = "unknown"
    on_started_at: datetime | None = None
    unsupported_started_at: datetime | None = None
    completed_cycles: tuple[datetime, ...] = ()

    def __post_init__(self) -> None:
        _text(self.node_id)
        _text(self.zone)
        if (
            not isinstance(self.phase, str)
            or self.phase not in {"on", "off", "unknown"}
        ):
            raise ValueError("Path health aggregate phase is invalid")
        for value in (self.on_started_at, self.unsupported_started_at):
            if value is not None:
                _utc(value)
                if self.phase != "on":
                    raise ValueError("Only ON can retain an unfinished health run")
        if (
            self.on_started_at is not None
            and self.unsupported_started_at is not None
            and self.unsupported_started_at < self.on_started_at
        ):
            raise ValueError("Unsupported duration cannot precede observed ON")
        if (
            type(self.completed_cycles) is not tuple
            or len(self.completed_cycles) > QUICK_CYCLE_COUNT
        ):
            raise ValueError("Path health must retain at most six cycle timestamps")
        for completion in self.completed_cycles:
            _utc(completion)
        if any(a > b for a, b in zip(
            self.completed_cycles, self.completed_cycles[1:], strict=False,
        )):
            raise ValueError("Path health completions must be ordered")
        if (
            self.completed_cycles and self.on_started_at is not None
            and self.completed_cycles[-1] > self.on_started_at
        ):
            raise ValueError("Completed cycle cannot follow the current ON start")


class PathHealth:
    """Reduce physical diagnostics without changing episodes, paths or filters."""

    def __init__(self, nodes: tuple[PhysicalNode, ...]) -> None:
        if type(nodes) is not tuple or any(
            not isinstance(node, PhysicalNode) for node in nodes
        ):
            raise ValueError("Path health requires physical nodes")
        ids = [node.node_id for node in nodes]
        aliases = [alias for node in nodes for alias in node.aliases]
        if len(ids) != len(set(ids)) or len(aliases) != len(set(aliases)):
            raise ValueError("Path health nodes and aliases must be unique")
        self._nodes = {node.node_id: node for node in nodes}
        self._states = {
            node.node_id: PathHealthState(node.node_id, node.zone) for node in nodes
        }
        self._occurrences: dict[tuple[str, str], ReliabilityWarningOccurrence] = {}
        self._at: datetime | None = None

    @property
    def states(self) -> tuple[PathHealthState, ...]:
        return tuple(self._states[key] for key in sorted(self._states))

    def _frontier(self, at: datetime, covered_nodes: frozenset[str]) -> None:
        _utc(at)
        if self._at is not None and at < self._at:
            raise ValueError("Path health cannot move backwards")
        if type(covered_nodes) is not frozenset or any(
            not isinstance(node, str) or node not in self._nodes
            for node in covered_nodes
        ):
            raise ValueError("Path health coverage must name mapped physical nodes")

    def _phases(self, states: tuple[EpisodeState, ...]) -> dict[str, str]:
        if type(states) is not tuple or any(
            not isinstance(state, EpisodeState) for state in states
        ):
            raise ValueError("Path health observations require episode states")
        if (
            len(states) != len(self._nodes)
            or {state.node_id for state in states} != set(self._nodes)
        ):
            raise ValueError("Path health observations must cover every node once")
        phases: dict[str, str] = {}
        for state in states:
            node = self._nodes[state.node_id]
            if (
                state.zone != node.zone or state.profile_name != node.profile_name
                or type(state.alias_states) is not tuple
                or any(
                    type(pair) is not tuple or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not isinstance(pair[1], str)
                    or pair[1] not in {"on", "off", "unknown", "unavailable"}
                    for pair in state.alias_states
                )
                or len(state.alias_states) != len(node.aliases)
                or {alias for alias, _ in state.alias_states} != set(node.aliases)
            ):
                raise ValueError("Path health observation identity or aliases differ")
            values = tuple(value for _, value in state.alias_states)
            phases[state.node_id] = (
                "on" if "on" in values else "off"
                if all(value == "off" for value in values) else "unknown"
            )
        return phases

    def _warning(
        self, state: PathHealthState, reason: str, at: datetime,
        qualified_at: datetime | None,
    ) -> None:
        key = state.node_id, reason
        previous = self._occurrences.get(key)
        if qualified_at is not None:
            first = (
                previous.first_observed_at
                if previous is not None and previous.cleared_at is None
                else qualified_at
            )
            self._occurrences[key] = ReliabilityWarningOccurrence(
                state.node_id, state.zone, _REASONS[reason], reason, first, at,
            )
        elif previous is not None and previous.cleared_at is None:
            self._occurrences[key] = replace(
                previous, last_observed_at=at, cleared_at=at,
            )

    def _progress(self, at: datetime, *, bootstrap: bool = False) -> None:
        """Resolve old predicates at exact deadlines before the next input."""
        for state in self.states:
            if not bootstrap and state.unsupported_started_at is not None:
                due = state.unsupported_started_at + UNSUPPORTED_ON_WINDOW
                if due <= at:
                    self._warning(state, "assertion_timeout", at, due)
            cycles = state.completed_cycles
            if len(cycles) == QUICK_CYCLE_COUNT:
                expiry = cycles[0] + QUICK_CYCLE_WINDOW
                if expiry <= at:
                    self._warning(state, "sustained_flapping", expiry, None)
                else:
                    self._warning(state, "sustained_flapping", at, cycles[-1])
            self._states[state.node_id] = replace(state, completed_cycles=tuple(
                completion for completion in cycles
                if at - completion < QUICK_CYCLE_WINDOW
            ))

    def _support(self, state: PathHealthState, at: datetime, covered: bool) -> None:
        start = state.unsupported_started_at
        if state.phase != "on" or covered:
            start = None
            self._warning(state, "unsupported_jump", at, None)
        elif start is None:
            start = at
        state = replace(state, unsupported_started_at=start)
        self._states[state.node_id] = state
        due = None if start is None else start + UNSUPPORTED_ON_WINDOW
        self._warning(
            state, "assertion_timeout", at,
            due if due is not None and due <= at else None,
        )

    def observe(
        self, states: tuple[EpisodeState, ...], at: datetime,
        covered_nodes: frozenset[str], *, bootstrap: bool = False,
    ) -> None:
        """Record aggregate edges, including flaps suppressed by inference.

        Bootstrap cancels an unfinished cycle and restarts observed unsupported
        duration even if the aggregate remains ON. Completed cycles remain real
        history and expire normally. Support never suppresses flapping diagnostics.
        """
        self._frontier(at, covered_nodes)
        if type(bootstrap) is not bool:
            raise ValueError("Path health bootstrap flag must be boolean")
        phases = self._phases(states)
        self._progress(at, bootstrap=bootstrap)
        for state in self.states:
            phase = phases[state.node_id]
            cycles = state.completed_cycles
            if (
                not bootstrap and phase == "off" and state.phase == "on"
                and state.on_started_at is not None
                and at - state.on_started_at <= QUICK_CYCLE_MAX_ON
            ):
                cycles = (*cycles, at)[-QUICK_CYCLE_COUNT:]
            start = None
            if phase == "on" and not bootstrap:
                start = at if state.phase != "on" else state.on_started_at
            if bootstrap:
                self._warning(state, "assertion_timeout", at, None)
                self._warning(state, "unsupported_jump", at, None)
            state = replace(
                state, phase=phase, on_started_at=start, completed_cycles=cycles,
                unsupported_started_at=(
                    state.unsupported_started_at
                    if phase == "on" and not bootstrap else None
                ),
            )
            self._support(state, at, state.node_id in covered_nodes)
            self._warning(
                state, "sustained_flapping", at,
                cycles[-1] if len(cycles) == QUICK_CYCLE_COUNT else None,
            )
        self._at = at

    def record_unsupported_jump(
        self, node_id: str, at: datetime, covered_nodes: frozenset[str],
    ) -> None:
        """Commit an event-only diagnostic AFTER observing its raw aggregate ON.

        This ledger never supplies inference. Timers can clear but cannot create
        or refresh the occurrence; a new physical ON begins a new occurrence.
        """
        self._frontier(at, covered_nodes)
        state = self._states[node_id]
        if self._at != at or state.on_started_at != at:
            raise ValueError("Unsupported jump requires the observed ON frontier")
        if state.phase == "on" and node_id not in covered_nodes:
            self._warning(state, "unsupported_jump", at, at)

    def advance(
        self, at: datetime, covered_nodes: frozenset[str],
    ) -> tuple[ReliabilityWarningOccurrence, ...]:
        """Return the full latest-per-node/reason ledger, including cleared rows."""
        self._frontier(at, covered_nodes)
        self._progress(at)
        for state in self.states:
            self._support(state, at, state.node_id in covered_nodes)
        self._at = at
        return tuple(self._occurrences[key] for key in sorted(self._occurrences))

    def restore(
        self, states: tuple[PathHealthState, ...],
        occurrences: tuple[ReliabilityWarningOccurrence, ...], at: datetime,
    ) -> None:
        """Atomically validate a coherent snapshot at its recorded frontier.

        No elapsed time or restart gap is inferred here. Call ``observe`` with
        ``bootstrap=True`` for a new observation session after loading a snapshot.
        """
        _utc(at)
        if type(states) is not tuple or any(
            not isinstance(state, PathHealthState) for state in states
        ):
            raise ValueError("Path health snapshot requires health states")
        ids = tuple(state.node_id for state in states)
        if ids != tuple(sorted(self._nodes)):
            raise ValueError("Path health snapshot must have every node in order")
        for state in states:
            state.__post_init__()
            if state.zone != self._nodes[state.node_id].zone:
                raise ValueError("Path health snapshot zone differs from physical node")
            if any(value > at for value in (
                state.on_started_at, state.unsupported_started_at,
                *state.completed_cycles,
            ) if value is not None):
                raise ValueError("Path health snapshot contains a future timestamp")
            if any(
                at - value >= QUICK_CYCLE_WINDOW for value in state.completed_cycles
            ):
                raise ValueError("Path health snapshot contains an expired cycle")
        if type(occurrences) is not tuple or any(
            not isinstance(item, ReliabilityWarningOccurrence) for item in occurrences
        ):
            raise ValueError("Path health snapshot requires warning occurrences")
        keys = tuple((item.node_id, item.reason) for item in occurrences)
        for item in occurrences:
            if (
                not isinstance(item.node_id, str) or item.node_id not in self._nodes
                or not isinstance(item.reason, str) or item.reason not in _REASONS
                or item.kind != _REASONS[item.reason]
                or item.zone != self._nodes[item.node_id].zone
            ):
                raise ValueError("Path health warning identity or reason is invalid")
            _utc(item.first_observed_at)
            _utc(item.last_observed_at)
            for value in (
                item.first_observed_at, item.last_observed_at, item.cleared_at,
            ):
                if value is not None and _utc(value) > at:
                    raise ValueError("Path health warning timestamp is in the future")
            item.__post_init__()
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Path health warnings require unique canonical order")
        ledger = dict(zip(keys, occurrences, strict=True))
        for state in states:
            jump = ledger.get((state.node_id, "unsupported_jump"))
            if jump is not None and jump.cleared_at is None and (
                state.phase != "on" or state.on_started_at != jump.first_observed_at
                or jump.last_observed_at != jump.first_observed_at
            ):
                raise ValueError("Unsupported jump disagrees with observed ON frontier")
            start = state.unsupported_started_at
            stuck_due = None if start is None else start + UNSUPPORTED_ON_WINDOW
            qualified = {
                "assertion_timeout": stuck_due is not None and stuck_due <= at,
                "sustained_flapping": len(state.completed_cycles) == QUICK_CYCLE_COUNT,
            }
            for reason, active in qualified.items():
                occurrence = ledger.get((state.node_id, reason))
                if active != (occurrence is not None and occurrence.cleared_at is None):
                    raise ValueError("Path health warning and physical ledger disagree")
                if (
                    occurrence is not None and occurrence.cleared_at is not None
                    and reason == "assertion_timeout" and start is not None
                    and occurrence.cleared_at > start
                ):
                    raise ValueError("Cleared warning overlaps current unsupported run")
                if occurrence is not None and occurrence.cleared_at is None:
                    if occurrence.last_observed_at != at:
                        raise ValueError("Active health warning must reach frontier")
                    if (
                        reason == "assertion_timeout"
                        and occurrence.first_observed_at != stuck_due
                    ):
                        raise ValueError("Unsupported warning starts at qualification")
                    if (
                        reason == "sustained_flapping"
                        and occurrence.first_observed_at > state.completed_cycles[-1]
                    ):
                        raise ValueError("Flapping warning must start at a completion")
        self._states = {state.node_id: state for state in states}
        self._occurrences = ledger
        self._at = at


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Path health JSON timestamp must be an ISO string or null")
    try:
        return _utc(datetime.fromisoformat(value))
    except ValueError as exc:
        raise ValueError("Path health JSON timestamp must be aware UTC") from exc


def decode_health(value: object) -> tuple[PathHealthState, ...]:
    """Strict JSON list decoder; independent of persistence and physical maps."""
    if type(value) is not list:
        raise ValueError("Path health JSON collection must be a list")
    result: list[PathHealthState] = []
    for item in value:
        if type(item) is not dict or set(item) != {
            "node_id", "zone", "phase", "on_started_at",
            "unsupported_started_at", "completed_cycles",
        }:
            raise ValueError("Path health JSON record has missing or unexpected fields")
        data = cast(dict[str, object], item)
        raw_cycles = data["completed_cycles"]
        if type(raw_cycles) is not list:
            raise ValueError("Path health JSON cycle timestamps must be a list")
        cycles = tuple(_timestamp(completion) for completion in raw_cycles)
        if any(completion is None for completion in cycles):
            raise ValueError("Path health completed cycle timestamp cannot be null")
        result.append(PathHealthState(
            _text(data["node_id"]), _text(data["zone"]), _text(data["phase"]),
            _timestamp(data["on_started_at"]),
            _timestamp(data["unsupported_started_at"]),
            cast(tuple[datetime, ...], cycles),
        ))
    ids = tuple(state.node_id for state in result)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("Path health JSON states require unique canonical order")
    return tuple(result)
