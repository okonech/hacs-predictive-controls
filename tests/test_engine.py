from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.actions import PredictiveAction
from custom_components.predictive_controls.engine import PredictiveEngine
from custom_components.predictive_controls.model import PredictiveMap


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "entry": {"adjacent": ["hall", "kitchen"]},
                "hall": {"adjacent": ["entry", "kitchen"]},
                "kitchen": {"adjacent": ["hall"]},
            }
        }
    )


def make_action() -> PredictiveAction:
    return PredictiveAction.from_mapping(
        "prelight_kitchen",
        {
            "when": {
                "predicted_node": "kitchen",
                "source_node": "hall",
                "min_probability": 0.6,
                "cooldown_seconds": 30,
            },
            "call": {"service": "light.turn_on"},
        },
    )


def test_engine_observes_first_node_without_learning_transition() -> None:
    engine = PredictiveEngine(make_map(), (), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    update = engine.observe_node("entry", now)

    assert update.source_node == "entry"
    assert update.learned_transition is None
    assert update.prediction is not None
    assert update.prediction.node_id == "hall"
    assert update.action_decisions == ()
    assert engine.last_source_node == "entry"
    assert engine.last_event_at == now


def test_engine_learns_adjacent_transition_inside_window() -> None:
    engine = PredictiveEngine(make_map(), (), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    engine.observe_node("entry", now)
    update = engine.observe_node("kitchen", now + timedelta(seconds=5))

    assert update.learned_transition == ("entry", "kitchen")
    assert engine.chain.counts["entry"]["kitchen"] == 1


def test_engine_does_not_learn_outside_window_or_invalid_transition() -> None:
    engine = PredictiveEngine(make_map(), (), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    engine.observe_node("entry", now)
    outside_window = engine.observe_node("hall", now + timedelta(seconds=31))
    engine.observe_node("kitchen", now + timedelta(seconds=32))
    invalid_transition = engine.observe_node("entry", now + timedelta(seconds=33))

    assert outside_window.learned_transition is None
    assert invalid_transition.learned_transition is None
    assert engine.chain.counts["entry"] == {"hall": 0.0, "kitchen": 0.0}
    assert engine.chain.counts["hall"] == {"entry": 0.0, "kitchen": 1.0}
    assert engine.chain.counts["kitchen"] == {"hall": 0.0}


def test_engine_returns_actions_and_records_cooldown() -> None:
    engine = PredictiveEngine(make_map(), (make_action(),), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    engine.chain.observe("hall", "kitchen", weight=5)
    first = engine.observe_node("hall", now)
    second = engine.observe_node("hall", now + timedelta(seconds=29))
    third = engine.observe_node("hall", now + timedelta(seconds=30))

    assert len(first.action_decisions) == 1
    assert first.action_decisions[0].action.action_id == "prelight_kitchen"
    assert second.action_decisions == ()
    assert len(third.action_decisions) == 1
    assert engine.last_fired["prelight_kitchen"] == now + timedelta(seconds=30)


def test_engine_keeps_prediction_none_for_dead_end() -> None:
    predictive_map = PredictiveMap.from_mapping({"nodes": {"office": {}}})
    engine = PredictiveEngine(predictive_map, (), timedelta(seconds=30))

    update = engine.observe_node("office", datetime(2026, 6, 6, tzinfo=UTC))

    assert update.prediction is None
    assert engine.probabilities == {}
