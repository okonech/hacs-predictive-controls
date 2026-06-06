from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACTIONS_YAML,
    CONF_MAP_YAML,
    CONF_TRANSITION_WINDOW,
    DEFAULT_TRANSITION_WINDOW,
    DOMAIN,
    PANEL_REGISTERED,
    WEBSOCKET_REGISTERED,
)
from .yaml_config import (
    DEFAULT_ACTIONS_YAML,
    DEFAULT_MAP_YAML,
    load_predictive_actions,
    load_predictive_map,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_NAMES = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform

    from .panel import async_register_panel
    from .runtime import PredictiveControlsRuntime
    from .websocket import async_register_websocket_commands

    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get(PANEL_REGISTERED):
        await async_register_panel(hass)
        domain_data[PANEL_REGISTERED] = True
    if not domain_data.get(WEBSOCKET_REGISTERED):
        async_register_websocket_commands(hass)
        domain_data[WEBSOCKET_REGISTERED] = True

    options = dict(entry.options)
    predictive_map = load_predictive_map(options.get(CONF_MAP_YAML, DEFAULT_MAP_YAML))
    actions = load_predictive_actions(
        options.get(CONF_ACTIONS_YAML, DEFAULT_ACTIONS_YAML)
    )
    transition_window = int(
        options.get(CONF_TRANSITION_WINDOW, DEFAULT_TRANSITION_WINDOW)
    )

    runtime = PredictiveControlsRuntime(
        hass, predictive_map, actions, transition_window
    )
    runtime.start()

    domain_data[entry.entry_id] = runtime
    platforms = [Platform(platform_name) for platform_name in PLATFORM_NAMES]
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform

    platforms = [Platform(platform_name) for platform_name in PLATFORM_NAMES]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        runtime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.async_stop()
    return bool(unload_ok)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.debug("Reloading Predictive Controls config entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
