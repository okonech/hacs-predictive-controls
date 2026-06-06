from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DISPATCH_UPDATE, DOMAIN
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [NextNodeSensor(runtime, entry.entry_id)]
    entities.extend(
        NodeProbabilitySensor(runtime, entry.entry_id, node_id)
        for node_id in runtime.map.nodes
    )
    async_add_entities(entities)


class RuntimeSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        self.runtime = runtime
        self.entry_id = entry_id

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class NextNodeSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="next_node",
        name="Predicted Next Node",
        icon="mdi:graph-outline",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_next_node"

    @property
    def native_value(self) -> str | None:
        prediction = self.runtime.last_prediction
        return prediction.node_id if prediction is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        prediction = self.runtime.last_prediction
        return {
            "probabilities": self.runtime.probabilities,
            "probability": prediction.probability if prediction is not None else None,
            "last_source_node": self.runtime.last_source_node,
        }


class NodeProbabilitySensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, node_id: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.node_id = node_id
        label = runtime.map.nodes[node_id].label
        self._attr_name = f"{label} Prediction Probability"
        self._attr_unique_id = f"{entry_id}_{node_id}_probability"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float:
        return round(self.runtime.probabilities.get(self.node_id, 0.0) * 100, 1)
