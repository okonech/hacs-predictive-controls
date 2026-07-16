from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import PRODUCT_MAX_OCCUPANTS
from .events import OccupancyEvent
from .inference.engine import ExactInferenceEngine
from .inference.policy import PosteriorEventPolicy, PosteriorPolicyAuditEntry
from .inference.port import EngineDiagnostics
from .markov import MarkovChain
from .model import PredictiveMap
from .occupancy_graph import ZoneGraph
from .occupancy_scoring import status_for_confidence
from .occupancy_state import (
    DirectionalContext,
    HypothesisKey,
    MovementEvidence,
    ObservationProvenance,
    PolicyAuditEntry,
    PolicyDecision,
    PredictionLease,
    WeightedHypothesis,
    ZonePolicyState,
)
from .prediction import PredictionManager


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC)


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
    activation_risk_threshold: float = 0.80
    release_risk_threshold: float = 0.95

    @property
    def occupant_limit(self) -> int | None:
        return self.expected_occupants if self.expected_occupants > 0 else None


@dataclass(frozen=True)
class AnonymousTrack:
    """One current anonymous location projected from the exact posterior."""

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
    joint_policy_audit: tuple[PolicyAuditEntry, ...] = ()
    joint_target_policy_audit: tuple[PosteriorPolicyAuditEntry, ...] = ()
    joint_arrival_supported_probabilities: dict[str, float] = field(
        default_factory=dict
    )
    joint_release_safe_available: bool = False
    joint_release_safe_probabilities: dict[str, float] = field(default_factory=dict)
    joint_prediction_leases: tuple[PredictionLease, ...] = ()
    joint_prediction_hints: dict[str, float] = field(default_factory=dict)
    joint_event_disposition: str | None = None
    joint_route_transition_counts: dict[str, dict[str, float]] = field(
        default_factory=dict
    )
    joint_route_diagnostics: dict[str, object] = field(default_factory=dict)
    joint_route_statistics: dict[tuple[str, ...], dict[str, float]] = field(
        default_factory=dict
    )
    joint_last_provenance: ObservationProvenance | None = None
    joint_movement_evidence: tuple[MovementEvidence, ...] = ()
    joint_directional_contexts: dict[
        HypothesisKey,
        tuple[DirectionalContext, ...],
    ] = field(default_factory=dict)
    joint_posterior_entropy: float = 0.0
    joint_normalization: float = 1.0
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
            PRODUCT_MAX_OCCUPANTS,
        )
        self._unsupported_count = (
            requested_config.expected_occupants
            if requested_config.expected_occupants > PRODUCT_MAX_OCCUPANTS
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
        policy = PosteriorEventPolicy(
            predictive_map.zones(),
            activation_threshold=requested_config.activation_risk_threshold,
            release_threshold=requested_config.release_risk_threshold,
        )
        self._engine = ExactInferenceEngine(
            predictive_map,
            self.config.expected_occupants,
            policy=policy,
        )
        self._engine_diagnostics = self._engine.diagnostics
        self._joint_restore_status = "not_attempted"
        self._joint_restore_reason: str | None = None

    @property
    def _joint_policy(self) -> PosteriorEventPolicy:
        policy = self._engine.policy
        if policy is None:
            raise RuntimeError("Target policy is unavailable")
        return policy

    @property
    def _joint_predictions(self) -> PredictionManager:
        return self._engine.predictions

    @property
    def prediction_chain(self) -> MarkovChain:
        return self._joint_predictions.chain

    @property
    def states(self) -> dict[str, ZoneState]:
        return self.joint_states

    @property
    def joint_states(self) -> dict[str, ZoneState]:
        diagnostics = self._engine_diagnostics
        return {
            zone: self._zone_state_from_diagnostics(zone, diagnostics)
            for zone in self._base_states
        }

    @property
    def joint_prediction_probabilities(self) -> dict[str, float]:
        return dict(self._engine_diagnostics.prediction_probabilities)

    @property
    def requested_expected_occupants(self) -> int:
        return self._requested_expected_occupants

    @property
    def recent_events(self) -> tuple[OccupancyEvent, ...]:
        return tuple(self._recent_events)

    @property
    def tracks(self) -> tuple[AnonymousTrack, ...]:
        diagnostics = self._engine_diagnostics
        tracks: list[AnonymousTrack] = []
        current_zones: set[str] = set()
        for state in diagnostics.episode_states:
            zone = getattr(state, "zone", None)
            if isinstance(zone, str) and getattr(state, "current_positive", False):
                current_zones.add(zone)
        for zone, count in diagnostics.most_likely_counts.items():
            probabilities = diagnostics.count_marginals.get(zone, ())
            for occurrence in range(1, count + 1):
                tracks.append(
                    AnonymousTrack(
                        track_id=f"track_{len(tracks) + 1}",
                        zone=zone,
                        confidence=math.fsum(probabilities[occurrence:]),
                        active=zone in current_zones,
                        last_evidence_at=diagnostics.updated_at,
                        source_entities=tuple(
                            sorted(
                                {
                                    event.entity_id
                                    for event in self._recent_events
                                    if event.zone == zone
                                }
                            )
                        ),
                    )
                )
        return tuple(tracks)

    @property
    def diagnostics(self) -> TrackerDiagnostics:
        engine = self._engine_diagnostics
        return TrackerDiagnostics(
            expected_occupants=engine.expected_occupants,
            tracks=self.tracks,
            protected_tracks=(),
            protected_corridor=(),
            inferred_join_slots=(),
            inferred_departures=(),
            prediction_hints={},
            dwell_seconds={},
            joint_posterior=(),
            joint_occupied_marginals=dict(engine.occupied_marginals),
            joint_count_marginals=dict(engine.count_marginals),
            joint_policy_states=dict(engine.policy_states),
            joint_policy_decisions=engine.policy_decisions,
            joint_policy_audit=(),
            joint_target_policy_audit=engine.policy_audit,
            joint_arrival_supported_probabilities=dict(
                engine.arrival_supported_probabilities
            ),
            joint_release_safe_available=engine.release_safe_available,
            joint_release_safe_probabilities=dict(
                engine.release_safe_probabilities
            ),
            joint_prediction_leases=engine.prediction_leases,
            joint_prediction_hints=dict(engine.prediction_probabilities),
            joint_event_disposition=engine.event_disposition,
            joint_route_transition_counts={
                source: dict(targets)
                for source, targets in engine.route_transition_counts.items()
            },
            joint_route_diagnostics=dict(engine.route_diagnostics),
            joint_route_statistics={
                prefix: dict(targets)
                for prefix, targets in engine.route_statistics.items()
            },
            joint_last_provenance=None,
            joint_movement_evidence=(),
            joint_directional_contexts={},
            joint_posterior_entropy=0.0,
            joint_normalization=engine.normalization,
            joint_pruned_probability=engine.pruned_probability,
            joint_performance={
                "factor_step_count": engine.factor_step_count,
                "last_operation_count": engine.factor_step_count,
                "last_candidate_expansions": engine.factor_step_count,
                "last_context_compactions": 0,
                "unresolved_assignment_count": engine.unresolved_assignment_count,
                "retained_input_count": engine.retained_input_count,
                "overloaded": int(engine.overloaded),
            },
            joint_restore_status=self._joint_restore_status,
            joint_restore_reason=self._joint_restore_reason,
            joint_requested_occupants=self._requested_expected_occupants,
            joint_unsupported_count=self._unsupported_count,
        )

    def state_for_zone(self, zone: str) -> ZoneState:
        return self.joint_states.get(zone, ZoneState(zone=zone))

    def observe(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool = True,
    ) -> ZoneUpdate:
        event = replace(event, event_at=_as_utc(event.event_at))
        previous = self._zone_state_from_diagnostics(
            event.zone,
            self._engine_diagnostics,
        )
        current_diagnostics = self._observe_joint(
            event,
            emit_activation=emit_activation,
        )
        self._recent_events = [*self._recent_events[-24:], event]
        return ZoneUpdate(
            event,
            previous,
            self._zone_state_from_diagnostics(event.zone, current_diagnostics),
        )

    def refresh_active(self, now: datetime) -> tuple[ZoneUpdate, ...]:
        self._engine.finalize(_as_utc(now))
        self._engine_diagnostics = self._engine.diagnostics
        return ()

    def expire_transient_state(self, now: datetime) -> bool:
        changed = self._engine.finalize(_as_utc(now))
        self._engine_diagnostics = self._engine.diagnostics
        return changed

    def reconcile_expected_occupants(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "occupant_count_change",
    ) -> None:
        now = _as_utc(now)
        if expected_occupants > PRODUCT_MAX_OCCUPANTS:
            self.reject_unsupported_count(expected_occupants, now, evidence_id)
            return
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        recovering_from_unsupported = self._unsupported_count is not None
        previous_supported = self._last_supported_expected_occupants
        self._requested_expected_occupants = expected_occupants
        self._unsupported_count = None
        self.config = replace(self.config, expected_occupants=expected_occupants)
        self._engine_diagnostics = self._engine.reconcile_count(
            expected_occupants,
            now,
            evidence_id,
            reconcile_policy=(
                not recovering_from_unsupported
                or expected_occupants < previous_supported
            ),
        )
        self._last_supported_expected_occupants = expected_occupants

    def reject_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "unsupported_occupant_count",
    ) -> None:
        """Enter a clear public state without constructing an unsupported filter."""

        if expected_occupants <= PRODUCT_MAX_OCCUPANTS:
            raise ValueError("unsupported occupant count must be above two")
        now = _as_utc(now)
        self._requested_expected_occupants = expected_occupants
        self._unsupported_count = expected_occupants
        self.config = replace(self.config, expected_occupants=0)
        self._engine_diagnostics = self._engine.enter_unsupported_count(
            expected_occupants,
            now,
            evidence_id,
        )

    def ensure_joint_state(self, now: datetime) -> None:
        self._engine.ensure(_as_utc(now))
        self._engine_diagnostics = self._engine.diagnostics

    def bootstrap_joint_state(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> None:
        normalized = tuple(
            replace(event, event_at=_as_utc(event.event_at)) for event in events
        )
        self._engine_diagnostics = self._engine.bootstrap(
            normalized,
            cold_start=cold_start,
        )

    def occupancy_store_data(
        self,
        now: datetime,
        transition_counts: Mapping[str, Mapping[str, float]],
    ) -> dict[str, object]:
        payload = self._engine.serialize(_as_utc(now), transition_counts)
        if not isinstance(payload, dict):
            raise TypeError("Runtime inference persistence must be a mapping")
        return payload

    def restore_joint_state(self, restored: object) -> None:
        self._engine_diagnostics = self._engine.restore(restored)
        self._joint_restore_status = getattr(restored, "restore_status", "restored")
        self._joint_restore_reason = None

    def migrate_legacy_joint_state(
        self,
        policy_states: Mapping[str, ZonePolicyState],
        transition_counts: Mapping[str, Mapping[str, object]],
        route_counts: Mapping[tuple[str, ...], Mapping[str, float]],
    ) -> None:
        self._engine.migrate_legacy_state(
            policy_states,
            transition_counts,
            route_counts,
        )
        self._engine_diagnostics = self._engine.diagnostics
        self._joint_restore_status = "legacy_v5_migrated"
        self._joint_restore_reason = None

    def reject_joint_restore(self, reason: str) -> None:
        self._joint_restore_status = "rejected"
        self._joint_restore_reason = reason

    def _observe_joint(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool,
    ) -> EngineDiagnostics:
        self._engine_diagnostics = self._engine.observe(
            event,
            emit_activation=emit_activation,
        )
        return self._engine_diagnostics

    def _zone_state_from_diagnostics(
        self,
        zone: str,
        diagnostics: EngineDiagnostics,
    ) -> ZoneState:
        base = self._base_states.get(zone)
        if base is None:
            return ZoneState(zone=zone)
        confidence = diagnostics.occupied_marginals.get(zone, 0.0)
        policy_state = diagnostics.policy_states.get(zone, ZonePolicyState())
        return ZoneState(
            zone=zone,
            confidence=confidence,
            status=status_for_confidence(confidence),
            occupancy_behavior=base.occupancy_behavior,
            active_since=(
                policy_state.last_trusted_at if policy_state.keep_on else None
            ),
            last_evidence_at=diagnostics.updated_at,
            updated_at=diagnostics.updated_at,
            reason=policy_state.reason,
            explanation={
                "type": "exact_posterior",
                "occupied_marginal": confidence,
            },
        )

