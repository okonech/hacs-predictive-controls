from __future__ import annotations

from typing import Any


def runtime_status_payload(runtime: Any) -> dict[str, Any]:
    """Serialize live runtime status for diagnostics and WebSocket clients."""

    return {
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
    return {
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
