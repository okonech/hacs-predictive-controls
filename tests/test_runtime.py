from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.predictive_controls.actions import (
    ActionDecision,
    PredictiveAction,
    ServiceCall,
)
from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.model import PredictiveMap
from tests.test_entity_platforms import install_fake_homeassistant

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {
                    "zone": "kitchen",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def runtime_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    return importlib.import_module("custom_components.predictive_controls.runtime")


def test_runtime_restores_target_state_and_rejects_corrupt_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    before = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    before.observe_entity("binary_sensor.hall", "on", NOW)
    before.observe_entity("binary_sensor.office", "on", NOW + timedelta(seconds=2))
    payload = before.transition_store_data()

    restored = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    assert restored.restore_stored_state(payload, NOW + timedelta(seconds=3))
    assert restored.confidence.diagnostics.policy_states["office"].active is True
    assert restored.transition_store_data()["schema"] == "zone-belief-v1"

    rejected = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    assert not rejected.restore_stored_state({"schema_version": 99}, NOW)
    assert rejected.confidence.diagnostics.restore_status == "rejected"
    assert rejected.problem_reasons == ("restore_rejected",)


def test_runtime_unsupported_count_retains_last_supported_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    hass = _FakeHass({"sensor.people": _FakeState("1")})
    runtime = module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
    )
    runtime.confidence.ensure_state(NOW)

    hass.states._states["sensor.people"] = _FakeState("3")
    assert runtime._sync_expected_occupants(NOW + timedelta(seconds=1))  # noqa: SLF001

    assert runtime.expected_occupants == 1
    assert runtime.confidence.requested_expected_occupants == 3
    assert runtime.confidence.diagnostics.unsupported_count == 3
    assert runtime.problem_reasons == ()


def test_runtime_start_bootstraps_snapshot_without_public_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    publications: list[str] = []
    monkeypatch.setattr(
        module,
        "async_dispatcher_send",
        lambda _hass, signal: publications.append(signal),
    )
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(
            {
                "binary_sensor.office": _FakeState("on"),
                "binary_sensor.hall": _FakeState("off"),
                "binary_sensor.kitchen": _FakeState("off"),
            }
        ),
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
    )

    runtime.start()

    assert publications == [module.DISPATCH_UPDATE]
    assert not runtime_automation_summary(runtime).keep_on_zones
    assert runtime.transition_store_data()["schema"] == "zone-belief-v1"
    assert runtime.latency_metrics["sample_count"] == 1


def test_runtime_lifecycle_persistence_callbacks_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    unsubscribed: list[str] = []
    state_callbacks: list[Callable[[object], None]] = []

    def track_state(
        _hass: object, _entities: object, callback: Callable[[object], None]
    ) -> Callable[[], None]:
        state_callbacks.append(callback)
        return lambda: unsubscribed.append("state")

    def track_interval(
        _hass: object, _callback: object, _interval: object
    ) -> Callable[[], None]:
        return lambda: unsubscribed.append("interval")

    monkeypatch.setattr(module, "async_track_state_change_event", track_state)
    monkeypatch.setattr(module, "async_track_time_interval", track_interval)
    store = _FakeStore()
    hass = _FakeHass()
    runtime = module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        transition_store=store,
    )
    runtime.start()
    observed_at = datetime.now(UTC) + timedelta(seconds=1)
    runtime.observe_entity("binary_sensor.hall", "on", observed_at)
    runtime.observe_entity(
        "binary_sensor.office", "on", observed_at + timedelta(seconds=2)
    )

    assert runtime_automation_summary(runtime).zones["office"].keep_on
    assert store.delayed
    assert state_callbacks

    action = PredictiveAction(
        "light",
        "office",
        ServiceCall("light.turn_on", {"entity_id": "light.office"}, {"brightness": 1}),
    )
    runtime._execute_actions((ActionDecision(action, 0.9),))  # noqa: SLF001
    assert hass.services.calls[0][0:2] == ("light", "turn_on")

    asyncio.run(runtime.async_stop())
    assert unsubscribed == ["state", "interval", "interval", "interval"]
    assert store.saved


def test_runtime_adapter_boundaries_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    publications: list[str] = []
    monkeypatch.setattr(
        module,
        "async_dispatcher_send",
        lambda _hass, signal: publications.append(signal),
    )
    hass = _FakeHass({"sensor.people": _FakeState("invalid")})
    runtime = module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
    )

    assert runtime.chain is runtime.confidence.prediction_chain
    assert runtime.probabilities == {}
    assert runtime.last_source_node is None
    assert runtime.last_prediction is None
    assert runtime.zone_states
    assert runtime.recent_occupancy_events == ()
    assert runtime.transition_counts
    assert runtime.authoritative_count_available
    assert not runtime.restore_stored_state([], NOW)

    runtime.confidence.ensure_state(NOW)
    assert not runtime._sync_expected_occupants(NOW)  # noqa: SLF001
    assert not runtime.authoritative_count_available
    runtime._restore_rejected = True  # noqa: SLF001
    assert runtime.problem_reasons == (
        "invalid_authoritative_count",
        "restore_rejected",
    )
    assert runtime.problem_sources == ("sensor.people", "occupancy_storage")

    runtime._async_state_changed(SimpleNamespace(data={}))  # noqa: SLF001
    hass.states._states["sensor.people"] = _FakeState("2")
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={
                "entity_id": "sensor.people",
                "new_state": _FakeState("2"),
            },
            time_fired=datetime.now(UTC) - timedelta(milliseconds=1),
        )
    )
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={
                "entity_id": "sensor.people",
                "new_state": _FakeState("2"),
            }
        )
    )
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={
                "entity_id": "binary_sensor.missing",
                "new_state": _FakeState("on"),
            }
        )
    )
    runtime._async_publish_diagnostics(NOW)  # noqa: SLF001
    runtime.observe_node("hall", NOW + timedelta(seconds=1))
    assert publications

    runtime._unsubscribe = object()  # noqa: SLF001
    asyncio.run(runtime.async_stop())


def test_runtime_prediction_action_refresh_health_and_empty_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    action = PredictiveAction(
        "prelight",
        "kitchen",
        ServiceCall("light.turn_on", {"entity_id": "light.kitchen"}),
        min_probability=0.4,
    )
    hass = _FakeHass()
    runtime = module.PredictiveControlsRuntime(
        hass, make_map(), (action,), transition_window=30, expected_occupants=1
    )
    runtime.observe_entity("binary_sensor.office", "on", NOW)
    runtime.observe_entity("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    assert runtime.last_prediction is not None
    assert runtime.last_source_node == "hall"
    assert runtime.probabilities["kitchen"] == pytest.approx(1.0)
    assert hass.services.calls

    runtime._async_refresh_active_confidence(  # noqa: SLF001
        NOW + timedelta(minutes=20)
    )
    runtime.confidence.refresh_active = lambda _now: ()
    runtime._async_refresh_active_confidence(  # noqa: SLF001
        NOW + timedelta(minutes=20)
    )
    runtime._async_refresh_active_confidence(  # noqa: SLF001
        NOW + timedelta(minutes=20)
    )
    assert "sensor_health_degraded" in runtime.problem_reasons
    assert "physical_sensor_episode" in runtime.problem_sources
    runtime._async_expire_transient_state(NOW + timedelta(minutes=21))  # noqa: SLF001
    transient = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    transient.observe_entity("binary_sensor.hall", "on", NOW)
    transient.observe_entity("binary_sensor.hall", "off", NOW + timedelta(seconds=1))
    transient._async_expire_transient_state(  # noqa: SLF001
        NOW + timedelta(seconds=6)
    )
    transient._observe_entity(  # noqa: SLF001
        "binary_sensor.office", "off", NOW + timedelta(seconds=7), True, 0
    )

    empty_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unbound": {
                    "zone": "unbound",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                }
            }
        }
    )
    empty = module.PredictiveControlsRuntime(
        _FakeHass(), empty_map, (), transition_window=30, expected_occupants=1
    )
    empty.start()
    empty.schedule_transition_count_save()
    asyncio.run(empty.async_save_transition_counts())
    assert module._as_utc(NOW.replace(tzinfo=None)).tzinfo is None  # noqa: SLF001

    partial = module.PredictiveControlsRuntime(
        _FakeHass({"binary_sensor.office": _FakeState("off")}),
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
    )
    partial.start()


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


class _FakeStore:
    def __init__(self) -> None:
        self.delayed = False
        self.saved = False

    def async_delay_save(self, data: object, delay: int) -> None:
        self.delayed = callable(data) and delay == 1

    async def async_save(self, data: object) -> None:
        self.saved = isinstance(data, dict)
