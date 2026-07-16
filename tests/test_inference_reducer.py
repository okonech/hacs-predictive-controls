from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
)
from custom_components.predictive_controls.inference.reducer import (
    AugmentedEventReducer,
    FactorChainEventReducer,
)
from custom_components.predictive_controls.inference.replay import (
    RetainedObservation,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.types import SupportEventAtom
from custom_components.predictive_controls.model import PredictiveMap

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {
                    "zone": "kitchen",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def event(node_id: str, seconds: int, state: str = "on") -> OccupancyEvent:
    return OccupancyEvent(
        f"binary_sensor.{node_id}",
        node_id,
        node_id,
        "first_floor",
        "transition_gate" if node_id == "hall" else "room_occupancy",
        "transient" if node_id == "hall" else "sustained",
        "motion",
        state,
        NOW + timedelta(seconds=seconds),
        1.0,
    )


def retained(*events: OccupancyEvent) -> tuple[RetainedObservation, ...]:
    return tuple(
        RetainedObservation(observation, f"evidence-{index}", index)
        for index, observation in enumerate(events, start=1)
    )


def reducer(occupants: int = 2) -> tuple[AugmentedEventReducer, StateSpace]:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), occupants)
    return AugmentedEventReducer(predictive_map, space), space


def test_positive_endpoint_localizes_unlocated_mass_without_pruning() -> None:
    event_reducer, space = reducer(2)
    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 2))
    )

    result = event_reducer.reduce(base, retained(event("office", 1)))
    posterior = result.message.occupancy_posterior()

    assert posterior.occupied_marginals()[space.location_index("office")] > 0.0
    assert result.message.normalization == pytest.approx(1.0, abs=1e-12)
    assert result.dispositions == (("evidence-1", "accepted_positive"),)
    dispositions = {
        atom.disposition
        for key, _ in result.message.entries
        for atom in key.contexts
    }
    assert dispositions == {
        "stay",
        "unlocated",
    }


def test_sequential_endpoint_fold_retains_direct_and_censored_contexts() -> None:
    event_reducer, space = reducer(2)
    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 2))
    )

    result = event_reducer.reduce(
        base,
        retained(
            event("office", 1),
            event("hall", 2),
            event("kitchen", 3),
        ),
    )
    dispositions = {
        atom.disposition
        for key, _ in result.message.entries
        for atom in key.contexts
    }

    assert "graph_valid" in dispositions
    assert "censored_graph_path" in dispositions
    assert result.message.normalization == pytest.approx(1.0, abs=1e-12)
    assert all(
        sum(space.unrank(key.occupancy_rank)) == 2
        for key, _ in result.message.entries
    )


def test_clear_likelihood_preserves_existing_assignment_context() -> None:
    event_reducer, space = reducer(1)
    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 1))
    )
    positive = event_reducer.reduce(base, retained(event("office", 1)))

    cleared = event_reducer.reduce(
        base,
        retained(event("office", 1), event("office", 2, "off")),
    )

    assert all(key.contexts for key, _ in positive.message.entries)
    assert all(key.contexts for key, _ in cleared.message.entries)
    assert cleared.message.normalization == pytest.approx(1.0, abs=1e-12)
    assert cleared.dispositions[-1] == ("evidence-2", "accepted_clear")


def test_later_remote_event_advances_stable_clear_frontier() -> None:
    event_reducer, space = reducer(1)
    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 1))
    )

    result = event_reducer.reduce(
        base,
        retained(
            event("office", 1),
            event("office", 2, "off"),
            event("kitchen", 8),
        ),
    )
    office_state = next(
        state for state in result.episode_states if state.node_id == "office"
    )

    assert not office_state.current_positive
    assert office_state.finalized_at == NOW + timedelta(seconds=7)
    assert result.message.normalization == pytest.approx(1.0, abs=1e-12)


def test_reducer_validates_exact_state_space_identity() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    event_reducer = AugmentedEventReducer(predictive_map, space)
    other_space = StateSpace(predictive_map.zones(), 1)
    other_posterior = CompactLogPosterior.certain(other_space, (0, 0, 0, 1))

    with pytest.raises(ValueError, match="zones must match"):
        AugmentedEventReducer(predictive_map, StateSpace(("wrong",), 1))
    with pytest.raises(ValueError, match="exact state space"):
        event_reducer.initial_state(other_posterior)

    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 1))
    )
    with pytest.raises(ValueError, match="reducer state space"):
        event_reducer.reduce(
            replace(
                base,
                message=AugmentedLogMessage.from_posterior(other_posterior),
            ),
            (),
        )


def test_frontier_advance_finalizes_strictly_without_new_evidence() -> None:
    event_reducer, space = reducer(1)
    base = event_reducer.initial_state(
        CompactLogPosterior.certain(space, (0, 0, 0, 1))
    )
    endpoint_at = NOW + timedelta(seconds=1)
    observed = event_reducer.reduce(base, retained(event("office", 1)))
    at_deadline, consumed_at_deadline = event_reducer.advance(
        observed,
        endpoint_at,
    )
    after_deadline, consumed_after_deadline = event_reducer.advance(
        observed,
        endpoint_at + timedelta(microseconds=1),
    )

    assert any(key.contexts for key, _ in at_deadline.message.entries)
    assert consumed_at_deadline == ()
    assert all(not key.contexts for key, _ in after_deadline.message.entries)
    assert consumed_after_deadline == (f"office@{endpoint_at.isoformat()}",)
    assert at_deadline.message.normalization == pytest.approx(1.0, abs=1e-12)
    assert after_deadline.message.normalization == pytest.approx(1.0, abs=1e-12)


def test_factor_chain_reducer_matches_explicit_reducer_projection() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 2)
    explicit = AugmentedEventReducer(predictive_map, space)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(space, (0, 0, 0, 2))
    records = retained(
        event("office", 1),
        event("hall", 2),
        event("kitchen", 3),
    )

    explicit_result = explicit.reduce(explicit.initial_state(posterior), records)
    compact_result = compact.reduce(compact.initial_state(posterior), records)

    assert tuple(compact_result.chain.posterior) == pytest.approx(
        tuple(explicit_result.message.occupancy_posterior()),
        abs=1e-12,
    )
    assert compact_result.episode_states == explicit_result.episode_states
    assert compact_result.dispositions == explicit_result.dispositions


def test_factor_chain_reducer_issues_finalized_movement_certificates() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(
        space,
        (0,) * len(space.zones) + (1,),
    )
    observed = compact.reduce(
        compact.initial_state(posterior),
        retained(event("office", 1), event("hall", 2)),
    )
    watermark = NOW + timedelta(seconds=70)

    finalized, consumed = compact.advance(observed, watermark)
    supports = {
        support
        for key, _ in finalized.chain.base_message.entries
        for support in key.supports
    }
    movement = {
        support for support in supports if support.disposition != "stay"
    }

    assert consumed == (
        f"office@{(NOW + timedelta(seconds=1)).isoformat()}",
        f"hall@{(NOW + timedelta(seconds=2)).isoformat()}",
    )
    assert supports
    assert movement
    assert {support.disposition for support in movement} <= {
        "graph_valid",
        "censored_graph_path",
        "missed_movement",
    }
    assert all(len(support.endpoint_ids) == 1 for support in movement)
    assert all(not support.episode_ids for support in movement)
    assert all(support.valid_until == watermark for support in supports)
    assert all(
        support.learning_eligible == (support.disposition == "graph_valid")
        for support in supports
    )
    assert all(
        support.support_event_id.startswith("assignment:") for support in supports
    )


def test_movement_certificate_metadata_is_deterministic() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(
        space,
        (0,) * len(space.zones) + (1,),
    )
    records = retained(event("office", 1), event("hall", 2))
    watermark = NOW + timedelta(seconds=70)

    first, _ = compact.advance(
        compact.reduce(compact.initial_state(posterior), records),
        watermark,
    )
    second, _ = compact.advance(
        compact.reduce(compact.initial_state(posterior), records),
        watermark,
    )

    assert first.chain.base_message.entries == second.chain.base_message.entries
    assert all(
        isinstance(support, SupportEventAtom)
        for key, _ in first.chain.base_message.entries
        for support in key.supports
    )


def test_unlocated_and_stay_branches_receive_fresh_local_support_only() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(
        space,
        (0,) * len(space.zones) + (1,),
    )
    endpoint_at = NOW + timedelta(seconds=1)
    observed = compact.reduce(
        compact.initial_state(posterior),
        retained(event("office", 1)),
    )
    watermark = endpoint_at + timedelta(microseconds=1)

    finalized, _ = compact.advance(observed, watermark)
    supports = {
        support
        for key, _ in finalized.chain.base_message.entries
        for support in key.supports
    }

    assert supports
    assert {support.disposition for support in supports} == {"stay"}
    assert all(support.origin_zone == "office" for support in supports)
    assert all(support.destination_zone == "office" for support in supports)
    assert all(support.route_nodes == ("office",) for support in supports)
    assert all(not support.endpoint_ids for support in supports)
    assert all(
        support.episode_ids == (f"office@{endpoint_at.isoformat()}",)
        for support in supports
    )
    assert all(not support.learning_eligible for support in supports)
    assert all(support.valid_until == watermark for support in supports)
    assert all(
        len(key.supports) <= 1
        for key, _ in finalized.chain.base_message.entries
    )


def test_stable_clear_prevents_historical_local_support_certificate() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(
        space,
        (0,) * len(space.zones) + (1,),
    )
    observed = compact.reduce(
        compact.initial_state(posterior),
        retained(event("office", 1), event("office", 2, "off")),
    )

    finalized, _ = compact.advance(observed, NOW + timedelta(seconds=8))

    assert all(
        not key.supports for key, _ in finalized.chain.base_message.entries
    )


def test_graph_branch_uses_movement_capacity_not_local_episode_capacity() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(
        space,
        (0,) * len(space.zones) + (1,),
    )
    observed = compact.reduce(
        compact.initial_state(posterior),
        retained(event("office", 1), event("hall", 2)),
    )

    finalized, _ = compact.advance(observed, NOW + timedelta(seconds=70))
    movement = {
        support
        for key, _ in finalized.chain.base_message.entries
        for support in key.supports
        if support.disposition != "stay"
    }

    assert movement
    assert all(support.endpoint_ids for support in movement)
    assert all(not support.episode_ids for support in movement)
