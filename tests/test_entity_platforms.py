from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.predictive_controls.const import DOMAIN
from custom_components.predictive_controls.entity_registry import (
    expected_entity_unique_ids,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_state import PolicyDecision


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
    def async_on_remove(self, callback: Callable[[], None]) -> None:
        self.remove_callbacks = getattr(self, "remove_callbacks", [])
        self.remove_callbacks.append(callback)

    def async_write_ha_state(self) -> None:
        self.state_write_count = getattr(self, "state_write_count", 0) + 1

    @property
    def unique_id(self) -> str | None:
        value = getattr(self, "_attr_unique_id", None)
        return value if isinstance(value, str) else None

    def _trigger_event(self, event_type: str, attributes: dict[str, object]) -> None:
        self.triggered_events = getattr(self, "triggered_events", [])
        self.triggered_events.append((event_type, attributes))


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
    sensor_module, _, _ = load_platform_modules(monkeypatch)

    unique_ids = platform_unique_ids(sensor_module, make_map())

    assert unique_ids == {
        "entry123_authoritative_occupant_count",
        "entry123_diagnostic_predicted_next_zone",
        "entry123_diagnostic_entry_path_plausible_zones",
        "entry123_living_room_diagnostic_confidence",
        "entry123_kitchen_diagnostic_confidence",
        "entry123_living_room_occupancy_probability",
        "entry123_kitchen_occupancy_probability",
        "entry123_living_room_arrival_supported_probability",
        "entry123_kitchen_arrival_supported_probability",
        "entry123_living_room_release_safe_probability",
        "entry123_kitchen_release_safe_probability",
    }


def test_binary_sensor_platform_exports_only_automation_facing_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, binary_sensor_module, _ = load_platform_modules(monkeypatch)

    unique_ids = platform_unique_ids(binary_sensor_module, make_map())

    assert unique_ids == {
        "entry123_home_active",
        "entry123_predictive_controls_problem",
        "entry123_living_room_active",
        "entry123_kitchen_active",
        "entry123_living_room_prelight",
        "entry123_kitchen_prelight",
        "entry123_living_room_diagnostic_entry_path_plausible",
        "entry123_kitchen_diagnostic_entry_path_plausible",
    }


def test_production_binary_sensor_publishes_only_edges_with_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, binary_sensor_module, _ = load_platform_modules(monkeypatch)
    runtime = SimpleNamespace(problem_reasons=(), problem_sources=())
    entity = binary_sensor_module.PredictiveControlsProblemSensor(
        runtime,
        "entry123",
    )
    entity.hass = object()
    asyncio.run(entity.async_added_to_hass())

    entity._handle_update()  # noqa: SLF001
    entity._handle_update()  # noqa: SLF001
    assert getattr(entity, "state_write_count", 0) == 0

    runtime.problem_reasons = ("association_overload",)
    runtime.problem_sources = ("movement_association",)
    entity._handle_update()  # noqa: SLF001
    entity._handle_update()  # noqa: SLF001

    assert entity.state_write_count == 1
    assert isinstance(entity.extra_state_attributes["explanation"], str)
    assert entity.extra_state_attributes["explanation"]

    runtime.problem_reasons = ()
    runtime.problem_sources = ()
    entity._handle_update()  # noqa: SLF001
    entity._handle_update()  # noqa: SLF001
    assert entity.state_write_count == 2


def test_diagnostic_sensor_subscribes_to_sampled_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor_module, _, _ = load_platform_modules(monkeypatch)
    signals: list[str] = []

    def connect(
        _hass: object,
        signal: str,
        _callback: Callable[[], None],
    ) -> Callable[[], None]:
        signals.append(signal)
        return lambda: None

    monkeypatch.setattr(
        sensor_module,
        "async_dispatcher_connect",
        connect,
    )
    entity = sensor_module.ZoneOccupancyProbabilitySensor(
        SimpleNamespace(),
        "entry123",
        "office",
    )
    entity.hass = object()

    asyncio.run(entity.async_added_to_hass())

    assert signals == [sensor_module.DISPATCH_DIAGNOSTIC_UPDATE]


def test_authoritative_count_sensor_remains_immediate_and_edge_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor_module, _, _ = load_platform_modules(monkeypatch)
    signals: list[str] = []

    def connect(
        _hass: object,
        signal: str,
        _callback: Callable[[], None],
    ) -> Callable[[], None]:
        signals.append(signal)
        return lambda: None

    monkeypatch.setattr(
        sensor_module,
        "async_dispatcher_connect",
        connect,
    )
    runtime = SimpleNamespace(
        authoritative_count_available=True,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
        confidence=SimpleNamespace(requested_expected_occupants=1),
    )
    entity = sensor_module.AuthoritativeOccupantCountSensor(runtime, "entry123")
    entity.hass = object()
    asyncio.run(entity.async_added_to_hass())

    entity._handle_update()  # noqa: SLF001
    runtime.expected_occupants = 2
    runtime.confidence.requested_expected_occupants = 2
    entity._handle_update()  # noqa: SLF001
    entity._handle_update()  # noqa: SLF001

    assert signals == [sensor_module.DISPATCH_UPDATE]
    assert entity.state_write_count == 1


def test_event_platform_exports_optional_arrival_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, event_module = load_platform_modules(monkeypatch)

    unique_ids = platform_unique_ids(event_module, make_map())

    assert unique_ids == {
        "entry123_living_room_arrival",
        "entry123_kitchen_arrival",
    }


def test_arrival_event_deduplicates_episode_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, event_module = load_platform_modules(monkeypatch)
    diagnostics = SimpleNamespace(
        joint_policy_decisions=(
            PolicyDecision(
                "living_room",
                "activate",
                True,
                "arrival_supported",
                {"probability": 0.9},
                ("living_motion@2026-07-15T12:00:00+00:00",),
            ),
        )
    )
    runtime = SimpleNamespace(
        confidence=SimpleNamespace(diagnostics=diagnostics),
        last_occupancy_event=SimpleNamespace(
            event_at=datetime(2026, 7, 15, 12, tzinfo=UTC)
        ),
    )
    entity = event_module.ZoneArrivalEvent(runtime, "entry123", "living_room")

    entity._project_decisions(emit=True)  # noqa: SLF001
    entity._project_decisions(emit=True)  # noqa: SLF001

    assert entity.triggered_events == [
        (
            "acquired",
            {
                "zone": "living_room",
                "episode_id": "living_motion@2026-07-15T12:00:00+00:00",
                "arrival_supported_probability": 0.9,
                "accepted_at": "2026-07-15T12:00:00+00:00",
                "reason": "arrival_supported",
            },
        )
    ]


def test_cleanup_registry_expected_ids_match_platform_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor_module, binary_sensor_module, event_module = load_platform_modules(
        monkeypatch
    )
    predictive_map = make_map()

    exported_ids = platform_unique_ids(
        sensor_module,
        predictive_map,
    ) | platform_unique_ids(
        binary_sensor_module,
        predictive_map,
    ) | platform_unique_ids(
        event_module,
        predictive_map,
    )

    assert expected_entity_unique_ids("entry123", predictive_map) == exported_ids


def load_platform_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType, ModuleType]:
    install_fake_homeassistant(monkeypatch)
    for module_name in (
        "custom_components.predictive_controls.runtime",
        "custom_components.predictive_controls.sensor",
        "custom_components.predictive_controls.binary_sensor",
        "custom_components.predictive_controls.event",
    ):
        sys.modules.pop(module_name, None)
    return (
        importlib.import_module("custom_components.predictive_controls.sensor"),
        importlib.import_module("custom_components.predictive_controls.binary_sensor"),
        importlib.import_module("custom_components.predictive_controls.event"),
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
    event_component = ModuleType("homeassistant.components.event")
    config_entries = ModuleType("homeassistant.config_entries")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    dispatcher = ModuleType("homeassistant.helpers.dispatcher")
    entity_platform = ModuleType("homeassistant.helpers.entity_platform")
    event = ModuleType("homeassistant.helpers.event")

    set_module_attr(sensor, "SensorEntity", FakeEntity)
    set_module_attr(sensor, "SensorEntityDescription", FakeSensorEntityDescription)
    set_module_attr(binary_sensor, "BinarySensorEntity", FakeEntity)
    set_module_attr(event_component, "EventEntity", FakeEntity)
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
    set_module_attr(components, "event", event_component)
    set_module_attr(helpers, "dispatcher", dispatcher)
    set_module_attr(helpers, "entity_platform", entity_platform)
    set_module_attr(helpers, "event", event)

    for module in (
        homeassistant,
        components,
        sensor,
        binary_sensor,
        event_component,
        config_entries,
        core,
        helpers,
        dispatcher,
        entity_platform,
        event,
    ):
        monkeypatch.setitem(sys.modules, module.__name__, module)
