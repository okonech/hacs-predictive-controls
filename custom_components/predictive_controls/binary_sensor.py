from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .automation_summary import runtime_automation_summary
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
        HomeOccupancyHoldSensor(runtime, entry.entry_id)
    ]
    entities.extend(
        ZoneEntryPlausibleSensor(runtime, entry.entry_id, zone, threshold)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneOccupancyHoldSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZonePredictedSensor(runtime, entry.entry_id, zone, threshold)
        for zone in runtime.map.zones()
    )
    async_add_entities(entities)


class RuntimeBinarySensor(BinarySensorEntity):
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


class HomeOccupancyHoldSensor(RuntimeBinarySensor):
    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_name = "Home Occupancy Hold"
        self._attr_unique_id = f"{entry_id}_home_occupancy_hold"

    @property
    def is_on(self) -> bool:
        return bool(runtime_automation_summary(self.runtime).occupancy_hold_zones)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "occupancy_hold_zones": list(summary.occupancy_hold_zones),
            "possible_inside_count": summary.possible_inside_count,
        }


class ZoneEntryPlausibleSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
        threshold: float,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self.threshold = threshold
        self._attr_name = f"{zone.replace('_', ' ').title()} Entry Plausible"
        self._attr_unique_id = f"{entry_id}_{zone}_entry_plausible"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ].entry_plausible

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime, self.threshold)
        state = summary.zones[self.zone]
        return {
            "prediction_probability": state.prediction_probability,
            "prediction_threshold": self.threshold,
            "predicted_next": state.predicted_next,
        }


class ZoneOccupancyHoldSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Occupancy Hold"
        self._attr_unique_id = f"{entry_id}_{zone}_occupancy_hold"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime).zones[
            self.zone
        ].occupancy_hold

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = runtime_automation_summary(self.runtime).zones[self.zone]
        return {
            "confidence": state.confidence,
            "status": state.status,
            "possible_occupancy": state.possible_occupancy,
        }


class ZonePredictedSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
        threshold: float,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self.threshold = threshold
        self._attr_name = f"{zone.replace('_', ' ').title()} Predicted Next"
        self._attr_unique_id = f"{entry_id}_{zone}_zone_predicted_next"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ].predicted_next

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        state = runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ]
        return {
            "probability": state.prediction_probability,
            "threshold": self.threshold,
        }
