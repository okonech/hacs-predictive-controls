from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
)
from custom_components.predictive_controls.inference.count_transition import (
    CountTransitionKernel,
    LogCountTransitionKernel,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    CompactPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import (
    AugmentedStateKey,
    EndpointAssignmentAtom,
    SupportEventAtom,
)
from tests.oracle.exact_inference import (
    decrease_count,
    enumerate_configurations,
    increase_count,
)


@pytest.mark.parametrize("occupants", range(5))
def test_count_increase_matches_independent_oracle(occupants: int) -> None:
    random_source = random.Random(41_000 + occupants)
    space = StateSpace(("alpha", "beta"), occupants)
    posterior = CompactPosterior(
        space,
        (random_source.random() for _ in space.configurations),
    )
    arrival_prior = (0.2, 0.3, 0.5)

    actual = CountTransitionKernel.increase(posterior, arrival_prior)
    oracle_configurations = enumerate_configurations(3, occupants)
    oracle_input = tuple(
        posterior[space.rank(configuration)] for configuration in oracle_configurations
    )
    target_configurations, expected = increase_count(
        oracle_configurations,
        oracle_input,
        arrival_prior,
    )

    assert actual.space.occupants == occupants + 1
    assert actual.normalization == pytest.approx(1.0, abs=1e-12)
    assert tuple(actual) == pytest.approx(
        tuple(
            expected[target_configurations.index(configuration)]
            for configuration in actual.space.configurations
        ),
        abs=1e-12,
    )


@pytest.mark.parametrize("occupants", range(1, 6))
def test_count_decrease_matches_exchangeable_oracle(occupants: int) -> None:
    random_source = random.Random(52_000 + occupants)
    space = StateSpace(("alpha", "beta"), occupants)
    posterior = CompactPosterior(
        space,
        (random_source.random() for _ in space.configurations),
    )
    exit_weights = (0.7, 0.2, 0.1)

    actual = CountTransitionKernel.decrease(posterior, exit_weights)
    oracle_configurations = enumerate_configurations(3, occupants)
    oracle_input = tuple(
        posterior[space.rank(configuration)] for configuration in oracle_configurations
    )
    target_configurations, expected = decrease_count(
        oracle_configurations,
        oracle_input,
        exit_weights,
    )

    assert actual.space.occupants == occupants - 1
    assert actual.normalization == pytest.approx(1.0, abs=1e-12)
    assert tuple(actual) == pytest.approx(
        tuple(
            expected[target_configurations.index(configuration)]
            for configuration in actual.space.configurations
        ),
        abs=1e-12,
    )


def test_default_count_kernels_are_anonymous_and_unlocated() -> None:
    empty_space = StateSpace(("alpha", "beta"), 0)
    empty = CompactPosterior.certain(empty_space, (0, 0, 0))

    arrived = CountTransitionKernel.increase(empty)
    assert arrived[arrived.space.rank((0, 0, 1))] == 1.0

    colocated = CompactPosterior.certain(
        StateSpace(("alpha", "beta"), 2),
        (1, 1, 0),
    )
    departed = CountTransitionKernel.decrease(colocated)
    assert departed[departed.space.rank((1, 0, 0))] == pytest.approx(0.5)
    assert departed[departed.space.rank((0, 1, 0))] == pytest.approx(0.5)


def test_multistep_reconciliation_is_deterministic_through_all_counts() -> None:
    start = CompactPosterior.certain(
        StateSpace(("alpha", "beta"), 0),
        (0, 0, 0),
    )

    five = CountTransitionKernel.reconcile(start, 5)
    zero = CountTransitionKernel.reconcile(five, 0)

    assert five.space.occupants == 5
    assert five[five.space.rank((0, 0, 5))] == 1.0
    assert zero.space.occupants == 0
    assert tuple(zero) == (1.0,)


def test_count_kernel_validation_rejects_invalid_controls() -> None:
    empty = CompactPosterior.certain(
        StateSpace(("alpha",), 0),
        (0, 0),
    )
    full = CompactPosterior.certain(
        StateSpace(("alpha",), 5),
        (5, 0),
    )
    occupied = CompactPosterior.certain(
        StateSpace(("alpha",), 1),
        (1, 0),
    )

    with pytest.raises(ValueError, match="maximum"):
        CountTransitionKernel.increase(full)
    with pytest.raises(ValueError, match="empty"):
        CountTransitionKernel.decrease(empty)
    with pytest.raises(ValueError, match="dimension"):
        CountTransitionKernel.increase(empty, (1.0,))
    with pytest.raises(ValueError, match="finite"):
        CountTransitionKernel.increase(empty, (float("nan"), 1.0))
    with pytest.raises(ValueError, match="positive"):
        CountTransitionKernel.increase(empty, (0.0, 0.0))
    with pytest.raises(ValueError, match="exclude"):
        CountTransitionKernel.decrease(occupied, (0.0, 1.0))
    with pytest.raises(ValueError, match="Target count"):
        CountTransitionKernel.reconcile(empty, 6)


@pytest.mark.parametrize("occupants", range(6))
def test_log_count_kernels_match_probability_domain_exactly(occupants: int) -> None:
    random_source = random.Random(63_000 + occupants)
    space = StateSpace(("alpha", "beta"), occupants)
    weights = tuple(random_source.random() for _ in space.configurations)
    probability = CompactPosterior(space, weights)
    logarithmic = CompactLogPosterior(space, (math.log(value) for value in weights))

    if occupants < 5:
        expected_increase = CountTransitionKernel.increase(
            probability,
            (0.2, 0.3, 0.5),
        )
        actual_increase = LogCountTransitionKernel.increase(
            logarithmic,
            (0.2, 0.3, 0.5),
        )
        assert tuple(math.exp(value) for value in actual_increase) == pytest.approx(
            tuple(expected_increase),
            abs=1e-12,
        )
    if occupants > 0:
        expected_decrease = CountTransitionKernel.decrease(
            probability,
            (0.7, 0.2, 0.1),
        )
        actual_decrease = LogCountTransitionKernel.decrease(
            logarithmic,
            (0.7, 0.2, 0.1),
        )
        assert tuple(math.exp(value) for value in actual_decrease) == pytest.approx(
            tuple(expected_decrease),
            abs=1e-12,
        )


def test_log_count_reconciliation_and_boundaries_match_contract() -> None:
    empty = CompactLogPosterior.certain(
        StateSpace(("alpha",), 0),
        (0, 0),
    )
    five = LogCountTransitionKernel.reconcile(empty, 5)
    assert five[five.space.rank((0, 5))] == 0.0
    assert LogCountTransitionKernel.reconcile(five, 0).normalization == 1.0
    with pytest.raises(ValueError, match="maximum"):
        LogCountTransitionKernel.increase(five)
    with pytest.raises(ValueError, match="empty"):
        LogCountTransitionKernel.decrease(empty)
    with pytest.raises(ValueError, match="Target count"):
        LogCountTransitionKernel.reconcile(empty, -1)


def test_log_count_decrease_skips_zero_mass_and_zero_weight_paths() -> None:
    posterior = CompactLogPosterior.certain(
        StateSpace(("alpha", "beta"), 2),
        (1, 1, 0),
    )

    decreased = LogCountTransitionKernel.decrease(
        posterior,
        (1.0, 0.0, 0.0),
    )

    assert decreased[decreased.space.rank((0, 1, 0))] == 0.0

    excluded = CompactLogPosterior.certain(
        StateSpace(("alpha",), 1),
        (1, 0),
    )
    with pytest.raises(ValueError, match="exclude"):
        LogCountTransitionKernel.decrease(excluded, (0.0, 1.0))


def test_augmented_count_reconciliation_preserves_support_strata() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    space = StateSpace(("alpha",), 1)
    support = SupportEventAtom(
        "support",
        "graph_valid",
        "alpha",
        "alpha",
        ("node-a",),
        ("endpoint",),
        ("episode",),
        now,
        now + timedelta(minutes=1),
        True,
    )
    context = EndpointAssignmentAtom(
        "endpoint",
        "stay:endpoint",
        "stay",
        0,
        0,
        None,
        0,
        None,
        "node-a",
        (),
        now,
        ("evidence",),
    )
    message = AugmentedLogMessage(
        space,
        (
            (
                AugmentedStateKey(0, contexts=(context,), supports=(support,)),
                math.log(0.3),
            ),
            (AugmentedStateKey(0), math.log(0.7)),
        ),
    )

    increased = LogCountTransitionKernel.reconcile_augmented(message, 3)
    restored = LogCountTransitionKernel.reconcile_augmented(increased, 0)

    assert increased.space.occupants == 3
    assert all(not key.contexts for key, _ in increased.entries)
    increased_support = increased.support_probability(
        lambda key: support in key.supports
    )
    assert increased_support == pytest.approx(
        0.3,
        abs=1e-12,
    )
    assert restored.space.occupants == 0
    restored_support = restored.support_probability(lambda key: support in key.supports)
    assert restored_support == pytest.approx(
        0.3,
        abs=1e-12,
    )
    assert restored.normalization == pytest.approx(1.0, abs=1e-12)
