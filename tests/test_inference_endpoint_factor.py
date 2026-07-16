from __future__ import annotations

import math
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast

import pytest

from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
    EndpointFactor,
)
from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import (
    AugmentedStateKey,
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    MovementDisposition,
    SupportEventAtom,
)
from tests.oracle.exact_inference import (
    DecimalAugmentedKey,
    DecimalEndpointKey,
    augmented_endpoint_factor_decimal,
    endpoint_factor_decimal,
    enumerate_configurations,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(seconds=30)


def alternative(
    alternative_id: str,
    disposition: MovementDisposition,
    source_index: int | None,
    weight: Decimal,
) -> EndpointAlternative:
    return EndpointAlternative(
        alternative_id,
        disposition,
        source_index,
        None if source_index is None else f"source-{source_index}",
        () if source_index is None else (f"source-{source_index}", "target-node"),
        math.log(float(weight)) if weight else -math.inf,
        DEADLINE,
        ("target-endpoint",),
    )


def factor(
    alternatives: tuple[EndpointAlternative, ...],
    *,
    endpoint_id: str = "target-endpoint",
    target_index: int = 2,
    empty_likelihood: Decimal = Decimal("0.2"),
    occupied_likelihood: Decimal = Decimal("0.9"),
) -> EndpointFactor:
    return EndpointFactor(
        EndpointToken(endpoint_id, "target-node", NOW),
        target_index,
        "gamma",
        alternatives,
        math.log(float(empty_likelihood)),
        math.log(float(occupied_likelihood)),
    )


def production_endpoint_probabilities(
    message: AugmentedLogMessage,
) -> dict[DecimalEndpointKey, float]:
    output: dict[DecimalEndpointKey, float] = {}
    for key, log_mass in message.entries:
        atom = key.contexts[-1]
        output[
            (
                message.space.unrank(key.occupancy_rank),
                message.space.unrank(atom.predecessor_rank),
                atom.alternative_id,
            )
        ] = math.exp(log_mass)
    return output


def production_augmented_probabilities(
    message: AugmentedLogMessage,
) -> dict[DecimalAugmentedKey, float]:
    return {
        (
            message.space.unrank(key.occupancy_rank),
            tuple(
                (
                    atom.endpoint_id,
                    message.space.unrank(atom.predecessor_rank),
                    atom.alternative_id,
                )
                for atom in key.contexts
            ),
        ): math.exp(log_mass)
        for key, log_mass in message.entries
    }


@pytest.mark.parametrize("occupants", range(6))
def test_endpoint_factor_matches_independent_decimal_oracle(occupants: int) -> None:
    random_source = random.Random(221_000 + occupants)
    space = StateSpace(("alpha", "beta", "gamma"), occupants)
    operators = CompleteMoveOperators(space)
    configurations = enumerate_configurations(len(space.locations), occupants)

    with localcontext() as context:
        context.prec = 70
        for trace_index in range(12):
            raw = {
                configuration: Decimal(str(random_source.uniform(0.01, 1.0)))
                for configuration in configurations
            }
            total = sum(raw.values(), Decimal(0))
            oracle_posterior = {
                configuration: weight / total
                for configuration, weight in raw.items()
            }
            optimized = CompactLogPosterior(
                space,
                (
                    math.log(float(oracle_posterior[configuration]))
                    for configuration in space.configurations
                ),
            )
            weights = (
                Decimal(str(10.0 ** random_source.uniform(-80.0, 80.0))),
                Decimal(0)
                if trace_index == 0
                else Decimal(str(10.0 ** random_source.uniform(-80.0, 80.0))),
                Decimal(str(10.0 ** random_source.uniform(-80.0, 80.0))),
                Decimal(str(10.0 ** random_source.uniform(-80.0, 80.0))),
            )
            empty_likelihood = Decimal(str(random_source.uniform(0.01, 0.4)))
            occupied_likelihood = Decimal(str(random_source.uniform(0.6, 0.99)))
            declarations = (
                ("stay", None, weights[0]),
                ("from-alpha", 0, weights[1]),
                ("from-beta", 1, weights[2]),
                ("from-unlocated", space.unlocated_index, weights[3]),
            )
            endpoint_factor = factor(
                (
                    alternative("stay", "stay", None, weights[0]),
                    alternative("from-alpha", "graph_valid", 0, weights[1]),
                    alternative("from-beta", "missed_movement", 1, weights[2]),
                    alternative(
                        "from-unlocated",
                        "unlocated",
                        space.unlocated_index,
                        weights[3],
                    ),
                ),
                empty_likelihood=empty_likelihood,
                occupied_likelihood=occupied_likelihood,
            )

            actual = endpoint_factor.apply(
                AugmentedLogMessage.from_posterior(optimized),
                operators,
            )
            expected = endpoint_factor_decimal(
                oracle_posterior,
                2,
                declarations,
                empty_likelihood=empty_likelihood,
                occupied_likelihood=occupied_likelihood,
            )
            actual_probabilities = production_endpoint_probabilities(actual)

            assert actual_probabilities.keys() == expected.keys()
            assert tuple(actual_probabilities.values()) == pytest.approx(
                tuple(float(expected[key]) for key in actual_probabilities),
                abs=2e-12,
            )
            assert actual.normalization == pytest.approx(1.0, abs=1e-12)
            assert actual.occupancy_posterior().normalization == pytest.approx(
                1.0,
                abs=1e-12,
            )


@pytest.mark.parametrize("occupants", range(6))
def test_multi_endpoint_factor_dag_matches_decimal_oracle(occupants: int) -> None:
    random_source = random.Random(337_000 + occupants)
    space = StateSpace(("alpha", "beta", "gamma"), occupants)
    operators = CompleteMoveOperators(space)
    configurations = enumerate_configurations(len(space.locations), occupants)

    with localcontext() as context:
        context.prec = 70
        for trace_index in range(4):
            raw = {
                configuration: Decimal(str(random_source.uniform(0.01, 1.0)))
                for configuration in configurations
            }
            total = sum(raw.values(), Decimal(0))
            oracle: dict[DecimalAugmentedKey, Decimal] = {
                (configuration, ()): weight / total
                for configuration, weight in raw.items()
            }
            production = AugmentedLogMessage.from_posterior(
                CompactLogPosterior(
                    space,
                    (
                        math.log(float(oracle[(configuration, ())]))
                        for configuration in space.configurations
                    ),
                )
            )

            for endpoint_index, target_index in enumerate((2, 0, 1)):
                endpoint_id = f"endpoint-{trace_index}-{endpoint_index}"
                source_indices = tuple(
                    index
                    for index in range(len(space.locations))
                    if index != target_index
                )
                weights = tuple(
                    Decimal(0)
                    if trace_index == 0 and branch_index == 1
                    else Decimal(str(10.0 ** random_source.uniform(-12.0, 12.0)))
                    for branch_index in range(4)
                )
                empty_likelihood = Decimal(str(random_source.uniform(0.05, 0.4)))
                occupied_likelihood = Decimal(str(random_source.uniform(0.6, 0.98)))
                declarations = (
                    ("stay", None, weights[0]),
                    *tuple(
                        (f"from-{source_index}", source_index, weights[offset + 1])
                        for offset, source_index in enumerate(source_indices)
                    ),
                )
                endpoint_factor = factor(
                    (
                        alternative("stay", "stay", None, weights[0]),
                        *tuple(
                            alternative(
                                f"from-{source_index}",
                                "graph_valid",
                                source_index,
                                weights[offset + 1],
                            )
                            for offset, source_index in enumerate(source_indices)
                        ),
                    ),
                    endpoint_id=endpoint_id,
                    target_index=target_index,
                    empty_likelihood=empty_likelihood,
                    occupied_likelihood=occupied_likelihood,
                )
                production = endpoint_factor.apply(production, operators)
                oracle = augmented_endpoint_factor_decimal(
                    oracle,
                    endpoint_id,
                    target_index,
                    declarations,
                    empty_likelihood=empty_likelihood,
                    occupied_likelihood=occupied_likelihood,
                )

            actual = production_augmented_probabilities(production)
            assert actual.keys() == oracle.keys()
            assert tuple(actual.values()) == pytest.approx(
                tuple(float(oracle[key]) for key in actual),
                abs=3e-12,
            )
            assert production.normalization == pytest.approx(1.0, abs=1e-12)


def test_competing_sources_are_disjoint_and_move_only_one_occupant() -> None:
    space = StateSpace(("alpha", "beta", "gamma"), 2)
    message = AugmentedLogMessage.from_posterior(
        CompactLogPosterior.certain(space, (1, 1, 0, 0))
    )
    applied = factor(
        (
            alternative("stay", "stay", None, Decimal(1)),
            alternative("alpha", "graph_valid", 0, Decimal(1)),
            alternative("beta", "graph_valid", 1, Decimal(1)),
        )
    ).apply(message, CompleteMoveOperators(space))

    alternatives = {key.contexts[-1].alternative_id for key, _ in applied.entries}
    assert alternatives == {"stay", "alpha", "beta"}
    assert all(len(key.contexts) == 1 for key, _ in applied.entries)
    assert all(sum(space.unrank(key.occupancy_rank)) == 2 for key, _ in applied.entries)
    assert not any(
        space.unrank(key.occupancy_rank) == (0, 0, 2, 0)
        for key, _ in applied.entries
    )


def test_existing_context_and_support_pass_through_and_block_endpoint_reuse() -> None:
    space = StateSpace(("alpha", "beta", "gamma"), 1)
    old_context = EndpointAssignmentAtom(
        "old-endpoint",
        "old-stay",
        "stay",
        0,
        0,
        None,
        0,
        None,
        "old-node",
        (),
        DEADLINE,
        ("old-evidence",),
    )
    support = SupportEventAtom(
        "support-1",
        "graph_valid",
        "alpha",
        "beta",
        ("alpha-node", "beta-node"),
        ("support-endpoint",),
        ("episode-1",),
        NOW,
        DEADLINE,
        True,
    )
    message = AugmentedLogMessage(
        space,
        ((AugmentedStateKey(0, (old_context,), (support,)), 0.0),),
    )
    applied = factor(
        (alternative("stay", "stay", None, Decimal(1)),),
    ).apply(message, CompleteMoveOperators(space))

    key = applied.entries[0][0]
    assert old_context in key.contexts
    assert support in key.supports
    assert len(key.contexts) == 2
    with pytest.raises(ValueError, match="already present"):
        factor(
            (alternative("stay", "stay", None, Decimal(1)),),
            endpoint_id="old-endpoint",
        ).apply(message, CompleteMoveOperators(space))
    with pytest.raises(ValueError, match="already present"):
        factor(
            (alternative("stay", "stay", None, Decimal(1)),),
            endpoint_id="support-endpoint",
        ).apply(message, CompleteMoveOperators(space))


def test_augmented_message_merges_duplicate_keys_and_validates_mass() -> None:
    space = StateSpace(("alpha",), 1)
    key = AugmentedStateKey(0)
    message = AugmentedLogMessage(space, ((key, math.log(2)), (key, math.log(3))))
    assert message.entries == ((key, 0.0),)
    with pytest.raises(ValueError, match="out of range"):
        AugmentedLogMessage(space, ((AugmentedStateKey(len(space)), 0.0),))
    with pytest.raises(ValueError, match="finite or negative"):
        AugmentedLogMessage(space, ((key, math.nan),))
    with pytest.raises(ValueError, match="finite probability mass"):
        AugmentedLogMessage(space, ((key, -math.inf),))


def test_endpoint_type_and_factor_validation() -> None:
    with pytest.raises(ValueError, match="alternative ID"):
        alternative("", "stay", None, Decimal(1))
    with pytest.raises(ValueError, match="disposition"):
        alternative("bad", cast(MovementDisposition, "invalid"), None, Decimal(1))
    with pytest.raises(ValueError, match="must not declare"):
        EndpointAlternative("stay", "stay", 0, "source", (), 0.0, DEADLINE, ())
    with pytest.raises(ValueError, match="valid source"):
        EndpointAlternative("move", "graph_valid", None, None, (), 0.0, DEADLINE, ())
    with pytest.raises(ValueError, match="finite or negative"):
        EndpointAlternative(
            "move", "graph_valid", 0, "source", (), math.inf, DEADLINE, ()
        )
    with pytest.raises(ValueError, match="route nodes"):
        EndpointAlternative(
            "move", "graph_valid", 0, "source", ("",), 0.0, DEADLINE, ()
        )
    with pytest.raises(ValueError, match="evidence IDs"):
        EndpointAlternative(
            "move", "graph_valid", 0, "source", (), 0.0, DEADLINE, ("",)
        )

    stay = alternative("stay", "stay", None, Decimal(1))
    with pytest.raises(ValueError, match="valid target"):
        EndpointFactor(EndpointToken("e", "n", NOW), -1, "gamma", (stay,), 0.0, 0.0)
    with pytest.raises(ValueError, match="requires alternatives"):
        EndpointFactor(EndpointToken("e", "n", NOW), 0, "alpha", (), 0.0, 0.0)
    with pytest.raises(ValueError, match="unique"):
        factor((stay, stay))
    with pytest.raises(ValueError, match="exactly one"):
        factor((alternative("move", "graph_valid", 0, Decimal(1)),))
    with pytest.raises(ValueError, match="finite weight"):
        factor((alternative("stay", "stay", None, Decimal(0)),))
    with pytest.raises(ValueError, match="cannot precede"):
        factor(
            (
                EndpointAlternative(
                    "stay",
                    "stay",
                    None,
                    None,
                    (),
                    0.0,
                    NOW - timedelta(microseconds=1),
                    (),
                ),
            )
        )
    with pytest.raises(ValueError, match="likelihoods"):
        EndpointFactor(EndpointToken("e", "n", NOW), 0, "alpha", (stay,), math.nan, 0.0)


def test_assignment_support_and_augmented_key_validation() -> None:
    assignment = EndpointAssignmentAtom(
        "endpoint",
        "stay",
        "stay",
        0,
        0,
        None,
        0,
        None,
        "target",
        (),
        DEADLINE,
        (),
    )
    with pytest.raises(ValueError, match="IDs must be non-empty"):
        replace(assignment, endpoint_id="")
    with pytest.raises(ValueError, match="disposition"):
        replace(assignment, disposition=cast(MovementDisposition, "invalid"))
    with pytest.raises(ValueError, match="indexes"):
        replace(assignment, predecessor_rank=-1)
    with pytest.raises(ValueError, match="must not declare"):
        replace(assignment, source_index=0)
    with pytest.raises(ValueError, match="valid source"):
        replace(assignment, disposition="graph_valid")
    with pytest.raises(ValueError, match="valid source"):
        replace(
            assignment,
            disposition="graph_valid",
            source_index=-1,
            source_node_id="source",
        )
    with pytest.raises(ValueError, match="valid source"):
        replace(
            assignment,
            disposition="graph_valid",
            source_index=0,
            source_node_id="",
        )
    with pytest.raises(ValueError, match="target node"):
        replace(assignment, target_node_id="")
    with pytest.raises(ValueError, match="UTC"):
        replace(assignment, deadline=datetime(2026, 7, 21))

    support = SupportEventAtom(
        "support",
        "graph_valid",
        "alpha",
        "beta",
        (),
        ("endpoint",),
        (),
        NOW,
        DEADLINE,
        True,
    )
    with pytest.raises(ValueError, match="zone IDs"):
        replace(support, support_event_id="")
    with pytest.raises(ValueError, match="zone IDs"):
        replace(support, origin_zone="")
    with pytest.raises(ValueError, match="zone IDs"):
        replace(support, destination_zone="")
    with pytest.raises(ValueError, match="disposition"):
        replace(support, disposition=cast(MovementDisposition, "invalid"))
    with pytest.raises(ValueError, match="endpoint IDs"):
        replace(support, endpoint_ids=("",))
    with pytest.raises(ValueError, match="UTC"):
        replace(support, valid_from=datetime(2026, 7, 21))
    with pytest.raises(ValueError, match="UTC"):
        replace(support, valid_until=datetime(2026, 7, 21))
    with pytest.raises(ValueError, match="must not exceed"):
        replace(support, valid_from=DEADLINE, valid_until=NOW)
    with pytest.raises(ValueError, match="rank"):
        AugmentedStateKey(-1)


def test_endpoint_apply_validation() -> None:
    space = StateSpace(("alpha", "beta", "gamma"), 1)
    message = AugmentedLogMessage.from_posterior(CompactLogPosterior.uniform(space))
    operators = CompleteMoveOperators(space)
    stay = alternative("stay", "stay", None, Decimal(1))
    with pytest.raises(ValueError, match="share"):
        factor((stay,)).apply(
            message,
            CompleteMoveOperators(StateSpace(("alpha", "beta", "gamma"), 1)),
        )
    with pytest.raises(IndexError, match="target"):
        factor((stay,), target_index=3).apply(message, operators)
    with pytest.raises(IndexError, match="source"):
        factor((stay, alternative("move", "graph_valid", 4, Decimal(1)))).apply(
            message,
            operators,
        )
    with pytest.raises(ValueError, match="must differ"):
        factor((stay, alternative("move", "graph_valid", 2, Decimal(1)))).apply(
            message,
            operators,
        )
    with pytest.raises(ValueError, match="unlocated source"):
        factor((stay, alternative("move", "unlocated", 0, Decimal(1)))).apply(
            message,
            operators,
        )
