from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .automation_summary import runtime_automation_summary
from .const import DISPATCH_UPDATE, DOMAIN
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        PredictedNextZoneSensor(runtime, entry.entry_id),
        EntryPlausibleZonesSensor(runtime, entry.entry_id),
        OccupancyHoldZonesSensor(runtime, entry.entry_id),
    ]
    entities.extend(
        ZoneConfidenceSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
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


class PredictedNextZoneSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="predicted_next_zone",
        name="Predicted Next Zone",
        icon="mdi:map-marker-path",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_predicted_next_zone"

    @property
    def native_value(self) -> str | None:
        return runtime_automation_summary(self.runtime).predicted_next_zone

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "probability": summary.predicted_next_probability,
            "predicted_zones": list(summary.predicted_zones),
            "zone_probabilities": {
                zone: state.prediction_probability
                for zone, state in summary.zones.items()
                if state.prediction_probability > 0
            },
        }


class ZoneListSensor(RuntimeSensor):
    _attr_icon = "mdi:floor-plan"
    _attr_zone_attribute = "zones"

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_{self.entity_key}"
        self._attr_name = self.entity_name

    @property
    def native_value(self) -> int:
        return len(self.zones)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {self._attr_zone_attribute: list(self.zones)}

    @property
    def zones(self) -> tuple[str, ...]:
        raise NotImplementedError


class EntryPlausibleZonesSensor(ZoneListSensor):
    entity_key = "entry_plausible_zones"
    entity_name = "Entry Plausible Zones"
    _attr_icon = "mdi:map-marker-path"
    _attr_zone_attribute = "entry_plausible_zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).entry_plausible_zones


class OccupancyHoldZonesSensor(ZoneListSensor):
    entity_key = "occupancy_hold_zones"
    entity_name = "Occupancy Hold Zones"
    _attr_icon = "mdi:account-clock-outline"
    _attr_zone_attribute = "occupancy_hold_zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).occupancy_hold_zones


class ZoneConfidenceSensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Confidence"
        self._attr_unique_id = f"{entry_id}_{zone}_confidence"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float:
        state = self.runtime.zone_states.get(self.zone)
        confidence = state.confidence if state is not None else 0.0
        return round(confidence * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.runtime.zone_states.get(self.zone)
        if state is None:
            return {"status": "rejected", "reason": "no evidence"}
        return {
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
        }


