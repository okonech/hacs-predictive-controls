from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


class PredictiveActionError(ValueError):
    """Raised when predictive action configuration is invalid."""


@dataclass(frozen=True)
class ServiceCall:
    """Generic Home Assistant service call."""

    service: str
    target: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictiveAction:
    """Action triggered by a predicted node probability."""

    action_id: str
    predicted_node: str
    call: ServiceCall
    min_probability: float = 0.6
    source_node: str | None = None
    cooldown: timedelta = timedelta(minutes=5)

    @classmethod
    def from_mapping(cls, action_id: str, raw: Any) -> PredictiveAction:
        if not isinstance(raw, dict):
            raise PredictiveActionError(f"Action {action_id!r} must be a mapping")
        when = raw.get("when")
        call = raw.get("call")
        if not isinstance(when, dict):
            raise PredictiveActionError(f"Action {action_id!r} when must be a mapping")
        if not isinstance(call, dict):
            raise PredictiveActionError(f"Action {action_id!r} call must be a mapping")

        predicted_node = when.get("predicted_node")
        if not isinstance(predicted_node, str) or not predicted_node:
            raise PredictiveActionError(
                f"Action {action_id!r} predicted_node must be a non-empty string"
            )

        min_probability = float(when.get("min_probability", 0.6))
        if not 0 <= min_probability <= 1:
            raise PredictiveActionError(
                f"Action {action_id!r} min_probability must be between 0 and 1"
            )

        source_node = when.get("source_node")
        if source_node is not None and not isinstance(source_node, str):
            raise PredictiveActionError(
                f"Action {action_id!r} source_node must be a string"
            )

        service = call.get("service")
        if not isinstance(service, str) or "." not in service:
            raise PredictiveActionError(
                f"Action {action_id!r} service must look like domain.service"
            )

        target = call.get("target", {})
        data = call.get("data", {})
        if not isinstance(target, dict) or not isinstance(data, dict):
            raise PredictiveActionError(
                f"Action {action_id!r} target and data must be mappings"
            )

        cooldown_seconds = int(when.get("cooldown_seconds", 300))
        if cooldown_seconds < 0:
            raise PredictiveActionError(
                f"Action {action_id!r} cooldown_seconds must be non-negative"
            )

        return cls(
            action_id=action_id,
            predicted_node=predicted_node,
            source_node=source_node,
            min_probability=min_probability,
            cooldown=timedelta(seconds=cooldown_seconds),
            call=ServiceCall(service=service, target=target.copy(), data=data.copy()),
        )


@dataclass(frozen=True)
class ActionDecision:
    """A predictive action that should be executed."""

    action: PredictiveAction
    probability: float


def parse_actions(raw: Any) -> tuple[PredictiveAction, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise PredictiveActionError("Actions document must be a mapping")
    raw_actions = raw.get("actions", {})
    if not isinstance(raw_actions, dict):
        raise PredictiveActionError("actions must be a mapping")
    return tuple(
        PredictiveAction.from_mapping(str(action_id), action_raw)
        for action_id, action_raw in raw_actions.items()
    )


def evaluate_actions(
    actions: tuple[PredictiveAction, ...],
    probabilities: Mapping[str, float],
    source_node: str | None,
    last_fired: Mapping[str, datetime],
    now: datetime,
) -> tuple[ActionDecision, ...]:
    decisions: list[ActionDecision] = []
    for action in actions:
        probability = probabilities.get(action.predicted_node, 0.0)
        previous_fire = last_fired.get(action.action_id)
        source_matches = action.source_node is None or action.source_node == source_node
        cooldown_elapsed = (
            previous_fire is None or now - previous_fire >= action.cooldown
        )
        should_fire = (
            source_matches
            and cooldown_elapsed
            and probability >= action.min_probability
        )
        if should_fire:
            decisions.append(ActionDecision(action=action, probability=probability))
    return tuple(decisions)
