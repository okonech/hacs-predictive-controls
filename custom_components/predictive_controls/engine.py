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

    def observe_node(self, node_id: str, now: datetime) -> EngineUpdate:
        learned_transition = self._learn_transition(node_id, now)
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

    def _learn_transition(
        self, node_id: str, now: datetime
    ) -> tuple[str, str] | None:
        if self.last_source_node is None or self.last_event_at is None:
            return None

        within_window = now - self.last_event_at <= self.transition_window
        if not within_window:
            return None

        learned = self.chain.observe(self.last_source_node, node_id)
        if not learned:
            return None

        return (self.last_source_node, node_id)
