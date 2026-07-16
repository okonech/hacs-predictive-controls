from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.automation_policy import AutomationPolicy
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.legacy_adapter import (
    LegacyInferenceEngine,
)
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_settings import (
    authoritative_occupants_from_state_value,
)
from custom_components.predictive_controls.occupancy_state import (
    PendingDeparture,
    PositiveEvidence,
    ZonePolicyState,
    probability_sum,
)
from tests.test_automation_policy import make_update

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def make_map(*, hall_is_transition: bool = True) -> PredictiveMap:
    hall_config: dict[str, object] = {
        "zone": "hall",
        "entities": {
            "motion": "binary_sensor.hall",
            "presence": "binary_sensor.hall_alias",
        },
        "adjacent": ["office", "kitchen"],
    }
    if hall_is_transition:
        hall_config.update(
            role="transition_gate",
            occupancy_behavior="transient",
        )
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": hall_config,
                "kitchen": {
                    "zone": "kitchen",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
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
    is_hall = zone == "hall"
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor="first_floor",
        role="transition_gate" if is_hall else "room_occupancy",
        occupancy_behavior="transient" if is_hall else "sustained",
        signal_type="motion",
        state=state,
        event_at=NOW + timedelta(seconds=seconds),
        reliability=0.9,
    )


def make_legacy(expected_occupants: int = 1) -> LegacyInferenceEngine:
    predictive_map = make_map()
    return LegacyInferenceEngine(
        predictive_map,
        ZoneGraph.from_map(predictive_map),
        expected_occupants,
        None,
    )


def test_legacy_adapter_lazy_lifecycle_and_projection_contract() -> None:
    engine = make_legacy()

    initial = engine.diagnostics
    assert engine.filter is None
    assert engine.predictions.leases == ()
    assert initial.expected_occupants == 1
    assert initial.occupied_marginals == {}
    assert initial.normalization == 1.0
    assert initial.updated_at is None
    assert not engine.finalize(NOW)

    engine.ensure(NOW)
    assert engine.filter is not None
    assert engine.diagnostics.normalization == pytest.approx(1.0, abs=1e-12)
    assert engine.diagnostics.event_disposition is None

    observed = engine.observe(event("office", 1), emit_activation=True)
    assert observed.event_disposition == "accepted"
    assert engine.policy.states["office"].keep_on
    assert probability_sum(engine.filter.posterior) == pytest.approx(1.0)


def test_legacy_adapter_bootstrap_and_count_controls_preserve_policy_safety() -> None:
    engine = make_legacy()
    bootstrapped = engine.bootstrap((event("office", 1),), cold_start=True)

    assert bootstrapped.event_disposition == "accepted"
    assert engine.policy.states["office"].keep_on
    assert engine.policy.states["office"].activation_expires_at is None

    engine.observe(event("office", 2, state="off"), emit_activation=False)
    engine.observe(event("office", 3), emit_activation=True)
    held = engine.policy.states["office"]
    assert held.keep_on
    assert held.activation_expires_at is not None

    reconciled = engine.reconcile_count(
        2,
        NOW + timedelta(seconds=4),
        "count-two",
        reconcile_policy=True,
    )
    assert reconciled.expected_occupants == 2
    assert engine.filter is not None
    assert engine.filter.expected_occupants == 2

    unchanged = engine.reconcile_count(
        2,
        NOW + timedelta(seconds=4, milliseconds=500),
        "count-two-unchanged",
        reconcile_policy=False,
    )
    assert unchanged.expected_occupants == 2

    without_policy_reconciliation = engine.reconcile_count(
        1,
        NOW + timedelta(seconds=5),
        "count-one",
        reconcile_policy=False,
    )
    assert without_policy_reconciliation.expected_occupants == 1
    assert engine.policy.states["office"].keep_on

    unsupported = engine.enter_unsupported_count(
        6,
        NOW + timedelta(seconds=6),
        "count-invalid",
    )
    state = engine.policy.states["office"]
    assert unsupported.expected_occupants == 0
    assert state.keep_on
    assert state.activation_expires_at is None
    assert engine.policy.pending_departures == {}
    assert {
        decision.reason_code for decision in engine.policy.last_decisions
    } == {"unsupported_occupant_count"}

    lazy = make_legacy(2)
    lazy_unsupported = lazy.enter_unsupported_count(
        6,
        NOW + timedelta(seconds=7),
        "lazy-count-invalid",
    )
    assert lazy.filter is None
    assert lazy_unsupported.expected_occupants == 0


def test_policy_missed_timing_keeps_ownership_and_records_rejection() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW if zone == "office" else None,
            )
            for zone in graph.zones()
        }
    )
    policy.restore_pending_departures(
        {
            "office": PendingDeparture(
                "office",
                "hall",
                0.99,
                False,
                ("late-route",),
                "missed_timing",
            )
        }
    )
    update = make_update(
        previous={"office": 0.95, "hall": 0.05},
        current={"office": 0.01, "hall": 0.99},
        movement={},
        event_id="late-route",
        zone="hall",
        positive_evidence=(
            PositiveEvidence(
                "binary_sensor.hall",
                "hall-episode",
                NOW,
                "motion",
                "hall",
            ),
        ),
    )

    policy.apply(update)

    assert policy.states["office"].keep_on
    decision = next(
        item
        for item in policy.last_decisions
        if item.zone == "office" and item.action == "release"
    )
    assert not decision.accepted
    assert decision.reason_code == "missed_timing_gate_failed"
    assert decision.evidence_ids == ("late-route",)


def test_filter_correlated_alias_is_stationary_and_normalized() -> None:
    occupancy_filter = JointOccupancyFilter(make_map(), 1, NOW)
    first = occupancy_filter.observe(event("hall", 1))
    before_context_count = occupancy_filter.context_count
    alias = occupancy_filter.observe(
        event("hall", 2, entity_id="binary_sensor.hall_alias")
    )

    assert first.provenance.disposition == "accepted"
    assert alias.provenance.disposition == "correlated_alias"
    assert alias.movement_mass == {}
    assert alias.movement_evidence == ()
    assert probability_sum(alias.current) == pytest.approx(1.0)
    assert occupancy_filter.context_count == before_context_count
    assert occupancy_filter.last_update == alias


def test_filter_rejects_non_transition_gate_for_censored_route() -> None:
    occupancy_filter = JointOccupancyFilter(
        make_map(hall_is_transition=False),
        1,
        NOW,
    )
    occupancy_filter.observe(event("hall", 1))
    occupancy_filter.observe(event("office", 10))

    arrived = occupancy_filter.observe(event("kitchen", 20))

    assert not any(
        evidence.disposition == "censored_graph_path"
        for evidence in arrived.movement_evidence
    )
    assert probability_sum(arrived.current) == pytest.approx(1.0)


def test_empty_filter_metrics_and_none_authoritative_count_are_neutral() -> None:
    metrics = JointOccupancyFilter(make_map(), 1, NOW).performance_metrics

    assert metrics["sample_count"] == 0
    assert metrics["p50_ms"] == metrics["p95_ms"] == metrics["p99_ms"] == 0.0
    assert metrics["max_ms"] == 0.0
    assert authoritative_occupants_from_state_value(None) is None
