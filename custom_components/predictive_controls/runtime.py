from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime, timedelta
from time import perf_counter_ns
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .actions import ActionDecision, PredictiveAction
from .confidence import ZoneConfidenceEngine, ZoneState, ZoneUpdate
from .const import DISPATCH_UPDATE
from .engine import PredictiveEngine
from .events import OccupancyEvent, event_from_entity
from .markov import MarkovChain, Prediction
from .model import PredictiveMap
from .occupancy_persistence import restore_occupancy_state
from .occupancy_settings import expected_occupants_from_state_value, tracked_entity_ids

_LOGGER = logging.getLogger(__name__)
RUNTIME_HARD_CEILING_MS = 100.0


class PredictiveControlsRuntime:
    """Live Home Assistant runtime for predictive controls."""

    def __init__(
        self,
        hass: HomeAssistant,
        predictive_map: PredictiveMap,
        actions: tuple[PredictiveAction, ...],
        transition_window: int,
        expected_occupants: int | None = None,
        expected_occupants_entity: str | None = None,
        transition_store: Any | None = None,
        transition_counts: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.hass = hass
        self.map = predictive_map
        self.actions = actions
        self._transition_store = transition_store
        self.engine = PredictiveEngine(
            predictive_map, actions, timedelta(seconds=transition_window)
        )
        if transition_counts is not None:
            self.engine.chain.restore_counts(transition_counts)
        self.configured_expected_occupants = (
            expected_occupants if expected_occupants and expected_occupants > 0 else 0
        )
        self.expected_occupants_entity = (expected_occupants_entity or "").strip()
        self.confidence = ZoneConfidenceEngine(
            predictive_map,
            expected_occupants=self.configured_expected_occupants,
            chain=self.engine.chain,
        )
        self.last_occupancy_event: OccupancyEvent | None = None
        self.last_zone_update: ZoneUpdate | None = None
        self._unsubscribe: object | None = None
        self._unsubscribe_refresh: object | None = None
        self._unsubscribe_transient_refresh: object | None = None
        self._restored_state = False
        self._latency_samples_ms: deque[float] = deque(maxlen=256)
        self._event_loop_delay_samples_ms: deque[float] = deque(maxlen=256)
        self._bootstrap_inference_ms = 0.0
        self._bootstrap_total_ms = 0.0
        self._performance_budget_exceeded_count = 0

    @property
    def chain(self) -> MarkovChain:
        return self.engine.chain

    @property
    def probabilities(self) -> dict[str, float]:
        return self.engine.probabilities

    @property
    def last_source_node(self) -> str | None:
        return self.engine.last_source_node

    @property
    def last_prediction(self) -> Prediction | None:
        return self.engine.last_prediction

    @property
    def zone_states(self) -> dict[str, ZoneState]:
        return self.confidence.joint_states

    @property
    def recent_occupancy_events(self) -> tuple[OccupancyEvent, ...]:
        return self.confidence.recent_events

    @property
    def transition_counts(self) -> dict[str, dict[str, float]]:
        return self.chain.counts

    @property
    def expected_occupants(self) -> int:
        return self.confidence.config.expected_occupants

    @property
    def latency_metrics(self) -> dict[str, float | int]:
        runtime = _latency_summary(tuple(self._latency_samples_ms))
        event_loop = _latency_summary(tuple(self._event_loop_delay_samples_ms))
        return {
            **runtime,
            "p50_ms": runtime["p50_ms"],
            "event_loop_delay_sample_count": event_loop["sample_count"],
            "event_loop_delay_last_ms": event_loop["last_ms"],
            "event_loop_delay_p50_ms": event_loop["p50_ms"],
            "event_loop_delay_p95_ms": event_loop["p95_ms"],
            "event_loop_delay_p99_ms": event_loop["p99_ms"],
            "event_loop_delay_max_ms": event_loop["max_ms"],
            "bootstrap_inference_ms": self._bootstrap_inference_ms,
            "bootstrap_total_ms": self._bootstrap_total_ms,
            "performance_budget_exceeded_count": (
                self._performance_budget_exceeded_count
            ),
            "performance_degraded": self._performance_budget_exceeded_count > 0,
        }

    def transition_store_data(self) -> dict[str, object]:
        return self.confidence.occupancy_store_data(
            datetime.now().astimezone(),
            self.transition_counts,
        )

    def restore_stored_state(
        self,
        stored_state: object,
        now: datetime,
    ) -> bool:
        """Restore validated inference before bootstrap observations run."""

        if not isinstance(stored_state, dict):
            return False
        self._sync_expected_occupants(now)
        try:
            restored = restore_occupancy_state(
                stored_state,
                self.map,
                self.expected_occupants,
                now,
            )
        except ValueError as exc:
            self.confidence.reject_joint_restore(str(exc))
            _LOGGER.warning("Rejected stored occupancy inference: %s", exc)
            return False
        self.confidence.restore_joint_state(restored)
        self.chain.restore_counts(restored.transition_counts)
        self._restored_state = True
        return True

    def start(self) -> None:
        startup_started_ns = perf_counter_ns()
        entity_ids = self._tracked_entity_ids()
        if not entity_ids:
            _LOGGER.warning("Predictive Controls map has no entity bindings")
            return
        self._unsubscribe = async_track_state_change_event(
            self.hass, entity_ids, self._async_state_changed
        )
        self._unsubscribe_refresh = async_track_time_interval(
            self.hass, self._async_refresh_active_confidence, timedelta(minutes=1)
        )
        self._unsubscribe_transient_refresh = async_track_time_interval(
            self.hass, self._async_expire_transient_state, timedelta(seconds=5)
        )
        now = datetime.now().astimezone()
        self._sync_expected_occupants(now)
        snapshot = self._current_snapshot(now)
        started_ns = perf_counter_ns()
        try:
            self.confidence.bootstrap_joint_state(
                tuple(snapshot),
                cold_start=not self._restored_state,
            )
        finally:
            self._bootstrap_inference_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self._latency_samples_ms.append(self._bootstrap_inference_ms)
        self._bootstrap_total_ms = (perf_counter_ns() - startup_started_ns) / 1_000_000
        async_dispatcher_send(self.hass, DISPATCH_UPDATE)
        if snapshot:
            self.schedule_transition_count_save()

    async def async_stop(self) -> None:
        if callable(self._unsubscribe):
            self._unsubscribe()
        if callable(self._unsubscribe_refresh):
            self._unsubscribe_refresh()
        if callable(self._unsubscribe_transient_refresh):
            self._unsubscribe_transient_refresh()
        self._unsubscribe = None
        self._unsubscribe_refresh = None
        self._unsubscribe_transient_refresh = None
        await self.async_save_transition_counts()

    async def async_save_transition_counts(self) -> None:
        if self._transition_store is None:
            return
        await self._transition_store.async_save(self.transition_store_data())

    def schedule_transition_count_save(self) -> None:
        if self._transition_store is None:
            return
        self._transition_store.async_delay_save(self.transition_store_data, 1)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        now = datetime.now().astimezone()
        time_fired = getattr(event, "time_fired", None)
        if isinstance(time_fired, datetime):
            delay_ms = max(0.0, (now - time_fired).total_seconds() * 1000.0)
            self._event_loop_delay_samples_ms.append(delay_ms)
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None:
            return

        if str(entity_id) == self.expected_occupants_entity:
            was_unsupported = self.confidence.requested_expected_occupants > 2
            if self._sync_expected_occupants(now):
                if (
                    was_unsupported
                    and 1 <= self.confidence.requested_expected_occupants <= 2
                ):
                    self.confidence.bootstrap_joint_state(
                        self._current_snapshot(now),
                        cold_start=True,
                    )
                self.schedule_transition_count_save()
            async_dispatcher_send(self.hass, DISPATCH_UPDATE)
            return

        self.observe_entity(
            entity_id=str(entity_id),
            state=str(new_state.state),
            now=now,
        )

    @callback
    def _async_refresh_active_confidence(self, now: datetime) -> None:
        self._sync_expected_occupants(now)
        updates = self.confidence.refresh_active(now)
        if not updates:
            return
        self.last_zone_update = updates[-1]
        _LOGGER.debug("Refreshed %s active zone confidence states", len(updates))
        async_dispatcher_send(self.hass, DISPATCH_UPDATE)

    @callback
    def _async_expire_transient_state(self, now: datetime) -> None:
        if self.confidence.expire_transient_state(now):
            self.schedule_transition_count_save()
            async_dispatcher_send(self.hass, DISPATCH_UPDATE)

    def observe_entity(
        self,
        entity_id: str,
        state: str,
        now: datetime,
        process_prediction_actions: bool = True,
    ) -> None:
        started_ns = perf_counter_ns()
        try:
            self._observe_entity(
                entity_id,
                state,
                now,
                process_prediction_actions,
                started_ns,
            )
        finally:
            self._latency_samples_ms.append(
                (perf_counter_ns() - started_ns) / 1_000_000
            )

    def _observe_entity(
        self,
        entity_id: str,
        state: str,
        now: datetime,
        process_prediction_actions: bool,
        started_ns: int,
    ) -> None:
        occupancy_event = event_from_entity(self.map, entity_id, state, now)
        if occupancy_event is None:
            return

        self._sync_expected_occupants(now)

        self.last_occupancy_event = occupancy_event
        self.last_zone_update = self.confidence.observe(
            occupancy_event,
            emit_activation=process_prediction_actions,
        )
        action_decisions: tuple[ActionDecision, ...] = ()
        if occupancy_event.state == "on" and process_prediction_actions:
            update = self.engine.project_predictions(
                self._node_prediction_probabilities(),
                occupancy_event.node_id,
                now,
            )
            action_decisions = update.action_decisions
        elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
        if elapsed_ms > RUNTIME_HARD_CEILING_MS:
            self._performance_budget_exceeded_count += 1
            _LOGGER.warning(
                "Predictive Controls runtime update exceeded %.1f ms: %.3f ms",
                RUNTIME_HARD_CEILING_MS,
                elapsed_ms,
            )
        _LOGGER.debug(
            "Updated zone confidence %s: %.3f -> %.3f (%s, %s)",
            self.last_zone_update.current.zone,
            self.last_zone_update.previous.confidence,
            self.last_zone_update.current.confidence,
            self.last_zone_update.current.status,
            self.last_zone_update.current.reason,
        )

        async_dispatcher_send(self.hass, DISPATCH_UPDATE)
        self.schedule_transition_count_save()
        self._execute_actions(action_decisions)

    def observe_node(self, node_id: str, now: datetime) -> None:
        self._sync_expected_occupants(now)
        update = self.engine.project_predictions(
            self._node_prediction_probabilities(),
            node_id,
            now,
        )
        async_dispatcher_send(self.hass, DISPATCH_UPDATE)
        self._execute_actions(update.action_decisions)

    def _node_prediction_probabilities(self) -> dict[str, float]:
        zone_probabilities = self.confidence.joint_prediction_probabilities
        return {
            node_id: zone_probabilities[node.occupancy_zone]
            for node_id, node in self.map.nodes.items()
            if node.occupancy_zone in zone_probabilities
        }

    def _tracked_entity_ids(self) -> tuple[str, ...]:
        return tracked_entity_ids(
            self.map.entity_ids(),
            self.expected_occupants_entity,
        )

    def _current_snapshot(self, now: datetime) -> tuple[OccupancyEvent, ...]:
        snapshot: list[OccupancyEvent] = []
        for entity_id in self.map.entity_ids():
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            event = event_from_entity(
                self.map,
                entity_id,
                str(state.state),
                now,
                allow_unsupported_state=True,
            )
            if event is not None:
                snapshot.append(event)
        return tuple(snapshot)

    def _sync_expected_occupants(self, now: datetime | None = None) -> bool:
        resolved = self.configured_expected_occupants
        if self.expected_occupants_entity:
            state = self.hass.states.get(self.expected_occupants_entity)
            resolved = expected_occupants_from_state_value(
                None if state is None else state.state,
                self.configured_expected_occupants,
            )
        if resolved == self.confidence.requested_expected_occupants:
            return False
        self.confidence.reconcile_expected_occupants(
            resolved,
            now or datetime.now().astimezone(),
            evidence_id="authoritative_occupant_count_change",
        )
        return True

    def _execute_actions(self, decisions: tuple[ActionDecision, ...]) -> None:
        for decision in decisions:
            domain, service = decision.action.call.service.split(".", 1)
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain,
                    service,
                    decision.action.call.data,
                    target=decision.action.call.target,
                    blocking=False,
                )
            )
            _LOGGER.debug(
                "Executed predictive action %s at probability %.3f",
                decision.action.action_id,
                decision.probability,
            )


def _latency_summary(samples: tuple[float, ...]) -> dict[str, float | int]:
    ordered = sorted(samples)

    def percentile(quantile: float) -> float:
        if not ordered:
            return 0.0
        return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]

    return {
        "sample_count": len(samples),
        "last_ms": samples[-1] if samples else 0.0,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": max(samples, default=0.0),
    }
