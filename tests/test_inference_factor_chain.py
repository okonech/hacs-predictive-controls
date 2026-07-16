from __future__ import annotations

import math
from array import array
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
    EndpointFactor,
)
from custom_components.predictive_controls.inference.factor_chain import (
    ExactFactorChain,
    ZoneLikelihoodStep,
)
from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import (
    AssignmentIdentity,
    AugmentedStateKey,
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    FinalizationSupport,
    SupportEventAtom,
)
from tests.oracle.exact_inference import (
    DecimalAugmentedKey,
    augmented_endpoint_factor_decimal,
)

NOW = datetime(2026, 7, 24, tzinfo=UTC)


def factor(endpoint_id: str, target: int, source: int) -> EndpointFactor:
    deadline = NOW + timedelta(seconds=30)
    return EndpointFactor(
        EndpointToken(endpoint_id, f"node-{target}", NOW),
        target,
        f"zone-{target}",
        (
            EndpointAlternative(
                f"stay:{endpoint_id}",
                "stay",
                None,
                None,
                (),
                math.log(0.4),
                NOW,
                (endpoint_id,),
            ),
            EndpointAlternative(
                f"move:{endpoint_id}",
                "graph_valid",
                source,
                f"node-{source}",
                (f"node-{source}", f"node-{target}"),
                math.log(0.6),
                deadline,
                (endpoint_id,),
            ),
        ),
        math.log(0.2),
        math.log(0.9),
    )


def identity(atom: EndpointAssignmentAtom) -> AssignmentIdentity:
    return AssignmentIdentity(
        atom.endpoint_id,
        atom.alternative_id,
        atom.predecessor_rank,
        atom.successor_rank,
    )


def certificate_factory(
    endpoint_factor: EndpointFactor,
    atom: EndpointAssignmentAtom,
) -> SupportEventAtom | None:
    if atom.disposition != "graph_valid" or atom.source_index is None:
        return None
    return SupportEventAtom(
        f"support:{atom.endpoint_id}:{atom.predecessor_rank}:{atom.successor_rank}",
        atom.disposition,
        f"zone-{atom.source_index}",
        endpoint_factor.target_zone,
        atom.route_nodes,
        (atom.endpoint_id,),
        atom.evidence_ids,
        endpoint_factor.endpoint.event_at,
        atom.deadline + timedelta(minutes=1),
        True,
    )


def finalize_factor(
    message: AugmentedLogMessage,
    endpoint_factor: EndpointFactor,
    watermark: datetime,
) -> AugmentedLogMessage:
    applied = endpoint_factor.apply(
        message,
        CompleteMoveOperators(message.space),
    )
    atoms = {
        identity(atom): atom
        for key, _ in applied.entries
        for atom in key.contexts
        if atom.endpoint_id == endpoint_factor.endpoint.token_id
    }
    return applied.finalize(
        watermark,
        tuple(
            FinalizationSupport(
                assignment_identity,
                certificate_factory(endpoint_factor, atom),
            )
            for assignment_identity, atom in atoms.items()
        ),
    )


def augmented_probabilities(
    message: AugmentedLogMessage,
) -> dict[AugmentedStateKey, float]:
    return {key: math.exp(log_mass) for key, log_mass in message.entries}


def test_factor_chain_matches_explicit_joint_and_backward_marginal() -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), 2)
    posterior = CompactLogPosterior(
        space,
        (math.log(rank + 1) for rank in range(len(space))),
    )
    factors = (factor("first", 1, 0), factor("second", 2, 1))
    explicit = AugmentedLogMessage.from_posterior(posterior)
    chain = ExactFactorChain(posterior)
    for endpoint_factor in factors:
        explicit = endpoint_factor.apply(explicit, CompleteMoveOperators(space))
        chain = chain.apply_endpoint(endpoint_factor)

    assert tuple(chain.posterior) == pytest.approx(
        tuple(explicit.occupancy_posterior()),
        abs=1e-12,
    )
    explicit_probability = explicit.support_probability(
        lambda key: any(
            atom.endpoint_id == "first" and atom.disposition == "graph_valid"
            for atom in key.contexts
        )
    )
    assert chain.assignment_probability(
        "first",
        lambda atom: atom.disposition == "graph_valid",
    ) == pytest.approx(explicit_probability, abs=1e-12)


@pytest.mark.parametrize("occupants", range(6))
def test_assignment_and_terminal_probability_matches_explicit_joint(
    occupants: int,
) -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), occupants)
    posterior = CompactLogPosterior(
        space,
        (math.log(rank + 1) for rank in range(len(space))),
    )
    factors = (factor("first", 1, 0), factor("second", 2, 1))
    explicit = AugmentedLogMessage.from_posterior(posterior)
    chain = ExactFactorChain(posterior)
    for endpoint_factor in factors:
        explicit = endpoint_factor.apply(explicit, CompleteMoveOperators(space))
        chain = chain.apply_endpoint(endpoint_factor)

    expected = explicit.support_probability(
        lambda key: space.unrank(key.occupancy_rank)[1] == 0
        and any(
            atom.endpoint_id == "first" and atom.disposition == "graph_valid"
            for atom in key.contexts
        )
    )

    assert chain.assignment_and_terminal_probability(
        "first",
        lambda atom: atom.disposition == "graph_valid",
        lambda configuration: configuration[1] == 0,
    ) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("occupants", range(6))
def test_batched_assignment_probabilities_match_scalar_queries(
    occupants: int,
) -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), occupants)
    posterior = CompactLogPosterior(
        space,
        (math.log(rank + 1) for rank in range(len(space))),
    )
    chain = ExactFactorChain(posterior)
    for endpoint_factor in (factor("first", 1, 0), factor("second", 2, 1)):
        chain = chain.apply_endpoint(endpoint_factor)
    queries = (
        (
            lambda atom: atom.disposition == "graph_valid",
            lambda configuration: configuration[1] == 0,
        ),
        (
            lambda atom: atom.disposition == "stay",
            lambda configuration: configuration[2] > 0,
        ),
    )

    assert chain.assignment_and_terminal_probabilities(
        "first",
        queries,
    ) == pytest.approx(
        tuple(
            chain.assignment_and_terminal_probability(
                "first",
                assignment_predicate,
                terminal_predicate,
            )
            for assignment_predicate, terminal_predicate in queries
        ),
        abs=1e-12,
    )


@pytest.mark.parametrize("occupants", range(6))
def test_terminal_alternative_probabilities_match_generic_joint_queries(
    occupants: int,
) -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), occupants)
    posterior = CompactLogPosterior(
        space,
        (math.log(rank + 1) for rank in range(len(space))),
    )
    chain = ExactFactorChain(posterior)
    for endpoint_factor in (factor("first", 1, 0), factor("second", 2, 1)):
        chain = chain.apply_endpoint(endpoint_factor)
    generic_queries = (
        (
            lambda atom: atom.disposition in {"graph_valid", "stay"},
            lambda configuration: configuration[2] > 0,
        ),
        (
            lambda atom: atom.alternative_id == "second:move",
            lambda configuration: (
                configuration[1] == 0 and configuration[2] > 0
            ),
        ),
    )
    terminal_queries = (
        (
            lambda alternative: alternative.disposition
            in {"graph_valid", "stay"},
            generic_queries[0][1],
        ),
        (
            lambda alternative: alternative.alternative_id == "second:move",
            generic_queries[1][1],
        ),
    )

    assert chain.terminal_alternative_and_configuration_probabilities(
        "second",
        terminal_queries,
    ) == pytest.approx(
        chain.assignment_and_terminal_probabilities("second", generic_queries),
        abs=1e-12,
    )
    assert chain.terminal_alternative_and_configuration_probabilities(
        "second",
        (),
    ) == ()
    with pytest.raises(ValueError, match="not the final"):
        chain.terminal_alternative_and_configuration_probabilities(
            "first",
            terminal_queries,
        )
    with pytest.raises(KeyError, match="not retained"):
        chain.terminal_alternative_and_configuration_probabilities(
            "missing",
            terminal_queries,
        )


def test_assignment_and_terminal_probability_matches_decimal_path_oracle() -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), 2)
    base_configuration = (2, 0, 0, 0)
    posterior = CompactLogPosterior.certain(space, base_configuration)
    factors = (factor("first", 1, 0), factor("second", 2, 1))
    chain = ExactFactorChain(posterior)
    oracle: dict[DecimalAugmentedKey, Decimal] = {
        (base_configuration, ()): Decimal(1)
    }
    for endpoint_factor in factors:
        chain = chain.apply_endpoint(endpoint_factor)
        oracle = augmented_endpoint_factor_decimal(
            oracle,
            endpoint_factor.endpoint.token_id,
            endpoint_factor.target_index,
            tuple(
                (
                    alternative.alternative_id,
                    alternative.source_index,
                    Decimal("0.4")
                    if alternative.disposition == "stay"
                    else Decimal("0.6"),
                )
                for alternative in endpoint_factor.alternatives
            ),
            empty_likelihood=Decimal("0.2"),
            occupied_likelihood=Decimal("0.9"),
        )

    expected = sum(
        (
            probability
            for (configuration, contexts), probability in oracle.items()
            if configuration[1] == 0
            and any(
                endpoint_id == "first" and alternative_id == "move:first"
                for endpoint_id, _, alternative_id in contexts
            )
        ),
        Decimal(0),
    )
    actual = chain.assignment_and_terminal_probability(
        "first",
        lambda atom: atom.disposition == "graph_valid",
        lambda configuration: configuration[1] == 0,
    )

    assert actual == pytest.approx(float(expected), abs=1e-12)


def test_assignment_and_terminal_probability_validates_and_reconstructs() -> None:
    space = StateSpace(("zone-0", "zone-1"), 5)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (5, 0, 0))
    ).apply_endpoint(factor("first", 1, 0))
    expected = chain.assignment_and_terminal_probability(
        "first",
        lambda atom: atom.disposition == "graph_valid",
        lambda configuration: configuration == (4, 1, 0),
    )
    reconstructed = ExactFactorChain(
        chain.base,
        chain.steps,
        chain.operators,
    ).with_persisted_posterior(chain.posterior)

    assert expected > 0.0
    assert reconstructed.assignment_and_terminal_probability(
        "first",
        lambda atom: atom.disposition == "graph_valid",
        lambda configuration: configuration == (4, 1, 0),
    ) == expected
    assert chain.assignment_and_terminal_probability(
        "first",
        lambda _atom: False,
        lambda _configuration: True,
    ) == 0.0
    with pytest.raises(ValueError, match="non-empty"):
        chain.assignment_and_terminal_probability(
            "",
            lambda _atom: True,
            lambda _configuration: True,
        )
    with pytest.raises(KeyError, match="not retained"):
        chain.assignment_and_terminal_probability(
            "missing",
            lambda _atom: True,
            lambda _configuration: True,
        )


def test_factor_chain_query_validation_handles_empty_chain_and_batches() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    chain = ExactFactorChain(CompactLogPosterior.uniform(space))

    assert chain.assignment_and_terminal_probabilities("missing", ()) == ()
    assert chain.terminal_alternative_and_configuration_probabilities(
        "missing", ()
    ) == ()
    with pytest.raises(ValueError, match="non-empty"):
        chain.terminal_alternative_and_configuration_probabilities(
            "",
            ((lambda _alternative: True, lambda _configuration: True),),
        )
    with pytest.raises(ValueError, match="requires a final endpoint"):
        chain.terminal_alternative_and_configuration_probabilities(
            "missing",
            ((lambda _alternative: True, lambda _configuration: True),),
        )


def test_factor_chain_queries_detect_incomplete_endpoint_prefix_cache() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    chain = ExactFactorChain(CompactLogPosterior.uniform(space)).apply_endpoint(
        factor("first", 1, 0)
    )
    chain._endpoint_prefixes.clear()  # noqa: SLF001

    with pytest.raises(RuntimeError, match="prefix cache"):
        chain.terminal_alternative_and_configuration_probabilities(
            "first",
            ((lambda _alternative: True, lambda _configuration: True),),
        )
    with pytest.raises(RuntimeError, match="prefix cache"):
        chain.assignment_and_terminal_probabilities(
            "first",
            ((lambda _atom: True, lambda _configuration: True),),
        )


def test_factor_chain_terminal_query_skips_impossible_movement_alternative() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    endpoint_factor = factor("impossible", 1, 0)
    stay, movement = endpoint_factor.alternatives
    endpoint_factor = EndpointFactor(
        endpoint_factor.endpoint,
        endpoint_factor.target_index,
        endpoint_factor.target_zone,
        (
            stay,
            EndpointAlternative(
                movement.alternative_id,
                movement.disposition,
                movement.source_index,
                movement.source_node_id,
                movement.route_nodes,
                -math.inf,
                movement.deadline,
                movement.evidence_ids,
            ),
        ),
        endpoint_factor.empty_log_likelihood,
        endpoint_factor.occupied_log_likelihood,
    )
    chain = ExactFactorChain(CompactLogPosterior.uniform(space)).apply_endpoint(
        endpoint_factor
    )

    assert chain.terminal_alternative_and_configuration_probabilities(
        "impossible",
        (
            (
                lambda alternative: alternative.disposition == "graph_valid",
                lambda _: True,
            ),
        ),
    ) == (0.0,)

    successor = array("d", [0.0]) * len(space)
    selected, total = chain._backward_steps(  # noqa: SLF001
        (successor,),
        successor,
        endpoint_factor,
    )
    assert selected[0] == total


def test_factor_chain_rejects_duplicate_endpoint_and_filters_impossible_move() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (0, 2, 0))
    ).apply_endpoint(factor("first", 1, 0))

    assert chain.assignment_probability(
        "first", lambda atom: atom.disposition == "graph_valid"
    ) == 0.0
    with pytest.raises(ValueError, match="already present"):
        chain.apply_endpoint(factor("first", 1, 0))


def test_factor_chain_rejects_invalid_endpoint_target_index() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    posterior = CompactLogPosterior.uniform(space)

    with pytest.raises(IndexError, match="target zone index is out of range"):
        ExactFactorChain(posterior).apply_endpoint(
            factor("invalid", 3, 0)
        )


def test_factor_chain_backward_helpers_cover_unary_and_endpoint_steps() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    chain = ExactFactorChain(CompactLogPosterior.uniform(space))
    successor = array("d", [0.0]) * len(space)
    likelihood = ZoneLikelihoodStep(0, math.log(0.2), math.log(0.8), NOW)

    unary = chain._backward_step(successor, likelihood)  # noqa: SLF001
    endpoint = chain._backward_step(  # noqa: SLF001
        successor,
        factor("backward", 1, 0),
    )
    selected, total = chain._backward_steps(  # noqa: SLF001
        (successor,),
        successor,
        likelihood,
    )
    selected_endpoint, total_endpoint = chain._backward_steps(  # noqa: SLF001
        (successor,),
        successor,
        factor("backward", 1, 0),
    )

    assert all(math.isfinite(value) for value in unary)
    assert all(math.isfinite(value) for value in endpoint)
    assert selected[0] == total
    assert selected_endpoint[0] == total_endpoint


@pytest.mark.parametrize(
    ("target", "source", "error", "message"),
    (
        (3, 0, IndexError, "target zone index"),
        (1, 4, IndexError, "source location index"),
        (1, 1, ValueError, "source and target must differ"),
    ),
)
def test_factor_chain_backward_batch_validates_endpoint_indices(
    target: int,
    source: int,
    error: type[Exception],
    message: str,
) -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    chain = ExactFactorChain(CompactLogPosterior.uniform(space))
    successor = array("d", [0.0]) * len(space)

    with pytest.raises(error, match=message):
        chain._backward_steps(  # noqa: SLF001
            (successor,),
            successor,
            factor("invalid", target, source),
        )


def test_factor_chain_strictly_compacts_only_resolved_prefix() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    chain = ExactFactorChain(posterior).apply_endpoint(factor("first", 1, 0))

    at_deadline, at_consumed = chain.compact(NOW + timedelta(seconds=30))
    after, consumed = chain.compact(
        NOW + timedelta(seconds=30, microseconds=1)
    )

    assert at_deadline is chain
    assert at_consumed == ()
    assert consumed == ("first",)
    assert after.steps == ()
    assert tuple(after.posterior) == pytest.approx(tuple(chain.posterior), abs=1e-12)


def test_compact_preserves_exact_branch_support_strata() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    posterior = CompactLogPosterior(
        space,
        (math.log(rank + 1) for rank in range(len(space))),
    )
    endpoint_factor = factor("first", 1, 0)
    chain = ExactFactorChain(posterior).apply_endpoint(endpoint_factor)
    watermark = NOW + timedelta(seconds=30, microseconds=1)
    expected = finalize_factor(
        AugmentedLogMessage.from_posterior(posterior),
        endpoint_factor,
        watermark,
    )

    compacted, consumed = chain.compact(watermark, certificate_factory)

    assert consumed == ("first",)
    assert compacted.steps == ()
    assert augmented_probabilities(compacted.base_message) == pytest.approx(
        augmented_probabilities(expected),
        abs=1e-12,
    )
    assert tuple(compacted.base) == pytest.approx(
        tuple(expected.occupancy_posterior()),
        abs=1e-12,
    )
    assert (
        compacted.finalized_support_message().entries
        == compacted.base_message.entries
    )


def test_compact_retains_cross_factor_support_correlation() -> None:
    space = StateSpace(("zone-0", "zone-1", "zone-2"), 2)
    posterior = CompactLogPosterior.certain(space, (2, 0, 0, 0))
    first = factor("first", 1, 0)
    second = factor("second", 2, 1)
    chain = ExactFactorChain(posterior).apply_endpoint(first).apply_endpoint(second)
    watermark = NOW + timedelta(seconds=30, microseconds=1)
    expected = AugmentedLogMessage.from_posterior(posterior)
    expected = finalize_factor(expected, first, watermark)
    expected = finalize_factor(expected, second, watermark)

    compacted, _ = chain.compact(watermark, certificate_factory)

    assert augmented_probabilities(compacted.base_message) == pytest.approx(
        augmented_probabilities(expected),
        abs=1e-12,
    )
    assert compacted.base_message.support_probability(
        lambda key: len(key.supports) == 2
    ) == pytest.approx(
        expected.support_probability(lambda key: len(key.supports) == 2),
        abs=1e-12,
    )
    assert tuple(compacted.posterior) == pytest.approx(
        tuple(chain.posterior),
        abs=1e-12,
    )


def test_compact_retains_existing_support_and_conditions_later_likelihood() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    existing = SupportEventAtom(
        "existing",
        "graph_valid",
        "zone-0",
        "zone-1",
        ("node-0", "node-1"),
        ("existing-endpoint",),
        ("existing-episode",),
        NOW,
        NOW + timedelta(minutes=2),
        True,
    )
    base_message = AugmentedLogMessage(
        space,
        (
            (AugmentedStateKey(0, supports=(existing,)), math.log(0.4)),
            (AugmentedStateKey(1), math.log(0.6)),
        ),
    )
    likelihood = ZoneLikelihoodStep(1, math.log(0.8), math.log(0.2), NOW)
    chain = ExactFactorChain(
        base_message.occupancy_posterior(),
        base_message=base_message,
    ).apply_zone_likelihood(
        likelihood.zone_index,
        empty_log_likelihood=likelihood.empty_log_likelihood,
        occupied_log_likelihood=likelihood.occupied_log_likelihood,
        event_at=likelihood.event_at,
    )
    expected = base_message.apply_zone_likelihood(
        1,
        empty_log_likelihood=likelihood.empty_log_likelihood,
        occupied_log_likelihood=likelihood.occupied_log_likelihood,
    )

    assert augmented_probabilities(
        chain.finalized_support_message()
    ) == pytest.approx(
        augmented_probabilities(expected),
        abs=1e-12,
    )
    compacted, _ = chain.compact(NOW + timedelta(microseconds=1))
    assert augmented_probabilities(compacted.base_message) == pytest.approx(
        augmented_probabilities(expected),
        abs=1e-12,
    )


def test_finalized_support_message_rejects_unresolved_endpoint() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (1, 0, 0))
    ).apply_endpoint(factor("first", 1, 0))

    with pytest.raises(ValueError, match="unresolved endpoint"):
        chain.finalized_support_message()


def test_factor_chain_validates_support_base_context_and_projection() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    contextual = factor("first", 1, 0).apply(
        AugmentedLogMessage.from_posterior(posterior),
        CompleteMoveOperators(space),
    )
    mismatched = AugmentedLogMessage.from_posterior(
        CompactLogPosterior.certain(space, (0, 1, 0))
    )

    with pytest.raises(ValueError, match="must not contain contexts"):
        ExactFactorChain(posterior, base_message=contextual)
    with pytest.raises(ValueError, match="does not project"):
        ExactFactorChain(posterior, base_message=mismatched)


def test_compact_expires_support_without_factor_steps_and_is_idempotent() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    expires_at = NOW + timedelta(seconds=5)
    existing = SupportEventAtom(
        "existing",
        "graph_valid",
        "zone-0",
        "zone-1",
        ("node-0", "node-1"),
        ("endpoint",),
        (),
        NOW,
        expires_at,
        True,
    )
    base_message = AugmentedLogMessage(
        space,
        (
            (AugmentedStateKey(0, supports=(existing,)), math.log(0.4)),
            (AugmentedStateKey(1), math.log(0.6)),
        ),
    )
    chain = ExactFactorChain(
        base_message.occupancy_posterior(),
        base_message=base_message,
    )

    at_expiry, consumed = chain.compact(expires_at)
    expired, expired_consumed = at_expiry.compact(
        expires_at + timedelta(microseconds=1)
    )
    repeated, repeated_consumed = expired.compact(
        expires_at + timedelta(microseconds=1)
    )

    assert consumed == expired_consumed == repeated_consumed == ()
    assert at_expiry.base_message.support_probability(
        lambda key: existing in key.supports
    ) == pytest.approx(0.4)
    assert expired.base_message.support_probability(
        lambda key: existing in key.supports
    ) == 0.0
    assert tuple(expired.posterior) == pytest.approx(tuple(chain.posterior), abs=1e-12)
    assert repeated.base_message.entries == expired.base_message.entries


def test_factor_chain_accepts_only_equivalent_persisted_forward_message() -> None:
    space = StateSpace(("zone-0", "zone-1"), 1)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (1, 0, 0))
    ).apply_endpoint(factor("first", 1, 0))
    restored = chain.with_persisted_posterior(chain.posterior)

    assert tuple(restored.posterior) == tuple(chain.posterior)
    with pytest.raises(ValueError, match="reconstruct"):
        chain.with_persisted_posterior(
            CompactLogPosterior.certain(space, (0, 1, 0))
        )


def test_factor_chain_batches_unary_likelihoods_without_changing_steps() -> None:
    space = StateSpace(("zone-0", "zone-1"), 2)
    posterior = CompactLogPosterior.uniform(space)
    steps = (
        ZoneLikelihoodStep(0, math.log(0.2), math.log(0.9), NOW),
        ZoneLikelihoodStep(1, math.log(0.7), math.log(0.3), NOW),
    )
    sequential = ExactFactorChain(posterior)
    for step in steps:
        sequential = sequential.apply_zone_likelihood(
            step.zone_index,
            empty_log_likelihood=step.empty_log_likelihood,
            occupied_log_likelihood=step.occupied_log_likelihood,
            event_at=step.event_at,
        )
    batched = ExactFactorChain(posterior).apply_zone_likelihoods(steps)

    assert batched.steps == sequential.steps
    assert tuple(batched.posterior) == pytest.approx(
        tuple(sequential.posterior),
        abs=1e-12,
    )
