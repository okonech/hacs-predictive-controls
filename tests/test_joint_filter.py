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
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {
                    "zone": "kitchen",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
                "garage": {
                    "zone": "garage",
                    "entities": {"motion": "binary_sensor.garage"},
                    "adjacent": [],
                },
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


def test_filter_censored_graph_path_is_one_use_and_preserves_via_provenance() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("office"), PositionState("garage"))
                ): 0.0
            },
            NOW,
        )
    )
    occupancy_filter.observe(event("hall", NOW + timedelta(seconds=1)))
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=10)))

    arrived = occupancy_filter.observe(
        event("kitchen", NOW + timedelta(seconds=20))
    )
    censored = tuple(
        evidence
        for evidence in arrived.movement_evidence
        if evidence.disposition == "censored_graph_path"
    )

    assert censored
    assert all(
        evidence.source_zone == "office"
        and evidence.via_zone == "hall"
        and evidence.via_node_id == "hall"
        and evidence.target_zone == "kitchen"
        for evidence in censored
    )
    assert occupancy_filter.consumed_censored_paths
    assert probability_sum(arrived.current) == pytest.approx(1.0)
    assert sum(arrived.count_marginals[zone][1] for zone in make_map().zones()) <= 2.0

    occupancy_filter.observe(
        event("kitchen", NOW + timedelta(seconds=21), state="off")
    )
    repeated = occupancy_filter.observe(
        event("kitchen", NOW + timedelta(seconds=22))
    )
    assert not any(
        evidence.disposition == "censored_graph_path"
        for evidence in repeated.movement_evidence
    )

    departed = occupancy_filter.observe(
        event("hall", NOW + timedelta(seconds=23), state="off")
    )
    departed = occupancy_filter.observe(event("hall", NOW + timedelta(seconds=24)))
    assert any(
        evidence.disposition == "graph_valid"
        and evidence.source_zone == "kitchen"
        and evidence.target_zone == "hall"
        for evidence in departed.movement_evidence
    )


@pytest.mark.parametrize(
    "gate_state,target_seconds",
    [
        ("off", 20),
        ("invalidated", 20),
        ("unavailable", 20),
        ("on", 62),
    ],
)
def test_filter_censored_graph_path_rejects_clear_or_late_gate(
    gate_state: str,
    target_seconds: int,
) -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)
    occupancy_filter.observe(event("hall", NOW + timedelta(seconds=1)))
    if gate_state == "off":
        occupancy_filter.observe(event("hall", NOW + timedelta(seconds=2), "off"))
    elif gate_state == "invalidated":
        occupancy_filter.observations.invalidate_asserted_episode(
            "binary_sensor.hall"
        )
    elif gate_state == "unavailable":
        occupancy_filter.observe(
            event("hall", NOW + timedelta(seconds=2), "unavailable")
        )
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=10)))

    arrived = occupancy_filter.observe(
        event("kitchen", NOW + timedelta(seconds=target_seconds))
    )

    assert not any(
        evidence.disposition == "censored_graph_path"
        for evidence in arrived.movement_evidence
    )


def test_filter_censored_graph_path_survives_restart_and_consumption() -> None:
    predictive_map = make_map()
    original = JointOccupancyFilter(predictive_map, 1, NOW)
    gate = event("hall", NOW + timedelta(seconds=1))
    source = event("office", NOW + timedelta(seconds=10))
    original.observe(gate)
    original.observe(source)

    restored = JointOccupancyFilter(predictive_map, 1, NOW)
    restored.restore_posterior(original.posterior)
    restored.restore_directional_contexts(
        original.directional_contexts,
        original.update_sequence,
    )
    restored.observations.restore_entity_states(original.observations.entity_states)
    restored.restore_consumed_censored_paths(original.consumed_censored_paths)
    restored.bootstrap((gate, source), cold_start=False)

    arrived = restored.observe(event("kitchen", NOW + timedelta(seconds=20)))
    assert any(
        evidence.disposition == "censored_graph_path"
        for evidence in arrived.movement_evidence
    )

    restarted = JointOccupancyFilter(predictive_map, 1, NOW)
    restarted.restore_posterior(restored.posterior)
    restarted.restore_directional_contexts(
        restored.directional_contexts,
        restored.update_sequence,
    )
    restarted.observations.restore_entity_states(restored.observations.entity_states)
    restarted.restore_consumed_censored_paths(restored.consumed_censored_paths)
    restarted.bootstrap(
        (gate, source, event("kitchen", NOW + timedelta(seconds=20))),
        cold_start=False,
    )
    restarted.observe(event("kitchen", NOW + timedelta(seconds=21), "off"))
    repeated = restarted.observe(event("kitchen", NOW + timedelta(seconds=22)))
    assert not any(
        evidence.disposition == "censored_graph_path"
        for evidence in repeated.movement_evidence
    )


def test_filter_censored_graph_path_selects_latest_eligible_gate() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall_a", "hall_b"],
                },
                "hall_a": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall_a"},
                    "adjacent": ["office", "kitchen"],
                },
                "hall_b": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall_b"},
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall_a", "hall_b"],
                },
            }
        }
    )
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    occupancy_filter.observe(event("hall_a", NOW + timedelta(seconds=1)))
    occupancy_filter.observe(event("hall_b", NOW + timedelta(seconds=2)))
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=10)))

    arrived = occupancy_filter.observe(
        event("kitchen", NOW + timedelta(seconds=20))
    )

    assert {
        evidence.via_zone
        for evidence in arrived.movement_evidence
        if evidence.disposition == "censored_graph_path"
    } == {"hall_b"}


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
    with pytest.raises(ValueError, match="identifiers must be non-empty"):
        restored.restore_consumed_censored_paths((("", "source"),))


def test_filter_discards_stale_motion_from_positive_corroboration() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))

    fresh_evidence = occupancy_filter.active_positive_evidence(
        NOW + timedelta(minutes=3)
    )
    asserted_evidence = occupancy_filter.asserted_positive_evidence(
        NOW + timedelta(minutes=3)
    )

    assert fresh_evidence["office"] == ()
    assert tuple(item.entity_id for item in asserted_evidence["office"]) == (
        "binary_sensor.office",
    )


def test_filter_sustained_duration_saturates_and_stops_after_departure() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    arrival = occupancy_filter.occupied_marginals["office"]
    office_context = next(
        context
        for contexts in occupancy_filter.directional_contexts.values()
        for context in contexts
        if context.current_node_id == "office"
    )

    assert occupancy_filter.reinforce_asserted_evidence(
        NOW + timedelta(minutes=22)
    )
    reinforced = occupancy_filter.occupied_marginals["office"]
    assert reinforced > arrival
    assert not occupancy_filter.reinforce_asserted_evidence(
        NOW + timedelta(minutes=22)
    )
    reinforced_context = next(
        context
        for contexts in occupancy_filter.directional_contexts.values()
        for context in contexts
        if context.current_node_id == "office"
    )
    assert reinforced_context.last_event_at == office_context.last_event_at
    assert reinforced_context.assertion_valid_until == NOW + timedelta(minutes=22)

    occupancy_filter.observe(event("hall", NOW + timedelta(minutes=22, seconds=1)))
    office_state = occupancy_filter.observations.entity_states[
        "binary_sensor.office"
    ]
    assert office_state.departure_observed
    assert office_state.duration_log_odds == 0.0
    assert office_state.log_likelihood_by_count == (0.0, 0.0)
    assert not occupancy_filter.reinforce_asserted_evidence(
        NOW + timedelta(minutes=30)
    )


def test_filter_out_of_order_event_cannot_advance_sustained_evidence() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(minutes=10)))
    before_posterior = occupancy_filter.posterior
    before_states = occupancy_filter.observations.entity_states
    before_contexts = occupancy_filter.directional_contexts
    before_sequence = occupancy_filter.update_sequence

    update = occupancy_filter.observe(event("garage", NOW + timedelta(minutes=5)))

    assert update.provenance.disposition == "out_of_order"
    assert occupancy_filter.posterior == before_posterior
    assert occupancy_filter.observations.entity_states == before_states
    assert occupancy_filter.directional_contexts == before_contexts
    assert occupancy_filter.update_sequence == before_sequence


def test_filter_asserted_source_retains_missed_relocation_hypothesis() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    occupancy_filter.reinforce_asserted_evidence(NOW + timedelta(minutes=10))

    update = occupancy_filter.observe(
        event("garage", NOW + timedelta(minutes=10, seconds=1))
    )

    assert any(
        evidence.source_zone == "office"
        and evidence.target_zone == "garage"
        and evidence.disposition == "missed_movement"
        and evidence.coherent_probability > 0.0
        for evidence in update.movement_evidence
    )
