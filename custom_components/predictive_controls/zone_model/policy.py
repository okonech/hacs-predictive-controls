"""Standalone hysteretic active projection and compact bounded audit."""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

from .prediction import PredictionLease
from .types import (
    CountConflictState,
    EpisodeEffect,
    EpisodeState,
    PendingAcquisitionCandidate,
    PolicyCalibration,
    PolicyDecision,
    PolicyEvent,
    PolicyUpdate,
    RefreshDedupEntry,
    TraversalAuthorization,
    ZoneBeliefState,
    ZonePolicyState,
    require_utc,
)

REFRESH_RETENTION = timedelta(hours=12)
REFRESH_LIMIT = 256
AUDIT_MAX_AGE = timedelta(hours=12)
AUDIT_ENTRY_LIMIT = 2048
AUDIT_BYTE_LIMIT = 2 * 1024 * 1024
AUDIT_MAX_ROW_BYTES = 4096
DIAGNOSTIC_LIMIT = 2**31 - 1

POLICY_CALIBRATIONS = MappingProxyType(
    {
        profile_name: PolicyCalibration(profile_name, 0.7, 0.3, dwell)
        for profile_name, dwell in {
            "entry_boundary": timedelta(seconds=15),
            "transition_fast": timedelta(seconds=15),
            "stay_pir": timedelta(seconds=60),
            "stay_presence": timedelta(seconds=120),
        }.items()
    }
)


class PolicyAuditLog:
    """Canonical UTF-8 audit rows with amortized constant-time FIFO eviction."""

    def __init__(
        self,
        *,
        max_age: timedelta = AUDIT_MAX_AGE,
        entry_limit: int = AUDIT_ENTRY_LIMIT,
        byte_limit: int = AUDIT_BYTE_LIMIT,
        max_row_bytes: int = AUDIT_MAX_ROW_BYTES,
    ) -> None:
        if (
            max_age <= timedelta(0)
            or not math.isfinite(max_age.total_seconds())
            or entry_limit <= 0
            or byte_limit <= 0
            or max_row_bytes <= 0
        ):
            raise ValueError("Policy audit bounds must be finite and positive")
        self._max_age = max_age
        self._entry_limit = entry_limit
        self._byte_limit = byte_limit
        self._max_row_bytes = max_row_bytes
        self._entries: deque[tuple[PolicyDecision, int]] = deque()
        self._deferred: list[PolicyDecision] | None = None
        self._encoded_bytes = 0
        self._rejected_rows = 0

    @property
    def rows(self) -> tuple[PolicyDecision, ...]:
        return tuple(row for row, _size in self._entries)

    @property
    def encoded_bytes(self) -> int:
        return self._encoded_bytes

    @property
    def rejected_rows(self) -> int:
        return self._rejected_rows

    @property
    def retention(self) -> tuple[timedelta, int, int, int]:
        return (
            self._max_age,
            self._entry_limit,
            self._byte_limit,
            self._max_row_bytes,
        )

    @classmethod
    def encoded_size(cls, row: PolicyDecision) -> int:
        payload = cls._json_value(asdict(row))
        return len(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )

    def append(self, row: PolicyDecision) -> bool:
        if self._deferred is not None:
            previous = (
                self._deferred[-1]
                if self._deferred
                else self._entries[-1][0]
                if self._entries
                else None
            )
            if previous is not None and row.event_at < previous.event_at:
                raise ValueError("Policy audit time cannot move backward")
            self._deferred.append(row)
            return True
        if self._entries and row.event_at < self._entries[-1][0].event_at:
            raise ValueError("Policy audit time cannot move backward")
        size = self.encoded_size(row)
        if size > self._max_row_bytes:
            self._rejected_rows = min(DIAGNOSTIC_LIMIT, self._rejected_rows + 1)
            return False
        while (
            self._entries
            and row.event_at - self._entries[0][0].event_at >= self._max_age
        ):
            self._evict_one()
        self._entries.append((row, size))
        self._encoded_bytes += size
        while (
            len(self._entries) > self._entry_limit
            or self._encoded_bytes > self._byte_limit
        ):
            self._evict_one()
        return True

    def begin_defer(self) -> None:
        """Buffer decisions until the publication schedule is complete."""

        if self._deferred is not None:
            raise RuntimeError("Policy audit deferral is already active")
        self._deferred = []

    def flush_deferred(self) -> None:
        """Materialize buffered rows after the publication handoff."""

        if self._deferred is None:
            raise RuntimeError("Policy audit deferral is not active")
        deferred = self._deferred
        self._deferred = None
        for row in deferred:
            self.append(row)

    def discard_deferred(self) -> None:
        """Drop an aborted operation's unmaterialized rows."""

        self._deferred = None

    def _evict_one(self) -> None:
        _row, size = self._entries.popleft()
        self._encoded_bytes -= size

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, timedelta):
            return value.total_seconds()
        if isinstance(value, dict):
            return {key: cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        return value


class ZonePolicy:
    """Project one zone belief into active state without model feedback."""

    def __init__(
        self,
        zone: str,
        calibration: PolicyCalibration,
        at: datetime,
        *,
        active: bool = False,
        state: ZonePolicyState | None = None,
        audit: PolicyAuditLog | None = None,
    ) -> None:
        require_utc(at, "Policy bootstrap time")
        if not zone:
            raise ValueError("Policy zone must be non-empty")
        if state is not None:
            if state.zone != zone or state.profile_name != calibration.profile_name:
                raise ValueError("Restored policy state is incompatible")
            if state.last_evaluated_at > at:
                raise ValueError("Restored policy state is ahead of bootstrap")
            self._state = state
        else:
            self._state = ZonePolicyState(
                zone,
                calibration.profile_name,
                active,
                at,
                phase="active" if active else "inactive",
                activation_provenance="restored_seed" if active else None,
            )
        self._calibration = calibration
        self._audit = audit or PolicyAuditLog()

    @property
    def state(self) -> ZonePolicyState:
        return self._state

    @property
    def audit(self) -> PolicyAuditLog:
        return self._audit

    @property
    def bootstrap_events(self) -> tuple[PolicyEvent, ...]:
        return ()

    def record_count_conflict(
        self,
        conflict: CountConflictState,
        state: EpisodeState,
        belief: ZoneBeliefState,
        *,
        result: str,
        at: datetime,
        processing_at: datetime,
    ) -> PolicyDecision:
        """Retain one explicit reliability audit row for a conflict transition."""

        self._validate_time(at, processing_at)
        if (
            conflict.target_node_id != state.node_id
            or conflict.target_zone != self._state.zone
            or state.zone != self._state.zone
            or belief.zone != self._state.zone
            or result not in {"degraded", "recovered"}
        ):
            raise ValueError("Count-conflict audit input is incompatible")
        reason = (
            "stuck_count_conflict"
            if result == "degraded"
            else "stuck_conflict_cleared"
        )
        decision = PolicyDecision(
            event_at=at,
            processing_at=processing_at,
            zone=self._state.zone,
            node_id=state.node_id,
            episode_id=state.episode_id,
            profile_name=self._state.profile_name,
            belief_before=belief.probability,
            belief_after=belief.probability,
            active_before=self._state.active,
            active_after=self._state.active,
            local_evidence_kind=(
                "health_degraded" if result == "degraded" else "health_recovered"
            ),
            local_trustworthy=result == "recovered",
            authorization_authorized=False,
            traversal_reason=reason,
            evidence_ids=(() if state.episode_id is None else (state.episode_id,)),
            count_zero=False,
            health_warning=state.health_warning,
            on_threshold=self._calibration.on_threshold,
            off_threshold=self._calibration.off_threshold,
            release_dwell=self._calibration.release_dwell,
            pending_release_since=self._state.pending_release_since,
            event_kind=None,
            reason=reason,
            count_conflict_support_ids=conflict.support_ids,
            reliability_result=result,
        )
        self._audit.append(decision)
        return decision

    def record_pending_expiry(
        self,
        candidate: PendingAcquisitionCandidate,
        belief: ZoneBeliefState,
        *,
        at: datetime,
        processing_at: datetime,
    ) -> PolicyDecision:
        """Record expiry of unsupported evidence without changing public active."""

        self._validate_time(at, processing_at)
        if candidate.zone != self._state.zone or belief.zone != self._state.zone:
            raise ValueError("Pending-expiry audit input is incompatible")
        if not self._state.active:
            self._state = ZonePolicyState(
                zone=self._state.zone,
                profile_name=self._state.profile_name,
                active=False,
                last_evaluated_at=at,
                refresh_dedup=self._pruned_dedup(at),
                phase="inactive",
            )
        decision = PolicyDecision(
            event_at=at,
            processing_at=processing_at,
            zone=self._state.zone,
            node_id=candidate.node_id,
            episode_id=candidate.episode_id,
            profile_name=self._state.profile_name,
            belief_before=belief.probability,
            belief_after=belief.probability,
            active_before=self._state.active,
            active_after=self._state.active,
            local_evidence_kind=None,
            local_trustworthy=False,
            authorization_authorized=False,
            traversal_reason="untracked_expired",
            evidence_ids=(candidate.episode_id,),
            count_zero=False,
            health_warning=False,
            on_threshold=self._calibration.on_threshold,
            off_threshold=self._calibration.off_threshold,
            release_dwell=self._calibration.release_dwell,
            pending_release_since=self._state.pending_release_since,
            event_kind=None,
            reason="untracked_expired",
        )
        self._audit.append(decision)
        return decision

    def evaluate(
        self,
        at: datetime,
        belief_before: ZoneBeliefState,
        belief_after: ZoneBeliefState,
        *,
        local_state: EpisodeState | None,
        local_effect: EpisodeEffect | None,
        authorization: TraversalAuthorization | None,
        processing_at: datetime | None = None,
        emit_event: bool = True,
        below_threshold_since: datetime | None = None,
        pending_candidate: PendingAcquisitionCandidate | None = None,
        asserted_stay_hold: bool = False,
        before_audit: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> PolicyUpdate:
        processing_at = at if processing_at is None else processing_at
        if not isinstance(asserted_stay_hold, bool):
            raise ValueError("Asserted-stay hold flag must be boolean")
        self._validate_evaluation(at, processing_at, belief_before, belief_after)
        dedup = self._pruned_dedup(at)
        active_before = self._state.active
        active_after = active_before
        pending = self._state.pending_release_since
        event: PolicyEvent | None = None
        trustworthy = self._confirming_evidence(at, local_state, local_effect)
        refresh_eligible = self._refresh_eligible(at, local_state, local_effect)
        episode_id = None if local_state is None else local_state.episode_id
        authorization_valid = self._authorization_valid(at, local_state, authorization)
        reason = "inactive_below_on" if not active_before else "active_hold"
        phase = self._state.phase
        provenance = self._state.activation_provenance
        prediction_expires_at = self._state.prediction_expires_at
        prediction_source_episode_id = self._state.prediction_source_episode_id
        prediction_probability = self._state.prediction_probability
        prediction_support = self._state.prediction_support
        activation_episode_id = self._state.activation_episode_id
        activation_at = self._state.activation_at
        activation_reason = self._state.activation_reason
        activation_track_confidence = self._state.activation_track_confidence
        activation_path_node_ids = self._state.activation_path_node_ids
        activation_provenance_kind = self._state.activation_provenance_kind
        activation_source_episode_ids = self._state.activation_source_episode_ids

        if not active_before:
            pending = None
            phase = "pending" if pending_candidate is not None else "inactive"
            provenance = None
            prediction_expires_at = None
            prediction_source_episode_id = None
            prediction_probability = None
            prediction_support = None
            activation_episode_id = None
            activation_at = None
            activation_reason = None
            activation_track_confidence = None
            activation_path_node_ids = ()
            activation_provenance_kind = None
            activation_source_episode_ids = ()
            if belief_after.probability >= self._calibration.on_threshold:
                if trustworthy and authorization_valid and episode_id is not None:
                    active_after = True
                    reason = "acquired"
                    phase = "active"
                    provenance = "evidence"
                    activation_episode_id = episode_id
                    activation_at = at
                    assert authorization is not None
                    activation_reason = authorization.reason
                    activation_track_confidence = authorization.track_confidence
                    activation_path_node_ids = authorization.path_node_ids
                    activation_provenance_kind = authorization.provenance_kind
                    activation_source_episode_ids = tuple(
                        token.episode_id for token in authorization.source_tokens
                    )
                    if emit_event:
                        event = self._event(
                            "acquired", at, episode_id, belief_after, authorization
                        )
                    dedup = self._remember_episode(dedup, episode_id, at)
                else:
                    reason = "acquisition_unauthorized"
        elif phase == "predicted":
            pending = None
            if trustworthy and episode_id is not None:
                reason = "prediction_confirmed"
                phase = "active"
                provenance = "evidence"
                prediction_expires_at = None
                prediction_source_episode_id = None
                prediction_probability = None
                prediction_support = None
                activation_episode_id = episode_id
                activation_at = at
                activation_reason = "prediction_confirmed"
                activation_track_confidence = None
                assert local_state is not None
                activation_path_node_ids = (local_state.node_id,)
                activation_provenance_kind = "prediction_confirmation"
                activation_source_episode_ids = ()
                dedup = self._remember_episode(dedup, episode_id, at)
            elif local_state is not None and local_state.last_event_at == at:
                active_after = False
                reason = "prediction_unconfirmed"
                phase = "inactive"
                provenance = None
                prediction_expires_at = None
                prediction_source_episode_id = None
                prediction_probability = None
                prediction_support = None
                activation_episode_id = None
                activation_at = None
                activation_reason = None
                activation_track_confidence = None
                activation_path_node_ids = ()
                activation_provenance_kind = None
                activation_source_episode_ids = ()
                if emit_event:
                    event = PolicyEvent(
                        "released",
                        at,
                        self._state.zone,
                        episode_id,
                        belief_after.probability,
                        "prediction_authorized",
                        "prediction_unconfirmed",
                    )
            else:
                reason = "prediction_active"
        else:
            if asserted_stay_hold:
                pending = None
                reason = "asserted_stay_hold"
            elif belief_after.probability <= self._calibration.off_threshold:
                pending = (
                    below_threshold_since
                    if pending is None and below_threshold_since is not None
                    else at
                    if pending is None
                    else pending
                )
                if at >= pending + self._calibration.release_dwell:
                    active_after = False
                    pending = None
                    reason = "released"
                    phase = "inactive"
                    provenance = None
                    prediction_expires_at = None
                    prediction_source_episode_id = None
                    prediction_probability = None
                    prediction_support = None
                    activation_episode_id = None
                    activation_at = None
                    activation_reason = None
                    activation_track_confidence = None
                    activation_path_node_ids = ()
                    activation_provenance_kind = None
                    activation_source_episode_ids = ()
                    if emit_event:
                        event = self._event(
                            "released", at, episode_id, belief_after, authorization
                        )
                else:
                    reason = "release_pending"
            elif pending is not None:
                pending = None
                reason = "release_canceled"
            if (
                active_after
                and refresh_eligible
                and episode_id is not None
                and episode_id not in {item.episode_id for item in dedup}
            ):
                reason = "refreshed"
                if emit_event:
                    event = self._event(
                        "refreshed", at, episode_id, belief_after, authorization
                    )
                dedup = self._remember_episode(dedup, episode_id, at)

        self._state = ZonePolicyState(
            zone=self._state.zone,
            profile_name=self._state.profile_name,
            active=active_after,
            last_evaluated_at=at,
            pending_release_since=pending,
            refresh_dedup=dedup,
            phase=phase,
            activation_provenance=provenance,
            prediction_expires_at=prediction_expires_at,
            prediction_source_episode_id=prediction_source_episode_id,
            prediction_probability=prediction_probability,
            prediction_support=prediction_support,
            activation_episode_id=activation_episode_id,
            activation_at=activation_at,
            activation_reason=activation_reason,
            activation_track_confidence=activation_track_confidence,
            activation_path_node_ids=activation_path_node_ids,
            activation_provenance_kind=activation_provenance_kind,
            activation_source_episode_ids=activation_source_episode_ids,
        )
        if (
            event is None
            and local_effect is not None
            and local_effect.kind
            in {
                "correlated_continuity_authorized",
                "correlated_flap_ignored",
                "impossible_cadence",
            }
        ):
            reason = local_effect.kind
        decision = self._decision(
            at,
            processing_at,
            belief_before.probability,
            belief_after.probability,
            active_before,
            local_state,
            local_effect,
            trustworthy,
            authorization,
            False,
            event,
            reason,
        )
        if event is not None and before_audit is not None:
            before_audit(event, decision, authorization)
        self._audit.append(decision)
        return PolicyUpdate(self._state, event, decision)

    def apply_prediction(
        self,
        lease: PredictionLease,
        belief: ZoneBeliefState,
        *,
        processing_at: datetime | None = None,
        emit_event: bool = True,
        before_audit: Callable[
            [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None
        ]
        | None = None,
    ) -> PolicyUpdate | None:
        """Activate this zone through one mature nonrenewing prediction lease."""

        at = lease.created_at
        processing_at = at if processing_at is None else processing_at
        self._validate_time(at, processing_at)
        if (
            self._state.active
            or not lease.mature
            or lease.target_zone != self._state.zone
            or belief.zone != self._state.zone
            or belief.last_updated_at != at
        ):
            return None
        active_before = self._state.active
        event = (
            PolicyEvent(
                "acquired",
                at,
                self._state.zone,
                lease.source_episode_id,
                belief.probability,
                "prediction_authorized",
                "predicted",
            )
            if emit_event
            else None
        )
        self._state = ZonePolicyState(
            zone=self._state.zone,
            profile_name=self._state.profile_name,
            active=True,
            last_evaluated_at=at,
            pending_release_since=None,
            refresh_dedup=self._pruned_dedup(at),
            phase="predicted",
            activation_provenance="prediction",
            prediction_expires_at=lease.expires_at,
            prediction_source_episode_id=lease.source_episode_id,
            prediction_probability=lease.probability,
            prediction_support=lease.support,
        )
        decision = replace(
            self._decision(
                at,
                processing_at,
                belief.probability,
                belief.probability,
                active_before,
                None,
                None,
                False,
                None,
                False,
                event,
                "prediction_authorized",
            ),
            authorization_authorized=True,
            traversal_reason="prediction_authorized",
            evidence_ids=(lease.source_episode_id,),
        )
        if event is not None and before_audit is not None:
            before_audit(event, decision, None)
        self._audit.append(decision)
        return PolicyUpdate(self._state, event, decision)

    def expire_prediction(
        self,
        at: datetime,
        belief: ZoneBeliefState,
        *,
        processing_at: datetime | None = None,
        emit_event: bool = True,
        force: bool = False,
    ) -> PolicyUpdate | None:
        """Expire a predicted phase at deadline or when its lease is canceled."""

        processing_at = at if processing_at is None else processing_at
        self._validate_time(at, processing_at)
        deadline = self._state.prediction_expires_at
        if (
            self._state.phase != "predicted"
            or deadline is None
            or (deadline > at and not force)
        ):
            return None
        event = (
            PolicyEvent(
                "released",
                at,
                self._state.zone,
                None,
                belief.probability,
                "prediction_authorized",
                "prediction_unconfirmed",
            )
            if emit_event
            else None
        )
        self._state = ZonePolicyState(
            zone=self._state.zone,
            profile_name=self._state.profile_name,
            active=False,
            last_evaluated_at=at,
            pending_release_since=None,
            refresh_dedup=self._pruned_dedup(at),
            phase="inactive",
        )
        decision = self._decision(
            at,
            processing_at,
            belief.probability,
            belief.probability,
            True,
            None,
            None,
            False,
            None,
            False,
            event,
            "prediction_unconfirmed",
        )
        self._audit.append(decision)
        return PolicyUpdate(self._state, event, decision)

    def apply_count_zero(
        self, at: datetime, *, processing_at: datetime | None = None
    ) -> PolicyUpdate:
        processing_at = at if processing_at is None else processing_at
        self._validate_time(at, processing_at)
        active_before = self._state.active
        event = (
            PolicyEvent("released", at, self._state.zone, None, 0.0, None, "count_zero")
            if active_before
            else None
        )
        self._state = ZonePolicyState(
            zone=self._state.zone,
            profile_name=self._state.profile_name,
            active=False,
            last_evaluated_at=at,
            pending_release_since=None,
            refresh_dedup=self._pruned_dedup(at),
            phase="inactive",
        )
        decision = self._decision(
            at,
            processing_at,
            0.0,
            0.0,
            active_before,
            None,
            None,
            False,
            None,
            True,
            event,
            "count_zero",
        )
        self._audit.append(decision)
        return PolicyUpdate(self._state, event, decision)

    def _validate_evaluation(
        self,
        at: datetime,
        processing_at: datetime,
        belief_before: ZoneBeliefState,
        belief_after: ZoneBeliefState,
    ) -> None:
        self._validate_time(at, processing_at)
        for belief in (belief_before, belief_after):
            if (
                belief.zone != self._state.zone
                or belief.profile_name != self._state.profile_name
            ):
                raise ValueError("Policy belief is incompatible with this frontier")
        if belief_before.last_updated_at > at or belief_after.last_updated_at != at:
            raise ValueError("Policy belief is incompatible with this frontier")

    def _validate_time(self, at: datetime, processing_at: datetime) -> None:
        require_utc(at, "Policy event time")
        require_utc(processing_at, "Policy processing time")
        if at < self._state.last_evaluated_at:
            raise ValueError("Policy event time cannot move backward")
        if processing_at < at:
            raise ValueError("Policy processing time cannot precede event time")

    @staticmethod
    def _confirming_evidence(
        at: datetime,
        state: EpisodeState | None,
        effect: EpisodeEffect | None,
    ) -> bool:
        return bool(
            state is not None
            and effect is not None
            and effect.kind in {"correlated_positive", "interaction", "positive"}
            and effect.at == at
            and effect.node_id == state.node_id
            and effect.zone == state.zone
            and effect.episode_id == state.episode_id
            and (
                state.status == "asserted"
                or (effect.kind == "interaction" and state.status == "clearing")
            )
            and not state.health_warning
            and (
                effect.kind == "correlated_positive" or not state.cadence_warning
            )
            and state.started_at is not None
            and state.traversal_valid_until is not None
            and state.started_at <= at < state.traversal_valid_until
        )

    @classmethod
    def _refresh_eligible(
        cls,
        at: datetime,
        state: EpisodeState | None,
        effect: EpisodeEffect | None,
    ) -> bool:
        return bool(
            effect is not None
            and effect.kind in {"interaction", "positive"}
            and cls._confirming_evidence(at, state, effect)
        )

    def _authorization_valid(
        self,
        at: datetime,
        state: EpisodeState | None,
        authorization: TraversalAuthorization | None,
    ) -> bool:
        return bool(
            state is not None
            and authorization is not None
            and authorization.authorized
            and authorization.authorized_at == at
            and authorization.target_node_id == state.node_id
            and authorization.target_zone == self._state.zone
            and authorization.target_episode_id == state.episode_id
        )

    def _pruned_dedup(self, at: datetime) -> tuple[RefreshDedupEntry, ...]:
        return tuple(item for item in self._state.refresh_dedup if item.expires_at > at)

    @staticmethod
    def _remember_episode(
        entries: tuple[RefreshDedupEntry, ...], episode_id: str, at: datetime
    ) -> tuple[RefreshDedupEntry, ...]:
        return (
            *entries,
            RefreshDedupEntry(episode_id, at, at + REFRESH_RETENTION),
        )[-REFRESH_LIMIT:]

    def _event(
        self,
        kind: str,
        at: datetime,
        episode_id: str | None,
        belief: ZoneBeliefState,
        authorization: TraversalAuthorization | None,
    ) -> PolicyEvent:
        return PolicyEvent(
            kind,
            at,
            self._state.zone,
            episode_id,
            belief.probability,
            None if authorization is None else authorization.reason,
            kind,
        )

    def _decision(
        self,
        at: datetime,
        processing_at: datetime,
        belief_before: float,
        belief_after: float,
        active_before: bool,
        local_state: EpisodeState | None,
        local_effect: EpisodeEffect | None,
        trustworthy: bool,
        authorization: TraversalAuthorization | None,
        count_zero: bool,
        event: PolicyEvent | None,
        reason: str,
    ) -> PolicyDecision:
        local_evidence = (
            ()
            if local_state is None or local_state.episode_id is None
            else (local_state.episode_id,)
        )
        source_evidence = (
            ()
            if authorization is None
            else tuple(token.episode_id for token in authorization.source_tokens)
        )
        evidence_ids = tuple(dict.fromkeys((*local_evidence, *source_evidence)))
        return PolicyDecision(
            at,
            processing_at,
            self._state.zone,
            None if local_state is None else local_state.node_id,
            None if local_state is None else local_state.episode_id,
            self._state.profile_name,
            belief_before,
            belief_after,
            active_before,
            self._state.active,
            None if local_effect is None else local_effect.kind,
            trustworthy,
            bool(authorization is not None and authorization.authorized),
            None if authorization is None else authorization.reason,
            evidence_ids,
            count_zero,
            bool(local_state is not None and local_state.health_warning),
            self._calibration.on_threshold,
            self._calibration.off_threshold,
            self._calibration.release_dwell,
            self._state.pending_release_since,
            None if event is None else event.kind,
            reason,
        )


__all__ = ["POLICY_CALIBRATIONS", "PolicyAuditLog", "ZonePolicy"]
