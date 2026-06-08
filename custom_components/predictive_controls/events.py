from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import PredictiveMap


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


def event_from_entity(
    predictive_map: PredictiveMap,
    entity_id: str,
    state: str,
    event_at: datetime,
) -> OccupancyEvent | None:
    """Normalize one mapped entity state change."""

    if state not in {"on", "off"}:
        return None

    binding = predictive_map.entity_binding_for_entity(entity_id)
    if binding is None:
        return None

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
        reliability=node.initial_weight,
    )
