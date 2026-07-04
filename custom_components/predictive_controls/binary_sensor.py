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
    entities: list[BinarySensorEntity] = [HomeKeepOnSensor(runtime, entry.entry_id)]
    entities.extend(
        ZoneActivationPlausibleSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneKeepOnSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZonePrelightPlausibleSensor(runtime, entry.entry_id, zone, threshold)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneDiagnosticEntryPathSensor(runtime, entry.entry_id, zone)
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


class HomeKeepOnSensor(RuntimeBinarySensor):
    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_name = "Home Keep On"
        self._attr_unique_id = f"{entry_id}_home_keep_on"

    @property
    def is_on(self) -> bool:
        return bool(runtime_automation_summary(self.runtime).keep_on_zones)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "keep_on_zones": list(summary.keep_on_zones),
            "possible_inside_count": summary.possible_inside_count,
        }


class ZoneActivationPlausibleSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Activation Plausible"
        self._attr_unique_id = f"{entry_id}_{zone}_activation_plausible"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime).zones[
            self.zone
        ].activation_plausible

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        state = summary.zones[self.zone]
        return {
            "keep_on": state.keep_on,
            "diagnostic_entry_path_plausible": state.diagnostic_entry_path_plausible,
        }


class ZoneKeepOnSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Keep On"
        self._attr_unique_id = f"{entry_id}_{zone}_keep_on"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime).zones[
            self.zone
        ].keep_on

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = runtime_automation_summary(self.runtime).zones[self.zone]
        return {
            "confidence": state.confidence,
            "status": state.status,
            "possible_occupancy": state.possible_occupancy,
        }


class ZonePrelightPlausibleSensor(RuntimeBinarySensor):
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
        self._attr_name = f"{zone.replace('_', ' ').title()} Prelight Plausible"
        self._attr_unique_id = f"{entry_id}_{zone}_prelight_plausible"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ].prelight_plausible

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        state = runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ]
        return {
            "probability": state.prediction_probability,
            "threshold": self.threshold,
        }


class ZoneDiagnosticEntryPathSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = (
            f"{zone.replace('_', ' ').title()} Diagnostic Entry Path Plausible"
        )
        self._attr_unique_id = f"{entry_id}_{zone}_diagnostic_entry_path_plausible"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime).zones[
            self.zone
        ].diagnostic_entry_path_plausible
