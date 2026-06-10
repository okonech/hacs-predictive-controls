from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_ACTIONS_YAML,
    CONF_EXPECTED_OCCUPANTS,
    CONF_MAP_YAML,
    CONF_PREDICTION_THRESHOLD,
    CONF_TRANSITION_WINDOW,
    DEFAULT_EXPECTED_OCCUPANTS,
    DEFAULT_PREDICTION_THRESHOLD,
    DEFAULT_TRANSITION_WINDOW,
    DOMAIN,
)
from .entity_catalog import serialize_candidates
from .status import runtime_status_payload
from .yaml_config import (
    DEFAULT_ACTIONS_YAML,
    DEFAULT_MAP_YAML,
    load_predictive_actions,
    load_predictive_map,
    load_yaml_document,
    map_yaml_from_payload,
)


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_config)
    websocket_api.async_register_command(hass, websocket_save_config)
    websocket_api.async_register_command(hass, websocket_entities)
    websocket_api.async_register_command(hass, websocket_status)


def _entry_for_message(hass: HomeAssistant, msg: dict[str, Any]) -> Any:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("No Predictive Controls config entry exists")

    entry_id = msg.get("entry_id")
    if entry_id is None:
        return entries[0]

    for entry in entries:
        if entry.entry_id == entry_id:
            return entry
    raise ValueError(f"Predictive Controls config entry {entry_id!r} was not found")


def _entry_payload(entry: Any) -> dict[str, Any]:
    options = entry.options
    map_yaml = options.get(CONF_MAP_YAML, DEFAULT_MAP_YAML)
    actions_yaml = options.get(CONF_ACTIONS_YAML, DEFAULT_ACTIONS_YAML)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "map": load_yaml_document(map_yaml),
        "map_yaml": map_yaml,
        "actions_yaml": actions_yaml,
        "transition_window_seconds": options.get(
            CONF_TRANSITION_WINDOW, DEFAULT_TRANSITION_WINDOW
        ),
        "prediction_threshold": options.get(
            CONF_PREDICTION_THRESHOLD, DEFAULT_PREDICTION_THRESHOLD
        ),
        "expected_occupants": options.get(
            CONF_EXPECTED_OCCUPANTS, DEFAULT_EXPECTED_OCCUPANTS
        ),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/config"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        entry = _entry_for_message(hass, msg)
    except ValueError as exc:
        connection.send_error(msg["id"], "not_found", str(exc))
        return

    connection.send_message(
        websocket_api.result_message(msg["id"], _entry_payload(entry))
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_config",
        vol.Required("entry_id"): str,
        vol.Optional("map"): dict,
        vol.Optional("map_yaml"): str,
        vol.Required("actions_yaml"): str,
        vol.Required("transition_window_seconds"): int,
        vol.Required("prediction_threshold"): float,
        vol.Optional("expected_occupants", default=DEFAULT_EXPECTED_OCCUPANTS): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_save_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        entry = _entry_for_message(hass, msg)
        map_yaml = map_yaml_from_payload(msg)
        load_predictive_map(map_yaml)
        load_predictive_actions(msg["actions_yaml"])
        threshold = float(msg["prediction_threshold"])
        if not 0 <= threshold <= 1:
            raise ValueError("prediction_threshold must be between 0 and 1")
        transition_window = int(msg["transition_window_seconds"])
        if transition_window < 1:
            raise ValueError("transition_window_seconds must be positive")
        expected_occupants = int(msg["expected_occupants"])
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be zero or positive")
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_config", str(exc))
        return

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_MAP_YAML: map_yaml,
            CONF_ACTIONS_YAML: msg["actions_yaml"],
            CONF_TRANSITION_WINDOW: transition_window,
            CONF_PREDICTION_THRESHOLD: threshold,
            CONF_EXPECTED_OCCUPANTS: expected_occupants,
        },
    )
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_message(
        websocket_api.result_message(msg["id"], _entry_payload(entry))
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/entities"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    states = list(hass.states.async_all())
    connection.send_message(
        websocket_api.result_message(
            msg["id"], {"entities": serialize_candidates(states)}
        )
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/status",
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        entry = _entry_for_message(hass, msg)
        runtime = hass.data[DOMAIN][entry.entry_id]
    except (KeyError, ValueError) as exc:
        connection.send_error(msg["id"], "not_found", str(exc))
        return

    connection.send_message(
        websocket_api.result_message(msg["id"], runtime_status_payload(runtime))
    )
