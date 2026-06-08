from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PREDICTION_THRESHOLD,
    DEFAULT_PREDICTION_THRESHOLD,
    DISPATCH_UPDATE,
    DOMAIN,
)
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    threshold = float(
        entry.options.get(CONF_PREDICTION_THRESHOLD, DEFAULT_PREDICTION_THRESHOLD)
    )
    entities: list[BinarySensorEntity] = [
        NodePredictedSensor(runtime, entry.entry_id, node_id, threshold)
        for node_id in runtime.map.nodes
    ]
    entities.extend(
        ZoneProbableSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    async_add_entities(entities)


class NodePredictedSensor(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        node_id: str,
        threshold: float,
    ) -> None:
        self.runtime = runtime
        self.node_id = node_id
        self.threshold = threshold
        label = runtime.map.nodes[node_id].label
        self._attr_name = f"{label} Predicted"
        self._attr_unique_id = f"{entry_id}_{node_id}_predicted"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.runtime.probabilities.get(self.node_id, 0.0) >= self.threshold

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        return {
            "probability": self.runtime.probabilities.get(self.node_id, 0.0),
            "threshold": self.threshold,
        }


class ZoneProbableSensor(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        self.runtime = runtime
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Probable Occupancy"
        self._attr_unique_id = f"{entry_id}_{zone}_probable_occupancy"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        state = self.runtime.zone_states.get(self.zone)
        return state is not None and state.status in {"probable", "confirmed"}

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.runtime.zone_states.get(self.zone)
        if state is None:
            return {"confidence": 0.0, "status": "rejected"}
        return {
            "confidence": state.confidence,
            "status": state.status,
            "occupancy_behavior": state.occupancy_behavior,
            "active_since": state.active_since.isoformat()
            if state.active_since is not None
            else None,
            "reason": state.reason,
        }
