from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_ACTIONS_YAML,
    CONF_MAP_YAML,
    CONF_PREDICTION_THRESHOLD,
    CONF_TRANSITION_WINDOW,
    DEFAULT_PREDICTION_THRESHOLD,
    DEFAULT_TRANSITION_WINDOW,
    DOMAIN,
)
from .yaml_config import (
    DEFAULT_ACTIONS_YAML,
    DEFAULT_MAP_YAML,
    load_predictive_actions,
    load_predictive_map,
)

_LOGGER = logging.getLogger(__name__)


def _yaml_selector(default: str) -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(multiline=True, type=selector.TextSelectorType.TEXT)
    )


def _options_schema(
    map_yaml: str = DEFAULT_MAP_YAML,
    actions_yaml: str = DEFAULT_ACTIONS_YAML,
    transition_window: int = DEFAULT_TRANSITION_WINDOW,
    prediction_threshold: float = DEFAULT_PREDICTION_THRESHOLD,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MAP_YAML, default=map_yaml): _yaml_selector(map_yaml),
            vol.Required(CONF_ACTIONS_YAML, default=actions_yaml): _yaml_selector(
                actions_yaml
            ),
            vol.Required(CONF_TRANSITION_WINDOW, default=transition_window): int,
            vol.Required(
                CONF_PREDICTION_THRESHOLD, default=prediction_threshold
            ): float,
        }
    )


def _validate_options(data: dict[str, Any]) -> None:
    load_predictive_map(data[CONF_MAP_YAML])
    load_predictive_actions(data[CONF_ACTIONS_YAML])
    if int(data[CONF_TRANSITION_WINDOW]) < 1:
        raise ValueError("Transition window must be positive")
    threshold = float(data[CONF_PREDICTION_THRESHOLD])
    if not 0 <= threshold <= 1:
        raise ValueError("Prediction threshold must be between 0 and 1")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_NAME, default="Predictive Controls"): str}
                ),
            )

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=user_input[CONF_NAME],
            data={},
            options={
                CONF_MAP_YAML: DEFAULT_MAP_YAML,
                CONF_ACTIONS_YAML: DEFAULT_ACTIONS_YAML,
                CONF_TRANSITION_WINDOW: DEFAULT_TRANSITION_WINDOW,
                CONF_PREDICTION_THRESHOLD: DEFAULT_PREDICTION_THRESHOLD,
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = self.config_entry.options
        if user_input is not None:
            errors: dict[str, str] = {}
            try:
                _validate_options(user_input)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Invalid Predictive Controls options")
                errors["base"] = "invalid_yaml"
            else:
                return self.async_create_entry(title="", data=user_input)

            return self.async_show_form(
                step_id="init",
                data_schema=_options_schema(
                    map_yaml=user_input[CONF_MAP_YAML],
                    actions_yaml=user_input[CONF_ACTIONS_YAML],
                    transition_window=int(user_input[CONF_TRANSITION_WINDOW]),
                    prediction_threshold=float(user_input[CONF_PREDICTION_THRESHOLD]),
                ),
                errors=errors,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                map_yaml=options.get(CONF_MAP_YAML, DEFAULT_MAP_YAML),
                actions_yaml=options.get(CONF_ACTIONS_YAML, DEFAULT_ACTIONS_YAML),
                transition_window=options.get(
                    CONF_TRANSITION_WINDOW, DEFAULT_TRANSITION_WINDOW
                ),
                prediction_threshold=options.get(
                    CONF_PREDICTION_THRESHOLD, DEFAULT_PREDICTION_THRESHOLD
                ),
            ),
        )
