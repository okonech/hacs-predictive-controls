"""Automation ownership policy over exact posterior events."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ..occupancy_state import (
    PackedPolicyAuditContext,
    PolicyDecision,
    ReleaseCause,
    ZonePolicyState,
)
from ..policy_audit import packed_policy_audit_context_size

POLICY_AUDIT_RETENTION = timedelta(hours=12)
POLICY_AUDIT_MAX_ENTRIES = 8192
POLICY_AUDIT_MAX_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class PosteriorPolicyAuditEntry:
    """One retained target policy decision and its latch transition."""

    decision_at: datetime
    decision: PolicyDecision
    prior_active: bool
    resulting_active: bool
    context: PackedPolicyAuditContext | None = None


class PosteriorEventPolicy:
    """Latch active ownership from ArrivalSupported and ReleaseSafe only."""

    def __init__(
        self,
        zones: tuple[str, ...],
        *,
        activation_threshold: float,
        release_threshold: float,
        activation_window: timedelta = timedelta(seconds=5),
    ) -> None:
        if not 0.0 <= activation_threshold <= 1.0:
            raise ValueError("activation threshold must be in [0, 1]")
        if not 0.0 <= release_threshold <= 1.0:
            raise ValueError("release threshold must be in [0, 1]")
        if activation_window < timedelta(0):
            raise ValueError("activation window must be non-negative")
        self.activation_threshold = activation_threshold
        self.release_threshold = release_threshold
        self.activation_window = activation_window
        self._states = {zone: ZonePolicyState() for zone in zones}
        self._last_decisions: tuple[PolicyDecision, ...] = ()
        self._audit: deque[PosteriorPolicyAuditEntry] = deque()
        self._audit_bytes = 0

    @property
    def states(self) -> dict[str, ZonePolicyState]:
        return self._states.copy()

    @property
    def last_decisions(self) -> tuple[PolicyDecision, ...]:
        return self._last_decisions

    @property
    def audit(self) -> tuple[PosteriorPolicyAuditEntry, ...]:
        return tuple(self._audit)

    @property
    def retained_audit_bytes(self) -> int:
        return self._audit_bytes

    def apply(
        self,
        now: datetime,
        expected_occupants: int,
        arrival_supported: Mapping[str, float],
        release_safe_available: bool,
        release_safe: Mapping[str, float],
        *,
        emit_activation: bool,
        arrival_evidence_ids: Mapping[str, tuple[str, ...]] | None = None,
        audit_context: PackedPolicyAuditContext | None = None,
    ) -> dict[str, ZonePolicyState]:
        """Apply available posterior events; missing values never authorize edges."""

        self.expire(now)
        arrival_evidence_ids = arrival_evidence_ids or {}
        prior_states = self.states
        decisions: list[PolicyDecision] = []
        if expected_occupants == 0:
            for zone, state in self._states.items():
                self._states[zone] = replace(
                    state,
                    keep_on=False,
                    activation_expires_at=None,
                    last_release_cause=ReleaseCause.AUTHORITATIVE_AWAY,
                    recovery_eligible=False,
                    reason="authoritative zero occupants",
                )
                decisions.append(
                    PolicyDecision(
                        zone,
                        "release",
                        True,
                        "authoritative_away",
                        {"expected_occupants": 0},
                    )
                )
            self._record_decisions(now, prior_states, decisions, audit_context)
            return self.states

        released: set[str] = set()
        for zone, state in self._states.items():
            if not state.keep_on:
                continue
            probability = release_safe.get(zone) if release_safe_available else None
            accepted = probability is not None and probability >= self.release_threshold
            decisions.append(
                PolicyDecision(
                    zone,
                    "release",
                    accepted,
                    "release_safe" if accepted else "release_safe_not_met",
                    {
                        "available": release_safe_available,
                        "probability": -1.0 if probability is None else probability,
                        "threshold": self.release_threshold,
                    },
                )
            )
            if accepted:
                self._states[zone] = replace(
                    state,
                    keep_on=False,
                    activation_expires_at=None,
                    last_release_cause=ReleaseCause.RELEASE_SAFE,
                    recovery_eligible=False,
                    reason="finalized release-safe posterior event",
                )
                released.add(zone)

        for zone, probability in sorted(arrival_supported.items()):
            if zone not in self._states or zone in released:
                continue
            state = self._states[zone]
            if probability < self.activation_threshold:
                decisions.append(
                    PolicyDecision(
                        zone,
                        "activate",
                        False,
                        "arrival_supported_not_met",
                        {
                            "probability": probability,
                            "threshold": self.activation_threshold,
                        },
                        arrival_evidence_ids.get(zone, ()),
                    )
                )
                continue
            if state.keep_on:
                decisions.append(
                    PolicyDecision(
                        zone,
                        "activate",
                        False,
                        "already_active",
                        {
                            "probability": probability,
                            "threshold": self.activation_threshold,
                        },
                        arrival_evidence_ids.get(zone, ()),
                    )
                )
                continue
            self._states[zone] = replace(
                state,
                keep_on=True,
                activation_expires_at=(
                    now + self.activation_window if emit_activation else None
                ),
                last_trusted_at=now,
                last_release_cause=None,
                recovery_eligible=False,
                reason="arrival-supported posterior event",
            )
            decisions.append(
                PolicyDecision(
                    zone,
                    "activate",
                    True,
                    "arrival_supported",
                    {
                        "probability": probability,
                        "threshold": self.activation_threshold,
                    },
                    arrival_evidence_ids.get(zone, ()),
                )
            )
        self._record_decisions(now, prior_states, decisions, audit_context)
        return self.states

    def expire(self, now: datetime) -> bool:
        changed = False
        audit_size = len(self._audit)
        for zone, state in self._states.items():
            if (
                state.activation_expires_at is not None
                and state.activation_expires_at <= now
            ):
                self._states[zone] = replace(state, activation_expires_at=None)
                changed = True
        self._prune_audit(now)
        return changed or len(self._audit) != audit_size

    def reset(self, now: datetime) -> dict[str, ZonePolicyState]:
        prior_states = self.states
        for zone, state in self._states.items():
            self._states[zone] = replace(
                state,
                keep_on=False,
                activation_expires_at=None,
                last_release_cause=ReleaseCause.EXPLICIT_RESET,
                recovery_eligible=False,
                reason="explicit reset",
            )
        decisions = tuple(
            PolicyDecision(
                zone,
                "release",
                True,
                "explicit_reset",
                {"reset_at": now.isoformat()},
            )
            for zone in self._states
        )
        self._record_decisions(now, prior_states, decisions)
        return self.states

    def restore_states(self, states: Mapping[str, ZonePolicyState]) -> None:
        if set(states) != set(self._states):
            raise ValueError("Restored policy zones do not match")
        if any(not isinstance(state, ZonePolicyState) for state in states.values()):
            raise ValueError("Restored policy states are invalid")
        self._states = dict(states)
        self._last_decisions = ()

    def restore_audit(
        self,
        entries: tuple[PosteriorPolicyAuditEntry, ...],
        now: datetime,
    ) -> None:
        if any(entry.decision.zone not in self._states for entry in entries):
            raise ValueError("Restored policy audit contains an unknown zone")
        if any(
            later.decision_at < earlier.decision_at
            for earlier, later in zip(entries, entries[1:], strict=False)
        ):
            raise ValueError("Restored policy audit is not ordered")
        self._audit = deque(entries)
        self._audit_bytes = sum(self._audit_entry_size(entry) for entry in entries)
        self._prune_audit(now)

    def _record_decisions(
        self,
        now: datetime,
        prior_states: Mapping[str, ZonePolicyState],
        decisions: list[PolicyDecision] | tuple[PolicyDecision, ...],
        audit_context: PackedPolicyAuditContext | None = None,
    ) -> None:
        self._last_decisions = tuple(decisions)
        for decision in decisions:
            entry = PosteriorPolicyAuditEntry(
                now,
                decision,
                prior_states[decision.zone].keep_on,
                self._states[decision.zone].keep_on,
                audit_context,
            )
            self._audit.append(entry)
            self._audit_bytes += self._audit_entry_size(entry)
        self._prune_audit(now)

    def _prune_audit(self, now: datetime) -> None:
        cutoff = now - POLICY_AUDIT_RETENTION
        while self._audit and self._audit[0].decision_at < cutoff:
            self._discard_oldest_audit_entry()
        while self._audit and (
            len(self._audit) > POLICY_AUDIT_MAX_ENTRIES
            or self._audit_bytes > POLICY_AUDIT_MAX_BYTES
        ):
            self._discard_oldest_audit_entry()

    def _discard_oldest_audit_entry(self) -> None:
        self._audit_bytes -= self._audit_entry_size(self._audit.popleft())

    @staticmethod
    def _audit_entry_size(entry: PosteriorPolicyAuditEntry) -> int:
        return (
            len(
            json.dumps(
                {
                    "decision_at": entry.decision_at.isoformat(),
                    "zone": entry.decision.zone,
                    "action": entry.decision.action,
                    "accepted": entry.decision.accepted,
                    "reason_code": entry.decision.reason_code,
                    "gate_values": entry.decision.gate_values,
                    "evidence_ids": entry.decision.evidence_ids,
                    "prior_active": entry.prior_active,
                    "resulting_active": entry.resulting_active,
                    "context_bytes": packed_policy_audit_context_size(
                        entry.context
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            )
            + packed_policy_audit_context_size(entry.context)
        )
