"""Release-0.1.20 comparator retained for test and replay validation only."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime

from ..automation_policy import AutomationPolicy
from ..events import OccupancyEvent
from ..joint_filter import JointOccupancyFilter
from ..markov import MarkovChain
from ..model import PredictiveMap
from ..occupancy_graph import ZoneGraph
from ..occupancy_persistence import (
    RestoredOccupancyState,
    serialize_occupancy_state,
)
from ..prediction import PredictionManager
from .port import EngineDiagnostics


class LegacyInferenceEngine:
    """Adapter for the release-0.1.20 filter, policy, and prediction stack."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        graph: ZoneGraph,
        expected_occupants: int,
        chain: MarkovChain | None,
    ) -> None:
        self._map = predictive_map
        self._expected_occupants = expected_occupants
        self._filter: JointOccupancyFilter | None = None
        self._policy = AutomationPolicy(graph)
        self._predictions = PredictionManager(predictive_map, chain)

    @property
    def filter(self) -> JointOccupancyFilter | None:
        return self._filter

    @property
    def policy(self) -> AutomationPolicy:
        return self._policy

    @property
    def predictions(self) -> PredictionManager:
        return self._predictions

    @property
    def diagnostics(self) -> EngineDiagnostics:
        occupancy_filter = self._filter
        if occupancy_filter is None:
            return EngineDiagnostics(
                self._expected_occupants,
                {},
                {},
                1.0,
                0.0,
                None,
                None,
                (),
            )
        last_update = occupancy_filter.last_update
        posterior = occupancy_filter.posterior
        return EngineDiagnostics(
            occupancy_filter.expected_occupants,
            occupancy_filter.occupied_marginals,
            occupancy_filter.count_marginals,
            math.fsum(
                math.exp(hypothesis.log_probability)
                for hypothesis in posterior.hypotheses
            ),
            posterior.pruned_probability,
            None if last_update is None else last_update.provenance.disposition,
            posterior.updated_at,
            (),
        )

    def ensure(self, now: datetime) -> None:
        self._ensure_filter(now)

    def _ensure_filter(self, now: datetime) -> JointOccupancyFilter:
        if self._filter is None:
            self._filter = JointOccupancyFilter(
                self._map,
                self._expected_occupants,
                now,
            )
        return self._filter

    def observe(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool,
    ) -> EngineDiagnostics:
        update = self._ensure_filter(event.event_at).observe(event)
        self._policy.apply(update, emit_activation=emit_activation)
        if emit_activation:
            self._predictions.apply(update)
            self._predictions.learn(update)
        return self.diagnostics

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> EngineDiagnostics:
        now = max(
            (event.event_at for event in events),
            default=datetime.now().astimezone(),
        )
        updates = self._ensure_filter(now).bootstrap(events, cold_start=cold_start)
        for update in updates:
            self._policy.apply(update, emit_activation=False)
        return self.diagnostics

    def finalize(self, now: datetime) -> bool:
        occupancy_filter = self._filter
        evidence_changed = (
            False
            if occupancy_filter is None
            else occupancy_filter.reinforce_asserted_evidence(
                now,
                advance_context_validity=False,
            )
        )
        policy_changed = self._policy.expire(
            now,
            None if occupancy_filter is None else occupancy_filter.occupied_marginals,
            None
            if occupancy_filter is None
            else occupancy_filter.asserted_positive_evidence(now),
        )
        prediction_changed = self._predictions.expire(now)
        return evidence_changed or policy_changed or prediction_changed

    def reconcile_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
        *,
        reconcile_policy: bool,
    ) -> EngineDiagnostics:
        previous = (
            self._filter.expected_occupants
            if self._filter is not None
            else self._expected_occupants
        )
        self._expected_occupants = expected_occupants
        occupancy_filter = self._ensure_filter(now)
        if occupancy_filter.expected_occupants != expected_occupants:
            occupancy_filter.set_expected_occupants(expected_occupants, now)
        if reconcile_policy:
            self._policy.reconcile_count(
                expected_occupants,
                now,
                evidence_id,
                occupancy_filter.occupied_marginals,
            )
        self._predictions.reconcile_count(previous, expected_occupants)
        return self.diagnostics

    def enter_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
    ) -> EngineDiagnostics:
        previous = self._expected_occupants
        self._expected_occupants = 0
        if self._filter is not None:
            self._filter.set_expected_occupants(0, now)
        self._policy.enter_unsupported_count(
            expected_occupants,
            evidence_id,
            now,
        )
        self._predictions.reconcile_count(previous, 0)
        return self.diagnostics

    def serialize(
        self,
        now: datetime,
        transition_counts: Mapping[str, Mapping[str, float]],
    ) -> dict[str, object]:
        occupancy_filter = self._ensure_filter(now)
        return serialize_occupancy_state(
            self._map,
            occupancy_filter.posterior,
            self._policy.states,
            self._predictions.leases,
            occupancy_filter.observations.entity_states,
            transition_counts,
            directional_contexts=occupancy_filter.directional_contexts,
            pending_departures=self._policy.pending_departures,
            update_sequence=occupancy_filter.update_sequence,
            policy_audit=self._policy.policy_audit,
            route_counts=self._predictions.route_counts,
            route_contexts=self._predictions.route_contexts,
            consumed_censored_paths=occupancy_filter.consumed_censored_paths,
        )

    def restore(self, restored: object) -> EngineDiagnostics:
        if not isinstance(restored, RestoredOccupancyState):
            raise TypeError("Legacy engine requires RestoredOccupancyState")
        occupancy_filter = JointOccupancyFilter(
            self._map,
            self._expected_occupants,
            restored.posterior.updated_at,
        )
        occupancy_filter.restore_posterior(restored.posterior)
        occupancy_filter.restore_directional_contexts(
            restored.directional_contexts,
            restored.update_sequence,
        )
        occupancy_filter.observations.restore_entity_states(restored.entity_states)
        occupancy_filter.restore_consumed_censored_paths(
            restored.consumed_censored_paths
        )
        self._filter = occupancy_filter
        self._policy.restore_states(restored.policy_states)
        self._policy.restore_policy_audit(restored.policy_audit)
        self._policy.restore_pending_departures(restored.pending_departures)
        self._predictions.restore_leases(
            restored.prediction_leases,
            restored.posterior.updated_at,
        )
        self._predictions.restore_route_state(
            restored.route_counts,
            restored.route_contexts,
        )
        return self.diagnostics
