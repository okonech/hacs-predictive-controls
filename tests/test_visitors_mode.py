from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.predictive_controls.const import DOMAIN
from custom_components.predictive_controls.events import (
    OccupancyEvent,
    event_from_entity,
)
from custom_components.predictive_controls.visitors import VisitorsMode
from tests.runtime_replay import RuntimeScenario
from tests.test_events import interaction_map
from tests.test_runtime import make_map

NOW = datetime(2026, 10, 31, tzinfo=UTC)


def motion(at: datetime = NOW, state: str = "on") -> OccupancyEvent:
    event = event_from_entity(make_map(), "binary_sensor.office", state, at)
    assert event is not None
    return event


def record(**changes: object) -> dict[str, object]:
    return {
        "version": 1,
        "enabled": False,
        "held_zones": [],
        "exit_at": None,
        **changes,
    }


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "on",
        {},
        record(version=True),
        record(version=2),
        record(enabled=1),
        record(enabled="false"),
        record(held_zones="office"),
        record(held_zones=[1]),
        record(held_zones=[""]),
        record(held_zones=["office", "office"]),
        record(exit_at=1),
        record(exit_at="invalid"),
        record(held_zones=["office"], exit_at="0001-01-01T00:00:00+01:00"),
        record(exit_at="2026-10-31T00:00:30"),
        record(enabled=True, exit_at="2026-10-31T00:00:30+00:00"),
        record(held_zones=["office"]),
        record(exit_at="2026-10-31T00:00:30+00:00"),
    ],
)
def test_invalid_manual_storage_resets_atomically(raw: object) -> None:
    mode = VisitorsMode(("office",))
    mode.set_enabled(True, NOW)
    mode.observe(motion(), NOW)
    assert not mode.restore(raw, NOW)
    assert mode.store_data() == record()


def test_storage_legacy_pruning_offsets_and_expiry() -> None:
    mode = VisitorsMode(("office",))
    assert mode.restore(None, NOW)
    assert mode.store_data() == record()
    assert mode.restore(record(enabled=True, held_zones=["office", "removed"]), NOW)
    assert mode.enabled and mode.held_zones == {"office"}
    mode.set_enabled(False, NOW)
    persisted = mode.store_data()
    assert mode.restore(persisted, NOW + timedelta(seconds=10))
    assert mode.exit_at == NOW + timedelta(seconds=30)
    assert not mode.expire(NOW + timedelta(seconds=29, microseconds=999999))
    assert mode.expire(NOW + timedelta(seconds=30))
    assert mode.store_data() == record()
    assert mode.restore(persisted, NOW + timedelta(minutes=1))
    assert mode.store_data() == record()
    assert mode.restore(
        record(
            held_zones=["office"],
            exit_at="2026-10-30T20:00:30-04:00",
        ),
        NOW,
    )
    assert mode.exit_at == NOW + timedelta(seconds=30)


@pytest.mark.parametrize("signal", ["motion", "pir", "mmwave", "presence", "occupancy"])
def test_local_motion_signals_hold_only_their_zone(signal: str) -> None:
    mode = VisitorsMode(("office", "hall"))
    mode.set_enabled(True, NOW)
    mode.observe(replace(motion(), signal_type=signal), NOW)
    mode.observe(motion(NOW + timedelta(seconds=1), "off"), NOW + timedelta(seconds=1))
    mode.observe(
        motion(NOW + timedelta(seconds=2), "unknown"), NOW + timedelta(seconds=2)
    )
    assert mode.held_zones == {"office"}
    assert not mode.retain_active(("office",))
    assert mode.retain_active(("hall",))


def test_input_frontiers_enable_grace_and_idempotency() -> None:
    mode = VisitorsMode(("office",))
    mode.sample((motion(),), NOW)
    mode.observe(motion(), NOW)
    assert not mode.held_zones
    mode.set_enabled(True, NOW)
    for event in (
        replace(motion(), signal_type="interaction"),
        replace(motion(), entity_id="event.fake_motion"),
        motion(NOW + timedelta(seconds=1)),
        motion(NOW - timedelta(seconds=1)),
    ):
        mode.observe(event, NOW)
    assert not mode.held_zones
    mode.observe(motion(NOW + timedelta(seconds=2), "off"), NOW + timedelta(seconds=2))
    mode.observe(motion(NOW + timedelta(seconds=1)), NOW + timedelta(seconds=2))
    assert not mode.held_zones
    mode.sample((motion(NOW + timedelta(seconds=3)),), NOW + timedelta(seconds=3))
    mode.set_enabled(False, NOW + timedelta(seconds=4))
    deadline = mode.exit_at
    mode.set_enabled(False, NOW + timedelta(seconds=10))
    assert mode.exit_at == deadline
    mode.set_enabled(True, NOW + timedelta(seconds=11))
    assert mode.exit_at is None and mode.held_zones == {"office"}
    assert not mode.expire(NOW + timedelta(hours=1))
    empty = VisitorsMode(("office",))
    empty.set_enabled(True, NOW)
    empty.set_enabled(False, NOW)
    assert empty.exit_at is None


@pytest.mark.parametrize("count", [0, 1, 2])
def test_count_independent_public_hold_and_normal_mode_inverse(count: int) -> None:
    with RuntimeScenario(NOW) as scenario:
        guest = scenario.create(make_map(), count)
        control = scenario.create(make_map(), count)
        asyncio.run(guest.runtime.async_set_visitors_mode(True))
        for offset, state in ((0, "on"), (1, "off"), (2, "unavailable")):
            for replay in (guest, control):
                replay.send(
                    "binary_sensor.office", state, NOW + timedelta(seconds=offset)
                )
        guest.advance(NOW + timedelta(minutes=1))
        assert guest.latest == {"hall": False, "kitchen": False, "office": True}
        assert not control.latest["office"]
        assert guest.inference_snapshot() == control.inference_snapshot()
        home = scenario.binary_module.HomeActiveSensor(guest.runtime, "entry")
        assert home.is_on
        assert home.extra_state_attributes["active_zones"] == ["office"]
        asyncio.run(guest.runtime.async_set_visitors_mode(False))
        assert guest.attributes["office"]["reason"] == "visitors_exit_grace"
        guest.advance(NOW + timedelta(seconds=90))
        assert not home.is_on
        assert not guest.latest["office"]


def test_enable_samples_asserted_sensors_and_preserves_normal_active() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(
            make_map(),
            1,
            initial_states={
                "binary_sensor.office": "on",
                "binary_sensor.hall": "off",
            },
        )
        assert not replay.latest["office"]
        asyncio.run(replay.runtime.async_set_visitors_mode(True))
        assert replay.latest["office"]
        replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.send("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
        assert replay.latest["kitchen"]
        replay.send("sensor.replay_people", "0", NOW + timedelta(seconds=3))
        assert replay.runtime.expected_occupants == 0
        assert not any(
            policy.active for policy in replay.runtime.confidence.policy_states.values()
        )
        assert replay.latest["office"] and replay.latest["kitchen"]


@pytest.mark.parametrize("grace", [False, True])
@pytest.mark.parametrize("valid_inference", [False, True])
def test_fresh_runtime_restore_before_start_preserves_manual_control(
    grace: bool,
    valid_inference: bool,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(make_map(), 0)
        asyncio.run(replay.runtime.async_set_visitors_mode(True))
        replay.send("binary_sensor.office", "on", NOW)
        replay.send("binary_sensor.office", "off", NOW + timedelta(seconds=1))
        if grace:
            asyncio.run(replay.runtime.async_set_visitors_mode(False))
        payload = replay.checkpoint()
        if not valid_inference:
            payload["schema"] = "unsupported"
        replay.close()
        fresh = scenario.runtime_module.PredictiveControlsRuntime(
            replay.hass,
            make_map(),
            (),
            30,
            expected_occupants=0,
        )
        writes: list[bool] = []
        entity = scenario.binary_module.ZoneActiveSensor(fresh, "fresh", "office")
        entity.hass = replay.hass
        scenario.patch.setattr(
            entity, "async_write_ha_state", lambda: writes.append(bool(entity.is_on))
        )
        try:
            assert (
                fresh.restore_stored_state(payload, scenario.clock.now)
                is valid_inference
            )
            asyncio.run(entity.async_added_to_hass())
            fresh.start()
            assert entity.is_on
            scenario.clock.advance(NOW + timedelta(seconds=30))
            assert entity.is_on
            scenario.clock.advance(NOW + timedelta(seconds=31))
            assert entity.is_on is (not grace)
            if grace:
                assert writes[-1] is False
        finally:
            asyncio.run(fresh.async_stop())
            for remove in entity.remove_callbacks:
                remove()


@pytest.mark.parametrize("manual", [
    record(enabled="on"),
    record(held_zones=["office"], exit_at="0001-01-01T00:00:00+01:00"),
])
def test_manual_restore_rejection_does_not_reject_inference(
    caplog: pytest.LogCaptureFixture,
    manual: dict[str, object],
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(make_map(), 1)
        payload = replay.checkpoint()
        payload["visitors_mode"] = manual
        assert replay.runtime.restore_stored_state(payload, NOW)
        assert not replay.runtime.visitors.enabled
        assert "Rejected stored Visitors mode" in caplog.text
        payload.pop("visitors_mode")
        assert replay.runtime.restore_stored_state(payload, NOW)
        assert not replay.runtime.visitors.enabled


@pytest.mark.parametrize("enable_first", [False, True])
def test_normal_policy_activity_joins_visitors_without_motion(
    enable_first: bool,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(interaction_map(), 1)
        store = RecordingStore()
        replay.runtime._transition_store = store
        if enable_first:
            asyncio.run(replay.runtime.async_set_visitors_mode(True))
        replay.send("event.bathroom_scene_002", NOW.isoformat(), NOW)
        assert replay.runtime.confidence.policy_states["bathroom"].active
        if not enable_first:
            asyncio.run(replay.runtime.async_set_visitors_mode(True))
        assert replay.runtime.visitors.held_zones == {"bathroom"}
        replay.send("sensor.replay_people", "0", NOW + timedelta(seconds=1))
        assert not replay.runtime.confidence.policy_states["bathroom"].active
        assert replay.latest["bathroom"]
        assert store.delayed


def test_canceled_grace_callback_cannot_clear_reenabled_mode() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(make_map(), 0)
        asyncio.run(replay.runtime.async_set_visitors_mode(True))
        replay.send("binary_sensor.office", "on", NOW)
        asyncio.run(replay.runtime.async_set_visitors_mode(False))
        assert scenario.clock.pending_count == 4
        old_callback = replay.runtime._async_visitors_deadline
        asyncio.run(replay.runtime.async_set_visitors_mode(True))
        assert scenario.clock.pending_count == 3
        old_callback(NOW)
        replay.advance(NOW + timedelta(seconds=30))
        assert replay.runtime.visitors.enabled and replay.latest["office"]


class RecordingStore:
    def __init__(self) -> None:
        self.fail = False
        self.saved: list[dict[str, object]] = []
        self.delayed: list[Callable[[], dict[str, object]]] = []

    async def async_save(self, payload: dict[str, object]) -> None:
        if self.fail:
            raise OSError("save failed")
        self.saved.append(payload)

    def async_delay_save(
        self, producer: Callable[[], dict[str, object]], _delay: int
    ) -> None:
        self.delayed.append(producer)


def test_native_switch_lifecycle_save_failure_and_retry() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(
            make_map(), 1, initial_states={"binary_sensor.office": "on"}
        )
        store = RecordingStore()
        replay.runtime._transition_store = store
        switch_module = scenario._load_leaf("switch")
        scenario.patch.setattr(
            switch_module, "async_dispatcher_connect", scenario._connect
        )
        replay.hass.data[DOMAIN] = {"entry": replay.runtime}
        entities: list[object] = []
        asyncio.run(
            switch_module.async_setup_entry(
                replay.hass,
                SimpleNamespace(entry_id="entry"),
                entities.extend,
            )
        )
        assert len(entities) == 1
        switch = switch_module.VisitorsModeSwitch(replay.runtime, "entry")
        switch.hass = replay.hass
        assert switch.unique_id == "entry_visitors_mode"
        assert not switch.is_on
        asyncio.run(switch.async_added_to_hass())
        switch._handle_update()
        assert getattr(switch, "state_write_count", 0) == 0
        store.fail = True
        with pytest.raises(OSError, match="save failed"):
            asyncio.run(switch.async_turn_on())
        assert switch.is_on and replay.latest["office"]
        store.fail = False
        asyncio.run(switch.async_turn_on())
        assert store.saved[-1]["visitors_mode"] == switch.extra_state_attributes
        assert switch.state_write_count == 1
        asyncio.run(switch.async_turn_off())
        deadline = replay.runtime.visitors.exit_at
        assert not switch.is_on
        asyncio.run(switch.async_turn_off())
        assert replay.runtime.visitors.exit_at == deadline
        replay.advance(NOW + timedelta(seconds=30))
        assert not replay.latest["office"]
        assert store.delayed
        assert "visitors_mode" not in store.delayed[-1]()
        assert switch.extra_state_attributes == record()
        assert switch.state_write_count == 3
        for remove in switch.remove_callbacks:
            remove()
