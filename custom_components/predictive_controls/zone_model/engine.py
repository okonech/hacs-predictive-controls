"""Ordered standalone orchestration for the graph-local target model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from ..model import PredictiveMap
from .count import CountContext, apply_count_update
from .episodes import PhysicalEpisodes
from .filter import ZoneBeliefFilter
from .policy import POLICY_CALIBRATIONS, PolicyAuditLog, ZonePolicy
from .profiles import BELIEF_PROFILES, build_physical_nodes
from .traversal import TraversalFrontier
from .types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneBeliefState,
    ZoneModelResult,
    ZoneModelSnapshot,
    require_utc,
)


class ZoneModelEngine:
    """Compose target components without publishing or mutating legacy state."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        initial_count: int,
        bootstrap_at: datetime,
        *,
        active_seed: Mapping[str, bool] | None = None,
    ) -> None:
        require_utc(bootstrap_at, "Zone-model bootstrap time")
        build = build_physical_nodes(predictive_map)
        if build.errors:
            raise ValueError("; ".join(build.errors))
        if not build.nodes:  # pragma: no cover - map validation reports this first
            raise ValueError("Zone model requires at least one physical node")
        profiles_by_zone: dict[str, set[str]] = {}
        for node in build.nodes:
            profiles_by_zone.setdefault(node.zone, set()).add(node.profile_name)
        mixed = sorted(
            zone for zone, profiles in profiles_by_zone.items() if len(profiles) != 1
        )
        if mixed:
            raise ValueError(
                "Target zones require one shared profile during migration: "
                + ", ".join(mixed)
            )

        self._map = predictive_map
        self._nodes = build.nodes
        self._episodes = PhysicalEpisodes(self._nodes)
        self._filters = {
            zone: ZoneBeliefFilter(
                zone,
                BELIEF_PROFILES[next(iter(profiles))],
                bootstrap_at,
            )
            for zone, profiles in sorted(profiles_by_zone.items())
        }
        self._frontier = TraversalFrontier(predictive_map, self._nodes)
        self._count = CountContext(initial_count)
        active_seed = {} if active_seed is None else dict(active_seed)
        if not set(active_seed) <= set(self._filters) or any(
            not isinstance(active, bool) for active in active_seed.values()
        ):
            raise ValueError("Zone-model active seed is incompatible")
        self._policies = {
            zone: ZonePolicy(
                zone,
                POLICY_CALIBRATIONS[filter_.state.profile_name],
                bootstrap_at,
                active=active_seed.get(zone, False),
            )
            for zone, filter_ in self._filters.items()
        }
        self._updated_at = bootstrap_at

    @classmethod
    def restore(
        cls,
        predictive_map: PredictiveMap,
        snapshot: ZoneModelSnapshot,
        audit_rows: tuple[PolicyDecision, ...],
        restore_at: datetime,
    ) -> ZoneModelEngine:
        require_utc(restore_at, "Zone-model restore time")
        if restore_at < snapshot.updated_at:
            raise ValueError("Zone-model restore time predates stored state")
        candidate = cls(
            predictive_map,
            snapshot.count_state.expected_count,
            snapshot.updated_at,
        )
        candidate._episodes.restore_snapshot(snapshot.episode_states)
        belief_by_zone = {state.zone: state for state in snapshot.belief_states}
        policy_by_zone = {state.zone: state for state in snapshot.policy_states}
        if set(belief_by_zone) != set(candidate._filters) or set(policy_by_zone) != set(
            candidate._policies
        ):
            raise ValueError("Zone-model snapshot zones are incompatible")
        candidate._filters = {
            zone: ZoneBeliefFilter.restore(
                BELIEF_PROFILES[state.profile_name],
                state,
            )
            for zone, state in belief_by_zone.items()
        }
        candidate._frontier.restore_snapshot(
            snapshot.traversal_tokens,
            snapshot.current_token_ids,
            snapshot.authorization_uses,
            snapshot.updated_at,
        )
        candidate._count = CountContext.restore(snapshot.count_state)
        audits: dict[str, PolicyAuditLog] = {
            zone: PolicyAuditLog() for zone in candidate._policies
        }
        for row in sorted(audit_rows, key=lambda item: (item.event_at, item.zone)):
            audit = audits.get(row.zone)
            if audit is None or row.event_at > snapshot.updated_at:
                raise ValueError("Zone-model audit row is incompatible")
            audit.append(row)
        candidate._policies = {
            zone: ZonePolicy(
                zone,
                POLICY_CALIBRATIONS[state.profile_name],
                snapshot.updated_at,
                state=state,
                audit=audits[zone],
            )
            for zone, state in policy_by_zone.items()
        }
        candidate._updated_at = snapshot.updated_at
        if restore_at > snapshot.updated_at:
            candidate.advance(restore_at, processing_at=restore_at, emit_events=False)
        return candidate

    @property
    def snapshot(self) -> ZoneModelSnapshot:
        return ZoneModelSnapshot(
            self._updated_at,
            self._episodes.states,
            tuple(self._filters[zone].state for zone in sorted(self._filters)),
            self._frontier.tokens,
            self._frontier.current_token_ids,
            self._frontier.uses,
            self._count.state,
            tuple(self._policies[zone].state for zone in sorted(self._policies)),
        )

    @property
    def audit_rows(self) -> tuple[PolicyDecision, ...]:
        return tuple(
            row
            for zone in sorted(self._policies)
            for row in self._policies[zone].audit.rows
        )

    def bootstrap_sensor_snapshot(
        self,
        events: Sequence[SensorInput],
        at: datetime,
    ) -> ZoneModelSnapshot:
        """Apply raw startup states without traversal or public policy events."""

        self._validate_operation_time(at, at)
        for event in sorted(events, key=lambda item: item.entity_id):
            if event.event_at != at:
                raise ValueError("Bootstrap sensor snapshot must share one frontier")
            update = self._episodes.observe(event)
            for effect in sorted(update.effects, key=self._effect_order):
                assert effect.kind == "positive"
                self._filters[effect.zone].apply_positive(effect.episode_id, effect.at)
            if event.state in {"unknown", "unavailable"}:
                self._filters[update.state.zone].apply_unavailable(at)
        self._advance_components(at)
        self._frontier.clear(at)
        self._updated_at = at
        return self.snapshot

    def observe(
        self,
        event: SensorInput,
        *,
        processing_at: datetime | None = None,
    ) -> ZoneModelResult:
        processing_at = event.event_at if processing_at is None else processing_at
        if event.event_at < self._updated_at:
            require_utc(event.event_at, "Zone-model event time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(event.event_at, processing_at)
        pending_updates = self._episodes.advance(event.event_at)
        for effect in sorted(
            (effect for update in pending_updates for effect in update.effects),
            key=self._effect_order,
        ):
            self._advance_components(effect.at)
            state = next(
                item for item in self._episodes.states if item.node_id == effect.node_id
            )
            self._apply_effect(state, effect)
        update = self._episodes.observe(event)
        if update.disposition in {"stale", "duplicate"}:
            return ZoneModelResult(update.disposition, self.snapshot)

        effects = tuple(sorted(update.effects, key=self._effect_order))
        final_effect: EpisodeEffect | None = None
        final_authorization: TraversalAuthorization | None = None
        belief_before: ZoneBeliefState | None = None
        authorizations: list[TraversalAuthorization] = []
        for effect in effects:
            self._advance_components(effect.at)
            current_before = self._filters[effect.zone].state
            authorization = self._apply_effect(update.state, effect)
            if authorization is not None:
                authorizations.append(authorization)
            final_effect = effect
            final_authorization = authorization
            belief_before = current_before

        self._advance_components(event.event_at)
        if event.state in {"unknown", "unavailable"}:
            belief_before = self._filters[update.state.zone].state
            self._filters[update.state.zone].apply_unavailable(event.event_at)
        self._frontier.sync(update.state, event.event_at)
        decisions, policy_events = self._evaluate_policies(
            event.event_at,
            processing_at,
            update.state,
            final_effect,
            final_authorization,
            belief_before,
        )
        self._updated_at = event.event_at
        return ZoneModelResult(
            update.disposition,
            self.snapshot,
            policy_events,
            decisions,
            tuple(authorizations),
        )

    def observe_count(
        self,
        event: CountInput,
        *,
        processing_at: datetime | None = None,
    ) -> ZoneModelResult:
        processing_at = event.event_at if processing_at is None else processing_at
        if event.event_at < self._updated_at:
            require_utc(event.event_at, "Zone-model event time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(event.event_at, processing_at)
        pending_updates = self._episodes.advance(event.event_at)
        for effect in sorted(
            (effect for update in pending_updates for effect in update.effects),
            key=self._effect_order,
        ):
            self._advance_components(effect.at)
            state = next(
                item for item in self._episodes.states if item.node_id == effect.node_id
            )
            self._apply_effect(state, effect)
        self._advance_components(event.event_at)
        update = self._count.observe(event)
        if update.disposition != "accepted":
            self._updated_at = event.event_at
            return ZoneModelResult(update.disposition, self.snapshot)
        if update.categorical_zero:
            apply_count_update(update, self._filters, self._frontier)
            policy_updates = tuple(
                self._policies[zone].apply_count_zero(
                    event.event_at,
                    processing_at=processing_at,
                )
                for zone in sorted(self._policies)
            )
            decisions = tuple(item.decision for item in policy_updates)
            policy_events = tuple(
                item.event for item in policy_updates if item.event is not None
            )
        else:
            decisions, policy_events = self._evaluate_policies(
                event.event_at,
                processing_at,
                None,
                None,
                None,
                None,
            )
        self._updated_at = event.event_at
        return ZoneModelResult(
            update.disposition,
            self.snapshot,
            policy_events,
            decisions,
        )

    def advance(
        self,
        at: datetime,
        *,
        processing_at: datetime | None = None,
        emit_events: bool = True,
    ) -> ZoneModelResult:
        processing_at = at if processing_at is None else processing_at
        if at < self._updated_at:
            require_utc(at, "Zone-model advance time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(at, processing_at)
        updates = self._episodes.advance(at)
        state_by_node = {state.node_id: state for state in self._episodes.states}
        effects = sorted(
            (effect for update in updates for effect in update.effects),
            key=self._effect_order,
        )
        for effect in effects:
            self._advance_components(effect.at)
            self._apply_effect(state_by_node[effect.node_id], effect)
        belief_before_advance = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
        self._advance_components(at)
        for state in self._episodes.states:
            self._frontier.sync(state, at)
        decisions, policy_events = self._evaluate_policies(
            at,
            processing_at,
            None,
            None,
            None,
            None,
            belief_before_by_zone=belief_before_advance,
            emit_events=emit_events,
        )
        self._updated_at = at
        return ZoneModelResult(
            "advanced",
            self.snapshot,
            policy_events,
            decisions,
            (),
        )

    def _apply_effect(
        self,
        state: EpisodeState,
        effect: EpisodeEffect,
    ) -> TraversalAuthorization | None:
        filter_ = self._filters[effect.zone]
        if effect.kind == "positive":
            filter_.apply_positive(effect.episode_id, effect.at)
            self._frontier.issue(state, effect)
            authorization = self._frontier.authorize(
                state,
                effect.at,
                count=self._count.state,
                corroborating_states=self._episodes.states,
            )
            TraversalFrontier.apply_outward_context(
                authorization,
                self._filters,
                effect.at,
                state.traversal_valid_until,
            )
            return authorization
        if effect.kind == "stable_clear":
            filter_.apply_stable_clear(effect.episode_id, effect.at)
        elif effect.kind == "health_degraded":
            filter_.apply_health_degraded(effect.episode_id, effect.at)
        else:
            assert effect.kind == "health_recovered"
            filter_.apply_health_recovered(effect.episode_id, effect.at)
        self._frontier.sync(state, effect.at)
        return None

    def _advance_components(self, at: datetime) -> None:
        for filter_ in self._filters.values():
            filter_.advance(at)
        self._frontier.advance(at)

    def _evaluate_policies(
        self,
        at: datetime,
        processing_at: datetime,
        local_state: EpisodeState | None,
        local_effect: EpisodeEffect | None,
        authorization: TraversalAuthorization | None,
        belief_before: ZoneBeliefState | None,
        *,
        belief_before_by_zone: Mapping[str, ZoneBeliefState] | None = None,
        emit_events: bool = True,
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        decisions: list[PolicyDecision] = []
        events: list[PolicyEvent] = []
        for zone in sorted(self._policies):
            belief_after = self._filters[zone].state
            before = (
                belief_before_by_zone[zone]
                if belief_before_by_zone is not None
                else belief_before
                if belief_before is not None and belief_before.zone == zone
                else belief_after
            )
            state = (
                local_state
                if local_state is not None and local_state.zone == zone
                else None
            )
            effect = local_effect if state is not None else None
            candidate_authorization = authorization if state is not None else None
            calibration = POLICY_CALIBRATIONS[belief_after.profile_name]
            below_since = self._filters[zone].threshold_crossed_at(
                before,
                calibration.off_threshold,
                at,
            )
            update = self._policies[zone].evaluate(
                at,
                before,
                belief_after,
                local_state=state,
                local_effect=effect,
                authorization=candidate_authorization,
                processing_at=processing_at,
                emit_event=emit_events,
                below_threshold_since=below_since,
            )
            decisions.append(update.decision)
            if update.event is not None:
                events.append(update.event)
        return tuple(decisions), tuple(events)

    def _validate_operation_time(
        self,
        event_at: datetime,
        processing_at: datetime,
    ) -> None:
        require_utc(event_at, "Zone-model event time")
        require_utc(processing_at, "Zone-model processing time")
        if processing_at < event_at:
            raise ValueError("Zone-model processing time cannot precede event time")

    @staticmethod
    def _effect_order(effect: EpisodeEffect) -> tuple[datetime, str, str]:
        return effect.at, effect.node_id, effect.kind


__all__ = ["ZoneModelEngine"]
