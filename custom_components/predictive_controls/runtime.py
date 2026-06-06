from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .actions import ActionDecision, PredictiveAction
from .const import DISPATCH_UPDATE
from .engine import PredictiveEngine
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
    ) -> None:
        self.hass = hass
        self.map = predictive_map
        self.actions = actions
        self.engine = PredictiveEngine(
            predictive_map, actions, timedelta(seconds=transition_window)
        )
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

    @callback
    def _async_state_changed(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None or new_state.state != "on":
            return
        node_id = self.map.node_for_entity(entity_id)
        if node_id is None:
            return

        now = datetime.now().astimezone()
        self.observe_node(node_id=node_id, now=now)

    def observe_node(self, node_id: str, now: datetime) -> None:
        update = self.engine.observe_node(node_id=node_id, now=now)
        if update.learned_transition is not None:
            source, target = update.learned_transition
            _LOGGER.debug("Learned transition %s -> %s", source, target)
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
