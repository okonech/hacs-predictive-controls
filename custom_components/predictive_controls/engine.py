from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .actions import ActionDecision, PredictiveAction, evaluate_actions
from .markov import MarkovChain, Prediction
from .model import PredictiveMap


@dataclass(frozen=True)
class EngineUpdate:
    """Result of observing one node event."""

    source_node: str
    learned_transition: tuple[str, str] | None
    prediction: Prediction | None
    action_decisions: tuple[ActionDecision, ...]


@dataclass
class _RecentEvent:
    node_id: str
    event_at: datetime
    consumed: bool = False


class PredictiveEngine:
    """Pure inference state for predictive controls."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        actions: tuple[PredictiveAction, ...],
        transition_window: timedelta,
    ) -> None:
        self.map = predictive_map
        self.actions = actions
        self.chain = MarkovChain(predictive_map)
        self.transition_window = transition_window
        self.probabilities: dict[str, float] = {}
        self.last_source_node: str | None = None
        self.last_event_at: datetime | None = None
        self.last_prediction: Prediction | None = None
        self.last_fired: dict[str, datetime] = {}
        self._recent_events: list[_RecentEvent] = []

    def observe_node(self, node_id: str, now: datetime) -> EngineUpdate:
        learned_transition = self._learn_transition(node_id, now)
        self._remember_event(node_id, now)
        self.last_source_node = node_id
        self.last_event_at = now
        self.probabilities = self.chain.predict({node_id: 1.0})
        self.last_prediction = self.chain.top_prediction({node_id: 1.0})

        action_decisions = evaluate_actions(
            self.actions,
            self.probabilities,
            self.last_source_node,
            self.last_fired,
            now,
        )
        for decision in action_decisions:
            self.last_fired[decision.action.action_id] = now

        return EngineUpdate(
            source_node=node_id,
            learned_transition=learned_transition,
            prediction=self.last_prediction,
            action_decisions=action_decisions,
        )

    def project_predictions(
        self,
        probabilities: dict[str, float],
        source_node: str,
        now: datetime,
    ) -> EngineUpdate:
        """Project posterior-consistent probabilities without raw-event learning."""

        self.last_source_node = source_node
        self.last_event_at = now
        self.probabilities = dict(sorted(probabilities.items()))
        self.last_prediction = (
            None
            if not self.probabilities
            else Prediction(
                node_id=max(
                    self.probabilities,
                    key=lambda node_id: (self.probabilities[node_id], node_id),
                ),
                probability=max(self.probabilities.values()),
            )
        )
        action_decisions = evaluate_actions(
            self.actions,
            self.probabilities,
            source_node,
            self.last_fired,
            now,
        )
        for decision in action_decisions:
            self.last_fired[decision.action.action_id] = now
        return EngineUpdate(
            source_node=source_node,
            learned_transition=None,
            prediction=self.last_prediction,
            action_decisions=action_decisions,
        )

    def _learn_transition(
        self, node_id: str, now: datetime
    ) -> tuple[str, str] | None:
        self._prune_recent_events(now)

        for event in reversed(self._recent_events):
            if event.consumed:
                continue
            learned = self.chain.observe(event.node_id, node_id)
            if learned:
                event.consumed = True
                return (event.node_id, node_id)

        return None

    def _remember_event(self, node_id: str, now: datetime) -> None:
        self._recent_events.append(_RecentEvent(node_id=node_id, event_at=now))
        self._prune_recent_events(now)

    def _prune_recent_events(self, now: datetime) -> None:
        self._recent_events = [
            event
            for event in self._recent_events
            if timedelta(0) <= now - event.event_at <= self.transition_window
        ]
