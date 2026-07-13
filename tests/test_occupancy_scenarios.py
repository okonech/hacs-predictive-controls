from __future__ import annotations

import json
import random
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
