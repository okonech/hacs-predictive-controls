from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .automation_summary import runtime_automation_summary
from .const import (
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
    entities: list[BinarySensorEntity] = [
        HomeActiveSensor(runtime, entry.entry_id),
        PredictiveControlsProblemSensor(runtime, entry.entry_id),
    ]
    entities.extend(
        ZoneActiveSensor(runtime, entry.entry_id, zone) for zone in runtime.map.zones()
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
        self._published_signature: object | None = None

    @property
    def update_signal(self) -> str:
        return DISPATCH_UPDATE

    async def async_added_to_hass(self) -> None:
        self._published_signature = self._state_signature()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.update_signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        signature = self._state_signature()
        if signature == self._published_signature:
            return
        self._published_signature = signature
        self.async_write_ha_state()

    def _state_signature(self) -> object:
        return bool(self.is_on), _freeze(self.extra_state_attributes)


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
            "affected_sources": list(getattr(self.runtime, "problem_sources", ())),
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
        reason = self.runtime.zone_states[self.zone].reason
        policy = self.runtime.confidence.policy_states.get(self.zone)
        decisions = tuple(
            row
            for row in self.runtime.confidence.policy_decisions
            if row.zone == self.zone
        )
        authorizations = tuple(
            item
            for item in self.runtime.confidence.authorizations
            if item.target_zone == self.zone
        )
        latest_decision = decisions[-1] if decisions else None
        latest_authorization = authorizations[-1] if authorizations else None
        return {
            "reason": reason,
            "occupancy_probability": state.confidence,
            "phase": None if policy is None else policy.phase,
            "activation_provenance": (
                None if policy is None else policy.activation_provenance
            ),
            "prediction_expires_at": (
                None
                if policy is None or policy.prediction_expires_at is None
                else policy.prediction_expires_at.isoformat()
            ),
            "prediction_probability": (
                None if policy is None else policy.prediction_probability
            ),
            "prediction_support": (
                None if policy is None else policy.prediction_support
            ),
            "track_confidence": (
                None
                if latest_authorization is None
                else latest_authorization.track_confidence
            ),
            "evidence_ids": (
                [] if latest_decision is None else list(latest_decision.evidence_ids)
            ),
            "explanation": reason,
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
        return (
            runtime_automation_summary(self.runtime)
            .zones[self.zone]
            .diagnostic_entry_path_plausible
        )

    @property
    def update_signal(self) -> str:
        return DISPATCH_DIAGNOSTIC_UPDATE

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "explanation": "Sampled diagnostic entry-path plausibility",
        }


def _freeze(value: object) -> object:
    """Return a deterministic comparison key for current entity attributes."""

    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value
