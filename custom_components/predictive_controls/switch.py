from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([VisitorsModeSwitch(runtime, entry.entry_id)])


class VisitorsModeSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_name = "Visitors"
    _attr_icon = "mdi:account-group"

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{entry_id}_visitors_mode"
        self._published_signature: object = None

    @property
    def is_on(self) -> bool:
        return self.runtime.visitors.enabled

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self.runtime.visitors.store_data()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.async_set_visitors_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.async_set_visitors_mode(False)

    async def async_added_to_hass(self) -> None:
        self._published_signature = (self.is_on, self.extra_state_attributes)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        signature = (self.is_on, self.extra_state_attributes)
        if signature != self._published_signature:
            self.async_write_ha_state()
            self._published_signature = signature
