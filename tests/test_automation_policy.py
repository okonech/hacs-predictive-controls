from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.automation_policy import (
    AutomationPolicy,
    PendingDeparture,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_state import (
    FilterUpdate,
    MovementEvidence,
    ObservationProvenance,
    PositionState,
    PositiveEvidence,
    Posterior,
    ZonePolicyState,
    canonical_hypothesis,
    normalize_hypotheses,
    zone_marginals,
)

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"zone": "office", "adjacent": ["hall"]},
                "hall": {"zone": "hall", "adjacent": ["office", "kitchen"]},
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
                "garage": {"zone": "garage", "adjacent": []},
            }
        }
    )


def event(
    zone: str,
    at: datetime,
    *,
    entity_id: str | None = None,
    state: str = "on",
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor=None,
        role="room_occupancy",
        occupancy_behavior="sustained",
        signal_type="motion",
        state=state,
        event_at=at,
        reliability=0.9,
    )


def test_policy_scenario_sensor_flap_keeps_latch_and_activation_expires() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    office = event("office", NOW + timedelta(seconds=1))

    policy.apply(occupancy_filter.observe(office))
    assert policy.states["office"].keep_on
    assert policy.activation_plausible("office", NOW + timedelta(seconds=2))
    assert not policy.expire(NOW + timedelta(seconds=2))

    policy.apply(
        occupancy_filter.observe(
            replace(office, state="off", event_at=NOW + timedelta(seconds=3))
        )
    )
    assert policy.states["office"].keep_on
    assert policy.expire(NOW + timedelta(seconds=7))
    assert not policy.activation_plausible("office", NOW + timedelta(seconds=7))
    assert policy.states["office"].keep_on


def test_policy_provisionally_releases_stale_low_confidence_latch() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW if zone == "office" else None,
                reason="graph-supported local arrival"
                if zone == "office"
                else "no trusted occupancy",
            )
            for zone in graph.zones()
        }
    )

    assert not policy.expire(
        NOW + timedelta(minutes=14),
        {"office": 0.0862},
    )
    assert policy.states["office"].keep_on
    assert policy.expire(
        NOW + timedelta(minutes=50),
        {"office": 0.0862},
    )

    state = policy.states["office"]
    assert not state.keep_on
    assert state.last_release_cause == "provisional_false_off"
    assert state.recovery_eligible
    assert state.reason == "sustained low occupancy without active local evidence"
    decision = policy.policy_audit[-1]
    assert decision.source == "policy_expiry"
    assert decision.decision.reason_code == "provisional_false_off"
    assert decision.decision.gate_values == {
        "occupied_marginal": 0.0862,
        "occupied_threshold": 0.1,
        "seconds_since_trusted": 3000.0,
        "grace_seconds": 900.0,
        "active_positive_episode_count": 0.0,
    }


def test_policy_provisional_release_requires_low_confidence_and_no_local_evidence() -> (
    None
):
    predictive_map = make_map()
    graph = ZoneGraph.from_map(predictive_map)
    high_confidence = AutomationPolicy(graph)
    high_confidence.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW if zone == "office" else None,
            )
            for zone in graph.zones()
        }
    )

    assert not high_confidence.expire(
        NOW + timedelta(minutes=50),
        {"office": 0.1001},
    )
    assert high_confidence.states["office"].keep_on

    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    active_evidence = AutomationPolicy(graph)
    active_evidence.apply(
        occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    )

    assert active_evidence.expire(
        NOW + timedelta(minutes=50),
        {"office": 0.01},
        {
            "office": (
                PositiveEvidence(
                    "binary_sensor.office_presence",
                    "office-presence-episode",
                    NOW + timedelta(minutes=49),
                    "presence",
                ),
            )
        },
    )
    assert active_evidence.states["office"].keep_on


def test_policy_observation_releases_other_stale_low_confidence_zone() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW - timedelta(minutes=20)
                if zone == "office"
                else None,
            )
            for zone in graph.zones()
        }
    )

    policy.apply(
        make_update(
            previous={"office": 0.08, "hall": 0.92},
            current={"office": 0.05, "hall": 0.95},
            movement={},
            event_id="hall-motion",
            zone="hall",
        )
    )

    assert not policy.states["office"].keep_on
    office_decision = next(
        decision
        for decision in policy.last_decisions
        if decision.zone == "office"
    )
    assert office_decision.reason_code == "provisional_false_off"


def test_policy_scenario_graph_departure_uses_coherent_multihop_evidence() -> None:
    predictive_map = make_map()
    graph = ZoneGraph.from_map(predictive_map)
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
    first = make_update(
        previous={"office": 0.9, "hall": 0.1},
        current={"office": 0.15, "hall": 0.85},
        movement={"office": ("hall", 0.70)},
        event_id="hall-edge",
        zone="hall",
    )
    second = make_update(
        previous={"office": 0.15, "hall": 0.85},
        current={"office": 0.05, "hall": 0.05, "kitchen": 0.9},
        movement={"hall": ("kitchen", 0.90)},
        event_id="kitchen-edge",
        zone="kitchen",
        movement_origins={"hall": "office"},
    )

    policy.apply(first)
    assert policy.states["office"].keep_on
    policy.apply(second)

    assert not policy.states["office"].keep_on
    assert policy.states["office"].reason == "graph-valid final occupant departure"
    assert policy.pending_departures == {}


def test_policy_audit_records_count_release_with_before_and_after_state() -> None:
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

    policy.reconcile_count(0, NOW, "everyone_away")

    office_entry = next(
        entry for entry in policy.policy_audit if entry.decision.zone == "office"
    )
    assert office_entry.decision_at == NOW
    assert office_entry.source == "occupant_count"
    assert office_entry.trigger_event_id == "everyone_away"
    assert office_entry.trigger_entity_id is None
    assert office_entry.decision.reason_code == "authoritative_away"
    assert office_entry.previous_keep_on
    assert not office_entry.current_keep_on
    assert office_entry.current_release_cause == "authoritative_away"


def test_policy_expiry_prunes_audit_entries_older_than_two_days() -> None:
    policy = AutomationPolicy(ZoneGraph.from_map(make_map()))

    policy.reconcile_count(0, NOW - timedelta(days=2, seconds=1), "old-away")

    assert policy.expire(NOW)
    assert policy.policy_audit == ()


def test_policy_scenario_false_positive_requires_independent_corroboration() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    unsupported = make_update(
        previous={"office": 0.95, "garage": 0.05},
        current={"office": 0.35, "garage": 0.65},
        movement={},
        event_id="garage-one",
        zone="garage",
        entity_id="binary_sensor.garage_one",
        positive_entities=("binary_sensor.garage_one",),
    )
    corroborated = make_update(
        previous={"office": 0.35, "garage": 0.65},
        current={"office": 0.05, "garage": 0.95},
        movement={},
        event_id="garage-two",
        zone="garage",
        entity_id="binary_sensor.garage_two",
        positive_entities=(
            "binary_sensor.garage_one",
            "binary_sensor.garage_two",
        ),
    )

    policy.apply(unsupported)
    assert not policy.states["garage"].keep_on
    policy.apply(corroborated)
    assert policy.states["garage"].keep_on
    assert policy.states["garage"].reason == (
        "independent local sensors corroborated occupancy"
    )


def test_policy_accepts_supported_adjacent_arrival_and_audits_context() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    update = make_update(
        previous={"hall": 0.95, "office": 0.05},
        current={"hall": 0.3638, "office": 0.6362},
        movement={"hall": ("office", 0.4348)},
        event_id="office-entrance-motion",
        zone="office",
        entity_id="binary_sensor.office_entrance_motion",
        positive_entities=("binary_sensor.office_entrance_motion",),
    )

    policy.apply(update)

    assert policy.states["office"].keep_on
    assert policy.activation_plausible("office", update.current.updated_at)
    activation = next(
        entry
        for entry in policy.policy_audit
        if entry.decision.zone == "office" and entry.decision.action == "activate"
    )
    assert activation.decision.reason_code == "graph_supported_arrival"
    assert activation.decision.gate_values["movement_threshold"] == 0.4
    assert activation.context is not None
    assert activation.context.previous_occupied_marginals == pytest.approx(
        {"garage": 0.0, "hall": 0.95, "kitchen": 0.0, "office": 0.05}
    )
    assert activation.context.occupied_marginals == update.occupied_marginals
    assert activation.context.count_marginals == update.count_marginals
    assert activation.context.movement_evidence == update.movement_evidence


def test_policy_does_not_reuse_stale_corroboration_after_release() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    first_session = make_update(
        previous={"office": 0.95, "garage": 0.05},
        current={"office": 0.05, "garage": 0.95},
        movement={},
        event_id="garage-session-one",
        zone="garage",
        positive_entities=("binary_sensor.garage_one", "binary_sensor.garage_two"),
    )
    policy.apply(first_session)
    policy.reconcile_count(
        1,
        NOW,
        "count-reduction",
        {"office": 0.9, "garage": 0.1, "hall": 0.0, "kitchen": 0.0},
    )

    second_session = make_update(
        previous={"office": 0.7, "garage": 0.1},
        current={"office": 0.15, "garage": 0.85},
        movement={},
        event_id="garage-session-two",
        zone="garage",
        positive_entities=("binary_sensor.garage_one",),
    )
    policy.apply(second_session)

    assert not policy.states["garage"].keep_on


def test_policy_scenario_relocation_recovery_count_zero_and_reset() -> None:
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
    relocation = make_update(
        previous={"office": 0.95, "garage": 0.05},
        current={"office": 0.05, "garage": 0.95},
        movement={"office": ("garage", 0.9)},
        event_id="relocation",
        zone="garage",
    )
    policy.apply(relocation)
    assert policy.states["office"].reason == "confident non-adjacent relocation"

    recovery = make_update(
        previous={"office": 0.05},
        current={"office": 0.9},
        movement={},
        event_id="recovery",
        zone="office",
    )
    policy.apply(recovery)
    assert policy.states["office"].keep_on
    assert policy.states["office"].reason == "trusted local occupancy established"
    assert not policy.states["office"].recovery_eligible

    policy.reconcile_count(1, NOW, "count-one")
    assert policy.states["office"].keep_on
    policy.reconcile_count(0, NOW, "count-zero")
    assert all(not state.keep_on for state in policy.states.values())
    policy.reset(NOW, "manual-reset")
    assert all(state.reason == "explicit reset" for state in policy.states.values())
    with pytest.raises(ValueError, match="non-negative"):
        policy.reconcile_count(-1, NOW, "bad")


def test_policy_scenario_count_reduction_keeps_strongest_latched_zone() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone in {"kitchen", "office"},
                activation_expires_at=NOW + timedelta(seconds=5)
                if zone in {"kitchen", "office"}
                else None,
                last_trusted_at=NOW if zone in {"kitchen", "office"} else None,
            )
            for zone in graph.zones()
        }
    )

    policy.reconcile_count(
        1,
        NOW + timedelta(seconds=1),
        "count-two-to-one",
        {"office": 0.9, "kitchen": 0.2, "hall": 0.0, "garage": 0.0},
    )

    assert policy.states["office"].keep_on
    assert not policy.states["kitchen"].keep_on
    assert policy.states["kitchen"].activation_expires_at is None
    assert policy.states["kitchen"].reason == "authoritative occupant count reduction"
    assert policy.states["kitchen"].evidence_ids == ("count-two-to-one",)


def test_policy_count_reduction_does_not_enable_recovery_bypass() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone in {"kitchen", "office"},
                last_trusted_at=NOW if zone in {"kitchen", "office"} else None,
            )
            for zone in graph.zones()
        }
    )
    policy.reconcile_count(
        1,
        NOW,
        "count-reduction",
        {"office": 0.9, "kitchen": 0.1, "hall": 0.0, "garage": 0.0},
    )

    policy.apply(
        make_update(
            previous={"office": 0.7, "kitchen": 0.1},
            current={"office": 0.15, "kitchen": 0.85},
            movement={},
            event_id="unsupported-kitchen-hit",
            zone="kitchen",
        )
    )

    assert not policy.states["kitchen"].keep_on
    assert policy.states["kitchen"].last_release_cause == "count_reduction"


def test_policy_does_not_release_from_aggregate_movement_without_path_evidence() -> (
    None
):
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(keep_on=zone == "office", last_trusted_at=NOW)
            for zone in graph.zones()
        }
    )
    aggregate_only = make_update(
        previous={"office": 0.95, "hall": 0.05},
        current={"office": 0.05, "hall": 0.95},
        movement={"office": ("hall", 0.95)},
        event_id="aggregate-only",
        zone="hall",
        include_movement_evidence=False,
    )

    policy.apply(aggregate_only)

    assert policy.states["office"].keep_on
    assert policy.pending_departures == {}


def test_policy_ignores_non_evidence_and_validates_restore_zones() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    ignored = make_update(
        previous={},
        current={},
        movement={},
        event_id="ignored",
        zone="office",
        disposition="duplicate",
    )
    assert policy.apply(ignored) == policy.states
    assert not policy.activation_plausible("missing", NOW)

    low_confidence = make_update(
        previous={},
        current={"office": 0.1},
        movement={},
        event_id="low-confidence",
        zone="office",
    )
    policy.apply(low_confidence)
    assert not policy.states["office"].keep_on

    zero_movement = make_update(
        previous={},
        current={},
        movement={"kitchen": ("hall", 0.0)},
        event_id="zero-movement",
        zone="hall",
    )
    policy.apply(zero_movement)
    first_path = make_update(
        previous={"office": 0.5},
        current={"hall": 0.5},
        movement={"office": ("hall", 0.4)},
        event_id="first-path",
        zone="hall",
    )
    unrelated_path = make_update(
        previous={"garage": 0.5},
        current={"kitchen": 0.5},
        movement={"garage": ("kitchen", 0.4)},
        event_id="unrelated-path",
        zone="kitchen",
    )
    repeated_source = make_update(
        previous={"office": 0.5},
        current={"hall": 0.5},
        movement={"office": ("hall", 0.4)},
        event_id="repeated-source",
        zone="hall",
    )
    policy.apply(first_path)
    policy.apply(unrelated_path)
    policy.apply(repeated_source)
    assert set(policy.pending_departures) == {"garage", "office"}

    with pytest.raises(ValueError, match="do not match"):
        policy.restore_states({})


def test_policy_suppression_and_pending_departure_validation() -> None:
    policy = AutomationPolicy(ZoneGraph.from_map(make_map()))
    assert not policy.suppress_activation("missing", "runtime_limit")
    assert not policy.suppress_activation("office", "runtime_limit")
    with pytest.raises(ValueError, match="pending departure"):
        policy.restore_pending_departures(
            {
                "office": PendingDeparture(
                    "office",
                    "hall",
                    0.5,
                    False,
                    (),
                    "invalid",
                )
            }
        )


def make_update(
    *,
    previous: dict[str, float],
    current: dict[str, float],
    movement: dict[str, tuple[str, float]],
    event_id: str,
    zone: str,
    entity_id: str | None = None,
    disposition: str = "accepted",
    positive_entities: tuple[str, ...] = (),
    include_movement_evidence: bool = True,
    movement_origins: dict[str, str] | None = None,
) -> FilterUpdate:
    zones = make_map().zones()
    previous_posterior = posterior_for_marginals(previous, zones, NOW)
    current_posterior = posterior_for_marginals(
        current,
        zones,
        NOW + timedelta(seconds=1),
    )
    occupied, counts = zone_marginals(current_posterior, zones)
    return FilterUpdate(
        previous=previous_posterior,
        current=current_posterior,
        occupied_marginals=occupied,
        count_marginals=counts,
        movement_mass={
            (source, target): probability
            for source, (target, probability) in movement.items()
        },
        active_positive_entities={zone: positive_entities},
        movement_evidence=(
            tuple(
                MovementEvidence(
                    path_key=(
                        (movement_origins or {}).get(source, source),
                        source,
                        target,
                    ),
                    origin_zone=(movement_origins or {}).get(source, source),
                    source_zone=source,
                    target_zone=target,
                    coherent_probability=probability,
                    source_node_id=source,
                    target_node_id=target,
                    evidence_ids=(event_id,),
                    disposition=(
                        "graph_valid"
                        if target in ZoneGraph.from_map(make_map()).neighbors(source)
                        else "missed_movement"
                    ),
                )
                for source, (target, probability) in movement.items()
            )
            if include_movement_evidence
            else ()
        ),
        provenance=ObservationProvenance(
            event_id=event_id,
            evidence_episode_id=event_id,
            entity_id=entity_id or f"binary_sensor.{zone}",
            node_id=zone,
            zone=zone,
            state="on",
            signal_type="motion",
            reliability=1.0,
            log_likelihood_by_count=(0.0, 0.0),
            disposition=disposition,
        ),
    )


def posterior_for_marginals(
    marginals: dict[str, float],
    zones: tuple[str, ...],
    now: datetime,
) -> Posterior:
    weights = {
        canonical_hypothesis((PositionState(zone),)): probability
        for zone in zones
        if (probability := marginals.get(zone, 0.0)) > 0.0
    }
    remaining = max(0.0, 1.0 - sum(weights.values()))
    if remaining:
        weights[canonical_hypothesis((PositionState(None),))] = remaining
    return normalize_hypotheses(
        {key: math.log(value) for key, value in weights.items()},
        now,
    )
