from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.predictive_controls.markov import MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_state import (
    FilterUpdate,
    MovementEvidence,
    ObservationProvenance,
    PositionState,
    PredictionLease,
    canonical_hypothesis,
    normalize_hypotheses,
    zone_marginals,
)
from custom_components.predictive_controls.prediction import PredictionManager

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"zone": "office", "adjacent": ["hall"]},
                "hall": {
                    "zone": "hall",
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
                "living": {"zone": "living", "adjacent": ["hall"]},
                "bedroom": {"zone": "bedroom", "adjacent": ["landing"]},
                "landing": {"zone": "landing", "adjacent": ["bedroom", "bath"]},
                "bath": {"zone": "bath", "adjacent": ["landing"]},
            }
        }
    )


def test_prediction_scenario_forced_paths_coexist_and_reverse_independently() -> None:
    manager = PredictionManager(make_map())
    hall_update = make_update(("office", "hall"), 0.7, "hall")
    landing_update = make_update(("bedroom", "landing"), 0.8, "landing")

    manager.apply(hall_update)
    manager.apply(landing_update)

    assert manager.probabilities == pytest.approx(
        {"bath": 0.8, "kitchen": 0.35, "living": 0.35}
    )
    assert len(manager.leases) == 3

    reversal = make_update(("hall", "office"), 0.9, "office")
    manager.apply(reversal)
    assert manager.probabilities == pytest.approx({"bath": 0.8})


def test_prediction_scenario_learned_branching_uses_only_forward_candidates() -> None:
    predictive_map = make_map()
    chain = MarkovChain(predictive_map)
    chain.observe("hall", "kitchen", weight=8.0)
    chain.observe("hall", "living", weight=2.0)
    manager = PredictionManager(predictive_map, chain)

    manager.apply(make_update(("office", "hall"), 1.0, "hall"))

    assert set(manager.probabilities) == {"kitchen", "living"}
    assert manager.probabilities["kitchen"] > manager.probabilities["living"]
    assert all(
        lease.reason == "learned forward branch probability" for lease in manager.leases
    )


def test_prediction_scenario_learning_requires_consistent_high_mass_node_edge() -> None:
    predictive_map = make_map()
    manager = PredictionManager(predictive_map)

    assert manager.learn(make_update(("office", "hall"), 0.79, "hall")) == ()
    ignored = make_update(("office", "hall"), 0.9, "hall", disposition="duplicate")
    assert manager.learn(ignored) == ()
    mismatched = make_update(("office", "hall"), 0.9, "kitchen")
    assert manager.learn(mismatched) == ()
    disconnected = make_update(("bath", "office"), 0.9, "office")
    assert manager.learn(disconnected) == ()

    original_observe = manager.chain.observe
    manager.chain.observe = lambda *args, **kwargs: False  # type: ignore[method-assign]
    assert manager.learn(make_update(("office", "hall"), 0.9, "hall")) == ()
    manager.chain.observe = original_observe  # type: ignore[method-assign]

    learned = manager.learn(make_update(("office", "hall"), 0.9, "hall"))
    assert learned == (("office", "hall"),)
    assert manager.chain.counts["office"]["hall"] == pytest.approx(0.9)


def test_prediction_uses_promoted_route_prefix_as_bounded_branch_boost() -> None:
    manager = PredictionManager(make_map())
    route = (
        ("office", "hall"),
        ("hall", "kitchen"),
        ("kitchen", "hall"),
        ("hall", "office"),
    )
    for _ in range(4):
        for movement in route:
            assert manager.learn(make_update(movement, 0.9, movement[1]))

    leases = manager.apply(make_update(("office", "hall"), 1.0, "hall"))
    probabilities = {lease.target_zone: lease.probability for lease in leases}

    assert probabilities["kitchen"] > probabilities["living"]
    assert probabilities["living"] > 0.0
    assert manager.route_diagnostics["matched_prefix"]
    support = manager.route_diagnostics["support"]
    assert isinstance(support, float)
    assert support >= 2.0
    assert all(lease.target_zone != "office" for lease in leases)


def test_prediction_rejects_ambiguous_source_node_learning() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_a": {"zone": "office", "adjacent": ["hall"]},
                "office_b": {"zone": "office", "adjacent": ["hall"]},
                "hall": {
                    "zone": "hall",
                    "adjacent": ["office_a", "office_b"],
                },
            }
        }
    )
    manager = PredictionManager(predictive_map)
    update = make_update_for_map(
        predictive_map,
        ("office", "hall"),
        0.9,
        "hall",
        node_id="hall",
    )

    assert manager.learn(update) == ()
    assert manager.chain.counts["office_a"]["hall"] == 0.0
    assert manager.chain.counts["office_b"]["hall"] == 0.0


def test_prediction_ignores_aggregate_movement_without_path_evidence() -> None:
    manager = PredictionManager(make_map())
    update = make_update(("office", "hall"), 0.9, "hall")
    aggregate_only = FilterUpdate(
        previous=update.previous,
        current=update.current,
        occupied_marginals=update.occupied_marginals,
        count_marginals=update.count_marginals,
        movement_mass=update.movement_mass,
        provenance=update.provenance,
    )

    assert manager.apply(aggregate_only) == ()
    assert manager.learn(aggregate_only) == ()


def test_prediction_quarantines_ambiguous_anonymous_route_context() -> None:
    manager = PredictionManager(make_map())
    manager._route_contexts = (  # noqa: SLF001
        ("office", "hall"),
        ("kitchen", "hall"),
    )

    assert manager._route_history_for_edge(  # noqa: SLF001
        SimpleNamespace(source_node_id="hall", target_node_id="living")
    ) == ()
    assert manager._route_history_for_edge(  # noqa: SLF001
        SimpleNamespace(source_node_id=None, target_node_id="living")
    ) == ()


def test_prediction_scenario_expiry_count_reset_and_restore_are_isolated() -> None:
    manager = PredictionManager(make_map())
    manager.apply(make_update(("bedroom", "landing"), 0.8, "landing"))
    assert not manager.expire(NOW)
    assert manager.expire(NOW + timedelta(minutes=1))
    assert list(manager.leases) == []

    valid = PredictionLease(
        ("landing", "bedroom", "bath"),
        "bath",
        0.8,
        NOW + timedelta(seconds=30),
        "restored",
    )
    expired = PredictionLease(
        ("hall", "office", "kitchen"),
        "kitchen",
        0.7,
        NOW,
        "expired",
    )
    invalid = PredictionLease(
        ("missing", None, "bath"),
        "bath",
        0.6,
        NOW + timedelta(seconds=30),
        "invalid",
    )
    manager.restore_leases((valid, expired, invalid), NOW)
    assert list(manager.leases) == [valid]
    manager.reconcile_count(1, 2)
    assert list(manager.leases) == [valid]
    manager.reconcile_count(2, 1)
    assert list(manager.leases) == []
    manager.restore_leases((valid,), NOW)
    manager.reset()
    assert list(manager.leases) == []


def test_prediction_ignores_weak_non_evidence_dead_ends_and_equal_fallback() -> None:
    predictive_map = make_map()
    manager = PredictionManager(predictive_map)
    assert manager.apply(make_update(("office", "hall"), 0.4, "hall")) == ()
    assert (
        manager.apply(
            make_update(("office", "hall"), 0.9, "hall", disposition="ignored")
        )
        == ()
    )
    assert manager.apply(make_update(("hall", "office"), 0.9, "office")) == ()

    update = make_update(("office", "hall"), 0.8, "hall", node_id="missing")
    leases = manager.apply(update)
    assert len(leases) == 2
    assert {lease.probability for lease in leases} == {0.4}

    asymmetric_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"zone": "office", "adjacent": ["hall"]},
                "hall": {
                    "zone": "hall",
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
                "living": {"zone": "living", "adjacent": ["hall"]},
            }
        }
    )
    asymmetric = PredictionManager(asymmetric_map)
    equal_leases = asymmetric.apply(make_update(("office", "hall"), 0.8, "hall"))
    assert {lease.target_zone: lease.probability for lease in equal_leases} == {
        "kitchen": 0.4,
        "living": 0.4,
    }
    asymmetric.chain.probabilities = lambda _node: {}  # type: ignore[assignment]
    assert asymmetric._branch_probabilities(  # noqa: SLF001
        "hall", "hall", ("kitchen", "living")
    ) == {"kitchen": 0.5, "living": 0.5}


def make_update(
    movement: tuple[str, str],
    probability: float,
    zone: str,
    *,
    disposition: str = "accepted",
    node_id: str | None = None,
) -> FilterUpdate:
    predictive_map = make_map()
    previous = normalize_hypotheses(
        {canonical_hypothesis((PositionState(movement[0]),)): 0.0},
        NOW,
    )
    current = normalize_hypotheses(
        {canonical_hypothesis((PositionState(movement[1]),)): 0.0},
        NOW + timedelta(seconds=1),
    )
    occupied, counts = zone_marginals(current, predictive_map.zones())
    return FilterUpdate(
        previous=previous,
        current=current,
        occupied_marginals=occupied,
        count_marginals=counts,
        movement_mass={movement: probability},
        movement_evidence=(
            MovementEvidence(
                path_key=(movement[0], movement[0], node_id or zone),
                origin_zone=movement[0],
                source_zone=movement[0],
                target_zone=movement[1],
                coherent_probability=probability,
                source_node_id=movement[0],
                target_node_id=node_id or zone,
                evidence_ids=(f"{zone}-event",),
                disposition="graph_valid",
            ),
        ),
        provenance=ObservationProvenance(
            event_id=f"{zone}-event",
            evidence_episode_id=f"{zone}-episode",
            entity_id=f"binary_sensor.{zone}",
            node_id=node_id or zone,
            zone=zone,
            state="on",
            signal_type="motion",
            reliability=1.0,
            log_likelihood_by_count=(0.0, 0.0),
            disposition=disposition,
        ),
    )


def make_update_for_map(
    predictive_map: PredictiveMap,
    movement: tuple[str, str],
    probability: float,
    zone: str,
    *,
    node_id: str,
) -> FilterUpdate:
    previous = normalize_hypotheses(
        {canonical_hypothesis((PositionState(movement[0]),)): 0.0},
        NOW,
    )
    current = normalize_hypotheses(
        {canonical_hypothesis((PositionState(movement[1]),)): 0.0},
        NOW + timedelta(seconds=1),
    )
    occupied, counts = zone_marginals(current, predictive_map.zones())
    source_nodes = tuple(
        node.node_id
        for node in predictive_map.nodes.values()
        if node.occupancy_zone == movement[0] and node_id in node.adjacent
    )
    return FilterUpdate(
        previous=previous,
        current=current,
        occupied_marginals=occupied,
        count_marginals=counts,
        movement_mass={movement: probability},
        movement_evidence=(
            MovementEvidence(
                path_key=(
                    movement[0],
                    source_nodes[0] if len(source_nodes) == 1 else None,
                    node_id,
                ),
                origin_zone=movement[0],
                source_zone=movement[0],
                target_zone=movement[1],
                coherent_probability=probability,
                source_node_id=(source_nodes[0] if len(source_nodes) == 1 else None),
                target_node_id=node_id,
                evidence_ids=("event",),
                disposition="graph_valid",
            ),
        ),
        provenance=ObservationProvenance(
            event_id="event",
            evidence_episode_id="episode",
            entity_id=f"binary_sensor.{node_id}",
            node_id=node_id,
            zone=zone,
            state="on",
            signal_type="motion",
            reliability=1.0,
            log_likelihood_by_count=(0.0, 0.0),
            disposition="accepted",
        ),
    )
