from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, cast

import pytest

from custom_components.predictive_controls.const import DOMAIN
from custom_components.predictive_controls.entity_registry import (
    expected_entity_unique_ids,
)
from custom_components.predictive_controls.model import PredictiveMap


@dataclass(frozen=True)
class FakeEntry:
    entry_id: str = "entry123"
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FakeRuntime:
    map: PredictiveMap


@dataclass(frozen=True)
class FakeHass:
    data: dict[str, dict[str, FakeRuntime]]


class FakeEntity:
    @property
    def unique_id(self) -> str | None:
        value = getattr(self, "_attr_unique_id", None)
        return value if isinstance(value, str) else None


class FakeSensorEntityDescription:
    def __init__(self, *, key: str, name: str, icon: str) -> None:
        self.key = key
        self.name = name
        self.icon = icon


EntityCollector = Callable[[list[object]], None]
PlatformSetup = Callable[
    [FakeHass, FakeEntry, EntityCollector],
    Coroutine[Any, Any, None],
]


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "living_motion": {
                    "zone": "living_room",
                    "adjacent": ["kitchen_motion"],
                },
                "kitchen_motion": {
                    "zone": "kitchen",
                    "adjacent": ["living_motion"],
                },
            }
        }
    )


def test_sensor_platform_exports_only_automation_facing_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor_module, _ = load_platform_modules(monkeypatch)

    unique_ids = platform_unique_ids(sensor_module, make_map())

    assert unique_ids == {
        "entry123_predicted_next_zone",
        "entry123_probable_inside_count",
        "entry123_possible_inside_count",
        "entry123_probable_occupied_zones",
        "entry123_possible_occupied_zones",
        "entry123_living_room_confidence",
        "entry123_kitchen_confidence",
    }


def test_binary_sensor_platform_exports_only_automation_facing_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, binary_sensor_module = load_platform_modules(monkeypatch)

    unique_ids = platform_unique_ids(binary_sensor_module, make_map())

    assert unique_ids == {
        "entry123_home_probable_occupancy",
        "entry123_living_room_probable_occupancy",
        "entry123_kitchen_probable_occupancy",
        "entry123_living_room_possible_occupancy",
        "entry123_kitchen_possible_occupancy",
        "entry123_living_room_zone_predicted_next",
        "entry123_kitchen_zone_predicted_next",
    }


def test_cleanup_registry_expected_ids_match_platform_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor_module, binary_sensor_module = load_platform_modules(monkeypatch)
    predictive_map = make_map()

    exported_ids = platform_unique_ids(
        sensor_module,
        predictive_map,
    ) | platform_unique_ids(
        binary_sensor_module,
        predictive_map,
    )

    assert expected_entity_unique_ids("entry123", predictive_map) == exported_ids


def load_platform_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType]:
    install_fake_homeassistant(monkeypatch)
    for module_name in (
        "custom_components.predictive_controls.runtime",
        "custom_components.predictive_controls.sensor",
        "custom_components.predictive_controls.binary_sensor",
    ):
        sys.modules.pop(module_name, None)
    return (
        importlib.import_module("custom_components.predictive_controls.sensor"),
        importlib.import_module("custom_components.predictive_controls.binary_sensor"),
    )


def platform_unique_ids(
    platform_module: ModuleType,
    predictive_map: PredictiveMap,
) -> set[str]:
    runtime = FakeRuntime(predictive_map)
    hass = FakeHass(data={DOMAIN: {"entry123": runtime}})
    entry = FakeEntry()
    entities: list[object] = []

    setup = cast(PlatformSetup, platform_module.async_setup_entry)
    asyncio.run(setup(hass, entry, entities.extend))

    unique_ids = {getattr(entity, "unique_id", None) for entity in entities}
    assert all(isinstance(unique_id, str) for unique_id in unique_ids)
    return cast(set[str], unique_ids)


def install_fake_homeassistant(monkeypatch: pytest.MonkeyPatch) -> None:
    def set_module_attr(module: ModuleType, name: str, value: object) -> None:
        module.__dict__[name] = value

    def callback(function: Callable[..., Any]) -> Callable[..., Any]:
        return function

    def unsubscribe_factory(*_args: object, **_kwargs: object) -> Callable[[], None]:
        return lambda: None

    def dispatcher_send(*_args: object, **_kwargs: object) -> None:
        return None

    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    sensor = ModuleType("homeassistant.components.sensor")
    binary_sensor = ModuleType("homeassistant.components.binary_sensor")
    config_entries = ModuleType("homeassistant.config_entries")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    dispatcher = ModuleType("homeassistant.helpers.dispatcher")
    entity_platform = ModuleType("homeassistant.helpers.entity_platform")
    event = ModuleType("homeassistant.helpers.event")

    set_module_attr(sensor, "SensorEntity", FakeEntity)
    set_module_attr(sensor, "SensorEntityDescription", FakeSensorEntityDescription)
    set_module_attr(binary_sensor, "BinarySensorEntity", FakeEntity)
    set_module_attr(config_entries, "ConfigEntry", object)
    set_module_attr(core, "Event", object)
    set_module_attr(core, "HomeAssistant", object)
    set_module_attr(core, "callback", callback)
    set_module_attr(dispatcher, "async_dispatcher_connect", unsubscribe_factory)
    set_module_attr(dispatcher, "async_dispatcher_send", dispatcher_send)
    set_module_attr(
        entity_platform,
        "AddEntitiesCallback",
        Callable[[list[object]], None],
    )
    set_module_attr(event, "async_track_state_change_event", unsubscribe_factory)
    set_module_attr(event, "async_track_time_interval", unsubscribe_factory)

    set_module_attr(homeassistant, "components", components)
    set_module_attr(homeassistant, "config_entries", config_entries)
    set_module_attr(homeassistant, "core", core)
    set_module_attr(homeassistant, "helpers", helpers)
    set_module_attr(components, "sensor", sensor)
    set_module_attr(components, "binary_sensor", binary_sensor)
    set_module_attr(helpers, "dispatcher", dispatcher)
    set_module_attr(helpers, "entity_platform", entity_platform)
    set_module_attr(helpers, "event", event)

    for module in (
        homeassistant,
        components,
        sensor,
        binary_sensor,
        config_entries,
        core,
        helpers,
        dispatcher,
        entity_platform,
        event,
    ):
        monkeypatch.setitem(sys.modules, module.__name__, module)
