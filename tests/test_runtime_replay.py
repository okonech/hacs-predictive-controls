"""Qualify fake scheduling independently of the incident acceptance outcomes."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, FakeClock, RuntimeScenario
from tests.test_prediction import make_map as prediction_map
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_clock_order_cancel_repeat_and_zero_delay() -> None:
    clock = FakeClock(NOW)
    calls: list[tuple[str, datetime]] = []

    def first(at: datetime) -> None:
        calls.append(("first", at))
        cancel_other()
        clock.schedule(timedelta(0), lambda at: calls.append(("zero", at)))

    clock.schedule(timedelta(seconds=5), first)
    cancel_other = clock.schedule(
        timedelta(seconds=5), lambda at: calls.append(("canceled", at)),
    )
    cancel_repeat = clock.schedule(
        timedelta(seconds=5), lambda at: calls.append(("repeat", at)),
        interval=timedelta(seconds=5),
    )
    clock.advance(NOW + timedelta(seconds=10))
    assert calls == [
        ("first", NOW + timedelta(seconds=5)),
        ("repeat", NOW + timedelta(seconds=5)),
        ("zero", NOW + timedelta(seconds=5)),
        ("repeat", NOW + timedelta(seconds=10)),
    ]
    cancel_repeat()
    clock.advance(NOW + timedelta(seconds=20))
    assert clock.pending_count == 0
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="duration"):
        clock.schedule(timedelta(seconds=-1), first)
    with pytest.raises(ValueError, match="duration"):
        clock.schedule(timedelta(0), first, interval=timedelta(0))


def test_clock_rejects_runaway_zero_delay_work() -> None:
    clock = FakeClock(NOW)

    def repeat(_at: datetime) -> None:
        clock.schedule(timedelta(0), repeat)

    clock.schedule(timedelta(0), repeat)
    with pytest.raises(RuntimeError, match="callback limit"):
        clock.advance(NOW, callback_limit=10)


def test_runtime_publication_timers_and_read_only_checkpoints() -> None:
    """PATH002: timers publish retention, never invent departure without movement."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        baseline = replay.inference_snapshot()
        assert all(state.generation == 0 for state in baseline.episode_states)
        assert all(state.last_event_at is None for state in baseline.episode_states)
        assert not replay.edges
        assert scenario.clock.pending_count == 3
        replay.send("binary_sensor.hall", "on", NOW)
        acquired_at = NOW + timedelta(seconds=2)
        assert replay.send("binary_sensor.room", "on", acquired_at).active("room")
        edges = replay.edges_for("room")
        assert edges == (ActiveEdge(acquired_at, "room", True),)
        acquired, = tuple(write for write in replay.writes_for("room") if write.active)
        assert acquired.phase == "input"
        assert acquired.attributes["reason"] == "acquired"
        assert acquired.attributes["activation_provenance"] == "evidence"
        assert acquired.attributes["track_confidence"] == "provisional"
        assert acquired.attributes["evidence_ids"]
        replay.send("binary_sensor.room", "on", acquired_at)  # Duplicate callback.
        assert replay.edges_for("room") == edges
        replay.send("binary_sensor.room", "off", NOW + timedelta(seconds=3))
        writes = replay.write_count
        replay.advance(NOW + timedelta(seconds=4))
        assert replay.write_count == writes  # No due callback: no forced evaluation.
        assert replay.advance(NOW + timedelta(minutes=12)).active("room")
        assert replay.edges_for("room") == edges
        assert replay.input_edges_for("room") == edges
        retained = replay.writes_for("room")[-1]
        assert retained.at == NOW + timedelta(minutes=12)
        assert retained.phase == "timer" and retained.active
        assert retained.attributes["reason"] == "retained_endpoint_hold"
        assert retained.attributes["activation_provenance"] == "evidence"
        names = [name for _, name in scenario.clock.executions]
        assert names.count("_async_expire_transient_state") == 144
        assert names.count("_async_refresh_active_confidence") == 12
        assert names.count("_async_publish_diagnostics") == 24
    assert scenario.clock.pending_count == 0
    assert not replay.hass.listeners
    assert not any(replay.hass.dispatchers.values())


def test_real_count_listener_and_same_time_timer_order() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        replay.send("binary_sensor.hall", "on", NOW)
        replay.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        assert not replay.send(
            "sensor.replay_people", "0", NOW + timedelta(seconds=5),
        ).active("room")
        assert scenario.clock.executions[0] == (
            NOW + timedelta(seconds=5), "_async_expire_transient_state",
        )
        assert replay.runtime.expected_occupants == 0
        assert replay.edges_for("room")[-1].at == NOW + timedelta(seconds=5)


def test_native_normalization_and_explicit_retained_reliability() -> None:
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        "a": {"entities": {"motion": "binary_sensor.a"}, "initial_weight": 0.7},
    }})
    with RuntimeScenario(NOW) as scenario:
        native = scenario.create(predictive_map, 1)
        retained = scenario.create(predictive_map, 1)
        native.send("binary_sensor.a", "on", NOW)
        event = SensorInput("binary_sensor.a", "on", NOW)
        retained.observe(event)
        assert native.normalized_inputs[0].reliability == 0.7
        assert retained.normalized_inputs == [event]
        assert native.map == retained.map


def test_occurrence_and_receipt_time_are_separate() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        event = SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.observe(event, processing_at=NOW + timedelta(seconds=2))
        assert replay.normalized_inputs == [event]
        assert replay.runtime.latency_metrics["event_loop_delay_last_ms"] == 1000
        with pytest.raises(ValueError, match="after receipt"):
            replay.send("binary_sensor.hall", "off", NOW + timedelta(seconds=4),
                        processing_at=NOW + timedelta(seconds=3))


def test_rejected_input_never_duplicates_previous_normalized_event() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        replay.send("binary_sensor.hall", "on", NOW)
        before = list(replay.normalized_inputs)
        replay.send("binary_sensor.hall", "invalid", NOW + timedelta(seconds=1))
        assert replay.normalized_inputs == before
        assert len(before) == 1


def test_public_oracle_does_not_read_unpublished_model_state() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        scenario.patch.setattr(
            replay.entities["room"], "async_write_ha_state", lambda: None,
        )
        replay.send("binary_sensor.hall", "on", NOW)
        published = replay.send(
            "binary_sensor.room", "on", NOW + timedelta(seconds=2),
        )
        assert replay.runtime.confidence.policy_states["room"].active
        assert not published.active("room")
        assert not replay.edges_for("room")


def test_real_prediction_one_shot_and_cancellation() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(prediction_map(), 1)
        # Explicit prelearned prediction fixture, never incident sensor evidence.
        for _ in range(5):
            replay.runtime.chain.observe("kitchen", "living")
        replay.send("binary_sensor.office", "on", NOW)
        replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.send("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
        assert replay.view().active("living")
        assert replay.advance(NOW + timedelta(seconds=11)).active("living")
        assert not replay.advance(NOW + timedelta(seconds=12)).active("living")
        assert replay.edges_for("living")[-1] == ActiveEdge(
            NOW + timedelta(seconds=12), "living", False,
        )
        assert sum(
            name == "_async_prediction_deadline"
            for _, name in scenario.clock.executions
        ) == 1
        assert scenario.clock.pending_count == 3


def test_inference_restore_preserves_timer_phase_and_continuation() -> None:
    """PUBLIC002: receiver synchronization is not replay of a physical acquisition."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(target_map(), 1)
        restored = scenario.create(target_map(), 1)
        for entity, state, seconds in (
            ("hall", "on", 0), ("room", "on", 2), ("room", "off", 3),
        ):
            live.send(f"binary_sensor.{entity}", state,
                      NOW + timedelta(seconds=seconds))
        # Destination has different inference; a successful no-op must fail.
        assert live.checkpoint()["snapshot"] != restored.checkpoint()["snapshot"]
        initial, = restored.writes_for("room")
        assert initial.phase == "initial" and not initial.active
        writes_before_restore = restored.writes
        restored.restore(live.checkpoint())
        assert live.checkpoint()["snapshot"] == restored.checkpoint()["snapshot"]
        assert restored.writes == writes_before_restore  # Restore does not dispatch.
        assert restored.runtime.confidence.policy_events == ()
        assert scenario.clock.pending_count == 6  # Original timer phases survive.
        live.advance(NOW + timedelta(minutes=12))
        assert live.view() == restored.view()
        assert live.view().active("room")
        assert live.edges_for("room") == (
            ActiveEdge(NOW + timedelta(seconds=2), "room", True),
        )
        assert restored.edges_for("room") == (
            ActiveEdge(NOW + timedelta(seconds=10), "room", True),
        )
        synchronized = restored.writes_for("room")[1]
        assert synchronized.at == NOW + timedelta(seconds=10)
        assert synchronized.phase == "timer" and synchronized.active
        assert synchronized.attributes["reason"] == "retained_endpoint_hold"
        assert synchronized.attributes["activation_provenance"] == "evidence"
        assert restored.input_edges_for("room") == ()
        assert restored.normalized_inputs == []
        assert restored.deliveries == ()
        assert restored.runtime.confidence.policy_events == ()
        for name, count in (
            ("_async_expire_transient_state", 288),
            ("_async_refresh_active_confidence", 24),
            ("_async_publish_diagnostics", 48),
        ):
            frontiers = [at for at, callback in scenario.clock.executions
                         if callback == name]
            assert len(frontiers) == count
            assert frontiers[::2] == frontiers[1::2]  # Both original timer phases.
        assert live.checkpoint()["snapshot"] == restored.checkpoint()["snapshot"]


def test_module_and_listener_cleanup_after_failure() -> None:
    parent = importlib.import_module("custom_components.predictive_controls")
    missing = object()
    names = ("runtime", "binary_sensor")
    modules = {name: sys.modules.get(f"{parent.__name__}.{name}", missing)
               for name in names}
    attributes = {name: getattr(parent, name, missing) for name in names}
    with pytest.raises(AssertionError, match="intentional"):
        with RuntimeScenario(NOW) as scenario:
            replay = scenario.create(target_map(), 1)
            raise AssertionError("intentional")
    assert scenario.clock.pending_count == 0
    assert not replay.hass.listeners
    for name in names:
        assert sys.modules.get(f"{parent.__name__}.{name}", missing) is modules[name]
        assert getattr(parent, name, missing) is attributes[name]
