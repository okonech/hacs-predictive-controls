"""Physical-node episode aggregation for the graph-local target model."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .profiles import SHARED_PROFILES
from .types import (
    EPISODE_STATUSES,
    EpisodeEffect,
    EpisodeState,
    EpisodeUpdate,
    PhysicalNode,
    SensorInput,
    SensorProfile,
    require_utc,
)


class PhysicalEpisodes:
    """Maintain one bounded, correlated process per physical node."""

    def __init__(self, nodes: tuple[PhysicalNode, ...]) -> None:
        node_ids = [node.node_id for node in nodes]
        aliases = [alias for node in nodes for alias in node.aliases]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Physical episode nodes must be unique")
        if len(aliases) != len(set(aliases)):
            raise ValueError("Physical episode aliases must map to one node")
        self._nodes = {node.node_id: node for node in nodes}
        self._node_by_alias = {
            alias: node.node_id for node in nodes for alias in node.aliases
        }
        self._states = {
            node.node_id: EpisodeState(
                node.node_id,
                node.zone,
                node.profile_name,
                tuple((alias, "unknown") for alias in sorted(node.aliases)),
            )
            for node in nodes
        }

    @property
    def states(self) -> tuple[EpisodeState, ...]:
        return tuple(self._states[node_id] for node_id in sorted(self._states))

    def restore_snapshot(self, states: tuple[EpisodeState, ...]) -> None:
        restored = {state.node_id: state for state in states}
        if len(restored) != len(states) or set(restored) != set(self._states):
            raise ValueError("Episode snapshot is incompatible with physical nodes")
        for node_id, state in restored.items():
            self._validate_state(state)
            expected = self._states[node_id]
            if (
                state.zone != expected.zone
                or state.profile_name != expected.profile_name
                or set(dict(state.alias_states)) != set(dict(expected.alias_states))
            ):
                raise ValueError("Episode snapshot is incompatible with physical nodes")
        self._states = restored

    def observe(self, event: SensorInput) -> EpisodeUpdate:
        try:
            node_id = self._node_by_alias[event.entity_id]
        except KeyError as exc:
            raise ValueError(
                f"Sensor entity {event.entity_id!r} is not mapped"
            ) from exc
        state = self._states[node_id]
        if self._is_stale(state, event.event_at):
            return EpisodeUpdate("stale", state)
        alias_states = dict(state.alias_states)
        if alias_states[event.entity_id] == event.state:
            return EpisodeUpdate("duplicate", state)

        state, frontier_effects = self._advance_state(state, event.event_at)
        alias_states = dict(state.alias_states)
        was_known_on = state.known_on
        alias_states[event.entity_id] = event.state
        is_known_on = any(value == "on" for value in alias_states.values())
        state = replace(
            state,
            alias_states=tuple(sorted(alias_states.items())),
            last_event_at=event.event_at,
            advanced_at=event.event_at,
        )
        effects = list(frontier_effects)

        if event.state in {"unknown", "unavailable"}:
            all_unavailable = all(
                value in {"unknown", "unavailable"}
                for value in alias_states.values()
            )
            if (was_known_on and not is_known_on) or all_unavailable:
                state = replace(
                    state,
                    status="unavailable",
                    clear_started_at=None,
                    clear_deadline=None,
                )
            state = replace(state, traversal_valid_until=None)
            disposition = "neutral_availability"
        elif is_known_on:
            if was_known_on:
                disposition = "correlated_alias"
            elif self._continues_flap(state, event.event_at):
                impossible = bool(
                    state.hold_until is not None
                    and event.event_at < state.hold_until
                )
                state = replace(
                    state,
                    status="asserted",
                    clear_started_at=None,
                    clear_deadline=None,
                    traversal_valid_until=(
                        None if impossible else state.traversal_valid_until
                    ),
                    cadence_warning=state.cadence_warning or impossible,
                )
                assert state.episode_id is not None
                if impossible:
                    effects.append(
                        EpisodeEffect(
                            state.node_id,
                            state.zone,
                            state.episode_id,
                            "impossible_cadence",
                            event.event_at,
                            event.reliability,
                        )
                    )
                else:
                    effects.append(
                        EpisodeEffect(
                            state.node_id,
                            state.zone,
                            state.episode_id,
                            "correlated_flap_ignored",
                            event.event_at,
                            event.reliability,
                        )
                    )
                disposition = "correlated_reassertion"
            else:
                state, start_effects = self._start_episode(
                    state, event.event_at, event.reliability
                )
                effects.extend(start_effects)
                disposition = "accepted_positive"
        elif was_known_on:
            profile = self._profile(state)
            state = replace(
                state,
                status="clearing",
                clear_started_at=event.event_at,
                clear_deadline=event.event_at + profile.stable_clear_window,
            )
            disposition = "clear_pending"
        else:
            if state.status == "unavailable":
                state = replace(state, status="baseline")
            disposition = "baseline_clear"

        self._states[node_id] = state
        return EpisodeUpdate(disposition, state, tuple(effects))

    def advance(self, now: datetime) -> tuple[EpisodeUpdate, ...]:
        require_utc(now, "Episode frontier")
        updates: list[EpisodeUpdate] = []
        for node_id in sorted(self._states):
            state = self._states[node_id]
            if self._is_stale(state, now):
                updates.append(EpisodeUpdate("stale", state))
                continue
            if state.advanced_at == now:
                updates.append(EpisodeUpdate("unchanged", state))
                continue
            state, effects = self._advance_state(state, now)
            state = replace(state, advanced_at=now)
            self._states[node_id] = state
            updates.append(EpisodeUpdate("advanced", state, effects))
        return tuple(updates)

    def apply_count_conflict(
        self, node_id: str, episode_id: str, at: datetime
    ) -> EpisodeUpdate:
        """Health-degrade one still-asserted stay episode after count conflict."""

        require_utc(at, "Count-conflict degradation time")
        state = self._states[node_id]
        if state.episode_id != episode_id:
            raise ValueError("Count conflict does not match the current episode")
        if state.status == "degraded" and state.health_warning:
            return EpisodeUpdate("unchanged", state)
        if (
            state.status != "asserted"
            or state.health_warning
            or not state.known_on
            or self._profile(state).role != "stay"
        ):
            raise ValueError("Count conflict target is not a trustworthy stay episode")
        if self._is_stale(state, at):
            raise ValueError("Count-conflict degradation cannot move backward")
        state = replace(
            state,
            status="degraded",
            advanced_at=at,
            traversal_valid_until=None,
            degraded_at=at,
            degradation_reason="count_conflict",
            health_warning=True,
        )
        self._states[node_id] = state
        return EpisodeUpdate(
            "count_conflict_degraded",
            state,
            (
                EpisodeEffect(
                    state.node_id,
                    state.zone,
                    episode_id,
                    "health_degraded",
                    at,
                    self._nodes[node_id].reliability,
                ),
            ),
        )

    @staticmethod
    def _is_stale(state: EpisodeState, at: datetime) -> bool:
        frontiers = tuple(
            value
            for value in (state.last_event_at, state.advanced_at)
            if value is not None
        )
        return bool(frontiers and at < max(frontiers))

    @staticmethod
    def _validate_state(state: EpisodeState) -> None:
        profile = SHARED_PROFILES.get(state.profile_name)
        if profile is None:
            raise ValueError("Episode snapshot has an unknown profile")
        if state.status not in EPISODE_STATUSES:
            raise ValueError("Episode snapshot status is invalid")
        if state.generation < 0:
            raise ValueError("Episode snapshot generation is invalid")
        if state.generation == 0 and state.episode_id is not None:
            raise ValueError("Episode snapshot identity is invalid")
        if state.generation > 0 and (
            state.episode_id is None or state.started_at is None
        ):
            raise ValueError("Episode snapshot identity is incomplete")
        aliases = dict(state.alias_states)
        if len(aliases) != len(state.alias_states):
            raise ValueError("Episode snapshot aliases are duplicated")
        if state.alias_states != tuple(sorted(state.alias_states)):
            raise ValueError("Episode snapshot aliases are not deterministic")
        if any(
            value not in {"off", "on", "unknown", "unavailable"}
            for _, value in state.alias_states
        ):
            raise ValueError("Episode snapshot alias state is invalid")
        for value in (
            state.started_at,
            state.last_event_at,
            state.advanced_at,
            state.clear_started_at,
            state.clear_deadline,
            state.hold_until,
            state.assertion_trust_until,
            state.traversal_valid_until,
            state.degraded_at,
        ):
            if value is not None:
                require_utc(value, "Episode snapshot time")
        if state.last_event_at is not None and state.advanced_at is None:
            raise ValueError("Episode snapshot event frontier is incomplete")
        if state.last_event_at is not None and state.advanced_at is not None:
            if state.last_event_at > state.advanced_at:
                raise ValueError("Episode snapshot frontiers are inconsistent")
        if state.health_warning != (state.degraded_at is not None):
            raise ValueError("Episode snapshot health state is inconsistent")
        if state.health_warning != (state.degradation_reason is not None):
            raise ValueError("Episode snapshot health reason is inconsistent")
        if state.degradation_reason not in {
            None,
            "assertion_timeout",
            "count_conflict",
        }:
            raise ValueError("Episode snapshot health reason is invalid")
        if state.clear_emitted != (state.status == "clear"):
            raise ValueError("Episode snapshot clear state is inconsistent")
        if state.generation > 0:
            assert state.started_at is not None
            expected_episode_id = (
                f"{state.node_id}:{state.generation}:{state.started_at.isoformat()}"
            )
            if state.episode_id != expected_episode_id:
                raise ValueError("Episode snapshot identity is not deterministic")
            expected_hold_until = state.started_at + profile.hardware_hold_interval
            expected_trust_until = state.started_at + profile.assertion_trust_horizon
            if state.hold_until != expected_hold_until:
                raise ValueError("Episode snapshot hold frontier is inconsistent")
            if state.assertion_trust_until != expected_trust_until:
                raise ValueError("Episode snapshot trust frontier is inconsistent")
            if state.degradation_reason == "assertion_timeout" and (
                state.degraded_at != expected_trust_until
            ):
                raise ValueError("Episode snapshot degradation time is inconsistent")
            if state.degradation_reason == "count_conflict" and (
                state.degraded_at is None
                or state.advanced_at is None
                or not state.started_at < state.degraded_at <= state.advanced_at
            ):
                raise ValueError("Episode snapshot degradation time is inconsistent")
            if state.traversal_valid_until is not None:
                expected_traversal_until = min(
                    state.started_at + profile.traversal_context_window,
                    expected_trust_until,
                )
                if state.traversal_valid_until != expected_traversal_until:
                    raise ValueError(
                        "Episode snapshot traversal frontier is inconsistent"
                    )
        if state.status in {"baseline", "clear", "clearing", "unavailable"}:
            if state.known_on:
                raise ValueError("Inactive episode snapshot has asserted aliases")
        if state.status == "asserted" and (
            not state.known_on or state.health_warning or state.degraded_at is not None
        ):
            raise ValueError("Asserted episode snapshot is inconsistent")
        if state.status == "degraded" and (
            not state.known_on
            or not state.health_warning
            or state.degraded_at is None
            or state.traversal_valid_until is not None
        ):
            raise ValueError("Degraded episode snapshot is inconsistent")
        if state.status == "clearing" and (
            state.clear_started_at is None or state.clear_deadline is None
        ):
            raise ValueError("Clearing episode snapshot is inconsistent")
        if state.status == "clearing":
            assert state.clear_started_at is not None
            expected_clear_deadline = (
                state.clear_started_at + profile.stable_clear_window
            )
            if state.clear_deadline != expected_clear_deadline:
                raise ValueError("Episode snapshot clear frontier is inconsistent")
        if state.status == "clear" and (
            state.clear_started_at is not None
            or state.clear_deadline is not None
            or state.traversal_valid_until is not None
        ):
            raise ValueError("Clear episode snapshot is inconsistent")
        if state.status == "unavailable" and state.traversal_valid_until is not None:
            raise ValueError("Unavailable episode snapshot has traversal authority")

    @staticmethod
    def _profile(state: EpisodeState) -> SensorProfile:
        return SHARED_PROFILES[state.profile_name]

    def _continues_flap(self, state: EpisodeState, at: datetime) -> bool:
        if state.episode_id is None or state.status == "unavailable":
            return False
        return bool(
            (
                state.clear_started_at is not None
                and at
                <= state.clear_started_at
                + self._profile(state).burst_correlation_window
            )
            or (state.hold_until is not None and at < state.hold_until)
        )

    def _start_episode(
        self,
        state: EpisodeState,
        at: datetime,
        reliability: float,
    ) -> tuple[EpisodeState, tuple[EpisodeEffect, ...]]:
        profile = self._profile(state)
        generation = state.generation + 1
        episode_id = f"{state.node_id}:{generation}:{at.isoformat()}"
        effects: list[EpisodeEffect] = []
        if state.health_warning:
            effects.append(
                EpisodeEffect(
                    state.node_id,
                    state.zone,
                    episode_id,
                    "health_recovered",
                    at,
                    reliability,
                )
            )
        effects.append(
            EpisodeEffect(
                state.node_id,
                state.zone,
                episode_id,
                "positive",
                at,
                reliability,
            )
        )
        trust_until = at + profile.assertion_trust_horizon
        traversal_until = min(
            at + profile.traversal_context_window,
            trust_until,
        )
        return (
            replace(
                state,
                generation=generation,
                episode_id=episode_id,
                status="asserted",
                started_at=at,
                clear_started_at=None,
                clear_deadline=None,
                hold_until=at + profile.hardware_hold_interval,
                assertion_trust_until=trust_until,
                traversal_valid_until=traversal_until,
                degraded_at=None,
                degradation_reason=None,
                clear_emitted=False,
                health_warning=False,
                cadence_warning=False,
            ),
            tuple(effects),
        )

    def _advance_state(
        self,
        state: EpisodeState,
        now: datetime,
    ) -> tuple[EpisodeState, tuple[EpisodeEffect, ...]]:
        effects: list[EpisodeEffect] = []
        if (
            state.status == "clearing"
            and state.clear_deadline is not None
            and now >= state.clear_deadline
            and not state.clear_emitted
            and state.episode_id is not None
        ):
            effects.append(
                EpisodeEffect(
                    state.node_id,
                    state.zone,
                    state.episode_id,
                    "stable_clear",
                    state.clear_deadline,
                    self._nodes[state.node_id].reliability,
                )
            )
            state = replace(
                state,
                status="clear",
                clear_started_at=None,
                clear_deadline=None,
                traversal_valid_until=None,
                clear_emitted=True,
            )
        if (
            state.status == "asserted"
            and self._profile(state).role != "stay"
            and state.assertion_trust_until is not None
            and now >= state.assertion_trust_until
            and not state.health_warning
            and state.episode_id is not None
        ):
            effects.append(
                EpisodeEffect(
                    state.node_id,
                    state.zone,
                    state.episode_id,
                    "health_degraded",
                    state.assertion_trust_until,
                    self._nodes[state.node_id].reliability,
                )
            )
            state = replace(
                state,
                status="degraded",
                traversal_valid_until=None,
                degraded_at=state.assertion_trust_until,
                degradation_reason="assertion_timeout",
                health_warning=True,
            )
        return state, tuple(effects)
