from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_state import (
    PositionState,
    Posterior,
    WeightedHypothesis,
    canonical_hypothesis,
    normalize_hypotheses,
    probability_sum,
)

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


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
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
                "garage": {"zone": "garage", "adjacent": []},
            }
        }
    )


def event(zone: str, at: datetime, state: str = "on") -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor="first_floor",
        role="transition_gate" if zone == "hall" else "room_occupancy",
        occupancy_behavior="transient" if zone == "hall" else "sustained",
        signal_type="motion",
        state=state,
        event_at=at,
        reliability=0.9,
    )


def test_filter_scenario_updates_marginals_moves_and_quarantines_event_order() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    office = event("office", NOW + timedelta(seconds=1))

    arrived = occupancy_filter.observe(office)
    duplicate = occupancy_filter.observe(
        replace(office, event_at=NOW + timedelta(seconds=2))
    )
    moved = occupancy_filter.observe(event("hall", NOW + timedelta(seconds=3)))
    late = occupancy_filter.observe(event("garage", NOW + timedelta(seconds=2)))

    assert arrived.occupied_marginals["office"] > 0.60
    assert occupancy_filter.count_marginals["hall"] == pytest.approx(
        moved.count_marginals["hall"]
    )
    assert duplicate.provenance.disposition == "duplicate"
    assert duplicate.current == duplicate.previous
    assert moved.occupied_marginals["hall"] > moved.occupied_marginals["office"]
    assert moved.movement_mass[("office", "hall")] > 0.6
    assert late.provenance.disposition == "out_of_order"
    assert late.current == moved.current
    assert occupancy_filter.last_update == late
    assert probability_sum(occupancy_filter.posterior) == pytest.approx(1.0)


def test_filter_uses_fixed_exact_two_occupant_configuration_space() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)

    for offset, zone in enumerate(
        ("office", "hall", "kitchen", "hall", "office") * 4,
        start=1,
    ):
        occupancy_filter.observe(event(zone, NOW + timedelta(seconds=offset)))
        assert len(occupancy_filter.posterior.hypotheses) == 15
        assert occupancy_filter.posterior.pruned_probability == 0.0
        assert probability_sum(occupancy_filter.posterior) == pytest.approx(1.0)

    assert occupancy_filter.configuration_count == 15


def test_filter_emits_origin_preserving_multihop_movement_evidence() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)

    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    occupancy_filter.observe(event("hall", NOW + timedelta(seconds=2)))
    arrived = occupancy_filter.observe(event("kitchen", NOW + timedelta(seconds=3)))

    assert any(
        evidence.origin_zone == "office"
        and evidence.source_zone == "hall"
        and evidence.target_zone == "kitchen"
        for evidence in arrived.movement_evidence
    )


def test_filter_bounds_directional_context_without_pruning_occupancy() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)

    for offset, zone in enumerate(
        ("office", "hall", "kitchen", "hall", "office", "garage") * 5,
        start=1,
    ):
        occupancy_filter.observe(event(zone, NOW + timedelta(seconds=offset)))

    assert all(
        len(contexts) <= 4
        for contexts in occupancy_filter.directional_contexts.values()
    )
    assert occupancy_filter.context_count <= occupancy_filter.configuration_count * 4
    assert occupancy_filter.posterior.pruned_probability == 0.0
    assert probability_sum(occupancy_filter.posterior) == pytest.approx(1.0)


def test_filter_bootstrap_is_atomic_order_independent_and_movement_free() -> None:
    snapshot = (
        event("office", NOW + timedelta(seconds=1)),
        event("hall", NOW + timedelta(seconds=1), state="off"),
        event("kitchen", NOW + timedelta(seconds=1)),
    )
    forward = JointOccupancyFilter(make_map(), 2, NOW)
    reverse = JointOccupancyFilter(make_map(), 2, NOW)

    forward_updates = forward.bootstrap(snapshot, cold_start=True)
    reverse.bootstrap(tuple(reversed(snapshot)), cold_start=True)

    assert [item.key for item in forward.posterior.hypotheses] == [
        item.key for item in reverse.posterior.hypotheses
    ]
    assert [
        item.log_probability for item in forward.posterior.hypotheses
    ] == pytest.approx([item.log_probability for item in reverse.posterior.hypotheses])
    assert all(not update.movement_mass for update in forward_updates)
    assert all(not update.movement_evidence for update in forward_updates)
    assert forward.update_sequence == reverse.update_sequence == 1
    assert forward.configuration_count == len(forward.posterior.hypotheses) == 15
    assert probability_sum(forward.posterior) == pytest.approx(1.0)


def test_filter_rejects_occupant_counts_above_supported_limit() -> None:
    with pytest.raises(ValueError, match="between zero and two"):
        JointOccupancyFilter(make_map(), 3, NOW)

    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    with pytest.raises(ValueError, match="between zero and two"):
        occupancy_filter.set_expected_occupants(3, NOW)


def test_filter_scenario_handles_clear_ignored_and_impossible_observations() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    on_event = event("office", NOW + timedelta(seconds=1))
    occupancy_filter.observe(on_event)

    cleared = occupancy_filter.observe(
        replace(on_event, state="off", event_at=NOW + timedelta(seconds=2))
    )
    ignored = occupancy_filter.observe(
        replace(on_event, state="unavailable", event_at=NOW + timedelta(seconds=3))
    )
    occupancy_filter.observations.prepare_delta = lambda _: replace(  # type: ignore[assignment]
        cleared.provenance,
        log_likelihood_by_count=(-math.inf, -math.inf),
    )
    impossible = occupancy_filter.observe(event("office", NOW + timedelta(seconds=4)))

    assert cleared.provenance.disposition == "replacement"
    assert ignored.provenance.disposition == "ignored"
    assert ignored.current == cleared.current
    assert impossible.provenance.disposition == "impossible_observation"
    assert impossible.current == ignored.current


def test_filter_scenario_reconciles_count_increase_decrease_and_zero() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {canonical_hypothesis((PositionState("office"),)): 0.0},
            NOW,
        )
    )

    assert occupancy_filter.set_expected_occupants(1, NOW) == occupancy_filter.posterior
    increased = occupancy_filter.set_expected_occupants(2, NOW + timedelta(seconds=1))
    assert increased.hypotheses[0].key.positions[1].zone is None
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("office"), PositionState("kitchen"))
                ): 0.0
            },
            NOW + timedelta(seconds=2),
        )
    )
    decreased = occupancy_filter.set_expected_occupants(1, NOW + timedelta(seconds=3))
    assert occupancy_filter.occupied_marginals == pytest.approx(
        {"garage": 0.0, "hall": 0.0, "kitchen": 0.5, "office": 0.5}
    )
    assert len(decreased.hypotheses) == occupancy_filter.configuration_count == 5
    assert decreased.pruned_probability == 0.0
    zero = occupancy_filter.set_expected_occupants(0, NOW + timedelta(seconds=4))
    assert zero.hypotheses[0].key.positions == ()
    with pytest.raises(ValueError, match="between zero and two"):
        occupancy_filter.set_expected_occupants(-1, NOW)


def test_filter_restore_rejects_count_normalization_and_unknown_zones() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    with pytest.raises(ValueError, match="occupant count"):
        occupancy_filter.restore_posterior(
            Posterior((WeightedHypothesis(canonical_hypothesis(()), 0.0),), NOW)
        )
    with pytest.raises(ValueError, match="normalized"):
        occupancy_filter.restore_posterior(
            Posterior(
                (
                    WeightedHypothesis(
                        canonical_hypothesis((PositionState("office"),)),
                        math.log(0.5),
                    ),
                ),
                NOW,
            )
        )
    with pytest.raises(ValueError, match="unknown zone"):
        occupancy_filter.restore_posterior(
            Posterior(
                (
                    WeightedHypothesis(
                        canonical_hypothesis((PositionState("attic"),)),
                        0.0,
                    ),
                ),
                NOW,
            )
        )
    with pytest.raises(ValueError, match="fixed state space"):
        occupancy_filter.restore_posterior(
            normalize_hypotheses(
                {
                    canonical_hypothesis(
                        (PositionState("office", incoming_zone="hall"),)
                    ): 0.0
                },
                NOW,
            )
        )


def test_filter_bootstrap_and_context_restore_reject_invalid_invariants() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    office = event("office", NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="duplicate entities"):
        occupancy_filter.bootstrap((office, office), cold_start=False)

    provenance = occupancy_filter.observations.prepare_snapshot_delta(office)
    occupancy_filter.observations.prepare_snapshot_delta = lambda _event: replace(  # type: ignore[assignment]
        provenance,
        log_likelihood_by_count=(-math.inf, -math.inf),
    )
    updates = occupancy_filter.bootstrap((office,), cold_start=False)
    assert updates[0].provenance.disposition == "impossible_observation"

    restored = JointOccupancyFilter(make_map(), 1, NOW)
    sparse = normalize_hypotheses(
        {canonical_hypothesis((PositionState("office"),)): 0.0},
        NOW,
    )
    restored.restore_posterior(sparse)
    office_key = sparse.hypotheses[0].key
    valid_context = restored.directional_contexts[office_key]
    with pytest.raises(ValueError, match="non-negative integer"):
        restored.restore_directional_contexts({office_key: valid_context}, -1)
    with pytest.raises(ValueError, match="posterior keys"):
        restored.restore_directional_contexts({}, 0)
    with pytest.raises(ValueError, match="one to four"):
        restored.restore_directional_contexts({office_key: ()}, 0)
    with pytest.raises(ValueError, match="mass"):
        restored.restore_directional_contexts(
            {office_key: (replace(valid_context[0], log_probability=math.log(0.5)),)},
            0,
        )
    restored.restore_directional_contexts({office_key: valid_context}, 3)
    assert restored.update_sequence == 3
    assert set(restored.directional_contexts) == {
        hypothesis.key for hypothesis in restored.posterior.hypotheses
    }


def test_filter_discards_stale_motion_from_positive_corroboration() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))

    evidence = occupancy_filter._current_positive_evidence(  # noqa: SLF001
        NOW + timedelta(minutes=3)
    )

    assert evidence["office"] == ()
