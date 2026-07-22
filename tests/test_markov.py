from __future__ import annotations

import pytest

from custom_components.predictive_controls.markov import MARKOV_COUNT_LIMIT, MarkovChain
from custom_components.predictive_controls.model import PredictiveMap


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "entry": {"adjacent": ["hall", "kitchen"]},
                "hall": {
                    "adjacent": ["entry", "kitchen"],
                    "route_prior_weight": 2,
                },
                "kitchen": {"adjacent": ["entry", "hall"]},
                "office": {"adjacent": []},
            }
        }
    )


def test_initial_probabilities_use_smoothed_node_weights() -> None:
    chain = MarkovChain(make_map())

    assert chain.probabilities("entry") == {
        "hall": pytest.approx(2 / 3),
        "kitchen": pytest.approx(1 / 3),
    }


def test_observed_transitions_update_probabilities_without_mutating_counts_copy() -> (
    None
):
    chain = MarkovChain(make_map())

    assert chain.observe("entry", "kitchen", weight=3)
    counts = chain.counts
    counts["entry"]["kitchen"] = 100

    assert chain.counts["entry"]["kitchen"] == 3
    assert chain.probabilities("entry") == {
        "hall": pytest.approx(2 / 6),
        "kitchen": pytest.approx(4 / 6),
    }


def test_restore_counts_keeps_only_valid_current_edges() -> None:
    chain = MarkovChain(make_map())

    chain.restore_counts(
        {
            "entry": {
                "hall": 2,
                "kitchen": "3.5",
                "office": 99,
                "missing": 99,
            },
            "hall": {"entry": None, "kitchen": "not-a-number"},
            "kitchen": {"hall": -1},
            "missing": {"entry": 99},
        }
    )

    assert chain.counts["entry"] == {"hall": 2.0, "kitchen": 3.5}
    assert chain.counts["hall"] == {"entry": 0.0, "kitchen": 0.0}
    assert chain.counts["kitchen"] == {"entry": 0.0, "hall": 0.0}


def test_invalid_transition_is_not_learned() -> None:
    chain = MarkovChain(make_map())

    assert not chain.observe("entry", "office")
    assert not chain.observe("missing", "entry")
    assert chain.counts["entry"] == {"hall": 0.0, "kitchen": 0.0}


def test_predict_normalizes_distribution_and_advances_horizon() -> None:
    chain = MarkovChain(make_map(), smoothing=0)
    chain.observe("entry", "hall")
    chain.observe("hall", "kitchen")

    assert chain.predict({"entry": 2, "missing": 99}, horizon=1) == {
        "hall": pytest.approx(1.0)
    }
    assert chain.predict({"entry": 2}, horizon=2) == {"kitchen": pytest.approx(1.0)}


def test_top_prediction_returns_none_for_dead_end() -> None:
    chain = MarkovChain(make_map())

    assert chain.probabilities("office") == {}
    assert chain.predict({"office": 1}) == {}
    assert chain.top_prediction({"office": 1}) is None


def test_top_prediction_returns_most_likely_node() -> None:
    chain = MarkovChain(make_map())
    chain.observe("entry", "kitchen", weight=5)

    prediction = chain.top_prediction({"entry": 1})

    assert prediction is not None
    assert prediction.node_id == "kitchen"
    assert prediction.probability == pytest.approx(6 / 8)


@pytest.mark.parametrize("smoothing", [-1, -0.1])
def test_smoothing_must_be_non_negative(smoothing: float) -> None:
    with pytest.raises(ValueError, match="smoothing"):
        MarkovChain(make_map(), smoothing=smoothing)


def test_weight_and_horizon_must_be_positive() -> None:
    chain = MarkovChain(make_map())

    with pytest.raises(ValueError, match="weight"):
        chain.observe("entry", "hall", weight=0)
    with pytest.raises(ValueError, match="finite"):
        chain.observe("entry", "hall", weight=float("inf"))
    with pytest.raises(ValueError, match="horizon"):
        chain.predict({"entry": 1}, horizon=0)


def test_empty_or_non_positive_distribution_predicts_nothing() -> None:
    chain = MarkovChain(make_map())

    assert chain.predict({}) == {}
    assert chain.predict({"entry": 0, "hall": -1}) == {}


def test_zero_smoothing_without_counts_falls_back_to_equal_probabilities() -> None:
    chain = MarkovChain(make_map(), smoothing=0)

    assert chain.probabilities("entry") == {
        "hall": pytest.approx(0.5),
        "kitchen": pytest.approx(0.5),
    }


def test_route_counts_are_finite_and_saturate_at_the_declared_bound() -> None:
    chain = MarkovChain(make_map())
    chain.restore_counts(
        {
            "entry": {
                "hall": float("inf"),
                "kitchen": MARKOV_COUNT_LIMIT + 1,
            }
        }
    )
    assert chain.counts["entry"] == {"hall": 0.0, "kitchen": 0.0}

    assert chain.observe("entry", "hall", MARKOV_COUNT_LIMIT)
    assert chain.observe("entry", "hall", 1.0)
    assert chain.counts["entry"]["hall"] == MARKOV_COUNT_LIMIT
