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


def make_house_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "entrance": {"adjacent": ["kitchen", "dining"]},
                "kitchen": {"adjacent": ["entrance", "dining"]},
                "dining": {"adjacent": ["entrance", "kitchen"]},
                "top_staircase": {"adjacent": ["master_bedroom_entrance"]},
                "master_bedroom_entrance": {"adjacent": ["top_staircase"]},
                "false_positive_sensor": {"adjacent": []},
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


def test_engine_learns_interleaved_two_person_paths() -> None:
    engine = PredictiveEngine(make_house_map(), (), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    first_person_starts = engine.observe_node("entrance", now)
    second_person_starts = engine.observe_node(
        "top_staircase", now + timedelta(seconds=2)
    )
    first_person_moves = engine.observe_node("kitchen", now + timedelta(seconds=4))
    second_person_moves = engine.observe_node(
        "master_bedroom_entrance", now + timedelta(seconds=6)
    )

    assert first_person_starts.learned_transition is None
    assert second_person_starts.learned_transition is None
    assert first_person_moves.learned_transition == ("entrance", "kitchen")
    assert second_person_moves.learned_transition == (
        "top_staircase",
        "master_bedroom_entrance",
    )
    assert engine.chain.counts["entrance"] == {"kitchen": 1.0, "dining": 0.0}
    assert engine.chain.counts["top_staircase"] == {
        "master_bedroom_entrance": 1.0
    }


def test_engine_ignores_interleaved_false_positive_for_transition_matching() -> None:
    engine = PredictiveEngine(make_house_map(), (), timedelta(seconds=30))
    now = datetime(2026, 6, 6, tzinfo=UTC)

    engine.observe_node("entrance", now)
    false_positive = engine.observe_node(
        "false_positive_sensor", now + timedelta(seconds=2)
    )
    kitchen = engine.observe_node("kitchen", now + timedelta(seconds=4))

    assert false_positive.learned_transition is None
    assert kitchen.learned_transition == ("entrance", "kitchen")
    assert engine.chain.counts["entrance"] == {"kitchen": 1.0, "dining": 0.0}
    assert engine.chain.counts["false_positive_sensor"] == {}


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
