from __future__ import annotations

import math
import random
from decimal import Decimal, localcontext

import pytest

from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
    OneOccupantMoveOperator,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    CompactPosterior,
    StateSpace,
)
from tests.oracle.exact_inference import (
    enumerate_configurations,
    transition_decimal,
)
from tests.oracle.exact_inference import (
    transition as oracle_transition,
)


@pytest.mark.parametrize("occupants", range(6))
def test_optimized_transitions_match_independent_oracle(occupants: int) -> None:
    random_source = random.Random(91_007 + occupants)
    space = StateSpace(("alpha", "beta", "gamma"), occupants)
    operators = CompleteMoveOperators(space)
    oracle_configurations = enumerate_configurations(
        len(space.locations),
        occupants,
    )
    assert set(oracle_configurations) == set(space.configurations)

    for _ in range(20):
        posterior = CompactPosterior(
            space,
            (random_source.random() for _ in space.configurations),
        )
        move_weights = {
            (source_index, target_index): random_source.random()
            for source_index in range(len(space.locations))
            for target_index in range(len(space.locations))
            if source_index != target_index and random_source.random() < 0.35
        }
        stay_weight = random_source.random()

        actual = operators.transition(
            posterior,
            move_weights,
            stay_weight=stay_weight,
        )
        oracle_input = tuple(
            posterior[space.rank(configuration)]
            for configuration in oracle_configurations
        )
        expected = oracle_transition(
            oracle_configurations,
            oracle_input,
            move_weights,
            stay_weight=stay_weight,
        )

        assert actual.normalization == pytest.approx(1.0, abs=1e-12)
        assert tuple(actual) == pytest.approx(
            tuple(
                expected[oracle_configurations.index(configuration)]
                for configuration in space.configurations
            ),
            abs=1e-12,
        )


def test_operator_preserves_count_and_weights_source_multiplicity() -> None:
    space = StateSpace(("alpha", "beta"), 2)
    operators = CompleteMoveOperators(space)
    posterior = CompactPosterior.certain(space, (2, 0, 0))

    moved = operators.transition(
        posterior,
        {(0, 1): 1.0},
        stay_weight=1.0,
    )

    assert moved[space.rank((2, 0, 0))] == pytest.approx(1 / 3)
    assert moved[space.rank((1, 1, 0))] == pytest.approx(2 / 3)
    assert all(
        sum(configuration) == 2
        for probability, configuration in zip(
            moved,
            space.configurations,
            strict=True,
        )
        if probability > 0.0
    )


@pytest.mark.parametrize("occupants", range(6))
def test_log_transitions_match_independent_decimal_oracle(occupants: int) -> None:
    random_source = random.Random(117_000 + occupants)
    space = StateSpace(("alpha", "beta"), occupants)
    operators = CompleteMoveOperators(space)

    with localcontext() as context:
        context.prec = 60
        for trace_index in range(20):
            weights = {
                configuration: Decimal(str(random_source.uniform(0.01, 1.0)))
                for configuration in enumerate_configurations(
                    len(space.locations),
                    occupants,
                )
            }
            total = sum(weights.values(), Decimal(0))
            oracle_posterior = {
                configuration: weight / total
                for configuration, weight in weights.items()
            }
            optimized = CompactLogPosterior(
                space,
                (
                    math.log(float(oracle_posterior[configuration]))
                    for configuration in space.configurations
                ),
            )
            move_weights = {
                move: Decimal(str(10.0 ** random_source.uniform(-120.0, 120.0)))
                for move in (
                    (source_index, target_index)
                    for source_index in range(len(space.locations))
                    for target_index in range(len(space.locations))
                    if source_index != target_index
                )
                if random_source.random() < 0.5
            }
            if trace_index == 0:
                move_weights[(0, 1)] = Decimal(0)
            stay_weight = (
                Decimal(0)
                if trace_index == 1 and occupants > 0
                else Decimal(str(10.0 ** random_source.uniform(-120.0, 120.0)))
            )

            actual = operators.transition_log(
                optimized,
                {
                    move: math.log(float(weight)) if weight else -math.inf
                    for move, weight in move_weights.items()
                },
                stay_log_weight=(
                    math.log(float(stay_weight)) if stay_weight else -math.inf
                ),
            )
            expected = transition_decimal(
                oracle_posterior,
                move_weights,
                stay_weight=stay_weight,
            )

            assert actual.normalization == pytest.approx(1.0, abs=1e-12)
            assert tuple(math.exp(value) for value in actual) == pytest.approx(
                tuple(
                    float(expected[configuration])
                    for configuration in space.configurations
                ),
                abs=2e-12,
            )


def test_reference_n5_operator_tables_are_complete_and_compact() -> None:
    space = StateSpace(tuple(f"zone_{index}" for index in range(16)), 5)
    operators = CompleteMoveOperators(space)

    assert len(operators) == 17 * 16
    assert operators.storage_bytes == len(space) * len(operators) * 5
    assert operators.storage_bytes < 28_000_000


def test_operator_validation_rejects_invalid_inputs() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    operators = CompleteMoveOperators(space)
    posterior = CompactPosterior.uniform(space)
    log_posterior = CompactLogPosterior.uniform(space)

    with pytest.raises(IndexError, match="Source"):
        OneOccupantMoveOperator.build(space, -1, 0)
    with pytest.raises(IndexError, match="Target"):
        OneOccupantMoveOperator.build(space, 0, 3)
    with pytest.raises(ValueError, match="must differ"):
        OneOccupantMoveOperator.build(space, 0, 0)
    with pytest.raises(KeyError, match="No move"):
        operators.operator(0, 0)
    with pytest.raises(ValueError, match="share"):
        operators.transition(
            CompactPosterior.uniform(StateSpace(("alpha", "beta"), 1)),
            {},
        )
    with pytest.raises(ValueError, match="Stay"):
        operators.transition(posterior, {}, stay_weight=math.inf)
    with pytest.raises(ValueError, match="Move"):
        operators.transition(posterior, {(0, 1): -1.0})
    assert tuple(operators.transition(posterior, {(0, 1): 0.0})) == pytest.approx(
        tuple(posterior)
    )
    with pytest.raises(ValueError, match="share"):
        operators.transition_log(
            CompactLogPosterior.uniform(StateSpace(("alpha", "beta"), 1)),
            {},
        )
    with pytest.raises(ValueError, match="Stay log"):
        operators.transition_log(log_posterior, {}, stay_log_weight=math.nan)
    with pytest.raises(ValueError, match="Move log"):
        operators.transition_log(log_posterior, {(0, 1): math.inf})
    with pytest.raises(ValueError, match="finite probability mass"):
        operators.transition_log(
            log_posterior,
            {(0, 1): -math.inf},
            stay_log_weight=-math.inf,
        )


def test_log_transition_skips_zero_predecessor_and_infeasible_move_mass() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))

    moved = CompleteMoveOperators(space).transition_log(
        posterior,
        {(0, 1): 0.0, (1, 0): 0.0},
        stay_log_weight=-math.inf,
    )

    assert moved[space.rank((0, 1, 0))] == 0.0
    assert all(
        value == -math.inf
        for rank, value in enumerate(moved)
        if rank != space.rank((0, 1, 0))
    )
