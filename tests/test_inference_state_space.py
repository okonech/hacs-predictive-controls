from __future__ import annotations

import math

import pytest

from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    CompactPosterior,
    StateSpace,
)


@pytest.mark.parametrize("occupants", range(6))
def test_state_space_enumerates_every_count_vector(occupants: int) -> None:
    space = StateSpace(("alpha", "beta", "gamma"), occupants)

    assert len(space) == math.comb(3 + occupants, occupants)
    assert len(set(space.configurations)) == len(space)
    assert all(
        sum(configuration) == occupants
        for configuration in space.configurations
    )
    assert all(
        space.unrank(space.rank(configuration)) == configuration
        for configuration in space.configurations
    )


def test_reference_state_space_contains_all_n5_configurations() -> None:
    space = StateSpace(tuple(f"zone_{index}" for index in range(16)), 5)

    assert len(space) == 20_349
    assert space.unrank(0) == (0,) * 16 + (5,)
    assert space.unrank(len(space) - 1) == (5,) + (0,) * 16


def test_compact_posterior_normalizes_and_computes_exact_marginals() -> None:
    space = StateSpace(("alpha", "beta"), 2)
    posterior = CompactPosterior(
        space,
        (
            3.0 if configuration == (1, 1, 0) else 1.0
            if configuration == (0, 0, 2)
            else 0.0
            for configuration in space.configurations
        ),
    )

    assert posterior.normalization == pytest.approx(1.0, abs=1e-12)
    assert posterior.occupied_marginals() == pytest.approx((0.75, 0.75))
    assert all(
        actual == pytest.approx(expected)
        for actual, expected in zip(
            posterior.count_marginals(),
            (
                (0.25, 0.75, 0.0),
                (0.25, 0.75, 0.0),
                (0.75, 0.0, 0.25),
            ),
            strict=True,
        )
    )
    assert posterior.storage_bytes == len(space) * 8


def test_state_space_and_posterior_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        StateSpace((), 1)
    with pytest.raises(ValueError, match="unique"):
        StateSpace(("alpha", "alpha"), 1)
    with pytest.raises(ValueError, match="between"):
        StateSpace(("alpha",), 6)

    space = StateSpace(("alpha", "beta"), 2)
    with pytest.raises(ValueError, match="dimension"):
        space.rank((2, 0))
    with pytest.raises(ValueError, match="non-negative"):
        space.rank((2, -1, 1))
    with pytest.raises(ValueError, match="conserve"):
        space.rank((1, 0, 0))
    with pytest.raises(IndexError, match="out of range"):
        space.unrank(len(space))
    with pytest.raises(IndexError, match="out of range"):
        space.unrank(-1)
    assert space.location_index("alpha") == 0
    assert space.location_index(None) == space.unlocated_index
    assert space.location_index("unlocated") == space.unlocated_index
    with pytest.raises(KeyError):
        space.location_index("missing")
    with pytest.raises(ValueError, match="dimension"):
        CompactPosterior(space, (1.0,))
    with pytest.raises(ValueError, match="finite"):
        CompactPosterior(space, (float("nan"),) * len(space))
    with pytest.raises(ValueError, match="positive"):
        CompactPosterior(space, (0.0,) * len(space))


def test_certain_and_uniform_posteriors_are_exact() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    certain = CompactPosterior.certain(space, (1, 0, 0))
    uniform = CompactPosterior.uniform(space)

    assert certain[space.rank((1, 0, 0))] == 1.0
    assert certain.occupied_marginals() == (1.0, 0.0)
    assert tuple(uniform) == pytest.approx((1 / 3, 1 / 3, 1 / 3))


def test_log_posterior_updates_complete_binary_zone_likelihood_exactly() -> None:
    space = StateSpace(("alpha", "beta"), 2)
    posterior = CompactLogPosterior.uniform(space).apply_zone_likelihood(
        0,
        empty_log_likelihood=math.log(0.1),
        occupied_log_likelihood=math.log(0.9),
    )

    expected_weights = tuple(
        0.9 if configuration[0] > 0 else 0.1
        for configuration in space.configurations
    )
    total = math.fsum(expected_weights)
    assert tuple(math.exp(value) for value in posterior) == pytest.approx(
        tuple(weight / total for weight in expected_weights),
        abs=1e-12,
    )
    assert posterior.normalization == pytest.approx(1.0, abs=1e-12)
    assert posterior.storage_bytes == len(space) * 8
    count_marginals = posterior.count_marginals()
    assert posterior.occupied_marginals() == pytest.approx(
        tuple(math.fsum(counts[1:]) for counts in count_marginals[:2]),
        abs=1e-12,
    )


def test_log_posterior_recovers_after_long_inverse_likelihood_trace() -> None:
    space = StateSpace(("alpha",), 1)
    posterior = CompactLogPosterior.uniform(space)
    for _ in range(2_000):
        posterior = posterior.apply_zone_likelihood(
            0,
            empty_log_likelihood=math.log(0.01),
            occupied_log_likelihood=math.log(0.99),
        )
    assert all(value != -math.inf for value in posterior)
    for _ in range(2_000):
        posterior = posterior.apply_zone_likelihood(
            0,
            empty_log_likelihood=math.log(0.99),
            occupied_log_likelihood=math.log(0.01),
        )

    assert tuple(math.exp(value) for value in posterior) == pytest.approx(
        (0.5, 0.5),
        abs=1e-12,
    )


def test_log_posterior_rejects_invalid_inputs() -> None:
    space = StateSpace(("alpha",), 1)
    with pytest.raises(ValueError, match="dimension"):
        CompactLogPosterior(space, (0.0,))
    with pytest.raises(ValueError, match="finite or negative infinity"):
        CompactLogPosterior(space, (0.0, math.inf))
    with pytest.raises(ValueError, match="finite probability mass"):
        CompactLogPosterior(space, (-math.inf, -math.inf))
    posterior = CompactLogPosterior.uniform(space)
    with pytest.raises(IndexError, match="zone index"):
        posterior.apply_zone_likelihood(
            1,
            empty_log_likelihood=0.0,
            occupied_log_likelihood=0.0,
        )
    with pytest.raises(ValueError, match="must be finite"):
        posterior.apply_zone_likelihood(
            0,
            empty_log_likelihood=math.nan,
            occupied_log_likelihood=0.0,
        )
