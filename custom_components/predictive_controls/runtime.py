from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .actions import ActionDecision, PredictiveAction
from .confidence import ZoneConfidenceEngine, ZoneState, ZoneUpdate
from .const import DISPATCH_UPDATE
from .engine import PredictiveEngine
from .events import OccupancyEvent, event_from_entity
from .markov import MarkovChain, Prediction
from .model import PredictiveMap

_LOGGER = logging.getLogger(__name__)


class PredictiveControlsRuntime:
    """Live Home Assistant runtime for predictive controls."""

    def __init__(
        self,
        hass: HomeAssistant,
        predictive_map: PredictiveMap,
        actions: tuple[PredictiveAction, ...],
        transition_window: int,
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
        self.confidence = ZoneConfidenceEngine(predictive_map)
        self.last_occupancy_event: OccupancyEvent | None = None
        self.last_zone_update: ZoneUpdate | None = None
        self._unsubscribe: object | None = None

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
        return self.confidence.states

    @property
    def recent_occupancy_events(self) -> tuple[OccupancyEvent, ...]:
        return self.confidence.recent_events

    @property
    def transition_counts(self) -> dict[str, dict[str, float]]:
        return self.chain.counts

    def transition_store_data(self) -> dict[str, object]:
        return {"transition_counts": self.transition_counts}

    def start(self) -> None:
        entity_ids = self.map.entity_ids()
        if not entity_ids:
            _LOGGER.warning("Predictive Controls map has no entity bindings")
            return
        self._unsubscribe = async_track_state_change_event(
            self.hass, entity_ids, self._async_state_changed
        )

    async def async_stop(self) -> None:
        if callable(self._unsubscribe):
            self._unsubscribe()
        self._unsubscribe = None
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
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None:
            return

        now = datetime.now().astimezone()
        self.observe_entity(
            entity_id=str(entity_id),
            state=str(new_state.state),
            now=now,
        )

    def observe_entity(self, entity_id: str, state: str, now: datetime) -> None:
        occupancy_event = event_from_entity(self.map, entity_id, state, now)
        if occupancy_event is None:
            return

        self.last_occupancy_event = occupancy_event
        self.last_zone_update = self.confidence.observe(occupancy_event)
        _LOGGER.debug(
            "Updated zone confidence %s: %.3f -> %.3f (%s, %s)",
            self.last_zone_update.current.zone,
            self.last_zone_update.previous.confidence,
            self.last_zone_update.current.confidence,
            self.last_zone_update.current.status,
            self.last_zone_update.current.reason,
        )

        action_decisions: tuple[ActionDecision, ...] = ()
        if occupancy_event.state == "on":
            update = self.engine.observe_node(node_id=occupancy_event.node_id, now=now)
            action_decisions = update.action_decisions
            if update.learned_transition is not None:
                source, target = update.learned_transition
                _LOGGER.debug("Learned transition %s -> %s", source, target)
                self.schedule_transition_count_save()

        async_dispatcher_send(self.hass, DISPATCH_UPDATE)
        self._execute_actions(action_decisions)

    def observe_node(self, node_id: str, now: datetime) -> None:
        update = self.engine.observe_node(node_id=node_id, now=now)
        if update.learned_transition is not None:
            source, target = update.learned_transition
            _LOGGER.debug("Learned transition %s -> %s", source, target)
            self.schedule_transition_count_save()
        async_dispatcher_send(self.hass, DISPATCH_UPDATE)
        self._execute_actions(update.action_decisions)

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
