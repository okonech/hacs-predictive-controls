from __future__ import annotations

import itertools
import json
import math
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from occupancy_test_utils import (
    assert_count_conserved,
    assert_normalized,
    public_snapshot,
    run_trace,
)
from test_prediction import make_update as prediction_update

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.markov import MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.observation_model import ObservationModel
from custom_components.predictive_controls.occupancy_state import (
    PositionState,
    ReleaseCause,
    ZonePolicyState,
    canonical_hypothesis,
    normalize_hypotheses,
)
from custom_components.predictive_controls.prediction import PredictionManager

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
                "living": {
                    "entities": {"motion": "binary_sensor.living"},
                    "adjacent": ["hall"],
                },
                "bedroom": {
                    "entities": {"motion": "binary_sensor.bedroom"},
                    "adjacent": ["landing"],
                },
                "landing": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.landing"},
                    "adjacent": ["bedroom", "bath"],
                },
                "bath": {
                    "entities": {"motion": "binary_sensor.bath"},
                    "adjacent": ["landing"],
                },
                "garage": {
                    "entities": {
                        "motion": "binary_sensor.garage",
                        "moving_target": "binary_sensor.garage_moving_target",
                        "still_target": "binary_sensor.garage_still_target",
                        "zone_occupancy": "binary_sensor.garage_zone_occupancy",
                    },
                    "adjacent": [],
                },
                "garage_presence": {
                    "zone": "garage",
                    "entities": {"presence": "binary_sensor.garage_presence"},
                    "adjacent": [],
                },
            }
        }
    )


def event(
    zone: str,
    seconds: int,
    *,
    state: str = "on",
    entity_id: str | None = None,
    node_id: str | None = None,
    reliability: float = 0.99,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{zone}",
        node_id=node_id or zone,
        zone=zone,
        floor=None,
        role="transition_gate" if zone in {"hall", "landing"} else "room_occupancy",
        occupancy_behavior="transient" if zone in {"hall", "landing"} else "sustained",
        signal_type="motion",
        state=state,
        event_at=NOW + timedelta(seconds=seconds),
        reliability=reliability,
    )


def test_s01_s02_clear_and_elapsed_time_never_release_keep_on() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    trace = (
        event("office", 1),
        event("office", 2, state="off"),
        event("office", 4),
    )

    snapshots = run_trace(tracker, predictive_map, trace)
    tracker.expire_transient_state(NOW + timedelta(hours=6))
    final = public_snapshot(tracker, predictive_map, trace[-1])

    assert all(snapshot.zones["office"].keep_on for snapshot in snapshots)
    assert final.zones["office"].keep_on
    assert not final.zones["office"].activation_plausible
    assert tracker.diagnostics.joint_policy_states["office"].last_release_cause is None


def test_s03_observed_departure_releases_origin_and_activates_destination() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)

    snapshots = run_trace(
        tracker,
        predictive_map,
        (event("office", 1), event("hall", 2), event("kitchen", 3)),
    )

    assert snapshots[0].zones["office"].keep_on
    assert not snapshots[-1].zones["office"].keep_on
    assert snapshots[-1].zones["kitchen"].keep_on
    assert snapshots[-1].zones["kitchen"].activation_plausible
    assert (
        tracker.diagnostics.joint_policy_states["office"].last_release_cause
        == "graph_departure"
    )
    assert_count_conserved(tracker, 1)


def test_s03_sustained_intermediate_releases_after_adjacent_departure() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)

    def incident_event(
        zone: str,
        timestamp: str,
        *,
        state: str = "on",
    ) -> OccupancyEvent:
        return replace(
            event(zone, 0, state=state),
            event_at=datetime.fromisoformat(timestamp),
        )

    snapshots = run_trace(
        tracker,
        predictive_map,
        (
            incident_event("office", "2026-07-13T19:44:25.720044-04:00"),
            incident_event("hall", "2026-07-13T19:45:01.417700-04:00"),
            incident_event(
                "hall",
                "2026-07-13T19:45:02.417700-04:00",
                state="off",
            ),
            incident_event("kitchen", "2026-07-13T19:45:05.638025-04:00"),
            incident_event("hall", "2026-07-13T19:46:09.704142-04:00"),
            incident_event(
                "kitchen",
                "2026-07-13T19:46:24.508538-04:00",
                state="off",
            ),
        ),
    )

    assert snapshots[3].zones["kitchen"].keep_on
    assert snapshots[3].zones["kitchen"].activation_plausible
    assert not snapshots[-1].zones["kitchen"].keep_on
    assert snapshots[-1].zones["hall"].keep_on
    assert (
        tracker.diagnostics.joint_policy_states["kitchen"].last_release_cause
        == "graph_departure"
    )
    assert_count_conserved(tracker, 1)


def test_s03_asserted_transition_supports_second_occupant_route() -> None:
    adjacency = {
        "workroom": ["hall"],
        "hall": ["workroom", "entry", "other_office", "stairs", "washroom"],
        "entry": ["hall", "closet"],
        "closet": ["entry", "bath"],
        "bath": ["closet"],
        "anchor": ["living", "stairs"],
        "dining": ["foyer", "gym", "kitchen", "living", "vestibule"],
        "vestibule": ["dining", "kitchen", "laundry"],
        "laundry": ["vestibule"],
        "foyer": ["dining", "stairs"],
        "gym": ["dining"],
        "kitchen": ["dining", "vestibule"],
        "living": ["anchor", "dining"],
        "other_office": ["hall", "washroom"],
        "stairs": ["anchor", "foyer", "hall"],
        "washroom": ["hall", "other_office"],
    }
    roles = {"hall": "transition_gate", "entry": "transition_gate"}
    behaviors = {
        "workroom": "sustained",
        "hall": "transient",
        "entry": "transient",
        "closet": "sustained",
        "bath": "sticky",
        "anchor": "sustained",
    }
    reliabilities = {
        "workroom": 0.75,
        "hall": 0.85,
        "entry": 0.8,
        "closet": 0.8,
        "bath": 0.7,
    }
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                zone: {
                    "role": roles.get(zone, "room_occupancy"),
                    "occupancy_behavior": behaviors.get(zone, "sustained"),
                    "initial_weight": reliabilities.get(zone, 0.75),
                    "entities": {"motion": f"binary_sensor.{zone}"},
                    "adjacent": neighbors,
                }
                for zone, neighbors in adjacency.items()
            },
        }
    )
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)

    captured_marginals = {
        "workroom": 0.9937038430546176,
        "dining": 0.000015110767781681922,
        "vestibule": 0.00005399074001303046,
        "laundry": 0.000000000003897432414031003,
        "foyer": 0.000012839346120867392,
        "anchor": 0.994706277850614,
        "gym": 1.688402858897895e-49,
        "kitchen": 0.000001236868555867169,
        "living": 0.00000000138817218194856,
        "bath": 0.00006570032515892287,
        "closet": 0.004692490991988322,
        "entry": 0.00014534408440393935,
        "other_office": 2.712543665519932e-15,
        "stairs": 0.00004901371615440477,
        "washroom": 0.0006377408068999706,
        "hall": 0.005899844087237978,
    }
    zones = tuple(sorted(predictive_map.zones()))
    keys = tuple(
        canonical_hypothesis((PositionState(left), PositionState(right)))
        for left, right in itertools.combinations_with_replacement(zones, 2)
    )
    weights = {key: 1.0 / len(keys) for key in keys}
    for _ in range(2_000):
        for zone in zones:
            current = math.fsum(
                probability
                for key, probability in weights.items()
                if any(position.zone == zone for position in key.positions)
            )
            wanted = captured_marginals[zone]
            odds_factor = wanted * (1.0 - current) / (current * (1.0 - wanted))
            weights = {
                key: probability
                * (
                    odds_factor
                    if any(position.zone == zone for position in key.positions)
                    else 1.0
                )
                for key, probability in weights.items()
            }
            total = math.fsum(weights.values())
            weights = {key: probability / total for key, probability in weights.items()}

    started_at = datetime.fromisoformat("2026-07-14T03:17:12.508501-04:00")
    tracker.reconcile_expected_occupants(2, started_at)
    assert tracker._joint_filter is not None  # noqa: SLF001
    tracker._joint_filter.restore_posterior(  # noqa: SLF001
        normalize_hypotheses(
            {
                key: math.log(probability)
                for key, probability in weights.items()
                if probability > 1e-300
            },
            started_at,
        )
    )
    assert all(
        tracker.states[zone].confidence == pytest.approx(marginal, abs=1e-6)
        for zone, marginal in captured_marginals.items()
    )

    def incident_event(
        zone: str,
        timestamp: str,
        *,
        state: str = "on",
    ) -> OccupancyEvent:
        node = predictive_map.nodes[zone]
        return OccupancyEvent(
            entity_id=f"binary_sensor.{zone}",
            node_id=zone,
            zone=zone,
            floor=None,
            role=node.role,
            occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
            signal_type="motion",
            state=state,
            event_at=datetime.fromisoformat(timestamp),
            reliability=node.initial_weight,
        )

    prior_workroom = incident_event("workroom", "2026-07-14T03:15:00-04:00")
    observations = ObservationModel(2, predictive_map=predictive_map)
    observations.prepare_delta(prior_workroom)
    tracker._joint_filter.observations.restore_entity_states(  # noqa: SLF001
        observations.entity_states
    )

    snapshots = run_trace(
        tracker,
        predictive_map,
        (
            incident_event("hall", "2026-07-14T03:17:12.508502-04:00"),
            incident_event(
                "workroom",
                "2026-07-14T03:17:28.821313-04:00",
                state="off",
            ),
            incident_event("workroom", "2026-07-14T03:17:35.172120-04:00"),
            incident_event("entry", "2026-07-14T03:17:43.573416-04:00"),
            incident_event("closet", "2026-07-14T03:17:46.913480-04:00"),
            incident_event("hall", "2026-07-14T03:17:53.495404-04:00", state="off"),
            incident_event(
                "workroom",
                "2026-07-14T03:17:56.196848-04:00",
                state="off",
            ),
            incident_event("entry", "2026-07-14T03:18:00.055739-04:00", state="off"),
            incident_event("bath", "2026-07-14T03:18:02.005122-04:00"),
        ),
    )

    assert snapshots[8].zones["bath"].activation_plausible
    assert snapshots[3].zones["entry"].activation_plausible
    assert snapshots[4].zones["closet"].activation_plausible
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s04_weak_nonadjacent_hit_is_quarantined() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)
    tracker.expire_transient_state(NOW + timedelta(seconds=10))

    tracker.observe(event("garage", 11, reliability=0.7))
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].keep_on
    assert not snapshot.zones["garage"].activation_plausible
    assert not snapshot.zones["garage"].keep_on


def test_s05_s07_independent_corroboration_repairs_missed_movement() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)
    tracker.expire_transient_state(NOW + timedelta(seconds=10))
    tracker.observe(event("garage", 11, entity_id="binary_sensor.garage"))
    tracker.observe(
        event(
            "garage",
            12,
            entity_id="binary_sensor.garage_presence",
            node_id="garage_presence",
        )
    )
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["garage"].activation_plausible
    assert snapshot.zones["garage"].keep_on
    assert not snapshot.zones["office"].keep_on
    assert tracker.diagnostics.joint_policy_states["office"].last_release_cause == (
        "confirmed_relocation"
    )
    assert tracker.diagnostics.joint_last_provenance is not None
    assert tracker.diagnostics.joint_last_provenance.entity_id == (
        "binary_sensor.garage_presence"
    )


def test_s06_repeated_single_source_never_manufactures_corroboration() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)
    tracker.expire_transient_state(NOW + timedelta(seconds=10))
    for seconds in range(11, 19, 2):
        tracker.observe(event("garage", seconds))
        tracker.observe(event("garage", seconds + 1, state="off"))
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].keep_on
    assert not snapshot.zones["garage"].activation_plausible
    assert not snapshot.zones["garage"].keep_on
    assert tracker.diagnostics.joint_policy_states["garage"].evidence_ids == ()


def test_s06_correlated_remote_aliases_cannot_release_sustained_ownership() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)
    tracker.expire_transient_state(NOW + timedelta(minutes=10))

    tracker.observe(
        event(
            "garage",
            601,
            entity_id="binary_sensor.garage",
        )
    )
    tracker.observe(
        event(
            "garage",
            602,
            entity_id="binary_sensor.garage_moving_target",
        )
    )
    tracker.observe(
        event(
            "garage",
            603,
            entity_id="binary_sensor.garage_still_target",
        )
    )
    tracker.observe(
        event(
            "garage",
            604,
            entity_id="binary_sensor.garage_zone_occupancy",
        )
    )
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].keep_on
    assert not snapshot.zones["garage"].activation_plausible
    assert not snapshot.zones["garage"].keep_on
    assert tracker.diagnostics.joint_policy_states["office"].last_release_cause is None
    assert tracker.states["office"].last_node_id == "office"


def test_s06_remote_aliases_support_other_occupant_without_moving_origin() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    office = event("office", 1)
    tracker.observe(office)
    tracker.observe(
        event(
            "garage",
            2,
            entity_id="binary_sensor.garage",
        )
    )
    office_before_aliases = tracker.diagnostics.joint_occupied_marginals["office"]

    for seconds, entity_id in enumerate(
        (
            "binary_sensor.garage_moving_target",
            "binary_sensor.garage_still_target",
            "binary_sensor.garage_zone_occupancy",
        ),
        start=3,
    ):
        tracker.observe(
            event(
                "garage",
                seconds,
                entity_id=entity_id,
            )
        )
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].keep_on
    assert tracker.diagnostics.joint_policy_states["office"].last_release_cause is None
    assert tracker.diagnostics.joint_occupied_marginals["office"] == pytest.approx(
        office_before_aliases
    )
    assert tracker.diagnostics.joint_movement_evidence == ()
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s08_two_interleaved_paths_conserve_both_occupants() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    snapshots = run_trace(
        tracker,
        predictive_map,
        (
            event("office", 1),
            event("bedroom", 2),
            event("hall", 3),
            event("landing", 4),
            event("kitchen", 5),
            event("bath", 6),
        ),
    )

    assert snapshots[-1].zones["kitchen"].keep_on
    assert snapshots[-1].zones["bath"].keep_on
    assert not snapshots[-1].zones["office"].keep_on
    assert not snapshots[-1].zones["bedroom"].keep_on
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s09_same_room_join_uses_one_zone_with_count_two() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("kitchen"), PositionState("kitchen"))
                ): 0.0
            },
            NOW,
        )
    )

    assert occupancy_filter.count_marginals["kitchen"] == pytest.approx((0.0, 0.0, 1.0))
    assert occupancy_filter.occupied_marginals["kitchen"] == 1.0
    assert len(occupancy_filter.posterior.hypotheses[0].key.positions) == 2


def test_s10_same_room_split_leaves_one_occupant_in_origin() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("kitchen"), PositionState("kitchen"))
                ): 0.0
            },
            NOW,
        )
    )

    moved = occupancy_filter.observe(event("hall", 1))

    assert moved.count_marginals["kitchen"][1] > 0.5
    assert moved.occupied_marginals["kitchen"] > 0.5
    assert moved.occupied_marginals["hall"] > 0.5
    assert all(len(item.key.positions) == 2 for item in moved.current.hypotheses)


def test_s10_one_departure_preserves_sustained_evidence_for_remaining_occupant() -> (
    None
):
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    office = event("office", 1)
    tracker.observe(office)
    assert tracker._joint_filter is not None  # noqa: SLF001
    tracker._joint_filter.restore_posterior(  # noqa: SLF001
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("office"), PositionState("office"))
                ): 0.0
            },
            office.event_at,
        )
    )

    latest_event = office
    for second, zone in enumerate(("hall", "kitchen", "hall", "living"), 2):
        latest_event = event(zone, second)
        tracker.observe(latest_event)
    snapshot = public_snapshot(tracker, predictive_map, latest_event)

    assert snapshot.zones["office"].keep_on
    assert tracker.diagnostics.joint_count_marginals["office"][1] > 0.9
    assert tracker.states["office"].confidence > 0.9
    assert tuple(
        evidence.entity_id
        for evidence in tracker._joint_filter.asserted_positive_evidence(  # noqa: SLF001
            latest_event.event_at
        )["office"]
    ) == ("binary_sensor.office",)


def test_s10_long_asserted_origin_stays_confident_during_other_occupant_route() -> (
    None
):
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)

    def incident_event(
        zone: str,
        timestamp: str,
        *,
        state: str = "on",
    ) -> OccupancyEvent:
        return replace(
            event(zone, 0, state=state),
            event_at=datetime.fromisoformat(timestamp),
        )

    office = incident_event("office", "2026-07-13T16:43:54-04:00")
    tracker.observe(office)
    tracker.observe(incident_event("kitchen", "2026-07-13T16:43:55-04:00"))
    tracker.observe(
        incident_event("kitchen", "2026-07-13T16:43:56-04:00", state="off")
    )
    tracker.expire_transient_state(
        datetime.fromisoformat("2026-07-13T17:03:54-04:00")
    )

    for asserted_at, cleared_at in (
        ("2026-07-13T17:05:00-04:00", "2026-07-13T17:05:01-04:00"),
        ("2026-07-13T17:15:00-04:00", "2026-07-13T17:15:01-04:00"),
        ("2026-07-13T17:16:00-04:00", "2026-07-13T17:16:01-04:00"),
    ):
        tracker.observe(incident_event("hall", asserted_at))
        tracker.observe(incident_event("hall", cleared_at, state="off"))
    tracker.observe(incident_event("hall", "2026-07-13T17:35:38-04:00"))
    latest_event = incident_event("living", "2026-07-13T17:35:50-04:00")
    tracker.observe(latest_event)
    tracker.expire_transient_state(
        datetime.fromisoformat("2026-07-13T17:35:51-04:00")
    )
    snapshot = public_snapshot(tracker, predictive_map, latest_event)
    occupancy_filter = tracker._joint_filter  # noqa: SLF001
    assert occupancy_filter is not None
    office_state = occupancy_filter.observations.entity_states[
        "binary_sensor.office"
    ]
    office_departure_probability = sum(
        evidence.coherent_probability
        for evidence in tracker.diagnostics.joint_movement_evidence
        if evidence.origin_zone == "office"
    )

    assert snapshot.zones["office"].keep_on
    assert latest_event.event_at - office_state.changed_at == timedelta(
        minutes=51,
        seconds=56,
    )
    assert tracker.states["office"].confidence > 0.6
    assert tracker.states["office"].confidence == max(
        tracker.diagnostics.joint_occupied_marginals.values()
    )
    assert office_departure_probability < 0.85
    assert not office_state.departure_observed
    assert tuple(
        evidence.entity_id
        for evidence in occupancy_filter.asserted_positive_evidence(
            latest_event.event_at
        )["office"]
    ) == ("binary_sensor.office",)
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s11_crossing_permutations_canonicalize_to_one_configuration() -> None:
    first = canonical_hypothesis((PositionState("office"), PositionState("kitchen")))
    second = canonical_hypothesis((PositionState("kitchen"), PositionState("office")))

    assert first == second
    assert first.positions == (PositionState("kitchen"), PositionState("office"))


def test_s12_s13_forced_and_learned_predictions_exclude_incoming_zone() -> None:
    predictive_map = make_map()
    chain = MarkovChain(predictive_map)
    chain.observe("hall", "kitchen", weight=8.0)
    chain.observe("hall", "living", weight=2.0)
    manager = PredictionManager(predictive_map, chain)

    manager.apply(prediction_update(("bedroom", "landing"), 0.8, "landing"))
    assert manager.probabilities == {"bath": 0.8}
    manager.apply(prediction_update(("office", "hall"), 1.0, "hall"))

    assert "office" not in manager.probabilities
    assert manager.probabilities["kitchen"] > manager.probabilities["living"]
    assert manager.probabilities["bath"] == 0.8


def test_s14_s15_reversal_cancels_only_its_own_prediction_path() -> None:
    manager = PredictionManager(make_map())
    manager.apply(prediction_update(("office", "hall"), 0.8, "hall"))
    manager.apply(prediction_update(("bedroom", "landing"), 0.9, "landing"))

    manager.apply(prediction_update(("hall", "office"), 0.9, "office"))

    assert manager.probabilities == {"bath": 0.9}
    assert all(lease.target_zone == "bath" for lease in manager.leases)


def test_s22_out_of_order_event_is_quarantined_without_invented_path() -> None:
    tracker = ZoneConfidenceEngine(make_map(), expected_occupants=1)
    tracker.observe(event("office", 1))
    tracker.observe(event("hall", 3))
    posterior = tracker.diagnostics.joint_posterior
    policy = tracker.diagnostics.joint_policy_states
    predictions = tracker.diagnostics.joint_prediction_leases
    tracker.observe(event("kitchen", 2))

    assert tracker.diagnostics.joint_posterior == posterior
    assert tracker.diagnostics.joint_policy_states == policy
    assert tracker.diagnostics.joint_prediction_leases == predictions
    assert tracker.diagnostics.joint_last_provenance is not None
    assert tracker.diagnostics.joint_last_provenance.disposition == "out_of_order"


def test_s23_provisional_false_off_can_emit_recovery_activation() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    tracker.ensure_joint_state(NOW)
    tracker._joint_policy.restore_states(  # noqa: SLF001
        {
            zone: ZonePolicyState(
                keep_on=False,
                last_trusted_at=NOW - timedelta(minutes=1)
                if zone == "office"
                else None,
                last_release_cause=ReleaseCause.PROVISIONAL_FALSE_OFF
                if zone == "office"
                else None,
                recovery_eligible=zone == "office",
            )
            for zone in predictive_map.zones()
        }
    )

    office = event("office", 1)
    tracker.observe(office)
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].activation_plausible
    assert snapshot.zones["office"].keep_on
    assert tracker.diagnostics.joint_policy_states["office"].reason == (
        "trusted occupancy reacquired after release"
    )


@pytest.mark.parametrize("seed", range(100))
def test_s24_equal_time_replay_is_deterministic_across_seeded_permutations(
    seed: int,
) -> None:
    predictive_map = make_map()
    simultaneous = (
        event("office", 1),
        event("bedroom", 1),
        event("garage", 1, state="off"),
    )
    baseline = _serialized_replay(predictive_map, simultaneous)
    for _ in range(2):
        shuffled = list(simultaneous)
        random.Random(seed).shuffle(shuffled)
        assert _serialized_replay(predictive_map, tuple(shuffled)) == baseline


def _serialized_replay(
    predictive_map: PredictiveMap,
    events: tuple[OccupancyEvent, ...],
) -> bytes:
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    timeline = run_trace(tracker, predictive_map, events)
    diagnostics = tracker.diagnostics
    payload = {
        "timeline": [
            {
                "entity_id": snapshot.event.entity_id,
                "event_at": snapshot.event.event_at.isoformat(),
                "state": snapshot.event.state,
                "zones": {
                    zone: {
                        "activation_plausible": state.activation_plausible,
                        "keep_on": state.keep_on,
                        "prelight_plausible": state.prelight_plausible,
                    }
                    for zone, state in sorted(snapshot.zones.items())
                },
            }
            for snapshot in timeline
        ],
        "posterior": [
            {
                "positions": [
                    {
                        "zone": position.zone,
                        "incoming_zone": position.incoming_zone,
                    }
                    for position in hypothesis.key.positions
                ],
                "log_probability": hypothesis.log_probability,
            }
            for hypothesis in diagnostics.joint_posterior
        ],
        "policy": {
            zone: {
                "keep_on": state.keep_on,
                "reason": state.reason,
                "evidence_ids": state.evidence_ids,
            }
            for zone, state in sorted(diagnostics.joint_policy_states.items())
        },
        "operation_count": diagnostics.joint_performance["last_operation_count"],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_s25_activation_expiry_is_independent_from_keep_on() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    first = event("office", 1)
    tracker.observe(first)
    active = public_snapshot(tracker, predictive_map, first)

    tracker.expire_transient_state(NOW + timedelta(seconds=7))
    expired = public_snapshot(tracker, predictive_map, first)

    assert active.zones["office"].activation_plausible
    assert active.zones["office"].keep_on
    assert not expired.zones["office"].activation_plausible
    assert expired.zones["office"].keep_on


def test_s27_interleaved_learning_uses_only_coherent_edges() -> None:
    manager = PredictionManager(make_map())
    updates = (
        prediction_update(("office", "hall"), 0.9, "hall"),
        prediction_update(("bedroom", "landing"), 0.9, "landing"),
    )

    learned = tuple(edge for update in updates for edge in manager.learn(update))

    assert learned == (("office", "hall"), ("bedroom", "landing"))
    assert manager.chain.counts["office"]["hall"] == pytest.approx(0.9)
    assert manager.chain.counts["bedroom"]["landing"] == pytest.approx(0.9)
    assert manager.chain.counts["office"].get("landing", 0.0) == 0.0
