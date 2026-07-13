from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .occupancy_graph import ZoneGraph
from .occupancy_state import (
    FilterUpdate,
    ObservationProvenance,
    PendingDepartureAudit,
    PolicyAuditContext,
    PolicyAuditEntry,
    PolicyDecision,
    PositiveEvidence,
    ReleaseCause,
    ZonePolicyState,
    zone_marginals,
)
from .policy_audit import (
    pack_policy_audit_context,
    packed_policy_audit_context_size,
)

ACTIVATION_OCCUPIED_THRESHOLD = 0.60
ACTIVATION_DELTA_THRESHOLD = 0.20
ACTIVATION_SOURCE_OCCUPIED_THRESHOLD = 0.10
GRAPH_RELEASE_OCCUPIED_THRESHOLD = 0.20
GRAPH_RELEASE_MOVEMENT_THRESHOLD = 0.85
RELOCATION_ORIGIN_THRESHOLD = 0.10
RELOCATION_DESTINATION_THRESHOLD = 0.80
RELOCATION_ODDS_THRESHOLD = 10.0
PROVISIONAL_RECOVERY_OCCUPIED_THRESHOLD = 0.40
POLICY_AUDIT_RETENTION = timedelta(hours=12)
POLICY_AUDIT_MAX_ENTRIES = 8192
POLICY_AUDIT_MAX_CONTEXT_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class PendingDeparture:
    """Accumulated path evidence carrying occupancy away from one origin."""

    origin: str
    current: str
    probability: float
    nonadjacent: bool
    evidence_ids: tuple[str, ...]
    disposition: str = "graph_valid"


class AutomationPolicy:
    """Project posterior evidence into conservative automation latches."""

    def __init__(
        self,
        graph: ZoneGraph,
        activation_window: timedelta = timedelta(seconds=5),
    ) -> None:
        self.graph = graph
        self.activation_window = activation_window
        self._states = {zone: ZonePolicyState() for zone in graph.zones()}
        self._pending_departures: dict[str, PendingDeparture] = {}
        self._last_decisions: tuple[PolicyDecision, ...] = ()
        self._policy_audit: deque[PolicyAuditEntry] = deque()
        self._policy_audit_context_bytes = 0
        self._latest_positive_episodes = {
            zone: tuple[str, ...]() for zone in graph.zones()
        }

    @property
    def states(self) -> dict[str, ZonePolicyState]:
        return self._states.copy()

    @property
    def pending_departures(self) -> dict[str, PendingDeparture]:
        return self._pending_departures.copy()

    @property
    def last_decisions(self) -> tuple[PolicyDecision, ...]:
        return self._last_decisions

    @property
    def policy_audit(self) -> tuple[PolicyAuditEntry, ...]:
        return tuple(self._policy_audit)

    def apply(
        self,
        update: FilterUpdate,
        *,
        emit_activation: bool = True,
    ) -> dict[str, ZonePolicyState]:
        """Apply one immutable filter update without feeding policy back into it."""

        now = update.current.updated_at
        previous_states = self.states
        self.expire(now)
        provenance = update.provenance
        self._latest_positive_episodes = {
            zone: tuple(
                evidence.evidence_episode_id
                for evidence in update.active_positive_evidence.get(zone, ())
            )
            for zone in self._states
        }
        if provenance.disposition not in {"accepted", "replacement"}:
            self._record_decisions(
                (
                PolicyDecision(
                    provenance.zone,
                    "observe",
                    False,
                    f"observation_{provenance.disposition}",
                    {"disposition": provenance.disposition},
                    (provenance.event_id,),
                ),
                ),
                decision_at=now,
                source="observation",
                previous_states=previous_states,
                provenance=provenance,
                context=self._audit_context(update),
            )
            return self.states

        self._advance_departures(update)
        audit_context = self._audit_context(update)
        previous_marginals = (
            dict(update.previous_occupied_marginals)
            if update.previous_occupied_marginals
            else zone_marginals(update.previous, self.graph.zones())[0]
        )
        decisions = self._release_supported_origins(update, previous_marginals)

        if provenance.state == "on":
            decisions.append(
                self._authorize_activation(
                    update,
                    previous_marginals,
                    emit_activation,
                )
            )
        else:
            decisions.append(
                PolicyDecision(
                    provenance.zone,
                    "activate",
                    False,
                    "non_positive_observation",
                    {"state_on": False},
                    (provenance.event_id,),
                )
            )
        self._record_decisions(
            tuple(decisions),
            decision_at=now,
            source="observation",
            previous_states=previous_states,
            provenance=provenance,
            context=audit_context,
        )
        return self.states

    def expire(
        self,
        now: datetime,
        occupied_marginals: Mapping[str, float] | None = None,
        active_positive_evidence: Mapping[str, tuple[PositiveEvidence, ...]]
        | None = None,
    ) -> bool:
        """Expire activation pulses while preserving keep-on ownership."""

        if active_positive_evidence is not None:
            self._latest_positive_episodes = {
                zone: tuple(
                    evidence.evidence_episode_id
                    for evidence in active_positive_evidence.get(zone, ())
                )
                for zone in self._states
            }
        changed = False
        for zone, state in tuple(self._states.items()):
            if (
                state.activation_expires_at is not None
                and state.activation_expires_at <= now
            ):
                self._states[zone] = replace(state, activation_expires_at=None)
                changed = True
        audit_size = len(self._policy_audit)
        self._prune_policy_audit(now)
        return changed or len(self._policy_audit) != audit_size

    def activation_plausible(self, zone: str, now: datetime) -> bool:
        state = self._states.get(zone)
        return bool(
            state is not None
            and state.activation_expires_at is not None
            and state.activation_expires_at > now
        )

    def reconcile_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
        occupied_marginals: dict[str, float] | None = None,
    ) -> None:
        """Apply an authoritative occupant-count command to policy latches."""

        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        previous_states = self.states
        if expected_occupants == 0:
            self._clear_all(
                now,
                "authoritative occupant count is zero",
                evidence_id,
                ReleaseCause.AUTHORITATIVE_AWAY,
            )
            self._record_decisions(
                tuple(
                PolicyDecision(
                    zone,
                    "release",
                    True,
                    "authoritative_away",
                    {"expected_occupants": 0.0},
                    (evidence_id,),
                )
                for zone in sorted(self._states)
                ),
                decision_at=now,
                source="occupant_count",
                previous_states=previous_states,
                trigger_event_id=evidence_id,
            )
            return
        if occupied_marginals is None:
            self._record_decisions(
                (),
                decision_at=now,
                source="occupant_count",
                previous_states=previous_states,
                trigger_event_id=evidence_id,
            )
            return
        retained = {
            zone
            for zone, _ in sorted(
                occupied_marginals.items(),
                key=lambda item: (-item[1], item[0]),
            )[:expected_occupants]
        }
        decisions: list[PolicyDecision] = []
        for zone, state in tuple(self._states.items()):
            if zone in retained or (
                not state.keep_on and state.activation_expires_at is None
            ):
                continue
            self._states[zone] = ZonePolicyState(
                keep_on=False,
                last_trusted_at=state.last_trusted_at,
                last_release_cause=ReleaseCause.COUNT_REDUCTION,
                reason="authoritative occupant count reduction",
                evidence_ids=_append_evidence(state.evidence_ids, evidence_id),
                blocked_episode_ids=self._latest_positive_episodes.get(zone, ()),
            )
            self._pending_departures.pop(zone, None)
            decisions.append(
                PolicyDecision(
                    zone,
                    "release",
                    True,
                    "occupant_count_reduction",
                    {
                        "expected_occupants": float(expected_occupants),
                        "occupied_marginal": occupied_marginals.get(zone, 0.0),
                    },
                    (evidence_id,),
                )
            )
        self._record_decisions(
            tuple(decisions),
            decision_at=now,
            source="occupant_count",
            previous_states=previous_states,
            trigger_event_id=evidence_id,
        )

    def reset(self, now: datetime, evidence_id: str = "explicit_reset") -> None:
        """Release all policy state through an explicit diagnosable reset."""

        previous_states = self.states
        self._clear_all(
            now,
            "explicit reset",
            evidence_id,
            ReleaseCause.EXPLICIT_RESET,
        )
        self._record_decisions(
            tuple(
            PolicyDecision(
                zone,
                "release",
                True,
                "explicit_reset",
                {"reset": True},
                (evidence_id,),
            )
            for zone in sorted(self._states)
            ),
            decision_at=now,
            source="reset",
            previous_states=previous_states,
            trigger_event_id=evidence_id,
        )

    def enter_unsupported_count(
        self,
        requested_count: int,
        evidence_id: str,
        decision_at: datetime,
    ) -> None:
        """Suspend transient policy state without causing a false-off."""

        previous_states = self.states
        self._states = {
            zone: replace(state, activation_expires_at=None)
            for zone, state in self._states.items()
        }
        self._pending_departures.clear()
        self._record_decisions(
            tuple(
            PolicyDecision(
                zone,
                "suspend",
                True,
                "unsupported_occupant_count",
                {"requested_occupants": float(requested_count)},
                (evidence_id,),
            )
            for zone in sorted(self._states)
            ),
            decision_at=decision_at,
            source="unsupported_occupant_count",
            previous_states=previous_states,
            trigger_event_id=evidence_id,
        )

    def restore_states(self, states: dict[str, ZonePolicyState]) -> None:
        """Restore policy only when it exactly matches configured zones."""

        if set(states) != set(self._states):
            raise ValueError("restored policy zones do not match the map")
        self._states = states.copy()
        self._last_decisions = ()
        self._policy_audit.clear()
        self._policy_audit_context_bytes = 0
        self._latest_positive_episodes = {
            zone: tuple[str, ...]() for zone in self._states
        }

    def restore_policy_audit(self, audit: tuple[PolicyAuditEntry, ...]) -> None:
        """Restore already-validated retained policy decisions."""

        self._policy_audit = deque(audit)
        self._policy_audit_context_bytes = sum(
            packed_policy_audit_context_size(entry.context) for entry in audit
        )
        self._bound_policy_audit()

    def _record_decisions(
        self,
        decisions: tuple[PolicyDecision, ...],
        *,
        decision_at: datetime,
        source: str,
        previous_states: dict[str, ZonePolicyState],
        provenance: ObservationProvenance | None = None,
        trigger_event_id: str = "",
        context: PolicyAuditContext | None = None,
    ) -> None:
        self._last_decisions = decisions
        packed_context = (
            None if context is None else pack_policy_audit_context(context)
        )
        for index, decision in enumerate(decisions):
            previous = previous_states.get(decision.zone, ZonePolicyState())
            current = self._states.get(decision.zone, ZonePolicyState())
            entry = PolicyAuditEntry(
                decision_at=decision_at,
                source=source,
                trigger_event_id=(
                    provenance.event_id
                    if provenance is not None
                    else trigger_event_id
                ),
                trigger_entity_id=(
                    None if provenance is None else provenance.entity_id
                ),
                trigger_zone=None if provenance is None else provenance.zone,
                trigger_state=None if provenance is None else provenance.state,
                trigger_disposition=(
                    None if provenance is None else provenance.disposition
                ),
                decision=decision,
                previous_keep_on=previous.keep_on,
                current_keep_on=current.keep_on,
                previous_reason=previous.reason,
                current_reason=current.reason,
                previous_release_cause=previous.last_release_cause,
                current_release_cause=current.last_release_cause,
                context=(packed_context if index == len(decisions) - 1 else None),
            )
            self._policy_audit.append(entry)
            self._policy_audit_context_bytes += packed_policy_audit_context_size(
                entry.context
            )
        self._prune_policy_audit(decision_at)

    def _audit_context(self, update: FilterUpdate) -> PolicyAuditContext:
        previous_marginals = (
            dict(update.previous_occupied_marginals)
            if update.previous_occupied_marginals
            else zone_marginals(update.previous, self.graph.zones())[0]
        )
        return PolicyAuditContext(
            provenance=update.provenance,
            previous_occupied_marginals=previous_marginals,
            occupied_marginals=dict(update.occupied_marginals),
            count_marginals=dict(update.count_marginals),
            active_positive_evidence={
                zone: tuple(evidence)
                for zone, evidence in sorted(update.active_positive_evidence.items())
            },
            movement_evidence=update.movement_evidence,
            pending_departures=tuple(
                PendingDepartureAudit(
                    origin=departure.origin,
                    current=departure.current,
                    probability=departure.probability,
                    nonadjacent=departure.nonadjacent,
                    evidence_ids=departure.evidence_ids,
                    disposition=departure.disposition,
                )
                for _, departure in sorted(self._pending_departures.items())
            ),
        )

    def _prune_policy_audit(self, now: datetime) -> None:
        cutoff = now - POLICY_AUDIT_RETENTION
        while self._policy_audit and self._policy_audit[0].decision_at < cutoff:
            self._discard_oldest_policy_audit_entry()
        self._bound_policy_audit()

    def _bound_policy_audit(self) -> None:
        while self._policy_audit and (
            len(self._policy_audit) > POLICY_AUDIT_MAX_ENTRIES
            or self._policy_audit_context_bytes
            > POLICY_AUDIT_MAX_CONTEXT_BYTES
        ):
            self._discard_oldest_policy_audit_entry()

    def _discard_oldest_policy_audit_entry(self) -> None:
        entry = self._policy_audit.popleft()
        self._policy_audit_context_bytes -= packed_policy_audit_context_size(
            entry.context
        )

    def restore_pending_departures(
        self,
        departures: dict[str, PendingDeparture],
    ) -> None:
        """Restore coherent paths only when every endpoint remains valid."""

        valid_zones = set(self._states)
        if any(
            origin != departure.origin
            or origin not in valid_zones
            or departure.current not in valid_zones
            or not 0.0 <= departure.probability <= 1.0
            or departure.disposition
            not in {"graph_valid", "missed_movement", "missed_timing"}
            for origin, departure in departures.items()
        ):
            raise ValueError("restored pending departure is invalid")
        self._pending_departures = departures.copy()

    def _authorize_activation(
        self,
        update: FilterUpdate,
        previous_marginals: dict[str, float],
        emit_activation: bool,
    ) -> PolicyDecision:
        zone = update.provenance.zone
        occupied = update.occupied_marginals.get(zone, 0.0)
        increase = occupied - previous_marginals.get(zone, 0.0)
        state = self._states[zone]
        graph_arrivals = tuple(
            evidence
            for evidence in update.movement_evidence
            if evidence.target_zone == zone and evidence.disposition == "graph_valid"
        )
        strongest_arrival = max(
            graph_arrivals,
            key=lambda evidence: (evidence.coherent_probability, evidence.path_key),
            default=None,
        )
        movement_in = (
            0.0
            if strongest_arrival is None
            else strongest_arrival.coherent_probability
        )
        source_prior = (
            0.0
            if strongest_arrival is None
            else previous_marginals.get(strongest_arrival.source_zone, 0.0)
        )
        graph_arrival_supported = (
            strongest_arrival is not None
            and source_prior >= ACTIVATION_SOURCE_OCCUPIED_THRESHOLD
        )
        prior_unlocated = _unlocated_probability(update.previous)
        structured_evidence = update.active_positive_evidence.get(zone, ())
        eligible_evidence = tuple(
            evidence
            for evidence in structured_evidence
            if evidence.evidence_episode_id not in state.blocked_episode_ids
        )
        eligible_entities = tuple(evidence.entity_id for evidence in eligible_evidence)
        eligible_nodes = tuple(
            sorted(
                {
                    evidence.node_id or evidence.entity_id
                    for evidence in eligible_evidence
                }
            )
        )
        if not structured_evidence:
            eligible_entities = update.active_positive_entities.get(zone, ())
            eligible_nodes = eligible_entities
        independently_corroborated = len(eligible_nodes) >= 2
        recovering = (
            state.last_trusted_at is not None
            and not state.keep_on
            and state.recovery_eligible
            and state.last_release_cause == ReleaseCause.PROVISIONAL_FALSE_OFF
        )
        occupied_threshold = (
            PROVISIONAL_RECOVERY_OCCUPIED_THRESHOLD
            if recovering
            else ACTIVATION_OCCUPIED_THRESHOLD
        )
        supported = (
            graph_arrival_supported
            or prior_unlocated >= 0.50
            or independently_corroborated
            or recovering
        )
        gate_values: dict[str, float | bool | str] = {
            "occupied_marginal": occupied,
            "occupied_threshold": occupied_threshold,
            "increase": increase,
            "increase_threshold": ACTIVATION_DELTA_THRESHOLD,
            "movement_in": movement_in,
            "source_prior": source_prior,
            "source_threshold": ACTIVATION_SOURCE_OCCUPIED_THRESHOLD,
            "graph_arrival_supported": graph_arrival_supported,
            "prior_unlocated": prior_unlocated,
            "independently_corroborated": independently_corroborated,
            "corroborating_entity_count": float(len(eligible_entities)),
            "corroborating_entities": ",".join(eligible_entities),
            "corroborating_node_count": float(len(eligible_nodes)),
            "corroborating_nodes": ",".join(eligible_nodes),
            "recovering": recovering,
            "supported": supported,
        }
        if occupied < occupied_threshold:
            return PolicyDecision(
                zone,
                "activate",
                False,
                "occupied_gate_failed",
                gate_values,
                (update.provenance.event_id,),
            )
        if increase < ACTIVATION_DELTA_THRESHOLD:
            return PolicyDecision(
                zone,
                "activate",
                False,
                "increase_gate_failed",
                gate_values,
                (update.provenance.event_id,),
            )
        if not supported:
            return PolicyDecision(
                zone,
                "activate",
                False,
                "support_gate_failed",
                gate_values,
                (update.provenance.event_id,),
            )

        reason = "trusted local occupancy established"
        if recovering:
            reason = "trusted occupancy reacquired after release"
        elif graph_arrival_supported:
            reason = "graph-supported local arrival"
        elif independently_corroborated:
            reason = "independent local sensors corroborated occupancy"
        self._states[zone] = ZonePolicyState(
            keep_on=True,
            activation_expires_at=(
                update.current.updated_at + self.activation_window
                if emit_activation
                else None
            ),
            last_trusted_at=update.current.updated_at,
            last_release_cause=None,
            recovery_eligible=False,
            reason=reason,
            evidence_ids=_append_evidence(
                state.evidence_ids,
                *(
                    eligible_entities
                    if independently_corroborated
                    else (update.provenance.event_id,)
                ),
            ),
            blocked_episode_ids=(),
        )
        reason_code = "trusted_local_occupancy"
        if recovering:
            reason_code = "provisional_false_off_recovery"
        elif graph_arrival_supported:
            reason_code = "graph_supported_arrival"
        elif independently_corroborated:
            reason_code = "independent_corroboration"
        return PolicyDecision(
            zone,
            "activate",
            True,
            reason_code,
            gate_values,
            eligible_entities
            if independently_corroborated
            else (update.provenance.event_id,),
        )

    def _advance_departures(self, update: FilterUpdate) -> None:
        candidates = tuple(
            evidence
            for evidence in update.movement_evidence
            if evidence.coherent_probability > 0.0
        )
        if not candidates:
            return
        strongest = max(
            candidates,
            key=lambda evidence: (
                evidence.coherent_probability,
                evidence.path_key,
            ),
        )
        if any(
            evidence.origin_zone != strongest.origin_zone
            and abs(evidence.coherent_probability - strongest.coherent_probability)
            <= 1e-12
            for evidence in candidates
        ):
            return
        self._pending_departures[strongest.origin_zone] = PendingDeparture(
            origin=strongest.origin_zone,
            current=strongest.target_zone,
            probability=strongest.coherent_probability,
            nonadjacent=strongest.disposition != "graph_valid",
            evidence_ids=strongest.evidence_ids,
            disposition=strongest.disposition,
        )

    def _release_supported_origins(
        self,
        update: FilterUpdate,
        previous_marginals: dict[str, float],
    ) -> list[PolicyDecision]:
        decisions: list[PolicyDecision] = []
        for origin, pending in tuple(self._pending_departures.items()):
            state = self._states.get(origin)
            if state is None or not state.keep_on:
                continue
            origin_probability = update.occupied_marginals.get(origin, 0.0)
            destination_probability = update.occupied_marginals.get(
                pending.current,
                0.0,
            )
            destination_nodes = {
                evidence.node_id or evidence.entity_id
                for evidence in update.active_positive_evidence.get(
                    pending.current,
                    (),
                )
            }
            independently_corroborated = len(destination_nodes) >= 2
            if pending.disposition == "missed_timing":
                releasable = False
                reason = "movement timing outside graph release window"
                reason_code = "missed_timing"
            elif pending.nonadjacent:
                odds = destination_probability / max(origin_probability, 1e-12)
                releasable = (
                    origin_probability <= RELOCATION_ORIGIN_THRESHOLD
                    and destination_probability >= RELOCATION_DESTINATION_THRESHOLD
                    and odds >= RELOCATION_ODDS_THRESHOLD
                    and independently_corroborated
                )
                reason = "confident non-adjacent relocation"
                reason_code = "confirmed_relocation"
            else:
                releasable = (
                    origin_probability <= GRAPH_RELEASE_OCCUPIED_THRESHOLD
                    and pending.probability >= GRAPH_RELEASE_MOVEMENT_THRESHOLD
                    and previous_marginals.get(origin, 0.0) > origin_probability
                )
                reason = "graph-valid final occupant departure"
                reason_code = "graph_departure"
            gate_values: dict[str, float | bool | str] = {
                "origin_marginal": origin_probability,
                "destination_marginal": destination_probability,
                "coherent_probability": pending.probability,
                "nonadjacent": pending.nonadjacent,
            }
            if pending.nonadjacent and pending.disposition != "missed_timing":
                gate_values["relocation_odds"] = odds
                gate_values["independently_corroborated"] = (
                    independently_corroborated
                )
                gate_values["corroborating_node_count"] = float(
                    len(destination_nodes)
                )
                gate_values["corroborating_nodes"] = ",".join(
                    sorted(destination_nodes)
                )
            if not releasable:
                decisions.append(
                    PolicyDecision(
                        origin,
                        "release",
                        False,
                        f"{reason_code}_gate_failed",
                        gate_values,
                        pending.evidence_ids,
                    )
                )
                continue
            self._states[origin] = ZonePolicyState(
                keep_on=False,
                activation_expires_at=None,
                last_trusted_at=state.last_trusted_at,
                last_release_cause=(
                    ReleaseCause.CONFIRMED_RELOCATION
                    if pending.nonadjacent
                    else ReleaseCause.GRAPH_DEPARTURE
                ),
                recovery_eligible=False,
                reason=reason,
                evidence_ids=_append_evidence(
                    state.evidence_ids,
                    *pending.evidence_ids,
                ),
                blocked_episode_ids=self._latest_positive_episodes.get(origin, ()),
            )
            del self._pending_departures[origin]
            decisions.append(
                PolicyDecision(
                    origin,
                    "release",
                    True,
                    reason_code,
                    gate_values,
                    pending.evidence_ids,
                )
            )
        return decisions

    def _clear_all(
        self,
        now: datetime,
        reason: str,
        evidence_id: str,
        release_cause: ReleaseCause,
    ) -> None:
        for zone, state in tuple(self._states.items()):
            self._states[zone] = ZonePolicyState(
                keep_on=False,
                activation_expires_at=None,
                last_trusted_at=state.last_trusted_at or now,
                last_release_cause=release_cause,
                recovery_eligible=False,
                reason=reason,
                evidence_ids=_append_evidence(state.evidence_ids, evidence_id),
                blocked_episode_ids=self._latest_positive_episodes.get(zone, ()),
            )
        self._pending_departures.clear()


def _unlocated_probability(posterior: object) -> float:
    hypotheses = getattr(posterior, "hypotheses", ())
    return sum(
        math.exp(hypothesis.log_probability)
        for hypothesis in hypotheses
        if any(position.zone is None for position in hypothesis.key.positions)
    )


def _append_evidence(existing: tuple[str, ...], *items: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, *items)))[-8:]
