"""Synthetic runtime/wire completion contracts, not physical incident replays.

Source: 2026-09-14 delegated coverage completion and completion-runtime-wire.
Expected: failed publication/drain retains accepted state, deadlines and lazy
saving; malformed bounded wire records reject atomically. Qualification uses
actual observations or explicitly labeled, strictly accepted component records.
No existing scenario/replay harness or production state injection is used.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Self, TypeGuard

import pytest

from custom_components.predictive_controls.const import DISPATCH_UPDATE
from custom_components.predictive_controls.events import event_from_entity
from custom_components.predictive_controls.markov import MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import OccupancyTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.prediction import (
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SelectedPredictionGrant,
    SensorInput,
)
from tests.test_entity_platforms import install_fake_homeassistant
from tests.test_learning_publication_completion import _pending as accepted_pending
from tests.test_zone_model_persistence import structural_payload

if TYPE_CHECKING:
    from custom_components.predictive_controls.runtime import PredictiveControlsRuntime

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _sensor(node: str, state: str, seconds: float) -> SensorInput:
    return SensorInput(f"binary_sensor.{node}", state, _at(seconds))


def _graph(targets: int = 2) -> PredictiveMap:
    adjacent = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
    for index in range(targets):
        target = f"t{index:02}"
        adjacent[target] = ["c"]
        adjacent["c"].append(target)
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "zone": node, "role": "room_occupancy",
            "occupancy_behavior": "sustained",
            "entities": {"motion": f"binary_sensor.{node}"},
            "adjacent": neighbors,
        }
        for node, neighbors in adjacent.items()
    }})


def _strict(model: PredictiveMap, engine: ZoneModelEngine) -> dict[str, object]:
    payload = serialize_target_state(model, engine)
    original = deepcopy(payload)
    restored = restore_target_state(model, payload, engine.snapshot.updated_at)
    assert serialize_target_state(model, restored) == payload == original
    return payload


def _issued(
    *, targets: int = 2, support: int = 30, suppress_last: bool = False,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    """Actual selected issuance; learned counts are explicit statistical inputs."""
    model = _graph(targets)
    engine = ZoneModelEngine(model, 2, NOW)
    for _ in range(support):
        assert engine.prediction_manager.chain.observe("c", "t00")
    engine.observe(_sensor("a", "on", 0))
    engine.observe(_sensor("b", "on", 1))
    if suppress_last:
        engine.observe(_sensor(f"t{targets - 1:02}", "unavailable", 1.5))
    engine.observe(_sensor("c", "on", 2))
    assert engine.snapshot.selected_prediction_grants
    assert engine.snapshot.selected_prediction_grants == (
        engine.prediction_manager.grants
    )
    _strict(model, engine)
    return model, engine


def _is_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    assert _is_mapping(value)
    return value


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _rows(value: object) -> list[dict[str, object]]:
    assert _is_list(value)
    return [_mapping(row) for row in value]


@dataclass(frozen=True)
class _State:
    state: str
    last_changed: datetime | None = None


@dataclass
class _States:
    values: dict[str, _State] = field(default_factory=dict)

    def get(self, entity_id: str) -> _State | None:
        return self.values.get(entity_id)


@dataclass
class _Hass:
    states: _States = field(default_factory=_States)


@dataclass
class _Store:
    """Only the HA Store transport seam: replace pending writer, never infer."""

    requests: list[int] = field(default_factory=list)
    pending: Callable[[], dict[str, object]] | None = None
    saved: list[dict[str, object]] = field(default_factory=list)

    def async_delay_save(
        self, writer: Callable[[], dict[str, object]], delay: int,
    ) -> None:
        assert delay == 1
        self.requests.append(delay)
        self.pending = writer

    async def async_save(self, payload: dict[str, object]) -> None:
        self.saved.append(deepcopy(payload))

    def flush(self) -> dict[str, object]:
        writer = self.pending
        assert writer is not None
        self.pending = None
        payload = writer()
        self.saved.append(deepcopy(payload))
        return payload


@dataclass
class _Deadline:
    at: datetime
    callback: Callable[[datetime], None]
    canceled: bool = False
    fired: bool = False

    def cancel(self) -> None:
        self.canceled = True

    def fire(self) -> None:
        assert not self.canceled and not self.fired
        self.fired = True
        self.callback(self.at)


@dataclass
class _Transport:
    now: datetime
    hass: _Hass = field(default_factory=_Hass)
    store: _Store = field(default_factory=_Store)
    publications: list[dict[str, object]] = field(default_factory=list)
    subscribers: list[Callable[[], None]] = field(default_factory=list)
    listeners: list[Callable[[object], None]] = field(default_factory=list)
    intervals: list[timedelta] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    deadlines: list[_Deadline] = field(default_factory=list)
    schedule_failure: RuntimeError | None = None

    def track_state(
        self, _hass: object, _entities: object, listener: Callable[[object], None],
    ) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: self.removed.append("state")

    def track_interval(
        self, _hass: object, _callback: object, interval: timedelta,
    ) -> Callable[[], None]:
        self.intervals.append(interval)
        return lambda: self.removed.append("interval")

    def call_later(
        self, _hass: object, delay: float, callback: Callable[[datetime], None],
    ) -> Callable[[], None]:
        if self.schedule_failure is not None:
            raise self.schedule_failure
        deadline = _Deadline(self.now + timedelta(seconds=delay), callback)
        self.deadlines.append(deadline)
        return deadline.cancel

    def count(self, state: _State, at: datetime) -> None:
        self.now = at
        self.hass.states.values["sensor.people"] = state
        listener, = self.listeners
        listener(SimpleNamespace(time_fired=at, data={
            "entity_id": "sensor.people", "new_state": state,
        }))


def _runtime(
    monkeypatch: pytest.MonkeyPatch, model: PredictiveMap, *, now: datetime = NOW,
    count: int = 2, states: dict[str, _State] | None = None,
    count_entity: bool = False,
) -> tuple[PredictiveControlsRuntime, _Transport]:
    """Tiny HA adapter seam; all inference, publication and persistence are real."""
    install_fake_homeassistant(monkeypatch)
    module = importlib.import_module("custom_components.predictive_controls.runtime")
    from custom_components.predictive_controls.runtime import PredictiveControlsRuntime

    transport = _Transport(now)
    transport.hass.states.values.update({} if states is None else states)

    class ClockMeta(type):
        def __instancecheck__(cls, instance: object) -> bool:
            return isinstance(instance, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            value = (
                transport.now.replace(tzinfo=None)
                if tz is None else transport.now.astimezone(tz)
            )
            return cls(
                value.year, value.month, value.day, value.hour,
                value.minute, value.second, value.microsecond,
                tzinfo=value.tzinfo, fold=value.fold,
            )

    monkeypatch.setattr(module, "datetime", Clock)
    tracker_module: ModuleType = sys.modules[OccupancyTracker.__module__]
    monkeypatch.setattr(tracker_module, "datetime", Clock)
    monkeypatch.setattr(module, "async_track_state_change_event", transport.track_state)
    monkeypatch.setattr(module, "async_track_time_interval", transport.track_interval)
    monkeypatch.setattr(module, "async_call_later", transport.call_later)
    runtime = PredictiveControlsRuntime(
        transport.hass, model, (), 30, expected_occupants=count,
        expected_occupants_entity="sensor.people" if count_entity else None,
        transition_store=transport.store,
    )

    def publish(_hass: object, signal: str) -> None:
        assert signal == DISPATCH_UPDATE
        transport.publications.append(runtime.transition_store_data())
        for subscriber in tuple(transport.subscribers):
            subscriber()

    monkeypatch.setattr(module, "async_dispatcher_send", publish)
    return runtime, transport


@pytest.mark.parametrize("populated", (False, True))
@pytest.mark.parametrize("fail", (False, True))
def test_startup_publication_failure_keeps_bootstrap_and_requests_lazy_save(
    monkeypatch: pytest.MonkeyPatch, populated: bool, fail: bool,
) -> None:
    """STATE006/PRED009: empty snapshot must still save on publication failure."""
    model = _graph()
    states = {"binary_sensor.a": _State("off")} if populated else {}
    runtime, io = _runtime(monkeypatch, model, states=states)
    failure = RuntimeError("startup subscriber failed")

    def subscriber() -> None:
        assert not any(
            state.active for state in runtime.confidence.policy_states.values()
        )
        assert not io.store.requests and not io.store.saved
        if fail:
            raise failure

    io.subscribers.append(subscriber)
    if fail:
        with pytest.raises(RuntimeError) as caught:
            runtime.start()
        assert caught.value is failure
    else:
        runtime.start()
    assert len(io.publications) == 1
    assert len(io.listeners) == 1
    assert io.intervals == [timedelta(minutes=1), timedelta(seconds=5),
                            timedelta(seconds=30)]
    assert runtime._safe_bootstrap_complete
    assert runtime._automation_summary_cache == {}
    assert runtime.confidence._publishing_snapshot is None
    assert io.store.requests == ([1] if populated or fail else [])
    assert not io.store.saved
    committed = runtime.transition_store_data()
    assert committed == io.publications[0]
    restored = restore_target_state(model, committed, NOW)
    assert serialize_target_state(model, restored) == committed
    if populated or fail:
        assert io.store.flush() == committed
    asyncio.run(runtime.async_stop())
    assert io.removed == ["state", "interval", "interval", "interval"]
    assert io.store.saved[-1] == committed


@pytest.mark.parametrize("stage", ("scheduler", "commit"))
@pytest.mark.parametrize("fail", (False, True))
def test_postpublication_failure_preserves_state_save_and_retry_continuation(
    monkeypatch: pytest.MonkeyPatch, stage: str, fail: bool,
) -> None:
    """PRED009/STATE013: real pending work or mature lease, no invented queue."""
    if stage == "scheduler":
        model, source = _issued()
        frontier = _at(2)
        assert any(
            policy.phase == "predicted" for policy in source.snapshot.policy_states
        )
    else:
        model, source, accepted, _ = accepted_pending()
        frontier = _at(38)
        assert accepted in source._pending_prediction_learning
        assert source.prediction_manager.chain.counts["c"]["t"] == 0
    baseline = _strict(model, source)
    control = restore_target_state(model, baseline, frontier)
    runtime, io = _runtime(monkeypatch, model, now=frontier)
    assert runtime.restore_stored_state(baseline, frontier)
    assert runtime.transition_store_data() == baseline
    chain = runtime.chain
    failure = RuntimeError(f"{stage} failed after publication")

    def reject_counts(_self: MarkovChain, _payload: object) -> None:
        assert io.publications == [baseline]
        raise failure

    with monkeypatch.context() as patch:
        if fail and stage == "scheduler":
            io.schedule_failure = failure
        if fail and stage == "commit":
            patch.setattr(type(chain), "restore_counts", reject_counts)
        if fail:
            with pytest.raises(RuntimeError) as caught:
                runtime.observe_node("c", frontier)
            assert caught.value is failure
            assert runtime.chain is chain
            assert runtime.transition_store_data() == baseline
            assert io.store.requests == [1]
            assert not io.store.saved
        else:
            runtime.observe_node("c", frontier)
    io.schedule_failure = None
    assert io.publications[0] == baseline
    assert runtime._automation_summary_cache == {}
    assert runtime.confidence._publishing_snapshot is None
    if fail:
        runtime.observe_node("c", frontier)
    changed = control.commit_prediction_learning()
    assert changed is (stage == "commit")
    assert runtime.transition_store_data() == serialize_target_state(model, control)
    requests = len(io.store.requests)
    runtime.observe_node("c", frontier)
    assert len(io.store.requests) == requests
    assert not control.commit_prediction_learning()
    assert runtime.transition_store_data() == serialize_target_state(model, control)
    if stage == "commit":
        assert runtime.chain.counts["c"]["t"] == 1
        assert io.store.requests == ([1, 1] if fail else [1])
    else:
        assert io.store.requests == ([1] if fail else [])
        live, = [deadline for deadline in io.deadlines
                 if not deadline.canceled and not deadline.fired]
        assert live.at == _at(12)  # Retry never renews the original ten-second lease.
    if io.store.pending is not None:
        assert io.store.flush() == serialize_target_state(model, control)
        assert len(io.store.saved) == 1

    future = _at(12) if stage == "scheduler" else _at(39)
    io.now = future
    if stage == "scheduler":
        live.fire()
        assert not runtime.confidence.policy_states["t00"].active
    else:
        runtime._async_expire_transient_state(future)
    control.advance(future)
    control.commit_prediction_learning()
    assert runtime.transition_store_data() == serialize_target_state(model, control)


def test_publication_failure_and_rejections_coalesce_latest_strict_store_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRED002/009: save callbacks are lazy and retain confirmation, not old lease."""
    model = _graph()
    runtime, io = _runtime(monkeypatch, model)
    runtime.confidence.ensure_state(NOW)
    for _ in range(30):
        assert runtime.chain.observe("c", "t00")
    counts = runtime.chain.counts
    for node, seconds in (("a", 0), ("b", 1)):
        io.now = _at(seconds)
        runtime.observe_entity(f"binary_sensor.{node}", "on", io.now)
    failure = RuntimeError("accepted arrival subscriber failed")

    def subscriber() -> None:
        assert runtime.confidence.policy_states["t00"].phase == "predicted"
        assert runtime.chain.counts == counts
        raise failure

    io.subscribers.append(subscriber)
    io.now = _at(2)
    with pytest.raises(RuntimeError) as caught:
        runtime.observe_entity("binary_sensor.c", "on", io.now)
    assert caught.value is failure
    io.subscribers.clear()
    assert runtime.confidence.policy_states["t00"].active
    assert io.store.requests == [1, 1, 1]
    accepted_wire = runtime.transition_store_data()
    assert serialize_target_state(
        model, restore_target_state(model, accepted_wire, _at(2)),
    ) == accepted_wire
    original_deadlines = tuple(lease.expires_at for lease in
                               runtime.confidence._predictions.leases)
    assert original_deadlines and set(original_deadlines) == {_at(12)}
    runtime.observe_entity("binary_sensor.c", "on", _at(2))
    assert runtime.confidence.diagnostics.event_disposition == "duplicate"
    runtime.observe_entity("binary_sensor.a", "off", _at(1), processing_at=_at(2))
    assert runtime.confidence.diagnostics.event_disposition == "stale"
    assert io.store.requests == [1] * 5
    assert tuple(
        lease.expires_at for lease in runtime.confidence._predictions.leases
    ) == original_deadlines
    io.now = _at(3)
    runtime.observe_entity("binary_sensor.t00", "on", io.now)
    assert runtime.confidence.policy_states["t00"].phase == "active"
    assert not runtime.confidence._predictions.leases
    assert all(deadline.canceled for deadline in io.deadlines)
    assert runtime.chain.counts == counts
    assert io.store.requests == [1] * 6
    assert not io.store.saved
    latest = runtime.transition_store_data()
    assert latest != accepted_wire
    assert io.store.flush() == latest
    assert io.store.pending is None and io.store.saved == [latest]
    control = restore_target_state(model, latest, _at(3))
    io.now = _at(4)
    runtime.observe_entity("binary_sensor.t00", "off", io.now)
    control.observe(_sensor("t00", "off", 4))
    control.commit_prediction_learning()
    assert runtime.transition_store_data() == serialize_target_state(model, control)


class _NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


@pytest.mark.parametrize("no_offset", (False, True))
def test_count_listener_rejects_unaware_identity_without_partial_zero(
    monkeypatch: pytest.MonkeyPatch, no_offset: bool,
) -> None:
    """COUNT001/STATE001: bad timestamp cannot clear accepted active/count state."""
    model = _graph()
    runtime, io = _runtime(
        monkeypatch, model, count_entity=True,
        states={"sensor.people": _State("2", NOW)},
    )
    runtime.start()
    runtime.observe_entity("binary_sensor.a", "on", NOW)
    io.now = _at(1)
    runtime.observe_entity("binary_sensor.b", "on", io.now)
    io.count(_State("1", _at(2)), _at(2))
    assert runtime.expected_occupants == 1
    assert runtime.confidence.policy_states["b"].active
    before = runtime.transition_store_data()
    engine = runtime.confidence._engine
    config = runtime.confidence.config
    identity = runtime._count_observation
    chain = runtime.chain
    publications, requests = len(io.publications), len(io.store.requests)
    invalid_at = _at(3).replace(tzinfo=_NoOffset() if no_offset else None)
    with pytest.raises(
        ValueError, match="^Count state last_changed must be timezone-aware$",
    ):
        io.count(_State("0", invalid_at), _at(3))
    assert runtime.confidence._engine is engine
    assert runtime.chain is chain
    assert runtime.transition_store_data() == before
    assert runtime.confidence.config == config
    assert runtime._count_observation == identity
    assert runtime.authoritative_count_available
    assert len(io.publications) == publications
    assert len(io.store.requests) == requests + 1
    control = restore_target_state(model, before, _at(2))
    io.count(_State("0", _at(3)), _at(3))
    control.observe_count(CountInput(
        f"authoritative_occupant_count:{_at(3).isoformat()}:0", 0, True, _at(3),
    ))
    control.commit_prediction_learning()
    assert runtime.expected_occupants == 0
    assert not runtime.confidence.policy_states["b"].active
    assert runtime.transition_store_data() == serialize_target_state(model, control)
    io.now = _at(4)
    runtime.observe_entity("binary_sensor.b", "off", io.now)
    control.observe(_sensor("b", "off", 4))
    control.commit_prediction_learning()
    assert runtime.transition_store_data() == serialize_target_state(model, control)
    assert io.store.flush() == runtime.transition_store_data()


@pytest.mark.parametrize("count", (0, 2))
def test_real_warning_deadline_has_zone_updates_and_same_frontier_is_inert(
    monkeypatch: pytest.MonkeyPatch, count: int,
) -> None:
    """HEALTH001: diagnostic-only health still advances public ZoneState time.

    This guards the real neighboring behavior, not forced coverage of the dead
    warning-only/no-ZoneUpdate runtime arc documented in the mapping ledger.
    """
    model = _graph()
    runtime, io = _runtime(
        monkeypatch, model, count=count,
        states={"binary_sensor.a": _State("on")},
    )
    runtime.start()
    assert not runtime.confidence.reliability_warning_occurrences
    before = runtime.zone_states
    publications = len(io.publications)
    io.now = _at(600)
    runtime._async_refresh_active_confidence(io.now)
    warning, = runtime.confidence.reliability_warning_occurrences
    assert warning.node_id == "a" and warning.reason == "assertion_timeout"
    assert warning.first_observed_at == _at(600) and warning.cleared_at is None
    after = runtime.zone_states
    assert all(before[zone].updated_at == NOW for zone in model.zones())
    assert all(after[zone].updated_at == _at(600) for zone in model.zones())
    assert runtime.last_zone_update is not None
    assert len(io.publications) == publications + 1
    assert not any(state.active for state in runtime.confidence.policy_states.values())
    requests = len(io.store.requests)
    runtime._async_refresh_active_confidence(io.now)
    assert runtime.zone_states == after
    assert runtime.confidence.reliability_warning_occurrences == (warning,)
    assert len(io.publications) == publications + 1
    assert len(io.store.requests) == requests
    payload = runtime.transition_store_data()
    assert serialize_target_state(
        model, restore_target_state(model, payload, io.now),
    ) == payload


@dataclass(frozen=True)
class _Inventory:
    model: PredictiveMap
    payload: dict[str, object]
    grants: tuple[SelectedPredictionGrant, ...]
    oversized: tuple[SelectedPredictionGrant, ...]


@pytest.fixture(scope="module")
def inventory() -> _Inventory:
    """65 authentic records pooled from two accepted 64-record issuances.

    This is an invalid component inventory, not a purported reachable oversized
    engine state. No capacity override, private lease insertion or made-up grant.
    """
    model, first = _issued(targets=65, support=0)
    other_model, other = _issued(targets=65, support=0, suppress_last=True)
    assert model == other_model
    grants = first.snapshot.selected_prediction_grants
    other_grants = other.snapshot.selected_prediction_grants
    assert len(grants) == len(other_grants) == 64
    pooled = {grant.key: grant for grant in (*grants, *other_grants)}
    oversized = tuple(pooled[key] for key in sorted(pooled))
    assert len(oversized) == 65
    return _Inventory(model, _strict(model, first), grants, oversized)


def _manager(inventory: _Inventory) -> TargetPredictionManager:
    manager = TargetPredictionManager(inventory.model)
    manager.restore(
        inventory.payload["prediction"], _at(2), grants=inventory.grants,
        strict_frontier=True,
    )
    assert manager.serialize() == inventory.payload["prediction"]
    assert manager.grants == inventory.grants and len(manager.leases) == 64
    return manager


def _same_expiry(
    receiver: TargetPredictionManager, control: TargetPredictionManager,
) -> None:
    for at, expired in ((_at(12) - timedelta(microseconds=1), False), (_at(12), True)):
        assert receiver.expire(at) is expired
        assert control.expire(at) is expired
        assert receiver.serialize() == control.serialize()
        assert receiver.grants == control.grants
    assert receiver.leases == ()
    assert receiver.grants == ()
    assert not receiver.commit(()) and not control.commit(())


@pytest.mark.parametrize("mutation", ("duplicate", "reversed", "oversized"))
def test_grant_staging_rejects_invalid_inventory_without_replacing_pairs(
    inventory: _Inventory, mutation: str,
) -> None:
    manager, control = _manager(inventory), _manager(inventory)
    manager.restore_grants(inventory.grants)  # Exact-cap accepted staging baseline.
    if mutation == "duplicate":
        invalid = (*inventory.grants[:-1], inventory.grants[0])
    elif mutation == "reversed":
        invalid = tuple(reversed(inventory.grants))
    else:
        invalid = inventory.oversized
    assert invalid != inventory.grants
    original = deepcopy(invalid)
    before, chain = manager.serialize(), manager.chain
    with pytest.raises(
        ValueError, match="^Selected prediction grant inventory is invalid$",
    ):
        manager.restore_grants(invalid)
    assert invalid == original
    assert manager.chain is chain
    assert manager.serialize() == before and manager.grants == inventory.grants
    _same_expiry(manager, control)


@pytest.mark.parametrize("mutation", ("duplicate", "oversized"))
def test_prediction_restore_rejects_inventory_before_installing_candidate_counts(
    inventory: _Inventory, mutation: str,
) -> None:
    manager, control = _manager(inventory), _manager(inventory)
    invalid = ((*inventory.grants[:-1], inventory.grants[0])
               if mutation == "duplicate" else inventory.oversized)
    candidate = deepcopy(_mapping(inventory.payload["prediction"]))
    counts = _mapping(candidate["counts"])
    _mapping(counts["a"])["b"] = 9.0  # Valid distinct row exposes partial installation.
    original = deepcopy(candidate)
    before, chain = manager.serialize(), manager.chain
    with pytest.raises(
        ValueError, match="^Selected prediction grant inventory is invalid$",
    ):
        manager.restore(candidate, _at(2), grants=invalid, strict_frontier=True)
    assert candidate == original
    assert manager.chain is chain
    assert manager.serialize() == before and manager.grants == inventory.grants
    _same_expiry(manager, control)


def _reject_wire_and_continue(
    model: PredictiveMap, baseline: dict[str, object], invalid: dict[str, object],
    message: str,
) -> None:
    """Accept first, then reject into a genuinely different, nonempty receiver."""
    assert invalid != baseline
    accepted = restore_target_state(model, baseline, _at(2))
    assert serialize_target_state(model, accepted) == baseline
    tracker = OccupancyTracker(model, expected_occupants=2)
    assert tracker.restore_state(baseline, _at(2))
    event = event_from_entity(model, "binary_sensor.c", "off", _at(3))
    assert event is not None
    tracker.observe(event)
    before = tracker.occupancy_store_data()
    assert before != baseline
    engine, chain, config = tracker._engine, tracker.prediction_chain, tracker.config
    recent = tracker.recent_events
    original = deepcopy(invalid)
    with pytest.raises(ValueError, match=f"^{message}$"):
        restore_target_state(model, invalid, _at(4))
    assert not tracker.restore_state(invalid, _at(4))
    assert tracker.diagnostics.restore_reason == message
    assert tracker.diagnostics.lifecycle_counters["restore_rejected"] == 1
    assert tracker._engine is engine and tracker.prediction_chain is chain
    assert tracker.config == config and tracker.recent_events == recent
    assert tracker.occupancy_store_data() == before
    assert invalid == original
    control = restore_target_state(model, before, _at(3))
    continuation = event_from_entity(model, "binary_sensor.a", "off", _at(4))
    assert continuation is not None
    tracker.observe(continuation)
    control.observe(_sensor("a", "off", 4))
    control.commit_prediction_learning()
    assert tracker.occupancy_store_data() == serialize_target_state(model, control)
    assert invalid == original


@pytest.mark.parametrize("mutation", ("missing_effect", "extra_field"))
def test_selected_grant_wire_requires_exact_outer_shape(mutation: str) -> None:
    model, source = _issued()
    baseline = _strict(model, source)
    invalid = deepcopy(baseline)
    snapshot = _mapping(invalid["snapshot"])
    grant = _rows(snapshot["selected_prediction_grants"])[0]
    if mutation == "missing_effect":
        del grant["effect_kind"]
    else:
        grant["unexpected"] = "must not be ignored"
    _reject_wire_and_continue(
        model, baseline, invalid, "Selected prediction grant shape is invalid",
    )


@pytest.mark.parametrize("field_name", (
    "target_node_id", "target_zone", "target_episode_id", "reason",
    "track_confidence", "provenance_kind",
))
@pytest.mark.parametrize("value", ("", 7))
def test_selected_authorization_wire_rejects_empty_and_nonstring_identity(
    field_name: str, value: object,
) -> None:
    model, source = _issued()
    baseline = _strict(model, source)
    invalid = deepcopy(baseline)
    grant = _rows(_mapping(invalid["snapshot"])["selected_prediction_grants"])[0]
    authorization = _mapping(grant["authorization"])
    authorization[field_name] = value
    _reject_wire_and_continue(
        model, baseline, invalid,
        "Selected prediction authorization identity is invalid",
    )


def test_current_outward_wire_requires_explicit_nullable_qualification() -> None:
    """STATE005/010: missing proof is not equivalent to explicit null.

    Read-only structural helper: real ordinary component outward records plus
    unchanged current selection, physical state and both prediction collections.
    The complete current reader accepts this baseline before any mutation.
    """
    model = _graph()
    baseline = structural_payload(
        model, (_sensor("a", "on", 0), _sensor("b", "on", 1),
                _sensor("c", "on", 2)), count=2, outward=True,
    )
    invalid = deepcopy(baseline)
    beliefs = _rows(_mapping(invalid["snapshot"])["belief_states"])
    source = next(row for row in beliefs if row["zone"] == "a")
    outward = _mapping(source["outward_context"])
    assert outward["qualified_until"] is None
    assert outward["source_episode_id"] == f"a:1:{NOW.isoformat()}"
    del outward["qualified_until"]
    _reject_wire_and_continue(
        model, baseline, invalid, "Target outward qualification field is missing",
    )
