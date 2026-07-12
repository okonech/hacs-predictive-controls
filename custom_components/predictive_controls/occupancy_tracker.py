from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from .automation_policy import AutomationPolicy
from .events import OccupancyEvent
from .joint_filter import JointOccupancyFilter
from .markov import MarkovChain
from .model import PredictiveMap
from .occupancy_graph import ZoneGraph
from .occupancy_persistence import (
    RestoredOccupancyState,
    serialize_occupancy_state,
)
from .occupancy_scoring import status_for_confidence
from .occupancy_state import (
    DirectionalContext,
    HypothesisKey,
    MovementEvidence,
    ObservationProvenance,
    PolicyDecision,
    PredictionLease,
    WeightedHypothesis,
    ZonePolicyState,
)
from .prediction import PredictionManager


@dataclass(frozen=True)
class ZoneState:
    """Current inferred occupancy state for one zone."""

    zone: str
    confidence: float = 0.0
    status: str = "rejected"
    occupancy_behavior: str = "sustained"
    active_since: datetime | None = None
    last_evidence_at: datetime | None = None
    last_clear_at: datetime | None = None
    updated_at: datetime | None = None
    last_node_id: str | None = None
    reason: str = "no evidence"
    explanation: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ZoneUpdate:
    """Result of applying one occupancy inference update."""

    event: OccupancyEvent
    previous: ZoneState
    current: ZoneState


@dataclass(frozen=True)
class TrackerConfig:
    """Configuration for anonymous multi-occupant occupancy inference."""

    expected_occupants: int = 0
    corridor_radius: int = 1
    recent_evidence_window: timedelta = timedelta(minutes=15)
    join_transition_window: timedelta = timedelta(minutes=3)
    join_slot_retention: timedelta = timedelta(minutes=5)
    join_destination_min_confidence: float = 0.35
    departure_transition_window: timedelta = timedelta(minutes=3)
    departure_retention: timedelta = timedelta(minutes=5)
    departure_source_min_confidence: float = 0.35
    entry_plausibility_window: timedelta = timedelta(seconds=30)
    activation_plausibility_window: timedelta = timedelta(seconds=5)
    trail_window: timedelta = timedelta(minutes=3)

    @property
    def occupant_limit(self) -> int | None:
        return self.expected_occupants if self.expected_occupants > 0 else None


@dataclass(frozen=True)
class AnonymousTrack:
    """Compatibility shape for historical diagnostic payloads."""

    track_id: str
    zone: str
    confidence: float
    active: bool
    last_evidence_at: datetime | None
    source_entities: tuple[str, ...]


@dataclass(frozen=True)
class InferredJoinSlot:
    """Compatibility shape for historical diagnostic payloads."""

    zone: str
    source_zone: str
    source_node_id: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class InferredDeparture:
    """Compatibility shape for historical diagnostic payloads."""

    zone: str
    via_zone: str
    via_node_id: str
    destination_zone: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class EntryPlausibility:
    """Compatibility shape for historical diagnostic payloads."""

    zone: str
    source_zone: str
    source_node_id: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ActivationPlausibility:
    """Compatibility shape for historical diagnostic payloads."""

    zone: str
    reason: str
    source_zone: str | None
    source_node_id: str | None
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TrackerDiagnostics:
    """Structured diagnostics for panel and status payloads."""

    expected_occupants: int
    tracks: tuple[AnonymousTrack, ...]
    protected_tracks: tuple[str, ...]
    protected_corridor: tuple[str, ...]
    inferred_join_slots: tuple[InferredJoinSlot, ...]
    inferred_departures: tuple[InferredDeparture, ...]
    prediction_hints: dict[str, float]
    dwell_seconds: dict[str, dict[str, float | int]]
    entry_plausibilities: tuple[EntryPlausibility, ...] = ()
    activation_plausibilities: tuple[ActivationPlausibility, ...] = ()
    joint_posterior: tuple[WeightedHypothesis, ...] = ()
    joint_occupied_marginals: dict[str, float] = field(default_factory=dict)
    joint_count_marginals: dict[str, tuple[float, ...]] = field(default_factory=dict)
    joint_policy_states: dict[str, ZonePolicyState] = field(default_factory=dict)
    joint_policy_decisions: tuple[PolicyDecision, ...] = ()
    joint_prediction_leases: tuple[PredictionLease, ...] = ()
    joint_prediction_hints: dict[str, float] = field(default_factory=dict)
    joint_last_provenance: ObservationProvenance | None = None
    joint_movement_evidence: tuple[MovementEvidence, ...] = ()
    joint_directional_contexts: dict[
        HypothesisKey,
        tuple[DirectionalContext, ...],
    ] = field(default_factory=dict)
    joint_posterior_entropy: float = 0.0
    joint_pruned_probability: float = 0.0
    joint_performance: dict[str, float | int] = field(default_factory=dict)
    joint_restore_status: str = "not_attempted"
    joint_restore_reason: str | None = None
    joint_requested_occupants: int = 0
    joint_unsupported_count: int | None = None


class OccupancyTracker:
    """Joint anonymous occupancy facade used by runtime and public entities."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        config: TrackerConfig | None = None,
        chain: MarkovChain | None = None,
    ) -> None:
        requested_config = config or TrackerConfig()
        if requested_config.expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        self._requested_expected_occupants = requested_config.expected_occupants
        self._last_supported_expected_occupants = min(
            requested_config.expected_occupants,
            2,
        )
        self._unsupported_count = (
            requested_config.expected_occupants
            if requested_config.expected_occupants > 2
            else None
        )
        self.config = (
            replace(requested_config, expected_occupants=0)
            if self._unsupported_count is not None
            else requested_config
        )
        self._map = predictive_map
        self.graph = ZoneGraph.from_map(predictive_map)
        self._base_states = {
            zone: ZoneState(
                zone=zone,
                occupancy_behavior=predictive_map.zone_occupancy_behavior(zone),
            )
            for zone in predictive_map.zones()
        }
        self._recent_events: list[OccupancyEvent] = []
        self._joint_filter: JointOccupancyFilter | None = None
        self._joint_policy = AutomationPolicy(self.graph)
        self._joint_predictions = PredictionManager(predictive_map, chain)
        self._joint_restore_status = "not_attempted"
        self._joint_restore_reason: str | None = None

    @property
    def states(self) -> dict[str, ZoneState]:
        return self.joint_states

    @property
    def joint_states(self) -> dict[str, ZoneState]:
        if self._joint_filter is None:
            return self._base_states.copy()
        last_update = self._joint_filter.last_update
        provenance = None if last_update is None else last_update.provenance
        occupied_marginals = self._joint_filter.occupied_marginals
        return {
            zone: self._project_zone_state(
                zone,
                base,
                provenance,
                occupied_marginals.get(zone, 0.0),
            )
            for zone, base in self._base_states.items()
        }

    @property
    def joint_prediction_probabilities(self) -> dict[str, float]:
        return self._joint_predictions.probabilities

    @property
    def requested_expected_occupants(self) -> int:
        return self._requested_expected_occupants

    @property
    def recent_events(self) -> tuple[OccupancyEvent, ...]:
        return tuple(self._recent_events)

    @property
    def tracks(self) -> tuple[AnonymousTrack, ...]:
        return ()

    @property
    def diagnostics(self) -> TrackerDiagnostics:
        joint_filter = self._joint_filter
        last_update = None if joint_filter is None else joint_filter.last_update
        return TrackerDiagnostics(
            expected_occupants=self.config.expected_occupants,
            tracks=(),
            protected_tracks=(),
            protected_corridor=(),
            inferred_join_slots=(),
            inferred_departures=(),
            prediction_hints={},
            dwell_seconds={},
            joint_posterior=()
            if joint_filter is None
            else joint_filter.posterior.hypotheses,
            joint_occupied_marginals={}
            if joint_filter is None
            else joint_filter.occupied_marginals,
            joint_count_marginals={}
            if joint_filter is None
            else joint_filter.count_marginals,
            joint_policy_states=self._joint_policy.states,
            joint_policy_decisions=self._joint_policy.last_decisions,
            joint_prediction_leases=self._joint_predictions.leases,
            joint_prediction_hints=self._joint_predictions.probabilities,
            joint_last_provenance=None
            if last_update is None
            else last_update.provenance,
            joint_movement_evidence=()
            if last_update is None
            else last_update.movement_evidence,
            joint_directional_contexts={}
            if joint_filter is None
            else joint_filter.directional_contexts,
            joint_posterior_entropy=0.0
            if joint_filter is None
            else -math.fsum(
                math.exp(hypothesis.log_probability) * hypothesis.log_probability
                for hypothesis in joint_filter.posterior.hypotheses
                if hypothesis.log_probability != -math.inf
            ),
            joint_pruned_probability=0.0
            if joint_filter is None
            else joint_filter.posterior.pruned_probability,
            joint_performance={}
            if joint_filter is None
            else joint_filter.performance_metrics,
            joint_restore_status=self._joint_restore_status,
            joint_restore_reason=self._joint_restore_reason,
            joint_requested_occupants=self._requested_expected_occupants,
            joint_unsupported_count=self._unsupported_count,
        )

    def state_for_zone(self, zone: str) -> ZoneState:
        base = self._base_states.get(zone, ZoneState(zone=zone))
        if self._joint_filter is None or zone not in self._base_states:
            return base
        last_update = self._joint_filter.last_update
        provenance = None if last_update is None else last_update.provenance
        return self._project_zone_state(
            zone,
            base,
            provenance,
            self._joint_filter.occupied_marginals.get(zone, 0.0),
        )

    def observe(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool = True,
    ) -> ZoneUpdate:
        previous = self.state_for_zone(event.zone)
        self._observe_joint(event, emit_activation=emit_activation)
        self._recent_events = [*self._recent_events[-24:], event]
        return ZoneUpdate(event, previous, self.state_for_zone(event.zone))

    def refresh_active(self, now: datetime) -> tuple[ZoneUpdate, ...]:
        self._joint_policy.expire(now)
        self._joint_predictions.expire(now)
        return ()

    def expire_transient_state(self, now: datetime) -> bool:
        policy_changed = self._joint_policy.expire(now)
        prediction_changed = self._joint_predictions.expire(now)
        return policy_changed or prediction_changed

    def suppress_last_activation(self, reason_code: str) -> bool:
        """Suppress the last event's activation before runtime publication."""

        if self._joint_filter is None or self._joint_filter.last_update is None:
            return False
        return self._joint_policy.suppress_activation(
            self._joint_filter.last_update.provenance.zone,
            reason_code,
        )

    def reconcile_expected_occupants(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "occupant_count_change",
    ) -> None:
        if expected_occupants > 2:
            self.reject_unsupported_count(expected_occupants, now, evidence_id)
            return
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        recovering_from_unsupported = self._unsupported_count is not None
        previous_supported = self._last_supported_expected_occupants
        self._requested_expected_occupants = expected_occupants
        self._unsupported_count = None
        previous = (
            self._joint_filter.expected_occupants
            if self._joint_filter is not None
            else self.config.expected_occupants
        )
        self.config = replace(self.config, expected_occupants=expected_occupants)
        if self._joint_filter is None:
            self._joint_filter = JointOccupancyFilter(
                self._map,
                expected_occupants,
                now,
            )
        else:
            self._joint_filter.set_expected_occupants(expected_occupants, now)
        if not recovering_from_unsupported or expected_occupants < previous_supported:
            self._joint_policy.reconcile_count(
                expected_occupants,
                now,
                evidence_id,
                self._joint_filter.occupied_marginals,
            )
        self._joint_predictions.reconcile_count(previous, expected_occupants)
        self._last_supported_expected_occupants = expected_occupants

    def reject_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "unsupported_occupant_count",
    ) -> None:
        """Enter a clear public state without constructing an unsupported filter."""

        if expected_occupants <= 2:
            raise ValueError("unsupported occupant count must be above two")
        previous = self.config.expected_occupants
        self._requested_expected_occupants = expected_occupants
        self._unsupported_count = expected_occupants
        self.config = replace(self.config, expected_occupants=0)
        if self._joint_filter is not None:
            self._joint_filter.set_expected_occupants(0, now)
        self._joint_policy.enter_unsupported_count(expected_occupants, evidence_id)
        self._joint_predictions.reconcile_count(previous, 0)

    def ensure_joint_state(self, now: datetime) -> None:
        if self._joint_filter is None:
            self._joint_filter = JointOccupancyFilter(
                self._map,
                self.config.expected_occupants,
                now,
            )

    def bootstrap_joint_state(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> None:
        now = max(
            (event.event_at for event in events),
            default=datetime.now().astimezone(),
        )
        self.ensure_joint_state(now)
        assert self._joint_filter is not None
        updates = self._joint_filter.bootstrap(events, cold_start=cold_start)
        for update in updates:
            self._joint_policy.apply(update, emit_activation=False)

    def occupancy_store_data(
        self,
        now: datetime,
        transition_counts: Mapping[str, Mapping[str, float]],
    ) -> dict[str, object]:
        self.ensure_joint_state(now)
        assert self._joint_filter is not None
        return serialize_occupancy_state(
            self._map,
            self._joint_filter.posterior,
            self._joint_policy.states,
            self._joint_predictions.leases,
            self._joint_filter.observations.entity_states,
            transition_counts,
            directional_contexts=self._joint_filter.directional_contexts,
            pending_departures=self._joint_policy.pending_departures,
            update_sequence=self._joint_filter.update_sequence,
        )

    def restore_joint_state(self, restored: RestoredOccupancyState) -> None:
        self._joint_filter = JointOccupancyFilter(
            self._map,
            self.config.expected_occupants,
            restored.posterior.updated_at,
        )
        self._joint_filter.restore_posterior(restored.posterior)
        self._joint_filter.restore_directional_contexts(
            restored.directional_contexts,
            restored.update_sequence,
        )
        self._joint_filter.observations.restore_entity_states(restored.entity_states)
        self._joint_policy.restore_states(restored.policy_states)
        self._joint_policy.restore_pending_departures(restored.pending_departures)
        self._joint_predictions.restore_leases(
            restored.prediction_leases,
            restored.posterior.updated_at,
        )
        self._joint_restore_status = restored.restore_status
        self._joint_restore_reason = None

    def reject_joint_restore(self, reason: str) -> None:
        self._joint_restore_status = "rejected"
        self._joint_restore_reason = reason

    def _observe_joint(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool,
    ) -> None:
        self.ensure_joint_state(event.event_at)
        assert self._joint_filter is not None
        update = self._joint_filter.observe(event)
        self._joint_policy.apply(update, emit_activation=emit_activation)
        if emit_activation:
            self._joint_predictions.apply(update)
            self._joint_predictions.learn(update)

    def _project_zone_state(
        self,
        zone: str,
        base: ZoneState,
        provenance: ObservationProvenance | None,
        confidence: float,
    ) -> ZoneState:
        assert self._joint_filter is not None
        explanation: dict[str, Any] = {
            "type": "joint_posterior",
            "occupied_marginal": confidence,
            "pruned_probability": self._joint_filter.posterior.pruned_probability,
        }
        if provenance is not None:
            explanation["last_event_id"] = provenance.event_id
            explanation["last_disposition"] = provenance.disposition
        return replace(
            base,
            confidence=confidence,
            status=status_for_confidence(confidence),
            updated_at=self._joint_filter.posterior.updated_at,
            last_node_id=None if provenance is None else provenance.node_id,
            reason=self._joint_policy.states[zone].reason,
            explanation=explanation,
        )
