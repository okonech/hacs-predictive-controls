"""Ordered standalone orchestration for the graph-local target model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from itertools import groupby

from ..model import PredictiveMap
from .count import (
    CountConflictTracker,
    CountContext,
    apply_count_update,
)
from .episodes import PhysicalEpisodes
from .filter import ZoneBeliefFilter
from .path_health import PathHealth, PathHealthState
from .policy import (
    POLICY_CALIBRATIONS,
    REFRESH_RETENTION,
    PolicyAuditLog,
    ZonePolicy,
)
from .prediction import PredictionLease, TargetPredictionManager
from .profiles import (
    BELIEF_PROFILES,
    SHARED_PROFILES,
    build_physical_nodes,
)
from .selected_paths import SelectedPaths
from .supported_gap_acquisition import (
    gap_geometry_valid,
    select_supported_gap_source,
)
from .supports import AnonymousSupportTracker
from .traversal import TraversalFrontier
from .types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    ReliabilityWarningOccurrence,
    SelectedPredictionGrant,
    SensorInput,
    SupportTransitionEvent,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
    ZoneModelSnapshot,
    _physical_episode_reference,
    require_utc,
)
from .validation import (
    SnapshotValidator,
    bounded_path_step,
    direct_different_zone_pair,
    episode_reference,
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
        self._episodes = PhysicalEpisodes(self._nodes, diagnostic_warnings=False)
        self._selected_paths = SelectedPaths(predictive_map, self._nodes, initial_count)
        self._path_health = PathHealth(self._nodes)
        self._restore_health_baseline: tuple[
            tuple[PathHealthState, ...], tuple[ReliabilityWarningOccurrence, ...],
            datetime,
        ] | None = None
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
        self._in_decision_callback = False

    @classmethod
    def restore(
        cls,
        predictive_map: PredictiveMap,
        snapshot: ZoneModelSnapshot,
        audit_rows: tuple[PolicyDecision, ...],
        restore_at: datetime,
        *, prediction_state: object | None = None,
    ) -> ZoneModelEngine:
        require_utc(restore_at, "Zone-model restore time")
        if restore_at < snapshot.updated_at:
            raise ValueError("Zone-model restore time predates stored state")
        if prediction_state is None and (
            snapshot.selected_prediction_grants
            or any(policy.phase == "predicted" for policy in snapshot.policy_states)
        ):
            raise ValueError("Snapshot restore requires independent prediction state")
        candidate = cls(
            predictive_map,
            snapshot.count_state.expected_count,
            snapshot.updated_at,
        )
        candidate._episodes.restore_snapshot(snapshot.episode_states)
        candidate._predictions.restore_grants(snapshot.selected_prediction_grants)
        candidate._selected_paths.restore(
            snapshot.selected_paths, snapshot.selected_sources, snapshot.updated_at,
        )
        candidate._path_health.restore(
            snapshot.path_health, snapshot.reliability_warning_occurrences,
            snapshot.updated_at,
        )
        candidate._restore_health_baseline = (
            snapshot.path_health, snapshot.reliability_warning_occurrences,
            snapshot.updated_at,
        )
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
        if prediction_state is not None:
            candidate.restore_prediction_state(prediction_state, snapshot.updated_at)
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
            self._selected_paths.paths,
            self._selected_paths.sources,
            self._path_health.states,
            self._predictions.grants,
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

    @property
    def prediction_state(self) -> dict[str, object]:
        """Project accepted raw and folded learning once, including in callbacks."""

        return self._predictions.serialize(
            pending=tuple(self._pending_prediction_learning),
        )

    def commit_prediction_learning(self) -> bool:
        """Commit queued confirmed route observations after publication."""

        self.assert_mutation_allowed()
        pending = tuple(self._pending_prediction_learning)
        self._predictions.defer(pending)
        self._pending_prediction_learning.clear()
        return self._predictions.commit(())

    def _fold_prior_learning(self, length: int, result: ZoneModelResult) -> None:
        if length and result.disposition not in {"stale", "duplicate"}:
            self._predictions.defer(tuple(self._pending_prediction_learning[:length]))
            del self._pending_prediction_learning[:length]

    def restore_prediction_state(self, payload: object, at: datetime) -> None:
        """Install validated route statistics and unexpired leases atomically."""

        self.assert_mutation_allowed()
        candidate = TargetPredictionManager.restored(
            self._map, payload, at, grants=self._predictions.grants,
            strict_frontier=True,
        )
        if self._count.state.expected_count == 0 and candidate.leases:
            raise ValueError("Zero-count state cannot restore prediction leases")
        self._validate_prediction_consistency(candidate)
        self._predictions = candidate
        self._pending_prediction_learning.clear()

    def bootstrap_sensor_snapshot(
        self,
        events: Sequence[SensorInput],
        at: datetime,
    ) -> ZoneModelSnapshot:
        """Apply raw startup states without traversal or public policy events."""

        self.assert_mutation_allowed()
        self._validate_operation_time(at, at)
        self._advance_components(at)
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
        self._selected_paths.reconcile(self._episodes.states, at)
        self._reconcile_physical_holds(at)
        self._path_health.observe(
            self._episodes.states, at, self._selected_paths.covered_nodes,
            bootstrap=True,
        )
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

        self.assert_mutation_allowed()
        self._validate_operation_time(at, at)
        if any(event.event_at != at for event in events):
            raise ValueError("Restore sensor snapshot must share one frontier")
        if at > self._updated_at:
            self.advance(at, processing_at=at, emit_events=False)
        # Startup establishes raw baselines, not traversal observations. Install
        # changed aliases in the physical reducer so the next real ON is not
        # mistaken for a duplicate of a pre-restart assertion.
        raw = {event.entity_id: event for event in events}
        for state in self._episodes.states:
            if any(
                alias not in raw or raw[alias].state != value
                for alias, value in state.alias_states
            ):
                self._frontier.sync(state, at, invalidate=True)
        updates = self._episodes.reconcile_startup_snapshot(events, at)
        if self._count.state.expected_count > 0:
            for update in updates:
                for effect in update.effects:
                    if effect.kind == "positive":
                        self._filters[effect.zone].apply_positive(
                            effect.episode_id, at, effect.reliability,
                        )
            for update in updates:
                if (
                    update.disposition == "startup_baseline"
                    and update.state.generation > 0
                ):
                    # Every node's levels are installed before same-zone context
                    # selection; a missing peer cannot erase an actual survivor.
                    self._reconcile_zone_availability(update.state.zone, at)
        before = self._selected_paths.covered_zones
        self._selected_paths.reconcile(self._episodes.states, at)
        # restore(at > snapshot frontier) permits an in-session elapsed replay.
        # An explicit startup snapshot instead declares an observation gap: use
        # the original observed ledger, not warnings inferred during that gap.
        if self._restore_health_baseline is not None:
            self._path_health.restore(*self._restore_health_baseline)
            self._restore_health_baseline = None
        self._path_health.observe(
            self._episodes.states, at, self._selected_paths.covered_nodes,
            bootstrap=True,
        )
        self._coverage_changed(before, at)
        self._reconcile_physical_holds(at)
        self._advance_supports(at)
        self._prepare_predictions(at, ())
        self._expire_prediction_policies(at, at, force_missing=True, emit_events=False)
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
        result_callback: Callable[[ZoneModelResult], None] | None = None,
        decision_callback: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> ZoneModelResult:
        """Observe one input with audit deferred across a public handoff."""

        self.assert_mutation_allowed()
        learning_frontier = len(self._pending_prediction_learning)
        if decision_callback is None and result_callback is None:
            try:
                result = self._observe(event, processing_at=processing_at)
            except Exception:
                del self._pending_prediction_learning[learning_frontier:]
                raise
            self._fold_prior_learning(learning_frontier, result)
            return result
        audits = tuple(policy.audit for policy in self._policies.values())
        for audit in audits:
            audit.begin_defer()
        callback_failure: Exception | None = None
        publications: list[
            tuple[PolicyEvent, PolicyDecision, TraversalAuthorization | None]
        ] = []

        def collect(
            policy_event: PolicyEvent,
            decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            publications.append((policy_event, decision, authorization))

        def safe_callback(
            policy_event: PolicyEvent,
            decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            nonlocal callback_failure
            if callback_failure is not None or decision_callback is None:
                return
            try:
                self._in_decision_callback = True
                decision_callback(policy_event, decision, authorization)
            except Exception as exc:  # publication failure is reported after commit
                callback_failure = exc
            finally:
                self._in_decision_callback = False

        try:
            result = self._observe(
                event,
                processing_at=processing_at,
                decision_callback=collect if decision_callback is not None else None,
            )
        except Exception:
            for audit in audits:
                audit.discard_deferred()
            del self._pending_prediction_learning[learning_frontier:]
            raise
        # Install every committed decision, including nonedges and deadlines,
        # before the first legacy edge callback can dispatch all zone entities.
        # Both external interfaces share the mutation/failure guard and audit
        # transaction; neither can learn or replace the accepted frontier.
        if result_callback is not None:
            try:
                self._in_decision_callback = True
                result_callback(result)
            except Exception as exc:
                callback_failure = exc
            finally:
                self._in_decision_callback = False
        for publication in publications:
            safe_callback(*publication)
        for audit in audits:
            audit.flush_deferred()
        self._fold_prior_learning(learning_frontier, result)
        if callback_failure is not None:
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
        self._restore_health_baseline = None
        if self._count.state.expected_count == 0:
            return self._observe_empty_house(event, processing_at)
        operation_beliefs = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
        qualified_beliefs = self._advance_episode_effects(event.event_at)
        retained_beliefs = {
            zone: qualified_beliefs.get(zone, filter_.state)
            for zone, filter_ in self._filters.items()
            if self._policies[zone].state.retained_endpoint_hold
            or zone in qualified_beliefs
        }
        self._advance_components(event.event_at)
        deadline_decisions, deadline_events = self._release_due_policies(
            event.event_at,
            processing_at,
            {**operation_beliefs, **qualified_beliefs},
        )
        # An external clear arriving exactly at a count-conflict deadline must
        # not erase the asserted episode before its health diagnosis. Positive
        # acquisition events defer this whole-house work until after the local
        # publication callback.
        if event.state not in {"on", "pressed"}:
            self._apply_count_conflicts(event.event_at)
        selected_before = self._episodes.states
        predicted_before = frozenset(
            zone for zone, policy in self._policies.items()
            if policy.state.phase == "predicted"
            and policy.state.prediction_expires_at is not None
            and event.event_at < policy.state.prediction_expires_at
        )
        update = self._episodes.observe(event)
        if update.disposition in {"stale", "duplicate"}:
            pending_expiry_decisions = self._record_pending_expiries(
                event.event_at, processing_at
            )
            self._apply_count_conflicts(event.event_at)
            retention_decisions, retention_events = self._evaluate_retention_loss(
                event.event_at, processing_at, retained_beliefs
            )
            self._updated_at = event.event_at
            return ZoneModelResult(
                update.disposition,
                self.snapshot,
                (*deadline_events, *retention_events),
                (*pending_expiry_decisions, *deadline_decisions, *retention_decisions),
            )

        if event.state in {"unknown", "unavailable"}:
            # Invalidate before warning-clear effects can promote a preserved
            # historical token when another alias still reports on.
            self._frontier.sync(update.state, event.event_at, invalidate=True)

        effects = tuple(sorted(update.effects, key=self._effect_order))
        final_effect: EpisodeEffect | None = None
        final_authorization: TraversalAuthorization | None = None
        final_token: TraversalToken | None = None
        belief_before: ZoneBeliefState | None = None
        authorizations: list[TraversalAuthorization] = []
        source_authorizations: list[TraversalAuthorization] = []
        unsupported_targets: set[str] = set()
        for effect in effects:
            # Deadlines were reconciled before the external observation. Do not
            # prune its old target generation before fresh branch selection.
            self._advance_components(effect.at, reconcile=False)
            current_before = self._filters[effect.zone].state
            jump_candidate = self._selected_paths.unsupported_jump(
                effect, update.state, selected_before,
            )
            authorization, applied_effect, issued_token = self._apply_effect(
                update.state, effect, selected_before=selected_before,
            )
            if (jump_candidate
                and (authorization is None or not authorization.authorized)
                and not (
                    effect.zone in predicted_before
                    and self._policies[effect.zone]._confirming_evidence(
                        effect.at, update.state, effect,
                    )
                )
            ):
                unsupported_targets.add(effect.node_id)
            if authorization is not None:
                authorizations.append(authorization)
                if (
                    authorization.authorized
                    and effect.kind in {"interaction", "positive"}
                    and authorization.reason not in {
                        "settled_endpoint_reacquired", "settled_adjacent_transfer",
                        "supported_gap_acquisition",
                    }
                    and self._policies[authorization.target_zone].state.phase
                    != "predicted"
                ):
                    source_authorizations.append(authorization)
            final_effect = applied_effect
            final_authorization = authorization
            final_token = issued_token
            belief_before = current_before

        # Preserve the deadline-advanced source/binding basis across issuance.
        self._advance_components(event.event_at, advance_supports=False)
        if event.state in {"unknown", "unavailable"}:
            belief_before = self._filters[update.state.zone].state
            self._reconcile_zone_availability(update.state.zone, event.event_at)
        elif update.disposition == "baseline_clear":
            belief_before = self._filters[update.state.zone].state
            cleared = self._filters[update.state.zone].apply_availability_clear(
                # Availability ends the existing zone context; a physical
                # generation observed during count0 may have no belief witness.
                belief_before.generation_episode_id,
                event.event_at,
            )
            retained = retained_beliefs.get(update.state.zone)
            if (
                cleared is belief_before
                and retained is not None
                and retained.generation_episode_id == cleared.generation_episode_id
                and retained.context == cleared.context
                and retained.qualified_departure_at == cleared.qualified_departure_at
            ):
                # An inert alias/baseline OFF must not replace an earlier proof
                # with the final callback's already-decayed belief. A real
                # unavailable clear still resets context and starts fresh dwell.
                belief_before = retained
        self._frontier.sync(update.state, event.event_at)
        losses = self._reconcile_physical_holds(event.event_at)
        retained_beliefs.update(losses)
        if update.state.zone in losses:
            belief_before = losses[update.state.zone]
        support_effect = (
            None
            if final_effect is not None
            and final_effect.kind == "correlated_positive"
            and (
                final_authorization is None
                or (
                    final_authorization.reason != "settled_endpoint_reacquired"
                    and final_token is None
                )
            )
            else final_effect
        )
        if (
            final_authorization is not None
            and final_authorization.reason in {
                "supported_gap_acquisition", "selected_path",
            }
        ):
            # Even a positive with token=None could rebind an exact endpoint.
            support_effect = None
        support_authorization = (
            None if support_effect is None else final_authorization
        )
        support_token = None if support_effect is None else final_token
        prepared_support = self._supports.prepare(
            event.event_at,
            support_effect,
            support_authorization,
            support_token,
            self._episodes.states,
            tuple(self._filters[zone].state for zone in sorted(self._filters)),
            self._frontier.tokens,
            self._frontier.retained_tokens,
        )
        prediction_leases = self._prepare_predictions(
            event.event_at, tuple(source_authorizations), effects=effects,
            departure_authorizations=tuple(authorizations),
            observed_node_ids=frozenset({update.state.node_id}),
        )
        self._path_health.observe(
            self._episodes.states, event.event_at, self._selected_paths.covered_nodes,
        )
        for node_id in sorted(unsupported_targets):
            self._path_health.record_unsupported_jump(
                node_id, event.event_at, self._selected_paths.covered_nodes,
            )
        self._advance_health(event.event_at)
        publications: list[
            tuple[PolicyEvent, PolicyDecision, TraversalAuthorization | None]
        ] = []

        def collect_publication(
            policy_event: PolicyEvent, decision: PolicyDecision,
            authorization: TraversalAuthorization | None,
        ) -> None:
            publications.append((policy_event, decision, authorization))

        decisions, policy_events = self._evaluate_policies(
            event.event_at, processing_at, update.state, final_effect,
            final_authorization, belief_before,
            belief_before_by_zone={
                zone: belief for zone, belief in retained_beliefs.items()
                if belief_before is None or zone != update.state.zone
            },
            settled_endpoint_zones=frozenset(
                support.current_zone
                for support in prepared_support.transition.supports
                if support.state == "settled"
            ),
            prediction_leases=prediction_leases,
            decision_callback=collect_publication if decision_callback else None,
        )
        self._supports.commit_prepared(prepared_support)
        pending_expiry_decisions = self._record_pending_expiries(
            event.event_at, processing_at
        )
        self._apply_count_conflicts(
            event.event_at,
            local_effect=final_effect,
            authorization=final_authorization,
        )
        self._updated_at = event.event_at
        # Publication reads the accepted frontier, including surviving support
        # bindings and all policy states. The outer callback guard and deferred
        # audit transaction still forbid mutations and commit on callback failure.
        if decision_callback is not None:
            for publication in publications:
                decision_callback(*publication)
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
        self._advance_health(event.event_at)
        update = self._episodes.observe(event)
        self._selected_paths.set_count(0, event.event_at)
        for effect in update.effects:
            if effect.kind in {"positive", "correlated_positive", "interaction"}:
                self._selected_paths.observe(
                    effect, update.state, self._episodes.states,
                )
        self._selected_paths.reconcile(self._episodes.states, event.event_at)
        self._path_health.observe(self._episodes.states, event.event_at, frozenset())
        self._advance_health(event.event_at)
        for filter_ in self._filters.values():
            filter_.apply_empty_baseline(event.event_at)
        self._frontier.clear(event.event_at)
        self._predictions.clear()
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
        self.assert_mutation_allowed()
        processing_at = event.event_at if processing_at is None else processing_at
        if event.event_at < self._updated_at:
            require_utc(event.event_at, "Zone-model event time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(event.event_at, processing_at)
        operation_beliefs = {
            zone: filter_.state for zone, filter_ in self._filters.items()
        }
        qualified_beliefs = self._advance_episode_effects(event.event_at)
        retained_beliefs = {
            zone: qualified_beliefs.get(zone, filter_.state)
            for zone, filter_ in self._filters.items()
            if self._policies[zone].state.retained_endpoint_hold
            or zone in qualified_beliefs
        }
        self._advance_components(event.event_at)
        pending_expiry_decisions = self._record_pending_expiries(
            event.event_at, processing_at
        )
        self._apply_count_conflicts(event.event_at)
        deadline_decisions, deadline_events = self._release_due_policies(
            event.event_at,
            processing_at,
            {**operation_beliefs, **qualified_beliefs},
        )
        update = self._count.observe(event)
        if update.disposition != "accepted":
            retention_decisions, retention_events = self._evaluate_retention_loss(
                event.event_at, processing_at, retained_beliefs
            )
            self._updated_at = event.event_at
            return ZoneModelResult(
                update.disposition,
                self.snapshot,
                (*deadline_events, *retention_events),
                (*pending_expiry_decisions, *deadline_decisions, *retention_decisions),
            )
        covered_before = self._selected_paths.covered_zones
        self._selected_paths.set_count(update.state.expected_count, event.event_at)
        self._coverage_changed(covered_before, event.event_at)
        self._reconcile_physical_holds(event.event_at)
        if update.categorical_zero:
            self._episodes.reset_cadence(event.event_at)
            apply_count_update(update, self._filters, self._frontier)
            self._count_conflicts.clear()
            self._supports.clear(event.event_at)
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
                belief_before_by_zone=retained_beliefs,
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
        self.assert_mutation_allowed()
        processing_at = at if processing_at is None else processing_at
        if at < self._updated_at:
            require_utc(at, "Zone-model advance time")
            require_utc(processing_at, "Zone-model processing time")
            return ZoneModelResult("stale", self.snapshot)
        self._validate_operation_time(at, processing_at)
        qualified_beliefs = self._advance_episode_effects(at)
        belief_before_advance = {
            zone: qualified_beliefs.get(zone, filter_.state)
            for zone, filter_ in self._filters.items()
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

    def _advance_episode_effects(self, at: datetime) -> dict[str, ZoneBeliefState]:
        """Consume complete deadline groups using immutable episode projections."""

        before = self._episodes.states
        updates = self._episodes.advance(at)
        effects = sorted(
            (effect for update in updates for effect in update.effects),
            key=self._effect_order,
        )
        beliefs: dict[str, ZoneBeliefState] = {}
        for frontier, grouped in groupby(effects, key=lambda effect: effect.at):
            group = tuple(grouped)
            covered_before = self._selected_paths.covered_zones
            self._advance_components(frontier, reconcile=False)
            projected = self._episode_states_at(before, frontier)
            states = {state.node_id: state for state in projected}
            for effect in group:
                self._apply_effect(
                    states[effect.node_id], effect,
                    episode_states_before_advance=before,
                )
            self._selected_paths.reconcile(projected, frontier)
            self._coverage_changed(covered_before, frontier, projected)
            for effect in group:
                self._capture_qualified_release_belief(effect, beliefs)
            # Capture after every same-time clear/reselection, never between them.
            beliefs.update(self._reconcile_physical_holds(frontier, projected))
            self._advance_supports(frontier)
        return beliefs

    def _capture_qualified_release_belief(
        self,
        effect: EpisodeEffect,
        beliefs: dict[str, ZoneBeliefState],
    ) -> None:
        """Keep the proof frontier across unrelated deadlines in this operation."""

        belief = self._filters[effect.zone].state
        if (
            (
                self._policies[effect.zone].state.retained_endpoint_hold
                and belief.qualified_departure_at == effect.at
            )
            or belief.path_displaced_at == effect.at
        ):
            beliefs.setdefault(effect.zone, belief)

    def _apply_effect(
        self,
        state: EpisodeState,
        effect: EpisodeEffect,
        *,
        episode_states_before_advance: tuple[EpisodeState, ...] | None = None,
        selected_before: tuple[EpisodeState, ...] | None = None,
    ) -> tuple[
        TraversalAuthorization | None,
        EpisodeEffect,
        TraversalToken | None,
    ]:
        filter_ = self._filters[effect.zone]
        token: TraversalToken | None
        if self._count.state.expected_count == 0:
            return None, effect, None
        if effect.kind in {"positive", "correlated_positive", "interaction"}:
            if effect.kind == "positive":
                filter_.apply_positive(effect.episode_id, effect.at, effect.reliability)
            elif effect.kind == "correlated_positive":
                filter_.apply_correlated_positive(
                    effect.episode_id, effect.at, effect.reliability,
                )
            else:
                filter_.apply_interaction(effect.episode_id, effect.at)
            covered_before = self._selected_paths.covered_zones
            selected = self._selected_paths.observe(
                effect, state, self._episodes.states, before=selected_before,
            )
            self._coverage_changed(covered_before, effect.at)
            if selected is not None:
                # The selected target and its consumed origin must not leave
                # legacy pending/token authority behind to reseed another path.
                for peer in self._episodes.states:
                    if peer.node_id == effect.node_id or peer.episode_id in (
                        selected.selected_source_episode_ids
                    ):
                        self._frontier.sync(peer, effect.at, invalidate=True)
                filter_.restore_path(effect.at)
                if effect.kind != "interaction":
                    filter_.apply_arrival_transition(effect.episode_id, effect.at)
                return selected, effect, None
        if effect.kind == "positive":
            settled_support = self._supports.settled_endpoint_for(state)
            authorization = self._frontier.authorize(
                state,
                effect.at,
                count=self._count.state,
                corroborating_states=self._episodes.states,
                settled_support=settled_support,
                handoff_resolver=lambda: self._supports.settled_adjacent_for(
                    state, effect, self._episodes.states,
                    tuple(item.state for item in self._filters.values()),
                ),
                allow_missed_edge=False,
            )
            if authorization.authorized:
                covered_before = self._selected_paths.covered_zones
                self._selected_paths.adopt(effect, state, authorization)
                self._coverage_changed(covered_before, effect.at)
                filter_.restore_path(effect.at)
                filter_.apply_arrival_transition(effect.episode_id, effect.at)
                token = (
                    None if authorization.reason == "supported_gap_acquisition"
                    else self._frontier.issue(state, effect, authorization)
                )
            else:
                token = None
            if (
                authorization.settled_handoff is None
                and authorization.reason != "supported_gap_acquisition"
            ):
                TraversalFrontier.apply_outward_context(
                    authorization,
                    self._filters,
                    effect.at,
                    state.traversal_valid_until,
                )
                self._register_generation_outward(
                    authorization,
                    state,
                    effect.at,
                )
            return authorization, effect, token
        if effect.kind == "correlated_positive":
            settled_support = self._supports.settled_endpoint_for(state)
            authorization = self._frontier.authorize_correlated_target(
                state,
                effect.at,
                settled_support=settled_support,
                handoff_resolver=lambda: self._supports.settled_adjacent_for(
                    state, effect, self._episodes.states,
                    tuple(item.state for item in self._filters.values()),
                ),
                allow_missed_edge=False,
            )
            if authorization.authorized:
                filter_.apply_arrival_transition(effect.episode_id, effect.at)
            support_backed = self._supports.has_transfer_authority(authorization)
            token = (
                self._frontier.issue_correlated_continuation(
                    state,
                    effect,
                    authorization,
                    support_backed=True,
                )
                if support_backed or authorization.settled_handoff is not None
                else None
            )
            return authorization, effect, token
        if effect.kind == "correlated_flap_ignored":
            if self._frontier.reopen_authorized_continuity(state, effect):
                effect = replace(effect, kind="correlated_continuity_authorized")
                filter_.supersede_outward(effect.episode_id, effect.at)
            else:
                self._frontier.sync(state, effect.at)
            return None, effect, None
        # Engine episode diagnostics are disabled; unsupported effects fail fast.
        assert effect.kind == "stable_clear"
        if filter_.state.generation_episode_id == effect.episode_id:
            filter_.apply_stable_clear(
                effect.episode_id, effect.at, effect.reliability
            )
        departure_states = (
            self._episodes.states
            if episode_states_before_advance is None
            else tuple(
                self._episodes._advance_state(peer, effect.at)[0]
                for peer in episode_states_before_advance
                if peer.zone == effect.zone
            )
        )
        # PhysicalEpisodes.advance has already committed the final states.
        # Its pure per-node transition above projects immutable same-zone
        # inputs to this proof frontier, including health/cadence deadlines.
        # Do not infer a clear start from last_event_at: alias-only updates
        # can change it both during clearing and after stable clear.
        departure_source = next(
            peer for peer in departure_states if peer.node_id == state.node_id
        )
        self._register_confirmed_departure(
            departure_source, effect, episode_states=departure_states,
        )
        self._frontier.sync(state, effect.at)
        return None, effect, None

    def _supported_gap_source(
        self, target: EpisodeState, effect: EpisodeEffect,
    ) -> TraversalToken | None:
        """Resolve late using current count, episodes and deadline-advanced support."""

        return select_supported_gap_source(
            self._map, {node.node_id: node for node in self._nodes},
            target, effect, self._count.state, self._frontier.tokens,
            self._episodes.states, self._supports.supports, self._supports.bindings,
        )

    def _register_generation_outward(
        self,
        authorization: TraversalAuthorization,
        target: EpisodeState,
        at: datetime,
    ) -> None:
        nodes = {node.node_id: node for node in self._nodes}
        for source_filter in self._filters.values():
            generation_episode_id = source_filter.state.generation_episode_id
            if generation_episode_id is None or source_filter.state.health_warning:
                continue
            generation = next(
                (
                    episode
                    for episode in self._episodes.states
                    if episode.episode_id == generation_episode_id
                ),
                None,
            )
            if generation is None or any(
                episode.episode_id != generation_episode_id
                and episode.zone == generation.zone
                and not nodes[episode.node_id].interaction_aliases
                and SHARED_PROFILES[episode.profile_name].role == "stay"
                and episode.status in {"asserted", "clearing"}
                and not episode.health_warning
                and not episode.cadence_warning
                for episode in self._episodes.states
            ):
                continue
            predecessor = self._frontier.same_zone_predecessor_for_outward(
                authorization,
                generation,
                at,
            )
            if predecessor is None:
                continue
            valid_until = max(
                predecessor.valid_until,
                predecessor.valid_until
                if target.traversal_valid_until is None
                else target.traversal_valid_until,
            )
            source_filter.register_outward(
                generation_episode_id,
                valid_until,
                at,
                qualified=predecessor.node_id in authorization.path_node_ids[:-1],
            )

    def _register_confirmed_departure(
        self,
        source: EpisodeState,
        effect: EpisodeEffect,
        *,
        episode_states: tuple[EpisodeState, ...] | None = None,
    ) -> None:
        episode_states = (
            self._episodes.states if episode_states is None else episode_states
        )
        source_node = next(
            node for node in self._nodes if node.node_id == source.node_id
        )
        source_filter = self._filters[source.zone]
        if (
            source.status != "clear"
            or source.episode_id != effect.episode_id
            or source.started_at is None
            or source.last_event_at is None
            or source_node.interaction_aliases
            or SHARED_PROFILES[source.profile_name].role != "stay"
            or source.health_warning
            or source.cadence_warning
            or source_filter.state.context not in {
                "cleared_without_outward", "cleared_with_outward",
            }
        ):
            return

        generation_episode_id = source_filter.state.generation_episode_id
        if generation_episode_id is None:
            # An episode observed during count0 supplies no belief generation
            # when the count later increases and its delayed clear is processed.
            return
        generation = next(
            (
                state
                for state in episode_states
                if state.episode_id == generation_episode_id
            ),
            None,
        )
        assert generation is not None
        assert generation.zone == source.zone
        nodes = {node.node_id: node for node in self._nodes}
        if generation.episode_id != source.episode_id:
            generation_node = nodes[generation.node_id]
            if (
                not generation_node.interaction_aliases
                or generation.started_at is None
                or not source.started_at
                <= generation.started_at
                <= source.last_event_at
                or generation.health_warning
                or generation.cadence_warning
                or not any(
                    contribution.kind == "local_interaction"
                    and contribution.episode_id == generation.episode_id
                    for contribution in source_filter.state.contributions
                )
            ):
                return

        if any(
            state.node_id != source.node_id
            and state.zone == source.zone
            and not nodes[state.node_id].interaction_aliases
            and SHARED_PROFILES[state.profile_name].role == "stay"
            and state.status in {"asserted", "clearing"}
            and not state.health_warning
            and not state.cadence_warning
            for state in episode_states
        ):
            return

        token = self._frontier.confirmed_departure_token(source, effect.at)
        if token is not None:
            source_filter.register_outward(
                generation.episode_id or "",
                token.valid_until,
                effect.at,
                qualified=True,
            )

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

    def _advance_components(
        self, at: datetime, *, advance_supports: bool = True,
        reconcile: bool = True,
    ) -> None:
        for filter_ in self._filters.values():
            filter_.advance(at)
        # Episode advance commits final states before returning intermediate
        # effects. Never use those final clears to revoke earlier path authority.
        if reconcile and all(
            frontier is None or frontier <= at for state in self._episodes.states
            for frontier in (state.started_at, state.last_event_at, state.advanced_at)
        ):
            self._reconcile_selected(at)
        else:
            self._advance_health(at)
        self._frontier.advance(at)
        if advance_supports:
            self._advance_supports(at)

    def _episode_states_at(
        self, states: tuple[EpisodeState, ...], at: datetime,
    ) -> tuple[EpisodeState, ...]:
        """Project immutable pre-operation states, not final-time episode flags."""

        return tuple(
            replace(self._episodes._advance_state(state, at)[0], advanced_at=at)
            for state in states
        )

    def _advance_health(self, at: datetime) -> None:
        self._reliability_warning_occurrences = {
            (item.node_id, item.reason): item
            for item in self._path_health.advance(
                at, self._selected_paths.covered_nodes,
            )
        }

    def _coverage_changed(
        self, before: frozenset[str], at: datetime,
        states: tuple[EpisodeState, ...] | None = None,
    ) -> None:
        sources = {source.node_id: source for source in self._selected_paths.sources}
        selected_episodes = {
            visit.episode_id for path in self._selected_paths.paths if path is not None
            for visit in path.occurrences
        }
        for state in self._episodes.states if states is None else states:
            source = sources[state.node_id]
            if (
                source.consumed
                and state.node_id not in self._selected_paths.covered_nodes
            ):
                # Correlated origins cannot seed selection, but TRAV014/018 may
                # independently issue bounded authority for this exact generation.
                # Selected success destroys its legacy tokens before returning;
                # history eviction must never reconstruct that retired authority.
                tokens = tuple(
                    token for token in (
                        *self._frontier.tokens, *self._frontier.retained_tokens,
                    ) if token.node_id == state.node_id
                )
                preserved = {
                    token.token_id for token in tokens
                    if source.origin == "correlated" and state.cadence_correlated
                    and source.episode_id == state.episode_id == token.episode_id
                    and source.at == state.started_at == token.accepted_at
                    and token.provenance_kind in {
                        "adjacent", "settled_adjacent_transfer",
                    }
                    and token.episode_id not in selected_episodes
                }
                if preserved:
                    for token in tokens:
                        if token.token_id not in preserved:
                            self._frontier._remove_token(token.token_id)
                self._frontier.sync(state, at, invalidate=not preserved)
        for zone in before - self._selected_paths.covered_zones:
            self._filters[zone].displace_path(at)
            policy = self._policies[zone]
            if policy.state.retained_endpoint_hold:
                # Consume hold loss at its actual movement/clear frontier. Later
                # sparse policy evaluation must not restart this full release dwell.
                belief = self._filters[zone].state
                policy.evaluate(
                    at, belief, belief, local_state=None, local_effect=None,
                    authorization=None, retained_endpoint_hold=False,
                )
        self._advance_health(at)

    def _reconcile_selected(
        self, at: datetime, states: tuple[EpisodeState, ...] | None = None,
    ) -> None:
        self._advance_health(at)
        before = self._selected_paths.covered_zones
        self._selected_paths.reconcile(
            self._episodes.states if states is None else states, at,
        )
        self._coverage_changed(before, at, states)

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
        *,
        effects: tuple[EpisodeEffect, ...] = (),
        departure_authorizations: tuple[TraversalAuthorization, ...] | None = None,
        observed_node_ids: frozenset[str] = frozenset(),
    ) -> tuple[PredictionLease, ...]:
        leases = self._predictions.prepare(
            at,
            self._count.state.expected_count,
            self._episodes.states,
            authorizations,
            effects=effects, selected_paths=self._selected_paths.paths,
            departure_authorizations=departure_authorizations,
            observed_node_ids=observed_node_ids,
        )
        self._pending_prediction_learning.extend(
            authorization
            for authorization in authorizations
            if authorization.track_confidence == "confirmed"
            and authorization.provenance_kind == "adjacent"
            and self._policies[authorization.target_zone].state.phase
            != "predicted"
        )
        return leases

    def _expire_prediction_policies(
        self, at: datetime, processing_at: datetime, *,
        force_missing: bool = False, emit_events: bool = True,
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        """Complete expiry before duplicate input and silent startup boundaries."""

        self._predictions.expire(at)
        decisions: list[PolicyDecision] = []
        events: list[PolicyEvent] = []
        for zone, policy in sorted(self._policies.items()):
            if policy.state.phase != "predicted":
                continue
            update = policy.expire_prediction(
                at, self._filters[zone].state, processing_at=processing_at,
                emit_event=emit_events,
                force=force_missing and not any(
                    lease.mature and lease.target_zone == zone
                    and (
                        lease.source_episode_id
                        == policy.state.prediction_source_episode_id
                    )
                    and lease.expires_at == policy.state.prediction_expires_at
                    for lease in self._predictions.leases
                ),
            )
            if update is not None:
                decisions.append(update.decision)
                if update.event is not None:
                    events.append(update.event)
        return tuple(decisions), tuple(events)

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
        """Legacy count pressure no longer changes physical inference health."""

        self._advance_health(at)

    def _release_due_policies(
        self,
        at: datetime,
        processing_at: datetime,
        belief_before_by_zone: Mapping[str, ZoneBeliefState],
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        """Advance normal release deadlines before an external input at ``at``."""

        prediction_decisions, prediction_events = self._expire_prediction_policies(
            at, processing_at,
        )
        decisions = list(prediction_decisions)
        events = list(prediction_events)
        asserted_stay_holds = self._asserted_stay_hold_zones()
        settled_endpoint_zones = frozenset(
            support.current_zone for support in self._supports.supports
            if support.state == "settled"
        )
        retained_endpoint_holds = self._retained_endpoint_hold_zones(
            settled_endpoint_zones
        )
        for zone in sorted(self._policies):
            policy = self._policies[zone]
            if not policy.state.active or policy.state.phase != "active":
                continue
            belief_after = self._filters[zone].state
            retained_hold = (
                zone in retained_endpoint_holds
                and policy.state.activation_provenance == "evidence"
            )
            if retained_hold or policy.state.retained_endpoint_hold:
                # Hold loss is evaluated normally, with the qualified/transfer
                # frontier, never by this pre-input deadline shortcut.
                if retained_hold and not policy.state.retained_endpoint_hold:
                    update = policy.evaluate(
                        at,
                        belief_before_by_zone[zone],
                        belief_after,
                        local_state=None,
                        local_effect=None,
                        authorization=None,
                        processing_at=processing_at,
                        asserted_stay_hold=zone in asserted_stay_holds,
                        retained_endpoint_hold=True,
                    )
                    decisions.append(update.decision)
                continue
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
            release_frontier = belief_after.path_displaced_at
            if release_frontier is None and zone in settled_endpoint_zones:
                release_frontier = belief_after.qualified_departure_at
            qualified_progress = (
                policy.state.activation_provenance == "evidence"
                and release_frontier is not None
            )
            if qualified_progress:
                below_since = max(
                    below_since or at, release_frontier or at
                )
            pending = policy.state.pending_release_since or below_since
            if pending is None:
                continue
            if at < pending + calibration.release_dwell and not (
                qualified_progress and policy.state.pending_release_since is None
            ):
                continue
            # Holds have ended: preserve the first eligible selected-displacement
            # or legacy qualified-departure crossing, never protected time.
            # Otherwise repeated ignored inputs discard progress before full dwell
            # and keep moving its start. This is a stored timer, not input evidence.
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
            if update.event is not None:
                events.append(update.event)
        return tuple(decisions), tuple(events)

    def _evaluate_retention_loss(
        self,
        at: datetime,
        processing_at: datetime,
        retained_beliefs: Mapping[str, ZoneBeliefState],
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        """Finish elapsed hold loss even when the external input is rejected."""

        if not retained_beliefs:
            return (), ()
        retained_holds = self._retained_endpoint_hold_zones()
        asserted_holds = self._asserted_stay_hold_zones()
        decisions: list[PolicyDecision] = []
        events: list[PolicyEvent] = []
        for zone, before in sorted(retained_beliefs.items()):
            policy = self._policies[zone]
            if not policy.state.retained_endpoint_hold or zone in retained_holds:
                continue
            belief = self._filters[zone].state
            below_since = self._filters[zone].threshold_crossed_at(
                before, POLICY_CALIBRATIONS[belief.profile_name].off_threshold, at
            )
            update = policy.evaluate(
                at, before, belief,
                local_state=None,
                local_effect=None,
                authorization=None,
                processing_at=processing_at,
                below_threshold_since=below_since,
                asserted_stay_hold=zone in asserted_holds,
            )
            decisions.append(update.decision)
            if update.event is not None:
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
        settled_endpoint_zones: frozenset[str] | None = None,
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
        retained_endpoint_holds = self._retained_endpoint_hold_zones(
            settled_endpoint_zones
        )
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
                if belief_before_by_zone is not None and zone in belief_before_by_zone
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
                retained_endpoint_hold=zone in retained_endpoint_holds,
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

    def _retained_endpoint_hold_zones(
        self, settled_endpoint_zones: frozenset[str] | None = None,
    ) -> frozenset[str]:
        """Only the selected route covers occupancy; rejected supports do not."""

        return self._selected_paths.covered_zones

    def _asserted_stay_hold_zones(self) -> frozenset[str]:
        return frozenset(
            zone for zone, filter_ in self._filters.items()
            if filter_.state.physical_hold
            and self._policies[zone].state.activation_provenance == "evidence"
        ) | frozenset(
            state.zone
            for state in self._episodes.states
            if SHARED_PROFILES[state.profile_name].role == "stay"
            and state.zone in self._selected_paths.covered_zones
            and self._filters[state.zone].state.path_displaced_at is None
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

    def _physical_witnesses(
        self, states: tuple[EpisodeState, ...], held_zones: frozenset[str],
    ) -> tuple[EpisodeState, ...]:
        """Real current origins protect locally even after route consumption."""

        sources = {source.node_id: source for source in self._selected_paths.sources}
        nodes = {node.node_id: node for node in self._nodes}
        return tuple(
            state for state in states
            if state.profile_name == "stay_presence"
            and not nodes[state.node_id].interaction_aliases
            and state.episode_id is not None
            and sources[state.node_id].episode_id == state.episode_id
            and sources[state.node_id].origin in {"ordinary", "correlated"}
            and (
                state.known_on
                or (
                    state.zone in held_zones
                    and state.status == "clearing"
                    and state.clear_deadline is not None
                    and all(value == "off" for _, value in state.alias_states)
                )
            )
        )

    def _reconcile_physical_holds(
        self, at: datetime, states: tuple[EpisodeState, ...] | None = None,
    ) -> dict[str, ZoneBeliefState]:
        """No policy feedback: derive context, then consume local hold loss."""

        held = frozenset(
            zone for zone, filter_ in self._filters.items()
            if filter_.state.physical_hold
        )
        witnesses = self._physical_witnesses(
            self._episodes.states if states is None else states, held,
        ) if self._count.state.expected_count > 0 else ()
        losses: dict[str, ZoneBeliefState] = {}
        for zone, filter_ in self._filters.items():
            local = tuple(state for state in witnesses if state.zone == zone)
            asserted = tuple(state for state in local if state.known_on)
            if asserted and (
                filter_.state.context != "asserted"
                or filter_.state.generation_episode_id not in {
                    state.episode_id for state in asserted
                }
            ):
                selected = max(asserted, key=lambda state: (
                    state.started_at or at, state.node_id,
                ))
                assert selected.episode_id is not None
                filter_.reselect_asserted_context(selected.episode_id, at)
            belief = filter_.set_physical_hold(bool(local), at)
            if zone in held and not local:
                losses[zone] = belief
            if (zone in held) != bool(local):
                policy = self._policies[zone]
                if (
                    policy.state.active
                    and policy.state.activation_provenance == "evidence"
                ):
                    # This frontier can only cancel or start pending release:
                    # the full positive dwell cannot expire on hold loss itself.
                    policy.evaluate(
                        at, belief, belief, local_state=None, local_effect=None,
                        authorization=None, below_threshold_since=at,
                        retained_endpoint_hold=(
                            zone in self._selected_paths.covered_zones
                        ),
                    )
        return losses

    def assert_mutation_allowed(self) -> None:
        """Publications may read projections but cannot nest model mutations."""

        if self._in_decision_callback:
            raise ValueError("Model mutation is forbidden during decision callback")

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
        interaction_traversal = row.traversal_reason == "local_interaction" or (
            interaction_evidence and row.traversal_reason == "selected_path"
        )
        if interaction_evidence != interaction_traversal:
            raise ValueError("Interaction audit provenance is inconsistent")
        if row.traversal_reason == "selected_path":
            if (
                row.node_id is None or row.episode_id is None
                or row.episode_id not in row.evidence_ids
                or row.local_evidence_kind not in {
                    "positive", "correlated_positive", "interaction",
                }
                or not row.local_trustworthy or not row.authorization_authorized
                or row.count_zero or row.health_warning
            ):
                raise ValueError("Selected-path audit identity is incomplete")
            sources = tuple(key for key in row.evidence_ids if key != row.episode_id)
            target, created_at = self._episode_reference(
                row.episode_id, episodes, frontier, exact=False, selected=True,
            )
            if (
                target.node_id != row.node_id or target.zone != row.zone
                or created_at != row.event_at or len(sources) > 1
                or (not sources and not interaction_evidence)
            ):
                raise ValueError("Selected-path audit target is incompatible")
            for source_id in sources:
                source, source_at = self._episode_reference(
                    source_id, episodes, frontier, exact=False, selected=True,
                )
                if source_at > row.event_at or not self._selected_step(
                    source.node_id, target.node_id,
                ):
                    raise ValueError("Selected-path audit source is incompatible")
        if row.traversal_reason == "supported_gap_acquisition":
            if (
                row.node_id is None
                or row.episode_id is None
                or len(row.evidence_ids) != 2
                or row.episode_id not in row.evidence_ids
                or row.local_evidence_kind not in {"positive", "correlated_positive"}
                or not row.local_trustworthy
                or not row.authorization_authorized
                or row.count_zero
                or row.health_warning
            ):
                raise ValueError("Supported-gap audit identity is incomplete")
            target, target_at = self._episode_reference(
                row.episode_id, episodes, frontier, exact=False
            )
            source_id = next(
                value for value in row.evidence_ids if value != row.episode_id
            )
            source, source_at = self._episode_reference(
                source_id, episodes, frontier, exact=False
            )
            if (
                target.node_id != row.node_id
                or target.zone != row.zone
                or target_at != row.event_at
                or not gap_geometry_valid(
                    self._map, {node.node_id: node for node in self._nodes},
                    source.node_id, target.node_id, source_at, row.event_at,
                )
            ):
                raise ValueError("Supported-gap audit is not episode-derived")
        if row.traversal_reason == "settled_adjacent_transfer":
            if (
                row.node_id is None
                or row.episode_id is None
                or len(row.evidence_ids) != 2
                or len(set(row.evidence_ids)) != 2
                or row.episode_id not in row.evidence_ids
                or row.local_evidence_kind not in {"positive", "correlated_positive"}
                or not row.local_trustworthy
                or not row.authorization_authorized
            ):
                raise ValueError("Settled-adjacent audit identity is incomplete")
            target, target_at = self._episode_reference(
                row.episode_id, episodes, frontier, exact=False
            )
            source_id = next(
                value for value in row.evidence_ids if value != row.episode_id
            )
            source, source_at = self._episode_reference(
                source_id, episodes, frontier, exact=False
            )
            source_node = next(
                node for node in self._nodes if node.node_id == source.node_id
            )
            if (
                target.node_id != row.node_id
                or target.zone != row.zone
                or target_at != row.event_at
                or source_at > row.event_at
                or source_node.interaction_aliases
                or SHARED_PROFILES[source_node.profile_name].role != "stay"
                or not self._direct_different_zone_pair(
                    (source.node_id, target.node_id)
                )
            ):
                raise ValueError("Settled-adjacent audit is not episode-derived")
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
        # PathHealth.restore owns warning/occurrence integrity. Legacy episode
        # warning flags are neither witnesses nor an alternate warning emitter.
        if snapshot.count_conflicts:
            raise ValueError("Selected-path engine cannot restore count degradation")
        for selected_source in snapshot.selected_sources:
            if selected_source.episode_id is not None:
                physical, _ = self._episode_reference(
                    selected_source.episode_id,
                    episodes,
                    at,
                    exact=False,
                    selected=True,
                )
                # Only the exact current episode can prove its original effect.
                # Resets may clear correlation without changing the episode;
                # the converse implication (or historical equality) is unsafe.
                if (
                    physical.episode_id == selected_source.episode_id
                    and physical.cadence_correlated
                    and selected_source.origin != "correlated"
                ):
                    raise ValueError("Selected source contradicts physical correlation")
        for selected_path in snapshot.selected_paths:
            if selected_path is not None:
                for visit in selected_path.occurrences:
                    self._episode_reference(
                        visit.episode_id, episodes, at, exact=False, selected=True,
                    )
        for grant in snapshot.selected_prediction_grants:
            self._validate_selected_prediction_grant(grant, episodes, snapshot)
        if any(
            item.reason == "unsupported_jump" and item.cleared_at is None
            and item.node_id in self._selected_paths.covered_nodes
            for item in snapshot.reliability_warning_occurrences
        ):
            raise ValueError("Covered node cannot retain an active unsupported jump")
        for health in snapshot.path_health:
            aliases = tuple(value for _, value in episodes[health.node_id].alias_states)
            phase = (
                "on" if "on" in aliases else "off"
                if all(value == "off" for value in aliases) else "unknown"
            )
            if health.phase != phase or (
                (phase == "on"
                 and health.node_id not in self._selected_paths.covered_nodes)
                != (health.unsupported_started_at is not None)
            ):
                raise ValueError(
                    "Path health disagrees with physical aggregate/coverage"
                )
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
            if state.cadence_warning or state.health_warning:
                raise ValueError("Selected-path engine cannot restore legacy warnings")

        self._selected_paths.reconcile(snapshot.episode_states, at)
        if (
            self._selected_paths.paths != snapshot.selected_paths
            or self._selected_paths.sources != snapshot.selected_sources
        ):
            raise ValueError("Selected authority disagrees with physical generations")

        held = frozenset(
            belief.zone for belief in snapshot.belief_states if belief.physical_hold
        )
        witnesses = self._physical_witnesses(snapshot.episode_states, held)
        physical_zones = frozenset(state.zone for state in witnesses) if (
            snapshot.count_state.expected_count > 0
        ) else frozenset()
        for belief in snapshot.belief_states:
            if belief.physical_hold != (belief.zone in physical_zones):
                raise ValueError("Physical hold disagrees with live presence witnesses")
            if (
                belief.path_displaced_at is None
                and belief.zone not in self._selected_paths.covered_zones
                and belief.generation_episode_id is not None
                and any(
                    visit.episode_id == belief.generation_episode_id
                    and visit.zone == belief.zone and not visit.branch_active
                    for path in snapshot.selected_paths if path is not None
                    for visit in path.occurrences
                )
            ):
                raise ValueError("Retired selected generation has no displacement")
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
                if (
                    belief.qualified_departure_at is not None
                    and belief.qualified_departure_at < _created_at
                ):
                    raise ValueError("Qualified departure predates belief generation")
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
                    # Physical-history records outlive the four selected visits.
                    # Generation ordering permits equal event times here; this
                    # grants no token, selection or prediction authority.
                    selected=True,
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
                    selected=True,
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
                    selected=policy.activation_reason in {
                        "selected_path", "prediction_confirmed",
                    },
                )
                physical_node = physical_nodes[state.node_id]
                interaction_episode = bool(physical_node.interaction_aliases)
                if policy.activation_reason == "selected_path":
                    authorization = TraversalAuthorization(
                        state.node_id, policy.zone, policy.activation_episode_id,
                        policy.activation_at, True, "selected_path",
                        track_confidence=policy.activation_track_confidence,
                        path_node_ids=policy.activation_path_node_ids,
                        provenance_kind=policy.activation_provenance_kind,
                        selected_source_episode_ids=policy.activation_source_episode_ids,
                    )
                    if (
                        created_at != policy.activation_at
                        or state.zone != policy.zone
                        or (not authorization.selected_source_episode_ids
                            and not interaction_episode)
                        or any(
                            node_id not in self._map.nodes
                            for node_id in authorization.path_node_ids
                        )
                        or any(not self._selected_step(left, right)
                            for left, right in zip(
                                authorization.path_node_ids,
                                authorization.path_node_ids[1:], strict=False,
                            ))
                    ):
                        raise ValueError("Selected activation is not episode-derived")
                    for source_id in authorization.selected_source_episode_ids:
                        self._episode_reference(
                            source_id, episodes, at, exact=False, selected=True,
                        )
                    continue
                expected_provenance = {
                    "adjacent_authorized": "adjacent",
                    "boundary_authorized": "boundary",
                    "local_interaction": "local_interaction",
                    "missed_edge_authorized": "missed_edge",
                    "prediction_confirmed": "prediction_confirmation",
                    "provisional_track_acquired": "adjacent_pair",
                    "same_zone_authorized": "same_zone",
                    "settled_adjacent_transfer": "settled_adjacent_transfer",
                    "supported_gap_acquisition": "supported_gap_acquisition",
                    "settled_endpoint_reacquired": "settled_endpoint",
                    "track_confirmed": "adjacent",
                }[policy.activation_reason]
                source_references = tuple(
                    self._episode_reference(
                        episode_id,
                        episodes,
                        at,
                        exact=False,
                    )
                    for episode_id in policy.activation_source_episode_ids
                )
                source_states = tuple(source for source, _ in source_references)
                path = policy.activation_path_node_ids
                source_nodes = {source.node_id for source in source_states}
                requires_source = policy.activation_reason not in {
                    "boundary_authorized",
                    "local_interaction",
                    "prediction_confirmed",
                    "settled_endpoint_reacquired",
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
                        and policy.activation_reason != "supported_gap_acquisition"
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
                    or (
                        policy.activation_reason == "settled_endpoint_reacquired"
                        and (
                            not (
                                (
                                    policy.activation_track_confidence == "confirmed"
                                    and len(path) == 3
                                )
                                or (
                                    policy.activation_track_confidence == "provisional"
                                    and len(path) == 1
                                )
                            )
                            or source_states
                        )
                    )
                    or (
                        policy.activation_reason == "supported_gap_acquisition"
                        and (
                            policy.activation_track_confidence != "provisional"
                            or path != (state.node_id,)
                            or len(source_references) != 1
                            or not gap_geometry_valid(
                                self._map, physical_nodes,
                                source_states[0].node_id, state.node_id,
                                source_references[0][1], policy.activation_at,
                            )
                        )
                    )
                    or (
                        policy.activation_reason == "settled_adjacent_transfer"
                        and (
                            policy.activation_track_confidence != "provisional"
                            or not self._direct_different_zone_pair(path)
                            or len(source_references) != 1
                            or source_states[0].node_id != path[0]
                            or source_references[0][1] > policy.activation_at
                            or physical_nodes[path[0]].interaction_aliases
                            or SHARED_PROFILES[
                                physical_nodes[path[0]].profile_name
                            ].role != "stay"
                        )
                    )
                ):
                    raise ValueError(
                        "Evidence-active policy is not bound to its acquisition episode"
                    )

        SnapshotValidator(
            self._map, self._nodes, self._supports._confirmed_strength,
        ).validate(snapshot)

    def _validate_support_snapshot(
        self,
        snapshot: ZoneModelSnapshot,
        active_tokens: Mapping[str, TraversalToken],
        retained_tokens: Mapping[str, TraversalToken],
    ) -> None:
        """Bind persisted supports to current physical and traversal state."""

        SnapshotValidator(
            self._map, self._nodes, self._supports._confirmed_strength,
        ).validate_support_snapshot(snapshot, active_tokens, retained_tokens)

    def _direct_different_zone_pair(self, path: tuple[str, ...]) -> bool:
        """A handoff is one physical edge, never a bounded missed-edge path."""

        return direct_different_zone_pair(self._map, path)

    def _validate_count_snapshot(self, snapshot: ZoneModelSnapshot) -> None:
        """Require stored count conflicts to match current support evidence."""

        SnapshotValidator(
            self._map, self._nodes, self._supports._confirmed_strength,
        ).validate_count_snapshot(snapshot)

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
            selected = lease.authority_kind == "selected_prediction_grant"
            state, created_at = self._episode_reference(
                lease.source_episode_id,
                episodes,
                self._updated_at,
                exact=False,
                selected=selected,
            )
            token = tokens.get(lease.source_episode_id)
            target_state = episodes.get(lease.target_node_id)
            if not selected and (
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
            if selected and (
                state.node_id != lease.current_node_id or created_at != lease.created_at
                or state.status in {"unavailable", "degraded"}
            ):
                raise ValueError("Selected prediction lease source is invalid")
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

    def _validate_selected_prediction_grant(
        self, grant: SelectedPredictionGrant,
        episodes: Mapping[str, EpisodeState], snapshot: ZoneModelSnapshot,
    ) -> None:
        authorization = grant.authorization
        source_id, current_id, target_id, episode_id = grant.key
        if (
            any(node not in self._map.nodes for node in authorization.path_node_ids)
            or target_id not in self._map.nodes
            or current_id not in self._map.nodes[source_id].adjacent
            or target_id not in self._map.nodes[current_id].adjacent
            or authorization.target_zone != self._map.nodes[current_id].occupancy_zone
            or any(not self._selected_step(left, right) for left, right in zip(
                authorization.path_node_ids,
                authorization.path_node_ids[1:],
                strict=False,
            ))
        ):
            raise ValueError("Selected prediction grant geometry is invalid")
        sources = {source.node_id: source for source in snapshot.selected_sources}
        for reference in (episode_id, *authorization.selected_source_episode_ids):
            state, origin_at = self._episode_reference(
                reference, episodes, snapshot.updated_at, exact=False, selected=True,
            )
            _, generation, _ = _physical_episode_reference(reference)
            source = sources.get(state.node_id)
            if source is None or source.episode_id is None or source.at is None:
                raise ValueError("Selected prediction grant lacks source ledger")
            _, ledger_generation, _ = _physical_episode_reference(source.episode_id)
            if (
                origin_at > authorization.authorized_at
                or generation > ledger_generation or origin_at > source.at
                or (generation == ledger_generation and reference != source.episode_id)
                or (generation == ledger_generation and not source.consumed)
                or (reference == episode_id and generation == ledger_generation
                    and source.origin != "ordinary")
            ):
                raise ValueError("Selected prediction grant generation is invalid")
        current = episodes[current_id]
        if (
            current.status in {"unavailable", "degraded"}
            or (current.status == "baseline"
                and not all(value == "off" for _, value in current.alias_states))
            or current.health_warning or current.cadence_warning
            or (current.episode_id == episode_id and current.cadence_correlated)
            or (current.episode_id == episode_id
                and current.started_at != authorization.authorized_at)
        ):
            raise ValueError(
                "Selected prediction grant source is not ordinary available"
            )

    def _bounded_path_step(self, source: str, target: str) -> bool:
        return bounded_path_step(self._map, source, target)

    def _selected_step(self, source: str, target: str) -> bool:
        """Selected observations cross one real edge or stay in the same zone."""

        return bool(
            source in self._map.nodes and target in self._map.nodes
            and (
                self._map.nodes[source].occupancy_zone
                == self._map.nodes[target].occupancy_zone
                or target in self._map.neighbors(source)
            )
        )

    @staticmethod
    def _episode_reference(
        episode_id: str,
        states: Mapping[str, EpisodeState],
        frontier: datetime,
        *,
        exact: bool,
        selected: bool = False,
    ) -> tuple[EpisodeState, datetime]:
        return episode_reference(
            episode_id, states, frontier, exact=exact, selected=selected,
        )

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
            snapshot.selected_prediction_grants,
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
