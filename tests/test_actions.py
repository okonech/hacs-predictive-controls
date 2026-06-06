from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.actions import (
    PredictiveAction,
    PredictiveActionError,
    evaluate_actions,
    parse_actions,
)


def make_action(source_node: str | None = None) -> PredictiveAction:
    raw: dict[str, Any] = {
        "when": {
            "predicted_node": "kitchen",
            "source_node": source_node,
            "min_probability": 0.7,
            "cooldown_seconds": 10,
        },
        "call": {
            "service": "light.turn_on",
            "target": {"entity_id": "light.kitchen"},
            "data": {"brightness_pct": 25},
        },
    }
    if source_node is None:
        del raw["when"]["source_node"]
    return PredictiveAction.from_mapping("prelight", raw)


def test_action_config_parses_generic_service_call() -> None:
    action = make_action("hall")

    assert action.action_id == "prelight"
    assert action.source_node == "hall"
    assert action.predicted_node == "kitchen"
    assert action.min_probability == 0.7
    assert action.cooldown == timedelta(seconds=10)
    assert action.call.service == "light.turn_on"
    assert action.call.target == {"entity_id": "light.kitchen"}
    assert action.call.data == {"brightness_pct": 25}


def test_parse_actions_allows_empty_documents() -> None:
    assert parse_actions(None) == ()
    assert parse_actions({}) == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "Actions document must be"),
        ({"actions": []}, "actions must be"),
        ({"actions": {"bad": []}}, "must be a mapping"),
        ({"actions": {"bad": {"call": {}}}}, "when must be"),
        ({"actions": {"bad": {"when": {}}}}, "call must be"),
        (
            {"actions": {"bad": {"when": {}, "call": {}}}},
            "predicted_node must be",
        ),
        (
            {
                "actions": {
                    "bad": {
                        "when": {"predicted_node": "kitchen", "min_probability": 2},
                        "call": {"service": "light.turn_on"},
                    }
                }
            },
            "min_probability must be",
        ),
        (
            {
                "actions": {
                    "bad": {
                        "when": {"predicted_node": "kitchen", "source_node": 1},
                        "call": {"service": "light.turn_on"},
                    }
                }
            },
            "source_node must be",
        ),
        (
            {
                "actions": {
                    "bad": {
                        "when": {"predicted_node": "kitchen"},
                        "call": {"service": "turn_on"},
                    }
                }
            },
            "service must look",
        ),
        (
            {
                "actions": {
                    "bad": {
                        "when": {"predicted_node": "kitchen"},
                        "call": {"service": "light.turn_on", "target": []},
                    }
                }
            },
            "target and data must",
        ),
        (
            {
                "actions": {
                    "bad": {
                        "when": {
                            "predicted_node": "kitchen",
                            "cooldown_seconds": -1,
                        },
                        "call": {"service": "light.turn_on"},
                    }
                }
            },
            "cooldown_seconds must",
        ),
    ],
)
def test_action_config_rejects_invalid_documents(raw: object, message: str) -> None:
    with pytest.raises(PredictiveActionError, match=message):
        parse_actions(raw)


def test_evaluate_actions_respects_probability_source_and_cooldown() -> None:
    now = datetime(2026, 6, 6, tzinfo=UTC)
    action = make_action("hall")

    assert evaluate_actions((action,), {"kitchen": 0.69}, "hall", {}, now) == ()
    assert evaluate_actions((action,), {"kitchen": 0.8}, "entry", {}, now) == ()
    assert evaluate_actions(
        (action,),
        {"kitchen": 0.8},
        "hall",
        {"prelight": now - timedelta(seconds=9)},
        now,
    ) == ()

    decisions = evaluate_actions(
        (action,),
        {"kitchen": 0.8},
        "hall",
        {"prelight": now - timedelta(seconds=10)},
        now,
    )
    assert len(decisions) == 1
    assert decisions[0].action is action
    assert decisions[0].probability == 0.8


def test_evaluate_actions_allows_actions_without_source_filter() -> None:
    now = datetime(2026, 6, 6, tzinfo=UTC)
    action = make_action()

    decisions = evaluate_actions((action,), {"kitchen": 0.7}, None, {}, now)

    assert len(decisions) == 1
