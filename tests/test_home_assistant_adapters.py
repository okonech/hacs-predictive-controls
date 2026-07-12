from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.const import (
    CONF_ACTIONS_YAML,
    CONF_EXPECTED_OCCUPANTS,
    CONF_EXPECTED_OCCUPANTS_ENTITY,
    CONF_MAP_YAML,
    CONF_PREDICTION_THRESHOLD,
    CONF_TRANSITION_WINDOW,
    DOMAIN,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import (
    DEFAULT_ACTIONS_YAML,
    DEFAULT_MAP_YAML,
)


def install_homeassistant(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    registered_commands: list[object] = []
    registered_panels: list[dict[str, object]] = []
    removed_panels: list[str] = []

    class FakeEntity:
        hass: object

        @property
        def unique_id(self) -> str | None:
            return getattr(self, "_attr_unique_id", None)

        def async_on_remove(self, callback: object) -> None:
            self.remove_callback = callback

        def async_write_ha_state(self) -> None:
            self.writes = getattr(self, "writes", 0) + 1

    class FakeDescription:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class FlowBase:
        domain: object = None

        def __init_subclass__(cls, **kwargs: object) -> None:
            cls.domain = kwargs.pop("domain", None)
            super().__init_subclass__()

        def async_show_form(self, **kwargs: object) -> dict[str, object]:
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs: object) -> dict[str, object]:
            return {"type": "create_entry", **kwargs}

        async def async_set_unique_id(self, unique_id: str) -> None:
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            self.checked_unique_id = True

    class ConfigFlow(FlowBase):
        pass

    class OptionsFlow(FlowBase):
        pass

    class TextSelectorType:
        TEXT = "text"

    class TextSelectorConfig:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class TextSelector:
        def __init__(self, config: object) -> None:
            self.config = config

    class Schema:
        def __init__(self, schema: object) -> None:
            self.schema = schema

        def __call__(self, value: object) -> object:
            return value

    def identity_decorator(
        _schema: object = None,
    ) -> Callable[[object], object]:
        def decorate(function: object) -> object:
            return function

        return decorate

    def identity_function(function: object) -> object:
        return function

    def set_attr(module: ModuleType, name: str, value: object) -> None:
        module.__dict__[name] = value

    modules = {
        name: ModuleType(name)
        for name in (
            "voluptuous",
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.binary_sensor",
            "homeassistant.components.frontend",
            "homeassistant.components.http",
            "homeassistant.components.sensor",
            "homeassistant.components.websocket_api",
            "homeassistant.config_entries",
            "homeassistant.const",
            "homeassistant.core",
            "homeassistant.helpers",
            "homeassistant.helpers.dispatcher",
            "homeassistant.helpers.entity_platform",
            "homeassistant.helpers.event",
            "homeassistant.helpers.selector",
            "homeassistant.helpers.storage",
        )
    }
    set_attr(modules["voluptuous"], "Schema", Schema)
    set_attr(modules["voluptuous"], "Required", lambda key, **_kwargs: key)
    set_attr(modules["voluptuous"], "Optional", lambda key, **_kwargs: key)
    set_attr(
        modules["homeassistant.components.binary_sensor"],
        "BinarySensorEntity",
        FakeEntity,
    )
    set_attr(modules["homeassistant.components.sensor"], "SensorEntity", FakeEntity)
    set_attr(
        modules["homeassistant.components.sensor"],
        "SensorEntityDescription",
        FakeDescription,
    )
    set_attr(modules["homeassistant.config_entries"], "ConfigEntry", object)
    set_attr(modules["homeassistant.config_entries"], "ConfigFlow", ConfigFlow)
    set_attr(modules["homeassistant.config_entries"], "OptionsFlow", OptionsFlow)
    set_attr(modules["homeassistant.config_entries"], "ConfigFlowResult", dict)
    set_attr(modules["homeassistant.const"], "CONF_NAME", "name")
    set_attr(modules["homeassistant.const"], "Platform", lambda value: value)
    set_attr(modules["homeassistant.core"], "Event", object)
    set_attr(modules["homeassistant.core"], "HomeAssistant", object)
    set_attr(modules["homeassistant.core"], "callback", identity_function)
    set_attr(modules["homeassistant.helpers.selector"], "TextSelector", TextSelector)
    set_attr(
        modules["homeassistant.helpers.selector"],
        "TextSelectorConfig",
        TextSelectorConfig,
    )
    set_attr(
        modules["homeassistant.helpers.selector"], "TextSelectorType", TextSelectorType
    )
    set_attr(
        modules["homeassistant.helpers.dispatcher"],
        "async_dispatcher_connect",
        lambda *_: lambda: None,
    )
    set_attr(
        modules["homeassistant.helpers.dispatcher"],
        "async_dispatcher_send",
        lambda *_: None,
    )
    set_attr(
        modules["homeassistant.helpers.entity_platform"], "AddEntitiesCallback", object
    )
    set_attr(
        modules["homeassistant.helpers.event"],
        "async_track_state_change_event",
        lambda *_: lambda: None,
    )
    set_attr(
        modules["homeassistant.helpers.event"],
        "async_track_time_interval",
        lambda *_: lambda: None,
    )

    websocket_api = modules["homeassistant.components.websocket_api"]
    set_attr(websocket_api, "ActiveConnection", object)
    set_attr(websocket_api, "websocket_command", identity_decorator)
    set_attr(websocket_api, "require_admin", identity_function)
    set_attr(websocket_api, "async_response", identity_function)
    set_attr(
        websocket_api,
        "async_register_command",
        lambda _hass, command: registered_commands.append(command),
    )
    set_attr(
        websocket_api,
        "result_message",
        lambda message_id, result: {"id": message_id, "result": result},
    )

    @dataclass
    class StaticPathConfig:
        url_path: str
        path: str
        cache_headers: bool

    set_attr(
        modules["homeassistant.components.http"], "StaticPathConfig", StaticPathConfig
    )
    set_attr(
        modules["homeassistant.components.frontend"],
        "async_register_built_in_panel",
        lambda _hass, **kwargs: registered_panels.append(kwargs),
    )
    set_attr(
        modules["homeassistant.components.frontend"],
        "async_remove_panel",
        lambda _hass, domain: removed_panels.append(domain),
    )

    for parent, children in {
        "homeassistant": ("components", "config_entries", "const", "core", "helpers"),
        "homeassistant.components": (
            "binary_sensor",
            "frontend",
            "http",
            "sensor",
            "websocket_api",
        ),
        "homeassistant.helpers": (
            "dispatcher",
            "entity_platform",
            "event",
            "selector",
            "storage",
        ),
    }.items():
        for child in children:
            set_attr(modules[parent], child, modules[f"{parent}.{child}"])
    for module in modules.values():
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return SimpleNamespace(
        modules=modules,
        registered_commands=registered_commands,
        registered_panels=registered_panels,
        removed_panels=removed_panels,
    )


def import_fresh(name: str) -> ModuleType:
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def valid_options() -> dict[str, object]:
    return {
        CONF_MAP_YAML: DEFAULT_MAP_YAML,
        CONF_ACTIONS_YAML: DEFAULT_ACTIONS_YAML,
        CONF_TRANSITION_WINDOW: 30,
        CONF_PREDICTION_THRESHOLD: 0.6,
        CONF_EXPECTED_OCCUPANTS: 1,
        CONF_EXPECTED_OCCUPANTS_ENTITY: "sensor.people_home",
    }


def test_config_flow_forms_validation_and_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_homeassistant(monkeypatch)
    module = import_fresh("custom_components.predictive_controls.config_flow")
    assert module._yaml_selector("unused").config.multiline  # noqa: SLF001
    assert module._options_schema()(valid_options()) == valid_options()  # noqa: SLF001
    module._validate_options(valid_options())  # noqa: SLF001

    invalid_cases = (
        (CONF_TRANSITION_WINDOW, 0, "positive"),
        (CONF_PREDICTION_THRESHOLD, 1.1, "between"),
        (CONF_EXPECTED_OCCUPANTS, -1, "between zero and two"),
        (CONF_EXPECTED_OCCUPANTS, 3, "between zero and two"),
        (CONF_EXPECTED_OCCUPANTS_ENTITY, "people", "entity id"),
    )
    for key, value, message in invalid_cases:
        data = {**valid_options(), key: value}
        with pytest.raises(ValueError, match=message):
            module._validate_options(data)  # noqa: SLF001

    flow = module.ConfigFlow()
    assert asyncio.run(flow.async_step_user())["type"] == "form"
    created = asyncio.run(flow.async_step_user({"name": "House"}))
    assert created["title"] == "House"
    assert flow.unique_id == DOMAIN
    options_flow = flow.async_get_options_flow(SimpleNamespace(options={}))
    assert asyncio.run(options_flow.async_step_init())["type"] == "form"
    assert (
        asyncio.run(options_flow.async_step_init(valid_options()))["type"]
        == "create_entry"
    )
    invalid = {**valid_options(), CONF_MAP_YAML: "nodes: ["}
    failed = asyncio.run(options_flow.async_step_init(invalid))
    assert failed["errors"] == {"base": "invalid_yaml"}


@dataclass
class FakeEntry:
    entry_id: str
    title: str = "Predictive"
    options: dict[str, object] = field(default_factory=valid_options)


class FakeConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.errors: list[tuple[object, str, str]] = []

    def send_message(self, message: object) -> None:
        self.messages.append(cast(dict[str, Any], message))

    def send_error(self, message_id: object, code: str, message: str) -> None:
        self.errors.append((message_id, code, message))


class FakeConfigEntries:
    def __init__(self, entries: list[FakeEntry]) -> None:
        self.entries = entries
        self.reloaded: list[str] = []

    def async_entries(self, _domain: str) -> list[FakeEntry]:
        return self.entries

    def async_update_entry(
        self, entry: FakeEntry, *, options: dict[str, object]
    ) -> None:
        entry.options = options

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


def test_websocket_commands_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_homeassistant(monkeypatch)
    module = import_fresh("custom_components.predictive_controls.websocket")
    entry = FakeEntry("entry1")
    config_entries = FakeConfigEntries([entry])
    runtime = SimpleNamespace(
        map=PredictiveMap.from_mapping({"nodes": {"room": {"adjacent": []}}})
    )
    hass = SimpleNamespace(
        config_entries=config_entries,
        data={DOMAIN: {"entry1": runtime}},
        states=SimpleNamespace(async_all=lambda: []),
    )
    connection = FakeConnection()

    module.async_register_websocket_commands(hass)
    assert len(fake.registered_commands) == 5
    assert module._entry_for_message(hass, {}) is entry  # noqa: SLF001
    assert module._entry_for_message(hass, {"entry_id": "entry1"}) is entry  # noqa: SLF001
    with pytest.raises(ValueError, match="not found"):
        module._entry_for_message(hass, {"entry_id": "missing"})  # noqa: SLF001
    with pytest.raises(ValueError, match="No Predictive"):
        module._entry_for_message(
            SimpleNamespace(config_entries=FakeConfigEntries([])), {}
        )  # noqa: SLF001

    asyncio.run(module.websocket_config(hass, connection, {"id": 1}))
    assert connection.messages[-1]["result"]["entry_id"] == "entry1"
    no_entry_hass = SimpleNamespace(config_entries=FakeConfigEntries([]))
    asyncio.run(module.websocket_config(no_entry_hass, connection, {"id": 2}))
    assert connection.errors[-1][1] == "not_found"

    save_message = {
        "id": 3,
        "entry_id": "entry1",
        "map_yaml": DEFAULT_MAP_YAML,
        "actions_yaml": DEFAULT_ACTIONS_YAML,
        "transition_window_seconds": 10,
        "prediction_threshold": 0.7,
        "expected_occupants": 2,
        "expected_occupants_entity": "sensor.people",
    }
    asyncio.run(module.websocket_save_config(hass, connection, save_message))
    assert config_entries.reloaded == ["entry1"]
    for key, value in (
        ("prediction_threshold", 2.0),
        ("transition_window_seconds", 0),
        ("expected_occupants", -1),
        ("expected_occupants", 3),
        ("expected_occupants_entity", "people"),
    ):
        invalid = {**save_message, "id": f"bad-{key}", key: value}
        asyncio.run(module.websocket_save_config(hass, connection, invalid))
        assert connection.errors[-1][1] == "invalid_config"

    asyncio.run(module.websocket_entities(hass, connection, {"id": 4}))
    assert connection.messages[-1]["result"] == {"entities": []}
    monkeypatch.setattr(module, "runtime_status_payload", lambda _runtime: {"ok": True})
    asyncio.run(module.websocket_status(hass, connection, {"id": 5}))
    assert connection.messages[-1]["result"] == {"ok": True}
    asyncio.run(module.websocket_status(no_entry_hass, connection, {"id": 6}))
    assert connection.errors[-1][1] == "not_found"
    monkeypatch.setattr(
        module,
        "async_cleanup_stale_entities",
        lambda *_args, **_kwargs: _async_value({"removed_count": 1}),
    )
    asyncio.run(
        module.websocket_cleanup_entities(
            hass,
            connection,
            {"id": 7, "entry_id": "entry1", "dry_run": False},
        )
    )
    assert connection.messages[-1]["result"] == {"removed_count": 1}
    asyncio.run(
        module.websocket_cleanup_entities(
            no_entry_hass,
            connection,
            {"id": 8, "dry_run": True},
        )
    )
    assert connection.errors[-1][1] == "not_found"


async def _async_value(value: object) -> object:
    return value


def test_panel_registration_and_unregistration(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_homeassistant(monkeypatch)
    module = import_fresh("custom_components.predictive_controls.panel")
    static_paths: list[object] = []

    async def register_static_paths(paths: list[object]) -> None:
        static_paths.extend(paths)

    hass = SimpleNamespace(
        http=SimpleNamespace(async_register_static_paths=register_static_paths)
    )

    asyncio.run(module.async_register_panel(hass, register_static_path=True))
    asyncio.run(module.async_register_panel(hass, register_static_path=False))
    assert len(static_paths) == 1
    assert len(fake.registered_panels) == 2
    assert fake.removed_panels == [DOMAIN, DOMAIN]
    assert module.panel_js_url().endswith("panel-v0.1.17.js")


def make_runtime() -> SimpleNamespace:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": [],
                }
            }
        }
    )
    confidence = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    occupancy_event = OccupancyEvent(
        "binary_sensor.office",
        "office",
        "office",
        None,
        "room_occupancy",
        "sustained",
        "motion",
        "on",
        datetime(2026, 7, 12, tzinfo=UTC),
        0.99,
    )
    confidence.observe(occupancy_event)
    return SimpleNamespace(
        map=predictive_map,
        zone_states=confidence.states,
        expected_occupants=1,
        expected_occupants_entity="",
        confidence=confidence,
        last_occupancy_event=occupancy_event,
        recent_occupancy_events=(occupancy_event,),
        last_source_node=None,
        last_prediction=None,
        probabilities={},
        transition_counts={},
        latency_metrics={"max_ms": 12.5, "performance_degraded": False},
        actions=(),
    )


def test_entity_lifecycles_properties_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_homeassistant(monkeypatch)
    sensor = import_fresh("custom_components.predictive_controls.sensor")
    binary = import_fresh("custom_components.predictive_controls.binary_sensor")
    diagnostics = import_fresh("custom_components.predictive_controls.diagnostics")
    runtime = make_runtime()
    hass = SimpleNamespace(data={DOMAIN: {"entry": runtime}})
    entry = SimpleNamespace(entry_id="entry", options={})
    entities: list[Any] = []
    asyncio.run(sensor.async_setup_entry(hass, entry, entities.extend))
    asyncio.run(binary.async_setup_entry(hass, entry, entities.extend))

    for entity in entities:
        entity.hass = hass
        asyncio.run(entity.async_added_to_hass())
        entity._handle_update()  # noqa: SLF001
        if hasattr(type(entity), "native_value"):
            _ = entity.native_value
        if hasattr(type(entity), "is_on"):
            _ = entity.is_on
        if hasattr(type(entity), "extra_state_attributes"):
            _ = entity.extra_state_attributes
        assert entity.writes == 1

    missing = sensor.ZoneDiagnosticConfidenceSensor(runtime, "entry", "missing")
    assert missing.native_value == 0.0
    assert missing.extra_state_attributes == {
        "status": "rejected",
        "reason": "no evidence",
    }
    zone_list = object.__new__(sensor.ZoneListSensor)
    with pytest.raises(NotImplementedError):
        _ = zone_list.zones
    payload = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))
    assert payload["entity_ids"] == ("binary_sensor.office",)
    assert payload["last_prediction"] is None
    assert payload["latency"] == {
        "max_ms": 12.5,
        "performance_degraded": False,
    }


def test_integration_setup_unload_and_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    install_homeassistant(monkeypatch)
    integration = importlib.import_module("custom_components.predictive_controls")
    calls: list[tuple[str, object]] = []

    class Store:
        def __init__(self, *_args: object) -> None:
            pass

        async def async_load(self) -> dict[str, object]:
            return {}

    class Runtime:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.stopped = False

        def restore_stored_state(self, *_args: object) -> bool:
            return False

        def start(self) -> None:
            calls.append(("start", self))

        async def async_stop(self) -> None:
            self.stopped = True

    async def register_panel(_hass: object, **kwargs: object) -> None:
        calls.append(("panel", kwargs))

    def register_websocket(_hass: object) -> None:
        calls.append(("websocket", None))

    panel_module = ModuleType("custom_components.predictive_controls.panel")
    panel_module.__dict__["async_register_panel"] = register_panel
    runtime_module = ModuleType("custom_components.predictive_controls.runtime")
    runtime_module.__dict__["PredictiveControlsRuntime"] = Runtime
    websocket_module = ModuleType("custom_components.predictive_controls.websocket")
    websocket_module.__dict__["async_register_websocket_commands"] = register_websocket
    storage_module = sys.modules["homeassistant.helpers.storage"]
    storage_module.__dict__["Store"] = Store
    monkeypatch.setitem(sys.modules, panel_module.__name__, panel_module)
    monkeypatch.setitem(sys.modules, runtime_module.__name__, runtime_module)
    monkeypatch.setitem(sys.modules, websocket_module.__name__, websocket_module)

    class ConfigEntries:
        unload_result = True

        async def async_forward_entry_setups(
            self, _entry: object, platforms: object
        ) -> None:
            calls.append(("forward", platforms))

        async def async_unload_platforms(
            self, _entry: object, _platforms: object
        ) -> bool:
            return self.unload_result

        async def async_reload(self, entry_id: str) -> None:
            calls.append(("reload", entry_id))

    hass = SimpleNamespace(data={}, config_entries=ConfigEntries())

    class Entry:
        entry_id = "entry"
        options = valid_options()

        def add_update_listener(self, listener: object) -> object:
            return listener

        def async_on_unload(self, listener: object) -> None:
            self.listener = listener

    entry = Entry()
    assert asyncio.run(integration.async_setup_entry(hass, entry))
    second = Entry()
    second.entry_id = "entry2"
    assert asyncio.run(integration.async_setup_entry(hass, second))
    assert sum(name == "websocket" for name, _ in calls) == 1
    assert asyncio.run(integration.async_unload_entry(hass, entry))
    hass.config_entries.unload_result = False
    assert not asyncio.run(integration.async_unload_entry(hass, second))
    asyncio.run(integration._async_update_listener(hass, second))  # noqa: SLF001
    assert ("reload", "entry2") in calls
