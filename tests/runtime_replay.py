"""Fake HA clock/transport; real runtime, inference and public active entities.

No inference decisions are mocked. Historical SensorInput reliability overrides
are explicit compatibility inputs; send() without an override is map-native.
"""

from __future__ import annotations

import asyncio
import heapq
import importlib
import importlib.util
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType
from typing import Any, Literal, Self, cast

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import (
    PredictiveMap,
    is_interaction_signal_type,
)
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
    ZoneModelSnapshot,
)
from tests.test_entity_platforms import install_fake_homeassistant


def _utc(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Replay timestamps must be timezone-aware")
    return at.astimezone(UTC)


@dataclass
class _Timer:
    at: datetime
    order: int
    callback: Callable[[datetime], None]
    interval: timedelta | None
    canceled: bool = False


class FakeClock:
    """Run registered timers only; registration order breaks equal-time ties."""

    def __init__(self, at: datetime) -> None:
        self.now = self.origin = _utc(at)
        self._queue: list[tuple[datetime, int, _Timer]] = []
        self._sequence = 0
        self.executions: list[tuple[datetime, str]] = []

    def schedule(
        self, delay: timedelta, callback: Callable[[datetime], None],
        *, interval: timedelta | None = None,
    ) -> Callable[[], None]:
        if delay < timedelta(0) or (
            interval is not None and interval <= timedelta(0)
        ):
            raise ValueError("Invalid replay timer duration")
        self._sequence += 1
        timer = _Timer(self.now + delay, self._sequence, callback, interval)
        heapq.heappush(self._queue, (timer.at, timer.order, timer))

        def cancel() -> None:
            timer.canceled = True

        return cancel

    def advance(self, at: datetime, *, callback_limit: int = 100_000) -> None:
        at = _utc(at)
        if at < self.now:
            raise ValueError("Replay clock cannot move backwards")
        executed = 0
        while self._queue and self._queue[0][0] <= at:
            deadline, _, timer = heapq.heappop(self._queue)
            if timer.canceled:
                continue
            executed += 1
            if executed > callback_limit:
                raise RuntimeError("Replay timer callback limit exceeded")
            self.now = deadline
            self.executions.append((deadline, timer.callback.__name__))
            timer.callback(deadline)
            if timer.interval is not None and not timer.canceled:
                timer.at = deadline + timer.interval
                heapq.heappush(self._queue, (timer.at, timer.order, timer))
        self.now = at

    @property
    def pending_count(self) -> int:
        return sum(not timer.canceled for _, _, timer in self._queue)


@dataclass(frozen=True)
class ActiveEdge:
    at: datetime
    zone: str
    active: bool


PublicationPhase = Literal["timer", "input", "post_input", "initial"]


@dataclass(frozen=True)
class ZoneWrite:
    """One actual publication, including unchanged values; attributes are copies."""

    at: datetime
    zone: str
    active: bool
    phase: PublicationPhase
    _attributes: dict[str, object] = field(repr=False)

    @property
    def attributes(self) -> dict[str, object]:
        return deepcopy(self._attributes)


@dataclass(frozen=True)
class ReliabilityWrite:
    at: datetime
    value: int
    _attributes: dict[str, object] = field(repr=False)

    @property
    def attributes(self) -> dict[str, object]:
        return deepcopy(self._attributes)


@dataclass(frozen=True)
class InputDelivery:
    """Raw callback plus normalization, not an inference acceptance verdict.

    Count callbacks (including invalid values) have no normalized SensorInput.
    Rejected interaction values have no known occurrence: raw_state and callback_at
    retain the evidence without inventing one. Startup levels are not deliveries.
    """

    entity_id: str
    raw_state: str
    callback_at: datetime
    processing_at: datetime
    event_at: datetime | None
    normalized: SensorInput | None
    retained_input: SensorInput | None
    is_count: bool
    delivered: bool


@dataclass(frozen=True)
class PublishedState:
    at: datetime
    zones: tuple[tuple[str, bool], ...]

    def active(self, zone: str) -> bool:
        return dict(self.zones)[zone]


class _Hass:
    def __init__(self, count: int) -> None:
        self.values: dict[str, Any] = {
            "sensor.replay_people": SimpleNamespace(state=str(count)),
        }
        self.states = SimpleNamespace(get=self.values.get)
        self.data: dict[str, Any] = {}
        self.listeners: list[tuple[frozenset[str], Callable[[Any], None]]] = []
        self.dispatchers: dict[str, list[Callable[[], None]]] = {}
        self.services = SimpleNamespace(async_call=self._forbid_service)

    async def _forbid_service(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("Runtime replay must not operate lights or services")


class RuntimeScenario:
    """Scoped fake HA environment; multiple replay branches share one clock."""

    def __init__(self, at: datetime) -> None:
        self.clock = FakeClock(at)
        self.patch = pytest.MonkeyPatch()
        self.replays: list[RuntimeReplay] = []
        self.runtime_module: ModuleType
        self.binary_module: ModuleType
        self.sensor_module: ModuleType
        self._phase: PublicationPhase = "timer"
        self._input: SensorInput | None = None
        self._normalized: OccupancyEvent | None = None

    def _load_leaf(self, leaf: str) -> ModuleType:
        parent = importlib.import_module("custom_components.predictive_controls")
        name = f"{parent.__name__}.{leaf}"
        path = (
            Path(__file__).resolve().parents[1]
            / "custom_components" / "predictive_controls" / f"{leaf}.py"
        )
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        self.patch.setitem(sys.modules, name, module)
        self.patch.setattr(parent, leaf, module, raising=False)
        spec.loader.exec_module(module)
        return module

    def __enter__(self) -> Self:
        try:
            install_fake_homeassistant(self.patch)
            self.runtime_module = self._load_leaf("runtime")
            self.binary_module = self._load_leaf("binary_sensor")
            self.sensor_module = self._load_leaf("sensor")
            clock = self.clock

            class DateTimeMeta(type):
                def __instancecheck__(cls, instance: object) -> bool:
                    return isinstance(instance, datetime)

            class ReplayDateTime(datetime, metaclass=DateTimeMeta):
                @classmethod
                def now(cls, tz: tzinfo | None = None) -> Self:
                    value = (
                        clock.now.replace(tzinfo=None)
                        if tz is None else clock.now.astimezone(tz)
                    )
                    return cls.fromisoformat(value.isoformat())

            tracker = importlib.import_module(
                "custom_components.predictive_controls.occupancy_tracker"
            )
            for module in (self.runtime_module, tracker, self.sensor_module):
                self.patch.setattr(module, "datetime", ReplayDateTime)
            self.patch.setattr(
                self.runtime_module, "perf_counter_ns",
                lambda: (clock.now - clock.origin) // timedelta(microseconds=1) * 1000,
            )
            self.patch.setattr(
                self.runtime_module, "async_track_state_change_event", self._listen,
            )
            self.patch.setattr(
                self.runtime_module, "async_track_time_interval", self._interval,
            )
            self.patch.setattr(
                self.runtime_module, "async_call_later", self._later,
            )
            self.patch.setattr(
                self.runtime_module, "async_dispatcher_send", self._dispatch,
            )
            self.patch.setattr(
                self.binary_module, "async_dispatcher_connect", self._connect,
            )
            self.patch.setattr(
                self.sensor_module, "async_dispatcher_connect", self._connect,
            )
            normalizer = self.runtime_module.event_from_entity

            def normalize(
                predictive_map: PredictiveMap, entity_id: str, state: str,
                at: datetime, *, allow_unsupported_state: bool = False,
            ) -> OccupancyEvent | None:
                event = cast(OccupancyEvent | None, normalizer(
                    predictive_map, entity_id, state, at,
                    allow_unsupported_state=allow_unsupported_state,
                ))
                if event is not None and self._input is not None:
                    retained = self._input
                    assert (event.entity_id, event.state, event.event_at) == (
                        retained.entity_id, retained.state, retained.event_at,
                    )
                    event = replace(event, reliability=retained.reliability)
                if not allow_unsupported_state:
                    self._normalized = event
                return event

            self.patch.setattr(self.runtime_module, "event_from_entity", normalize)
            return self
        except BaseException:
            self.patch.undo()
            raise

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            for replay in reversed(self.replays):
                replay.close()
        finally:
            self.patch.undo()

    def _listen(
        self, hass: _Hass, entities: list[str], callback: Callable[[Any], None],
    ) -> Callable[[], None]:
        subscription = (frozenset(entities), callback)
        hass.listeners.append(subscription)
        return lambda: hass.listeners.remove(subscription)

    def _interval(
        self, _hass: _Hass, callback: Callable[[datetime], None], interval: timedelta,
    ) -> Callable[[], None]:
        return self.clock.schedule(interval, callback, interval=interval)

    def _later(
        self, _hass: _Hass, delay: float, callback: Callable[[datetime], None],
    ) -> Callable[[], None]:
        return self.clock.schedule(timedelta(seconds=delay), callback)

    @staticmethod
    def _connect(
        hass: _Hass, signal: str, callback: Callable[[], None],
    ) -> Callable[[], None]:
        listeners = hass.dispatchers.setdefault(signal, [])
        listeners.append(callback)
        return lambda: listeners.remove(callback)

    @staticmethod
    def _dispatch(hass: _Hass, signal: str) -> None:
        for listener in tuple(hass.dispatchers.get(signal, ())):
            listener()

    @contextmanager
    def _publishing(self, phase: PublicationPhase) -> Iterator[None]:
        previous = self._phase
        self._phase = phase
        try:
            yield
        finally:
            self._phase = previous

    def create(
        self, predictive_map: PredictiveMap, count: int,
        *, initial_states: dict[str, str] | None = None,
    ) -> RuntimeReplay:
        """Explicit raw levels, even {}, use cold startup; None keeps old fixtures."""
        return RuntimeReplay(
            self, predictive_map, count, initial_states=initial_states,
        )


class RuntimeReplay:
    """Drive HA input subscriptions and read only captured public state writes."""

    def __init__(
        self, scenario: RuntimeScenario, predictive_map: PredictiveMap, count: int,
        *, initial_states: dict[str, str] | None = None,
    ) -> None:
        self.scenario = scenario
        self.map = predictive_map
        self.hass = _Hass(count)
        if initial_states is not None:
            self.hass.values.update({
                entity: SimpleNamespace(state=state)
                for entity, state in initial_states.items()
            })
        self.edges: list[ActiveEdge] = []
        self._input_edges: list[ActiveEdge] = []
        self._writes: list[ZoneWrite] = []
        self._deliveries: list[InputDelivery] = []
        self._reliability_writes: list[ReliabilityWrite] = []
        self._reliability_entity: Any = None
        self.normalized_inputs: list[SensorInput] = []
        self.latest: dict[str, bool] = {}
        self.attributes: dict[str, dict[str, object]] = {}
        self.write_count = 0
        self.entities: dict[str, Any] = {}
        self.closed = False
        self.runtime: Any = scenario.runtime_module.PredictiveControlsRuntime(
            self.hass, predictive_map, (), transition_window=30,
            expected_occupants=count, expected_occupants_entity="sensor.replay_people",
        )
        scenario.replays.append(self)
        # Explicit synthetic unobserved baseline, identical to the old fixtures.
        if initial_states is None:
            self.runtime.confidence.ensure_state(scenario.clock.now)
        self.runtime.start()
        for zone in predictive_map.zones():
            entity = scenario.binary_module.ZoneActiveSensor(
                self.runtime, "replay", zone,
            )
            self.entities[zone] = entity
            entity.hass = self.hass
            scenario.patch.setattr(
                entity, "async_write_ha_state",
                lambda zone=zone: self._write(zone),
            )
            asyncio.run(entity.async_added_to_hass())
            with scenario._publishing("initial"):
                entity.async_write_ha_state()  # Platform baseline, not an edge.

    def _write(self, zone: str) -> None:
        entity = self.entities[zone]
        active = bool(entity.is_on)
        if zone in self.latest and self.latest[zone] != active:
            edge = ActiveEdge(self.scenario.clock.now, zone, active)
            self.edges.append(edge)
            if self.scenario._phase == "input":
                self._input_edges.append(edge)
        self.latest[zone] = active
        self.attributes[zone] = deepcopy(entity.extra_state_attributes)
        self._writes.append(ZoneWrite(
            self.scenario.clock.now, zone, active, self.scenario._phase,
            deepcopy(self.attributes[zone]),
        ))
        self.write_count += 1

    @property
    def writes(self) -> tuple[ZoneWrite, ...]:
        return tuple(self._writes)

    @property
    def deliveries(self) -> tuple[InputDelivery, ...]:
        return tuple(self._deliveries)

    def watch_reliability(self) -> Self:
        """Subscribe the actual diagnostic entity, without forcing a baseline write."""
        if self.closed:
            raise ValueError("Cannot watch a closed replay")
        if self._reliability_entity is None:
            entity = (
                self.scenario.sensor_module.PredictiveControlsReliabilityWarningsSensor(
                    self.runtime, "replay",
                )
            )
            self._reliability_entity = entity
            entity.hass = self.hass
            self.scenario.patch.setattr(
                entity, "async_write_ha_state", self._write_reliability,
            )
            asyncio.run(entity.async_added_to_hass())
        return self

    def _write_reliability(self) -> None:
        entity = self._reliability_entity
        self._reliability_writes.append(ReliabilityWrite(
            self.scenario.clock.now, entity.native_value,
            deepcopy(entity.extra_state_attributes),
        ))

    @property
    def reliability_writes(self) -> tuple[ReliabilityWrite, ...]:
        return tuple(self._reliability_writes)

    @property
    def reliability_attributes(self) -> dict[str, object] | None:
        """Last published snapshot, not live properties; None means never written."""
        return (
            self._reliability_writes[-1].attributes
            if self._reliability_writes else None
        )

    def view(self) -> PublishedState:
        return PublishedState(
            self.scenario.clock.now, tuple(sorted(self.latest.items())),
        )

    def advance(self, at: datetime) -> PublishedState:
        with self.scenario._publishing("timer"):
            self.scenario.clock.advance(at)
        return self.view()

    def observe(
        self, event: SensorInput, *, processing_at: datetime | None = None,
    ) -> PublishedState:
        binding = self.map.entity_binding_for_entity(event.entity_id)
        state = event.state
        if (state == "pressed" and binding is not None
                and is_interaction_signal_type(binding.signal_type)):
            state = _utc(event.event_at).isoformat()
        return self.send(
            event.entity_id, state, event.event_at,
            processing_at=processing_at, retained_input=event,
        )

    def send(
        self, entity_id: str, state: str, at: datetime,
        *, processing_at: datetime | None = None,
        retained_input: SensorInput | None = None,
    ) -> PublishedState:
        at = _utc(at)
        received = at if processing_at is None else _utc(processing_at)
        if at > received:
            raise ValueError("Observation cannot occur after receipt")
        self.advance(received)
        old = self.hass.values.get(entity_id)
        new = SimpleNamespace(state=state)
        event = SimpleNamespace(
            time_fired=at,
            data={"entity_id": entity_id, "old_state": old, "new_state": new},
        )
        self.hass.values[entity_id] = new
        with self.scenario._publishing("input"):
            self.scenario._input = retained_input
            self.scenario._normalized = None
            delivered = False
            try:
                for entities, callback in tuple(self.hass.listeners):
                    if entity_id in entities:
                        delivered = True
                        callback(event)
                if not delivered:
                    raise ValueError(f"No runtime subscriber for {entity_id}")
            finally:
                normalized = self.scenario._normalized
                captured = None if normalized is None else SensorInput(
                    normalized.entity_id, normalized.state, normalized.event_at,
                    reliability=normalized.reliability,
                )
                is_count = entity_id == "sensor.replay_people"
                if not is_count and captured is not None:
                    self.normalized_inputs.append(captured)
                binding = self.map.entity_binding_for_entity(entity_id)
                interaction = (
                    binding is not None
                    and is_interaction_signal_type(binding.signal_type)
                )
                self._deliveries.append(InputDelivery(
                    entity_id, state, at, received,
                    captured.event_at if captured else (None if interaction else at),
                    captured, retained_input, is_count, delivered,
                ))
                self.scenario._input = None
                self.scenario._normalized = None
        with self.scenario._publishing("post_input"):
            self.scenario.clock.advance(received)  # Drain new zero-delay work.
        return self.view()

    def edges_for(self, zone: str) -> tuple[ActiveEdge, ...]:
        return tuple(edge for edge in self.edges if edge.zone == zone)

    def input_edges_for(self, zone: str) -> tuple[ActiveEdge, ...]:
        return tuple(edge for edge in self._input_edges if edge.zone == zone)

    def writes_for(self, zone: str) -> tuple[ZoneWrite, ...]:
        return tuple(write for write in self._writes if write.zone == zone)

    def checkpoint(self) -> dict[str, object]:
        return cast(dict[str, object], self.runtime.transition_store_data())

    def restore(self, payload: dict[str, object]) -> None:
        if not self.runtime.restore_stored_state(payload, self.scenario.clock.now):
            raise AssertionError("Runtime rejected its replay checkpoint")

    def inference_snapshot(self) -> ZoneModelSnapshot:
        """Supplementary strict storage checks; never the public outcome oracle."""
        return restore_target_state(
            self.map, self.checkpoint(), self.scenario.clock.now,
        ).snapshot

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            asyncio.run(self.runtime.async_stop())
        finally:
            entities = [*self.entities.values()]
            if self._reliability_entity is not None:
                entities.append(self._reliability_entity)
            for entity in entities:
                for remove in getattr(entity, "remove_callbacks", ()):
                    remove()
