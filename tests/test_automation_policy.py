from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.automation_policy import (
    POLICY_AUDIT_MAX_ENTRIES,
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
    ReleaseCause,
    ZonePolicyState,
    canonical_hypothesis,
    competing_current_update_source_nodes,
    normalize_hypotheses,
    zone_marginals,
)
from custom_components.predictive_controls.policy_audit import (
    policy_audit_context_payload,
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


def test_policy_elapsed_time_and_low_confidence_do_not_release_latch() -> None:
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
    assert not policy.expire(
        NOW + timedelta(minutes=50),
        {"office": 0.0862},
    )

    state = policy.states["office"]
    assert state.keep_on
    assert state.last_release_cause is None
    assert not state.recovery_eligible


def test_policy_silence_and_low_confidence_preserve_latch_with_local_evidence() -> (
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


def test_policy_unrelated_observation_preserves_stale_low_confidence_zone() -> None:
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

    assert policy.states["office"].keep_on
    assert not any(
        decision.zone == "office" and decision.action == "release"
        for decision in policy.last_decisions
    )


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


def test_policy_releases_immediate_segment_across_ambiguous_route_origins() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "kitchen",
                last_trusted_at=NOW if zone == "kitchen" else None,
            )
            for zone in graph.zones()
        }
    )
    update = make_update(
        previous={"kitchen": 0.9768120157474351},
        current={"kitchen": 0.13604044324814651, "hall": 0.892307709342551},
        movement={},
        event_id="hall@2026-07-13T19:46:09.704142-04:00",
        zone="hall",
    )
    alternatives = (
        ("office", "kitchen", 0.26560508798058513),
        ("hall", "kitchen", 0.15550854013610185),
        ("kitchen", "kitchen", 0.3965465521546088),
        ("office", "office", 0.0071718640178732),
    )
    update = replace(
        update,
        previous_occupied_marginals={"kitchen": 0.9768120157474351},
        occupied_marginals={
            "kitchen": 0.13604044324814651,
            "hall": 0.892307709342551,
        },
        movement_evidence=tuple(
            MovementEvidence(
                path_key=(origin, source, "hall"),
                origin_zone=origin,
                source_zone=source,
                target_zone="hall",
                coherent_probability=probability,
                source_node_id=source,
                target_node_id="hall",
                evidence_ids=(update.provenance.event_id,),
                disposition="graph_valid",
            )
            for origin, source, probability in alternatives
        ),
    )

    policy.apply(update)

    assert not policy.states["kitchen"].keep_on
    decision = next(
        decision
        for decision in policy.last_decisions
        if decision.zone == "kitchen" and decision.action == "release"
    )
    assert decision.accepted
    assert decision.gate_values["segment_probability"] == pytest.approx(
        0.8176601802712958
    )
    assert decision.gate_values["coherent_probability"] == pytest.approx(
        0.9913050613545762
    )
    assert decision.gate_values["origin_decrease"] == pytest.approx(
        0.8407715724992886
    )


def test_policy_asserted_office_survives_other_occupant_hallway_route() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    office_detected_at = datetime.fromisoformat(
        "2026-07-14T18:19:28.191772-04:00"
    )
    hallway_detected_at = datetime.fromisoformat(
        "2026-07-14T18:25:24.760937-04:00"
    )
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=office_detected_at if zone == "office" else None,
                reason=(
                    "graph-supported local arrival"
                    if zone == "office"
                    else "no trusted occupancy"
                ),
            )
            for zone in graph.zones()
        }
    )
    update = make_update(
        previous={"office": 0.9834496225277384, "hall": 0.06702069063261329},
        current={"office": 0.14857533676907292, "hall": 0.9329793093673867},
        movement={"office": ("hall", 0.927880457512608)},
        event_id=(
            "binary_sensor.hall@"
            "2026-07-14T18:25:24.760937-04:00:on"
        ),
        zone="hall",
    )
    update = replace(
        update,
        previous_occupied_marginals={"office": 0.9834496225277384},
        occupied_marginals={
            "office": 0.14857533676907292,
            "hall": 0.9329793093673867,
        },
        active_positive_entities={"kitchen": ("binary_sensor.kitchen",)},
        active_positive_evidence={
            "kitchen": (
                PositiveEvidence(
                    entity_id="binary_sensor.kitchen",
                    evidence_episode_id=(
                        "binary_sensor.kitchen@"
                        "2026-07-14T18:14:30.934769-04:00"
                    ),
                    changed_at=datetime.fromisoformat(
                        "2026-07-14T18:25:21.820608-04:00"
                    ),
                    signal_type="motion",
                ),
            )
        },
        movement_evidence=(
            MovementEvidence(
                path_key=("office", "office", "hall"),
                origin_zone="office",
                source_zone="office",
                target_zone="hall",
                coherent_probability=0.927880457512608,
                source_node_id="office",
                target_node_id="hall",
                evidence_ids=(
                    "binary_sensor.office@"
                    "2026-07-14T18:19:28.191772-04:00:on",
                    "binary_sensor.hall@"
                    "2026-07-14T18:25:24.760937-04:00:on",
                ),
                disposition="graph_valid",
            ),
            MovementEvidence(
                path_key=("kitchen", "kitchen", "hall"),
                origin_zone="kitchen",
                source_zone="kitchen",
                target_zone="hall",
                coherent_probability=0.071855459827822,
                source_node_id="kitchen",
                target_node_id="hall",
                evidence_ids=(
                    "binary_sensor.kitchen@"
                    "2026-07-14T18:25:21.820608-04:00:on",
                    "binary_sensor.hall@"
                    "2026-07-14T18:25:24.760937-04:00:on",
                ),
                disposition="graph_valid",
            ),
        ),
    )

    policy.apply(update)

    assert hallway_detected_at - office_detected_at == timedelta(
        minutes=5,
        seconds=56,
        microseconds=569165,
    )
    assert policy.states["office"].keep_on
    assert policy.states["office"].last_release_cause is None
    decision = next(
        decision
        for decision in policy.last_decisions
        if decision.zone == "office" and decision.action == "release"
    )
    assert not decision.accepted
    assert decision.reason_code == "competing_source_gate_failed"
    assert decision.gate_values["origin_asserted"] is False
    assert decision.gate_values["competing_source_present"] is True
    assert decision.gate_values["competing_source_nodes"] == "binary_sensor.kitchen"


def test_policy_graph_departure_overrides_asserted_origin_when_confirmed() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(keep_on=zone == "office")
            for zone in graph.zones()
        }
    )
    update = make_update(
        previous={"office": 0.95, "hall": 0.05},
        current={"office": 0.04, "hall": 0.96},
        movement={"office": ("hall", 0.95)},
        event_id="hall-edge",
        zone="hall",
    )
    update = replace(
        update,
        active_positive_entities={"office": ("binary_sensor.office",)},
        active_positive_evidence={
            "office": (
                PositiveEvidence(
                    "binary_sensor.office",
                    "office-episode",
                    NOW,
                    "motion",
                    "office",
                ),
            )
        },
    )

    policy.apply(update)

    assert not policy.states["office"].keep_on
    decision = next(
        decision
        for decision in policy.last_decisions
        if decision.zone == "office" and decision.action == "release"
    )
    assert decision.accepted
    assert decision.reason_code == "graph_departure"
    assert decision.gate_values["origin_asserted"] is True
    assert decision.gate_values["competing_source_present"] is False


def test_competing_source_requires_current_graph_valid_active_edge() -> None:
    target_event_id = "binary_sensor.hall@2026-07-14T18:25:24+00:00:on"
    source_changed_at = datetime.fromisoformat("2026-07-14T18:25:21+00:00")
    source_edge_id = (
        f"binary_sensor.kitchen@{source_changed_at.isoformat()}:on"
    )
    evidence = MovementEvidence(
        path_key=("kitchen", "kitchen", "hall"),
        origin_zone="kitchen",
        source_zone="kitchen",
        target_zone="hall",
        coherent_probability=0.1,
        source_node_id="kitchen",
        target_node_id="hall",
        evidence_ids=(source_edge_id, target_event_id),
        disposition="graph_valid",
    )
    positive = PositiveEvidence(
        "binary_sensor.kitchen",
        "kitchen-episode",
        source_changed_at,
        "motion",
        "kitchen",
    )

    def competing(
        candidate: MovementEvidence,
        active: dict[str, tuple[PositiveEvidence, ...]] | None = None,
    ) -> tuple[str, ...]:
        return competing_current_update_source_nodes(
            (candidate,),
            {"kitchen": (positive,)} if active is None else active,
            origin_source_zone="office",
            target_zone="hall",
            target_node_id="hall",
            target_event_id=target_event_id,
        )

    assert competing(evidence) == ("kitchen",)
    assert competing(
        evidence,
        {"kitchen": (replace(positive, node_id=None),)},
    ) == ("binary_sensor.kitchen",)
    assert competing(replace(evidence, disposition="missed_movement")) == ()
    assert competing(replace(evidence, source_zone="office")) == ()
    assert competing(replace(evidence, target_zone="garage")) == ()
    assert competing(replace(evidence, target_node_id="other_hall")) == ()
    assert competing(replace(evidence, evidence_ids=(source_edge_id,))) == ()
    assert competing(evidence, {}) == ()
    assert competing(
        evidence,
        {
            "kitchen": (
                replace(
                    positive,
                    changed_at=source_changed_at - timedelta(seconds=1),
                ),
            )
        },
    ) == ()
    assert competing(
        evidence,
        {"kitchen": (replace(positive, node_id="other_kitchen"),)},
    ) == ()


@pytest.mark.parametrize(
    ("previous_origin", "current_origin", "destination", "segment", "competing"),
    (
        (0.95, 0.25, 0.90, 0.90, 0.05),
        (0.95, 0.10, 0.55, 0.90, 0.05),
        (0.30, 0.15, 0.90, 0.90, 0.05),
        (0.95, 0.10, 0.90, 0.84, 0.16),
        (0.95, 0.10, 0.90, 0.79, 0.01),
    ),
)
def test_policy_segment_departure_requires_every_release_gate(
    previous_origin: float,
    current_origin: float,
    destination: float,
    segment: float,
    competing: float,
) -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(keep_on=zone == "kitchen")
            for zone in graph.zones()
        }
    )
    update = make_update(
        previous={"kitchen": previous_origin},
        current={"kitchen": current_origin, "hall": destination},
        movement={},
        event_id="hall-edge",
        zone="hall",
    )
    update = replace(
        update,
        previous_occupied_marginals={"kitchen": previous_origin},
        occupied_marginals={"kitchen": current_origin, "hall": destination},
        movement_evidence=(
            MovementEvidence(
                ("office", "kitchen", "hall"),
                "office",
                "kitchen",
                "hall",
                segment,
                "kitchen",
                "hall",
                ("hall-edge",),
                "graph_valid",
            ),
            MovementEvidence(
                ("office", "office", "hall"),
                "office",
                "office",
                "hall",
                competing,
                "office",
                "hall",
                ("hall-edge",),
                "graph_valid",
            ),
        ),
    )

    policy.apply(update)

    assert policy.states["kitchen"].keep_on


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


def test_policy_expiry_prunes_audit_entries_older_than_twelve_hours() -> None:
    policy = AutomationPolicy(ZoneGraph.from_map(make_map()))

    policy.reconcile_count(0, NOW - timedelta(hours=12, seconds=1), "old-away")

    assert policy.expire(NOW)
    assert policy.policy_audit == ()


def test_policy_audit_entry_bound_discards_oldest_decisions() -> None:
    policy = AutomationPolicy(ZoneGraph.from_map(make_map()))
    decisions_per_update = len(make_map().zones())

    for index in range(POLICY_AUDIT_MAX_ENTRIES // decisions_per_update + 2):
        policy.reconcile_count(0, NOW, f"away-{index}")

    assert len(policy.policy_audit) == POLICY_AUDIT_MAX_ENTRIES
    assert policy.policy_audit[0].trigger_event_id != "away-0"


def test_policy_audit_compressed_context_bound_discards_oldest_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.predictive_controls.automation_policy."
        "POLICY_AUDIT_MAX_CONTEXT_BYTES",
        1,
    )
    predictive_map = make_map()
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)

    policy.apply(occupancy_filter.observe(event("office", NOW)))

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
        previous={"hall": 0.9493315610505566, "office": 0.0002950603962558},
        current={"hall": 0.1722022184984167, "office": 0.8277977815015833},
        movement={"hall": ("office", 0.2922710370286617)},
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
    assert activation.context is not None
    context = policy_audit_context_payload(activation.context)
    assert context is not None
    assert context["previous_occupied_marginals"] == pytest.approx(
        {
            "garage": 0.0,
            "hall": 0.9493315610505566,
            "kitchen": 0.0,
            "office": 0.0002950603962558,
        }
    )
    assert context["occupied_marginals"] == update.occupied_marginals
    count_marginals = cast(dict[str, object], context["count_marginals"])
    movement_evidence = cast(list[object], context["movement_evidence"])
    assert set(count_marginals) == set(update.count_marginals)
    assert len(movement_evidence) == len(update.movement_evidence)


def test_policy_recovers_provisional_release_after_supported_local_jump() -> None:
    graph = ZoneGraph.from_map(make_map())
    policy = AutomationPolicy(graph)
    policy.restore_states(
        {
            zone: ZonePolicyState(
                keep_on=False,
                last_trusted_at=NOW - timedelta(hours=1)
                if zone == "office"
                else None,
                last_release_cause=ReleaseCause.PROVISIONAL_FALSE_OFF
                if zone == "office"
                else None,
                recovery_eligible=zone == "office",
                reason="sustained low occupancy without active local evidence"
                if zone == "office"
                else "no trusted occupancy",
            )
            for zone in graph.zones()
        }
    )
    update = make_update(
        previous={
            "office": 0.000000062398192077,
            "hall": 0.0434218294512191,
            "kitchen": 0.6652335824047371,
            "garage": 0.2913445257458517,
        },
        current={
            "office": 0.4113746471684672,
            "hall": 0.027032041587682788,
            "kitchen": 0.4,
            "garage": 0.16159331124385,
        },
        movement={"hall": ("office", 0.03238892574420407)},
        event_id=(
            "binary_sensor.upstairs_bathroom_motion_motion_detection@"
            "2026-07-13T02:27:41.385185-04:00:on"
        ),
        zone="office",
        entity_id="binary_sensor.upstairs_bathroom_motion_motion_detection",
        positive_entities=(
            "binary_sensor.upstairs_bathroom_motion_motion_detection",
        ),
    )

    policy.apply(update)

    assert policy.states["office"].keep_on
    assert policy.activation_plausible("office", update.current.updated_at)
    activation = next(
        decision
        for decision in policy.last_decisions
        if decision.zone == "office" and decision.action == "activate"
    )
    assert activation.accepted
    assert activation.reason_code == "provisional_false_off_recovery"

    ordinary_policy = AutomationPolicy(graph)
    ordinary_policy.apply(update)
    ordinary_activation = next(
        decision
        for decision in ordinary_policy.last_decisions
        if decision.zone == "office" and decision.action == "activate"
    )
    assert not ordinary_policy.states["office"].keep_on
    assert not ordinary_activation.accepted
    assert ordinary_activation.reason_code == "occupied_gate_failed"
    assert ordinary_activation.gate_values["occupied_threshold"] == 0.6


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
        positive_evidence=(
            PositiveEvidence(
                "binary_sensor.garage_left",
                "garage-left-episode",
                NOW,
                "presence",
                "garage_left",
            ),
            PositiveEvidence(
                "binary_sensor.garage_right",
                "garage-right-episode",
                NOW,
                "presence",
                "garage_right",
            ),
        ),
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


def test_policy_pending_departure_validation() -> None:
    policy = AutomationPolicy(ZoneGraph.from_map(make_map()))
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
    positive_evidence: tuple[PositiveEvidence, ...] = (),
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
        active_positive_evidence={zone: positive_evidence},
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



