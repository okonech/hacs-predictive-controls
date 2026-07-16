from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import UTC, datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace

import pytest
from test_entity_platforms import install_fake_homeassistant, make_map
from test_home_assistant_adapters import (
    FakeConfigEntries,
    FakeConnection,
    FakeEntry,
    install_homeassistant,
    valid_options,
)
from test_runtime import _FakeHass, _FakeState

from custom_components.predictive_controls.const import (
    CONF_ACTIVATION_RISK_THRESHOLD,
    CONF_RELEASE_RISK_THRESHOLD,
    DOMAIN,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_state import PolicyDecision
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
)

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    (
        (CONF_ACTIVATION_RISK_THRESHOLD, -0.01, "Activation risk threshold"),
        (CONF_RELEASE_RISK_THRESHOLD, 1.01, "Release risk threshold"),
    ),
)
def test_config_flow_rejects_out_of_range_policy_thresholds(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: float,
    message: str,
) -> None:
    install_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.config_flow", None)
    config_flow = importlib.import_module(
        "custom_components.predictive_controls.config_flow"
    )

    with pytest.raises(ValueError, match=message):
        config_flow._validate_options({**valid_options(), key: value})  # noqa: SLF001


def test_arrival_event_lifecycle_filters_and_deduplicates_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.event", None)
    event_module = importlib.import_module(
        "custom_components.predictive_controls.event"
    )
    decisions = (
        PolicyDecision("kitchen", "activate", True, "arrival_supported", {}, ("x",)),
        PolicyDecision("living_room", "release", True, "arrival_supported", {}, ("y",)),
        PolicyDecision("living_room", "activate", True, "other", {}, ("z",)),
        PolicyDecision(
            "living_room",
            "activate",
            True,
            "arrival_supported",
            {"probability": 0.91},
            ("episode-acquired", "episode-acquired"),
        ),
        PolicyDecision(
            "living_room",
            "activate",
            False,
            "already_active",
            {"probability": 0.82},
            ("episode-refreshed",),
        ),
    )
    runtime = SimpleNamespace(
        confidence=SimpleNamespace(
            diagnostics=SimpleNamespace(joint_policy_decisions=decisions)
        ),
        last_occupancy_event=None,
    )
    entity = event_module.ZoneArrivalEvent(runtime, "entry", "living_room")
    entity.hass = object()
    entity.async_on_remove = lambda callback: setattr(entity, "remove", callback)
    entity.async_write_ha_state = lambda: setattr(
        entity, "writes", getattr(entity, "writes", 0) + 1
    )

    asyncio.run(entity.async_added_to_hass())
    assert not hasattr(entity, "triggered_events")

    entity._handle_update()  # noqa: SLF001
    assert entity.writes == 1
    assert not hasattr(entity, "triggered_events")

    fresh = event_module.ZoneArrivalEvent(runtime, "entry", "living_room")
    fresh._project_decisions(emit=True)  # noqa: SLF001
    fresh._project_decisions(emit=True)  # noqa: SLF001
    assert fresh.triggered_events == [
        (
            "acquired",
            {
                "zone": "living_room",
                "episode_id": "episode-acquired",
                "arrival_supported_probability": 0.91,
                "accepted_at": None,
                "reason": "arrival_supported",
            },
        ),
        (
            "refreshed",
            {
                "zone": "living_room",
                "episode_id": "episode-refreshed",
                "arrival_supported_probability": 0.82,
                "accepted_at": None,
                "reason": "already_active",
            },
        ),
    ]


def test_tracker_defensive_guards_and_restore_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker_module = importlib.import_module(
        "custom_components.predictive_controls.occupancy_tracker"
    )
    naive = datetime(2026, 7, 15, 12)
    assert tracker_module._as_utc(naive) is naive  # noqa: SLF001

    tracker = OccupancyTracker(make_map(), TrackerConfig(expected_occupants=6))
    assert tracker.diagnostics.joint_requested_occupants == 6
    assert tracker.diagnostics.joint_unsupported_count == 6

    tracker.reconcile_expected_occupants(7, NOW, "count-seven")
    assert tracker.requested_expected_occupants == 7
    tracker.reconcile_expected_occupants(2, NOW, "count-two")
    assert tracker.config.expected_occupants == 2

    monkeypatch.setattr(tracker._engine, "serialize", lambda *_args: [])  # noqa: SLF001
    with pytest.raises(TypeError, match="must be a mapping"):
        tracker.occupancy_store_data(NOW, {})

    restored = SimpleNamespace(restore_status="verified")
    monkeypatch.setattr(
        tracker._engine,
        "restore",
        lambda value: tracker._engine.diagnostics,  # noqa: SLF001
    )
    tracker.restore_joint_state(restored)
    assert tracker.diagnostics.joint_restore_status == "verified"
    tracker.reject_joint_restore("bad checksum")
    assert tracker.diagnostics.joint_restore_status == "rejected"
    assert tracker.diagnostics.joint_restore_reason == "bad checksum"

    monkeypatch.setattr(tracker._engine, "_policy", None)  # noqa: SLF001
    with pytest.raises(RuntimeError, match="policy is unavailable"):
        _ = tracker._joint_policy  # noqa: SLF001

    migrated: list[tuple[object, object, object]] = []
    monkeypatch.setattr(
        tracker._engine,  # noqa: SLF001
        "migrate_legacy_state",
        lambda policies, transitions, routes: migrated.append(
            (policies, transitions, routes)
        ),
    )
    tracker.migrate_legacy_joint_state({}, {"office": {"hall": 2}}, {})
    assert migrated == [({}, {"office": {"hall": 2}}, {})]
    assert tracker.diagnostics.joint_restore_status == "legacy_v5_migrated"
    assert tracker.diagnostics.joint_restore_reason is None


def _load_runtime(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.runtime", None)
    return importlib.import_module("custom_components.predictive_controls.runtime")


def _runtime_map() -> PredictiveMap:
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
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office"],
                },
            }
        }
    )


def test_runtime_problem_reporting_and_restore_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_module = _load_runtime(monkeypatch)
    runtime = runtime_module.PredictiveControlsRuntime(
        _FakeHass(),
        _runtime_map(),
        (),
        transition_window=30,
        expected_occupants=1,
        expected_occupants_entity="sensor.people",
    )
    assert runtime.problem_reasons == ()
    monkeypatch.setattr(
        type(runtime.confidence),
        "diagnostics",
        property(
            lambda _confidence: SimpleNamespace(
                joint_performance={"overloaded": True},
                joint_route_transition_counts={},
            )
        ),
    )
    runtime._invalid_authoritative_count = True  # noqa: SLF001
    runtime._restore_rejected = True  # noqa: SLF001

    assert not runtime.authoritative_count_available
    assert runtime.problem_reasons == (
        "association_overload",
        "invalid_authoritative_count",
        "restore_rejected",
    )
    assert runtime.problem_sources == (
        "movement_association",
        "sensor.people",
        "occupancy_storage",
    )

    runtime.expected_occupants_entity = ""
    assert runtime.problem_sources[1] == "configured_expected_occupants"
    monkeypatch.setattr(
        runtime.confidence,
        "restore_joint_state",
        lambda _stored: (_ for _ in ()).throw(ValueError("bad exact payload")),
    )
    assert not runtime.restore_stored_state({"schema": "exact-augmented-v6"}, NOW)
    assert runtime.problem_reasons[-1] == "restore_rejected"

    restored = SimpleNamespace(
        policy_states={"office": object()},
        transition_counts={"office": {"hall": 1.0}},
        route_counts={("office",): {"hall": 2.0}},
    )
    migrations: list[tuple[object, object, object]] = []
    monkeypatch.setattr(runtime_module, "restore_occupancy_state", lambda *_: restored)
    monkeypatch.setattr(
        runtime.confidence,
        "migrate_legacy_joint_state",
        lambda policies, transitions, routes: migrations.append(
            (policies, transitions, routes)
        ),
    )
    assert runtime.restore_stored_state({"schema_version": 5}, NOW)
    assert migrations == [
        (restored.policy_states, restored.transition_counts, restored.route_counts)
    ]
    assert not runtime._restore_rejected  # noqa: SLF001


def test_runtime_recovers_supported_count_and_records_action_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_module = _load_runtime(monkeypatch)
    publications: list[str] = []
    monkeypatch.setattr(
        runtime_module,
        "async_dispatcher_send",
        lambda _hass, signal: publications.append(signal),
    )
    hass = _FakeHass(
        {
            "binary_sensor.office": _FakeState("on"),
            "sensor.people": _FakeState("2"),
        }
    )
    runtime = runtime_module.PredictiveControlsRuntime(
        hass,
        _runtime_map(),
        (),
        transition_window=30,
        expected_occupants=6,
        expected_occupants_entity="sensor.people",
    )
    assert runtime.confidence.requested_expected_occupants == 6

    bootstraps: list[tuple[tuple[OccupancyEvent, ...], bool]] = []
    monkeypatch.setattr(
        runtime.confidence,
        "bootstrap_joint_state",
        lambda snapshot, *, cold_start: bootstraps.append((snapshot, cold_start)),
    )
    runtime._async_state_changed(  # noqa: SLF001
        SimpleNamespace(
            data={"entity_id": "sensor.people", "new_state": _FakeState("2")},
            time_fired=NOW,
        )
    )
    assert runtime.confidence.requested_expected_occupants == 2
    assert bootstraps and bootstraps[0][1]
    assert [event.entity_id for event in bootstraps[0][0]] == [
        "binary_sensor.office"
    ]
    assert publications == [runtime_module.DISPATCH_UPDATE]

    action = SimpleNamespace(action=SimpleNamespace(action_id="prelight-office"))
    monkeypatch.setattr(runtime_module, "evaluate_actions", lambda *_args: (action,))
    runtime._evaluate_prediction_actions("office", NOW)  # noqa: SLF001
    assert runtime._last_action_fired == {"prelight-office": NOW}  # noqa: SLF001

    hass.states._states["sensor.people"] = _FakeState("unknown")
    assert not runtime._sync_expected_occupants(NOW)  # noqa: SLF001
    assert not runtime.authoritative_count_available

    naive = datetime(2026, 7, 15, 12)
    assert runtime_module._as_utc(naive) is naive  # noqa: SLF001
    eastern = datetime(2026, 7, 15, 8, tzinfo=timezone(timedelta(hours=-4)))
    assert runtime_module._as_utc(eastern) == NOW  # noqa: SLF001


def test_probability_sensors_preserve_unavailable_and_finalized_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.sensor", None)
    sensor_module = importlib.import_module(
        "custom_components.predictive_controls.sensor"
    )
    diagnostics = SimpleNamespace(
        joint_arrival_supported_probabilities={},
        joint_release_safe_available=True,
        joint_policy_states={
            "office": SimpleNamespace(keep_on=True),
            "idle": SimpleNamespace(keep_on=False),
        },
        joint_release_safe_probabilities={"office": 0.976, "idle": 0.8},
    )
    runtime = SimpleNamespace(confidence=SimpleNamespace(diagnostics=diagnostics))

    arrival = sensor_module.ZoneArrivalSupportedProbabilitySensor(
        runtime, "entry", "office"
    )
    assert not arrival.available
    assert arrival.native_value is None

    release = sensor_module.ZoneReleaseSafeProbabilitySensor(
        runtime, "entry", "office"
    )
    assert release.available
    assert release.native_value == 97.6
    assert release.extra_state_attributes == {"finalization_available": True}
    idle = sensor_module.ZoneReleaseSafeProbabilitySensor(runtime, "entry", "idle")
    assert not idle.available
    assert idle.native_value is None


def test_store_preserves_supported_legacy_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = install_homeassistant(monkeypatch)
    fake.modules["homeassistant.helpers.storage"].Store = object
    sys.modules.pop("custom_components.predictive_controls.storage", None)
    storage_module = importlib.import_module(
        "custom_components.predictive_controls.storage"
    )
    store = object.__new__(storage_module.PredictiveControlsStore)
    payload = {"schema_version": 4, "transition_counts": {"office": {}}}

    assert asyncio.run(store._async_migrate_func(4, 2, payload)) is payload
    development = {"schema": "prototype-augmented-v5", "occupants": 2}
    migrated = asyncio.run(store._async_migrate_func(5, 0, development))
    assert migrated == {"schema": "exact-augmented-v6", "occupants": 2}
    assert development["schema"] == "prototype-augmented-v5"


def test_websocket_rejects_out_of_range_policy_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_homeassistant(monkeypatch)
    sys.modules.pop("custom_components.predictive_controls.websocket", None)
    websocket = importlib.import_module(
        "custom_components.predictive_controls.websocket"
    )
    entry = FakeEntry("entry")
    hass = SimpleNamespace(
        config_entries=FakeConfigEntries([entry]),
        data={DOMAIN: {}},
        states=SimpleNamespace(async_all=lambda: []),
    )
    connection = FakeConnection()
    base = {
        "id": "save",
        "entry_id": "entry",
        "map_yaml": valid_options()["map_yaml"],
        "actions_yaml": valid_options()["actions_yaml"],
        "transition_window_seconds": 30,
        "prediction_threshold": 0.5,
        "expected_occupants": 1,
        "expected_occupants_entity": "",
    }

    for key in ("activation_risk_threshold", "release_risk_threshold"):
        asyncio.run(
            websocket.websocket_save_config(
                hass,
                connection,
                {**base, "id": key, key: 1.1},
            )
        )
        assert connection.errors[-1][0:2] == (key, "invalid_config")
        assert key in connection.errors[-1][2]
