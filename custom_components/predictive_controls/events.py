from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .model import PredictiveMap, is_interaction_signal_type


@dataclass(frozen=True)
class OccupancyEvent:
    """Normalized Home Assistant event for occupancy confidence."""

    entity_id: str
    node_id: str
    zone: str
    floor: str | None
    role: str
    occupancy_behavior: str
    signal_type: str
    state: str
    event_at: datetime
    reliability: float


def _interaction_event_at(state: str, callback_at: datetime) -> datetime | None:
    normalized = f"{state[:-1]}+00:00" if state.endswith(("Z", "z")) else state
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        callback_utc = callback_at.astimezone(UTC)
        parsed_utc = parsed.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        return None
    return None if parsed_utc > callback_utc else parsed_utc


def event_from_entity(
    predictive_map: PredictiveMap,
    entity_id: str,
    state: str,
    event_at: datetime,
    *,
    allow_unsupported_state: bool = False,
) -> OccupancyEvent | None:
    """Normalize one mapped entity state change."""

    binding = predictive_map.entity_binding_for_entity(entity_id)
    if binding is None:
        return None

    supported_states = {"on", "off", "unknown", "unavailable"}
    if is_interaction_signal_type(binding.signal_type):
        if state not in {"unknown", "unavailable"}:
            if allow_unsupported_state:
                state = "unknown"
            else:
                interaction_at = _interaction_event_at(state, event_at)
                if interaction_at is None:
                    return None
                state = "pressed"
                event_at = interaction_at
    elif state not in supported_states:
        if not allow_unsupported_state:
            return None
        state = "unknown"

    node = predictive_map.nodes[binding.node_id]
    return OccupancyEvent(
        entity_id=entity_id,
        node_id=node.node_id,
        zone=node.occupancy_zone,
        floor=node.floor,
        role=node.role,
        occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
        signal_type=binding.signal_type,
        state=state,
        event_at=event_at,
        reliability=node.reliability,
    )
