from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, cast

from .const import PRODUCT_MAX_OCCUPANTS
from .events import OccupancyEvent
from .markov import MarkovChain
from .model import PredictiveMap
from .zone_model.engine import ZoneModelEngine
from .zone_model.persistence import (
    LEGACY_EXACT_SCHEMA,
    LEGACY_V2_SCHEMA,
    LegacySchema6Seed,
    LegacyV2Seed,
    decode_schema6_seed,
    decode_v2_seed,
    migrate_schema6_seed,
    migrate_v2_seed,
    restore_target_state,
    serialize_target_state,
)
from .zone_model.prediction import PredictionLease, TargetPredictionManager
from .zone_model.types import (
    AnonymousOccupancySupport,
    CountConflictState,
    CountInput,
    EpisodeState,
    PendingAcquisitionCandidate,
    PolicyDecision,
    PolicyEvent,
    ReliabilityWarningOccurrence,
    SensorInput,
    SupportTokenBinding,
    SupportTransitionEvent,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
    ZonePolicyState,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ZoneState:
    """Current public projection of one target zone belief."""

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
    explanation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ZoneUpdate:
    """Result of applying one target-model observation."""

    event: OccupancyEvent
    previous: ZoneState
    current: ZoneState


@dataclass(frozen=True)
class TrackerConfig:
    """Authoritative count configuration for the zone-belief engine."""

    expected_occupants: int = 0


@dataclass(frozen=True)
class TrackerDiagnostics:
    """Bounded target diagnostics consumed by entities and status APIs."""

    expected_occupants: int
    beliefs: dict[str, float]
    policy_states: dict[str, ZonePolicyState]
    policy_decisions: tuple[PolicyDecision, ...]
    policy_events: tuple[PolicyEvent, ...]
    authorizations: tuple[TraversalAuthorization, ...]
    episode_states: tuple[EpisodeState, ...]
    traversal_tokens: tuple[TraversalToken, ...]
    retained_traversal_tokens: tuple[TraversalToken, ...]
    pending_candidates: tuple[PendingAcquisitionCandidate, ...]
    anonymous_supports: tuple[AnonymousOccupancySupport, ...]
    support_token_bindings: tuple[SupportTokenBinding, ...]
    latest_support_transition: SupportTransitionEvent | None
    count_conflicts: tuple[CountConflictState, ...]
    reliability_warning_occurrences: tuple[ReliabilityWarningOccurrence, ...]
    sensor_reliability: dict[str, float]
    prediction_leases: tuple[PredictionLease, ...]
    prediction_probabilities: dict[str, float]
    policy_audit: tuple[PolicyDecision, ...]
    event_disposition: str | None
    restore_status: str
    restore_reason: str | None
    requested_occupants: int
    unsupported_count: int | None
    lifecycle_counters: dict[str, int]
    processing: dict[str, float | int] = field(default_factory=dict)


class OccupancyTracker:
    """Production-facing facade for graph-local zone-belief inference."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        config: TrackerConfig | None = None,
        **_compatibility: object,
    ) -> None:
        requested = (config or TrackerConfig()).expected_occupants
        if requested < 0:
            raise ValueError("expected_occupants must be non-negative")
        supported = requested if requested <= PRODUCT_MAX_OCCUPANTS else 0
        self._map = predictive_map
        self.config = TrackerConfig(supported)
        self._requested_expected_occupants = requested
        self._unsupported_count = (
            requested if requested > PRODUCT_MAX_OCCUPANTS else None
        )
        self._engine: ZoneModelEngine | None = None
        self._predictions = TargetPredictionManager(predictive_map)
        self._legacy_seed: LegacySchema6Seed | None = None
        self._v2_seed: LegacyV2Seed | None = None
        self._recent_events: list[OccupancyEvent] = []
        self._last_result: ZoneModelResult | None = None
        self._restore_status = "not_attempted"
        self._restore_reason: str | None = None
        self._restore_rejection_count = 0
        self._active_since_by_zone: dict[str, datetime] = {}
        self._policy_reason_by_zone: dict[str, str] = {}

    @property
    def states(self) -> dict[str, ZoneState]:
        snapshot = None if self._engine is None else self._engine.snapshot
        beliefs = (
            {}
            if snapshot is None
            else {item.zone: item for item in snapshot.belief_states}
        )
        policies = (
            {}
            if snapshot is None
            else {item.zone: item for item in snapshot.policy_states}
        )
        episodes = () if snapshot is None else snapshot.episode_states
        return {
            zone: self._zone_state(
                zone, beliefs.get(zone), policies.get(zone), episodes
            )
            for zone in self._map.zones()
        }

    @property
    def beliefs(self) -> dict[str, float]:
        """Return the lightweight current belief projection without audit data."""

        if self._engine is None:
            return {}
        return {
            state.zone: state.probability
            for state in self._engine.snapshot.belief_states
        }

    @property
    def policy_states(self) -> dict[str, ZonePolicyState]:
        """Return current policy states without materializing retained audit."""

        if self._engine is None:
            return {}
        return {state.zone: state for state in self._engine.snapshot.policy_states}

    @property
    def episode_states(self) -> tuple[EpisodeState, ...]:
        """Return current physical episodes without materializing retained audit."""

        return () if self._engine is None else self._engine.snapshot.episode_states

    @property
    def traversal_tokens(self) -> tuple[TraversalToken, ...]:
        """Return current traversal tokens without materializing retained audit."""

        return () if self._engine is None else self._engine.snapshot.traversal_tokens

    @property
    def authorizations(self) -> tuple[TraversalAuthorization, ...]:
        """Return authorizations from the latest model result."""

        return () if self._last_result is None else self._last_result.authorizations

    @property
    def policy_events(self) -> tuple[PolicyEvent, ...]:
        """Return public policy events from the latest model result."""

        return () if self._last_result is None else self._last_result.policy_events

    @property
    def policy_decisions(self) -> tuple[PolicyDecision, ...]:
        """Return decisions from the latest operation without retained audit."""

        return () if self._last_result is None else self._last_result.policy_decisions

    @property
    def requested_expected_occupants(self) -> int:
        return self._requested_expected_occupants

    @property
    def prediction_chain(self) -> MarkovChain:
        return self._predictions.chain

    @property
    def prediction_probabilities(self) -> dict[str, float]:
        return self._predictions.probabilities

    @property
    def recent_events(self) -> tuple[OccupancyEvent, ...]:
        return tuple(self._recent_events)

    @property
    def diagnostics(self) -> TrackerDiagnostics:
        snapshot = None if self._engine is None else self._engine.snapshot
        beliefs = (
            {}
            if snapshot is None
            else {item.zone: item.probability for item in snapshot.belief_states}
        )
        policies = (
            {}
            if snapshot is None
            else {item.zone: item for item in snapshot.policy_states}
        )
        result = self._last_result
        return TrackerDiagnostics(
            expected_occupants=self.config.expected_occupants,
            beliefs=beliefs,
            policy_states=policies,
            policy_decisions=() if result is None else result.policy_decisions,
            policy_events=() if result is None else result.policy_events,
            authorizations=() if result is None else result.authorizations,
            episode_states=() if snapshot is None else snapshot.episode_states,
            traversal_tokens=() if snapshot is None else snapshot.traversal_tokens,
            retained_traversal_tokens=(
                () if snapshot is None else snapshot.retained_traversal_tokens
            ),
            pending_candidates=(
                () if snapshot is None else snapshot.pending_candidates
            ),
            anonymous_supports=(
                () if snapshot is None else snapshot.anonymous_supports
            ),
            support_token_bindings=(
                () if snapshot is None else snapshot.support_token_bindings
            ),
            latest_support_transition=(
                None
                if self._engine is None
                else self._engine.latest_support_transition
            ),
            count_conflicts=() if snapshot is None else snapshot.count_conflicts,
            reliability_warning_occurrences=(
                ()
                if snapshot is None
                else snapshot.reliability_warning_occurrences
            ),
            sensor_reliability={
                node_id: node.reliability
                for node_id, node in sorted(self._map.nodes.items())
            },
            prediction_leases=self._predictions.leases,
            prediction_probabilities=self._predictions.probabilities,
            policy_audit=() if self._engine is None else self._engine.audit_rows,
            event_disposition=None if result is None else result.disposition,
            restore_status=self._restore_status,
            restore_reason=self._restore_reason,
            requested_occupants=self._requested_expected_occupants,
            unsupported_count=self._unsupported_count,
            lifecycle_counters={
                **(
                    {}
                    if self._engine is None
                    else self._engine.diagnostic_counters
                ),
                "restore_rejected": self._restore_rejection_count,
            },
            processing={
                "zone_count": len(beliefs),
                "episode_count": 0
                if snapshot is None
                else len(snapshot.episode_states),
                "token_count": 0
                if snapshot is None
                else len(snapshot.traversal_tokens),
                "retained_token_count": 0
                if snapshot is None
                else len(snapshot.retained_traversal_tokens),
                "pending_candidate_count": 0
                if snapshot is None
                else len(snapshot.pending_candidates),
                "support_count": 0
                if snapshot is None
                else len(snapshot.anonymous_supports),
                "support_binding_count": 0
                if snapshot is None
                else len(snapshot.support_token_bindings),
                "count_conflict_count": 0
                if snapshot is None
                else len(snapshot.count_conflicts),
                "audit_count": 0
                if self._engine is None
                else len(self._engine.audit_rows),
            },
        )

    def state_for_zone(self, zone: str) -> ZoneState:
        if self._engine is None or zone not in self._map.zones():
            return ZoneState(zone=zone)
        snapshot = self._engine.snapshot
        belief = next(
            (item for item in snapshot.belief_states if item.zone == zone), None
        )
        policy = next(
            (item for item in snapshot.policy_states if item.zone == zone), None
        )
        return self._zone_state(zone, belief, policy, snapshot.episode_states)

    def observe(
        self,
        event: OccupancyEvent,
        *,
        processing_at: datetime | None = None,
        emit_activation: bool = True,
        defer_learning: bool = False,
        publication_callback: Callable[[], None] | None = None,
    ) -> ZoneUpdate:
        del emit_activation
        event = replace(event, event_at=_as_utc(event.event_at))
        processed_at = (
            event.event_at if processing_at is None else _as_utc(processing_at)
        )
        previous = self.state_for_zone(event.zone)
        engine = self._ensure_engine(event.event_at)
        self._record_result(
            engine.observe(
                self._sensor_input(event),
                processing_at=processed_at,
                decision_callback=(
                    None
                    if publication_callback is None
                    else lambda policy_event, decision, authorization: (
                        self._publish_fast_projection(
                            policy_event,
                            decision,
                            authorization,
                            publication_callback,
                        )
                    )
                ),
            ),
            defer_learning=defer_learning,
        )
        self._recent_events = [*self._recent_events[-24:], event]
        return ZoneUpdate(event, previous, self.state_for_zone(event.zone))

    def refresh_active(self, now: datetime) -> tuple[ZoneUpdate, ...]:
        return self._advance(_as_utc(now))

    def expire_transient_state(self, now: datetime) -> bool:
        engine = self._ensure_engine(_as_utc(now))
        before = _transient_projection(engine)
        self._record_result(self._ensure_engine(_as_utc(now)).advance(_as_utc(now)))
        return before != _transient_projection(engine)

    def reconcile_expected_occupants(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "occupant_count_change",
        *,
        processing_at: datetime | None = None,
    ) -> None:
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        self._requested_expected_occupants = expected_occupants
        if expected_occupants > PRODUCT_MAX_OCCUPANTS:
            self._unsupported_count = expected_occupants
            return
        self._unsupported_count = None
        self.config = TrackerConfig(expected_occupants)
        at = _as_utc(now)
        if self._legacy_seed is not None or self._v2_seed is not None:
            return
        self._record_result(
            self._ensure_engine(at).observe_count(
                CountInput(evidence_id, expected_occupants, True, at),
                processing_at=(at if processing_at is None else _as_utc(processing_at)),
            )
        )

    def reject_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str = "unsupported_occupant_count",
    ) -> None:
        del now, evidence_id
        if expected_occupants <= PRODUCT_MAX_OCCUPANTS:
            raise ValueError("unsupported occupant count must be above two")
        self._requested_expected_occupants = expected_occupants
        self._unsupported_count = expected_occupants

    def ensure_state(self, now: datetime) -> None:
        self._ensure_engine(_as_utc(now))

    def bootstrap_state(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> None:
        del cold_start
        normalized = tuple(
            replace(event, event_at=_as_utc(event.event_at)) for event in events
        )
        at = max((event.event_at for event in normalized), default=datetime.now(UTC))
        sensor_snapshot = tuple(self._sensor_input(event) for event in normalized)
        if self._legacy_seed is not None:
            self._engine = migrate_schema6_seed(
                self._map,
                self._legacy_seed,
                sensor_snapshot,
                at,
                expected_count=self.config.expected_occupants,
            )
            self._predictions = self._engine.prediction_manager
            self._legacy_seed = None
            self._adopt_engine_count()
            self._restore_status = "schema6_migrated"
            self._rebuild_policy_projection_cache()
            return
        if self._v2_seed is not None:
            self._engine = migrate_v2_seed(
                self._map,
                self._v2_seed,
                sensor_snapshot,
                at,
                expected_count=self.config.expected_occupants,
            )
            self._predictions = self._engine.prediction_manager
            self._v2_seed = None
            self._adopt_engine_count()
            self._restore_status = "v2_migrated"
            self._rebuild_policy_projection_cache()
            return
        if self._engine is not None:
            if at > self._engine.snapshot.updated_at:
                self._record_result(self._engine.advance(at, emit_events=False))
            else:
                self._rebuild_policy_projection_cache()
            return
        self._engine = ZoneModelEngine(self._map, self.config.expected_occupants, at)
        self._predictions = self._engine.prediction_manager
        self._engine.bootstrap_sensor_snapshot(sensor_snapshot, at)
        self._rebuild_policy_projection_cache()

    def occupancy_store_data(
        self,
        now: datetime | None = None,
        transition_counts: object | None = None,
    ) -> dict[str, object]:
        del transition_counts
        if self._engine is None:
            self._ensure_engine(datetime.now(UTC) if now is None else _as_utc(now))
        assert self._engine is not None
        payload = serialize_target_state(self._map, self._engine)
        return payload

    def restore_state(self, restored: object, now: datetime) -> bool:
        at = _as_utc(now)
        if isinstance(restored, dict) and restored.get("schema") == LEGACY_EXACT_SCHEMA:
            try:
                seed = decode_schema6_seed(self._map, restored)
            except (TypeError, ValueError) as exc:
                self.reject_restore(str(exc))
                return False
            self._legacy_seed = seed
            self._v2_seed = None
            self._restore_status = "schema6_pending"
            self._restore_reason = None
            return True
        if isinstance(restored, dict) and restored.get("schema") == LEGACY_V2_SCHEMA:
            try:
                self._v2_seed = decode_v2_seed(self._map, restored)
            except (TypeError, ValueError) as exc:
                self.reject_restore(str(exc))
                return False
            self._legacy_seed = None
            self._restore_status = "v2_pending"
            self._restore_reason = None
            return True
        try:
            candidate = restore_target_state(self._map, restored, at)
        except (TypeError, ValueError) as exc:
            self.reject_restore(str(exc))
            return False
        self._engine = candidate
        self._predictions = candidate.prediction_manager
        self._legacy_seed = None
        self._v2_seed = None
        self._adopt_engine_count()
        self._restore_status = "restored"
        self._restore_reason = None
        self._rebuild_policy_projection_cache()
        return True

    def reject_restore(self, reason: str) -> None:
        self._restore_status = "rejected"
        self._restore_reason = reason
        self._restore_rejection_count = min(
            2**31 - 1,
            self._restore_rejection_count + 1,
        )

    def _advance(self, at: datetime) -> tuple[ZoneUpdate, ...]:
        before = self.states
        self._record_result(self._ensure_engine(at).advance(at))
        after = self.states
        updates: list[ZoneUpdate] = []
        for zone in self._map.zones():
            if before[zone] == after[zone]:
                continue
            synthetic = OccupancyEvent(
                "timer.zone_model",
                "timer",
                zone,
                None,
                "timer",
                after[zone].occupancy_behavior,
                "timer",
                "off",
                at,
                1.0,
            )
            updates.append(ZoneUpdate(synthetic, before[zone], after[zone]))
        return tuple(updates)

    def _ensure_engine(self, at: datetime) -> ZoneModelEngine:
        if self._engine is None:
            self._engine = ZoneModelEngine(
                self._map, self.config.expected_occupants, at
            )
            self._predictions = self._engine.prediction_manager
        return self._engine

    def commit_prediction_learning(self) -> None:
        if self._engine is not None:
            self._engine.commit_prediction_learning()

    def _record_result(
        self, result: ZoneModelResult, *, defer_learning: bool = False
    ) -> None:
        self._last_result = result
        if not defer_learning:
            self.commit_prediction_learning()
        for decision in result.policy_decisions:
            self._policy_reason_by_zone[decision.zone] = decision.reason
            if decision.active_after and not decision.active_before:
                self._active_since_by_zone[decision.zone] = decision.event_at
            elif not decision.active_after:
                self._active_since_by_zone.pop(decision.zone, None)

    def _publish_fast_projection(
        self,
        event: PolicyEvent,
        decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
        callback: Callable[[], None],
    ) -> None:
        """Install coherent edge metadata before scheduling the entity write."""

        engine = cast(ZoneModelEngine, self._engine)
        self._last_result = ZoneModelResult(
            "publishing",
            engine.snapshot,
            (event,),
            (decision,),
            () if authorization is None else (authorization,),
        )
        self._policy_reason_by_zone[decision.zone] = decision.reason
        if decision.active_after and not decision.active_before:
            self._active_since_by_zone[decision.zone] = decision.event_at
        callback()

    def _rebuild_policy_projection_cache(self) -> None:
        """Build small public projection indexes outside the event hot path."""

        self._active_since_by_zone.clear()
        self._policy_reason_by_zone.clear()
        engine = cast(ZoneModelEngine, self._engine)
        rows_by_zone: dict[str, list[PolicyDecision]] = {}
        for row in engine.audit_rows:
            rows_by_zone.setdefault(row.zone, []).append(row)
        for policy in engine.snapshot.policy_states:
            rows = rows_by_zone.get(policy.zone, [])
            if rows:
                latest = max(rows, key=lambda row: row.event_at)
                self._policy_reason_by_zone[policy.zone] = latest.reason
            else:
                self._policy_reason_by_zone[policy.zone] = "bootstrap"
            if not policy.active:
                continue
            acquired = [row.event_at for row in rows if row.event_kind == "acquired"]
            self._active_since_by_zone[policy.zone] = max(
                acquired,
                default=policy.last_evaluated_at,
            )

    def _adopt_engine_count(self) -> None:
        """Adopt restored count as the facade's reconciliation frontier."""

        engine = cast(ZoneModelEngine, self._engine)
        expected = engine.snapshot.count_state.expected_count
        self.config = TrackerConfig(expected)
        self._requested_expected_occupants = expected
        self._unsupported_count = None

    @staticmethod
    def _sensor_input(event: OccupancyEvent) -> SensorInput:
        return SensorInput(
            event.entity_id,
            event.state,
            event.event_at,
            event.reliability,
        )

    def _zone_state(
        self,
        zone: str,
        belief: ZoneBeliefState | None,
        policy: ZonePolicyState | None,
        episodes: tuple[EpisodeState, ...],
    ) -> ZoneState:
        probability = 0.0 if belief is None else belief.probability
        zone_episodes = tuple(item for item in episodes if item.zone == zone)
        recent = max(
            (item for item in zone_episodes if item.last_event_at is not None),
            key=lambda item: item.last_event_at or datetime.min.replace(tzinfo=UTC),
            default=None,
        )
        last_clear = max(
            (item.clear_started_at for item in zone_episodes if item.clear_started_at),
            default=None,
        )
        active = policy is not None and policy.active
        active_since = self._active_since_by_zone.get(zone) if active else None
        return ZoneState(
            zone=zone,
            confidence=probability,
            status=_status_for_probability(probability),
            occupancy_behavior=self._map.zone_occupancy_behavior(zone),
            active_since=active_since,
            last_evidence_at=None if recent is None else recent.last_event_at,
            last_clear_at=last_clear,
            updated_at=None if belief is None else belief.last_updated_at,
            last_node_id=None if recent is None else recent.node_id,
            reason="no evidence" if policy is None else self._policy_reason(zone),
            explanation={
                "type": "zone_belief",
                "belief": probability,
                "context": None if belief is None else belief.context,
                "active": active,
                "profile": None if belief is None else belief.profile_name,
                "health_warning": False if belief is None else belief.health_warning,
            },
        )

    def _policy_reason(self, zone: str) -> str:
        if self._engine is None:
            return "no evidence"
        return self._policy_reason_by_zone.get(zone, "bootstrap")


__all__ = [
    "OccupancyTracker",
    "TrackerConfig",
    "TrackerDiagnostics",
    "ZoneState",
    "ZoneUpdate",
]


def _status_for_probability(probability: float) -> str:
    if probability >= 0.85:
        return "confirmed"
    if probability >= 0.60:
        return "probable"
    if probability >= 0.35:
        return "possible"
    if probability > 0.0:
        return "suspect"
    return "rejected"


def _transient_projection(engine: ZoneModelEngine) -> tuple[object, ...]:
    snapshot = engine.snapshot
    return (
        snapshot.traversal_tokens,
        snapshot.retained_traversal_tokens,
        snapshot.current_token_ids,
        tuple(
            (state.node_id, state.status, state.health_warning)
            for state in snapshot.episode_states
        ),
        tuple(
            (state.zone, state.active, state.pending_release_since)
            for state in snapshot.policy_states
        ),
    )
