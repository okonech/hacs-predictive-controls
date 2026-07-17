from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .automation_summary import runtime_automation_summary
from .const import DISPATCH_DIAGNOSTIC_UPDATE, DISPATCH_UPDATE, DOMAIN
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        AuthoritativeOccupantCountSensor(runtime, entry.entry_id),
        DiagnosticPredictedNextZoneSensor(runtime, entry.entry_id),
        DiagnosticEntryPathPlausibleZonesSensor(runtime, entry.entry_id),
    ]
    entities.extend(
        ZoneDiagnosticConfidenceSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneOccupancyProbabilitySensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneArrivalSupportedProbabilitySensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneReleaseSafeProbabilitySensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    async_add_entities(entities)


class RuntimeSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        self.runtime = runtime
        self.entry_id = entry_id

    @property
    def update_signal(self) -> str:
        return DISPATCH_DIAGNOSTIC_UPDATE

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.update_signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class AuthoritativeOccupantCountSensor(RuntimeSensor):
    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_name = "Authoritative Occupant Count"
        self._attr_unique_id = f"{entry_id}_authoritative_occupant_count"
        self._published_value: tuple[bool, int | None] | None = None

    @property
    def update_signal(self) -> str:
        return DISPATCH_UPDATE

    async def async_added_to_hass(self) -> None:
        self._published_value = (self.available, self.native_value)
        await super().async_added_to_hass()

    @callback
    def _handle_update(self) -> None:
        value = (self.available, self.native_value)
        if value == self._published_value:
            return
        self._published_value = value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.runtime.authoritative_count_available

    @property
    def native_value(self) -> int | None:
        return self.runtime.expected_occupants if self.available else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "source": self.runtime.expected_occupants_entity
            or "configured_expected_occupants",
            "requested_count": (
                self.runtime.confidence.requested_expected_occupants
            ),
        }


class DiagnosticPredictedNextZoneSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="diagnostic_predicted_next_zone",
        name="Diagnostic Predicted Next Zone",
        icon="mdi:map-marker-path",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_diagnostic_predicted_next_zone"

    @property
    def native_value(self) -> str | None:
        return runtime_automation_summary(self.runtime).diagnostic_predicted_next_zone

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "probability": summary.diagnostic_predicted_next_probability,
            "prelight_plausible_zones": list(summary.prelight_plausible_zones),
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


class DiagnosticEntryPathPlausibleZonesSensor(ZoneListSensor):
    entity_key = "diagnostic_entry_path_plausible_zones"
    entity_name = "Diagnostic Entry Path Plausible Zones"
    _attr_icon = "mdi:map-marker-path"
    _attr_zone_attribute = "diagnostic_entry_path_plausible_zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return (
            runtime_automation_summary(self.runtime)
            .diagnostic_entry_path_plausible_zones
        )


class ZoneDiagnosticConfidenceSensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Diagnostic Confidence"
        self._attr_unique_id = f"{entry_id}_{zone}_diagnostic_confidence"
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


class ZoneProbabilitySensor(RuntimeSensor):
    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
        key: str,
        name: str,
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} {name}"
        self._attr_unique_id = f"{entry_id}_{zone}_{key}"
        self._attr_native_unit_of_measurement = "%"


class ZoneOccupancyProbabilitySensor(ZoneProbabilitySensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(
            runtime,
            entry_id,
            zone,
            "occupancy_probability",
            "Occupancy Probability",
        )

    @property
    def native_value(self) -> float:
        probability = self.runtime.confidence.diagnostics.joint_occupied_marginals.get(
            self.zone,
            0.0,
        )
        return round(probability * 100, 1)


class ZoneArrivalSupportedProbabilitySensor(ZoneProbabilitySensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(
            runtime,
            entry_id,
            zone,
            "arrival_supported_probability",
            "Arrival Supported Probability",
        )

    @property
    def available(self) -> bool:
        return (
            self.zone
            in self.runtime.confidence.diagnostics.joint_arrival_supported_probabilities
        )

    @property
    def native_value(self) -> float | None:
        probability = self.runtime.confidence.diagnostics
        if not self.available:
            return None
        return round(
            probability.joint_arrival_supported_probabilities[self.zone] * 100,
            1,
        )


class ZoneReleaseSafeProbabilitySensor(ZoneProbabilitySensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(
            runtime,
            entry_id,
            zone,
            "release_safe_probability",
            "Release Safe Probability",
        )

    @property
    def available(self) -> bool:
        diagnostics = self.runtime.confidence.diagnostics
        policy_state = diagnostics.joint_policy_states.get(self.zone)
        return bool(
            diagnostics.joint_release_safe_available
            and policy_state is not None
            and policy_state.keep_on
            and self.zone in diagnostics.joint_release_safe_probabilities
        )

    @property
    def native_value(self) -> float | None:
        diagnostics = self.runtime.confidence.diagnostics
        if not self.available:
            return None
        return round(
            diagnostics.joint_release_safe_probabilities[self.zone] * 100,
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "finalization_available": (
                self.runtime.confidence.diagnostics.joint_release_safe_available
            )
        }


