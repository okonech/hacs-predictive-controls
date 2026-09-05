import asyncio
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest

from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.model import PredictiveMap


def install_fake_homeassistant(monkeypatch: pytest.MonkeyPatch) -> None:
    def callback(function: Callable[..., Any]) -> Callable[..., Any]:
        return function

    def unsubscribe_factory(*_args: object, **_kwargs: object) -> Callable[[], None]:
        return lambda: None

    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    dispatcher = ModuleType("homeassistant.helpers.dispatcher")
    event = ModuleType("homeassistant.helpers.event")

    core.Event = object  # type: ignore[attr-defined]
    core.HomeAssistant = object  # type: ignore[attr-defined]
    core.callback = callback  # type: ignore[attr-defined]
    dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    event.async_call_later = unsubscribe_factory  # type: ignore[attr-defined]
    event.async_track_state_change_event = unsubscribe_factory  # type: ignore[attr-defined]
    event.async_track_time_interval = unsubscribe_factory  # type: ignore[attr-defined]
    homeassistant.core = core  # type: ignore[attr-defined]
    homeassistant.helpers = helpers  # type: ignore[attr-defined]
    helpers.dispatcher = dispatcher  # type: ignore[attr-defined]
    helpers.event = event  # type: ignore[attr-defined]

    for module in (homeassistant, core, helpers, dispatcher, event):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def runtime_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    return importlib.import_module("custom_components.predictive_controls.runtime")


@dataclass
class _FakeState:
    state: str


class _FakeStates:
    def __init__(self, states: dict[str, _FakeState] | None = None) -> None:
        self._states = states or {}

    def get(self, entity_id: str) -> _FakeState | None:
        return self._states.get(entity_id)


class _FakeHass:
    def __init__(self, states: dict[str, _FakeState] | None = None) -> None:
        self.states = _FakeStates(states)
        self.data: dict[str, Any] = {}
        self.services = _FakeServices()

    def async_create_task(self, task: object) -> None:
        asyncio.run(task)  # type: ignore[arg-type]


class _FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, object],
        *,
        target: dict[str, object],
        blocking: bool,
    ) -> None:
        self.calls.append((domain, service, data, target, blocking))


@pytest.mark.scenario
def test_inc_2026_08_23_stale_interaction_recovery_does_not_change_occupancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "top_of_staircase_motion": {
                    "zone": "upstairs_hallway",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.top_of_staircase"},
                    "adjacent": ["alex_office_motion"],
                    "initial_weight": 0.85,
                },
                "alex_office_motion": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.alex_office"},
                    "adjacent": ["top_of_staircase_motion"],
                    "initial_weight": 0.75,
                },
                "alex_office_interaction": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.alex_office_scene_001",
                        "interaction_scene_002": "event.alex_office_scene_002",
                        "interaction_scene_003": "event.alex_office_scene_003",
                    },
                },
                "shaila_office_interaction": {
                    "zone": "shaila_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.shaila_office_scene_001",
                        "interaction_scene_002": "event.shaila_office_scene_002",
                        "interaction_scene_003": "event.shaila_office_scene_003",
                    },
                },
                "bathroom_fan_interaction": {
                    "zone": "upstairs_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.bathroom_fan_scene_001",
                        "interaction_scene_002": "event.bathroom_fan_scene_002",
                        "interaction_scene_003": "event.bathroom_fan_scene_003",
                    },
                },
                "bathroom_light_interaction": {
                    "zone": "upstairs_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.bathroom_light_scene_001",
                        "interaction_scene_002": "event.bathroom_light_scene_002",
                        "interaction_scene_003": "event.bathroom_light_scene_003",
                    },
                },
            }
        }
    )
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(),
        predictive_map,
        (),
        transition_window=30,
        expected_occupants=2,
    )
    runtime.observe_entity(
        "binary_sensor.top_of_staircase",
        "on",
        datetime(2026, 8, 23, 19, 9, 17, 250589, tzinfo=UTC),
    )
    runtime.observe_entity(
        "binary_sensor.alex_office",
        "on",
        datetime(2026, 8, 23, 19, 9, 26, 138958, tzinfo=UTC),
    )
    runtime.observe_entity(
        "binary_sensor.top_of_staircase",
        "off",
        datetime(2026, 8, 23, 19, 9, 33, 708108, tzinfo=UTC),
    )

    callbacks = (
        ("event.shaila_office_scene_001", "2026-08-21T08:16:35.309+00:00", 242662),
        ("event.shaila_office_scene_002", "2026-08-20T01:36:12.778+00:00", 248572),
        ("event.shaila_office_scene_003", "2026-06-03T02:49:10.471+00:00", 254359),
        ("event.bathroom_fan_scene_001", "2026-08-21T21:40:44.433+00:00", 516623),
        ("event.bathroom_fan_scene_002", "2026-08-21T21:34:30.319+00:00", 522891),
        ("event.bathroom_fan_scene_003", "2026-08-21T17:24:40.415+00:00", 529171),
        ("event.bathroom_light_scene_001", "2026-08-21T21:40:44.416+00:00", 549337),
        ("event.bathroom_light_scene_002", "2026-08-20T19:06:04.325+00:00", 556143),
        ("event.bathroom_light_scene_003", "2026-08-13T21:46:51.905+00:00", 562480),
        ("event.alex_office_scene_001", "2026-07-01T09:07:28.501+00:00", 627256),
        ("event.alex_office_scene_002", "2026-08-20T06:14:11.299+00:00", 633659),
        ("event.alex_office_scene_003", "unknown", 640059),
    )
    for entity_id, state, microsecond in callbacks:
        runtime.observe_entity(
            entity_id,
            state,
            datetime(2026, 8, 23, 19, 23, 1, microsecond, tzinfo=UTC),
        )

    immediate = runtime_automation_summary(runtime)
    assert immediate.zones["alex_office"].keep_on
    assert not immediate.zones["shaila_office"].keep_on
    assert not immediate.zones["upstairs_bathroom"].keep_on
    episodes = {
        state.node_id: state for state in runtime.confidence.episode_states
    }
    alex_episode = episodes["alex_office_motion"]
    assert alex_episode.status == "asserted"
    assert alex_episode.episode_id is not None
    alex_interaction = episodes["alex_office_interaction"]
    assert dict(alex_interaction.alias_states)["event.alex_office_scene_003"] == (
        "unknown"
    )
    assert alex_interaction.episode_id is None
    assert all(
        episodes[node_id].episode_id is None
        for node_id in (
            "shaila_office_interaction",
            "bathroom_fan_interaction",
            "bathroom_light_interaction",
        )
    )
    engine = runtime.confidence._engine  # noqa: SLF001
    assert engine is not None
    alex_belief = next(
        state
        for state in engine.snapshot.belief_states
        if state.zone == "alex_office"
    )
    assert alex_belief.context == "asserted"
    assert alex_belief.generation_episode_id == alex_episode.episode_id
    assert alex_belief.asserted_episode_id == alex_episode.episode_id
    assert not any(
        item.kind == "local_interaction" for item in alex_belief.contributions
    )
    for seconds in range(5, 22 * 60 + 1, 5):
        runtime.confidence.expire_transient_state(
            datetime(2026, 8, 23, 19, 23, 1, 640059, tzinfo=UTC)
            + timedelta(seconds=seconds)
        )
    assert runtime_automation_summary(runtime).zones["alex_office"].keep_on
