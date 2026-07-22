from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.markov import MARKOV_COUNT_LIMIT
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.prediction import (
    LEASE_DURATION,
    PredictionLease,
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
    ZoneModelResult,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


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
                    "adjacent": ["hall", "living"],
                },
                "living": {
                    "zone": "living",
                    "entities": {"motion": "binary_sensor.living"},
                    "adjacent": ["kitchen"],
                },
            }
        }
    )


def confirmed_traversal() -> tuple[ZoneModelEngine, ZoneModelResult]:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    result = engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )
    assert result.authorizations[-1].track_confidence == "confirmed"
    return engine, result


def seed_mature_route(manager: TargetPredictionManager) -> None:
    for _ in range(5):
        assert manager.chain.observe("kitchen", "living")


def test_only_confirmed_physical_track_learns_and_predicts() -> None:
    _, result = confirmed_traversal()
    manager = TargetPredictionManager(make_map())

    manager.apply(result)

    assert manager.chain.counts["hall"]["kitchen"] == 1.0
    assert manager.probabilities == {"living": 0.5}
    assert manager.leases[0].support == 0.0
    assert not manager.leases[0].mature

    provisional = replace(
        result.authorizations[-1],
        track_confidence="provisional",
        path_node_ids=("hall", "kitchen"),
    )
    rejected = replace(
        result.authorizations[-1],
        authorized=False,
        track_confidence=None,
        path_node_ids=(),
        provenance_kind=None,
    )
    untouched = TargetPredictionManager(make_map())
    untouched.apply(
        ZoneModelResult(
            "accepted",
            result.snapshot,
            authorizations=(provisional, rejected),
        )
    )
    assert untouched.probabilities == {}
    assert untouched.chain.counts["hall"]["kitchen"] == 0.0


def test_prediction_rejects_missing_current_and_malformed_confirmed_edges() -> None:
    _, result = confirmed_traversal()
    authorization = result.authorizations[-1]
    manager = TargetPredictionManager(make_map())
    state_by_node = {
        state.node_id: state for state in result.snapshot.episode_states
    }

    without_current = dict(state_by_node)
    without_current.pop(authorization.target_node_id)
    assert manager._create_leases(authorization, without_current) == ()  # noqa: SLF001

    wrong_tail = replace(
        authorization,
        path_node_ids=("office", "hall"),
    )
    assert manager._confirmed_edge(wrong_tail) is None  # noqa: SLF001

    missing_source = replace(
        authorization,
        path_node_ids=("missing", authorization.target_node_id),
    )
    assert manager._confirmed_edge(missing_source) is None  # noqa: SLF001


def test_engine_prediction_projection_handles_suppressed_and_active_targets() -> None:
    lease = PredictionLease(
        "office",
        "kitchen",
        "living",
        "living",
        0.9,
        5.0,
        "source:1",
        NOW,
        NOW + timedelta(seconds=10),
        True,
        "test",
    )
    suppressed = ZoneModelEngine(make_map(), 1, NOW)
    decisions, events = suppressed._evaluate_policies(  # noqa: SLF001
        NOW,
        NOW,
        None,
        None,
        None,
        None,
        emit_events=False,
        prediction_leases=(lease,),
    )
    assert any(row.reason == "prediction_authorized" for row in decisions)
    assert events == ()

    active = ZoneModelEngine(
        make_map(),
        1,
        NOW,
        active_seed={"living": True},
    )
    decisions, events = active._evaluate_policies(  # noqa: SLF001
        NOW,
        NOW,
        None,
        None,
        None,
        None,
        prediction_leases=(lease,),
    )
    assert all(row.reason != "prediction_authorized" for row in decisions)
    assert events == ()


def test_mature_prediction_activates_same_active_entity_without_changing_belief(
) -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    living_before = next(
        state for state in engine.snapshot.belief_states if state.zone == "living"
    )

    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    result = engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    living_policy = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    living_after = next(
        state for state in result.snapshot.belief_states if state.zone == "living"
    )
    assert living_policy.active
    assert living_policy.phase == "predicted"
    assert living_policy.prediction_probability == pytest.approx(6 / 7)
    assert living_policy.prediction_support == 5.0
    assert living_after.probability == living_before.probability
    assert [event.kind for event in result.policy_events if event.zone == "living"] == [
        "acquired"
    ]
    assert result.policy_events[-1].authorization_reason == "prediction_authorized"
    prediction_decision = next(
        row
        for row in result.policy_decisions
        if row.zone == "living" and row.reason == "prediction_authorized"
    )
    assert prediction_decision.authorization_authorized
    assert prediction_decision.traversal_reason == "prediction_authorized"
    assert prediction_decision.evidence_ids == (result.policy_events[-1].episode_id,)


def test_prediction_confirmation_emits_no_second_edge_or_refresh() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    result = engine.observe(
        SensorInput("binary_sensor.living", "on", NOW + timedelta(seconds=3))
    )
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    decision = next(
        row for row in result.policy_decisions if row.zone == "living"
    )
    assert policy.active
    assert policy.phase == "active"
    assert policy.activation_provenance == "evidence"
    assert policy.prediction_expires_at is None
    assert decision.reason == "prediction_confirmed"
    assert not [event for event in result.policy_events if event.zone == "living"]
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["kitchen"]["living"] == 5.0


def test_contradictory_target_evidence_cancels_prediction_atomically() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    result = engine.observe(
        SensorInput(
            "binary_sensor.living",
            "unavailable",
            NOW + timedelta(seconds=3),
        )
    )

    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert not policy.active
    assert policy.phase == "inactive"
    assert engine.prediction_manager.leases == ()
    assert [
        (event.kind, event.policy_reason)
        for event in result.policy_events
        if event.zone == "living"
    ] == [("released", "prediction_unconfirmed")]


def test_unconfirmed_prediction_expires_at_ten_seconds_without_release_dwell() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    before = engine.advance(NOW + timedelta(seconds=11, milliseconds=999))
    before_policy = next(
        state for state in before.snapshot.policy_states if state.zone == "living"
    )
    assert before_policy.active
    result = engine.advance(NOW + timedelta(seconds=12))
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert not policy.active
    assert policy.phase == "inactive"
    assert [(event.kind, event.policy_reason) for event in result.policy_events] == [
        ("released", "prediction_unconfirmed")
    ]


def test_target_evidence_at_prediction_deadline_cannot_confirm_expired_phase() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    result = engine.observe(
        SensorInput("binary_sensor.living", "on", NOW + timedelta(seconds=12))
    )
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert policy.active
    assert policy.phase == "active"
    assert [(event.kind, event.policy_reason) for event in result.policy_events] == [
        ("released", "prediction_unconfirmed"),
        ("acquired", "acquired"),
    ]


def test_sparse_probability_one_and_provisional_track_cannot_activate() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    for _ in range(4):
        engine.prediction_manager.chain.observe("kitchen", "living")
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    provisional = engine.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    )
    assert not any(
        state.phase == "predicted" for state in provisional.snapshot.policy_states
    )

    result = engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )
    living = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert not living.active
    lease = engine.prediction_manager.leases[0]
    assert lease.probability == pytest.approx(5 / 6)
    assert lease.support == 4.0
    assert not lease.mature


def test_backtracking_exclusion_cannot_renormalize_weak_route_to_maturity() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    for _ in range(100):
        engine.prediction_manager.chain.observe("kitchen", "hall")
    for _ in range(5):
        engine.prediction_manager.chain.observe("kitchen", "living")

    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    result = engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    living = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    lease = next(
        item
        for item in engine.prediction_manager.leases
        if item.target_node_id == "living"
    )
    assert lease.probability == pytest.approx(6 / 107)
    assert lease.support == 5.0
    assert not lease.mature
    assert not living.active


def test_prediction_learning_is_explicitly_deferred() -> None:
    engine, result = confirmed_traversal()
    assert result.authorizations[-1].track_confidence == "confirmed"
    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 0.0

    engine.commit_prediction_learning()

    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 1.0
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 1.0


def test_same_route_leases_retain_each_source_episode_identity() -> None:
    _engine, result = confirmed_traversal()
    authorization = result.authorizations[-1]
    states = {state.node_id: state for state in result.snapshot.episode_states}
    manager = TargetPredictionManager(make_map())
    seed_mature_route(manager)

    first = manager._create_leases(authorization, states)  # noqa: SLF001
    second_authorization = replace(
        authorization,
        target_episode_id=f"{authorization.target_episode_id}:next",
        authorized_at=authorization.authorized_at + timedelta(seconds=1),
    )
    second = manager._create_leases(second_authorization, states)  # noqa: SLF001

    assert len(first) == len(second) == 1
    assert {lease.source_episode_id for lease in manager.leases} == {
        authorization.target_episode_id,
        second_authorization.target_episode_id,
    }


def test_observed_departure_cancels_stale_outgoing_route_lease() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )
    assert engine.prediction_manager.leases

    departure = replace(
        confirmed_traversal()[1].authorizations[-1],
        path_node_ids=("office", "kitchen", "hall"),
        target_node_id="hall",
        target_zone="hall",
        target_episode_id="hall:departure",
        authorized_at=NOW + timedelta(seconds=3),
    )
    engine._advance_components(NOW + timedelta(seconds=3))  # noqa: SLF001
    new_leases = engine._prepare_predictions(  # noqa: SLF001
        NOW + timedelta(seconds=3),
        (departure,),
    )
    _decisions, events = engine._evaluate_policies(  # noqa: SLF001
        NOW + timedelta(seconds=3),
        NOW + timedelta(seconds=3),
        None,
        None,
        None,
        None,
        prediction_leases=new_leases,
    )
    engine.commit_prediction_learning()

    assert all(
        lease.current_node_id != "kitchen"
        for lease in engine.prediction_manager.leases
    )
    assert any(
        event.zone == "living" and event.policy_reason == "prediction_unconfirmed"
        for event in events
    )
    living = engine._policies["living"].state  # noqa: SLF001
    assert not living.active
    assert engine.prediction_manager.chain.counts["kitchen"]["hall"] == 1.0


def test_source_unavailability_cancels_prediction_and_public_phase() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    result = engine.observe(
        SensorInput(
            "binary_sensor.kitchen",
            "unavailable",
            NOW + timedelta(seconds=3),
        )
    )

    living = next(
        policy for policy in result.snapshot.policy_states if policy.zone == "living"
    )
    assert not living.active
    assert all(
        lease.current_node_id != "kitchen"
        for lease in engine.prediction_manager.leases
    )
    assert any(
        event.zone == "living" and event.policy_reason == "prediction_unconfirmed"
        for event in result.policy_events
    )


def test_one_failed_publication_suppresses_later_callbacks_but_commits_turn(
) -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    callback_calls = 0

    def fail_once(*_args: object) -> None:
        nonlocal callback_calls
        callback_calls += 1
        raise RuntimeError("dispatcher failed")

    with pytest.raises(RuntimeError, match="dispatcher failed"):
        engine.observe(
            SensorInput(
                "binary_sensor.kitchen",
                "on",
                NOW + timedelta(seconds=2),
            ),
            decision_callback=fail_once,
        )

    assert callback_calls == 1
    policies = {state.zone: state for state in engine.snapshot.policy_states}
    assert policies["kitchen"].active
    assert policies["living"].active
    assert policies["living"].phase == "predicted"
    assert {row.zone for row in engine.audit_rows if row.event_kind == "acquired"} >= {
        "kitchen",
        "living",
    }
    engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 0.0


def test_count_zero_discards_deferred_confirmed_route_learning() -> None:
    engine, result = confirmed_traversal()
    assert result.authorizations[-1].track_confidence == "confirmed"
    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 0.0

    engine.observe_count(
        CountInput(
            "count-zero-before-learning",
            0,
            True,
            NOW + timedelta(seconds=3),
        )
    )
    engine.commit_prediction_learning()

    assert engine.prediction_manager.chain.counts["hall"]["kitchen"] == 0.0


def test_prediction_count_zero_clear_and_restore_are_isolated() -> None:
    engine, result = confirmed_traversal()
    manager = TargetPredictionManager(make_map())
    seed_mature_route(manager)
    manager.apply(result)
    payload = manager.serialize()

    restored = TargetPredictionManager(make_map())
    restored.restore(payload, NOW + timedelta(seconds=3))
    assert restored.probabilities == manager.probabilities
    assert restored.expire(NOW + timedelta(seconds=12))
    assert restored.probabilities == {}

    restored.restore(payload, NOW + timedelta(seconds=3))
    count_zero = replace(
        engine.snapshot,
        count_state=replace(engine.snapshot.count_state, expected_count=0),
    )
    restored.apply(ZoneModelResult("accepted", count_zero))
    assert restored.probabilities == {}


def test_prediction_restore_rejects_map_incompatible_lease_atomically() -> None:
    _, result = confirmed_traversal()
    manager = TargetPredictionManager(make_map())
    seed_mature_route(manager)
    manager.apply(result)
    payload = manager.serialize()
    leases = payload["leases"]
    assert isinstance(leases, list)
    leases[0]["target_node_id"] = "missing"

    restored = TargetPredictionManager(make_map())
    with pytest.raises(ValueError, match="map-incompatible"):
        restored.restore(payload, NOW + timedelta(seconds=3))
    assert restored.probabilities == {}


@pytest.mark.parametrize(
    "invalid_count",
    ("garbage", -1, float("inf"), True, MARKOV_COUNT_LIMIT + 1),
)
def test_v3_prediction_restore_rejects_invalid_route_counts_atomically(
    invalid_count: object,
) -> None:
    source = TargetPredictionManager(make_map())
    payload = source.serialize()
    counts = payload["counts"]
    assert isinstance(counts, dict)
    office = counts["office"]
    assert isinstance(office, dict)
    office["hall"] = invalid_count
    restored = TargetPredictionManager(make_map())
    baseline = restored.serialize()

    with pytest.raises(ValueError, match="route counts are invalid"):
        restored.restore(payload, NOW)

    assert restored.serialize() == baseline


@pytest.mark.parametrize("mutation", ("source", "target", "nested"))
def test_v3_prediction_restore_requires_exact_route_count_shape(
    mutation: str,
) -> None:
    manager = TargetPredictionManager(make_map())
    payload = deepcopy(manager.serialize())
    counts = payload["counts"]
    assert isinstance(counts, dict)
    if mutation == "source":
        counts.pop("office")
    elif mutation == "target":
        office = counts["office"]
        assert isinstance(office, dict)
        office["missing"] = 0.0
    else:
        counts["office"] = []

    with pytest.raises(ValueError, match="route counts"):
        manager.restore(payload, NOW)


def valid_lease_payload() -> dict[str, object]:
    return {
        "source_node_id": "hall",
        "current_node_id": "kitchen",
        "target_node_id": "living",
        "target_zone": "living",
        "probability": 1.0,
        "support": 5.0,
        "source_episode_id": "kitchen:1",
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + LEASE_DURATION).isoformat(),
        "mature": True,
        "reason": "confirmed-track prediction",
    }


@pytest.mark.parametrize(
    "update",
    (
        {"probability": 2.0},
        {"support": -1.0},
        {"mature": False},
        {"mature": "true"},
        {"expires_at": NOW.isoformat()},
        {"source_episode_id": ""},
        {"reason": "junk"},
        {"extra": "junk"},
    ),
)
def test_prediction_decoder_rejects_invalid_lease_values(
    update: dict[str, object],
) -> None:
    raw = valid_lease_payload()
    raw.update(update)
    with pytest.raises(ValueError, match="invalid"):
        TargetPredictionManager(make_map())._decode_lease(raw)  # noqa: SLF001


def test_prediction_restore_and_decoder_boundaries() -> None:
    manager = TargetPredictionManager(make_map())
    with pytest.raises(ValueError, match="mapping"):
        manager.restore([], NOW)
    with pytest.raises(ValueError, match="invalid"):
        manager.restore({"counts": [], "leases": []}, NOW)
    with pytest.raises(ValueError, match="mapping"):
        manager._decode_lease([])  # noqa: SLF001
    with pytest.raises(ValueError, match="invalid"):
        manager._decode_lease({})  # noqa: SLF001

    expired = valid_lease_payload()
    expired["created_at"] = (NOW - LEASE_DURATION).isoformat()
    expired["expires_at"] = NOW.isoformat()
    manager.restore(
        {"counts": manager.serialize()["counts"], "leases": [expired]},
        NOW,
    )
    assert manager.leases == ()

    duplicate = valid_lease_payload()
    with pytest.raises(ValueError, match="duplicated"):
        manager.restore(
            {
                "counts": manager.serialize()["counts"],
                "leases": [duplicate, deepcopy(duplicate)],
            },
            NOW,
        )


def test_prediction_enforces_live_and_restored_lease_bounds() -> None:
    manager = TargetPredictionManager(make_map())
    for index in range(65):
        lease = PredictionLease(
            "hall",
            "kitchen",
            f"target-{index}",
            f"zone-{index}",
            0.5,
            0.0,
            f"episode-{index}",
            NOW + timedelta(microseconds=index),
            NOW + timedelta(seconds=10, microseconds=index),
            False,
            "test seed",
        )
        manager._leases[  # noqa: SLF001
            ("hall", "kitchen", lease.target_node_id, lease.source_episode_id)
        ] = lease
    manager._enforce_bound()  # noqa: SLF001
    assert len(manager.leases) == 64

    target_ids = [f"target_{index}" for index in range(65)]
    nodes: dict[str, object] = {
        "source": {"adjacent": ["hub"]},
        "hub": {"adjacent": ["source", *target_ids]},
    }
    nodes.update({target: {"adjacent": ["hub"]} for target in target_ids})
    large_map = PredictiveMap.from_mapping({"nodes": nodes})
    leases = []
    for target in target_ids:
        raw = valid_lease_payload()
        raw.update(
            {
                "source_node_id": "source",
                "current_node_id": "hub",
                "target_node_id": target,
                "target_zone": target,
                "probability": 1 / 65,
                "support": 0.0,
                "source_episode_id": f"hub:{target}",
                "mature": False,
            }
        )
        leases.append(raw)
    with pytest.raises(ValueError, match="bound exceeded"):
        large_manager = TargetPredictionManager(large_map)
        large_manager.restore(
            {"counts": large_manager.serialize()["counts"], "leases": leases},
            NOW,
        )


def test_prediction_target_health_and_contradictory_evidence_block_activation() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.living", "unavailable", NOW))
    engine.observe(
        SensorInput("binary_sensor.office", "on", NOW + timedelta(seconds=1))
    )
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=2)))
    result = engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=3))
    )
    living = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert not living.active
    assert engine.prediction_manager.leases == ()


def test_count_input_zero_expires_predicted_policy_immediately() -> None:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1)))
    engine.observe(
        SensorInput("binary_sensor.kitchen", "on", NOW + timedelta(seconds=2))
    )

    result = engine.observe_count(
        CountInput("count:0", 0, True, NOW + timedelta(seconds=3))
    )
    living = next(
        state for state in result.snapshot.policy_states if state.zone == "living"
    )
    assert not living.active
    assert engine.prediction_manager.leases == ()
