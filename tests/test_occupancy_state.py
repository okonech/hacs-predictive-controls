from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.occupancy_state import (
    HypothesisKey,
    PositionState,
    Posterior,
    canonical_hypothesis,
    cold_start_posterior,
    deterministic_prune,
    hypothesis_sort_key,
    initial_posterior,
    log_sum_exp,
    normalize_hypotheses,
    position_sort_key,
    probability_sum,
    zone_marginals,
)

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def test_joint_state_canonicalizes_normalizes_and_derives_marginals() -> None:
    office = PositionState("office", "hall", NOW)
    kitchen = PositionState("kitchen")
    joined = canonical_hypothesis((office, office))
    separated = canonical_hypothesis((kitchen, office))

    assert canonical_hypothesis((office, kitchen)) == separated
    assert joined.positions == (office, office)
    assert position_sort_key(PositionState(None)) > position_sort_key(kitchen)
    assert hypothesis_sort_key(separated) == tuple(
        position_sort_key(position) for position in separated.positions
    )

    posterior = normalize_hypotheses(
        {joined: math.log(0.25), separated: math.log(0.75)}, NOW
    )
    occupied, counts = zone_marginals(posterior, ("office", "kitchen"))

    assert probability_sum(posterior) == pytest.approx(1.0)
    assert occupied == pytest.approx({"office": 1.0, "kitchen": 0.75})
    assert counts["office"] == pytest.approx((0.0, 0.75, 0.25))
    assert counts["kitchen"] == pytest.approx((0.25, 0.75, 0.0))


def test_joint_state_validates_impossible_inputs_and_empty_marginals() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        initial_posterior(-1, NOW)
    with pytest.raises(ValueError, match="at least one hypothesis"):
        normalize_hypotheses({}, NOW)
    for invalid in (math.nan, math.inf):
        with pytest.raises(ValueError, match=r"NaN or \+infinity"):
            normalize_hypotheses({HypothesisKey(()): invalid}, NOW)
    with pytest.raises(ValueError, match="must be possible"):
        normalize_hypotheses({HypothesisKey(()): -math.inf}, NOW)

    assert log_sum_exp(()) == -math.inf
    assert log_sum_exp((-math.inf,)) == -math.inf
    assert zone_marginals(Posterior((), NOW), ("office",)) == (
        {"office": 0},
        {"office": (0.0,)},
    )
    assert initial_posterior(0, NOW).hypotheses[0].key.positions == ()
    with pytest.raises(ValueError, match="non-negative"):
        cold_start_posterior(("office",), -1, NOW)
    with pytest.raises(ValueError, match="finite and positive"):
        cold_start_posterior(("office",), 1, NOW, unlocated_weight=0.0)


def test_deterministic_pruning_reports_mass_and_honors_limits() -> None:
    weights = {
        canonical_hypothesis((PositionState(f"zone_{number}"),)): math.log(weight)
        for number, weight in enumerate((0.4, 0.3, 0.2, 0.1))
    }
    posterior = normalize_hypotheses(weights, NOW)

    assert deterministic_prune(posterior, exact_limit=4) is posterior
    retained_mass = deterministic_prune(
        posterior,
        exact_limit=1,
        retained_probability=0.65,
        hard_limit=4,
    )
    hard_limited = deterministic_prune(
        posterior,
        exact_limit=1,
        retained_probability=1.0,
        hard_limit=1,
    )
    exhausted = deterministic_prune(
        posterior,
        exact_limit=1,
        retained_probability=1.1,
        hard_limit=10,
    )

    assert len(retained_mass.hypotheses) == 2
    assert retained_mass.pruned_probability == pytest.approx(0.3)
    assert probability_sum(retained_mass) == pytest.approx(1.0)
    assert len(hard_limited.hypotheses) == 1
    assert hard_limited.pruned_probability == pytest.approx(0.6)
    assert exhausted.pruned_probability == pytest.approx(0.0)
