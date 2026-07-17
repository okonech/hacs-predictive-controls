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
    DISPATCH_DIAGNOSTIC_UPDATE,
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
        HomeActiveSensor(runtime, entry.entry_id),
        PredictiveControlsProblemSensor(runtime, entry.entry_id),
    ]
    entities.extend(
        ZoneActiveSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZonePrelightSensor(runtime, entry.entry_id, zone, threshold)
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
        self._published_is_on: bool | None = None

    @property
    def update_signal(self) -> str:
        return DISPATCH_UPDATE

    async def async_added_to_hass(self) -> None:
        self._published_is_on = bool(self.is_on)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.update_signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        is_on = bool(self.is_on)
        if is_on == self._published_is_on:
            return
        self._published_is_on = is_on
        self.async_write_ha_state()


class HomeActiveSensor(RuntimeBinarySensor):
    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_name = "Home Active"
        self._attr_unique_id = f"{entry_id}_home_active"

    @property
    def is_on(self) -> bool:
        return bool(runtime_automation_summary(self.runtime).keep_on_zones)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        zones = list(summary.keep_on_zones)
        return {
            "active_zones": zones,
            "explanation": (
                f"Active policy ownership in: {', '.join(zones)}"
                if zones
                else "No zone currently has active policy ownership"
            ),
        }


class PredictiveControlsProblemSensor(RuntimeBinarySensor):
    _attr_device_class = "problem"

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_name = "Predictive Controls Problem"
        self._attr_unique_id = f"{entry_id}_predictive_controls_problem"

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.runtime, "problem_reasons", ()))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        reasons = list(getattr(self.runtime, "problem_reasons", ()))
        return {
            "reasons": reasons,
            "affected_sources": list(
                getattr(self.runtime, "problem_sources", ())
            ),
            "explanation": (
                f"Active problems: {', '.join(reasons)}"
                if reasons
                else "No active Predictive Controls problem"
            ),
        }


class ZoneActiveSensor(RuntimeBinarySensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Active"
        self._attr_unique_id = f"{entry_id}_{zone}_active"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime).zones[self.zone].keep_on

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = runtime_automation_summary(self.runtime).zones[self.zone]
        return {
            "reason": self.runtime.confidence.diagnostics.joint_policy_states[
                self.zone
            ].reason,
            "occupancy_probability": state.confidence,
            "explanation": (
                self.runtime.confidence.diagnostics.joint_policy_states[
                    self.zone
                ].reason
            ),
        }


class ZonePrelightSensor(RuntimeBinarySensor):
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
        self._attr_name = f"{zone.replace('_', ' ').title()} Prelight"
        self._attr_unique_id = f"{entry_id}_{zone}_prelight"

    @property
    def is_on(self) -> bool:
        return runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ].prelight_plausible

    @property
    def extra_state_attributes(self) -> dict[str, float | str]:
        state = runtime_automation_summary(self.runtime, self.threshold).zones[
            self.zone
        ]
        return {
            "probability": state.prediction_probability,
            "threshold": self.threshold,
            "explanation": (
                f"Prediction probability {state.prediction_probability:.3f} "
                f"against threshold {self.threshold:.3f}"
            ),
        }


class ZoneDiagnosticEntryPathSensor(RuntimeBinarySensor):
    _attr_entity_registry_enabled_default = False
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

    @property
    def update_signal(self) -> str:
        return DISPATCH_DIAGNOSTIC_UPDATE

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "explanation": "Sampled diagnostic entry-path plausibility",
        }
