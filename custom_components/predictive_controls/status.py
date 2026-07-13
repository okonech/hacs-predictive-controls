from __future__ import annotations

import math
from datetime import datetime
from typing import Any, cast

from .automation_policy import POLICY_AUDIT_RETENTION
from .occupancy_persistence import policy_audit_context_payload


def runtime_status_payload(runtime: Any) -> dict[str, Any]:
    """Serialize live runtime status for diagnostics and WebSocket clients."""

    payload = {
        "zone_states": {
            zone: zone_state_payload(state)
            for zone, state in runtime.zone_states.items()
        },
        "recent_occupancy_events": [
            occupancy_event_payload(event)
            for event in runtime.recent_occupancy_events
        ],
        "last_source_node": runtime.last_source_node,
        "last_prediction": None
        if runtime.last_prediction is None
        else {
            "node_id": runtime.last_prediction.node_id,
            "probability": runtime.last_prediction.probability,
        },
        "probabilities": runtime.probabilities,
        "transition_counts": runtime.transition_counts,
        "expected_occupants": getattr(runtime, "expected_occupants", 0),
        "occupancy_diagnostics": tracker_diagnostics_payload(
            runtime.confidence.diagnostics
        ),
    }
    latency_metrics = getattr(runtime, "latency_metrics", None)
    if latency_metrics is not None:
        payload["latency"] = latency_metrics
    return payload


def zone_state_payload(state: Any) -> dict[str, Any]:
    return {
        "confidence": state.confidence,
        "status": state.status,
        "occupancy_behavior": state.occupancy_behavior,
        "active_since": state.active_since.isoformat()
        if state.active_since is not None
        else None,
        "last_evidence_at": state.last_evidence_at.isoformat()
        if state.last_evidence_at is not None
        else None,
        "last_clear_at": state.last_clear_at.isoformat()
        if state.last_clear_at is not None
        else None,
        "last_node_id": state.last_node_id,
        "reason": state.reason,
        "explanation": dict(getattr(state, "explanation", {})),
    }


def tracker_diagnostics_payload(diagnostics: Any) -> dict[str, Any]:
    payload = {
        "expected_occupants": diagnostics.expected_occupants,
        "protected_tracks": list(diagnostics.protected_tracks),
        "protected_corridor": list(diagnostics.protected_corridor),
        "inferred_join_slots": [
            join_slot_payload(slot) for slot in diagnostics.inferred_join_slots
        ],
        "inferred_departures": [
            departure_payload(departure)
            for departure in diagnostics.inferred_departures
        ],
        "entry_plausibilities": [
            entry_plausibility_payload(plausibility)
            for plausibility in diagnostics.entry_plausibilities
        ],
        "activation_plausibilities": [
            activation_plausibility_payload(plausibility)
            for plausibility in diagnostics.activation_plausibilities
        ],
        "prediction_hints": diagnostics.prediction_hints,
        "dwell_seconds": diagnostics.dwell_seconds,
        "tracks": [track_payload(track) for track in diagnostics.tracks],
    }
    joint_posterior = getattr(diagnostics, "joint_posterior", ())
    joint_provenance = getattr(diagnostics, "joint_last_provenance", None)
    if joint_posterior or joint_provenance is not None:
        policy_audit = tuple(getattr(diagnostics, "joint_policy_audit", ()))
        oldest_decision_at = cast(
            datetime | None,
            min(
                (entry.decision_at for entry in policy_audit),
                default=None,
            ),
        )
        newest_decision_at = cast(
            datetime | None,
            max(
                (entry.decision_at for entry in policy_audit),
                default=None,
            ),
        )
        payload["joint"] = {
            "hypotheses": [
                {
                    "probability": math.exp(hypothesis.log_probability),
                    "positions": [
                        {
                            "zone": position.zone,
                            "incoming_zone": position.incoming_zone,
                            "entered_at": position.entered_at.isoformat()
                            if position.entered_at is not None
                            else None,
                        }
                        for position in hypothesis.key.positions
                    ],
                }
                for hypothesis in joint_posterior
            ],
            "occupied_marginals": getattr(
                diagnostics,
                "joint_occupied_marginals",
                {},
            ),
            "count_marginals": getattr(diagnostics, "joint_count_marginals", {}),
            "posterior_entropy": getattr(
                diagnostics,
                "joint_posterior_entropy",
                0.0,
            ),
            "pruned_probability": getattr(
                diagnostics,
                "joint_pruned_probability",
                0.0,
            ),
            "performance": getattr(diagnostics, "joint_performance", {}),
            "requested_occupants": getattr(
                diagnostics,
                "joint_requested_occupants",
                diagnostics.expected_occupants,
            ),
            "unsupported_count": getattr(
                diagnostics,
                "joint_unsupported_count",
                None,
            ),
            "policy": {
                zone: {
                    "keep_on": state.keep_on,
                    "activation_expires_at": state.activation_expires_at.isoformat()
                    if state.activation_expires_at is not None
                    else None,
                    "last_trusted_at": state.last_trusted_at.isoformat()
                    if state.last_trusted_at is not None
                    else None,
                    "last_release_cause": None
                    if state.last_release_cause is None
                    else state.last_release_cause.value,
                    "recovery_eligible": state.recovery_eligible,
                    "reason": state.reason,
                    "evidence_ids": list(state.evidence_ids),
                }
                for zone, state in getattr(
                    diagnostics,
                    "joint_policy_states",
                    {},
                ).items()
            },
            "policy_decisions": [
                {
                    "zone": decision.zone,
                    "action": decision.action,
                    "accepted": decision.accepted,
                    "reason_code": decision.reason_code,
                    "gate_values": dict(decision.gate_values),
                    "evidence_ids": list(decision.evidence_ids),
                }
                for decision in getattr(
                    diagnostics,
                    "joint_policy_decisions",
                    (),
                )
            ],
            "policy_audit": [
                {
                    "decision_at": entry.decision_at.isoformat(),
                    "source": entry.source,
                    "trigger": {
                        "event_id": entry.trigger_event_id,
                        "entity_id": entry.trigger_entity_id,
                        "zone": entry.trigger_zone,
                        "state": entry.trigger_state,
                        "disposition": entry.trigger_disposition,
                    },
                    "decision": {
                        "zone": entry.decision.zone,
                        "action": entry.decision.action,
                        "accepted": entry.decision.accepted,
                        "reason_code": entry.decision.reason_code,
                        "gate_values": dict(entry.decision.gate_values),
                        "evidence_ids": list(entry.decision.evidence_ids),
                    },
                    "previous": {
                        "keep_on": entry.previous_keep_on,
                        "reason": entry.previous_reason,
                        "release_cause": None
                        if entry.previous_release_cause is None
                        else entry.previous_release_cause.value,
                    },
                    "current": {
                        "keep_on": entry.current_keep_on,
                        "reason": entry.current_reason,
                        "release_cause": None
                        if entry.current_release_cause is None
                        else entry.current_release_cause.value,
                    },
                    "context": policy_audit_context_payload(entry.context),
                }
                for entry in policy_audit
            ],
            "policy_audit_retention": {
                "retention_hours": int(
                    POLICY_AUDIT_RETENTION.total_seconds() // 3600
                ),
                "entry_count": len(policy_audit),
                "oldest_decision_at": oldest_decision_at.isoformat()
                if oldest_decision_at is not None
                else None,
                "newest_decision_at": newest_decision_at.isoformat()
                if newest_decision_at is not None
                else None,
            },
            "movement_evidence": [
                {
                    "path_key": list(evidence.path_key),
                    "origin_zone": evidence.origin_zone,
                    "source_zone": evidence.source_zone,
                    "target_zone": evidence.target_zone,
                    "coherent_probability": evidence.coherent_probability,
                    "source_node_id": evidence.source_node_id,
                    "target_node_id": evidence.target_node_id,
                    "evidence_ids": list(evidence.evidence_ids),
                    "disposition": evidence.disposition,
                }
                for evidence in getattr(
                    diagnostics,
                    "joint_movement_evidence",
                    (),
                )
            ],
            "directional_contexts": [
                {
                    "positions": [position.zone for position in key.positions],
                    "contexts": [
                        {
                            "origin_zone": context.origin_zone,
                            "previous_node_id": context.previous_node_id,
                            "current_node_id": context.current_node_id,
                            "started_at": context.started_at.isoformat()
                            if context.started_at is not None
                            else None,
                            "last_event_at": context.last_event_at.isoformat()
                            if context.last_event_at is not None
                            else None,
                            "evidence_ids": list(context.evidence_ids),
                            "probability": math.exp(context.log_probability),
                            "disposition": context.disposition,
                        }
                        for context in contexts
                    ],
                }
                for key, contexts in getattr(
                    diagnostics,
                    "joint_directional_contexts",
                    {},
                ).items()
            ],
            "prediction_leases": [
                {
                    "path_key": list(lease.path_key),
                    "target_zone": lease.target_zone,
                    "probability": lease.probability,
                    "expires_at": lease.expires_at.isoformat(),
                    "reason": lease.reason,
                }
                for lease in getattr(diagnostics, "joint_prediction_leases", ())
            ],
            "prediction_hints": getattr(
                diagnostics,
                "joint_prediction_hints",
                {},
            ),
            "last_provenance": None
            if joint_provenance is None
            else {
                "event_id": joint_provenance.event_id,
                "evidence_episode_id": joint_provenance.evidence_episode_id,
                "entity_id": joint_provenance.entity_id,
                "node_id": joint_provenance.node_id,
                "zone": joint_provenance.zone,
                "state": joint_provenance.state,
                "signal_type": joint_provenance.signal_type,
                "reliability": joint_provenance.reliability,
                "log_likelihood_by_count": list(
                    joint_provenance.log_likelihood_by_count
                ),
                "disposition": joint_provenance.disposition,
            },
            "restore": {
                "status": getattr(
                    diagnostics,
                    "joint_restore_status",
                    "not_attempted",
                ),
                "reason": getattr(diagnostics, "joint_restore_reason", None),
            },
        }
    return payload


def track_payload(track: Any) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "zone": track.zone,
        "confidence": track.confidence,
        "active": track.active,
        "last_evidence_at": track.last_evidence_at.isoformat()
        if track.last_evidence_at is not None
        else None,
        "source_entities": list(track.source_entities),
    }


def join_slot_payload(slot: Any) -> dict[str, Any]:
    return {
        "zone": slot.zone,
        "source_zone": slot.source_zone,
        "source_node_id": slot.source_node_id,
        "event_at": slot.event_at.isoformat(),
        "expires_at": slot.expires_at.isoformat(),
    }


def departure_payload(departure: Any) -> dict[str, Any]:
    return {
        "zone": departure.zone,
        "via_zone": departure.via_zone,
        "via_node_id": departure.via_node_id,
        "destination_zone": departure.destination_zone,
        "event_at": departure.event_at.isoformat(),
        "expires_at": departure.expires_at.isoformat(),
    }


def entry_plausibility_payload(plausibility: Any) -> dict[str, Any]:
    return {
        "zone": plausibility.zone,
        "source_zone": plausibility.source_zone,
        "source_node_id": plausibility.source_node_id,
        "event_at": plausibility.event_at.isoformat(),
        "expires_at": plausibility.expires_at.isoformat(),
    }


def activation_plausibility_payload(plausibility: Any) -> dict[str, Any]:
    return {
        "zone": plausibility.zone,
        "reason": plausibility.reason,
        "source_zone": plausibility.source_zone,
        "source_node_id": plausibility.source_node_id,
        "event_at": plausibility.event_at.isoformat(),
        "expires_at": plausibility.expires_at.isoformat(),
    }


def occupancy_event_payload(event: Any) -> dict[str, Any]:
    return {
        "entity_id": event.entity_id,
        "node_id": event.node_id,
        "zone": event.zone,
        "floor": event.floor,
        "role": event.role,
        "occupancy_behavior": event.occupancy_behavior,
        "signal_type": event.signal_type,
        "state": event.state,
        "event_at": event.event_at.isoformat(),
        "reliability": event.reliability,
    }
