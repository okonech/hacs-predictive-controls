"""Standalone hysteretic active projection and compact bounded audit."""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

from .types import (
    EpisodeEffect,
    EpisodeState,
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
            self._state = ZonePolicyState(zone, calibration.profile_name, active, at)
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
    ) -> PolicyUpdate:
        processing_at = at if processing_at is None else processing_at
        self._validate_evaluation(at, processing_at, belief_before, belief_after)
        dedup = self._pruned_dedup(at)
        active_before = self._state.active
        active_after = active_before
        pending = self._state.pending_release_since
        event: PolicyEvent | None = None
        trustworthy = self._trustworthy(at, local_state, local_effect)
        episode_id = None if local_state is None else local_state.episode_id
        authorization_valid = self._authorization_valid(at, local_state, authorization)
        reason = "inactive_below_on" if not active_before else "active_hold"

        if not active_before:
            pending = None
            if belief_after.probability >= self._calibration.on_threshold:
                if trustworthy and authorization_valid and episode_id is not None:
                    active_after = True
                    reason = "acquired"
                    if emit_event:
                        event = self._event(
                            "acquired", at, episode_id, belief_after, authorization
                        )
                    dedup = self._remember_episode(dedup, episode_id, at)
                else:
                    reason = "acquisition_unauthorized"
        else:
            if belief_after.probability <= self._calibration.off_threshold:
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
                and trustworthy
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
            self._state.zone,
            self._state.profile_name,
            active_after,
            at,
            pending,
            dedup,
        )
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
            self._state.zone,
            self._state.profile_name,
            False,
            at,
            None,
            self._pruned_dedup(at),
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
    def _trustworthy(
        at: datetime,
        state: EpisodeState | None,
        effect: EpisodeEffect | None,
    ) -> bool:
        return bool(
            state is not None
            and effect is not None
            and effect.kind == "positive"
            and effect.at == at
            and effect.node_id == state.node_id
            and effect.zone == state.zone
            and effect.episode_id == state.episode_id
            and state.status == "asserted"
            and not state.health_warning
            and state.started_at is not None
            and state.traversal_valid_until is not None
            and state.started_at <= at < state.traversal_valid_until
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
