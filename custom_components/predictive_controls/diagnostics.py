from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .runtime import PredictiveControlsRuntime
from .status import runtime_status_payload


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    status = runtime_status_payload(runtime)
    return {
        "nodes": {
            node_id: {
                "label": node.label,
                "entities": node.entities,
                "adjacent": node.adjacent,
                "floor": node.floor,
                "zone": node.occupancy_zone,
                "role": node.role,
                "review_required": node.review_required,
            }
            for node_id, node in runtime.map.nodes.items()
        },
        "entity_ids": runtime.map.entity_ids(),
        "zone_states": status["zone_states"],
        "recent_occupancy_events": status["recent_occupancy_events"],
        "last_source_node": runtime.last_source_node,
        "last_prediction": None
        if runtime.last_prediction is None
        else {
            "node_id": runtime.last_prediction.node_id,
            "probability": runtime.last_prediction.probability,
        },
        "probabilities": runtime.probabilities,
        "transition_counts": runtime.chain.counts,
        "actions": [action.action_id for action in runtime.actions],
    }
