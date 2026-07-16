from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.inference.association import (
    FixedLagAssociationGraph,
)
from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import (
    AssignmentAlternative,
    EndpointToken,
    UnresolvedAssignment,
)

NOW = datetime(2026, 7, 15, tzinfo=UTC)


def candidate(
    *,
    candidate_id: str = "candidate-1",
    endpoint_id: str = "endpoint-1",
    deadline: datetime = NOW + timedelta(seconds=10),
) -> UnresolvedAssignment:
    return UnresolvedAssignment(
        candidate_id=candidate_id,
        endpoint=EndpointToken(endpoint_id, "hall-node", NOW),
        alternatives=(AssignmentAlternative(0, 1, 2.0),),
        stay_weight=1.0,
        deadline=deadline,
        evidence_ids=("source-episode", endpoint_id),
    )


def test_assignment_finalizes_only_after_strict_watermark_crossing() -> None:
    space = StateSpace(("office", "hall"), 1)
    operators = CompleteMoveOperators(space)
    initial = CompactPosterior.certain(space, (1, 0, 0))
    graph = FixedLagAssociationGraph(timedelta(seconds=2), NOW)
    graph.add(candidate())

    unresolved, certificates = graph.advance(
        NOW + timedelta(seconds=12),
        initial,
        operators,
    )
    assert unresolved is initial
    assert certificates == ()
    assert len(graph.pending) == 1

    finalized, certificates = graph.advance(
        NOW + timedelta(seconds=12, microseconds=1),
        initial,
        operators,
    )
    assert finalized[space.rank((1, 0, 0))] == pytest.approx(1 / 3)
    assert finalized[space.rank((0, 1, 0))] == pytest.approx(2 / 3)
    assert finalized.normalization == pytest.approx(1.0, abs=1e-12)
    assert tuple(certificate.endpoint_id for certificate in certificates) == (
        "endpoint-1",
    )
    assert not graph.pending
    assert graph.consumed_endpoint_ids == ("endpoint-1",)


def test_watermark_is_monotone_and_finalization_order_is_deterministic() -> None:
    space = StateSpace(("alpha", "beta"), 1)
    operators = CompleteMoveOperators(space)
    posterior = CompactPosterior.certain(space, (1, 0, 0))
    graph = FixedLagAssociationGraph(timedelta(seconds=1), NOW)
    graph.add(
        candidate(
            candidate_id="later-id",
            endpoint_id="endpoint-b",
            deadline=NOW + timedelta(seconds=3),
        )
    )
    graph.add(
        candidate(
            candidate_id="earlier-id",
            endpoint_id="endpoint-a",
            deadline=NOW + timedelta(seconds=2),
        )
    )

    _, certificates = graph.advance(
        NOW + timedelta(seconds=5),
        posterior,
        operators,
    )
    watermark = graph.watermark
    graph.advance(NOW + timedelta(seconds=4), posterior, operators)

    assert tuple(certificate.candidate_id for certificate in certificates) == (
        "earlier-id",
        "later-id",
    )
    assert graph.watermark == watermark


def test_endpoint_tokens_are_globally_one_use() -> None:
    graph = FixedLagAssociationGraph(timedelta(0), NOW)
    graph.add(candidate())

    with pytest.raises(ValueError, match="candidate ID"):
        graph.add(candidate(endpoint_id="endpoint-2"))
    with pytest.raises(ValueError, match="already assigned"):
        graph.add(candidate(candidate_id="candidate-2"))

    space = StateSpace(("office", "hall"), 1)
    graph.advance(
        NOW + timedelta(seconds=11),
        CompactPosterior.uniform(space),
        CompleteMoveOperators(space),
    )
    with pytest.raises(ValueError, match="already assigned"):
        graph.add(
            candidate(
                candidate_id="candidate-3",
                deadline=NOW + timedelta(seconds=20),
            )
        )


def test_assignment_types_and_graph_reject_invalid_bounds() -> None:
    naive = datetime(2026, 7, 15)
    with pytest.raises(ValueError, match="UTC"):
        EndpointToken("endpoint", "node", naive)
    with pytest.raises(ValueError, match="non-empty"):
        EndpointToken("", "node", NOW)
    with pytest.raises(ValueError, match="must differ"):
        AssignmentAlternative(0, 0, 1.0)
    with pytest.raises(ValueError, match="finite"):
        AssignmentAlternative(0, 1, float("inf"))
    with pytest.raises(ValueError, match="non-negative"):
        FixedLagAssociationGraph(timedelta(seconds=-1), NOW)
    with pytest.raises(ValueError, match="at least one"):
        UnresolvedAssignment(
            "candidate",
            EndpointToken("endpoint", "node", NOW),
            (),
            1.0,
            NOW,
            (),
        )
    with pytest.raises(ValueError, match="candidate ID"):
        UnresolvedAssignment(
            "",
            EndpointToken("endpoint", "node", NOW),
            (AssignmentAlternative(0, 1, 1.0),),
            1.0,
            NOW,
            (),
        )
    with pytest.raises(ValueError, match="stay weight"):
        UnresolvedAssignment(
            "candidate",
            EndpointToken("endpoint", "node", NOW),
            (AssignmentAlternative(0, 1, 1.0),),
            -1.0,
            NOW,
            (),
        )
    with pytest.raises(ValueError, match="cannot precede"):
        candidate(deadline=NOW - timedelta(microseconds=1))

    graph = FixedLagAssociationGraph(timedelta(0), NOW + timedelta(seconds=20))
    with pytest.raises(ValueError, match="behind"):
        graph.add(candidate())
