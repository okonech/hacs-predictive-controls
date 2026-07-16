from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import (
    AssignmentIdentity,
    AugmentedStateKey,
    EndpointAssignmentAtom,
    FinalizationSupport,
    SupportEventAtom,
)
from tests.oracle.exact_inference import project_augmented_decimal

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(seconds=10)


def assignment(
    alternative_id: str,
    predecessor_rank: int,
    successor_rank: int,
    *,
    endpoint_id: str = "endpoint",
    deadline: datetime = DEADLINE,
) -> EndpointAssignmentAtom:
    return EndpointAssignmentAtom(
        endpoint_id,
        alternative_id,
        "stay",
        predecessor_rank,
        successor_rank,
        None,
        0,
        None,
        "target",
        (),
        deadline,
        (endpoint_id,),
    )


def identity(atom: EndpointAssignmentAtom) -> AssignmentIdentity:
    return AssignmentIdentity(
        atom.endpoint_id,
        atom.alternative_id,
        atom.predecessor_rank,
        atom.successor_rank,
    )


def support(
    support_id: str,
    endpoint_id: str,
    *,
    valid_from: datetime = NOW,
    valid_until: datetime = DEADLINE + timedelta(seconds=10),
) -> SupportEventAtom:
    return SupportEventAtom(
        support_id,
        "graph_valid",
        "alpha",
        "beta",
        ("alpha-node", "beta-node"),
        (endpoint_id,),
        ("episode",),
        valid_from,
        valid_until,
        True,
    )


def probabilities(
    message: AugmentedLogMessage,
) -> dict[tuple[int, tuple[str, ...], tuple[str, ...]], float]:
    return {
        (
            key.occupancy_rank,
            tuple(atom.alternative_id for atom in key.contexts),
            tuple(atom.support_event_id for atom in key.supports),
        ): math.exp(log_mass)
        for key, log_mass in message.entries
    }


def test_finalization_strict_boundary_and_decimal_projection_parity() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    alpha = assignment("alpha", 0, 1)
    beta = assignment("beta", 2, 1)
    message = AugmentedLogMessage(
        space,
        (
            (AugmentedStateKey(1, (alpha,)), math.log(Decimal("0.3"))),
            (AugmentedStateKey(1, (beta,)), math.log(Decimal("0.2"))),
            (AugmentedStateKey(2, (alpha,)), math.log(Decimal("0.5"))),
        ),
    )

    assert message.finalize(DEADLINE).entries == message.entries
    finalized = message.finalize(DEADLINE + timedelta(microseconds=1))
    expected = project_augmented_decimal(
        (
            (1, ("alpha",), (), Decimal("0.3")),
            (1, ("beta",), (), Decimal("0.2")),
            (2, ("alpha",), (), Decimal("0.5")),
        ),
        frozenset({"alpha", "beta"}),
        {},
    )

    assert probabilities(finalized) == pytest.approx(
        {key: float(value) for key, value in expected.items()},
        abs=1e-12,
    )
    assert tuple(finalized.occupancy_posterior()) == pytest.approx(
        tuple(message.occupancy_posterior()),
        abs=1e-12,
    )
    assert finalized.normalization == pytest.approx(1.0, abs=1e-12)


def test_support_is_inserted_before_merge_and_remains_queryable() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    first = assignment("first", 0, 1, endpoint_id="endpoint-1")
    second = assignment("second", 2, 1, endpoint_id="endpoint-2")
    certificate = support("arrival", "endpoint-1")
    message = AugmentedLogMessage(
        space,
        (
            (AugmentedStateKey(1, (first,)), math.log(0.4)),
            (AugmentedStateKey(1, (second,)), math.log(0.6)),
        ),
    )

    finalized = message.finalize(
        DEADLINE + timedelta(microseconds=1),
        (
            FinalizationSupport(identity(first), certificate),
            FinalizationSupport(identity(second), None),
        ),
    )

    assert len(finalized.entries) == 2
    assert finalized.has_endpoint("endpoint-1")
    assert finalized.support_probability(
        lambda key: certificate in key.supports
    ) == pytest.approx(0.4)
    assert finalized.support_probability(lambda key: not key.supports) == pytest.approx(
        0.6
    )
    assert tuple(finalized.occupancy_posterior()) == pytest.approx(
        tuple(message.occupancy_posterior()),
        abs=1e-12,
    )


def test_partial_finalization_retains_newer_context_and_existing_support() -> None:
    space = StateSpace(("alpha",), 1)
    old = assignment("old", 0, 0, deadline=DEADLINE)
    newer = assignment(
        "new",
        0,
        0,
        endpoint_id="new-endpoint",
        deadline=DEADLINE + timedelta(seconds=5),
    )
    existing = support("existing", "existing-endpoint")
    message = AugmentedLogMessage(
        space,
        ((AugmentedStateKey(0, (newer, old), (existing,)), 0.0),),
    )

    finalized = message.finalize(DEADLINE + timedelta(microseconds=1))

    key = finalized.entries[0][0]
    assert key.contexts == (newer,)
    assert key.supports == (existing,)


def test_finalization_declaration_validation_is_atomic() -> None:
    space = StateSpace(("alpha",), 1)
    atom = assignment("stay", 0, 0)
    message = AugmentedLogMessage(
        space,
        ((AugmentedStateKey(0, (atom,)), 0.0),),
    )
    declaration = FinalizationSupport(identity(atom), support("valid", "endpoint"))

    with pytest.raises(ValueError, match="unique"):
        message.finalize(
            DEADLINE + timedelta(microseconds=1),
            (declaration, declaration),
        )
    with pytest.raises(ValueError, match="not used"):
        message.finalize(DEADLINE, (declaration,))
    with pytest.raises(ValueError, match="endpoint"):
        message.finalize(
            DEADLINE + timedelta(microseconds=1),
            (
                FinalizationSupport(
                    identity(atom),
                    support("wrong", "different-endpoint"),
                ),
            ),
        )
    with pytest.raises(ValueError, match="deadline"):
        message.finalize(
            DEADLINE + timedelta(microseconds=1),
            (
                FinalizationSupport(
                    identity(atom),
                    support(
                        "early",
                        "endpoint",
                        valid_until=DEADLINE - timedelta(microseconds=1),
                    ),
                ),
            ),
        )
    with pytest.raises(ValueError, match="deadline"):
        message.finalize(
            DEADLINE + timedelta(microseconds=1),
            (
                FinalizationSupport(
                    identity(atom),
                    support(
                        "late",
                        "endpoint",
                        valid_from=DEADLINE + timedelta(microseconds=1),
                    ),
                ),
            ),
        )


def test_support_expiration_is_strict_and_preserves_marginals() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    expiring = support("expiring", "endpoint", valid_until=DEADLINE)
    retained = support(
        "retained",
        "endpoint-2",
        valid_until=DEADLINE + timedelta(seconds=1),
    )
    message = AugmentedLogMessage(
        space,
        (
            (AugmentedStateKey(0, supports=(expiring, retained)), math.log(0.2)),
            (AugmentedStateKey(0, supports=(retained,)), math.log(0.3)),
            (AugmentedStateKey(1, supports=(expiring,)), math.log(0.5)),
        ),
    )

    assert message.expire_support(DEADLINE).entries == message.entries
    expired = message.expire_support(DEADLINE + timedelta(microseconds=1))

    assert expired.support_probability(lambda key: expiring in key.supports) == 0.0
    retained_probability = expired.support_probability(
        lambda key: retained in key.supports
    )
    assert retained_probability == pytest.approx(0.5)
    assert tuple(expired.occupancy_posterior()) == pytest.approx(
        tuple(message.occupancy_posterior()),
        abs=1e-12,
    )


def test_finalization_types_and_utc_validation() -> None:
    with pytest.raises(ValueError, match="IDs"):
        AssignmentIdentity("", "alternative", 0, 0)
    with pytest.raises(ValueError, match="ranks"):
        AssignmentIdentity("endpoint", "alternative", -1, 0)

    space = StateSpace(("alpha",), 0)
    message = AugmentedLogMessage.from_posterior(
        CompactLogPosterior.uniform(space)
    )
    naive = datetime(2026, 7, 22)
    with pytest.raises(ValueError, match="UTC"):
        message.finalize(naive)
    with pytest.raises(ValueError, match="UTC"):
        message.expire_support(naive)
