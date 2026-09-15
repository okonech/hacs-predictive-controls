"""Transport qualification, independent of frozen incident/model expectations.

Only raw inputs and real runtime timers drive inference. The explicit extra write
in the phase test qualifies transport capture, not an inference/publication rule.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from custom_components.predictive_controls.const import DISPATCH_DIAGNOSTIC_UPDATE
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeScenario
from tests.test_events import interaction_map
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_pressed_observation_uses_iso_transport_and_preserves_normalized_input(
    count: int,
) -> None:
    occurrence = NOW + timedelta(seconds=1)
    callback = NOW + timedelta(seconds=2)
    receipt = NOW + timedelta(seconds=3)
    retained = SensorInput("event.bathroom_scene_002", "pressed", occurrence)
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(interaction_map(), count)
        replay.observe(retained, processing_at=receipt)
        assert replay.normalized_inputs == [retained]
        (delivery,) = replay.deliveries
        assert delivery.raw_state == occurrence.isoformat()
        assert delivery.event_at == delivery.callback_at == occurrence
        assert delivery.processing_at == receipt
        assert delivery.normalized == delivery.retained_input == retained
        assert delivery.delivered and not delivery.is_count
        assert replay.view().active("bathroom") is (count > 0)
        assert replay.input_edges_for("bathroom") == (
            (ActiveEdge(receipt, "bathroom", True),) if count else ()
        )

        # Raw HA input can separate occurrence, state_changed time_fired and receipt.
        raw = scenario.create(interaction_map(), count)
        raw.send(
            retained.entity_id,
            occurrence.astimezone(timezone(timedelta(hours=2))).isoformat(),
            callback, processing_at=receipt, retained_input=retained,
        )
        assert raw.normalized_inputs == [retained]
        assert raw.deliveries[0].event_at == occurrence
        assert raw.deliveries[0].callback_at == callback
        assert raw.deliveries[0].processing_at == receipt


def test_normalizer_checks_retained_identity_and_keeps_effective_reliability() -> None:
    predictive_map = PredictiveMap.from_mapping({"nodes": {
        "a": {"entities": {"motion": "binary_sensor.a"}, "initial_weight": 0.7},
    }})
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(predictive_map, 1)
        replay.send("binary_sensor.a", "on", NOW)
        retained = SensorInput("binary_sensor.a", "off", NOW + timedelta(seconds=1))
        replay.observe(retained)
        assert [item.reliability for item in replay.normalized_inputs] == [0.7, 1.0]
        assert replay.deliveries[-1].normalized == retained
        with pytest.raises(AssertionError):
            replay.send("binary_sensor.a", "on", retained.event_at,
                        retained_input=retained)
        assert replay.deliveries[-1].raw_state == "on"
        # Failure must clear the compatibility override and publication phase.
        replay.send("binary_sensor.a", "off", NOW + timedelta(seconds=2))
        assert replay.normalized_inputs[-1].reliability == 0.7


def test_explicit_startup_raw_states_use_cold_bootstrap_not_live_observations() -> None:
    raw_states = {"binary_sensor.hall": "on", "binary_sensor.room": "off"}
    with RuntimeScenario(NOW) as scenario:
        legacy = scenario.create(target_map(), 1)
        raw = scenario.create(target_map(), 1, initial_states=raw_states)
        empty = scenario.create(target_map(), 1, initial_states={})
        raw_states["binary_sensor.hall"] = "off"
        assert raw.hass.states.get("binary_sensor.hall").state == "on"
        assert not raw.normalized_inputs and not raw.deliveries and not raw.edges
        assert not any(raw.view().active(zone) for zone in target_map().zones())
        assert all(write.phase == "initial" for write in raw.writes)
        assert not empty.edges and not empty.deliveries
        assert all(not write.active for write in empty.writes)
        # A retained raw ON is not a fresh observed path origin.
        for replay in (legacy, raw):
            replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        for replay in (legacy, raw):
            replay.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        assert legacy.view().active("room")
        assert not raw.view().active("room")


@pytest.mark.parametrize("startup_count", [0, 1])
def test_startup_event_timestamp_is_neutral_and_startup_count_is_raw(
    startup_count: int,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(interaction_map(), 1, initial_states={
            "event.bathroom_scene_002": (NOW - timedelta(seconds=1)).isoformat(),
            "sensor.replay_people": str(startup_count),
        })
        assert not replay.view().active("bathroom")
        assert not replay.deliveries and not replay.normalized_inputs
        replay.observe(SensorInput(
            "event.bathroom_scene_002", "pressed", NOW + timedelta(seconds=1),
        ))
        assert replay.view().active("bathroom") is (startup_count > 0)


@pytest.mark.parametrize("raw_state", [
    "pressed", "bad-date", "2026-09-01T00:00:01", "2026-09-01T00:00:10Z",
])
def test_delivery_ledger_retains_rejected_interactions_and_count(
    raw_state: str,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(interaction_map(), 1)
        replay.observe(SensorInput("event.bathroom_scene_002", "pressed", NOW))
        replay.send("event.bathroom_scene_002", raw_state,
                    NOW + timedelta(seconds=1),
                    processing_at=NOW + timedelta(seconds=2))
        replay.send("sensor.replay_people", "invalid", NOW + timedelta(seconds=2))
        replay.send("sensor.replay_people", "0", NOW + timedelta(seconds=3))
        assert len(replay.normalized_inputs) == 1
        assert len(replay.deliveries) == 4
        rejected = replay.deliveries[1]
        assert rejected.raw_state == raw_state
        assert rejected.delivered and not rejected.is_count
        assert rejected.normalized is None and rejected.event_at is None
        assert rejected.callback_at == NOW + timedelta(seconds=1)
        assert rejected.processing_at == NOW + timedelta(seconds=2)
        for delivery in replay.deliveries[2:]:
            assert delivery.is_count and delivery.delivered
            assert delivery.normalized is None
        assert not replay.view().active("bathroom")
        with pytest.raises(FrozenInstanceError):
            cast(Any, rejected).raw_state = "changed"
        with pytest.raises(ValueError, match="No runtime subscriber"):
            replay.send("binary_sensor.unmapped", "on", NOW + timedelta(seconds=3))
        assert not replay.deliveries[-1].delivered


def test_zone_snapshots_are_immutable_and_capture_unchanged_writes() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        baseline = replay.writes_for("room")
        assert len(baseline) == 1 and baseline[0].phase == "initial"
        replay.send("binary_sensor.hall", "on", NOW)
        replay.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        published = replay.writes_for("room")[-1]
        original = published.attributes
        exposed = published.attributes
        cast(list[str], exposed["evidence_ids"]).append("not evidence")
        exposed["reason"] = "changed"
        cast(list[str], replay.attributes["room"]["evidence_ids"]).clear()
        assert published.attributes == original
        with pytest.raises(FrozenInstanceError):
            cast(Any, published).active = False
        edges = replay.edges_for("room")
        writes = replay.write_count
        replay.entities["room"].async_write_ha_state()  # Capture-only duplicate write.
        assert replay.write_count == writes + 1
        assert replay.edges_for("room") == edges
        assert replay.writes_for("room")[-1].active
        assert published.attributes == original and len(baseline) == 1
        assert len(replay.writes) == replay.write_count
        assert [item.name for item in fields(ActiveEdge)] == ["at", "zone", "active"]


def test_timer_input_post_input_phases_and_shared_clock() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        other = scenario.create(target_map(), 1)
        for branch in (replay, other):
            branch.send("binary_sensor.hall", "on", NOW)
        for branch in (replay, other):
            branch.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        for branch in (replay, other):
            branch.send("binary_sensor.room", "off", NOW + timedelta(seconds=3))
        # The real stable-clear callback publishes at 10s; mere timer execution
        # at 5s is not itself a promise of a public write.
        at = NOW + timedelta(seconds=10)
        entity = replay.entities["room"]

        def defer_capture(_event: Any) -> None:
            scenario.clock.schedule(
                timedelta(0), lambda _at: entity.async_write_ha_state(),
            )

        # Extra HA transport listener schedules a same-value write, not inference.
        remove = scenario._listen(replay.hass, ["sensor.replay_people"], defer_capture)
        try:
            replay.send("sensor.replay_people", "0", at)
        finally:
            remove()
        writes = [write for write in replay.writes_for("room") if write.at == at]
        phases = [write.phase for write in writes]
        assert phases[0] == "timer"
        assert "input" in phases and phases[-1] == "post_input"
        assert phases == sorted(phases, key=["timer", "input", "post_input"].index)
        assert replay.input_edges_for("room")[-1] == ActiveEdge(at, "room", False)
        assert writes[-1].active is False  # Unchanged post-input write is retained.
        other_writes = [write for write in other.writes if write.at == at]
        assert other_writes and all(write.phase == "timer" for write in other_writes)
        assert other.view().active("room")
        assert not other.input_edges_for("room")[-1].at == at


def test_timer_publication_after_opaque_restore_is_not_an_input_edge() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(target_map(), 1)
        restored = scenario.create(target_map(), 1)
        live.send("binary_sensor.hall", "on", NOW)
        live.send("binary_sensor.room", "on", NOW + timedelta(seconds=2))
        live.send("binary_sensor.room", "off", NOW + timedelta(seconds=3))
        restored.restore(live.checkpoint())
        assert not restored.view().active("room")  # Restore itself does not publish.
        assert not restored.writes_for("room")[-1].active
        restored.advance(NOW + timedelta(seconds=10))
        assert restored.view().active("room")
        assert restored.edges_for("room")
        assert not restored.input_edges_for("room")
        assert all(write.phase == "timer" for write in restored.writes_for("room")
                   if write.active)


def test_reliability_sampling_has_no_forced_baseline_or_rephasing() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        replay.advance(NOW + timedelta(seconds=7))
        assert replay.watch_reliability() is replay
        replay.watch_reliability()  # Idempotent subscription, not a new timer.
        assert scenario.clock.pending_count == 3
        assert len(replay.hass.dispatchers[DISPATCH_DIAGNOSTIC_UPDATE]) == 1
        assert not replay.reliability_writes
        assert replay.reliability_attributes is None
        replay.advance(NOW + timedelta(seconds=29))
        assert replay.reliability_attributes is None
        replay.advance(NOW + timedelta(seconds=30))
        (first,) = replay.reliability_writes
        assert first.at == NOW + timedelta(seconds=30) and first.value == 0
        assert first.attributes["warnings"] == []
        assert first.attributes["active_count"] == 0
        replay.advance(NOW + timedelta(seconds=60))
        assert [write.at for write in replay.reliability_writes] == [
            NOW + timedelta(seconds=30), NOW + timedelta(seconds=60),
        ]


def test_reliability_captures_sampled_active_and_cleared_history_immutably() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1).watch_reliability()
        replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.advance(NOW + timedelta(seconds=600))
        assert replay.reliability_writes[-1].value == 0
        replay.advance(NOW + timedelta(seconds=630))
        active = replay.reliability_writes[-1]
        assert active.value == 1 and active.attributes["active_count"] == 1
        rows = cast(list[dict[str, object]], active.attributes["warnings"])
        assert rows[0]["node_id"] == "hall"
        assert rows[0]["first_observed_at"] == (
            NOW + timedelta(seconds=601)
        ).isoformat()
        assert rows[0]["last_observed_at"] == (
            NOW + timedelta(seconds=630)
        ).isoformat()
        assert rows[0]["cleared_at"] is None
        replay.send("binary_sensor.hall", "off", NOW + timedelta(seconds=631))
        assert replay.reliability_writes[-1] == active  # No immediate diagnostic write.
        replay.advance(NOW + timedelta(seconds=660))
        cleared = replay.reliability_writes[-1]
        assert cleared.value == 1  # Native value counts history, not just active rows.
        assert cleared.attributes["active_count"] == 0
        cleared_rows = cast(list[dict[str, object]], cleared.attributes["warnings"])
        assert cleared_rows[0]["node_id"] == rows[0]["node_id"]
        assert cleared_rows[0]["cleared_at"] == (
            NOW + timedelta(seconds=631)
        ).isoformat()
        assert cleared_rows[0]["last_observed_at"] == cleared_rows[0]["cleared_at"]
        cleared_rows[0]["node_id"] = "changed"
        cast(list[object], cleared_rows[0]["reasons"]).clear()
        latest = replay.reliability_attributes
        assert latest is not None
        cast(list[object], latest["warnings"]).clear()
        assert replay.reliability_attributes == cleared.attributes
        assert active.attributes["active_count"] == 1
        with pytest.raises(FrozenInstanceError):
            cast(Any, cleared).value = 0


def test_reliability_oracle_never_reads_unpublished_properties() -> None:
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1).watch_reliability()
        entity = replay._reliability_entity
        assert isinstance(
            entity, scenario.sensor_module.PredictiveControlsReliabilityWarningsSensor,
        )
        scenario.patch.setattr(entity, "async_write_ha_state", lambda: None)
        replay.send("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
        replay.advance(NOW + timedelta(seconds=630))
        assert replay.reliability_attributes is None
        assert replay.reliability_writes == ()


def test_optional_sensor_cleanup_and_clock_modules_survive_failure() -> None:
    parent = importlib.import_module("custom_components.predictive_controls")
    tracker = importlib.import_module(f"{parent.__name__}.occupancy_tracker")
    original_datetime = tracker.datetime
    missing = object()
    leaves = ("runtime", "binary_sensor", "sensor")
    modules = {name: sys.modules.get(f"{parent.__name__}.{name}", missing)
               for name in leaves}
    attributes = {name: getattr(parent, name, missing) for name in leaves}
    with pytest.raises(RuntimeError, match="intentional"):
        with RuntimeScenario(NOW) as scenario:
            replay = scenario.create(target_map(), 1).watch_reliability()
            assert scenario.sensor_module.datetime.now(UTC) == NOW
            replay.advance(NOW + timedelta(seconds=30))
            captured = replay.reliability_writes
            raise RuntimeError("intentional")
    assert scenario.clock.pending_count == 0
    assert not replay.hass.listeners
    assert not any(replay.hass.dispatchers.values())
    replay.close()  # Idempotent, including the optional sensor.
    with pytest.raises(ValueError, match="closed"):
        replay.watch_reliability()
    scenario.clock.advance(NOW + timedelta(seconds=90))
    assert replay.reliability_writes == captured
    assert tracker.datetime is original_datetime
    for name in leaves:
        assert sys.modules.get(f"{parent.__name__}.{name}", missing) is modules[name]
        assert getattr(parent, name, missing) is attributes[name]
