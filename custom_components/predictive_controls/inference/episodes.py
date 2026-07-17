"""Physical-node correlated observation episode processes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ..events import OccupancyEvent
from ..model import PredictiveMap
from .types import require_utc


@dataclass(frozen=True)
class EpisodeProfile:
    """Shared calibration and independent timing bounds for one node class."""

    burst_correlation_window: timedelta
    stable_clear_window: timedelta
    refractory_or_hold_interval: timedelta
    on_occupied: float
    on_empty: float
    off_occupied: float
    off_empty: float
    duration_tau: timedelta
    duration_max_log_odds: float

    def __post_init__(self) -> None:
        windows = (
            self.burst_correlation_window,
            self.stable_clear_window,
            self.refractory_or_hold_interval,
            self.duration_tau,
        )
        if any(window < timedelta(0) for window in windows):
            raise ValueError("Episode profile durations must be non-negative")
        likelihoods = (
            self.on_occupied,
            self.on_empty,
            self.off_occupied,
            self.off_empty,
        )
        if any(not 0.0 < value <= 1.0 for value in likelihoods):
            raise ValueError("Episode likelihoods must be in (0, 1]")
        if (
            not math.isfinite(self.duration_max_log_odds)
            or self.duration_max_log_odds < 0.0
        ):
            raise ValueError(
                "Duration log-odds ceiling must be finite and non-negative"
            )
        if self.duration_max_log_odds > 0.0 and self.duration_tau == timedelta(0):
            raise ValueError("Duration tau must be positive when duration is enabled")


SUSTAINED_EPISODE_PROFILE = EpisodeProfile(
    burst_correlation_window=timedelta(seconds=5),
    stable_clear_window=timedelta(seconds=5),
    refractory_or_hold_interval=timedelta(seconds=30),
    on_occupied=0.97,
    on_empty=0.02,
    off_occupied=0.30,
    off_empty=0.95,
    duration_tau=timedelta(minutes=5),
    duration_max_log_odds=math.log(24.0),
)
ORDINARY_EPISODE_PROFILE = EpisodeProfile(
    burst_correlation_window=timedelta(seconds=5),
    stable_clear_window=timedelta(seconds=5),
    refractory_or_hold_interval=timedelta(seconds=30),
    on_occupied=0.90,
    on_empty=0.04,
    off_occupied=0.45,
    off_empty=0.90,
    duration_tau=timedelta(0),
    duration_max_log_odds=0.0,
)
TRANSITION_EPISODE_PROFILE = EpisodeProfile(
    burst_correlation_window=timedelta(seconds=5),
    stable_clear_window=timedelta(seconds=5),
    refractory_or_hold_interval=timedelta(seconds=30),
    on_occupied=0.85,
    on_empty=0.05,
    off_occupied=0.55,
    off_empty=0.85,
    duration_tau=timedelta(0),
    duration_max_log_odds=0.0,
)


@dataclass(frozen=True)
class EpisodeEmission:
    """One bounded binary-zone likelihood contribution."""

    node_id: str
    zone: str
    episode_id: str
    evidence_id: str
    kind: str
    empty_log_likelihood: float
    occupied_log_likelihood: float


@dataclass(frozen=True)
class NodeEpisodeState:
    """Complete restart-safe state for one physical-node process."""

    node_id: str
    zone: str
    raw_alias_states: tuple[tuple[str, str], ...]
    episode_id: str | None = None
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    last_inactive_at: datetime | None = None
    latest_clear_at: datetime | None = None
    clear_deadline: datetime | None = None
    current_positive: bool = False
    positive_emitted: bool = False
    clear_emitted: bool = False
    asserted_seconds: float = 0.0
    asserted_segment_started_at: datetime | None = None
    applied_duration_log_odds: float = 0.0
    endpoint_valid_until: datetime | None = None
    finalized_at: datetime | None = None
    status: str = "baseline"

    @property
    def known_on(self) -> bool:
        return any(state == "on" for _, state in self.raw_alias_states)


@dataclass(frozen=True)
class EpisodeUpdate:
    """Immutable result of one node event or frontier evaluation."""

    disposition: str
    state: NodeEpisodeState
    emissions: tuple[EpisodeEmission, ...] = ()


class ObservationEpisodes:
    """Maintain one correlated process per physical map node."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        profiles: dict[str, EpisodeProfile] | None = None,
    ) -> None:
        self._map = predictive_map
        self._profiles = profiles or {}
        self._aliases_by_node = {
            node_id: tuple(sorted(node.entities.values()))
            for node_id, node in predictive_map.nodes.items()
        }
        self._states = {
            node_id: NodeEpisodeState(
                node_id,
                node.occupancy_zone,
                tuple((entity_id, "unknown") for entity_id in aliases),
            )
            for node_id, aliases in self._aliases_by_node.items()
            if (node := predictive_map.nodes.get(node_id)) is not None
        }

    @property
    def states(self) -> tuple[NodeEpisodeState, ...]:
        return tuple(self._states[node_id] for node_id in sorted(self._states))

    def restore_snapshot(self, states: tuple[NodeEpisodeState, ...]) -> None:
        """Restore a validated immutable in-memory episode snapshot."""

        restored = {state.node_id: state for state in states}
        if len(restored) != len(states) or set(restored) != set(self._states):
            raise ValueError("Episode snapshot nodes are invalid")
        for node_id, state in restored.items():
            expected = self._states[node_id]
            if state.zone != expected.zone or set(dict(state.raw_alias_states)) != set(
                self._aliases_by_node[node_id]
            ):
                raise ValueError("Episode snapshot is incompatible with the map")
        _validate_restored_states(restored)
        self._states = restored

    def serialize(self) -> list[dict[str, object]]:
        return [
            {
                "node_id": state.node_id,
                "zone": state.zone,
                "profile": _profile_payload(self._profile(state.node_id)),
                "raw_alias_states": dict(state.raw_alias_states),
                "episode_id": state.episode_id,
                "started_at": _datetime_payload(state.started_at),
                "last_event_at": _datetime_payload(state.last_event_at),
                "last_inactive_at": _datetime_payload(state.last_inactive_at),
                "latest_clear_at": _datetime_payload(state.latest_clear_at),
                "clear_deadline": _datetime_payload(state.clear_deadline),
                "current_positive": state.current_positive,
                "positive_emitted": state.positive_emitted,
                "clear_emitted": state.clear_emitted,
                "asserted_seconds": state.asserted_seconds,
                "asserted_segment_started_at": _datetime_payload(
                    state.asserted_segment_started_at
                ),
                "applied_duration_log_odds": state.applied_duration_log_odds,
                "endpoint_valid_until": _datetime_payload(state.endpoint_valid_until),
                "finalized_at": _datetime_payload(state.finalized_at),
                "status": state.status,
            }
            for state in self.states
        ]

    def restore(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise TypeError("Stored episode state must be a list")
        restored: dict[str, NodeEpisodeState] = {}
        for raw in payload:
            if not isinstance(raw, Mapping):
                raise ValueError("Stored node episode must be a mapping")
            node_id = raw.get("node_id")
            if not isinstance(node_id, str) or node_id not in self._states:
                raise ValueError("Stored episode node is invalid")
            if node_id in restored:
                raise ValueError("Stored episode node is duplicated")
            if raw.get("zone") != self._states[node_id].zone:
                raise ValueError("Stored episode zone is invalid")
            if raw.get("profile") != _profile_payload(self._profile(node_id)):
                raise ValueError("Stored episode profile is incompatible")
            raw_aliases = raw.get("raw_alias_states")
            if not isinstance(raw_aliases, Mapping) or set(raw_aliases) != set(
                self._aliases_by_node[node_id]
            ):
                raise ValueError("Stored episode aliases are incompatible")
            alias_states: dict[str, str] = {}
            for entity_id, value in raw_aliases.items():
                if not isinstance(entity_id, str) or value not in {
                    "on",
                    "off",
                    "unknown",
                    "unavailable",
                }:
                    raise ValueError("Stored alias state is invalid")
                alias_states[entity_id] = str(value)
            episode_id = raw.get("episode_id")
            status = raw.get("status")
            if episode_id is not None and not isinstance(episode_id, str):
                raise ValueError("Stored episode ID is invalid")
            if status not in {
                "baseline",
                "asserted",
                "clearing",
                "unavailable",
                "finalized",
            }:
                raise ValueError("Stored episode status is invalid")
            booleans = {
                key: raw.get(key)
                for key in (
                    "current_positive",
                    "positive_emitted",
                    "clear_emitted",
                )
            }
            if any(not isinstance(value, bool) for value in booleans.values()):
                raise ValueError("Stored episode flags are invalid")
            asserted_seconds = _finite_non_negative(
                raw.get("asserted_seconds"),
                "asserted duration",
            )
            applied_duration = _finite_non_negative(
                raw.get("applied_duration_log_odds"),
                "duration likelihood",
            )
            if applied_duration > self._profile(node_id).duration_max_log_odds:
                raise ValueError("Stored duration likelihood exceeds its profile")
            restored[node_id] = NodeEpisodeState(
                node_id,
                self._states[node_id].zone,
                tuple(sorted(alias_states.items())),
                episode_id=episode_id,
                started_at=_restore_datetime(raw.get("started_at")),
                last_event_at=_restore_datetime(raw.get("last_event_at")),
                last_inactive_at=_restore_datetime(raw.get("last_inactive_at")),
                latest_clear_at=_restore_datetime(raw.get("latest_clear_at")),
                clear_deadline=_restore_datetime(raw.get("clear_deadline")),
                current_positive=bool(booleans["current_positive"]),
                positive_emitted=bool(booleans["positive_emitted"]),
                clear_emitted=bool(booleans["clear_emitted"]),
                asserted_seconds=asserted_seconds,
                asserted_segment_started_at=_restore_datetime(
                    raw.get("asserted_segment_started_at")
                ),
                applied_duration_log_odds=applied_duration,
                endpoint_valid_until=_restore_datetime(raw.get("endpoint_valid_until")),
                finalized_at=_restore_datetime(raw.get("finalized_at")),
                status=str(status),
            )
        if set(restored) != set(self._states):
            raise ValueError("Stored episode nodes are incomplete")
        _validate_restored_states(restored)
        self._states = restored

    def observe(self, event: OccupancyEvent) -> EpisodeUpdate:
        require_utc(event.event_at, "Observation event time")
        state = self._state_for_event(event)
        raw_states = dict(state.raw_alias_states)
        if raw_states[event.entity_id] == event.state:
            return EpisodeUpdate("duplicate", state)
        if state.last_event_at is not None and event.event_at < state.last_event_at:
            return EpisodeUpdate("stale", state)

        profile = self._profile(event.node_id)
        state, duration_emissions = self._advance_state(
            state,
            profile,
            event.event_at,
        )
        raw_states = dict(state.raw_alias_states)
        was_known_on = state.known_on
        raw_states[event.entity_id] = event.state
        is_known_on = any(value == "on" for value in raw_states.values())
        state = replace(
            state,
            raw_alias_states=tuple(sorted(raw_states.items())),
            last_event_at=event.event_at,
        )
        emissions = list(duration_emissions)

        if event.state in {"unknown", "unavailable"}:
            if was_known_on and not is_known_on:
                state = replace(
                    state,
                    asserted_segment_started_at=None,
                    last_inactive_at=event.event_at,
                    endpoint_valid_until=None,
                    status="unavailable",
                )
            self._states[event.node_id] = state
            return EpisodeUpdate("neutral_availability", state, tuple(emissions))

        if is_known_on:
            if was_known_on:
                disposition = "correlated_alias"
            elif self._continues_episode(state, profile, event.event_at):
                state = replace(
                    state,
                    clear_deadline=None,
                    current_positive=True,
                    asserted_segment_started_at=event.event_at,
                    status="asserted",
                )
                disposition = "correlated_reassertion"
            else:
                state, positive = self._start_episode(
                    state,
                    profile,
                    event,
                )
                emissions.append(positive)
                disposition = "accepted_positive"
        elif state.current_positive:
            state, clear = self._clear_episode(state, profile, event)
            if clear is not None:
                emissions.append(clear)
                disposition = "accepted_clear"
            else:
                disposition = "correlated_clear"
        else:
            disposition = "baseline_clear"

        self._states[event.node_id] = state
        return EpisodeUpdate(disposition, state, tuple(emissions))

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> tuple[EpisodeUpdate, ...]:
        grouped: dict[str, dict[str, OccupancyEvent]] = {}
        for event in events:
            require_utc(event.event_at, "Snapshot event time")
            self._state_for_event(event)
            node_events = grouped.setdefault(event.node_id, {})
            if event.entity_id in node_events:
                raise ValueError("Snapshot contains a duplicate entity")
            node_events[event.entity_id] = event

        updates: list[EpisodeUpdate] = []
        for node_id in sorted(grouped):
            node_events = grouped[node_id]
            state = self._states[node_id]
            raw_states = dict(state.raw_alias_states)
            if all(
                raw_states[entity_id] == event.state
                for entity_id, event in node_events.items()
            ):
                continue
            event_at = max(event.event_at for event in node_events.values())
            if state.last_event_at is not None and event_at < state.last_event_at:
                updates.append(EpisodeUpdate("stale", state))
                continue
            profile = self._profile(node_id)
            state, duration_emissions = self._advance_state(
                state,
                profile,
                event_at,
            )
            was_known_on = state.known_on
            for entity_id, snapshot_event in node_events.items():
                raw_states[entity_id] = snapshot_event.state
            is_known_on = any(value == "on" for value in raw_states.values())
            state = replace(
                state,
                raw_alias_states=tuple(sorted(raw_states.items())),
                last_event_at=event_at,
            )
            emissions = list(duration_emissions)
            representative = min(
                node_events.values(),
                key=lambda item: (item.event_at, item.entity_id),
            )
            positive_events = tuple(
                sorted(
                    (event for event in node_events.values() if event.state == "on"),
                    key=lambda item: (item.event_at, item.entity_id),
                )
            )
            off_events = tuple(
                sorted(
                    (event for event in node_events.values() if event.state == "off"),
                    key=lambda item: (item.event_at, item.entity_id),
                )
            )

            if is_known_on and not was_known_on:
                positive = positive_events[0]
                if not cold_start and self._continues_episode(
                    state,
                    profile,
                    event_at,
                ):
                    state = replace(
                        state,
                        clear_deadline=None,
                        current_positive=True,
                        asserted_segment_started_at=event_at,
                        status="asserted",
                    )
                else:
                    state, positive_emission = self._start_episode(
                        state,
                        profile,
                        positive,
                    )
                    state = replace(
                        state,
                        raw_alias_states=tuple(sorted(raw_states.items())),
                        last_event_at=event_at,
                    )
                    emissions.append(positive_emission)
            elif not is_known_on and state.current_positive and off_events:
                state, clear_emission = self._clear_episode(
                    state,
                    profile,
                    off_events[-1],
                )
                state = replace(
                    state,
                    raw_alias_states=tuple(sorted(raw_states.items())),
                    last_event_at=event_at,
                )
                if clear_emission is not None:
                    emissions.append(clear_emission)
            elif not is_known_on and state.current_positive:
                state = replace(
                    state,
                    asserted_segment_started_at=None,
                    last_inactive_at=event_at,
                    endpoint_valid_until=None,
                    status="unavailable",
                )
            elif not is_known_on and cold_start:
                state = replace(state, status="baseline")
            elif was_known_on and is_known_on:
                state = replace(state, status="asserted")
            else:
                state = replace(
                    state,
                    last_inactive_at=representative.event_at,
                )
            self._states[node_id] = state
            updates.append(
                EpisodeUpdate("snapshot_reconciled", state, tuple(emissions))
            )
        return tuple(updates)

    def advance(self, now: datetime) -> tuple[EpisodeUpdate, ...]:
        require_utc(now, "Episode evaluation time")
        updates: list[EpisodeUpdate] = []
        for node_id in sorted(self._states):
            state = self._states[node_id]
            if state.last_event_at is not None and now < state.last_event_at:
                continue
            advanced, emissions = self._advance_state(
                state,
                self._profile(node_id),
                now,
            )
            if advanced != state or emissions:
                self._states[node_id] = advanced
                updates.append(EpisodeUpdate("advanced", advanced, emissions))
        return tuple(updates)

    def _state_for_event(self, event: OccupancyEvent) -> NodeEpisodeState:
        try:
            state = self._states[event.node_id]
        except KeyError as exc:
            raise ValueError(
                f"Observation node is not in the predictive map: {event.node_id}"
            ) from exc
        if event.zone != state.zone:
            raise ValueError("Observation zone does not match its physical node")
        if event.entity_id not in dict(state.raw_alias_states):
            raise ValueError("Observation entity is not an alias of its physical node")
        return state

    def _profile(self, node_id: str) -> EpisodeProfile:
        configured = self._profiles.get(node_id)
        if configured is not None:
            return configured
        node = self._map.nodes[node_id]
        behavior = self._map.occupancy_behavior_for_node(node)
        if behavior == "transient" or node.role == "transition_gate":
            return TRANSITION_EPISODE_PROFILE
        if behavior in {"sticky", "sustained"}:
            return SUSTAINED_EPISODE_PROFILE
        return ORDINARY_EPISODE_PROFILE

    @staticmethod
    def _continues_episode(
        state: NodeEpisodeState,
        profile: EpisodeProfile,
        event_at: datetime,
    ) -> bool:
        return (
            state.episode_id is not None
            and state.current_positive
            and state.last_inactive_at is not None
            and event_at - state.last_inactive_at <= profile.burst_correlation_window
        )

    def _start_episode(
        self,
        state: NodeEpisodeState,
        profile: EpisodeProfile,
        event: OccupancyEvent,
    ) -> tuple[NodeEpisodeState, EpisodeEmission]:
        episode_id = f"{event.node_id}@{event.event_at.isoformat()}"
        next_state = replace(
            state,
            episode_id=episode_id,
            started_at=event.event_at,
            last_inactive_at=None,
            latest_clear_at=None,
            clear_deadline=None,
            current_positive=True,
            positive_emitted=True,
            clear_emitted=False,
            asserted_seconds=0.0,
            asserted_segment_started_at=event.event_at,
            applied_duration_log_odds=0.0,
            endpoint_valid_until=(event.event_at + profile.refractory_or_hold_interval),
            finalized_at=None,
            status="asserted",
        )
        empty, occupied = _calibrated_likelihoods(
            profile.on_empty,
            profile.on_occupied,
            event.reliability,
        )
        return next_state, EpisodeEmission(
            event.node_id,
            event.zone,
            episode_id,
            _event_id(event),
            "positive",
            math.log(empty),
            math.log(occupied),
        )

    def _clear_episode(
        self,
        state: NodeEpisodeState,
        profile: EpisodeProfile,
        event: OccupancyEvent,
    ) -> tuple[NodeEpisodeState, EpisodeEmission | None]:
        next_state = replace(
            state,
            last_inactive_at=event.event_at,
            latest_clear_at=event.event_at,
            clear_deadline=event.event_at + profile.stable_clear_window,
            asserted_segment_started_at=None,
            endpoint_valid_until=None,
            status="clearing",
        )
        if state.clear_emitted or state.episode_id is None:
            return next_state, None
        empty, occupied = _calibrated_likelihoods(
            profile.off_empty,
            profile.off_occupied,
            event.reliability,
        )
        return replace(next_state, clear_emitted=True), EpisodeEmission(
            event.node_id,
            event.zone,
            state.episode_id,
            _event_id(event),
            "clear",
            math.log(empty),
            math.log(occupied),
        )

    def _advance_state(
        self,
        state: NodeEpisodeState,
        profile: EpisodeProfile,
        now: datetime,
    ) -> tuple[NodeEpisodeState, tuple[EpisodeEmission, ...]]:
        advanced = state
        emissions: list[EpisodeEmission] = []
        if (
            state.asserted_segment_started_at is not None
            and now > state.asserted_segment_started_at
        ):
            asserted_seconds = (
                state.asserted_seconds
                + (now - state.asserted_segment_started_at).total_seconds()
            )
            target = _duration_log_odds(profile, asserted_seconds)
            delta = target - state.applied_duration_log_odds
            advanced = replace(
                state,
                asserted_seconds=asserted_seconds,
                asserted_segment_started_at=now,
                applied_duration_log_odds=target,
            )
            if delta > 0.0 and state.episode_id is not None:
                emissions.append(
                    EpisodeEmission(
                        state.node_id,
                        state.zone,
                        state.episode_id,
                        f"{state.episode_id}:duration:{asserted_seconds:.6f}",
                        "duration",
                        0.0,
                        delta,
                    )
                )
        if advanced.clear_deadline is not None and now >= advanced.clear_deadline:
            advanced = replace(
                advanced,
                current_positive=False,
                clear_deadline=None,
                asserted_segment_started_at=None,
                endpoint_valid_until=None,
                finalized_at=advanced.clear_deadline,
                status="finalized",
            )
        return advanced, tuple(emissions)


def _calibrated_likelihoods(
    empty: float,
    occupied: float,
    reliability: float,
) -> tuple[float, float]:
    bounded_reliability = min(1.0, max(0.0, reliability))
    return (
        0.5 + bounded_reliability * (empty - 0.5),
        0.5 + bounded_reliability * (occupied - 0.5),
    )


def _duration_log_odds(profile: EpisodeProfile, asserted_seconds: float) -> float:
    if profile.duration_max_log_odds == 0.0:
        return 0.0
    return profile.duration_max_log_odds * (
        1.0 - math.exp(-asserted_seconds / profile.duration_tau.total_seconds())
    )


def _event_id(event: OccupancyEvent) -> str:
    return f"{event.entity_id}@{event.event_at.isoformat()}:{event.state}"


def _profile_payload(profile: EpisodeProfile) -> dict[str, float]:
    return {
        "burst_seconds": profile.burst_correlation_window.total_seconds(),
        "stable_clear_seconds": profile.stable_clear_window.total_seconds(),
        "hold_seconds": profile.refractory_or_hold_interval.total_seconds(),
        "on_occupied": profile.on_occupied,
        "on_empty": profile.on_empty,
        "off_occupied": profile.off_occupied,
        "off_empty": profile.off_empty,
        "duration_tau_seconds": profile.duration_tau.total_seconds(),
        "duration_max_log_odds": profile.duration_max_log_odds,
    }


def _datetime_payload(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _restore_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Stored episode datetime is invalid")
    try:
        restored = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Stored episode datetime is invalid") from exc
    require_utc(restored, "Stored episode datetime")
    return restored


def _finite_non_negative(value: object, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Stored {label} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"Stored {label} is invalid")
    return numeric


def _validate_restored_states(states: Mapping[str, NodeEpisodeState]) -> None:
    for state in states.values():
        if state.episode_id is None and any(
            (
                state.started_at is not None,
                state.current_positive,
                state.positive_emitted,
                state.clear_emitted,
                state.asserted_segment_started_at is not None,
            )
        ):
            raise ValueError("Stored baseline episode has active state")
        if state.clear_deadline is not None and state.latest_clear_at is None:
            raise ValueError("Stored clear deadline lacks a clear event")
        if (
            state.started_at is not None
            and state.last_event_at is not None
            and state.last_event_at < state.started_at
        ):
            raise ValueError("Stored episode event ordering is invalid")
