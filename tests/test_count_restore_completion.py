"""Synthetic count/restore proofs from selected-path-completion, 2026-09-13.

Expected: distinct observed count changes commit together with facade state;
count zero clears only physical inference cadence; backward wire restore rejects.
Observed source defects: reused count ID, preacceptance config mutation, missing
cadence reset, and a wire reader bypassing the existing backward-time guard.
These are local runtime/component controls, not newly captured lighting incidents.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from custom_components.predictive_controls.const import DISPATCH_UPDATE
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import OccupancyTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
    ZoneModelResult,
)
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
PEOPLE = "sensor.replay_people"


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def model(*, alias: bool = False) -> PredictiveMap:
    adjacent = {"a": ["b"], "b": ["a", "c"], "c": ["b", "t"], "t": ["c"]}
    return PredictiveMap.from_mapping({"nodes": {
        node: {"zone": node, "entities": {
            "mmwave": f"binary_sensor.{node}",
            **({"presence": "binary_sensor.a_alias"} if alias and node == "a" else {}),
        }, "adjacent": neighbors}
        for node, neighbors in adjacent.items()
    }})


def observe(engine: ZoneModelEngine, node: str, value: str, seconds: float) -> None:
    engine.observe(SensorInput(f"binary_sensor.{node}", value, at(seconds)))


def tracker_for(live: RuntimeReplay) -> OccupancyTracker:
    return cast(OccupancyTracker, live.runtime.confidence)


def engine_for(tracker: OccupancyTracker) -> ZoneModelEngine:
    assert tracker._engine is not None
    return tracker._engine


def deliver_count(
    live: RuntimeReplay, value: str, changed: datetime, received: datetime,
    *, install: bool = True,
) -> None:
    """Use the actual registered listener with HA-like stable last_changed."""
    live.advance(received)
    state = SimpleNamespace(state=value, last_changed=changed)
    event = SimpleNamespace(time_fired=received, data={
        "entity_id": PEOPLE, "new_state": state,
        "old_state": live.hass.values.get(PEOPLE),
    })
    if install:
        live.hass.values[PEOPLE] = state
    with live.scenario._publishing("input"):
        listeners = [fn for ids, fn in live.hass.listeners if PEOPLE in ids]
        assert len(listeners) == 1
        listeners[0](event)


def test_count_zero_clears_physical_cadence_without_new_generation() -> None:
    """COUNT001/EVID cadence: no fake OFF, new generation or observation time."""
    graph = model(alias=True)
    engine = ZoneModelEngine(graph, 2, NOW)
    observe(engine, "a_alias", "off", 0)
    observe(engine, "a", "on", 0)
    observe(engine, "a", "off", 20)
    engine.advance(at(30))
    observe(engine, "a", "on", 60)
    engine.advance(at(61))
    before = engine.snapshot.episode_states
    assert before[0].cadence_correlated
    health = engine.snapshot.path_health
    warnings = engine.snapshot.reliability_warning_occurrences
    result = engine.observe_count(CountInput("zero", 0, True, at(61)))
    expected = tuple(replace(
        item, cadence_run_started_at=None, cadence_last_transition_at=None,
        cadence_cycle_count=0, cadence_correlated=False, cadence_warning=False,
        cadence_warning_reason=None,
    ) for item in before)
    assert result.snapshot.episode_states == expected
    assert result.snapshot.path_health == health
    assert result.snapshot.reliability_warning_occurrences == warnings
    assert not result.snapshot.selected_paths
    assert not result.policy_events
    assert restore_target_state(graph, serialize_target_state(graph, engine), at(61))


@pytest.mark.parametrize("offset", (-1, 0, 1))
def test_wire_restore_frontier_and_nonempty_runtime_atomicity(offset: int) -> None:
    """STATE001/003: the wire API must enforce the existing engine frontier."""
    graph = model()
    source = ZoneModelEngine(graph, 2, NOW)
    observe(source, "a", "on", 0)
    observe(source, "b", "on", 1)
    source.advance(at(2))
    payload = serialize_target_state(graph, source)
    original = deepcopy(payload)
    requested = at(2) + timedelta(microseconds=offset)
    if offset < 0:
        with pytest.raises(ValueError, match="predates stored state"):
            restore_target_state(graph, payload, requested)
    else:
        restored = restore_target_state(graph, payload, requested)
        if offset > 0:
            source.advance(requested, emit_events=False)
        assert serialize_target_state(graph, restored) == serialize_target_state(
            graph, source,
        )
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(graph, 1)
        live.send("binary_sensor.c", "on", NOW)
        live.send("binary_sensor.t", "on", at(1))
        tracker = tracker_for(live)
        before_engine = engine_for(tracker)
        before = live.checkpoint()
        writes = live.writes
        config = tracker.config
        assert live.runtime.restore_stored_state(payload, requested) is (offset >= 0)
        if offset < 0:
            assert engine_for(tracker) is before_engine
            assert live.checkpoint() == before
            assert tracker.config == config
        assert live.writes == writes  # Restore itself does not publish an edge.
    assert payload == original


def test_runtime_listener_distinct_counts_and_public_zero_recovery() -> None:
    """COUNT001/002/006: actual listener 2->1->0->2, not direct facade calls."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        live.send("binary_sensor.a", "on", NOW)
        live.send("binary_sensor.b", "on", at(1))
        assert live.view().active("b")
        tracker = tracker_for(live)
        accepted: list[str | None] = []
        for value, seconds in ((1, 2), (0, 3), (2, 4)):
            deliver_count(live, str(value), at(seconds), at(seconds))
            state = engine_for(tracker).snapshot.count_state
            assert state.expected_count == value
            assert tracker.config.expected_occupants == value
            assert tracker.requested_expected_occupants == value
            assert state.last_event_at == at(seconds)
            accepted.append(state.last_event_id)
        assert len(set(accepted)) == 3
        assert live.edges_for("b") == (
            ActiveEdge(at(1), "b", True), ActiveEdge(at(3), "b", False),
        )
        assert not any(live.latest.values())
        assert len(engine_for(tracker).snapshot.selected_paths) == 2


@pytest.mark.parametrize("rejected", (
    "stale", "same_time", "duplicate", "invalid_time",
))
def test_facade_rejected_count_does_not_change_effective_configuration(
    rejected: str,
) -> None:
    tracker = OccupancyTracker(model(), expected_occupants=2)
    tracker.ensure_state(NOW)
    tracker.reconcile_expected_occupants(1, at(2), evidence_id="one")
    engine = engine_for(tracker)
    before = engine.snapshot
    config = tracker.config
    if rejected == "invalid_time":
        with pytest.raises(ValueError):
            tracker.reconcile_expected_occupants(
                0, at(3), "zero", processing_at=at(2),
            )
        assert engine.snapshot == before
    else:
        frontier = at(1) if rejected == "stale" else at(2)
        evidence_id = "one" if rejected == "duplicate" else "zero"
        tracker.reconcile_expected_occupants(0, frontier, evidence_id=evidence_id)
        assert engine.snapshot.count_state.expected_count == 1
    assert tracker.config == config
    assert tracker.requested_expected_occupants == 1


@pytest.mark.parametrize("source", ("listener", "poll", "bootstrap"))
def test_count_identity_uses_observed_state_frontier_not_receipt(
    source: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[CountInput] = []
    original = ZoneModelEngine.observe_count

    def record(
        self: ZoneModelEngine, event: CountInput, *,
        processing_at: datetime | None = None,
    ) -> ZoneModelResult:
        captured.append(event)
        return original(self, event, processing_at=processing_at)

    monkeypatch.setattr(ZoneModelEngine, "observe_count", record)
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        if source == "listener":
            # The queued event, not a newer hass.states value, owns this input.
            deliver_count(live, "1", at(1), at(2), install=False)
        else:
            live.hass.values[PEOPLE] = SimpleNamespace(state="1", last_changed=at(1))
            scenario.clock.now = at(2)
            if source == "poll":
                live.runtime._async_refresh_active_confidence(at(2))
            else:
                # A separate runtime startup, with no test inference injection.
                runtime = scenario.runtime_module.PredictiveControlsRuntime(
                    live.hass, live.map, (), 30, expected_occupants=2,
                    expected_occupants_entity=PEOPLE,
                )
                runtime.start()
                asyncio.run(runtime.async_stop())
        assert len(captured) == 1
        assert captured[0].event_at == at(1)
        assert captured[0].value == 1
        assert at(1).isoformat() in captured[0].event_id


def test_zero_preserves_unfinished_sixth_real_cycle_and_warning_history() -> None:
    """HEALTH002/003: reset is not an OFF; only the actual sixth OFF warns."""
    graph = model(alias=True)
    engine = ZoneModelEngine(graph, 2, NOW)
    observe(engine, "a_alias", "off", 0)
    for start in range(0, 100, 20):
        observe(engine, "a", "on", start)
        observe(engine, "a", "off", start + 10)
    observe(engine, "a", "on", 100)
    engine.advance(at(105))
    health = engine.snapshot.path_health
    assert health[0].completed_cycles == tuple(at(s) for s in range(10, 100, 20))
    assert health[0].on_started_at == at(100)
    assert not engine.snapshot.reliability_warning_occurrences
    engine.observe_count(CountInput("zero", 0, True, at(105)))
    assert engine.snapshot.path_health == health
    assert not engine.snapshot.reliability_warning_occurrences
    observe(engine, "a", "off", 110)
    warnings = engine.snapshot.reliability_warning_occurrences
    assert len(warnings) == 1
    assert warnings[0].reason == "sustained_flapping"
    assert warnings[0].first_observed_at == at(110)
    assert warnings[0].cleared_at is None
    engine.observe_count(CountInput("two", 2, True, at(111)))
    engine.observe_count(CountInput("zero-again", 0, True, at(112)))
    retained = engine.snapshot.reliability_warning_occurrences[0]
    assert retained.first_observed_at == at(110)
    assert engine.snapshot.reliability_warning_occurrences[0].cleared_at is None
    payload = serialize_target_state(graph, engine)
    restored = restore_target_state(graph, payload, at(112))
    assert serialize_target_state(graph, restored) == payload


def test_zero_advances_real_due_unsupported_on_deadline_without_new_cycle() -> None:
    engine = ZoneModelEngine(model(), 2, NOW)
    observe(engine, "a", "on", 0)
    result = engine.observe_count(CountInput("zero", 0, True, at(600)))
    assert len(result.snapshot.reliability_warning_occurrences) == 1
    warning = result.snapshot.reliability_warning_occurrences[0]
    assert warning.reason == "assertion_timeout"
    assert warning.first_observed_at == at(600)
    assert result.snapshot.path_health[0].completed_cycles == ()
    assert result.snapshot.path_health[0].on_started_at == NOW


@pytest.mark.parametrize("invalid", ("stale", "same_time", "unavailable", "future"))
def test_runtime_rejected_controls_do_not_change_count_or_public_active(
    invalid: str,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        live.send("binary_sensor.a", "on", NOW)
        live.send("binary_sensor.b", "on", at(1))
        deliver_count(live, "1", at(2), at(2))
        tracker = tracker_for(live)
        accepted = engine_for(tracker).snapshot.count_state
        changed = {"stale": at(1), "same_time": at(2),
                   "unavailable": at(3), "future": at(4)}[invalid]
        value = "unavailable" if invalid == "unavailable" else "0"
        if invalid == "future":
            with pytest.raises(ValueError):
                deliver_count(live, value, changed, at(3))
        else:
            deliver_count(live, value, changed, at(3))
        state = engine_for(tracker).snapshot.count_state
        assert state.expected_count == accepted.expected_count
        assert state.last_event_id == accepted.last_event_id
        assert state.last_event_at == accepted.last_event_at
        assert tracker.config.expected_occupants == 1
        assert tracker.requested_expected_occupants == 1
        assert live.edges_for("b") == (ActiveEdge(at(1), "b", True),)


@pytest.mark.parametrize("timestamps", (False, True))
def test_listener_replay_and_poll_reuse_identity_even_after_restart(
    timestamps: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[CountInput] = []
    original = ZoneModelEngine.observe_count

    def record(
        self: ZoneModelEngine, event: CountInput, *,
        processing_at: datetime | None = None,
    ) -> ZoneModelResult:
        captured.append(event)
        return original(self, event, processing_at=processing_at)

    monkeypatch.setattr(ZoneModelEngine, "observe_count", record)
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        if timestamps:
            deliver_count(live, "1", at(1), at(1))
        else:
            live.send(PEOPLE, "1", at(1))
        first = captured[-1]
        payload = live.checkpoint()
        # The same observation through another runtime must have the same ID.
        other = scenario.create(model(), 2)
        other.hass.values[PEOPLE] = live.hass.values[PEOPLE]
        assert other.runtime.restore_stored_state(payload, at(1))
        assert engine_for(tracker_for(other)).snapshot.count_state.last_event_id == (
            first.event_id
        )
        if timestamps:
            deliver_count(live, "1", at(1), at(2))
        else:
            live.send(PEOPLE, "1", at(1), processing_at=at(2))
        live.runtime._sync_expected_occupants(at(2))
        after = engine_for(tracker_for(live)).snapshot.count_state
        assert after.diagnostics[0] == 1
        assert after.last_event_id == first.event_id
        assert after.last_event_at == at(1)
        # Persisted replay is still deduplicated at the engine boundary even if
        # its delivery frontier is later; changing processing time adds no evidence.
        engine = restore_target_state(live.map, payload, at(1))
        replayed = engine.observe_count(first, processing_at=at(2))
        assert replayed.disposition == "duplicate"
        assert replayed.snapshot.count_state.last_event_id == first.event_id


@pytest.mark.parametrize("fast", (False, True))
def test_runtime_count_and_facade_restore_reentry_are_atomic(fast: bool) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        live.send("binary_sensor.a", "on", NOW)
        tracker = tracker_for(live)
        payload = live.checkpoint()
        checked = 0

        def subscriber() -> None:
            nonlocal checked
            checked += 1
            engine = engine_for(tracker)
            snapshot = engine.snapshot
            config = tracker.config
            requested = tracker.requested_expected_occupants
            before_flags = (
                live.runtime._invalid_authoritative_count,
                live.runtime._restored_state, live.runtime._restore_rejected,
            )
            for operation in (
                lambda: live.runtime._sync_expected_occupants(at(1)),
                lambda: tracker.restore_state(payload, at(1)),
            ):
                with pytest.raises(ValueError, match="publication"):
                    operation()
                assert engine_for(tracker) is engine
                assert engine.snapshot == snapshot
                assert tracker.config == config
                assert tracker.requested_expected_occupants == requested
                assert before_flags == (live.runtime._invalid_authoritative_count,
                                        live.runtime._restored_state,
                                        live.runtime._restore_rejected)

        def publish() -> None:
            live.hass.values[PEOPLE] = SimpleNamespace(state="0", last_changed=at(1))
            live.runtime._publish_update()

        # Call the real dispatcher from inside a guarded committed projection.
        live.hass.dispatchers[DISPATCH_UPDATE].append(subscriber)
        if fast:
            event = SensorInput("binary_sensor.b", "on", at(1))
            engine_for(tracker).observe(event, decision_callback=lambda *_: publish())
        else:
            publish()
        assert checked


def test_fingerprint_rejection_precedes_backward_time_and_decode() -> None:
    graph = model()
    engine = ZoneModelEngine(graph, 2, NOW)
    payload = serialize_target_state(graph, engine)
    payload["map_fingerprint"] = "incompatible"
    payload["snapshot"] = None
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="fingerprint"):
        restore_target_state(graph, payload, NOW - timedelta(microseconds=1))
    assert payload == before


def predicted_engine() -> tuple[PredictiveMap, ZoneModelEngine]:
    """Authentic selected prediction with explicit mature learned route input."""
    graph = model()
    engine = ZoneModelEngine(graph, 2, NOW)
    for _ in range(5):
        assert engine.prediction_manager.chain.observe("c", "t")
    for node, seconds in (("a", 0), ("b", 1), ("c", 2)):
        observe(engine, node, "on", seconds)
    assert engine.snapshot.selected_prediction_grants
    assert engine.prediction_manager.leases
    assert next(p for p in engine.snapshot.policy_states if p.zone == "t").active
    return graph, engine


@pytest.mark.parametrize("seconds", (2, 11.999999, 12, 12.000001))
def test_wire_prediction_expiry_advances_once_without_relearning(
    seconds: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STATE003/007/009: half-open expiry, one advance, no renewal/likelihood."""
    graph, engine = predicted_engine()
    payload = serialize_target_state(graph, engine)
    before = deepcopy(payload)
    counts = engine.prediction_manager.chain.counts
    if seconds > 2:
        engine.advance(at(seconds), emit_events=False)
    calls: list[datetime] = []
    original = ZoneModelEngine.advance

    def record(
        self: ZoneModelEngine, frontier: datetime, *,
        processing_at: datetime | None = None, emit_events: bool = True,
    ) -> ZoneModelResult:
        calls.append(frontier)
        return original(
            self, frontier, processing_at=processing_at, emit_events=emit_events,
        )

    monkeypatch.setattr(ZoneModelEngine, "advance", record)
    restored = restore_target_state(graph, payload, at(seconds))
    assert calls == ([] if seconds == 2 else [at(seconds)])
    assert serialize_target_state(graph, restored) == serialize_target_state(
        graph, engine,
    )
    target = next(p for p in restored.snapshot.policy_states if p.zone == "t")
    assert target.active is (seconds < 12)
    assert bool(restored.prediction_manager.leases) is (seconds < 12)
    first = restored.advance(at(13))
    repeated = restored.advance(at(13))
    assert len(first.policy_events) == (1 if seconds < 12 else 0)
    assert not repeated.policy_events
    assert sum(row.zone == "t" and row.reason == "prediction_unconfirmed"
               for row in restored.audit_rows) == 1
    assert restored.prediction_manager.chain.counts == counts
    assert payload == before


def test_stored_expired_prediction_is_rejected_before_pruning_atomically() -> None:
    """STATE001: valid live proofs cannot be smuggled into an expired snapshot."""
    graph, engine = predicted_engine()
    live_payload = serialize_target_state(graph, engine)
    assert restore_target_state(graph, live_payload, at(2)).snapshot == engine.snapshot
    engine.advance(at(12), emit_events=False)
    payload = serialize_target_state(graph, engine)
    assert restore_target_state(graph, payload, at(12)).snapshot == engine.snapshot
    expired_snapshot = cast(dict[str, object], payload["snapshot"])
    live_snapshot = cast(dict[str, object], live_payload["snapshot"])
    expired_prediction = cast(dict[str, object], payload["prediction"])
    live_prediction = cast(dict[str, object], live_payload["prediction"])
    expired_snapshot["selected_prediction_grants"] = deepcopy(
        live_snapshot["selected_prediction_grants"],
    )
    expired_prediction["leases"] = deepcopy(live_prediction["leases"])
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="not bounded live proofs"):
        restore_target_state(graph, payload, at(13))
    with RuntimeScenario(NOW) as scenario:
        receiver = scenario.create(graph, 1)
        receiver.send("binary_sensor.a", "on", NOW)
        receiver.send("binary_sensor.b", "on", at(1))
        installed = engine_for(tracker_for(receiver))
        state = receiver.checkpoint()
        assert not receiver.runtime.restore_stored_state(payload, at(13))
        assert engine_for(tracker_for(receiver)) is installed
        assert receiver.checkpoint() == state
        assert payload == before
        receiver.send("binary_sensor.c", "on", at(2))
        assert receiver.view().active("c")


def test_backward_restore_never_constructs_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph, engine = predicted_engine()
    payload = serialize_target_state(graph, engine)

    def forbidden(*_args: object, **_kwargs: object) -> ZoneModelEngine:
        raise AssertionError("Backward input reached candidate construction")

    monkeypatch.setattr(ZoneModelEngine, "restore", forbidden)
    with pytest.raises(ValueError, match="predates stored state"):
        restore_target_state(graph, payload, at(2) - timedelta(microseconds=1))


def test_startup_offline_gap_differs_from_elapsed_inference_continuation() -> None:
    """HEALTH001/STATE003: actual restart cannot invent an offline ON warning."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        live.send("binary_sensor.a", "on", NOW)
        payload = live.checkpoint()
        live.close()
        scenario.clock.advance(at(601))
        continuation = restore_target_state(live.map, payload, at(601))
        warnings = continuation.snapshot.reliability_warning_occurrences
        assert len(warnings) == 1
        assert warnings[0].first_observed_at == at(600)
        restarted = scenario.runtime_module.PredictiveControlsRuntime(
            live.hass, live.map, (), 30, expected_occupants=2,
            expected_occupants_entity=PEOPLE,
        )
        try:
            assert restarted.restore_stored_state(payload, at(601))
            restarted.start()  # Actual current raw-state bootstrap after wire restore.
            tracker = cast(OccupancyTracker, restarted.confidence)
            assert not tracker.reliability_warning_occurrences
            health = engine_for(tracker).snapshot.path_health[0]
            assert health.on_started_at is None
            assert health.unsupported_started_at == at(601)
            tracker.expire_transient_state(at(1200))
            assert not tracker.reliability_warning_occurrences
            tracker.expire_transient_state(at(1201))
            warning = tracker.reliability_warning_occurrences[0]
            assert warning.first_observed_at == at(1201)
        finally:
            asyncio.run(restarted.async_stop())


def test_runtime_prediction_count_restart_write_timeline_is_factual() -> None:
    """COUNT001/PRED008: count0 clears an actual predicted ON, not a mock edge."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        for _ in range(5):
            assert live.runtime.chain.observe("c", "t")
        counts = deepcopy(live.runtime.chain.counts)
        for node, seconds in (("a", 0), ("b", 1), ("c", 2)):
            live.send(f"binary_sensor.{node}", "on", at(seconds))
        # Keep genuine initial and pre-acquisition OFF writes; count writes != edges.
        assert [(w.at, w.active, w.phase) for w in live.writes_for("t")] == [
            (NOW, False, "initial"), (NOW, False, "input"), (at(2), True, "input"),
        ]
        deliver_count(live, "1", at(3), at(3))
        deliver_count(live, "0", at(4), at(4))
        deliver_count(live, "2", at(4.5), at(4.5))
        assert [(w.at, w.active, w.attributes["reason"])
                for w in live.writes_for("t")[3:]] == [
            (at(3), True, "prediction_active"), (at(4), False, "count_zero"),
            (at(4.5), False, "inactive_below_on"),
        ]
        expected_edges = (ActiveEdge(at(2), "t", True), ActiveEdge(at(4), "t", False))
        assert live.edges_for("t") == expected_edges
        restored = scenario.create(live.map, 2)
        before_writes = restored.writes
        restored.restore(live.checkpoint())
        assert restored.writes == before_writes
        live.advance(at(13))
        assert live.edges_for("t") == expected_edges
        assert not restored.edges_for("t")
        for replay in (live, restored):
            assert not replay.view().active("t")
            assert replay.runtime.chain.counts == counts
            state = engine_for(tracker_for(replay)).snapshot
            assert not state.selected_prediction_grants
            assert state.count_state.expected_count == 2
            assert len(state.selected_paths) == 2


def test_same_timestamp_distinct_values_are_stale_not_identity_duplicates() -> None:
    """COUNT006: include value in identity, without accepting equal-time controls."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        deliver_count(live, "1", at(1), at(1))
        accepted = engine_for(tracker_for(live)).snapshot.count_state
        deliver_count(live, "0", at(1), at(1))
        state = engine_for(tracker_for(live)).snapshot.count_state
        assert state.diagnostics == (1, 0, 1, 0, 0)
        assert state.last_event_id == accepted.last_event_id
        assert len(state.seen_event_ids) == 2
        assert tracker_for(live).config.expected_occupants == 1


@pytest.mark.parametrize("recovered", (0, 1, 2))
def test_supported_count_recovers_unsupported_request_without_reapplying_evidence(
    recovered: int,
) -> None:
    """COUNT006: a valid repeated level clears unsupported-request diagnostics."""
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        deliver_count(live, "1", at(1), at(1))
        tracker = tracker_for(live)
        accepted = engine_for(tracker).snapshot.count_state
        deliver_count(live, "3", at(2), at(2))
        assert tracker.requested_expected_occupants == 3
        assert tracker.diagnostics.unsupported_count == 3
        assert tracker.config.expected_occupants == 1
        # An old value cannot clear the unsupported request; a current valid
        # same-value duplicate can reconcile diagnostics to the accepted count.
        deliver_count(live, "1", at(0.5), at(2))
        assert tracker.requested_expected_occupants == 3
        deliver_count(live, str(recovered), at(3), at(3))
        state = engine_for(tracker).snapshot.count_state
        assert state.expected_count == recovered
        assert tracker.config.expected_occupants == recovered
        assert tracker.requested_expected_occupants == recovered
        assert tracker.diagnostics.unsupported_count is None
        if recovered == 1:
            assert state.last_event_id == accepted.last_event_id
            assert state.last_event_at == accepted.last_event_at
            assert state.diagnostics[0] == accepted.diagnostics[0]
        assert not live.edges


