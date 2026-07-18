from __future__ import annotations

from typing import Any


def runtime_status_payload(runtime: Any) -> dict[str, Any]:
    """Serialize live target state for diagnostics and WebSocket clients."""

    diagnostics = runtime.confidence.diagnostics
    payload = {
        "zone_states": {
            zone: zone_state_payload(state)
            for zone, state in runtime.zone_states.items()
        },
        "recent_occupancy_events": [
            occupancy_event_payload(event) for event in runtime.recent_occupancy_events
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
        "expected_occupants": runtime.expected_occupants,
        "authoritative_count": {
            "source": runtime.expected_occupants_entity
            or "configured_expected_occupants",
            "requested": runtime.confidence.requested_expected_occupants,
            "accepted": runtime.expected_occupants,
            "available": runtime.authoritative_count_available,
            "invalid": "invalid_authoritative_count"
            in getattr(runtime, "problem_reasons", ()),
            "unsupported": diagnostics.unsupported_count,
        },
        "occupancy_diagnostics": tracker_diagnostics_payload(diagnostics),
    }
    if getattr(runtime, "latency_metrics", None) is not None:
        payload["latency"] = runtime.latency_metrics
    return payload


def zone_state_payload(state: Any) -> dict[str, Any]:
    return {
        "confidence": state.confidence,
        "status": state.status,
        "occupancy_behavior": state.occupancy_behavior,
        "active_since": _iso(state.active_since),
        "last_evidence_at": _iso(state.last_evidence_at),
        "last_clear_at": _iso(state.last_clear_at),
        "last_node_id": state.last_node_id,
        "reason": state.reason,
        "explanation": dict(state.explanation),
    }


def tracker_diagnostics_payload(diagnostics: Any) -> dict[str, Any]:
    return {
        "model": "zone_belief",
        "expected_occupants": diagnostics.expected_occupants,
        "requested_occupants": diagnostics.requested_occupants,
        "unsupported_count": diagnostics.unsupported_count,
        "beliefs": dict(diagnostics.beliefs),
        "policy": {
            zone: {
                "active": state.active,
                "profile": state.profile_name,
                "last_evaluated_at": state.last_evaluated_at.isoformat(),
                "pending_release_since": _iso(state.pending_release_since),
            }
            for zone, state in diagnostics.policy_states.items()
        },
        "episodes": [
            {
                "node_id": state.node_id,
                "zone": state.zone,
                "profile": state.profile_name,
                "episode_id": state.episode_id,
                "status": state.status,
                "last_event_at": _iso(state.last_event_at),
                "health_warning": state.health_warning,
            }
            for state in diagnostics.episode_states
        ],
        "traversal_frontier": [
            {
                "token_id": token.token_id,
                "node_id": token.node_id,
                "zone": token.zone,
                "episode_id": token.episode_id,
                "accepted_at": token.accepted_at.isoformat(),
                "valid_until": token.valid_until.isoformat(),
            }
            for token in diagnostics.traversal_tokens
        ],
        "authorizations": [
            {
                "target_node_id": item.target_node_id,
                "target_zone": item.target_zone,
                "target_episode_id": item.target_episode_id,
                "authorized_at": item.authorized_at.isoformat(),
                "authorized": item.authorized,
                "reason": item.reason,
                "source_token_ids": [token.token_id for token in item.source_tokens],
            }
            for item in diagnostics.authorizations
        ],
        "recent_policy_events": [
            {
                "kind": item.kind,
                "event_at": item.event_at.isoformat(),
                "zone": item.zone,
                "episode_id": item.episode_id,
                "belief": item.belief,
                "authorization_reason": item.authorization_reason,
                "policy_reason": item.policy_reason,
            }
            for item in diagnostics.policy_events
        ],
        "policy_audit": [
            policy_decision_payload(row) for row in diagnostics.policy_audit
        ],
        "prediction": {
            "probabilities": dict(diagnostics.prediction_probabilities),
            "leases": [
                {
                    "source_node_id": lease.source_node_id,
                    "current_node_id": lease.current_node_id,
                    "target_node_id": lease.target_node_id,
                    "target_zone": lease.target_zone,
                    "probability": lease.probability,
                    "created_at": lease.created_at.isoformat(),
                    "expires_at": lease.expires_at.isoformat(),
                    "reason": lease.reason,
                }
                for lease in diagnostics.prediction_leases
            ],
        },
        "event_disposition": diagnostics.event_disposition,
        "restore": {
            "status": diagnostics.restore_status,
            "reason": diagnostics.restore_reason,
        },
        "processing": dict(diagnostics.processing),
        "health_warnings": [
            state.node_id
            for state in diagnostics.episode_states
            if state.health_warning
        ],
    }


def policy_decision_payload(row: Any) -> dict[str, Any]:
    return {
        "event_at": row.event_at.isoformat(),
        "processing_at": row.processing_at.isoformat(),
        "zone": row.zone,
        "node_id": row.node_id,
        "episode_id": row.episode_id,
        "profile": row.profile_name,
        "belief_before": row.belief_before,
        "belief_after": row.belief_after,
        "active_before": row.active_before,
        "active_after": row.active_after,
        "local_evidence_kind": row.local_evidence_kind,
        "local_trustworthy": row.local_trustworthy,
        "authorization_authorized": row.authorization_authorized,
        "traversal_reason": row.traversal_reason,
        "evidence_ids": list(row.evidence_ids),
        "count_zero": row.count_zero,
        "health_warning": row.health_warning,
        "on_threshold": row.on_threshold,
        "off_threshold": row.off_threshold,
        "release_dwell_seconds": row.release_dwell.total_seconds(),
        "pending_release_since": _iso(row.pending_release_since),
        "event_kind": row.event_kind,
        "reason": row.reason,
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


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()
