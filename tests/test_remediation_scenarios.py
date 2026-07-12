from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns

import pytest
from occupancy_test_utils import assert_count_conserved, public_snapshot

from custom_components.predictive_controls.automation_policy import AutomationPolicy
from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_persistence import (
    restore_occupancy_state,
)
from custom_components.predictive_controls.occupancy_state import (
    PositionState,
    ZonePolicyState,
    canonical_hypothesis,
    normalize_hypotheses,
)
from custom_components.predictive_controls.yaml_config import load_predictive_map

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def make_map(*, transition_seconds: float | None = None) -> PredictiveMap:
    office_timing = {} if transition_seconds is None else {"hall": transition_seconds}
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                    "transition_seconds": office_timing,
                },
                "living": {
                    "entities": {"motion": "binary_sensor.living"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "living", "kitchen"],
                },
                "kitchen": {
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
                "garage": {
                    "entities": {
                        "motion": "binary_sensor.garage",
                        "presence": "binary_sensor.garage_presence",
                    },
                    "adjacent": [],
                },
            }
        }
    )


def event(
    zone: str,
    seconds: int,
    *,
    entity_id: str | None = None,
    state: str = "on",
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor=None,
        role="transition_gate" if zone == "hall" else "room_occupancy",
        occupancy_behavior="transient" if zone == "hall" else "sustained",
        signal_type="motion",
        state=state,
        event_at=NOW + timedelta(seconds=seconds),
        reliability=0.99,
    )


def snapshot_event(predictive_map: PredictiveMap, entity_id: str) -> OccupancyEvent:
    binding = predictive_map.entity_binding_for_entity(entity_id)
    assert binding is not None
    node = predictive_map.nodes[binding.node_id]
    return OccupancyEvent(
        entity_id=entity_id,
        node_id=node.node_id,
        zone=node.occupancy_zone,
        floor=node.floor,
        role=node.role,
        occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
        signal_type=binding.signal_type,
        state="off",
        event_at=NOW,
        reliability=node.initial_weight,
    )


def test_r01_reference_map_two_occupant_bootstrap_performance() -> None:
    map_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "reference-map.yaml"
    )
    predictive_map = load_predictive_map(map_path.read_text())
    events = tuple(
        snapshot_event(predictive_map, entity_id)
        for entity_id in predictive_map.entity_ids()
    )
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)

    started_ns = perf_counter_ns()
    tracker.bootstrap_joint_state(events, cold_start=True)
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000

    assert len(events) == 23
    assert len(tracker.diagnostics.joint_posterior) == 153
    assert elapsed_ms <= 100.0
    assert tracker.diagnostics.joint_performance["last_operation_count"] == 153 * 23
    assert tracker.diagnostics.joint_pruned_probability == 0.0
    assert_count_conserved(tracker, 2)


def test_r02_release_followed_by_unsupported_local_hit_stays_released() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    for occupancy_event in (event("office", 1), event("hall", 2), event("kitchen", 3)):
        tracker.observe(occupancy_event)
    assert not tracker.diagnostics.joint_policy_states["office"].keep_on

    tracker.observe(event("office", 4, state="off"))
    tracker.observe(event("office", 5))
    snapshot = public_snapshot(tracker, predictive_map, event("office", 5))

    assert not snapshot.zones["office"].keep_on
    assert not snapshot.zones["office"].activation_plausible
    assert tracker.diagnostics.joint_policy_states["office"].last_release_cause == (
        "graph_departure"
    )
    assert tracker.diagnostics.joint_policy_decisions[-1].reason_code == (
        "support_gate_failed"
    )


def test_r03_restart_midway_through_departure_matches_uninterrupted() -> None:
    predictive_map = make_map()
    office = event("office", 1)
    hall = event("hall", 2)
    kitchen = event("kitchen", 3)
    uninterrupted = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    for occupancy_event in (office, hall, kitchen):
        uninterrupted.observe(occupancy_event)

    before_restart = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    before_restart.observe(office)
    before_restart.observe(hall)
    payload = before_restart.occupancy_store_data(NOW + timedelta(seconds=2), {})
    restored = restore_occupancy_state(
        payload,
        predictive_map,
        1,
        NOW + timedelta(seconds=2, milliseconds=500),
    )
    after_restart = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    after_restart.restore_joint_state(restored)
    after_restart.observe(kitchen)

    assert after_restart.diagnostics.joint_policy_states == (
        uninterrupted.diagnostics.joint_policy_states
    )
    assert after_restart.diagnostics.joint_occupied_marginals == pytest.approx(
        uninterrupted.diagnostics.joint_occupied_marginals
    )
    assert after_restart.diagnostics.joint_prediction_hints == pytest.approx(
        uninterrupted.diagnostics.joint_prediction_hints
    )


def test_r04_entity_rebound_rebuilds_evidence_in_new_zone() -> None:
    old_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.shared"},
                    "adjacent": ["hall"],
                },
                "hall": {"adjacent": ["office"]},
            }
        }
    )
    old = ZoneConfidenceEngine(old_map, expected_occupants=1)
    old_event = OccupancyEvent(
        "binary_sensor.shared",
        "office",
        "office",
        None,
        "room_occupancy",
        "sustained",
        "motion",
        "on",
        NOW,
        0.99,
    )
    old.observe(old_event)
    payload = old.occupancy_store_data(NOW, {})
    new_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "garage": {
                    "entities": {"motion": "binary_sensor.shared"},
                    "adjacent": ["hall"],
                },
                "hall": {"adjacent": ["garage"]},
            }
        }
    )
    restored = restore_occupancy_state(payload, new_map, 1, NOW + timedelta(seconds=1))
    rebuilt = ZoneConfidenceEngine(new_map, expected_occupants=1)
    rebuilt.restore_joint_state(restored)
    rebound = replace(
        old_event,
        node_id="garage",
        zone="garage",
        event_at=NOW + timedelta(seconds=1),
    )
    rebuilt.bootstrap_joint_state((rebound,), cold_start=False)

    assert rebuilt.diagnostics.joint_restore_status == "map_changed_rebuilt"
    assert rebuilt.diagnostics.joint_occupied_marginals["garage"] > 0.5
    assert "office" not in rebuilt.diagnostics.joint_occupied_marginals
    assert rebuilt.diagnostics.joint_last_provenance is not None
    assert rebuilt.diagnostics.joint_last_provenance.disposition == "accepted"


def test_r05_ambiguous_source_nodes_learn_no_concrete_edge() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_a": {"zone": "office", "adjacent": ["hall"]},
                "office_b": {"zone": "office", "adjacent": ["hall"]},
                "hall": {"adjacent": ["office_a", "office_b"]},
            }
        }
    )
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    tracker.bootstrap_joint_state(
        (
            OccupancyEvent(
                "binary_sensor.office",
                "office_a",
                "office",
                None,
                "room_occupancy",
                "sustained",
                "motion",
                "on",
                NOW,
                0.99,
            ),
        ),
        cold_start=True,
    )
    tracker.observe(
        OccupancyEvent(
            "binary_sensor.hall",
            "hall",
            "hall",
            None,
            "transition_gate",
            "transient",
            "motion",
            "on",
            NOW + timedelta(seconds=1),
            0.99,
        )
    )

    assert tracker._joint_predictions.chain.counts["office_a"]["hall"] == 0.0  # noqa: SLF001
    assert tracker._joint_predictions.chain.counts["office_b"]["hall"] == 0.0  # noqa: SLF001


def test_r06_shared_corridor_event_advances_at_most_one_origin() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 2, NOW)
    occupancy_filter.restore_posterior(
        normalize_hypotheses(
            {
                canonical_hypothesis(
                    (PositionState("office"), PositionState("living"))
                ): 0.0
            },
            NOW,
        )
    )
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone in {"office", "living"},
                last_trusted_at=NOW if zone in {"office", "living"} else None,
            )
            for zone in predictive_map.zones()
        }
    )

    policy.apply(occupancy_filter.observe(event("hall", 1)))

    assert len(policy.pending_departures) <= 1
    assert all(
        len(hypothesis.key.positions) == 2
        for hypothesis in occupancy_filter.posterior.hypotheses
    )


def test_r07_nonreciprocal_graph_declaration_is_rejected() -> None:
    with pytest.raises(ValueError, match="reciprocal"):
        PredictiveMap.from_mapping(
            {
                "nodes": {
                    "office": {"adjacent": ["hall"]},
                    "hall": {"adjacent": []},
                }
            }
        )


def test_r08_directed_timing_accepts_fast_path_and_rejects_late_release() -> None:
    predictive_map = make_map(transition_seconds=2.0)
    fast = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    for occupancy_event in (event("office", 0), event("hall", 1)):
        fast.observe(occupancy_event)
    fast_evidence = fast.diagnostics.joint_movement_evidence[0]

    late = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    for occupancy_event in (event("office", 0), event("hall", 10)):
        late.observe(occupancy_event)

    assert fast_evidence.disposition == "graph_valid"
    assert not fast.diagnostics.joint_policy_states["office"].keep_on
    assert any(
        evidence.disposition == "missed_timing"
        for evidence in late.diagnostics.joint_movement_evidence
    )
    assert late.diagnostics.joint_policy_states["office"].keep_on
    assert late.diagnostics.joint_policy_decisions[0].reason_code == (
        "missed_timing_gate_failed"
    )


def test_r09_unsupported_dynamic_count_enters_diagnostic_safe_state() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    tracker.observe(event("office", 1))

    tracker.reconcile_expected_occupants(3, NOW + timedelta(seconds=2))
    snapshot = public_snapshot(tracker, predictive_map, event("office", 1))

    assert tracker.requested_expected_occupants == 3
    assert tracker.config.expected_occupants == 0
    assert tracker.diagnostics.joint_unsupported_count == 3
    assert tracker.diagnostics.joint_requested_occupants == 3
    assert tracker.diagnostics.joint_posterior[0].key.positions == ()
    assert snapshot.zones["office"].keep_on
    assert all(not zone.activation_plausible for zone in snapshot.zones.values())
    assert all(not zone.prelight_plausible for zone in snapshot.zones.values())


def test_r10_context_compaction_preserves_parent_occupancy_mass() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 2, NOW)
    for seconds, zone in enumerate(
        ("office", "hall", "kitchen", "hall", "living", "hall") * 8,
        start=1,
    ):
        occupancy_filter.observe(event(zone, seconds))

    posterior_weights = {
        hypothesis.key: hypothesis.log_probability
        for hypothesis in occupancy_filter.posterior.hypotheses
    }
    assert all(
        len(contexts) <= 4
        for contexts in occupancy_filter.directional_contexts.values()
    )
    assert occupancy_filter.context_count <= occupancy_filter.configuration_count * 4
    assert occupancy_filter.performance_metrics["p50_ms"] >= 0.0
    assert (
        occupancy_filter.performance_metrics["last_candidate_expansions"]
        == (occupancy_filter.performance_metrics["last_operation_count"])
    )
    assert occupancy_filter.performance_metrics["last_context_compactions"] >= 0
    assert all(
        math.isclose(
            math.fsum(math.exp(context.log_probability) for context in contexts),
            math.exp(posterior_weights[key]),
            abs_tol=1e-12,
        )
        for key, contexts in occupancy_filter.directional_contexts.items()
    )
    assert occupancy_filter.posterior.pruned_probability == 0.0
