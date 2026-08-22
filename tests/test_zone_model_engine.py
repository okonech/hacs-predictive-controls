from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)

NOW = datetime(2026, 7, 18, 22, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def target_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def correlated_continuity_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bottom"},
                    "adjacent": ["top"],
                },
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["bottom", "bathroom"],
                },
                "bathroom": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.bathroom"},
                    "adjacent": ["top"],
                },
            }
        }
    )


def interaction_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "room_interaction": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.room_scene_001",
                        "interaction_scene_002": "event.room_scene_002",
                    },
                }
            }
        }
    )


def test_older_interaction_clear_does_not_withdraw_newer_same_zone_pulse() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "switch_a": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"interaction_a": "event.switch_a"},
                },
                "switch_b": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"interaction_b": "event.switch_b"},
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("event.switch_a", "pressed", NOW))
    engine.observe(
        SensorInput("event.switch_b", "pressed", NOW + timedelta(seconds=1))
    )
    supports = engine.snapshot.anonymous_supports
    assert len(supports) == 1
    assert supports[0].current_zone == "room"
    assert supports[0].provenance_kind == "local_interaction"
    episodes = {state.node_id: state for state in engine.snapshot.episode_states}
    first_clear = episodes["switch_a"].clear_deadline
    second_clear = episodes["switch_b"].clear_deadline
    assert first_clear is not None and second_clear is not None

    after_first_clear = engine.advance(first_clear)
    belief = next(
        state
        for state in after_first_clear.snapshot.belief_states
        if state.zone == "room"
    )
    assert belief.context == "asserted"

    after_second_clear = engine.advance(second_clear)
    belief = next(
        state
        for state in after_second_clear.snapshot.belief_states
        if state.zone == "room"
    )
    assert belief.context == "cleared_without_outward"


def test_interaction_count_two_acquires_without_conflict_delay() -> None:
    engine = ZoneModelEngine(interaction_map(), 2, NOW)

    result = engine.observe(
        SensorInput("event.room_scene_001", "pressed", NOW + timedelta(seconds=1))
    )

    authorization = result.authorizations[0]
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    )
    assert authorization.reason == "local_interaction"
    assert authorization.provenance_kind == "local_interaction"
    assert authorization.equivalent_confirmed_strength
    assert policy.active
    assert result.snapshot.pending_candidates == ()
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("room", "acquired")
    ]


def test_interaction_at_clear_deadline_applies_timer_then_new_generation() -> None:
    engine = ZoneModelEngine(interaction_map(), 1, NOW)
    first = engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    first_episode = first.snapshot.episode_states[0]
    clear_deadline = first_episode.clear_deadline
    assert clear_deadline is not None

    replaced = engine.observe(
        SensorInput("event.room_scene_002", "pressed", clear_deadline)
    )

    episode = replaced.snapshot.episode_states[0]
    belief = replaced.snapshot.belief_states[0]
    assert episode.generation == first_episode.generation + 1
    assert belief.generation_episode_id == episode.episode_id
    assert belief.log_odds == 30.0
    assert [item.kind for item in belief.contributions[-2:]] == [
        "stable_clear",
        "local_interaction",
    ]
    assert not any(event.kind == "released" for event in replaced.policy_events)


def test_interaction_publication_failure_commits_atomic_snapshot() -> None:
    engine = ZoneModelEngine(interaction_map(), 1, NOW)
    event_at = NOW + timedelta(seconds=1)

    def fail(_event: object, _decision: object, _authorization: object) -> None:
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        engine.observe(
            SensorInput("event.room_scene_001", "pressed", event_at),
            decision_callback=fail,
        )

    policy = engine.snapshot.policy_states[0]
    assert engine.snapshot.updated_at == event_at
    assert policy.active
    assert len(engine.snapshot.traversal_tokens) == 1
    assert len(engine.snapshot.anonymous_supports) == 1
    assert engine.audit_rows[-1].local_evidence_kind == "interaction"
    assert engine.audit_rows[-1].traversal_reason == "local_interaction"


def test_interaction_health_invalidates_token_and_support_without_release() -> None:
    engine = ZoneModelEngine(interaction_map(), 1, NOW)
    acquired = engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    assert acquired.snapshot.traversal_tokens
    assert acquired.snapshot.anonymous_supports

    unavailable = engine.observe(
        SensorInput("event.room_scene_002", "unknown", NOW + timedelta(seconds=1))
    )

    assert unavailable.disposition == "neutral_availability"
    assert unavailable.snapshot.episode_states[0].status == "unavailable"
    assert unavailable.snapshot.belief_states[0].context == "unavailable"
    assert unavailable.snapshot.traversal_tokens == ()
    assert unavailable.snapshot.retained_traversal_tokens == ()
    assert unavailable.snapshot.anonymous_supports == ()
    assert unavailable.snapshot.policy_states[0].active
    assert not any(event.kind == "released" for event in unavailable.policy_events)


def test_engine_composes_transition_authorization_and_policy_acquisition() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    hall = engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    room = engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    assert hall.policy_events == ()
    assert room.authorizations[0].reason == "provisional_track_acquired"
    assert [(event.zone, event.kind) for event in room.policy_events] == [
        ("room", "acquired")
    ]
    assert {state.zone: state.active for state in room.snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }


def test_incident_correlated_hallway_reassertion_preserves_authorized_path() -> None:
    engine = ZoneModelEngine(correlated_continuity_map(), 2, NOW)
    bottom_at = NOW
    top_at = NOW + timedelta(seconds=7, microseconds=93785)
    top_off_at = top_at + timedelta(seconds=43, microseconds=488547)
    token_expiry = top_at + timedelta(seconds=45)
    reasserted_at = top_off_at + timedelta(seconds=2, microseconds=200084)
    bathroom_at = reasserted_at + timedelta(seconds=6, microseconds=712904)

    engine.observe(SensorInput("binary_sensor.bottom", "on", bottom_at))
    top = engine.observe(SensorInput("binary_sensor.top", "on", top_at))
    assert top.authorizations[0].reason == "provisional_track_acquired"
    engine.observe(
        SensorInput(
            "binary_sensor.bottom",
            "off",
            bottom_at + timedelta(seconds=21, microseconds=339468),
        )
    )
    engine.observe(SensorInput("binary_sensor.top", "off", top_off_at))
    engine.advance(token_expiry + timedelta(milliseconds=50))

    top_token = next(
        token
        for token in engine.snapshot.retained_traversal_tokens
        if token.node_id == "top"
    )
    assert top_token.path_node_ids == ("bottom", "top")

    reasserted = engine.observe(SensorInput("binary_sensor.top", "on", reasserted_at))
    top_decision = next(
        decision for decision in reasserted.policy_decisions if decision.zone == "top"
    )
    assert reasserted.disposition == "correlated_reassertion"
    assert reasserted.policy_events == ()
    assert top_decision.reason == "correlated_continuity_authorized"
    assert top_decision.local_evidence_kind == "correlated_continuity_authorized"
    assert top_decision.belief_before == top_decision.belief_after
    reopened = next(
        token
        for token in reasserted.snapshot.traversal_tokens
        if token.node_id == "top"
    )
    assert reopened.token_id == top_token.token_id
    assert reopened.accepted_at == top_token.accepted_at
    assert reopened.path_node_ids == top_token.path_node_ids
    assert reopened.continuity_reopened_at == reasserted_at
    assert reopened.valid_until == top_at + timedelta(seconds=60)

    bathroom = engine.observe(SensorInput("binary_sensor.bathroom", "on", bathroom_at))
    authorization = bathroom.authorizations[0]
    assert authorization.authorized
    assert authorization.reason == "track_confirmed"
    assert authorization.track_confidence == "confirmed"
    assert authorization.path_node_ids == ("bottom", "top", "bathroom")
    assert [(event.zone, event.kind) for event in bathroom.policy_events] == [
        ("bathroom", "acquired")
    ]


def test_supported_edge_callback_precedes_whole_house_count_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    order: list[str] = []
    original = cast(Any, engine._count_conflicts.evaluate)  # noqa: SLF001

    def count_work(*args: Any, **kwargs: Any) -> Any:
        order.append("whole_house_count")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine._count_conflicts, "evaluate", count_work)  # noqa: SLF001

    engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)),
        decision_callback=lambda *_args: order.append("publication"),
    )

    assert order[0] == "publication"
    assert order[1:] == ["whole_house_count"]


def test_supported_edge_callback_precedes_unrelated_pending_expiry_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "isolated": {
                    "entities": {"motion": "binary_sensor.isolated"},
                    "adjacent": [],
                },
                "a": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.a"},
                    "adjacent": ["b"],
                },
                "b": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.b"},
                    "adjacent": ["a", "c"],
                },
                "c": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.c"},
                    "adjacent": ["b", "d"],
                },
                "d": {
                    "entities": {"motion": "binary_sensor.d"},
                    "adjacent": ["c"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.isolated", "on", NOW))
    engine.observe(SensorInput("binary_sensor.a", "on", NOW + timedelta(seconds=87)))
    engine.observe(SensorInput("binary_sensor.b", "on", NOW + timedelta(seconds=88)))
    engine.observe(SensorInput("binary_sensor.c", "on", NOW + timedelta(seconds=89)))
    order: list[str] = []
    original = cast(Any, engine._policies["isolated"].record_pending_expiry)  # noqa: SLF001

    def pending_expiry(*args: Any, **kwargs: Any) -> Any:
        order.append("pending_expiry_materialized")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engine._policies["isolated"],  # noqa: SLF001
        "record_pending_expiry",
        pending_expiry,
    )

    result = engine.observe(
        SensorInput("binary_sensor.d", "on", NOW + timedelta(seconds=90)),
        decision_callback=lambda *_args: order.append("publication"),
    )

    authorization = result.authorizations[-1]
    assert authorization.reason == "adjacent_authorized"
    assert next(
        state for state in result.snapshot.policy_states if state.zone == "d"
    ).active
    assert order == ["publication", "pending_expiry_materialized"]


def test_publication_callback_failure_reports_after_atomic_engine_commit() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    baseline = engine.audit_rows

    def fail(_event: object, _decision: object, _authorization: object) -> None:
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        engine.observe(
            SensorInput(
                "binary_sensor.room",
                "on",
                NOW + timedelta(seconds=2),
            ),
            decision_callback=fail,
        )

    assert len(engine.audit_rows) > len(baseline)
    assert engine.snapshot.updated_at == NOW + timedelta(seconds=2)
    room = next(
        state for state in engine.snapshot.policy_states if state.zone == "room"
    )
    assert room.active
    follow_up = engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3))
    )
    assert follow_up.disposition == "clear_pending"


def test_publication_callback_deferral_discards_on_engine_validation_failure() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    baseline = engine.audit_rows

    with pytest.raises(ValueError, match="processing time cannot precede"):
        engine.observe(
            SensorInput("binary_sensor.hall", "on", NOW),
            processing_at=NOW - timedelta(microseconds=1),
            decision_callback=lambda *_args: None,
        )

    assert engine.audit_rows == baseline


def test_count_zero_sensor_assertion_remains_categorical_empty_baseline() -> None:
    engine = ZoneModelEngine(target_map(), 0, NOW)

    result = engine.observe(SensorInput("binary_sensor.room", "on", NOW))

    assert result.policy_events == ()
    assert result.authorizations == ()
    assert result.snapshot.traversal_tokens == ()
    assert result.snapshot.pending_candidates == ()
    assert all(not state.active for state in result.snapshot.policy_states)
    assert all(
        state.probability == pytest.approx(0.05)
        and state.generation_episode_id is None
        and state.asserted_episode_id is None
        for state in result.snapshot.belief_states
    )


def test_count_zero_bootstrap_assertion_remains_empty_baseline() -> None:
    engine = ZoneModelEngine(target_map(), 0, NOW)

    snapshot = engine.bootstrap_sensor_snapshot(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )
    assert snapshot.traversal_tokens == ()
    assert snapshot.pending_candidates == ()
    assert all(not state.active for state in snapshot.policy_states)
    assert all(
        state.probability == pytest.approx(0.05)
        and state.generation_episode_id is None
        and state.asserted_episode_id is None
        for state in snapshot.belief_states
    )


@pytest.mark.parametrize("previously_asserted", (False, True))
def test_accepted_off_ends_unavailable_belief_context(
    previously_asserted: bool,
) -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    if previously_asserted:
        engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    unavailable_at = NOW + timedelta(seconds=1)
    engine.observe(SensorInput("binary_sensor.room", "unavailable", unavailable_at))
    unavailable = next(
        state for state in engine.snapshot.belief_states if state.zone == "room"
    )

    result = engine.observe(
        SensorInput(
            "binary_sensor.room",
            "off",
            unavailable_at + timedelta(seconds=1),
        )
    )
    recovered = next(
        state for state in result.snapshot.belief_states if state.zone == "room"
    )

    assert recovered.context == "cleared_without_outward"
    assert recovered.outward_context is None
    if previously_asserted:
        assert recovered.probability <= unavailable.probability
        assert recovered.contributions[-1].kind == "availability_clear"
        assert recovered.contributions[-1].log_odds_delta == 0.0
    else:
        assert recovered.probability == pytest.approx(0.05)


def test_engine_count_zero_resets_beliefs_frontier_and_active_state() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    zero_at = NOW + timedelta(seconds=3)
    result = engine.observe_count(CountInput("count:zero", 0, True, zero_at))

    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("room", "released")
    ]
    assert result.snapshot.traversal_tokens == ()
    assert all(not state.active for state in result.snapshot.policy_states)
    assert all(
        state.generation_episode_id is None for state in result.snapshot.belief_states
    )


def test_engine_timer_degrades_transition_but_preserves_held_room() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    direct = engine.advance(NOW + timedelta(minutes=20))

    states = {state.zone: state for state in direct.snapshot.policy_states}
    assert states["room"].active is True
    assert ("room", "released") not in {
        (event.zone, event.kind) for event in direct.policy_events
    }
    episodes = {state.node_id: state for state in direct.snapshot.episode_states}
    assert episodes["hall"].health_warning
    assert not episodes["room"].health_warning


def test_bootstrap_asserted_stay_seeds_belief_but_not_active() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    snapshot = engine.bootstrap_sensor_snapshot(
        (
            SensorInput("binary_sensor.hall", "off", NOW),
            SensorInput("binary_sensor.room", "on", NOW),
        ),
        NOW,
    )

    assert {state.zone: state.active for state in snapshot.policy_states} == {
        "hall": False,
        "room": False,
    }
    assert engine.audit_rows == ()
    assert snapshot.traversal_tokens == ()

    empty_house = ZoneModelEngine(target_map(), 0, NOW)
    empty_snapshot = empty_house.bootstrap_sensor_snapshot(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )
    assert all(not state.active for state in empty_snapshot.policy_states)


def test_isolated_positive_expires_without_activation() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    result = engine.observe(SensorInput("binary_sensor.room", "on", NOW))

    assert not result.authorizations[0].authorized
    assert result.authorizations[0].reason == "track_bootstrap_pending"
    candidate = result.snapshot.pending_candidates[0]
    before = engine.advance(candidate.expires_at - timedelta(microseconds=1))
    expired = engine.advance(candidate.expires_at)
    assert not any(
        event.zone == "room" and event.kind == "acquired"
        for event in (
            *result.policy_events,
            *before.policy_events,
            *expired.policy_events,
        )
    )
    assert all(
        decision.reason != "untracked_expired" for decision in before.policy_decisions
    )
    expiry = next(
        decision
        for decision in expired.policy_decisions
        if decision.reason == "untracked_expired"
    )
    assert expiry.zone == "room"
    assert expiry.node_id == "room"
    assert expiry.episode_id == candidate.episode_id
    assert expiry.active_before is expiry.active_after is False
    assert expiry.evidence_ids == (candidate.episode_id,)
    assert expired.snapshot.pending_candidates == ()
    room = next(
        state for state in expired.snapshot.policy_states if state.zone == "room"
    )
    assert room.active is False


def test_pending_adjacent_pair_activates_only_leading_zone() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)

    first = engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    second = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2))
    )

    assert first.policy_events == ()
    assert second.authorizations[0].reason == "provisional_track_acquired"
    states = {state.zone: state.active for state in second.snapshot.policy_states}
    assert states == {"hall": False, "room": True}
    assert {
        token.node_id: token.track_confidence
        for token in second.snapshot.traversal_tokens
    } == {"hall": "provisional", "room": "provisional"}


def test_third_distinct_adjacent_node_confirms_track() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "a": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.a"},
                    "adjacent": ["b"],
                },
                "b": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.b"},
                    "adjacent": ["a", "c"],
                },
                "c": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.c"},
                    "adjacent": ["b"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.a", "on", NOW))
    engine.observe(SensorInput("binary_sensor.b", "on", NOW + timedelta(seconds=1)))

    result = engine.observe(
        SensorInput("binary_sensor.c", "on", NOW + timedelta(seconds=2))
    )

    assert result.authorizations[0].reason == "track_confirmed"
    target = next(
        token for token in result.snapshot.traversal_tokens if token.node_id == "c"
    )
    assert target.track_confidence == "confirmed"
    assert target.path_node_ids == ("a", "b", "c")


def test_two_node_backtracking_remains_provisional() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    engine.observe(SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3)))
    engine.advance(NOW + timedelta(seconds=8))

    result = engine.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=20))
    )

    target = max(
        (
            token
            for token in result.snapshot.traversal_tokens
            if token.node_id == "hall"
        ),
        key=lambda token: token.accepted_at,
    )
    assert target.track_confidence == "provisional"
    assert len(set(target.path_node_ids)) == 2


def test_same_node_flap_cannot_bootstrap_or_activate() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    first = engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=1)))
    flap = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2))
    )

    assert first.policy_events == ()
    assert flap.policy_events == ()
    assert flap.disposition == "correlated_reassertion"
    assert any(
        decision.reason == "impossible_cadence" for decision in flap.policy_decisions
    )
    assert flap.snapshot.traversal_tokens == ()


def test_correlated_flap_after_hardware_hold_is_ignored_and_audited() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    first = engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=31))
    )

    flap = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=32))
    )

    assert first.policy_events == ()
    assert flap.disposition == "correlated_reassertion"
    assert flap.policy_events == ()
    assert any(
        decision.reason == "correlated_flap_ignored"
        for decision in flap.policy_decisions
    )
    assert flap.snapshot.traversal_tokens == ()


def test_engine_rejects_ambiguous_behavior_or_mixed_profile_zones() -> None:
    ambiguous = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unknown": {
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": "binary_sensor.unknown"},
                }
            }
        }
    )
    with pytest.raises(ValueError, match="ambiguous occupancy metadata"):
        ZoneModelEngine(ambiguous, 1, NOW)

    mixed = PredictiveMap.from_mapping(
        {
            "nodes": {
                "pir": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.pir"},
                },
                "presence": {
                    "zone": "room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.presence"},
                },
            }
        }
    )
    with pytest.raises(ValueError, match="one shared profile"):
        ZoneModelEngine(mixed, 1, NOW)


def test_engine_snapshot_restore_is_atomic_and_emits_no_bootstrap_edge() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    engine.observe(SensorInput("binary_sensor.room", "on", room_at))
    snapshot = engine.snapshot

    restored = ZoneModelEngine.restore(
        target_map(),
        snapshot,
        engine.audit_rows,
        room_at + timedelta(seconds=1),
    )

    assert restored.snapshot.policy_states == tuple(
        sorted(restored.snapshot.policy_states, key=lambda state: state.zone)
    )
    assert {state.zone: state.active for state in restored.snapshot.policy_states}[
        "room"
    ] is True
    assert restored.snapshot.current_token_ids


def test_restore_path_validation_accepts_two_hops_but_not_same_node() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "a": {
                    "entities": {"motion": "binary_sensor.a"},
                    "adjacent": ["b"],
                },
                "b": {
                    "entities": {"motion": "binary_sensor.b"},
                    "adjacent": ["a", "c"],
                },
                "c": {
                    "entities": {"motion": "binary_sensor.c"},
                    "adjacent": ["b"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)

    assert engine._bounded_path_step("a", "c")  # noqa: SLF001
    assert not engine._bounded_path_step("a", "a")  # noqa: SLF001


def test_restore_episode_reference_rejects_malformed_and_unknown_nodes() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    states = {state.node_id: state for state in engine.snapshot.episode_states}

    with pytest.raises(ValueError, match="malformed"):
        engine._episode_reference(  # noqa: SLF001
            "hall:not-valid",
            states,
            NOW,
            exact=False,
        )
    with pytest.raises(ValueError, match="no stored physical node"):
        engine._episode_reference(  # noqa: SLF001
            f"missing:1:{NOW.isoformat()}",
            states,
            NOW,
            exact=False,
        )
