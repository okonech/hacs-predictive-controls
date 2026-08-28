"""Ordered standalone orchestration for the graph-local target model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from ..const import PRODUCT_MAX_OCCUPANTS
from ..model import PredictiveMap
from .count import (
    SEEN_EVENT_LIMIT,
    CountConflictTracker,
    CountContext,
    apply_count_update,
)
from .episodes import PhysicalEpisodes
from .filter import ZoneBeliefFilter
from .policy import (
    POLICY_CALIBRATIONS,
    REFRESH_RETENTION,
    PolicyAuditLog,
    ZonePolicy,
)
from .prediction import PredictionLease, TargetPredictionManager
from .profiles import (
    BELIEF_PROFILES,
    ENTRY_BOUNDARY,
    SHARED_PROFILES,
    build_physical_nodes,
)
from .supports import AnonymousSupportTracker
from .traversal import TraversalFrontier
from .types import (
    CountInput,
    CountSupport,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    ReliabilityWarningOccurrence,
    SensorInput,
    SupportTransitionEvent,
    TraversalAuthorization,
    TraversalToken,
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
        self._supports = AnonymousSupportTracker(predictive_map, self._nodes)
        self._predictions = TargetPredictionManager(predictive_map)
        self._pending_prediction_learning: list[TraversalAuthorization] = []
        self._count = CountContext(initial_count)
        self._count_conflicts = CountConflictTracker()
        self._reliability_warning_occurrences: dict[
            tuple[str, str], ReliabilityWarningOccurrence
        ] = {}
        active_seed = {} if active_seed is None else dict(active_seed)
        if not set(active_seed) <= set(self._filters) or any(
            not isinstance(active, bool) for active in active_seed.values()
        ):
            raise ValueError("Zone-model active seed is incompatible")
        if initial_count == 0:
            active_seed = {}
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
        candidate._validate_snapshot_integrity(snapshot)
        candidate._reliability_warning_occurrences = {
            (item.node_id, item.reason): item
            for item in snapshot.reliability_warning_occurrences
        }
        if snapshot.count_state.expected_count == 0 and any(
            state.active for state in policy_by_zone.values()
        ):
            raise ValueError("Zero-count snapshot cannot restore active zones")
        if snapshot.count_state.expected_count == 0:
            candidate._validate_zero_count_snapshot(snapshot)
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
            snapshot.pending_candidates,
            snapshot.retained_traversal_tokens,
        )
        candidate._supports.restore(
            snapshot.anonymous_supports,
            snapshot.support_token_bindings,
            snapshot.updated_at,
        )
        candidate._count = CountContext.restore(snapshot.count_state)
        candidate._count_conflicts.restore(
            snapshot.count_conflicts,
            snapshot.count_state.expected_count,
        )
        audits: dict[str, PolicyAuditLog] = {
            zone: PolicyAuditLog() for zone in candidate._policies
        }
        episodes = {state.node_id: state for state in snapshot.episode_states}
        for row in sorted(audit_rows, key=lambda item: (item.event_at, item.zone)):
            audit = audits.get(row.zone)
            if audit is None or row.event_at > snapshot.updated_at:
                raise ValueError("Zone-model audit row is incompatible")
            candidate._validate_interaction_audit(
                row,
                episodes,
                snapshot.updated_at,
            )
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
            self._frontier.pending_candidates,
            self._count_conflicts.conflicts,
            self._frontier.retained_tokens,
            self._supports.supports,
            self._supports.bindings,
            tuple(
                self._reliability_warning_occurrences[key]
                for key in sorted(self._reliability_warning_occurrences)
            ),
        )

    @property
    def audit_rows(self) -> tuple[PolicyDecision, ...]:
        return tuple(
            row
            for zone in sorted(self._policies)
            for row in self._policies[zone].audit.rows
        )

    @property
    def latest_support_transition(self) -> SupportTransitionEvent | None:
        return self._supports.latest_transition

    @property
    def diagnostic_counters(self) -> dict[str, int]:
        return {
            **self._supports.counters,
            **self._count_conflicts.counters,
        }

    @property
    def prediction_manager(self) -> TargetPredictionManager:
        return self._predictions

    def commit_prediction_learning(self) -> None:
        """Commit queued confirmed route observations after publication."""

        pending = tuple(self._pending_prediction_learning)
        self._pending_prediction_learning.clear()
        self._predictions.commit(pending)

    def restore_prediction_state(self, payload: object, at: datetime) -> None:
        """Install validated route statistics and unexpired leases atomically."""

        candidate = TargetPredictionManager.restored(self._map, payload, at)
        if self._count.state.expected_count == 0 and candidate.leases:
            raise ValueError("Zero-count state cannot restore prediction leases")
        self._validate_prediction_consistency(candidate)
        self._predictions = candidate

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
            if self._count.state.expected_count > 0:
                for effect in sorted(update.effects, key=self._effect_order):
                    assert effect.kind == "positive"
                    self._filters[effect.zone].apply_positive(
                        effect.episode_id, effect.at, effect.reliability
                    )
                if event.state in {"unknown", "unavailable"}:
                    self._reconcile_zone_availability(update.state.zone, at)
        self._advance_components(at)
        self._frontier.clear(at)
        self._supports.clear(at, "bootstrap")
        self._predictions.clear()
        if self._count.state.expected_count == 0:
            for filter_ in self._filters.values():
                filter_.apply_empty_baseline(at)
        self._updated_at = at
        return self.snapshot

    def reconcile_restored_asserted_contexts(
        self,
        events: Sequence[SensorInput],
        at: datetime,
    ) -> ZoneModelSnapshot:
        """Reconcile current raw-on levels with matching restored assertions."""

        self._validate_operation_time(at, at)
        if any(event.event_at != at for event in events):
            raise ValueError("Restore sensor snapshot must share one frontier")
        if at > self._updated_at:
            self.advance(at, processing_at=at, emit_events=False)
        if self._count.state.expected_count == 0:
            return self.snapshot

        current_on_entities = frozenset(
            event.entity_id for event in events if event.state == "on"
        )
        eligible_node_ids = frozenset(
            node.node_id
            for node in self._nodes
            if any(
                alias in current_on_entities
                for alias in set(node.aliases) - set(node.interaction_aliases)
            )
        )
        if not eligible_node_ids:
            return self.snapshot
        for zone in sorted(self._filters):
            selected = self._select_asserted_context(zone, eligible_node_ids)
            if selected is None:
                continue
            assert selected.episode_id is not None
            self._filters[zone].reselect_asserted_context(selected.episode_id, at)
        return self.snapshot

    def observe(
        self,
        event: SensorInput,
        *,
        processing_at: datetime | None = None,
        decision_callback: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> ZoneModelResult:
        """Observe one input with audit deferred across a public handoff."""

        if decision_callback is None:
            return self._observe(event, processing_at=processing_at)
        audits = tuple(policy.audit for policy in self._policies.values())
        for audit in audits:
            audit.begin_defer()
        callback_failure: Exception | None = None
        learning_frontier = len(self._pending_prediction_learning)

        def safe_callback(
            policy_event: PolicyEvent,
            decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            nonlocal callback_failure
            if callback_failure is not None:
                return
            try:
                decision_callback(policy_event, decision, authorization)
            except Exception as exc:  # publication failure is reported after commit
                callback_failure = exc

        try:
            result = self._observe(
                event,
                processing_at=processing_at,
                decision_callback=safe_callback,
            )
        except Exception:
            for audit in audits:
                audit.discard_deferred()
            del self._pending_prediction_learning[learning_frontier:]
            raise
        for audit in audits:
            audit.flush_deferred()
        if callback_failure is not None:
            del self._pending_prediction_learning[learning_frontier:]
            raise callback_failure
        return result

    def _observe(
        self,
        event: SensorInput,
        *,
        processing_at: datetime | None = None,
        decision_callback: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> ZoneModelResult:
        processing_at = event.event_at if processing_at is None else processing_at
        if event.event_at < self._updated_at:
            require_utc(event.event_at, "Zone-model event time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(event.event_at, processing_at)
        if self._count.state.expected_count == 0:
            return self._observe_empty_house(event, processing_at)
        operation_beliefs = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
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
            self._advance_supports(effect.at)
        self._advance_components(event.event_at)
        deadline_decisions, deadline_events = self._release_due_policies(
            event.event_at,
            processing_at,
            operation_beliefs,
        )
        # An external clear arriving exactly at a count-conflict deadline must
        # not erase the asserted episode before its health diagnosis. Positive
        # acquisition events defer this whole-house work until after the local
        # publication callback.
        if event.state not in {"on", "pressed"}:
            self._apply_count_conflicts(event.event_at)
        update = self._episodes.observe(event)
        if update.disposition in {"stale", "duplicate"}:
            pending_expiry_decisions = self._record_pending_expiries(
                event.event_at, processing_at
            )
            self._apply_count_conflicts(event.event_at)
            self._updated_at = event.event_at
            return ZoneModelResult(
                update.disposition,
                self.snapshot,
                deadline_events,
                (*pending_expiry_decisions, *deadline_decisions),
            )

        recovered_conflicts = tuple(
            conflict
            for conflict in self._count_conflicts.conflicts
            if conflict.target_node_id == update.state.node_id
            and any(effect.kind == "health_recovered" for effect in update.effects)
        )

        effects = tuple(sorted(update.effects, key=self._effect_order))
        final_effect: EpisodeEffect | None = None
        final_authorization: TraversalAuthorization | None = None
        final_token: TraversalToken | None = None
        belief_before: ZoneBeliefState | None = None
        authorizations: list[TraversalAuthorization] = []
        source_authorizations: list[TraversalAuthorization] = []
        for effect in effects:
            self._advance_components(effect.at)
            current_before = self._filters[effect.zone].state
            authorization, applied_effect, issued_token = self._apply_effect(
                update.state, effect
            )
            if authorization is not None:
                authorizations.append(authorization)
                if (
                    authorization.authorized
                    and effect.kind in {"interaction", "positive"}
                ):
                    source_authorizations.append(authorization)
            final_effect = applied_effect
            final_authorization = authorization
            final_token = issued_token
            belief_before = current_before

        self._advance_components(event.event_at)
        if event.state in {"unknown", "unavailable"}:
            belief_before = self._filters[update.state.zone].state
            self._reconcile_zone_availability(update.state.zone, event.event_at)
        elif update.disposition == "baseline_clear":
            belief_before = self._filters[update.state.zone].state
            self._filters[update.state.zone].apply_availability_clear(
                update.state.episode_id,
                event.event_at,
            )
        self._frontier.sync(update.state, event.event_at)
        prediction_leases = self._prepare_predictions(
            event.event_at, tuple(source_authorizations)
        )
        decisions, policy_events = self._evaluate_policies(
            event.event_at,
            processing_at,
            update.state,
            final_effect,
            final_authorization,
            belief_before,
            prediction_leases=prediction_leases,
            decision_callback=decision_callback,
        )
        support_effect = (
            None
            if final_effect is not None
            and final_effect.kind == "correlated_positive"
            else final_effect
        )
        support_authorization = (
            None if support_effect is None else final_authorization
        )
        support_token = None if support_effect is None else final_token
        self._supports.apply(
            event.event_at,
            support_effect,
            support_authorization,
            support_token,
            self._episodes.states,
            tuple(self._filters[zone].state for zone in sorted(self._filters)),
            self._frontier.tokens,
            self._frontier.retained_tokens,
        )
        pending_expiry_decisions = self._record_pending_expiries(
            event.event_at, processing_at
        )
        self._apply_count_conflicts(
            event.event_at,
            local_effect=final_effect,
            authorization=final_authorization,
        )
        for conflict in recovered_conflicts:
            self._policies[update.state.zone].record_count_conflict(
                conflict,
                update.state,
                self._filters[update.state.zone].state,
                result="recovered",
                at=event.event_at,
                processing_at=processing_at,
            )
        self._updated_at = event.event_at
        return ZoneModelResult(
            update.disposition,
            self.snapshot,
            (*deadline_events, *policy_events),
            (*pending_expiry_decisions, *deadline_decisions, *decisions),
            tuple(authorizations),
        )

    def _select_asserted_context(
        self,
        zone: str,
        eligible_node_ids: frozenset[str] | None = None,
    ) -> EpisodeState | None:
        candidates = tuple(
            state
            for state in self._episodes.states
            if state.zone == zone
            and state.episode_id is not None
            and state.last_event_at is not None
            and state.known_on
            and state.status == "asserted"
            and not state.health_warning
            and (
                eligible_node_ids is None or state.node_id in eligible_node_ids
            )
        )
        if not candidates:
            return None

        def selection_key(state: EpisodeState) -> tuple[datetime, str, str]:
            assert state.last_event_at is not None
            assert state.episode_id is not None
            return state.last_event_at, state.node_id, state.episode_id

        return max(candidates, key=selection_key)

    def _reconcile_zone_availability(
        self,
        zone: str,
        at: datetime,
        eligible_node_ids: frozenset[str] | None = None,
    ) -> None:
        selected = self._select_asserted_context(zone, eligible_node_ids)
        if selected is None:
            self._filters[zone].apply_unavailable(at)
            return
        assert selected.episode_id is not None
        self._filters[zone].reselect_asserted_context(selected.episode_id, at)

    def _observe_empty_house(
        self,
        event: SensorInput,
        processing_at: datetime,
    ) -> ZoneModelResult:
        """Retain sensor health state while count zero suppresses all inference."""

        self._episodes.advance(event.event_at)
        update = self._episodes.observe(event)
        for filter_ in self._filters.values():
            filter_.apply_empty_baseline(event.event_at)
        self._frontier.clear(event.event_at)
        self._predictions.clear()
        self._pending_prediction_learning.clear()
        self._count_conflicts.clear()
        self._supports.clear(event.event_at)
        policy_updates = tuple(
            self._policies[zone].apply_count_zero(
                event.event_at,
                processing_at=processing_at,
            )
            for zone in sorted(self._policies)
        )
        self._updated_at = event.event_at
        return ZoneModelResult(
            update.disposition,
            self.snapshot,
            tuple(item.event for item in policy_updates if item.event is not None),
            tuple(item.decision for item in policy_updates),
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
        operation_beliefs = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
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
            self._advance_supports(effect.at)
        self._advance_components(event.event_at)
        pending_expiry_decisions = self._record_pending_expiries(
            event.event_at, processing_at
        )
        self._apply_count_conflicts(event.event_at)
        deadline_decisions, deadline_events = self._release_due_policies(
            event.event_at,
            processing_at,
            operation_beliefs,
        )
        update = self._count.observe(event)
        if update.disposition != "accepted":
            self._updated_at = event.event_at
            return ZoneModelResult(
                update.disposition,
                self.snapshot,
                deadline_events,
                (*pending_expiry_decisions, *deadline_decisions),
            )
        if update.categorical_zero:
            cadence_resets = self._episodes.reset_cadence(event.event_at)
            for reset in cadence_resets:
                for effect in reset.effects:
                    self._apply_effect(reset.state, effect)
            apply_count_update(update, self._filters, self._frontier)
            self._count_conflicts.clear()
            self._supports.clear(event.event_at)
            self._pending_prediction_learning.clear()
            self._prepare_predictions(event.event_at, ())
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
            self._apply_count_conflicts(event.event_at)
            prediction_leases = self._prepare_predictions(event.event_at, ())
            decisions, policy_events = self._evaluate_policies(
                event.event_at,
                processing_at,
                None,
                None,
                None,
                None,
                prediction_leases=prediction_leases,
            )
        self._updated_at = event.event_at
        return ZoneModelResult(
            update.disposition,
            self.snapshot,
            (*deadline_events, *policy_events),
            (*pending_expiry_decisions, *deadline_decisions, *decisions),
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
            self._advance_supports(effect.at)
        belief_before_advance = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
        self._advance_components(at)
        for state in self._episodes.states:
            self._frontier.sync(state, at)
        pending_expiry_decisions = self._record_pending_expiries(at, processing_at)
        self._apply_count_conflicts(at)
        prediction_leases = self._prepare_predictions(at, ())
        decisions, policy_events = self._evaluate_policies(
            at,
            processing_at,
            None,
            None,
            None,
            None,
            belief_before_by_zone=belief_before_advance,
            emit_events=emit_events,
            prediction_leases=prediction_leases,
        )
        self._updated_at = at
        return ZoneModelResult(
            "advanced",
            self.snapshot,
            policy_events,
            (*pending_expiry_decisions, *decisions),
            (),
        )

    def _apply_effect(
        self,
        state: EpisodeState,
        effect: EpisodeEffect,
    ) -> tuple[
        TraversalAuthorization | None,
        EpisodeEffect,
        TraversalToken | None,
    ]:
        filter_ = self._filters[effect.zone]
        token: TraversalToken | None
        if effect.kind == "interaction":
            filter_.apply_interaction(effect.episode_id, effect.at)
            authorization = self._frontier.authorize_interaction(state, effect.at)
            token = self._frontier.issue(state, effect, authorization)
            return authorization, effect, token
        if effect.kind == "positive":
            filter_.apply_positive(effect.episode_id, effect.at, effect.reliability)
            authorization = self._frontier.authorize(
                state,
                effect.at,
                count=self._count.state,
                corroborating_states=self._episodes.states,
            )
            if authorization.authorized:
                filter_.apply_arrival_transition(effect.episode_id, effect.at)
                token = self._frontier.issue(state, effect, authorization)
            else:
                token = None
            TraversalFrontier.apply_outward_context(
                authorization,
                self._filters,
                effect.at,
                state.traversal_valid_until,
            )
            return authorization, effect, token
        if effect.kind == "correlated_positive":
            filter_.apply_correlated_positive(
                effect.episode_id,
                effect.at,
                effect.reliability,
            )
            authorization = self._frontier.authorize_correlated_target(
                state,
                effect.at,
            )
            if authorization.authorized:
                filter_.apply_arrival_transition(effect.episode_id, effect.at)
            return authorization, effect, None
        if effect.kind == "correlated_flap_ignored":
            if self._frontier.reopen_authorized_continuity(state, effect):
                effect = replace(effect, kind="correlated_continuity_authorized")
                filter_.supersede_outward(effect.episode_id, effect.at)
            else:
                self._frontier.sync(state, effect.at)
            return None, effect, None
        if effect.kind in {
            "cadence_warning_cleared",
            "impossible_cadence",
            "sustained_flapping",
        }:
            self._apply_warning_effect(effect)
            self._frontier.sync(state, effect.at)
            return None, effect, None
        if effect.kind == "stable_clear":
            if filter_.state.generation_episode_id == effect.episode_id:
                filter_.apply_stable_clear(
                    effect.episode_id, effect.at, effect.reliability
                )
        elif effect.kind == "health_degraded":
            filter_.apply_health_degraded(effect.episode_id, effect.at)
            self._apply_warning_effect(effect)
        else:
            assert effect.kind == "health_recovered"
            filter_.apply_health_recovered(effect.episode_id, effect.at)
            self._apply_warning_effect(effect)
        self._frontier.sync(state, effect.at)
        return None, effect, None

    def _apply_warning_effect(self, effect: EpisodeEffect) -> None:
        reason = effect.warning_reason
        assert reason is not None
        key = (effect.node_id, reason)
        current = self._reliability_warning_occurrences.get(key)
        if effect.kind in {
            "health_degraded",
            "impossible_cadence",
            "sustained_flapping",
        }:
            kind = (
                "flapping"
                if reason in {"impossible_cadence", "sustained_flapping"}
                else "suspected_stuck"
            )
            first_observed_at = (
                current.first_observed_at
                if current is not None and current.cleared_at is None
                else effect.at
            )
            self._reliability_warning_occurrences[key] = (
                ReliabilityWarningOccurrence(
                    effect.node_id,
                    effect.zone,
                    kind,
                    reason,
                    first_observed_at,
                    effect.at,
                )
            )
            return
        assert effect.kind in {"cadence_warning_cleared", "health_recovered"}
        if current is None or current.cleared_at is not None:
            raise ValueError("Reliability warning clear has no active occurrence")
        self._reliability_warning_occurrences[key] = replace(
            current,
            last_observed_at=effect.at,
            cleared_at=effect.at,
        )

    def _advance_components(self, at: datetime) -> None:
        for filter_ in self._filters.values():
            filter_.advance(at)
        self._frontier.advance(at)
        self._advance_supports(at)

    def _advance_supports(self, at: datetime) -> None:
        self._supports.advance(
            at,
            self._episodes.states,
            tuple(self._filters[zone].state for zone in sorted(self._filters)),
            self._frontier.tokens,
            self._frontier.retained_tokens,
        )

    def _prepare_predictions(
        self,
        at: datetime,
        authorizations: tuple[TraversalAuthorization, ...],
    ) -> tuple[PredictionLease, ...]:
        leases = self._predictions.prepare(
            at,
            self._count.state.expected_count,
            self._episodes.states,
            authorizations,
        )
        self._pending_prediction_learning.extend(
            authorization
            for authorization in authorizations
            if authorization.track_confidence == "confirmed"
            and self._policies[authorization.target_zone].state.phase
            != "predicted"
        )
        return leases

    def _record_pending_expiries(
        self,
        at: datetime,
        processing_at: datetime,
    ) -> tuple[PolicyDecision, ...]:
        return tuple(
            self._policies[candidate.zone].record_pending_expiry(
                candidate,
                self._filters[candidate.zone].state,
                at=at,
                processing_at=processing_at,
            )
            for candidate in self._frontier.take_expired_pending()
        )

    def _apply_count_conflicts(
        self,
        at: datetime,
        *,
        local_effect: EpisodeEffect | None = None,
        authorization: TraversalAuthorization | None = None,
    ) -> None:
        previous = {
            conflict.target_node_id: conflict
            for conflict in self._count_conflicts.conflicts
            if conflict.degraded_at is not None
        }
        release_dwells = {
            zone: POLICY_CALIBRATIONS[filter_.state.profile_name].release_dwell
            for zone, filter_ in self._filters.items()
        }
        crossed = self._count_conflicts.evaluate(
            at,
            self._count.state.expected_count,
            self._nodes,
            self._episodes.states,
            self._supports.count_supports(),
            release_dwells,
            local_effect=local_effect,
            authorization=authorization,
        )
        current = {
            conflict.target_node_id: conflict
            for conflict in self._count_conflicts.conflicts
        }
        episode_by_node = {
            state.node_id: state for state in self._episodes.states
        }
        for node_id, conflict in previous.items():
            retained = current.get(node_id)
            if (
                retained is not None
                and retained.target_episode_id == conflict.target_episode_id
                and retained.support_ids == conflict.support_ids
                and retained.degraded_at is not None
            ):
                continue
            state = episode_by_node[node_id]
            if (
                state.episode_id == conflict.target_episode_id
                and state.status == "clear"
                and not state.health_warning
                and state.degradation_reason is None
            ):
                self._policies[state.zone].record_count_conflict(
                    conflict,
                    state,
                    self._filters[state.zone].state,
                    result="recovered",
                    at=at,
                    processing_at=at,
                )
                continue
            if (
                state.episode_id != conflict.target_episode_id
                or state.status != "degraded"
                or state.degradation_reason != "count_conflict"
            ):
                continue
            update = self._episodes.recover_count_conflict(
                conflict.target_node_id,
                conflict.target_episode_id,
                at,
            )
            effect = update.effects[0]
            self._filters[effect.zone].apply_health_recovered(
                effect.episode_id, effect.at
            )
            self._apply_warning_effect(effect)
            self._frontier.sync(update.state, at)
            self._policies[update.state.zone].record_count_conflict(
                conflict,
                update.state,
                self._filters[update.state.zone].state,
                result="recovered",
                at=at,
                processing_at=at,
            )
        for conflict in crossed:
            update = self._episodes.apply_count_conflict(
                conflict.target_node_id,
                conflict.target_episode_id,
                at,
            )
            effect = update.effects[0]
            self._filters[effect.zone].apply_health_degraded(
                effect.episode_id, effect.at
            )
            self._apply_warning_effect(effect)
            self._frontier.sync(update.state, at)
            self._policies[update.state.zone].record_count_conflict(
                conflict,
                update.state,
                self._filters[update.state.zone].state,
                result="degraded",
                at=at,
                processing_at=at,
            )

    def _release_due_policies(
        self,
        at: datetime,
        processing_at: datetime,
        belief_before_by_zone: Mapping[str, ZoneBeliefState],
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        """Advance normal release deadlines before an external input at ``at``."""

        decisions: list[PolicyDecision] = []
        events: list[PolicyEvent] = []
        asserted_stay_holds = self._asserted_stay_hold_zones()
        for zone in sorted(self._policies):
            policy = self._policies[zone]
            if not policy.state.active or policy.state.phase != "active":
                continue
            belief_after = self._filters[zone].state
            if zone in asserted_stay_holds:
                if policy.state.pending_release_since is not None:
                    update = policy.evaluate(
                        at,
                        belief_before_by_zone[zone],
                        belief_after,
                        local_state=None,
                        local_effect=None,
                        authorization=None,
                        processing_at=processing_at,
                        asserted_stay_hold=True,
                    )
                    decisions.append(update.decision)
                continue
            calibration = POLICY_CALIBRATIONS[belief_after.profile_name]
            if belief_after.probability > calibration.off_threshold:
                continue
            below_since = self._filters[zone].threshold_crossed_at(
                belief_before_by_zone[zone],
                calibration.off_threshold,
                at,
            )
            pending = policy.state.pending_release_since or below_since
            if pending is None or at < pending + calibration.release_dwell:
                continue
            update = policy.evaluate(
                at,
                belief_before_by_zone[zone],
                belief_after,
                local_state=None,
                local_effect=None,
                authorization=None,
                processing_at=processing_at,
                below_threshold_since=below_since,
            )
            decisions.append(update.decision)
            assert update.event is not None
            events.append(update.event)
        return tuple(decisions), tuple(events)

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
        prediction_leases: tuple[PredictionLease, ...] = (),
        decision_callback: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        decisions: list[PolicyDecision] = []
        events: list[PolicyEvent] = []
        pending_by_zone = {
            candidate.zone: candidate
            for candidate in self._frontier.pending_candidates
        }
        prediction_by_zone = {
            lease.target_zone: lease
            for lease in sorted(
                prediction_leases,
                key=lambda item: (
                    item.target_zone,
                    item.probability,
                    item.support,
                    item.target_node_id,
                ),
            )
        }
        asserted_stay_holds = self._asserted_stay_hold_zones()
        priority_zones = set(prediction_by_zone)
        if local_state is not None:
            priority_zones.add(local_state.zone)
        ordered_zones = sorted(
            self._policies,
            key=lambda zone: (zone not in priority_zones, zone),
        )
        for zone in ordered_zones:
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
            expiry = self._policies[zone].expire_prediction(
                at,
                belief_after,
                processing_at=processing_at,
                emit_event=emit_events,
                force=bool(
                    state is None
                    and self._policies[zone].state.phase == "predicted"
                    and not any(
                        lease.mature
                        and lease.target_zone == zone
                        and lease.source_episode_id
                        == self._policies[zone].state.prediction_source_episode_id
                        and lease.expires_at
                        == self._policies[zone].state.prediction_expires_at
                        and lease.probability
                        == self._policies[zone].state.prediction_probability
                        and lease.support
                        == self._policies[zone].state.prediction_support
                        for lease in self._predictions.leases
                    )
                ),
            )
            if expiry is not None:
                decisions.append(expiry.decision)
                if expiry.event is not None:
                    events.append(expiry.event)
                if state is None:
                    continue
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
                pending_candidate=pending_by_zone.get(zone),
                asserted_stay_hold=zone in asserted_stay_holds,
                before_audit=decision_callback,
            )
            decisions.append(update.decision)
            if update.event is not None:
                events.append(update.event)
            lease = prediction_by_zone.get(zone)
            if lease is not None:
                prediction = self._policies[zone].apply_prediction(
                    lease,
                    belief_after,
                    processing_at=processing_at,
                    emit_event=emit_events,
                    before_audit=decision_callback,
                )
                if prediction is not None:
                    decisions.append(prediction.decision)
                    if prediction.event is not None:
                        events.append(prediction.event)
        return tuple(decisions), tuple(events)

    def _asserted_stay_hold_zones(self) -> frozenset[str]:
        return frozenset(
            state.zone
            for state in self._episodes.states
            if SHARED_PROFILES[state.profile_name].role == "stay"
            and (
                (
                    state.status in {"degraded", "clearing"}
                    and state.health_warning
                    and state.degradation_reason == "count_conflict"
                )
                or (
                    state.status in {"asserted", "clearing"}
                    and state.cadence_correlated
                )
            )
        )

    def _validate_operation_time(
        self,
        event_at: datetime,
        processing_at: datetime,
    ) -> None:
        require_utc(event_at, "Zone-model event time")
        require_utc(processing_at, "Zone-model processing time")
        if processing_at < event_at:
            raise ValueError("Zone-model processing time cannot precede event time")

    def _validate_interaction_audit(
        self,
        row: PolicyDecision,
        episodes: Mapping[str, EpisodeState],
        frontier: datetime,
    ) -> None:
        interaction_evidence = row.local_evidence_kind == "interaction"
        interaction_traversal = row.traversal_reason == "local_interaction"
        if interaction_evidence != interaction_traversal:
            raise ValueError("Interaction audit provenance is inconsistent")
        if not interaction_evidence:
            return
        if row.node_id is None or row.episode_id is None:
            raise ValueError("Interaction audit identity is incomplete")
        state, created_at = self._episode_reference(
            row.episode_id,
            episodes,
            frontier,
            exact=False,
        )
        node = next(item for item in self._nodes if item.node_id == state.node_id)
        if (
            state.node_id != row.node_id
            or state.zone != row.zone
            or not node.interaction_aliases
            or node.reliability != 1.0
            or row.event_at != created_at
            or not row.local_trustworthy
            or not row.authorization_authorized
            or row.episode_id not in row.evidence_ids
        ):
            raise ValueError("Interaction audit is not episode-derived")

    def _validate_snapshot_integrity(self, snapshot: ZoneModelSnapshot) -> None:
        """Validate cross-component links and frontiers before installing state."""

        at = snapshot.updated_at
        episodes = {state.node_id: state for state in snapshot.episode_states}
        physical_nodes = {node.node_id: node for node in self._nodes}
        active_occurrences: set[tuple[str, str]] = set()
        for occurrence in snapshot.reliability_warning_occurrences:
            physical_node = physical_nodes.get(occurrence.node_id)
            if (
                physical_node is None
                or physical_node.zone != occurrence.zone
                or occurrence.last_observed_at > at
            ):
                raise ValueError("Reliability warning occurrence is incompatible")
            if occurrence.cleared_at is not None:
                continue
            state = episodes[occurrence.node_id]
            if occurrence.reason in {
                "impossible_cadence",
                "sustained_flapping",
            }:
                agrees = (
                    state.cadence_warning
                    and state.cadence_warning_reason == occurrence.reason
                )
            else:
                agrees = (
                    state.health_warning
                    and state.degradation_reason == occurrence.reason
                )
            if not agrees:
                raise ValueError("Active reliability warning occurrence is stale")
            active_occurrences.add((occurrence.node_id, occurrence.reason))
        for state in snapshot.episode_states:
            historical_frontiers = (
                state.started_at,
                state.last_event_at,
                state.advanced_at,
                state.clear_started_at,
                state.degraded_at,
            )
            if any(value is not None and value > at for value in historical_frontiers):
                raise ValueError("Episode snapshot is newer than its model frontier")
            current_reasons = tuple(
                reason
                for reason in (
                    state.cadence_warning_reason,
                    state.degradation_reason if state.health_warning else None,
                )
                if reason is not None
            )
            if any(
                (state.node_id, reason) not in active_occurrences
                for reason in current_reasons
            ):
                raise ValueError("Current reliability warning occurrence is missing")

        for belief in snapshot.belief_states:
            if belief.last_updated_at > at:
                raise ValueError("Belief snapshot is newer than its model frontier")
            if belief.generation_episode_id is not None:
                state, _created_at = self._episode_reference(
                    belief.generation_episode_id,
                    episodes,
                    at,
                    exact=True,
                )
                if state.zone != belief.zone:
                    raise ValueError("Belief snapshot episode is zone-incompatible")
            for contribution in belief.contributions:
                if contribution.episode_id is None:
                    if contribution.kind == "local_interaction":
                        raise ValueError(
                            "Interaction belief contribution has no episode"
                        )
                    continue
                source, created_at = self._episode_reference(
                    contribution.episode_id,
                    episodes,
                    at,
                    exact=False,
                )
                interaction_source = bool(
                    physical_nodes[source.node_id].interaction_aliases
                )
                if contribution.kind == "local_interaction" and (
                    not interaction_source
                    or source.zone != belief.zone
                    or contribution.at != created_at
                ):
                    raise ValueError(
                        "Interaction belief contribution is not episode-derived"
                    )
                if interaction_source and contribution.kind in {
                    "arrival_transition",
                    "local_positive",
                }:
                    raise ValueError(
                        "Interaction episode retains ordinary positive belief"
                    )

        for policy in snapshot.policy_states:
            if policy.last_evaluated_at > at:
                raise ValueError("Policy snapshot is newer than its model frontier")
            for entry in policy.refresh_dedup:
                state, created_at = self._episode_reference(
                    entry.episode_id,
                    episodes,
                    at,
                    exact=False,
                )
                if (
                    entry.expires_at != entry.published_at + REFRESH_RETENTION
                    or state.zone != policy.zone
                    or created_at > entry.published_at
                ):
                    raise ValueError(
                        "Refresh deduplication entry is not episode-derived"
                    )
            if policy.phase == "active" and policy.activation_provenance == "evidence":
                assert policy.activation_episode_id is not None
                assert policy.activation_at is not None
                assert policy.activation_reason is not None
                assert policy.activation_provenance_kind is not None
                state, created_at = self._episode_reference(
                    policy.activation_episode_id,
                    episodes,
                    at,
                    exact=False,
                )
                physical_node = physical_nodes[state.node_id]
                interaction_episode = bool(physical_node.interaction_aliases)
                expected_provenance = {
                    "adjacent_authorized": "adjacent",
                    "boundary_authorized": "boundary",
                    "local_interaction": "local_interaction",
                    "missed_edge_authorized": "missed_edge",
                    "prediction_confirmed": "prediction_confirmation",
                    "provisional_track_acquired": "adjacent_pair",
                    "same_zone_authorized": "same_zone",
                    "track_confirmed": "adjacent",
                }[policy.activation_reason]
                source_states = tuple(
                    self._episode_reference(
                        episode_id,
                        episodes,
                        at,
                        exact=False,
                    )[0]
                    for episode_id in policy.activation_source_episode_ids
                )
                path = policy.activation_path_node_ids
                source_nodes = {source.node_id for source in source_states}
                requires_source = policy.activation_reason not in {
                    "boundary_authorized",
                    "local_interaction",
                    "prediction_confirmed",
                }
                if interaction_episode != (
                    policy.activation_reason == "local_interaction"
                ):
                    raise ValueError("Interaction policy provenance is incompatible")
                if (
                    state.zone != policy.zone
                    or created_at != policy.activation_at
                    or policy.activation_provenance_kind != expected_provenance
                    or path[-1] != state.node_id
                    or any(node_id not in self._map.nodes for node_id in path)
                    or any(
                        not self._bounded_path_step(left, right)
                        for left, right in zip(path, path[1:], strict=False)
                    )
                    or (requires_source and not source_nodes)
                    or (
                        requires_source
                        and not source_nodes.intersection(path[:-1])
                        and not (
                            policy.activation_reason == "same_zone_authorized"
                            and any(
                                source.zone == policy.zone
                                for source in source_states
                            )
                        )
                    )
                    or (
                        policy.activation_reason == "provisional_track_acquired"
                        and (
                            policy.activation_track_confidence != "provisional"
                            or len(path) != 2
                        )
                    )
                    or (
                        policy.activation_reason == "track_confirmed"
                        and (
                            policy.activation_track_confidence != "confirmed"
                            or len(path) != 3
                        )
                    )
                    or (
                        policy.activation_reason == "boundary_authorized"
                        and (
                            policy.activation_track_confidence != "provisional"
                            or len(path) != 1
                            or source_states
                        )
                    )
                    or (
                        policy.activation_reason == "prediction_confirmed"
                        and (
                            policy.activation_track_confidence is not None
                            or len(path) != 1
                            or source_states
                        )
                    )
                    or (
                        policy.activation_reason == "local_interaction"
                        and (
                            policy.activation_track_confidence != "provisional"
                            or len(path) != 1
                            or source_states
                        )
                    )
                ):
                    raise ValueError(
                        "Evidence-active policy is not bound to its acquisition episode"
                    )

        count = snapshot.count_state
        if (count.last_event_at is None) != (count.last_event_id is None):
            raise ValueError("Count snapshot event identity is incomplete")
        if any(
            value is not None and value > at
            for value in (count.last_event_at, count.positive_transition_at)
        ):
            raise ValueError("Count snapshot is newer than its model frontier")
        if (
            count.last_event_id is not None
            and count.last_event_id not in count.seen_event_ids
        ) or len(count.seen_event_ids) > SEEN_EVENT_LIMIT:
            raise ValueError("Count snapshot event sequence is inconsistent")
        if (
            count.positive_transition_at is not None
            and count.positive_transition_until
            != count.positive_transition_at
            + ENTRY_BOUNDARY.traversal_context_window
        ):
            raise ValueError("Count transition expiry is not calibration-derived")

        allowed_provenance = {
            "adjacent",
            "adjacent_pair",
            "boundary",
            "local_interaction",
            "missed_edge",
            "same_zone",
        }
        tokens = {token.token_id: token for token in snapshot.traversal_tokens}
        retained_tokens = {
            token.token_id: token for token in snapshot.retained_traversal_tokens
        }
        if (
            len(tokens) != len(snapshot.traversal_tokens)
            or len(retained_tokens) != len(snapshot.retained_traversal_tokens)
            or set(tokens) & set(retained_tokens)
        ):
            raise ValueError("Traversal token snapshot is duplicated")
        for token in (
            *snapshot.traversal_tokens,
            *snapshot.retained_traversal_tokens,
        ):
            state, created_at = self._episode_reference(
                token.episode_id,
                episodes,
                at,
                exact=False,
            )
            profile = SHARED_PROFILES[token.profile_name]
            expected_valid_until = min(
                created_at + profile.traversal_context_window,
                created_at + profile.assertion_trust_horizon,
            )
            trust_until = created_at + profile.assertion_trust_horizon
            reopened_at = token.continuity_reopened_at
            if reopened_at is not None:
                expected_valid_until = min(
                    reopened_at + profile.traversal_context_window,
                    trust_until,
                )
            retained = token.token_id in retained_tokens
            physical_node = physical_nodes[state.node_id]
            interaction_episode = bool(physical_node.interaction_aliases)
            interaction_token = token.provenance_kind == "local_interaction"
            if (
                state.node_id != token.node_id
                or created_at != token.accepted_at
                or token.valid_until != expected_valid_until
                or (
                    reopened_at is not None
                    and not (
                        created_at + profile.hardware_hold_interval
                        <= reopened_at
                        < trust_until
                    )
                )
                or (retained and not token.valid_until <= at < trust_until)
                or (not retained and token.valid_until <= at)
            ):
                raise ValueError("Traversal token is not bound to its physical episode")
            if interaction_episode != interaction_token or (
                interaction_token
                and (
                    physical_node.reliability != 1.0
                    or token.track_confidence != "provisional"
                    or token.path_node_ids != (state.node_id,)
                    or not token.equivalent_confirmed_strength
                )
            ):
                raise ValueError("Interaction traversal token is incompatible")
            if token.provenance_kind not in allowed_provenance:
                raise ValueError("Traversal token provenance is incompatible")
            if token.track_confidence == "confirmed" and len(token.path_node_ids) != 3:
                raise ValueError("Confirmed traversal token lacks a bounded path")
            if token.equivalent_confirmed_strength and (
                (
                    token.provenance_kind in {"boundary", "missed_edge"}
                    and len(token.path_node_ids) != 3
                )
                or (
                    token.provenance_kind == "local_interaction"
                    and len(token.path_node_ids) != 1
                )
                or token.provenance_kind
                not in {"boundary", "local_interaction", "missed_edge"}
            ):
                raise ValueError("Equivalent traversal strength is incompatible")
            if any(node_id not in self._map.nodes for node_id in token.path_node_ids):
                raise ValueError("Traversal token path contains an unknown node")
            if any(
                not self._bounded_path_step(left, right)
                for left, right in zip(
                    token.path_node_ids,
                    token.path_node_ids[1:],
                    strict=False,
                )
            ):
                raise ValueError("Traversal token path is graph-incompatible")

        max_target_traversal = max(
            min(
                SHARED_PROFILES[node.profile_name].traversal_context_window,
                SHARED_PROFILES[node.profile_name].assertion_trust_horizon,
            )
            for node in self._nodes
        )
        for belief in snapshot.belief_states:
            outward = belief.outward_context
            if outward is None:
                continue
            state, created_at = self._episode_reference(
                outward.source_episode_id,
                episodes,
                at,
                exact=True,
            )
            source_profile = SHARED_PROFILES[state.profile_name]
            source_valid_until = min(
                created_at + source_profile.traversal_context_window,
                created_at + source_profile.assertion_trust_horizon,
            )
            if outward.valid_until > source_valid_until + max_target_traversal:
                raise ValueError("Outward context expiry exceeds its calibrated bound")

        for token_id in snapshot.current_token_ids:
            current_token = tokens.get(token_id)
            if current_token is None:
                raise ValueError("Current traversal token does not exist")
            state = episodes[current_token.node_id]
            if (
                state.episode_id != current_token.episode_id
                or state.status != "asserted"
                or state.health_warning
                or state.cadence_warning
            ):
                raise ValueError("Current traversal token is not physically current")

        for candidate in snapshot.pending_candidates:
            state, created_at = self._episode_reference(
                candidate.episode_id,
                episodes,
                at,
                exact=True,
            )
            node = self._map.nodes[candidate.node_id]
            physical_profile = next(
                item for item in self._nodes if item.node_id == candidate.node_id
            )
            sensor_profile = SHARED_PROFILES[candidate.profile_name]
            expected_traversal = min(
                created_at + sensor_profile.traversal_context_window,
                created_at + sensor_profile.assertion_trust_horizon,
            )
            if (
                state.node_id != candidate.node_id
                or created_at != candidate.created_at
                or candidate.expires_at
                != created_at + sensor_profile.track_bootstrap_window
                or candidate.traversal_valid_until != expected_traversal
                or candidate.reliability != physical_profile.reliability
                or node.occupancy_zone != candidate.zone
            ):
                raise ValueError("Pending candidate is not bound to its episode")

        for use in snapshot.authorization_uses:
            traversal_source = tokens.get(use.token_id) or retained_tokens.get(
                use.token_id
            )
            if traversal_source is None or not (
                traversal_source.accepted_at <= use.authorized_at <= at
            ):
                raise ValueError("Traversal use has an incompatible source frontier")
            _state, target_created_at = self._episode_reference(
                use.target_episode_id,
                episodes,
                at,
                exact=False,
            )
            if target_created_at > use.authorized_at:
                raise ValueError("Traversal use predates its target episode")

        self._validate_support_snapshot(snapshot, tokens, retained_tokens)
        self._validate_count_snapshot(snapshot)

    def _validate_support_snapshot(
        self,
        snapshot: ZoneModelSnapshot,
        active_tokens: Mapping[str, TraversalToken],
        retained_tokens: Mapping[str, TraversalToken],
    ) -> None:
        """Bind persisted supports to current physical and traversal state."""

        if len(snapshot.anonymous_supports) > PRODUCT_MAX_OCCUPANTS:
            raise ValueError("Anonymous-support snapshot exceeds its bound")
        episodes = {state.node_id: state for state in snapshot.episode_states}
        beliefs = {state.zone: state for state in snapshot.belief_states}
        tokens = {**active_tokens, **retained_tokens}
        bindings = {
            binding.token_id: binding.support_id
            for binding in snapshot.support_token_bindings
        }
        if any(token_id not in tokens for token_id in bindings):
            raise ValueError("Support-token binding is incompatible")
        for support in snapshot.anonymous_supports:
            node = next(
                (
                    physical
                    for physical in self._nodes
                    if physical.node_id == support.current_node_id
                ),
                None,
            )
            state = episodes.get(support.current_node_id)
            belief = beliefs[support.current_zone]
            if (
                node is None
                or node.zone != support.current_zone
                or state is None
                or state.episode_id != support.current_episode_id
                or support.updated_at > snapshot.updated_at
            ):
                raise ValueError("Anonymous-support endpoint is incompatible")
            origin_token = tokens.get(
                support.support_id.removeprefix("support:")
            )
            if (
                origin_token is not None
                and origin_token.accepted_at == support.created_at
                and origin_token.provenance_kind != support.provenance_kind
            ):
                raise ValueError("Interaction support provenance is incompatible")
            if support.state == "settled":
                calibration = POLICY_CALIBRATIONS[node.profile_name]
                if (
                    SHARED_PROFILES[node.profile_name].role != "stay"
                    or state.status not in {"asserted", "clearing", "clear"}
                    or (
                        state.status == "clear"
                        and belief.outward_context is not None
                    )
                    or state.health_warning
                    or state.cadence_warning
                    or belief.health_warning
                    or belief.probability < calibration.on_threshold
                ):
                    raise ValueError("Settled anonymous support is incompatible")
                continue
            target_tokens = tuple(
                tokens[token_id]
                for token_id, support_id in bindings.items()
                if support_id == support.support_id
                and tokens[token_id].node_id == support.current_node_id
                and tokens[token_id].episode_id == support.current_episode_id
            )
            if not target_tokens or all(
                token.valid_until != support.valid_until for token in target_tokens
            ):
                raise ValueError("Moving support lacks its target binding")

    def _validate_count_snapshot(self, snapshot: ZoneModelSnapshot) -> None:
        """Require stored count conflicts to match current support evidence."""

        episodes = {state.node_id: state for state in snapshot.episode_states}
        supports = tuple(
            CountSupport(
                support.support_id,
                support.current_node_id,
                support.current_zone,
                support.path_node_ids,
            )
            for support in snapshot.anonymous_supports
        )
        for conflict in snapshot.count_conflicts:
            state = episodes.get(conflict.target_node_id)
            historical = (
                conflict.started_at,
                conflict.last_evaluated_at,
                conflict.degraded_at,
            )
            if (
                state is None
                or state.zone != conflict.target_zone
                or state.episode_id != conflict.target_episode_id
                or any(
                    value is not None and value > snapshot.updated_at
                    for value in historical
                )
                or (
                    state is not None
                    and conflict.deadline
                    != conflict.started_at
                    + POLICY_CALIBRATIONS[state.profile_name].release_dwell
                )
                or (
                    conflict.degraded_at is None
                    and conflict.support_ids
                    != tuple(
                        support.support_id
                        for support in supports
                        if support.endpoint_zone != conflict.target_zone
                        and conflict.target_node_id not in support.path_node_ids
                    )[: snapshot.count_state.expected_count]
                )
            ):
                raise ValueError("Count-conflict snapshot is incompatible")

    def _validate_prediction_consistency(
        self,
        manager: TargetPredictionManager,
    ) -> None:
        """Bind every restored predicted policy to one mature current lease."""

        leases = manager.leases
        counts = manager.chain.counts
        episodes = {state.node_id: state for state in self.snapshot.episode_states}
        tokens = {
            token.episode_id: token for token in self.snapshot.traversal_tokens
        }
        for lease in leases:
            state, created_at = self._episode_reference(
                lease.source_episode_id,
                episodes,
                self._updated_at,
                exact=False,
            )
            token = tokens.get(lease.source_episode_id)
            target_state = episodes.get(lease.target_node_id)
            if (
                state.node_id != lease.current_node_id
                or created_at != lease.created_at
                or token is None
                or token.node_id != lease.current_node_id
                or token.track_confidence != "confirmed"
                or len(token.path_node_ids) != 3
                or token.path_node_ids[-2:] != (
                    lease.source_node_id,
                    lease.current_node_id,
                )
            ):
                raise ValueError(
                    "Prediction lease is not bound to confirmed traversal provenance"
                )
            if (
                target_state is not None
                and target_state.last_event_at is not None
                and target_state.last_event_at > lease.created_at
            ):
                raise ValueError(
                    "Prediction lease survived contradictory target evidence"
                )
            prior_total = sum(
                self._map.nodes[node_id].route_prior_weight
                for node_id in self._map.nodes[lease.current_node_id].adjacent
            )
            expected_probability = (
                counts[lease.current_node_id][lease.target_node_id]
                + self._map.nodes[lease.target_node_id].route_prior_weight
            ) / (
                sum(counts[lease.current_node_id].values()) + prior_total
            )
            if lease.support > counts[lease.current_node_id][lease.target_node_id]:
                raise ValueError("Prediction lease support exceeds learned route state")
            if lease.support < counts[lease.current_node_id][lease.target_node_id]:
                raise ValueError(
                    "Prediction lease support disagrees with learned route state"
                )
            if lease.probability > expected_probability + 1e-12:
                raise ValueError(
                    "Prediction lease probability exceeds its learned route state"
                )
            if lease.probability < expected_probability - 1e-12:
                raise ValueError(
                    "Prediction lease probability disagrees with its "
                    "learned route state"
                )
        for policy in self.snapshot.policy_states:
            if policy.phase != "predicted":
                continue
            matches = tuple(
                lease
                for lease in leases
                if lease.mature
                and lease.target_zone == policy.zone
                and lease.source_episode_id == policy.prediction_source_episode_id
                and lease.expires_at == policy.prediction_expires_at
                and lease.probability == policy.prediction_probability
                and lease.support == policy.prediction_support
            )
            if len(matches) != 1:
                raise ValueError("Predicted policy has no matching mature lease")

    def _bounded_path_step(self, source: str, target: str) -> bool:
        if source == target:
            return False
        neighbors = set(self._map.neighbors(source))
        if target in neighbors:
            return True
        return any(target in self._map.neighbors(node_id) for node_id in neighbors)

    @staticmethod
    def _episode_reference(
        episode_id: str,
        states: Mapping[str, EpisodeState],
        frontier: datetime,
        *,
        exact: bool,
    ) -> tuple[EpisodeState, datetime]:
        for node_id in sorted(states, key=len, reverse=True):
            prefix = f"{node_id}:"
            if not episode_id.startswith(prefix):
                continue
            raw_generation, separator, raw_at = episode_id[len(prefix) :].partition(
                ":"
            )
            try:
                generation = int(raw_generation)
                created_at = datetime.fromisoformat(raw_at)
            except ValueError as exc:
                raise ValueError("Episode reference is malformed") from exc
            require_utc(created_at, "Episode reference time")
            state = states[node_id]
            if (
                not separator
                or not 1 <= generation <= state.generation
                or created_at > frontier
                or (
                    generation < state.generation
                    and state.started_at is not None
                    and created_at >= state.started_at
                )
                or (
                    generation == state.generation
                    and state.episode_id != episode_id
                )
                or (exact and state.episode_id != episode_id)
            ):
                raise ValueError("Episode reference is outside stored state")
            return state, created_at
        raise ValueError("Episode reference has no stored physical node")

    @staticmethod
    def _validate_zero_count_snapshot(snapshot: ZoneModelSnapshot) -> None:
        forbidden = (
            snapshot.traversal_tokens,
            snapshot.retained_traversal_tokens,
            snapshot.current_token_ids,
            snapshot.authorization_uses,
            snapshot.pending_candidates,
            snapshot.count_conflicts,
            snapshot.anonymous_supports,
            snapshot.support_token_bindings,
        )
        if any(forbidden):
            raise ValueError("Zero-count snapshot contains acquisition state")
        for belief in snapshot.belief_states:
            prior = BELIEF_PROFILES[belief.profile_name].prior_probability
            if (
                abs(belief.probability - prior) > 1e-12
                or belief.generation_episode_id is not None
                or belief.asserted_episode_id is not None
                or belief.outward_context is not None
                or belief.health_warning
                or belief.context != "cleared_without_outward"
                or belief.contributions
            ):
                raise ValueError("Zero-count snapshot contains nonbaseline belief")
        for policy in snapshot.policy_states:
            if (
                policy.active
                or policy.phase != "inactive"
                or policy.pending_release_since is not None
                or policy.activation_provenance is not None
                or policy.prediction_expires_at is not None
                or policy.prediction_source_episode_id is not None
                or policy.prediction_probability is not None
                or policy.prediction_support is not None
            ):
                raise ValueError("Zero-count snapshot contains policy authority")

    @staticmethod
    def _effect_order(effect: EpisodeEffect) -> tuple[datetime, str, int, str]:
        priority = {
            "cadence_warning_cleared": 0,
            "stable_clear": 1,
            "health_degraded": 2,
            "health_recovered": 2,
            "correlated_positive": 3,
            "interaction": 3,
            "positive": 3,
            "sustained_flapping": 3,
        }.get(effect.kind, 1)
        return effect.at, effect.node_id, priority, effect.kind


__all__ = ["ZoneModelEngine"]
