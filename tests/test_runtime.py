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
    PredictiveAction,
    ServiceCall,
)
from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.model import PredictiveMap
from tests.test_entity_platforms import install_fake_homeassistant
from tests.test_prediction import make_map as prediction_map

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
    assert restored.transition_store_data()["schema"] == "zone-belief-v3"

    rejected = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    assert not rejected.restore_stored_state({"schema_version": 99}, NOW)
    assert rejected.confidence.diagnostics.restore_status == "rejected"
    assert rejected.problem_reasons == ("restore_rejected",)


def test_runtime_reconciles_external_zero_after_restoring_count_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    source = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=2
    )
    source.confidence.ensure_state(NOW)
    payload = source.transition_store_data()
    restored = module.PredictiveControlsRuntime(
        _FakeHass({"sensor.people": _FakeState("0")}),
        make_map(),
        (),
        transition_window=30,
        expected_occupants=0,
        expected_occupants_entity="sensor.people",
    )

    assert restored.restore_stored_state(payload, NOW)
    assert restored.expected_occupants == 0
    assert restored.confidence.requested_expected_occupants == 0
    assert not restored._sync_expected_occupants(NOW)  # noqa: SLF001

    configured_zero = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=0
    )
    assert configured_zero.restore_stored_state(payload, NOW)
    assert configured_zero.expected_occupants == 0
    assert configured_zero.confidence.requested_expected_occupants == 0


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
    assert runtime_automation_summary(runtime).keep_on_zones == ()
    assert runtime.last_zone_update is None
    assert runtime.transition_store_data()["schema"] == "zone-belief-v3"
    assert runtime.latency_metrics["sample_count"] == 1


def test_runtime_lifecycle_persistence_callbacks_and_no_direct_actions(
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

    assert hass.services.calls == []

    asyncio.run(runtime.async_stop())
    assert unsubscribed == ["state", "interval", "interval", "interval"]
    assert store.saved


def test_runtime_schedules_prediction_release_at_exact_lease_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    scheduled: list[tuple[float, Callable[[datetime], None]]] = []

    def call_later(
        _hass: object,
        delay: float,
        callback: Callable[[datetime], None],
    ) -> Callable[[], None]:
        scheduled.append((delay, callback))
        return lambda: None

    monkeypatch.setattr(module, "async_call_later", call_later)
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), prediction_map(), (), transition_window=30, expected_occupants=1
    )
    runtime.confidence.ensure_state(NOW)
    for _ in range(5):
        runtime.chain.observe("kitchen", "living")
    runtime.observe_entity("binary_sensor.office", "on", NOW)
    runtime.observe_entity("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    runtime.observe_entity(
        "binary_sensor.kitchen", "on", NOW + timedelta(seconds=2)
    )

    assert runtime.confidence.policy_states["living"].phase == "predicted"
    delay, deadline_callback = scheduled[-1]
    assert delay == 10.0

    deadline_callback(NOW + timedelta(seconds=12))

    assert not runtime.confidence.policy_states["living"].active
    assert runtime.confidence.policy_states["living"].phase == "inactive"
    assert runtime._unsubscribe_prediction_deadline is None  # noqa: SLF001
    canceled: list[bool] = []
    runtime._unsubscribe_prediction_deadline = lambda: canceled.append(True)  # noqa: SLF001
    asyncio.run(runtime.async_stop())
    assert canceled == [True]


def test_zone_active_entity_publishes_prediction_confirmation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.binary_sensor", None)
    binary = importlib.import_module(
        "custom_components.predictive_controls.binary_sensor"
    )
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), prediction_map(), (), transition_window=30, expected_occupants=1
    )
    runtime.confidence.ensure_state(NOW)
    for _ in range(5):
        runtime.chain.observe("kitchen", "living")
    runtime.observe_entity("binary_sensor.office", "on", NOW)
    runtime.observe_entity("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    runtime.observe_entity(
        "binary_sensor.kitchen", "on", NOW + timedelta(seconds=2)
    )
    entity = binary.ZoneActiveSensor(runtime, "entry", "living")
    entity.hass = runtime.hass
    asyncio.run(entity.async_added_to_hass())
    assert entity.is_on
    assert entity.extra_state_attributes["phase"] == "predicted"

    runtime.observe_entity(
        "binary_sensor.living", "on", NOW + timedelta(seconds=3)
    )
    entity._handle_update()  # noqa: SLF001

    assert entity.is_on
    assert entity.extra_state_attributes["phase"] == "active"
    assert entity.state_write_count == 1


def test_supported_edge_dispatches_before_current_decision_audit_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.binary_sensor", None)
    binary = importlib.import_module(
        "custom_components.predictive_controls.binary_sensor"
    )
    publications: list[dict[str, object]] = []
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    entity = binary.ZoneActiveSensor(runtime, "entry", "office")
    entity.hass = runtime.hass
    asyncio.run(entity.async_added_to_hass())

    def capture(_hass: object, signal: str) -> None:
        if signal != module.DISPATCH_UPDATE:
            return
        entity._handle_update()  # noqa: SLF001
        publications.append(
            {
                "audit_count": len(runtime.confidence.diagnostics.policy_audit),
                "is_on": entity.is_on,
                **entity.extra_state_attributes,
            }
        )

    monkeypatch.setattr(module, "async_dispatcher_send", capture)
    runtime.observe_entity("binary_sensor.hall", "on", NOW)
    baseline_audit_count = len(runtime.confidence.diagnostics.policy_audit)
    publications.clear()

    runtime.observe_entity(
        "binary_sensor.office", "on", NOW + timedelta(seconds=1)
    )

    first = publications[0]
    assert first["audit_count"] == baseline_audit_count
    assert first["is_on"] is True
    assert first["reason"] == "acquired"
    assert first["phase"] == "active"
    assert first["activation_provenance"] == "evidence"
    assert first["track_confidence"] == "provisional"
    evidence_ids = first["evidence_ids"]
    final_audit_count = publications[-1]["audit_count"]
    assert isinstance(evidence_ids, list)
    assert len(evidence_ids) == 2
    assert isinstance(final_audit_count, int)
    assert final_audit_count > baseline_audit_count


def test_runtime_startup_validation_failure_does_not_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    subscriptions: list[str] = []
    monkeypatch.setattr(
        module,
        "async_track_state_change_event",
        lambda *_args, **_kwargs: subscriptions.append("state"),
    )
    monkeypatch.setattr(
        module,
        "async_track_time_interval",
        lambda *_args, **_kwargs: subscriptions.append("interval"),
    )
    ambiguous_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "room": {
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": "binary_sensor.room"},
                }
            }
        }
    )
    runtime = module.PredictiveControlsRuntime(
        _FakeHass({"binary_sensor.room": _FakeState("off")}),
        ambiguous_map,
        (),
        transition_window=30,
        expected_occupants=1,
    )

    with pytest.raises(ValueError, match="ambiguous occupancy metadata"):
        runtime.start()

    assert subscriptions == []


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


def test_runtime_preserves_event_time_and_records_processing_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    fired_at = datetime.now(UTC) - timedelta(milliseconds=5)

    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={
                "entity_id": "binary_sensor.hall",
                "new_state": _FakeState("on"),
            },
            time_fired=fired_at,
        )
    )

    assert runtime.recent_occupancy_events[-1].event_at == fired_at
    decision = next(
        row
        for row in reversed(runtime.confidence.diagnostics.policy_audit)
        if row.node_id == "hall"
    )
    assert decision.event_at == fired_at
    assert decision.processing_at >= fired_at
    assert runtime.latency_metrics["event_loop_delay_sample_count"] == 1


def test_runtime_rejects_delayed_out_of_order_sensor_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    runtime.observe_entity(
        "binary_sensor.hall",
        "on",
        NOW,
        processing_at=NOW + timedelta(seconds=1),
    )
    runtime.observe_entity(
        "binary_sensor.office",
        "on",
        NOW + timedelta(seconds=2),
        processing_at=NOW + timedelta(seconds=3),
    )
    generation = next(
        state
        for state in runtime.confidence.episode_states
        if state.node_id == "office"
    ).generation

    runtime.observe_entity(
        "binary_sensor.office",
        "off",
        NOW + timedelta(seconds=1),
        processing_at=NOW + timedelta(seconds=4),
    )

    office = next(
        state
        for state in runtime.confidence.episode_states
        if state.node_id == "office"
    )
    assert runtime.confidence.diagnostics.event_disposition == "stale"
    assert office.generation == generation
    assert office.status == "asserted"


def test_runtime_unavailable_source_cannot_authorize_adjacent_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    runtime = module.PredictiveControlsRuntime(
        _FakeHass(), make_map(), (), transition_window=30, expected_occupants=1
    )
    runtime.observe_entity("binary_sensor.hall", "on", NOW)
    runtime.observe_entity(
        "binary_sensor.hall", "unavailable", NOW + timedelta(seconds=1)
    )
    runtime.observe_entity(
        "binary_sensor.office", "on", NOW + timedelta(seconds=2)
    )

    hall = next(
        state
        for state in runtime.confidence.episode_states
        if state.node_id == "hall"
    )
    assert hall.status == "unavailable"
    assert runtime.confidence.traversal_tokens == ()
    assert not runtime.confidence.policy_states["office"].active


def test_runtime_migrates_legacy_state_with_current_authoritative_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runtime_module(monkeypatch)
    legacy_fingerprint = importlib.import_module(
        "custom_components.predictive_controls.zone_model.persistence"
    ).legacy_target_map_fingerprint
    legacy = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_fingerprint(make_map()),
        "occupants": 1,
        "policy": {"states": {"office": {"keep_on": True}}},
    }
    hass = _FakeHass(
        {
            "sensor.people": _FakeState("2"),
            "binary_sensor.office": _FakeState("on"),
            "binary_sensor.hall": _FakeState("off"),
            "binary_sensor.kitchen": _FakeState("off"),
        }
    )
    runtime = module.PredictiveControlsRuntime(
        hass,
        make_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
    )

    assert runtime.restore_stored_state(legacy, NOW)
    assert runtime.confidence.diagnostics.restore_status == "schema6_pending"
    assert runtime.confidence.requested_expected_occupants == 2
    runtime.start()

    assert runtime.confidence.diagnostics.restore_status == "schema6_migrated"
    assert runtime.expected_occupants == 2


def test_runtime_ignores_legacy_prediction_actions_and_reports_health(
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
    assert runtime.last_prediction is None
    assert runtime.last_source_node == "hall"
    assert runtime.probabilities == {}
    assert hass.services.calls == []

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
        "binary_sensor.office",
        "off",
        NOW + timedelta(seconds=7),
        NOW + timedelta(seconds=7),
        True,
        0,
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
    assert module._as_utc(NOW.replace(tzinfo=None)).tzinfo is UTC  # noqa: SLF001

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
