from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from test_entity_platforms import install_fake_homeassistant

from custom_components.predictive_controls.actions import (
    ActionDecision,
    PredictiveAction,
    ServiceCall,
)
from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
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
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def office_event() -> OccupancyEvent:
    return OccupancyEvent(
        entity_id="binary_sensor.office",
        node_id="office",
        zone="office",
        floor=None,
        role="room_occupancy",
        occupancy_behavior="sustained",
        signal_type="motion",
        state="on",
        event_at=NOW + timedelta(seconds=1),
        reliability=0.9,
    )


def test_runtime_s19_s20_restore_bootstrap_and_reject_corrupt_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    runtime_module = importlib.import_module(
        "custom_components.predictive_controls.runtime"
    )
    runtime_type = runtime_module.PredictiveControlsRuntime
    predictive_map = make_map()
    before = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    before.observe(office_event())
    payload = before.occupancy_store_data(
        NOW + timedelta(seconds=2),
        {"office": {"hall": 0.9}},
    )
    store = _FakeStore()
    runtime = runtime_type(
        _FakeHass(),
        predictive_map,
        (),
        transition_window=30,
        expected_occupants=1,
        transition_store=store,
    )
    restart_at = NOW + timedelta(minutes=5)

    assert runtime.restore_stored_state(payload, restart_at)
    assert runtime.transition_counts["office"]["hall"] == 0.9
    runtime.observe_entity(
        "binary_sensor.office",
        "off",
        restart_at,
        process_prediction_actions=False,
    )
    summary = runtime_automation_summary(runtime)

    assert summary.zones["office"].keep_on
    assert not summary.zones["office"].activation_plausible
    assert not summary.prelight_plausible_zones
    assert store.delayed
    assert runtime.transition_store_data()["schema_version"] == 3

    store.delayed = False
    runtime.observe_entity(
        "binary_sensor.office",
        "off",
        restart_at + timedelta(seconds=1),
        process_prediction_actions=False,
    )
    provenance = runtime.confidence.diagnostics.joint_last_provenance
    assert provenance is not None
    assert provenance.disposition == "duplicate"
    assert store.delayed

    rejected = runtime_type(
        _FakeHass(),
        predictive_map,
        (),
        transition_window=30,
        expected_occupants=1,
    )
    assert not rejected.restore_stored_state({"schema_version": 99}, restart_at)
    assert rejected.confidence.diagnostics.joint_restore_status == "rejected"
    assert rejected.confidence.diagnostics.joint_restore_reason == (
        "unsupported occupancy storage schema"
    )


def test_runtime_unsupported_count_retains_keep_on_and_bootstraps_on_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    runtime_module = importlib.import_module(
        "custom_components.predictive_controls.runtime"
    )
    hass = _FakeHass(
        {
            "binary_sensor.office": _FakeState("on"),
            "sensor.people": _FakeState("1"),
        }
    )
    runtime = runtime_module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
    )
    runtime.observe_entity("binary_sensor.office", "on", NOW)
    assert runtime_automation_summary(runtime).zones["office"].keep_on

    hass.states._states["sensor.people"] = _FakeState("3")
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={"entity_id": "sensor.people", "new_state": _FakeState("3")},
            time_fired=NOW + timedelta(seconds=1),
        )
    )
    unsupported = runtime_automation_summary(runtime)
    assert runtime.confidence.requested_expected_occupants == 3
    assert unsupported.zones["office"].keep_on
    assert not unsupported.activation_plausible_zones
    assert not unsupported.prelight_plausible_zones

    bootstraps: list[tuple[tuple[OccupancyEvent, ...], bool]] = []
    original_bootstrap = runtime.confidence.bootstrap_joint_state

    def record_bootstrap(
        events: tuple[OccupancyEvent, ...], *, cold_start: bool
    ) -> None:
        bootstraps.append((events, cold_start))
        original_bootstrap(events, cold_start=cold_start)

    monkeypatch.setattr(runtime.confidence, "bootstrap_joint_state", record_bootstrap)
    hass.states._states["binary_sensor.office"] = _FakeState("off")
    hass.states._states["sensor.people"] = _FakeState("1")
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={"entity_id": "sensor.people", "new_state": _FakeState("1")},
            time_fired=NOW + timedelta(seconds=2),
        )
    )

    assert runtime.expected_occupants == 1
    assert len(bootstraps) == 1
    assert bootstraps[0][1]
    assert tuple(event.entity_id for event in bootstraps[0][0]) == (
        "binary_sensor.office",
    )
    recovered = runtime_automation_summary(runtime)
    assert recovered.zones["office"].keep_on
    assert not recovered.activation_plausible_zones


def test_runtime_start_bootstraps_snapshot_and_publishes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    runtime_module = importlib.import_module(
        "custom_components.predictive_controls.runtime"
    )
    publications: list[str] = []
    monkeypatch.setattr(
        runtime_module,
        "async_dispatcher_send",
        lambda _hass, signal: publications.append(signal),
    )
    hass = _FakeHass(
        {
            "binary_sensor.office": _FakeState("on"),
            "binary_sensor.hall": _FakeState("off"),
            "binary_sensor.kitchen": _FakeState("on"),
        }
    )
    runtime = runtime_module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=2,
    )

    runtime.start()

    assert publications == [runtime_module.DISPATCH_UPDATE]
    assert runtime.transition_store_data()["update_sequence"] == 1
    assert runtime.confidence.diagnostics.joint_pruned_probability == 0.0


def test_runtime_lifecycle_callbacks_persistence_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    runtime_module = importlib.import_module(
        "custom_components.predictive_controls.runtime"
    )
    publications: list[str] = []
    unsubscribed: list[str] = []
    state_callbacks: list[Callable[[object], None]] = []
    interval_callbacks: list[Callable[[object], None]] = []

    def track_state(
        _hass: object,
        _entities: object,
        callback: Callable[[object], None],
    ) -> object:
        state_callbacks.append(callback)
        return lambda: unsubscribed.append("state")

    def track_interval(
        _hass: object,
        callback: Callable[[object], None],
        _interval: object,
    ) -> object:
        interval_callbacks.append(callback)
        return lambda: unsubscribed.append("interval")

    monkeypatch.setattr(runtime_module, "async_track_state_change_event", track_state)
    monkeypatch.setattr(runtime_module, "async_track_time_interval", track_interval)
    monkeypatch.setattr(
        runtime_module,
        "async_dispatcher_send",
        lambda _hass, signal: publications.append(signal),
    )
    hass = _FakeHass(
        {
            "binary_sensor.office": _FakeState("on"),
            "binary_sensor.kitchen": _FakeState("unavailable"),
            "sensor.people": _FakeState("1"),
        }
    )
    store = _FakeStore()
    runtime = runtime_module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=2,
        expected_occupants_entity=" sensor.people ",
        transition_store=store,
        transition_counts={"office": {"hall": 2.0}},
    )

    assert runtime.chain is runtime.engine.chain
    assert runtime.probabilities == {}
    assert runtime.last_source_node is None
    assert runtime.last_prediction is None
    assert runtime.zone_states
    assert runtime.recent_occupancy_events == ()
    assert runtime.transition_counts["office"]["hall"] == 2.0
    assert runtime.expected_occupants == 2
    assert runtime.latency_metrics["sample_count"] == 0
    assert not runtime.restore_stored_state(None, NOW)

    runtime.start()
    assert len(state_callbacks) == 1
    assert len(interval_callbacks) == 2
    assert runtime.expected_occupants == 1
    assert runtime.latency_metrics["sample_count"] == 1
    assert store.delayed

    state_callback = state_callbacks[0]
    state_callback(SimpleNamespace(data={}, time_fired=NOW))
    state_callback(
        SimpleNamespace(
            data={"entity_id": "binary_sensor.office"},
            time_fired=datetime(2100, 1, 1, tzinfo=UTC),
        )
    )
    hass.states._states["sensor.people"] = _FakeState("2")
    state_callback(
        SimpleNamespace(
            data={
                "entity_id": "sensor.people",
                "new_state": _FakeState("2"),
            },
            time_fired=NOW,
        )
    )
    assert runtime.expected_occupants == 2
    state_callback(
        SimpleNamespace(
            data={
                "entity_id": "sensor.people",
                "new_state": _FakeState("2"),
            }
        )
    )
    state_callback(
        SimpleNamespace(
            data={
                "entity_id": "binary_sensor.office",
                "new_state": _FakeState("off"),
            }
        )
    )

    unchanged_update = runtime.last_zone_update
    monkeypatch.setattr(runtime.confidence, "refresh_active", lambda _now: ())
    runtime._async_refresh_active_confidence(NOW)  # noqa: SLF001
    assert runtime.last_zone_update is unchanged_update
    refreshed_update = SimpleNamespace(current=SimpleNamespace(zone="office"))
    monkeypatch.setattr(
        runtime.confidence,
        "refresh_active",
        lambda _now: (refreshed_update,),
    )
    runtime._async_refresh_active_confidence(NOW)  # noqa: SLF001
    assert runtime.last_zone_update is refreshed_update
    monkeypatch.setattr(
        runtime.confidence, "expire_transient_state", lambda _now: False
    )
    runtime._async_expire_transient_state(NOW)  # noqa: SLF001
    monkeypatch.setattr(runtime.confidence, "expire_transient_state", lambda _now: True)
    runtime._async_expire_transient_state(NOW)  # noqa: SLF001

    runtime.observe_entity("binary_sensor.unknown", "on", NOW)
    runtime.observe_entity("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    runtime.observe_node("hall", NOW + timedelta(seconds=2))
    assert isinstance(runtime._node_prediction_probabilities(), dict)  # noqa: SLF001
    assert "sensor.people" in runtime._tracked_entity_ids()  # noqa: SLF001

    action = PredictiveAction(
        "light",
        "office",
        ServiceCall("light.turn_on", {"entity_id": "light.office"}, {"brightness": 1}),
    )
    runtime._execute_actions((ActionDecision(action, 0.9),))  # noqa: SLF001
    assert hass.services.calls == [
        (
            "light",
            "turn_on",
            {"brightness": 1},
            {"entity_id": "light.office"},
            False,
        )
    ]

    awaitable = runtime.async_save_transition_counts()
    asyncio_run(awaitable)
    assert store.saved
    asyncio_run(runtime.async_stop())
    assert unsubscribed == ["state", "interval", "interval"]
    assert store.saved

    no_store = runtime_module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30
    )
    no_store.schedule_transition_count_save()
    asyncio_run(no_store.async_save_transition_counts())
    asyncio_run(no_store.async_stop())
    empty_map = PredictiveMap.from_mapping({"nodes": {"unbound": {"adjacent": []}}})
    empty_runtime = runtime_module.PredictiveControlsRuntime(
        _FakeHass(), empty_map, (), transition_window=30
    )
    empty_runtime.start()
    none_event_runtime = runtime_module.PredictiveControlsRuntime(
        _FakeHass({"binary_sensor.office": _FakeState("on")}),
        make_map(),
        (),
        transition_window=30,
    )
    monkeypatch.setattr(
        runtime_module, "event_from_entity", lambda *_args, **_kwargs: None
    )
    none_event_runtime.start()
    monkeypatch.setattr(
        runtime_module,
        "event_from_entity",
        importlib.import_module(
            "custom_components.predictive_controls.events"
        ).event_from_entity,
    )
    ceiling_runtime = runtime_module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    clock = iter((0, 100_000_001, 100_000_002))
    monkeypatch.setattr(runtime_module, "perf_counter_ns", lambda: next(clock))
    ceiling_runtime.observe_entity("binary_sensor.office", "on", NOW)
    assert ceiling_runtime.latency_metrics["performance_degraded"]
    assert ceiling_runtime.latency_metrics["performance_budget_exceeded_count"] == 1
    assert runtime_automation_summary(ceiling_runtime).zones[
        "office"
    ].activation_plausible
    assert runtime_module._latency_summary((4.0, 1.0, 3.0, 2.0)) == {  # noqa: SLF001
        "sample_count": 4,
        "last_ms": 2.0,
        "p50_ms": 2.0,
        "p95_ms": 4.0,
        "p99_ms": 4.0,
        "max_ms": 4.0,
    }


def asyncio_run(awaitable: object) -> object:
    import asyncio

    return asyncio.run(awaitable)  # type: ignore[arg-type]


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
        self.tasks: list[object] = []

    def async_create_task(self, task: object) -> None:
        self.tasks.append(task)
        asyncio_run(task)


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
