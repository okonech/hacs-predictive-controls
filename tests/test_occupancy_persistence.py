from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

import custom_components.predictive_controls.occupancy_persistence as persistence_module
from custom_components.predictive_controls.automation_policy import (
    AutomationPolicy,
    PendingDeparture,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import (
    SUSTAINED_DURATION_MAX_LOG_ODDS,
    JointOccupancyFilter,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.observation_model import EntityEvidence
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_persistence import (
    _restore_consumed_censored_paths,
    _restore_policy_audit,
    _restore_route_contexts,
    _restore_route_counts,
    map_fingerprint,
    restore_occupancy_state,
    serialize_occupancy_state,
)
from custom_components.predictive_controls.occupancy_state import (
    PolicyAuditEntry,
    PolicyDecision,
    PredictionLease,
    ReleaseCause,
)
from custom_components.predictive_controls.policy_audit import (
    policy_audit_context_payload,
)
from custom_components.predictive_controls.prediction import PredictionManager

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_map(include_office: bool = True) -> PredictiveMap:
    nodes = {
        "hall": {
            "zone": "hall",
            "entities": {"motion": "binary_sensor.hall"},
            "adjacent": ["kitchen"],
        },
        "kitchen": {
            "zone": "kitchen",
            "entities": {"motion": "binary_sensor.kitchen"},
            "adjacent": ["hall"],
        },
    }
    if include_office:
        nodes["office"] = {
            "zone": "office",
            "entities": {"motion": "binary_sensor.office"},
            "adjacent": ["hall"],
        }
        nodes["hall"]["adjacent"] = ["office", "kitchen"]
    return PredictiveMap.from_mapping({"nodes": nodes})


def event(zone: str, at: datetime) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor=None,
        role="room_occupancy",
        occupancy_behavior="sustained",
        signal_type="motion",
        state="on",
        event_at=at,
        reliability=0.9,
    )


def policy_audit_entry(decision_at: datetime) -> PolicyAuditEntry:
    return PolicyAuditEntry(
        decision_at=decision_at,
        source="observation",
        trigger_event_id="office-motion",
        trigger_entity_id="binary_sensor.office",
        trigger_zone="office",
        trigger_state="on",
        trigger_disposition="accepted",
        decision=PolicyDecision(
            zone="office",
            action="release",
            accepted=True,
            reason_code="graph_departure",
            gate_values={"origin_marginal": 0.05},
            evidence_ids=("office-hall",),
        ),
        previous_keep_on=True,
        current_keep_on=False,
        previous_reason="trusted local occupancy established",
        current_reason="graph-valid final occupant departure",
        previous_release_cause=None,
        current_release_cause=ReleaseCause.GRAPH_DEPARTURE,
    )


@pytest.mark.scenario
def test_restart_scenario_round_trips_complete_inference_state() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    predictions = PredictionManager(predictive_map)
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    occupancy_filter.reinforce_asserted_evidence(NOW + timedelta(minutes=1))
    movement_update = occupancy_filter.observe(
        event("hall", NOW + timedelta(minutes=1, seconds=1))
    )
    policy.apply(movement_update)
    assert occupancy_filter.reinforce_asserted_evidence(
        NOW + timedelta(minutes=1, seconds=1)
    )
    office_state = policy.states["office"]
    policy.restore_states(
        {
            **policy.states,
            "office": replace(
                office_state,
                keep_on=False,
                last_release_cause=ReleaseCause.PROVISIONAL_FALSE_OFF,
                recovery_eligible=True,
                reason="provisional false-off",
            ),
        }
    )
    predictions.restore_leases(
        (
            PredictionLease(
                ("hall", "office", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(minutes=1),
                "test lease",
            ),
        ),
        NOW,
    )
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        predictions.leases,
        occupancy_filter.observations.entity_states,
        {"office": {"hall": 2.5}},
        directional_contexts=occupancy_filter.directional_contexts,
        pending_departures=policy.pending_departures,
        update_sequence=occupancy_filter.update_sequence,
        route_counts={
            ("office", "hall"): {"kitchen": 3.5},
        },
        route_contexts=(("office", "hall"),),
        consumed_censored_paths=(("binary_sensor.hall@gate", "office@source"),),
    )

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert [item.key for item in restored.posterior.hypotheses] == [
        item.key for item in occupancy_filter.posterior.hypotheses
    ]
    assert [item.log_probability for item in restored.posterior.hypotheses] == (
        pytest.approx(
            [item.log_probability for item in occupancy_filter.posterior.hypotheses]
        )
    )
    assert restored.policy_states == policy.states
    assert restored.pending_departures == policy.pending_departures
    assert set(restored.directional_contexts) == set(
        occupancy_filter.directional_contexts
    )
    for key, contexts in restored.directional_contexts.items():
        expected = occupancy_filter.directional_contexts[key]
        assert [replace(context, log_probability=0.0) for context in contexts] == [
            replace(context, log_probability=0.0) for context in expected
        ]
        assert [context.log_probability for context in contexts] == pytest.approx(
            [context.log_probability for context in expected]
        )
    assert restored.prediction_leases == predictions.leases
    assert restored.entity_states == occupancy_filter.observations.entity_states
    assert not occupancy_filter.reinforce_asserted_evidence(
        NOW + timedelta(minutes=1, seconds=1)
    )
    assert restored.transition_counts == {"office": {"hall": 2.5}}
    assert restored.route_counts == {
        ("office", "hall"): {"kitchen": 3.5},
    }
    assert restored.route_contexts == (("office", "hall"),)
    assert restored.consumed_censored_paths == (
        ("binary_sensor.hall@gate", "office@source"),
    )
    assert restored.map_compatible
    assert restored.restore_status == "restored"
    assert restored.update_sequence == 2
    assert payload["map_fingerprint"] == map_fingerprint(predictive_map)


def test_duration_evidence_above_legacy_ceiling_round_trips() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        AutomationPolicy(ZoneGraph.from_map(predictive_map)).states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        directional_contexts=occupancy_filter.directional_contexts,
        update_sequence=occupancy_filter.update_sequence,
    )
    entity_states = payload["entity_states"]
    assert isinstance(entity_states, dict)
    office = entity_states["binary_sensor.office"]
    assert isinstance(office, dict)
    office["duration_log_odds"] = SUSTAINED_DURATION_MAX_LOG_ODDS

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.entity_states[
        "binary_sensor.office"
    ].duration_log_odds == pytest.approx(SUSTAINED_DURATION_MAX_LOG_ODDS)


def test_schema_four_restores_with_empty_censored_consumption_state() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        AutomationPolicy(ZoneGraph.from_map(predictive_map)).states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        directional_contexts=occupancy_filter.directional_contexts,
    )
    payload["schema_version"] = 4
    payload.pop("consumed_censored_paths")

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.map_compatible
    assert restored.consumed_censored_paths == ()


@pytest.mark.parametrize(
    "raw",
    ({}, ["not-a-list"], [["only-one"]], [["", "source"]]),
)
def test_consumed_censored_path_restore_rejects_malformed_values(
    raw: object,
) -> None:
    with pytest.raises(ValueError, match="consumed censored path"):
        _restore_consumed_censored_paths(raw)


def test_route_storage_defaults_filters_and_rejects_malformed_values() -> None:
    predictive_map = make_map()
    assert _restore_route_counts(None, predictive_map) == {}
    assert _restore_route_contexts(None, predictive_map) == ()

    with pytest.raises(ValueError, match="counts must be a list"):
        _restore_route_counts({}, predictive_map)
    with pytest.raises(ValueError, match="entry must be a mapping"):
        _restore_route_counts(["bad"], predictive_map)
    with pytest.raises(ValueError, match="entry is invalid"):
        _restore_route_counts([{"prefix": "office", "targets": {}}], predictive_map)
    assert _restore_route_counts(
        [{"prefix": ["office", "kitchen"], "targets": {"hall": 1.0}}],
        predictive_map,
    ) == {}
    assert _restore_route_counts(
        [{"prefix": ["office", "hall"], "targets": {"missing": 1.0}}],
        predictive_map,
    ) == {}
    invalid_targets = (
        (3, 1.0),
        ("kitchen", "bad"),
        ("kitchen", math.nan),
        ("kitchen", 0.0),
    )
    for target, value in invalid_targets:
        with pytest.raises(ValueError, match="route count is invalid"):
            _restore_route_counts(
                [{"prefix": ["office", "hall"], "targets": {target: value}}],
                predictive_map,
            )

    with pytest.raises(ValueError, match="contexts are invalid"):
        _restore_route_contexts({}, predictive_map)
    with pytest.raises(ValueError, match="contexts are invalid"):
        _restore_route_contexts([[], [], [], [], []], predictive_map)
    with pytest.raises(ValueError, match="context is invalid"):
        _restore_route_contexts(["bad"], predictive_map)
    assert _restore_route_contexts(
        [["office", "kitchen"]],
        predictive_map,
    ) == ()
    assert _restore_route_contexts(
        [["office", "hall"], ["office", "hall"]],
        predictive_map,
    ) == (("office", "hall"),)


def test_restart_retains_only_last_twelve_hours_of_policy_audit() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        policy_audit=(
            policy_audit_entry(NOW - timedelta(hours=12, seconds=1)),
            policy_audit_entry(NOW - timedelta(hours=12)),
            policy_audit_entry(NOW - timedelta(minutes=1)),
        ),
    )

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert [entry.decision_at for entry in restored.policy_audit] == [
        NOW - timedelta(hours=12),
        NOW - timedelta(minutes=1),
    ]
    assert restored.policy_audit[-1].decision.evidence_ids == ("office-hall",)


def test_policy_audit_restore_applies_hard_entry_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(persistence_module, "POLICY_AUDIT_MAX_ENTRIES", 1)
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        AutomationPolicy(ZoneGraph.from_map(predictive_map)).states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        policy_audit=(
            policy_audit_entry(NOW - timedelta(minutes=1)),
            policy_audit_entry(NOW),
        ),
    )

    restored = _restore_policy_audit(
        payload["policy_audit"],
        set(predictive_map.zones()),
        NOW,
    )

    assert len(restored) == 1
    assert restored[0].decision_at == NOW


def test_policy_audit_round_trips_observation_context() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    policy.apply(occupancy_filter.observe(event("office", NOW + timedelta(seconds=1))))
    expected = next(entry for entry in policy.policy_audit if entry.context is not None)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        policy_audit=policy.policy_audit,
    )

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    actual = next(entry for entry in restored.policy_audit if entry.context is not None)
    assert actual.context == expected.context

    raw_audit = cast(list[dict[str, object]], payload["policy_audit"])
    stored_context = next(
        cast(dict[str, object], entry["context"])
        for entry in raw_audit
        if entry.get("context") is not None
    )
    assert stored_context["encoding"] == "zlib-json-v1"
    expanded_size = len(
        json.dumps(
            policy_audit_context_payload(expected.context),
            separators=(",", ":"),
        )
    )
    assert len(json.dumps(stored_context, separators=(",", ":"))) < (
        expanded_size * 2 / 3
    )
    for entry in raw_audit:
        entry.pop("context")
    legacy = _restore_policy_audit(raw_audit, set(predictive_map.zones()), NOW)
    assert all(entry.context is None for entry in legacy)


def test_policy_audit_restore_rejects_non_list_and_non_mapping_entries() -> None:
    valid_zones = set(make_map().zones())

    with pytest.raises(ValueError, match="must be a list"):
        _restore_policy_audit({}, valid_zones, NOW)
    with pytest.raises(ValueError, match="must be a mapping"):
        _restore_policy_audit(["bad"], valid_zones, NOW)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda entry: entry.update(source=""), "trigger"),
        (lambda entry: entry.update(decision=[]), "decision must be a mapping"),
        (
            lambda entry: cast(dict[str, object], entry["decision"]).update(
                zone="attic"
            ),
            "decision is invalid",
        ),
        (
            lambda entry: cast(dict[str, object], entry["decision"]).update(
                gate_values=[]
            ),
            "gates must be a mapping",
        ),
        (
            lambda entry: cast(dict[str, object], entry["decision"]).update(
                gate_values={3: 0.5}
            ),
            "gate key is invalid",
        ),
        (
            lambda entry: cast(dict[str, object], entry["decision"]).update(
                gate_values={"bad": math.nan}
            ),
            "gate value is invalid",
        ),
        (lambda entry: entry.update(previous=[]), "state must be a mapping"),
        (
            lambda entry: cast(dict[str, object], entry["previous"]).update(
                keep_on="yes"
            ),
            "state is invalid",
        ),
        (
            lambda entry: cast(dict[str, object], entry["current"]).update(
                release_cause=3
            ),
            "release cause is invalid",
        ),
        (
            lambda entry: cast(dict[str, object], entry["current"]).update(
                release_cause="not-a-cause"
            ),
            "release cause is invalid",
        ),
        (lambda entry: entry.update(context=[]), "context must be a mapping"),
    ),
)
def test_policy_audit_restore_rejects_corrupt_entry(
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        policy_audit=(policy_audit_entry(NOW),),
    )
    raw_entry = cast(list[dict[str, object]], payload["policy_audit"])[0]
    mutate(raw_entry)

    with pytest.raises(ValueError, match=message):
        _restore_policy_audit([raw_entry], set(predictive_map.zones()), NOW)


def _contextual_policy_audit_entry() -> tuple[dict[str, object], set[str]]:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    policy.apply(occupancy_filter.observe(event("office", NOW + timedelta(seconds=1))))
    policy.apply(occupancy_filter.observe(event("hall", NOW + timedelta(seconds=2))))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
        policy_audit=policy.policy_audit,
    )
    raw_audit = cast(list[dict[str, object]], payload["policy_audit"])
    for entry, audit_entry in zip(raw_audit, policy.policy_audit, strict=True):
        context = policy_audit_context_payload(audit_entry.context)
        if context is not None and context["movement_evidence"]:
            entry["context"] = context
            return entry, set(predictive_map.zones())
    raise AssertionError("test fixture did not produce movement evidence")


def test_policy_audit_restore_accepts_valid_movement_evidence() -> None:
    raw_entry, valid_zones = _contextual_policy_audit_entry()

    restored = _restore_policy_audit([raw_entry], valid_zones, NOW)

    assert restored[0].context is not None


def _replace_nested(
    payload: dict[str, object],
    path: tuple[str | int, ...],
    value: object,
) -> None:
    target: object = payload
    for key in path[:-1]:
        if isinstance(key, int):
            target = cast(list[object], target)[key]
        else:
            target = cast(dict[str, object], target)[key]
    final_key = path[-1]
    if isinstance(final_key, int):
        cast(list[object], target)[final_key] = value
    else:
        cast(dict[str, object], target)[final_key] = value


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("observation",), [], "observation must be a mapping"),
        (("observation", "event_id"), "", "observation is invalid"),
        (("observation", "zone"), 3, "observation is invalid"),
        (("observation", "zone"), "attic", "observation is invalid"),
        (
            ("observation", "log_likelihood_by_count"),
            {},
            "observation is invalid",
        ),
        (
            ("observation", "log_likelihood_by_count"),
            [],
            "observation is invalid",
        ),
        (
            ("observation", "log_likelihood_by_count", 0),
            math.nan,
            "observation is invalid",
        ),
        (("previous_occupied_marginals",), [], "marginals must be a mapping"),
        (
            ("previous_occupied_marginals",),
            {"attic": 0.5},
            "marginal zone is invalid",
        ),
        (("count_marginals",), [], "count marginals must be a mapping"),
        (
            ("count_marginals",),
            {"attic": [1.0]},
            "count marginal is invalid",
        ),
        (
            ("count_marginals",),
            {"office": "invalid"},
            "count marginal is invalid",
        ),
        (
            ("count_marginals",),
            {"office": []},
            "count marginal is invalid",
        ),
        (
            ("active_positive_evidence",),
            [],
            "positive evidence must be a mapping",
        ),
        (
            ("active_positive_evidence",),
            {"attic": []},
            "positive evidence is invalid",
        ),
        (
            ("active_positive_evidence",),
            {"office": "invalid"},
            "positive evidence is invalid",
        ),
        (
            ("active_positive_evidence", "hall", 0),
            [],
            "positive evidence is invalid",
        ),
        (
            ("active_positive_evidence", "hall", 0, "entity_id"),
            "",
            "positive evidence is invalid",
        ),
        (("movement_evidence",), {}, "movement evidence must be a list"),
        (
            ("movement_evidence", 0),
            [],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "path_key"),
            {},
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "path_key"),
            ["office", "hall"],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "path_key"),
            [3, None, "hall"],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "path_key"),
            ["office", 3, "hall"],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "path_key"),
            ["office", None, 3],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "origin_zone"),
            "attic",
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "source_zone"),
            "attic",
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "target_zone"),
            "attic",
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "source_node_id"),
            3,
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "target_node_id"),
            3,
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "evidence_ids"),
            {},
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "evidence_ids"),
            [3],
            "movement evidence is invalid",
        ),
        (
            ("movement_evidence", 0, "disposition"),
            "invalid",
            "movement evidence is invalid",
        ),
    ),
)
def test_policy_audit_restore_rejects_corrupt_context(
    path: tuple[str | int, ...],
    value: object,
    message: str,
) -> None:
    raw_entry, valid_zones = _contextual_policy_audit_entry()
    context = cast(dict[str, object], raw_entry["context"])
    _replace_nested(context, path, value)

    with pytest.raises(ValueError, match=message):
        _restore_policy_audit([raw_entry], valid_zones, NOW)


@pytest.mark.scenario
def test_restart_scenario_expires_leases_and_reconciles_removed_zones() -> None:
    old_map = make_map()
    occupancy_filter = JointOccupancyFilter(old_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(old_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        old_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("office", "hall", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(seconds=2),
                "expires",
            ),
        ),
        occupancy_filter.observations.entity_states,
        {},
    )
    policy_payload = cast(dict[str, dict[str, object]], payload["policy"])
    posterior_payload = cast(list[dict[str, object]], payload["posterior"])
    first_positions = cast(list[dict[str, object]], posterior_payload[0]["positions"])
    last_positions = cast(list[dict[str, object]], posterior_payload[-1]["positions"])
    leases_payload = cast(list[dict[str, object]], payload["prediction_leases"])
    policy_payload["removed_zone"] = copy.deepcopy(policy_payload["office"])
    policy_payload["hall"]["activation_expires_at"] = (
        NOW + timedelta(seconds=2)
    ).isoformat()
    first_positions[0].update(
        zone="hall",
        incoming_zone="office",
    )
    last_positions[0].update(
        zone="office",
        incoming_zone=None,
    )
    leases_payload.append(
        {
            "path_key": ["hall", None, "office"],
            "target_zone": "office",
            "probability": 0.7,
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
            "reason": "removed path",
        }
    )

    restored = restore_occupancy_state(
        payload,
        make_map(include_office=False),
        1,
        NOW + timedelta(seconds=10),
    )

    assert not restored.map_compatible
    assert restored.restore_status == "map_changed_rebuilt"
    assert restored.prediction_leases == ()
    assert set(restored.policy_states) == {"hall", "kitchen"}
    assert restored.policy_states["hall"].activation_expires_at is None
    assert len(restored.posterior.hypotheses) == 3
    assert restored.posterior.hypotheses[0].key.positions[0].zone is None
    assert all(
        position.zone is None or position.zone in {"hall", "kitchen"}
        for hypothesis in restored.posterior.hypotheses
        for position in hypothesis.key.positions
    )


@pytest.mark.scenario
def test_schema_two_migrates_policy_and_valid_counts_only() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("hall", "office", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(minutes=1),
                "discarded lease",
            ),
        ),
        occupancy_filter.observations.entity_states,
        {"office": {"hall": 2.5, "missing": 9.0}},
    )
    payload["schema_version"] = 2
    for state in cast(dict[str, dict[str, object]], payload["policy"]).values():
        state.pop("last_release_cause")
        state.pop("recovery_eligible")

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.restore_status == "migrated_policy_only"
    assert restored.policy_states["office"].keep_on
    assert restored.transition_counts == {"office": {"hall": 2.5}}
    assert restored.prediction_leases == ()
    assert restored.entity_states == {}
    assert restored.pending_departures == {}
    assert restored.update_sequence == 0
    assert restored.posterior.hypotheses[0].key.positions[0].zone is None


@pytest.mark.scenario
def test_schema_three_rebuilds_entity_multiplied_posterior() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {"office": {"hall": 2.5}},
    )
    payload["schema_version"] = 3

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.restore_status == "migrated_node_factors"
    assert restored.policy_states["office"].keep_on
    assert restored.transition_counts == {"office": {"hall": 2.5}}
    assert restored.entity_states == {}
    assert restored.directional_contexts
    assert restored.pending_departures == {}
    assert restored.posterior.hypotheses[0].key.positions[0].zone is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update(schema_version=99),
        lambda payload: payload.update(expected_occupants=2),
        lambda payload: payload.update(zone_index=[]),
        lambda payload: payload.update(update_sequence=-1),
        lambda payload: payload.update(updated_at="not-a-date"),
        lambda payload: payload.update(updated_at=None),
        lambda payload: payload.update(posterior=[]),
        lambda payload: payload["posterior"].append("bad"),
        lambda payload: payload["posterior"][0].update(probability=math.nan),
        lambda payload: payload["posterior"][0].update(positions=[]),
        lambda payload: payload["posterior"][0]["positions"].__setitem__(0, "bad"),
        lambda payload: payload["posterior"][0]["positions"][0].update(zone=3),
        lambda payload: payload["posterior"][0]["positions"][0].update(incoming_zone=3),
        lambda payload: payload["posterior"][0]["positions"][0].update(zone="attic"),
        lambda payload: payload["posterior"][0]["positions"][0].update(
            incoming_zone="attic"
        ),
        lambda payload: payload["posterior"][0].update(probability=0.5),
        lambda payload: payload.update(policy=[]),
        lambda payload: payload["policy"].update(office=[]),
        lambda payload: payload["policy"]["office"].update(keep_on="yes"),
        lambda payload: payload["policy"]["office"].update(evidence_ids=[3]),
        lambda payload: payload["policy"]["office"].update(blocked_episode_ids=[3]),
        lambda payload: payload["policy"]["office"].update(last_release_cause=3),
        lambda payload: payload["policy"]["office"].update(
            last_release_cause="not-a-cause"
        ),
        lambda payload: payload["policy"]["office"].update(recovery_eligible="yes"),
        lambda payload: payload["policy"]["office"].update(
            recovery_eligible=True,
            last_release_cause=None,
        ),
        lambda payload: payload.update(prediction_leases={}),
        lambda payload: payload["prediction_leases"].append("bad"),
        lambda payload: payload["prediction_leases"].append({}),
        lambda payload: payload["prediction_leases"].append(
            {
                "path_key": [None, None, "kitchen"],
                "target_zone": "kitchen",
                "probability": 0.8,
                "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
                "reason": "bad path",
            }
        ),
        lambda payload: payload.update(entity_states=[]),
        lambda payload: payload["entity_states"].update(bad=[]),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            state=3
        ),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            log_likelihood_by_count=[0.0]
        ),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            binding_signature={}
        ),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            duration_log_odds=-1.0
        ),
        lambda payload: payload.update(directional_contexts={}),
        lambda payload: payload["directional_contexts"].append("bad"),
        lambda payload: payload["directional_contexts"][0].update(contexts=[]),
        lambda payload: payload["directional_contexts"][0]["contexts"].__setitem__(
            0, "bad"
        ),
        lambda payload: payload["directional_contexts"][0]["contexts"][0].update(
            origin_zone="attic"
        ),
        lambda payload: payload["directional_contexts"].pop(),
        lambda payload: payload["directional_contexts"][0]["contexts"][0].update(
            probability=0.5
        ),
        lambda payload: payload.update(pending_departures=[]),
        lambda payload: payload["pending_departures"].update(attic={}),
        lambda payload: payload["pending_departures"].update(
            office={
                "current": "attic",
                "probability": 0.5,
                "nonadjacent": False,
                "evidence_ids": [],
            }
        ),
        lambda payload: payload.update(transition_counts=[]),
        lambda payload: payload["transition_counts"].update(bad=[]),
        lambda payload: payload["transition_counts"].update(bad={"target": -1}),
    ),
)
def test_corrupt_restart_state_is_rejected_atomically(mutate: object) -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
    )
    corrupt = copy.deepcopy(payload)
    mutate(corrupt)  # type: ignore[operator]

    with pytest.raises(ValueError):
        restore_occupancy_state(corrupt, predictive_map, 1, NOW)


@pytest.mark.scenario
def test_restart_reconciles_stale_leases_departures_and_unmapped_evidence() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("office", None, "attic"),
                "attic",
                0.8,
                NOW + timedelta(minutes=1),
                "stale zone",
            ),
            PredictionLease(
                ("office", "hall", "kitchen"),
                "kitchen",
                0.7,
                NOW,
                "expired",
            ),
        ),
        {
            "binary_sensor.unmapped": EntityEvidence(
                "on",
                (0.0, 0.0),
                NOW,
                NOW,
            )
        },
        {},
        pending_departures={
            "office": PendingDeparture(
                "office",
                "hall",
                0.6,
                False,
                ("office-hall",),
                "graph_valid",
                0.54,
                0.72,
            ),
            "kitchen": PendingDeparture(
                "kitchen",
                "hall",
                0.5,
                True,
                ("kitchen-hall",),
                "missed_movement",
            ),
        },
    )
    departures_payload = cast(
        dict[str, dict[str, object]],
        payload["pending_departures"],
    )
    for departure in departures_payload.values():
        departure.pop("disposition")

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.prediction_leases == ()
    assert restored.entity_states["binary_sensor.unmapped"].state == "on"
    assert restored.pending_departures["office"].disposition == "graph_valid"
    assert restored.pending_departures["office"].segment_probability == 0.54
    assert (
        restored.pending_departures["office"].destination_movement_probability
        == 0.72
    )
    assert restored.pending_departures["kitchen"].disposition == "missed_movement"


def test_restart_parser_requires_timezone_and_accepts_z_suffix() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        {},
        {},
    )
    payload["updated_at"] = "2026-07-12T12:00:00Z"
    assert (
        restore_occupancy_state(payload, predictive_map, 1, NOW).posterior.updated_at
        == NOW
    )
    payload["updated_at"] = "2026-07-12T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        restore_occupancy_state(payload, predictive_map, 1, NOW)
