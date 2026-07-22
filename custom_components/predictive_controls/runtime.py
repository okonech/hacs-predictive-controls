from __future__ import annotations

import logging
import math
from collections import deque
from datetime import UTC, datetime, timedelta
from time import perf_counter_ns
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .actions import PredictiveAction
from .confidence import ZoneConfidenceEngine, ZoneState, ZoneUpdate
from .const import (
    DISPATCH_DIAGNOSTIC_UPDATE,
    DISPATCH_UPDATE,
)
from .events import OccupancyEvent, event_from_entity
from .markov import MarkovChain, Prediction
from .model import PredictiveMap
from .occupancy_settings import (
    authoritative_occupants_from_state_value,
    tracked_entity_ids,
)

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
        **_legacy_options: object,
    ) -> None:
        self.hass = hass
        self.map = predictive_map
        del actions
        self._transition_store = transition_store
        del transition_window, transition_counts
        self.configured_expected_occupants = (
            expected_occupants if expected_occupants and expected_occupants > 0 else 0
        )
        self.expected_occupants_entity = (expected_occupants_entity or "").strip()
        self.confidence = ZoneConfidenceEngine(
            predictive_map,
            expected_occupants=self.configured_expected_occupants,
        )
        self._prediction_probabilities: dict[str, float] = {}
        self._last_prediction_source_node: str | None = None
        self._last_prediction: Prediction | None = None
        self.last_occupancy_event: OccupancyEvent | None = None
        self.last_zone_update: ZoneUpdate | None = None
        self._unsubscribe: object | None = None
        self._unsubscribe_refresh: object | None = None
        self._unsubscribe_transient_refresh: object | None = None
        self._unsubscribe_prediction_deadline: object | None = None
        self._unsubscribe_diagnostic_refresh: object | None = None
        self._restored_state = False
        self._latency_samples_ms: deque[float] = deque(maxlen=256)
        self._event_loop_delay_samples_ms: deque[float] = deque(maxlen=256)
        self._bootstrap_inference_ms = 0.0
        self._bootstrap_total_ms = 0.0
        self._performance_budget_exceeded_count = 0
        self._invalid_authoritative_count = False
        self._restore_rejected = False
        self._safe_bootstrap_complete = False
        self._automation_summary_cache: dict[object, object] = {}

    @property
    def chain(self) -> MarkovChain:
        return self.confidence.prediction_chain

    @property
    def probabilities(self) -> dict[str, float]:
        return self._prediction_probabilities.copy()

    @property
    def last_source_node(self) -> str | None:
        return self._last_prediction_source_node

    @property
    def last_prediction(self) -> Prediction | None:
        return self._last_prediction

    @property
    def zone_states(self) -> dict[str, ZoneState]:
        return self.confidence.states

    @property
    def recent_occupancy_events(self) -> tuple[OccupancyEvent, ...]:
        return self.confidence.recent_events

    @property
    def transition_counts(self) -> dict[str, dict[str, float]]:
        return self.confidence.prediction_chain.counts

    @property
    def expected_occupants(self) -> int:
        return self.confidence.config.expected_occupants

    @property
    def authoritative_count_available(self) -> bool:
        return not self._invalid_authoritative_count

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

    @property
    def problem_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if any(state.health_warning for state in self.confidence.episode_states):
            reasons.append("sensor_health_degraded")
        if self._invalid_authoritative_count:
            reasons.append("invalid_authoritative_count")
        if self._restore_rejected:
            reasons.append("restore_rejected")
        return tuple(reasons)

    @property
    def problem_sources(self) -> tuple[str, ...]:
        sources = {
            "sensor_health_degraded": "physical_sensor_episode",
            "invalid_authoritative_count": (
                self.expected_occupants_entity or "configured_expected_occupants"
            ),
            "restore_rejected": "occupancy_storage",
        }
        return tuple(sources[reason] for reason in self.problem_reasons)

    def transition_store_data(self) -> dict[str, object]:
        payload = self.confidence.occupancy_store_data(
            datetime.now(UTC),
            self.transition_counts,
        )
        if self._safe_bootstrap_complete:
            self._restore_rejected = False
        return payload

    def restore_stored_state(
        self,
        stored_state: object,
        now: datetime,
    ) -> bool:
        """Restore validated inference before bootstrap observations run."""

        if not isinstance(stored_state, dict):
            return False
        now = _as_utc(now)
        if self.confidence.restore_state(stored_state, now):
            self._sync_expected_occupants(now)
            self._restored_state = True
            self._restore_rejected = False
            return True
        self._restore_rejected = True
        _LOGGER.warning(
            "Rejected stored zone-belief inference: %s",
            self.confidence.diagnostics.restore_reason,
        )
        return False

    def start(self) -> None:
        startup_started_ns = perf_counter_ns()
        entity_ids = self._tracked_entity_ids()
        if not entity_ids:
            _LOGGER.warning("Predictive Controls map has no entity bindings")
            return
        now = datetime.now(UTC)
        self._sync_expected_occupants(now)
        snapshot = self._current_snapshot(now)
        started_ns = perf_counter_ns()
        try:
            self.confidence.bootstrap_state(
                tuple(snapshot),
                cold_start=not self._restored_state,
            )
        finally:
            self._bootstrap_inference_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self._latency_samples_ms.append(self._bootstrap_inference_ms)
        # Subscribe only after the target model has bootstrapped successfully.
        # A startup validation error must not leave orphaned state and timer
        # callbacks running after Home Assistant marks the entry setup_error.
        self._unsubscribe = async_track_state_change_event(
            self.hass, entity_ids, self._async_state_changed
        )
        self._unsubscribe_refresh = async_track_time_interval(
            self.hass, self._async_refresh_active_confidence, timedelta(minutes=1)
        )
        self._unsubscribe_transient_refresh = async_track_time_interval(
            self.hass, self._async_expire_transient_state, timedelta(seconds=5)
        )
        self._unsubscribe_diagnostic_refresh = async_track_time_interval(
            self.hass, self._async_publish_diagnostics, timedelta(seconds=30)
        )
        self._safe_bootstrap_complete = True
        self._bootstrap_total_ms = (perf_counter_ns() - startup_started_ns) / 1_000_000
        self._publish_update()
        self._schedule_prediction_deadline(now)
        if snapshot:
            self.schedule_transition_count_save()

    async def async_stop(self) -> None:
        if callable(self._unsubscribe):
            self._unsubscribe()
        if callable(self._unsubscribe_refresh):
            self._unsubscribe_refresh()
        if callable(self._unsubscribe_transient_refresh):
            self._unsubscribe_transient_refresh()
        if callable(self._unsubscribe_diagnostic_refresh):
            self._unsubscribe_diagnostic_refresh()
        if callable(self._unsubscribe_prediction_deadline):
            self._unsubscribe_prediction_deadline()
        self._unsubscribe = None
        self._unsubscribe_refresh = None
        self._unsubscribe_transient_refresh = None
        self._unsubscribe_diagnostic_refresh = None
        self._unsubscribe_prediction_deadline = None
        await self.async_save_transition_counts()

    async def async_save_transition_counts(self) -> None:
        if self._transition_store is not None:
            await self._transition_store.async_save(self.transition_store_data())

    def schedule_transition_count_save(self) -> None:
        if self._transition_store is not None:
            self._transition_store.async_delay_save(self.transition_store_data, 1)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        now = datetime.now(UTC)
        time_fired = getattr(event, "time_fired", None)
        event_at = now
        if isinstance(time_fired, datetime):
            event_at = _as_utc(time_fired)
            delay_ms = max(0.0, (now - event_at).total_seconds() * 1000.0)
            self._event_loop_delay_samples_ms.append(delay_ms)
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None:
            return

        if str(entity_id) == self.expected_occupants_entity:
            if self._sync_expected_occupants(event_at, processing_at=now):
                self.schedule_transition_count_save()
            self._publish_update()
            return

        self.observe_entity(
            entity_id=str(entity_id),
            state=str(new_state.state),
            now=event_at,
            processing_at=now,
        )

    @callback
    def _async_refresh_active_confidence(self, now: datetime) -> None:
        now = _as_utc(now)
        self._sync_expected_occupants(now)
        updates = self.confidence.refresh_active(now)
        if not updates:
            return
        self.last_zone_update = updates[-1]
        _LOGGER.debug("Refreshed %s active zone confidence states", len(updates))
        self._publish_update()

    @callback
    def _async_expire_transient_state(self, now: datetime) -> None:
        now = _as_utc(now)
        if self.confidence.expire_transient_state(now):
            self.schedule_transition_count_save()
            self._publish_update()
        self._schedule_prediction_deadline(now)

    @callback
    def _async_prediction_deadline(self, now: datetime) -> None:
        self._unsubscribe_prediction_deadline = None
        self._async_expire_transient_state(now)

    @callback
    def _async_publish_diagnostics(self, _now: datetime) -> None:
        async_dispatcher_send(self.hass, DISPATCH_DIAGNOSTIC_UPDATE)

    def observe_entity(
        self,
        entity_id: str,
        state: str,
        now: datetime,
        process_prediction_actions: bool = True,
        *,
        processing_at: datetime | None = None,
    ) -> None:
        now = _as_utc(now)
        processed_at = now if processing_at is None else _as_utc(processing_at)
        started_ns = perf_counter_ns()
        try:
            self._observe_entity(
                entity_id,
                state,
                now,
                processed_at,
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
        processing_at: datetime,
        process_prediction_actions: bool,
        started_ns: int,
    ) -> None:
        occupancy_event = event_from_entity(self.map, entity_id, state, now)
        if occupancy_event is None:
            return

        self._sync_expected_occupants(processing_at)

        self.last_occupancy_event = occupancy_event
        self.last_zone_update = self.confidence.observe(
            occupancy_event,
            processing_at=processing_at,
            emit_activation=process_prediction_actions,
            defer_learning=True,
            publication_callback=self._publish_update,
        )
        if occupancy_event.state == "on":
            self._update_prediction_diagnostics(occupancy_event.node_id)
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

        self._publish_update()
        self._schedule_prediction_deadline(processing_at)
        self.confidence.commit_prediction_learning()
        self.schedule_transition_count_save()

    def observe_node(self, node_id: str, now: datetime) -> None:
        now = _as_utc(now)
        self._sync_expected_occupants(now)
        self._update_prediction_diagnostics(node_id)
        self._publish_update()

    def _publish_update(self) -> None:
        """Invalidate projections and publish one coherent runtime update."""

        self._automation_summary_cache.clear()
        async_dispatcher_send(self.hass, DISPATCH_UPDATE)

    def _schedule_prediction_deadline(self, now: datetime) -> None:
        if callable(self._unsubscribe_prediction_deadline):
            self._unsubscribe_prediction_deadline()
        self._unsubscribe_prediction_deadline = None
        deadlines = tuple(
            state.prediction_expires_at
            for state in self.confidence.policy_states.values()
            if state.phase == "predicted" and state.prediction_expires_at is not None
        )
        if not deadlines:
            return
        deadline = min(deadlines)
        delay = max(0.0, (deadline - _as_utc(now)).total_seconds())
        self._unsubscribe_prediction_deadline = async_call_later(
            self.hass,
            delay,
            self._async_prediction_deadline,
        )

    def _update_prediction_diagnostics(self, source_node: str) -> None:
        self._last_prediction_source_node = source_node
        self._prediction_probabilities = dict(
            sorted(self._node_prediction_probabilities().items())
        )
        self._last_prediction = (
            None
            if not self._prediction_probabilities
            else Prediction(
                node_id=max(
                    self._prediction_probabilities,
                    key=lambda node_id: (
                        self._prediction_probabilities[node_id],
                        node_id,
                    ),
                ),
                probability=max(self._prediction_probabilities.values()),
            )
        )

    def _node_prediction_probabilities(self) -> dict[str, float]:
        zone_probabilities = self.confidence.prediction_probabilities
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
            assert event is not None
            snapshot.append(event)
        return tuple(snapshot)

    def _sync_expected_occupants(
        self,
        now: datetime | None = None,
        *,
        processing_at: datetime | None = None,
    ) -> bool:
        resolved = self.configured_expected_occupants
        if self.expected_occupants_entity:
            state = self.hass.states.get(self.expected_occupants_entity)
            authoritative = authoritative_occupants_from_state_value(
                None if state is None else state.state
            )
            self._invalid_authoritative_count = authoritative is None
            if authoritative is None:
                return False
            resolved = authoritative
        else:
            self._invalid_authoritative_count = False
        if resolved == self.confidence.requested_expected_occupants:
            return False
        self.confidence.reconcile_expected_occupants(
            resolved,
            _as_utc(now) if now is not None else datetime.now(UTC),
            evidence_id="authoritative_occupant_count_change",
            processing_at=processing_at,
        )
        return True

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
