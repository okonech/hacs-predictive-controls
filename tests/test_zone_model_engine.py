from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
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


def presence_target_map() -> PredictiveMap:
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
                    "entities": {"mmwave": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def same_zone_presence_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "first": {
                    "zone": "room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.first"},
                },
                "second": {
                    "zone": "room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.second"},
                },
            }
        }
    )


def cleared_source(
    engine: ZoneModelEngine,
    node_id: str,
    *,
    started_at: datetime = NOW,
    cleared_at: datetime = NOW + timedelta(seconds=2),
    stable_clear_at: datetime = NOW + timedelta(seconds=12),
) -> tuple[EpisodeState, EpisodeEffect]:
    state = next(
        item for item in engine.snapshot.episode_states if item.node_id == node_id
    )
    episode_id = state.episode_id or f"{node_id}:1:{started_at.isoformat()}"
    return (
        replace(
            state,
            alias_states=((f"binary_sensor.{node_id}", "off"),),
            generation=max(1, state.generation),
            episode_id=episode_id,
            status="clear",
            started_at=started_at,
            last_event_at=cleared_at,
            advanced_at=stable_clear_at,
            clear_started_at=None,
            clear_deadline=None,
            traversal_valid_until=None,
            clear_emitted=True,
        ),
        EpisodeEffect(
            node_id,
            "room",
            episode_id,
            "stable_clear",
            stable_clear_at,
        ),
    )


def test_confirmed_departure_requires_a_current_belief_generation() -> None:
    engine = ZoneModelEngine(same_zone_presence_map(), 1, NOW)
    source, effect = cleared_source(engine, "first")

    with pytest.raises(AssertionError):
        engine._register_confirmed_departure(source, effect)  # noqa: SLF001

    belief = engine.snapshot.belief_states[0]
    assert belief.generation_episode_id is None
    assert belief.context == "cleared_without_outward"


def test_confirmed_departure_rejects_noninteraction_generation() -> None:
    engine = ZoneModelEngine(same_zone_presence_map(), 1, NOW)
    engine.observe(
        SensorInput("binary_sensor.second", "on", NOW + timedelta(seconds=1))
    )
    engine.observe(
        SensorInput("binary_sensor.second", "off", NOW + timedelta(seconds=2))
    )
    engine.advance(NOW + timedelta(seconds=12))
    source, effect = cleared_source(
        engine,
        "first",
        stable_clear_at=NOW + timedelta(seconds=13),
    )

    engine._register_confirmed_departure(source, effect)  # noqa: SLF001

    belief = engine.snapshot.belief_states[0]
    second = next(
        state for state in engine.snapshot.episode_states if state.node_id == "second"
    )
    assert belief.generation_episode_id == second.episode_id
    assert belief.context == "cleared_without_outward"


def test_confirmed_departure_rejects_another_asserted_same_zone_stay() -> None:
    engine = ZoneModelEngine(same_zone_presence_map(), 1, NOW)
    engine.observe(
        SensorInput("binary_sensor.second", "on", NOW + timedelta(seconds=1))
    )
    engine.observe(
        SensorInput("binary_sensor.first", "on", NOW + timedelta(seconds=2))
    )
    first = next(
        state for state in engine.snapshot.episode_states if state.node_id == "first"
    )
    assert first.episode_id is not None
    engine._filters["room"].apply_stable_clear(  # noqa: SLF001
        first.episode_id,
        NOW + timedelta(seconds=12),
        1.0,
    )
    source = replace(
        first,
        alias_states=(("binary_sensor.first", "off"),),
        status="clear",
        last_event_at=NOW + timedelta(seconds=3),
        advanced_at=NOW + timedelta(seconds=12),
        traversal_valid_until=None,
        clear_emitted=True,
    )
    effect = EpisodeEffect(
        "first",
        "room",
        first.episode_id,
        "stable_clear",
        NOW + timedelta(seconds=12),
    )

    engine._register_confirmed_departure(source, effect)  # noqa: SLF001

    assert engine.snapshot.belief_states[0].context == "cleared_without_outward"


def correlated_arrival_incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "bottom": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bottom"},
                    "adjacent": ["hall"],
                    "initial_weight": 0.8,
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["bottom", "entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["hall", "closet"],
                    "initial_weight": 0.8,
                },
                "closet": {
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.8,
                },
            }
        }
    )


def restore_incident_closet_belief(
    engine: ZoneModelEngine,
    predictive_map: PredictiveMap,
    at: datetime,
) -> ZoneModelEngine:
    engine.advance(at)
    probability = 0.6424240878301262
    log_odds = math.log(probability / (1.0 - probability))
    snapshot = engine.snapshot
    belief_states = tuple(
        replace(state, log_odds=log_odds) if state.zone == "closet" else state
        for state in snapshot.belief_states
    )
    return ZoneModelEngine.restore(
        predictive_map,
        replace(snapshot, belief_states=belief_states),
        engine.audit_rows,
        at,
    )


def test_unauthorized_correlated_target_does_not_apply_arrival_transition() -> None:
    predictive_map = correlated_arrival_incident_map()
    first_at = datetime(2026, 8, 28, 15, 45, 6, 906293, tzinfo=UTC)
    engine = ZoneModelEngine(predictive_map, 2, first_at)
    engine.observe(SensorInput("binary_sensor.closet", "on", first_at, 0.8))
    cleared_at = datetime(2026, 8, 28, 15, 46, 48, 88053, tzinfo=UTC)
    engine.observe(SensorInput("binary_sensor.closet", "off", cleared_at, 0.8))
    engine.advance(cleared_at + timedelta(seconds=10))
    target_at = datetime(2026, 8, 28, 15, 48, 0, 349791, tzinfo=UTC)
    engine = restore_incident_closet_belief(engine, predictive_map, target_at)

    result = engine.observe(
        SensorInput("binary_sensor.closet", "on", target_at, 0.8)
    )

    episode = next(
        state
        for state in result.snapshot.episode_states
        if state.node_id == "closet"
    )
    belief = next(
        state for state in result.snapshot.belief_states if state.zone == "closet"
    )
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "closet"
    )
    authorization = next(
        item
        for item in result.authorizations
        if item.target_episode_id == episode.episode_id
    )
    assert episode.cadence_correlated
    assert not authorization.authorized
    assert not any(
        item.kind == "arrival_transition" and item.episode_id == episode.episode_id
        for item in belief.contributions
    )
    assert not policy.active
    assert result.policy_events == ()


def test_correlated_stay_holds_active_zone_until_stable_clear() -> None:
    engine = ZoneModelEngine(presence_target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=1))
    )
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=20))
    )
    engine.advance(NOW + timedelta(seconds=30))
    correlated = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=60))
    )

    policy = next(
        state for state in engine.snapshot.policy_states if state.zone == "room"
    )
    assert policy.active
    assert engine._asserted_stay_hold_zones() == frozenset({"room"})
    assert not any(event.kind == "refreshed" for event in correlated.policy_events)

    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=80))
    )
    assert engine._asserted_stay_hold_zones() == frozenset({"room"})

    engine.advance(NOW + timedelta(seconds=90))
    assert engine._asserted_stay_hold_zones() == frozenset()


def test_independent_source_authorizes_correlated_target_without_source_leak() -> None:
    engine = ZoneModelEngine(presence_target_map(), 1, NOW)
    first = engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    assert not next(
        state for state in first.snapshot.policy_states if state.zone == "room"
    ).active
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=20))
    )
    engine.advance(NOW + timedelta(seconds=30))
    engine.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=40))
    )
    correlated_at = NOW + timedelta(seconds=60)
    engine.advance(correlated_at)
    supports_before = engine.snapshot.anonymous_supports

    result = engine.observe(
        SensorInput("binary_sensor.room", "on", correlated_at)
    )

    room = next(
        state for state in result.snapshot.episode_states if state.node_id == "room"
    )
    authorization = next(
        item
        for item in result.authorizations
        if item.target_episode_id == room.episode_id
    )
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    )
    assert room.cadence_correlated
    assert authorization.authorized
    assert policy.active
    assert any(
        event.zone == "room" and event.kind == "acquired"
        for event in result.policy_events
    )
    assert all(
        token.episode_id != room.episode_id
        for token in result.snapshot.traversal_tokens
    )
    assert all(
        candidate.node_id != room.node_id
        for candidate in result.snapshot.pending_candidates
    )
    assert result.snapshot.anonymous_supports == supports_before
    assert engine.prediction_manager.leases == ()
    assert not any(event.kind == "refreshed" for event in result.policy_events)


def stale_transfer_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "independent_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.independent_entry"},
                    "adjacent": ["independent_transition"],
                },
                "independent_transition": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {
                        "motion": "binary_sensor.independent_transition"
                    },
                    "adjacent": ["independent_entry", "independent_stay"],
                },
                "independent_stay": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.independent_stay"},
                    "adjacent": ["independent_transition"],
                },
                "source": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": ["bridge"],
                },
                "bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.bridge"},
                    "adjacent": ["source", "retained", "second"],
                },
                "retained": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.retained"},
                    "adjacent": ["bridge"],
                },
                "second": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.second"},
                    "adjacent": ["bridge"],
                },
            }
        }
    )


def engine_before_stale_transfer(at: datetime) -> ZoneModelEngine:
    engine = ZoneModelEngine(stale_transfer_map(), 2, at)
    for entity_id, event_at in (
        ("binary_sensor.independent_entry", at + timedelta(microseconds=100000)),
        (
            "binary_sensor.independent_transition",
            at + timedelta(microseconds=200000),
        ),
        ("binary_sensor.independent_stay", at + timedelta(microseconds=300000)),
        ("binary_sensor.source", at + timedelta(seconds=1)),
        ("binary_sensor.bridge", at + timedelta(seconds=2)),
        ("binary_sensor.retained", at + timedelta(seconds=3)),
    ):
        engine.observe(SensorInput(entity_id, "on", event_at))
    return engine


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


def mixed_same_zone_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "room_presence": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.room"},
                },
                "room_interaction": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.room_scene_001",
                        "interaction_scene_002": "event.room_scene_002",
                    },
                },
            }
        }
    )


def multiple_same_zone_assertions_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "presence_a": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.presence_a"},
                },
                "presence_b": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.presence_b"},
                },
                "room_interaction": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.room_scene_001",
                        "interaction_scene_002": "event.room_scene_002",
                    },
                },
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


def test_stale_transfer_publication_failure_preserves_accepted_commit() -> None:
    engine = engine_before_stale_transfer(NOW)
    before = engine.diagnostic_counters["support_stale_binding_ignored"]

    def fail(_event: object, _decision: object, _authorization: object) -> None:
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        engine.observe(
            SensorInput("binary_sensor.second", "on", NOW + timedelta(seconds=4)),
            decision_callback=fail,
        )

    assert engine.snapshot.updated_at == NOW + timedelta(seconds=4)
    assert engine.diagnostic_counters["support_stale_binding_ignored"] == before + 1
    assert {support.current_zone for support in engine.snapshot.anonymous_supports} == {
        "independent_stay",
        "retained",
    }
    assert next(
        policy for policy in engine.snapshot.policy_states if policy.zone == "second"
    ).active
    assert any(
        row.zone == "second"
        and row.reason == "acquired"
        and row.event_at == NOW + timedelta(seconds=4)
        for row in engine.audit_rows
    )


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


def test_interaction_health_preserves_distinct_same_zone_assertion() -> None:
    engine = ZoneModelEngine(mixed_same_zone_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(
        SensorInput("event.room_scene_001", "pressed", NOW + timedelta(seconds=1))
    )
    before = engine.snapshot
    presence = next(
        state for state in before.episode_states if state.node_id == "room_presence"
    )
    belief_before = before.belief_states[0]

    result = engine.observe(
        SensorInput("event.room_scene_002", "unknown", NOW + timedelta(seconds=2))
    )

    belief_after = result.snapshot.belief_states[0]
    assert presence.episode_id is not None
    assert belief_after.context == "asserted"
    assert belief_after.generation_episode_id == presence.episode_id
    assert belief_after.asserted_episode_id == presence.episode_id
    assert belief_after.log_odds < belief_before.log_odds
    assert belief_after.contributions[:-1] == belief_before.contributions
    assert belief_after.contributions[-1].kind == "elapsed_decay"
    assert result.snapshot.traversal_tokens == ()
    assert result.snapshot.retained_traversal_tokens == ()
    assert result.snapshot.anonymous_supports == ()
    assert result.policy_events == ()
    assert result.snapshot.policy_states[0].active

    clearing = engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3))
    )
    presence_clearing = next(
        state
        for state in clearing.snapshot.episode_states
        if state.node_id == "room_presence"
    )
    assert presence_clearing.clear_deadline is not None
    cleared = engine.advance(presence_clearing.clear_deadline)
    assert cleared.snapshot.belief_states[0].context == "cleared_without_outward"
    assert [
        item.kind for item in cleared.snapshot.belief_states[0].contributions
    ].count("stable_clear") == 1


def test_bootstrap_neutral_interaction_preserves_same_zone_assertion() -> None:
    engine = ZoneModelEngine(mixed_same_zone_map(), 1, NOW)

    snapshot = engine.bootstrap_sensor_snapshot(
        (
            SensorInput("binary_sensor.room", "on", NOW),
            SensorInput("event.room_scene_001", "unknown", NOW),
            SensorInput("event.room_scene_002", "unknown", NOW),
        ),
        NOW,
    )

    presence = next(
        state
        for state in snapshot.episode_states
        if state.node_id == "room_presence"
    )
    assert presence.episode_id is not None
    assert snapshot.belief_states[0].context == "asserted"
    assert snapshot.belief_states[0].asserted_episode_id == presence.episode_id
    assert not snapshot.policy_states[0].active


@pytest.mark.parametrize(
    "entity_order",
    (
        ("binary_sensor.presence_a", "binary_sensor.presence_b"),
        ("binary_sensor.presence_b", "binary_sensor.presence_a"),
    ),
)
def test_same_zone_assertion_selection_is_deterministic(
    entity_order: tuple[str, str],
) -> None:
    engine = ZoneModelEngine(multiple_same_zone_assertions_map(), 1, NOW)
    for entity_id in entity_order:
        engine.observe(SensorInput(entity_id, "on", NOW))
    engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))

    result = engine.observe(
        SensorInput("event.room_scene_002", "unknown", NOW + timedelta(seconds=1))
    )

    selected = next(
        state
        for state in result.snapshot.episode_states
        if state.node_id == "presence_b"
    )
    assert selected.episode_id is not None
    assert result.snapshot.belief_states[0].asserted_episode_id == selected.episode_id


def test_restore_reconciliation_requires_matching_current_on_assertion() -> None:
    engine = ZoneModelEngine(mixed_same_zone_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    presence = next(
        state
        for state in engine.snapshot.episode_states
        if state.node_id == "room_presence"
    )
    engine._filters["room"].apply_unavailable(NOW)  # noqa: SLF001

    unmatched = engine.reconcile_restored_asserted_contexts((), NOW)
    reconciled = engine.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )

    assert unmatched.belief_states[0].context == "unavailable"
    assert presence.episode_id is not None
    assert reconciled.belief_states[0].context == "asserted"
    assert reconciled.belief_states[0].generation_episode_id == presence.episode_id
    assert reconciled.belief_states[0].asserted_episode_id == presence.episode_id
    assert not reconciled.policy_states[0].active


def test_restore_reconciliation_validates_frontier_and_no_op_boundaries() -> None:
    engine = ZoneModelEngine(mixed_same_zone_map(), 1, NOW)
    later = NOW + timedelta(seconds=1)

    with pytest.raises(ValueError, match="share one frontier"):
        engine.reconcile_restored_asserted_contexts(
            (SensorInput("binary_sensor.room", "on", NOW),),
            later,
        )

    unmatched = engine.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", later),),
        later,
    )
    assert unmatched.updated_at == later
    assert unmatched.belief_states[0].context == "cleared_without_outward"

    empty = ZoneModelEngine(mixed_same_zone_map(), 0, NOW)
    unchanged = empty.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )
    assert unchanged == empty.snapshot


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
