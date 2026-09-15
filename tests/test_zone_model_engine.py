"""Engine qualification: selected PATH/HEALTH plus explicit legacy components.

Original IDs/inputs are mapped before edits in completion-engine-endpoint-mapping.
Standalone component checks are not claims of current engine token authority.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
    ZoneModelSnapshot,
)
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
)
from tests.handoff_lifecycle_fixture import (
    commit_component_arrival,
    component_arrival,
    prepare_component_arrival,
    publish_component_arrival,
)
from tests.persistence_component_fixture import PersistenceComponents
from tests.runtime_replay import ActiveEdge, RuntimeScenario

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
    # PATH001/STATE: a count0-era physical clear has no belief to depart from.
    engine = ZoneModelEngine(same_zone_presence_map(), 1, NOW)
    source, effect = cleared_source(engine, "first")
    before = engine.snapshot

    engine._register_confirmed_departure(source, effect)  # noqa: SLF001

    assert engine.snapshot == before
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
    # BELIEF010/PATH001: physical pulses own generations, not legacy supports.
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
    episodes = {state.node_id: state for state in engine.snapshot.episode_states}
    selected, = engine.snapshot.selected_paths
    assert selected is not None and selected.endpoint.node_id == "switch_b"
    assert selected.endpoint.kind == "interaction"
    assert selected.endpoint.episode_id == episodes["switch_b"].episode_id
    assert engine.snapshot.anonymous_supports == ()
    assert engine.snapshot.traversal_tokens == ()
    assert engine.snapshot.belief_states[0].log_odds == 30.0
    first_clear = episodes["switch_a"].clear_deadline
    second_clear = episodes["switch_b"].clear_deadline
    assert first_clear is not None and second_clear is not None
    assert first_clear < second_clear

    after_first_clear = engine.advance(first_clear)
    belief = next(
        state
        for state in after_first_clear.snapshot.belief_states
        if state.zone == "room"
    )
    assert belief.context == "asserted"
    assert belief.generation_episode_id == episodes["switch_b"].episode_id
    assert after_first_clear.snapshot.policy_states[0].active

    after_second_clear = engine.advance(second_clear)
    belief = next(
        state
        for state in after_second_clear.snapshot.belief_states
        if state.zone == "room"
    )
    assert belief.context == "cleared_without_outward"
    assert belief.generation_episode_id == episodes["switch_b"].episode_id
    assert after_second_clear.snapshot.policy_states[0].active


def test_interaction_count_two_acquires_without_conflict_delay() -> None:
    # BELIEF010/EVID011: conclusive physical evidence assigns only one of two slots.
    engine = ZoneModelEngine(interaction_map(), 2, NOW)

    result = engine.observe(
        SensorInput("event.room_scene_001", "pressed", NOW + timedelta(seconds=1))
    )

    authorization = result.authorizations[0]
    policy = next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    )
    assert authorization.authorized
    assert authorization.reason == "selected_path"
    assert authorization.provenance_kind == "selected_path"
    assert not authorization.equivalent_confirmed_strength
    selected, unlocated = result.snapshot.selected_paths
    assert selected is not None and unlocated is None
    assert selected.endpoint.kind == "interaction"
    assert selected.endpoint.episode_id == result.snapshot.episode_states[0].episode_id
    assert result.snapshot.belief_states[0].log_odds == 30.0
    assert math.isfinite(result.snapshot.belief_states[0].log_odds)
    assert result.snapshot.anonymous_supports == ()
    assert result.snapshot.traversal_tokens == ()
    assert result.snapshot.count_conflicts == ()
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
    # I/O: both the throwing callback frontier and the final wire state are strict.
    engine = ZoneModelEngine(interaction_map(), 1, NOW)
    event_at = NOW + timedelta(seconds=1)
    published: list[ZoneModelSnapshot] = []

    def fail(_event: object, _decision: object, _authorization: object) -> None:
        published.append(engine.snapshot)
        assert engine.snapshot.updated_at == event_at
        assert engine.snapshot.policy_states[0].active
        _assert_current_round_trip(interaction_map(), engine)
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        engine.observe(
            SensorInput("event.room_scene_001", "pressed", event_at),
            decision_callback=fail,
        )

    policy = engine.snapshot.policy_states[0]
    assert engine.snapshot.updated_at == event_at
    assert policy.active
    assert published == [engine.snapshot]
    assert engine.snapshot.traversal_tokens == ()
    assert engine.snapshot.anonymous_supports == ()
    selected, = engine.snapshot.selected_paths
    assert selected is not None and selected.endpoint.kind == "interaction"
    assert engine.snapshot.belief_states[0].log_odds == 30.0
    assert engine.audit_rows[-1].local_evidence_kind == "interaction"
    assert engine.audit_rows[-1].traversal_reason == "selected_path"
    _assert_current_round_trip(interaction_map(), engine)


def test_stale_transfer_publication_failure_preserves_accepted_commit() -> None:
    # L/O: retain real stale binding rejection/counter, not a selected-path alias.
    engine = _components_before_stale_transfer(NOW)
    before = engine.diagnostic_counters["support_stale_binding_ignored"]
    before_supports = engine.snapshot.anonymous_supports
    published: list[str] = []

    def fail(_event: object, _decision: object, _authorization: object) -> None:
        assert engine.diagnostic_counters["support_stale_binding_ignored"] == before
        assert engine.snapshot.anonymous_supports == before_supports
        published.append("publication")
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        component_arrival(
            engine,
            SensorInput("binary_sensor.second", "on", NOW + timedelta(seconds=4)),
            decision_callback=fail,
        )

    assert published == ["publication"]
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
    validator = SnapshotValidator(
        engine.predictive_map, engine.nodes, engine.supports._confirmed_strength,
    )
    validator.validate_support_snapshot(
        engine.snapshot, *validator.validate_tokens(engine.snapshot),
    )


def test_interaction_health_invalidates_token_and_support_without_release() -> None:
    # I: current physical authority is revoked; historical tokens are separate below.
    engine = ZoneModelEngine(interaction_map(), 1, NOW)
    acquired = engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    selected, = acquired.snapshot.selected_paths
    assert selected is not None and selected.endpoint_eligible
    assert selected.endpoint.branch_active
    assert acquired.snapshot.belief_states[0].log_odds == 30.0
    assert acquired.snapshot.policy_states[0].active

    unavailable = engine.observe(
        SensorInput("event.room_scene_002", "unknown", NOW + timedelta(seconds=1))
    )

    assert unavailable.disposition == "neutral_availability"
    assert unavailable.snapshot.episode_states[0].status == "unavailable"
    assert unavailable.snapshot.belief_states[0].context == "unavailable"
    assert unavailable.snapshot.traversal_tokens == ()
    assert unavailable.snapshot.retained_traversal_tokens == ()
    assert unavailable.snapshot.anonymous_supports == ()
    withdrawn, = unavailable.snapshot.selected_paths
    assert withdrawn is not None and not withdrawn.endpoint_eligible
    assert not withdrawn.endpoint.branch_active
    assert withdrawn.endpoint.episode_id == selected.endpoint.episode_id
    assert unavailable.snapshot.policy_states[0].active
    assert not any(event.kind == "released" for event in unavailable.policy_events)
    _assert_current_round_trip(interaction_map(), engine)


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
    # B: independent restored branches; an empty COMPLETE snapshot withdraws ON.
    engine = ZoneModelEngine(mixed_same_zone_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    presence = next(
        state
        for state in engine.snapshot.episode_states
        if state.node_id == "room_presence"
    )
    engine._filters["room"].apply_unavailable(NOW)  # noqa: SLF001
    snapshot = engine.snapshot
    matching = ZoneModelEngine.restore(
        mixed_same_zone_map(), snapshot, engine.audit_rows, NOW,
    )

    unmatched = engine.reconcile_restored_asserted_contexts((), NOW)
    reconciled = matching.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )

    assert unmatched.belief_states[0].context == "unavailable"
    assert presence.episode_id is not None
    assert reconciled.belief_states[0].context == "asserted"
    assert reconciled.belief_states[0].generation_episode_id == presence.episode_id
    assert reconciled.belief_states[0].asserted_episode_id == presence.episode_id
    assert not reconciled.policy_states[0].active
    assert snapshot.belief_states[0].context == "unavailable"
    new_on = engine.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", NOW),), NOW,
    )
    replaced = next(
        state for state in new_on.episode_states if state.node_id == "room_presence"
    )
    assert replaced.generation == presence.generation + 1
    assert replaced.episode_id != presence.episode_id
    assert new_on.belief_states[0].asserted_episode_id == replaced.episode_id
    assert new_on.selected_paths == reconciled.selected_paths == (None,)
    assert not new_on.policy_states[0].active
    _assert_current_round_trip(mixed_same_zone_map(), matching)
    _assert_current_round_trip(mixed_same_zone_map(), engine)


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
    # New startup ON installs a physical baseline, never a selected live origin.
    assert unmatched.belief_states[0].context == "asserted"
    assert unmatched.selected_paths == (None,)
    assert not unmatched.policy_states[0].active
    assert unmatched.traversal_tokens == ()
    assert unmatched.pending_candidates == ()
    matching = engine.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", later),), later,
    )
    assert matching == unmatched

    empty = ZoneModelEngine(mixed_same_zone_map(), 0, NOW)
    unchanged = empty.reconcile_restored_asserted_contexts(
        (SensorInput("binary_sensor.room", "on", NOW),),
        NOW,
    )
    assert unchanged == empty.snapshot
    assert unchanged.selected_paths == ()
    assert unchanged.belief_states[0].generation_episode_id is None
    assert unchanged.belief_states[0].probability == pytest.approx(0.05)
    assert not unchanged.policy_states[0].active


def test_engine_composes_transition_authorization_and_policy_acquisition() -> None:
    # S/PATH003: ordinary live pair, no token-seeded engine authority.
    engine = ZoneModelEngine(target_map(), 1, NOW)

    hall = engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    room_at = NOW + timedelta(seconds=2)
    room = engine.observe(SensorInput("binary_sensor.room", "on", room_at))

    assert hall.policy_events == ()
    assert room.authorizations[0].reason == "selected_path"
    assert room.authorizations[0].track_confidence == "provisional"
    assert room.authorizations[0].path_node_ids == ("hall", "room")
    assert room.snapshot.traversal_tokens == ()
    assert room.snapshot.anonymous_supports == ()
    assert [(event.zone, event.kind) for event in room.policy_events] == [
        ("room", "acquired")
    ]
    assert {state.zone: state.active for state in room.snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }


def test_incident_correlated_hallway_reassertion_preserves_authorized_path() -> None:
    # L/TRAV: original token45/trust60 and every microsecond remain component facts.
    engine = PersistenceComponents(correlated_continuity_map(), 2, NOW)
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

    # Explicitly compose the real continuity and policy APIs: the generic fixture
    # does not relabel a successful reopen as an engine policy effect.
    engine.advance(reasserted_at, emit_events=False)
    reasserted = engine.episodes.observe(
        SensorInput("binary_sensor.top", "on", reasserted_at)
    )
    effect, = reasserted.effects
    assert effect.kind == "correlated_flap_ignored"
    assert engine.frontier.reopen_authorized_continuity(reasserted.state, effect)
    engine.filters["top"].supersede_outward(effect.episode_id, effect.at)
    belief = engine.filters["top"].state
    top_policy = engine.policies["top"].evaluate(
        reasserted_at, belief, belief, local_state=reasserted.state,
        local_effect=replace(effect, kind="correlated_continuity_authorized"),
        authorization=None,
    )
    top_decision = top_policy.decision
    assert reasserted.disposition == "correlated_reassertion"
    assert top_policy.event is None
    assert top_decision.reason == "correlated_continuity_authorized"
    assert top_decision.local_evidence_kind == "correlated_continuity_authorized"
    assert top_decision.belief_before == top_decision.belief_after
    reopened = next(
        token
        for token in engine.snapshot.traversal_tokens
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
    # O/L: true legacy count work after callback, not a current no-op spy.
    engine = PersistenceComponents(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    order: list[str] = []
    original = cast(Any, engine.conflicts.evaluate)

    def count_work(*args: Any, **kwargs: Any) -> Any:
        order.append("whole_house_count")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine.conflicts, "evaluate", count_work)

    component_arrival(
        engine,
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
    audit_before = engine.audit_rows
    candidate, = (
        item for item in engine.snapshot.pending_candidates if item.zone == "isolated"
    )
    assert candidate.expires_at == NOW + timedelta(seconds=90)
    original = cast(Any, engine._policies["isolated"].record_pending_expiry)  # noqa: SLF001

    def pending_expiry(*args: Any, **kwargs: Any) -> Any:
        order.append("pending_expiry_prepared")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engine._policies["isolated"],  # noqa: SLF001
        "record_pending_expiry",
        pending_expiry,
    )
    audit = engine._policies["isolated"].audit
    encode = audit.encoded_size

    def materialize(row: PolicyDecision) -> int:
        if row.reason == "untracked_expired":
            order.append("pending_expiry_materialized")
        return encode(row)

    monkeypatch.setattr(audit, "encoded_size", materialize)
    committed: list[ZoneModelResult] = []

    def publish(*_args: object) -> None:
        order.append("publication")
        assert engine.audit_rows == audit_before
        assert engine.snapshot.updated_at == candidate.expires_at
        assert all(
            item.episode_id != candidate.episode_id
            for item in engine.snapshot.pending_candidates
        )
        _assert_current_round_trip(predictive_map, engine)

    result = engine.observe(
        SensorInput("binary_sensor.d", "on", NOW + timedelta(seconds=90)),
        result_callback=committed.append,
        decision_callback=publish,
    )

    authorization = result.authorizations[-1]
    assert authorization.reason == "selected_path"
    assert authorization.track_confidence == "confirmed"
    assert committed == [result]
    expiry, = (
        row for row in result.policy_decisions if row.reason == "untracked_expired"
    )
    assert expiry.episode_id == candidate.episode_id
    assert expiry.event_at == candidate.expires_at
    assert expiry in engine.audit_rows
    assert next(
        state for state in result.snapshot.policy_states if state.zone == "d"
    ).active
    # Committed deadline metadata is preparation, actual JSON encoding is deferred.
    assert order == [
        "pending_expiry_prepared", "publication", "pending_expiry_materialized",
    ]


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
    # HEALTH003 supersedes engine age degradation, retaining the original20min.
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
    assert not episodes["hall"].health_warning
    assert not episodes["room"].health_warning
    assert episodes["hall"].status == episodes["room"].status == "asserted"
    assert direct.snapshot.reliability_warning_occurrences == ()
    selected, = direct.snapshot.selected_paths
    assert selected is not None and selected.endpoint.node_id == "room"
    assert selected.updated_at == room_at
    _assert_current_round_trip(target_map(), engine)


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


def test_isolated_correlated_positive_remains_inactive() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "isolated": {
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.isolated"},
                }
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.isolated", "on", NOW))
    clear_at = NOW + timedelta(seconds=10)
    stable_clear_at = clear_at + timedelta(seconds=10)
    engine.observe(SensorInput("binary_sensor.isolated", "off", clear_at))
    engine.advance(stable_clear_at)
    pending_before = engine.snapshot.pending_candidates

    correlated = engine.observe(
        SensorInput(
            "binary_sensor.isolated",
            "on",
            stable_clear_at + timedelta(seconds=10),
        )
    )

    assert correlated.disposition == "accepted_correlated_positive"
    assert correlated.authorizations[0].reason == "untracked_rejected"
    assert not correlated.snapshot.policy_states[0].active
    assert correlated.snapshot.pending_candidates == pending_before
    assert correlated.snapshot.traversal_tokens == ()


def test_pending_adjacent_pair_activates_only_leading_zone() -> None:
    # S: one physical pair creates one provisional selected slot, not two tokens.
    engine = ZoneModelEngine(target_map(), 1, NOW)

    first = engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    second = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2))
    )

    assert first.policy_events == ()
    assert second.authorizations[0].reason == "selected_path"
    states = {state.zone: state.active for state in second.snapshot.policy_states}
    assert states == {"hall": False, "room": True}
    selected, = second.snapshot.selected_paths
    assert selected is not None
    assert selected.track_confidence == "provisional"
    assert tuple(visit.node_id for visit in selected.visits) == ("hall", "room")
    assert tuple(visit.at for visit in selected.visits) == (
        NOW, NOW + timedelta(seconds=2),
    )
    assert selected.endpoint.node_id == "room"
    assert second.snapshot.traversal_tokens == ()
    assert second.snapshot.anonymous_supports == ()


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

    # S: the same third distinct observation confirms the single selected slot.
    assert result.authorizations[0].reason == "selected_path"
    target, = result.snapshot.selected_paths
    assert target is not None
    assert target.track_confidence == "confirmed"
    assert tuple(visit.node_id for visit in target.visits) == ("a", "b", "c")
    assert target.endpoint.node_id == "c"
    assert result.snapshot.traversal_tokens == ()
    assert result.snapshot.anonymous_supports == ()
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("c", "acquired"),
    ]


def test_two_node_backtracking_remains_provisional() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    engine.observe(SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3)))
    engine.advance(NOW + timedelta(seconds=8))

    result = engine.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=20))
    )

    # S: three visits to only two distinct nodes cannot become confirmed.
    target, = result.snapshot.selected_paths
    assert target is not None and target.endpoint.node_id == "hall"
    assert target.track_confidence == "provisional"
    assert tuple(visit.node_id for visit in target.visits) == ("hall", "room", "hall")
    assert len({visit.node_id for visit in target.visits}) == 2
    assert target.visits[0].episode_id != target.endpoint.episode_id
    assert not target.visits[0].branch_active
    assert result.snapshot.traversal_tokens == ()


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
    # HEALTH002: correlation rejection remains, but a two-second flap is not six
    # completed quick cycles. The old early warning is qualified separately.
    assert any(
        decision.reason == "correlated_flap_ignored"
        for decision in flap.policy_decisions
    )
    assert flap.snapshot.traversal_tokens == ()
    assert flap.snapshot.selected_paths == (None,)
    assert flap.snapshot.reliability_warning_occurrences == ()
    assert all(not state.active for state in flap.snapshot.policy_states)


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
    # S/STATE: strict selected identity and silent later-frontier continuation.
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
    assert restored.snapshot.selected_paths == snapshot.selected_paths
    selected, = snapshot.selected_paths
    assert selected is not None and selected.endpoint.node_id == "room"
    assert restored.snapshot.current_token_ids == ()
    assert restored.snapshot.anonymous_supports == ()
    assert engine.snapshot == snapshot
    control = engine.advance(room_at + timedelta(seconds=1), emit_events=False)
    assert restored.snapshot == control.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert all(not policy.bootstrap_events for policy in restored._policies.values())
    event = SensorInput("binary_sensor.room", "off", room_at + timedelta(seconds=2))
    assert restored.observe(event) == engine.observe(event)
    _assert_current_round_trip(target_map(), restored)


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


def _assert_current_round_trip(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> None:
    """Strict writer/reader, independent prediction and input immutability."""
    payload = serialize_target_state(predictive_map, engine)
    original = deepcopy(payload)
    snapshot = engine.snapshot
    restored = restore_target_state(predictive_map, payload, snapshot.updated_at)
    assert restored.snapshot == snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, restored) == original == payload


def _components_before_stale_transfer(at: datetime) -> PersistenceComponents:
    """Same original stream; deliberately NOT the shared selected-engine helper."""
    components = PersistenceComponents(stale_transfer_map(), 2, at)
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
        components.observe(SensorInput(entity_id, "on", event_at))
    return components


def test_selected_stale_branch_callback_commits_strict_snapshot_on_failure() -> None:
    """PATH001/O: same legacy stream, but selected movement is not support transfer."""
    engine = engine_before_stale_transfer(NOW)
    before = engine.diagnostic_counters.copy()
    snapshots: list[ZoneModelSnapshot] = []
    event_at = NOW + timedelta(seconds=4)

    def publish(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "second" and event.kind == "acquired"
        assert decision.active_after
        assert authorization is not None and authorization.reason == "selected_path"
        snapshots.append(engine.snapshot)
        assert engine.snapshot.updated_at == event_at
        assert {path.endpoint.node_id for path in engine.snapshot.selected_paths
                if path is not None} == {"independent_stay", "second"}
        assert engine.snapshot.anonymous_supports == ()
        _assert_current_round_trip(stale_transfer_map(), engine)
        raise RuntimeError("publication failed")

    with pytest.raises(RuntimeError, match="publication failed"):
        engine.observe(
            SensorInput("binary_sensor.second", "on", event_at),
            decision_callback=publish,
        )
    assert snapshots == [engine.snapshot]
    assert engine.diagnostic_counters == before
    assert any(row.zone == "second" and row.reason == "acquired"
               and row.event_at == event_at for row in engine.audit_rows)
    _assert_current_round_trip(stale_transfer_map(), engine)
    follow_up = SensorInput(
        "binary_sensor.second", "off", event_at + timedelta(seconds=1),
    )
    restored = restore_target_state(
        stale_transfer_map(), serialize_target_state(stale_transfer_map(), engine),
        event_at,
    )
    assert restored.observe(follow_up) == engine.observe(follow_up)


def test_legacy_interaction_availability_invalidates_actual_token_and_support() -> None:
    """L/EVID011: historical support removal still has a real nonempty premise."""
    components = PersistenceComponents(interaction_map(), 1, NOW)
    acquired = components.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    token, = acquired.snapshot.traversal_tokens
    support, = acquired.snapshot.anonymous_supports
    assert token.provenance_kind == support.provenance_kind == "local_interaction"
    assert acquired.snapshot.policy_states[0].active
    result = components.observe(
        SensorInput("event.room_scene_002", "unknown", NOW + timedelta(seconds=1))
    )
    assert result.disposition == "neutral_availability"
    assert result.snapshot.episode_states[0].status == "unavailable"
    assert result.snapshot.belief_states[0].context == "unavailable"
    assert result.snapshot.traversal_tokens == ()
    assert result.snapshot.retained_traversal_tokens == ()
    assert result.snapshot.anonymous_supports == ()
    assert result.snapshot.policy_states[0].active
    assert not any(event.kind == "released" for event in result.policy_events)


def test_legacy_transition_age_degrades_but_held_room_remains_active() -> None:
    """L/old EVID005: preserve20min and actual assertion-timeout calibration."""
    components = PersistenceComponents(target_map(), 1, NOW)
    components.observe(SensorInput("binary_sensor.hall", "on", NOW))
    components.observe(SensorInput(
        "binary_sensor.room", "on", NOW + timedelta(seconds=2),
    ))
    result = components.advance(NOW + timedelta(minutes=20))
    episodes = {state.node_id: state for state in result.snapshot.episode_states}
    assert episodes["hall"].health_warning and episodes["hall"].status == "degraded"
    assert not episodes["room"].health_warning
    assert next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    ).active
    assert not any(event.zone == "room" and event.kind == "released"
                   for event in result.policy_events)
    warning, = result.snapshot.reliability_warning_occurrences
    assert warning.node_id == "hall" and warning.reason == "assertion_timeout"
    assert warning.first_observed_at == NOW + timedelta(seconds=60)


def test_legacy_same_node_flap_retains_early_cadence_component_warning() -> None:
    """L: old0/1/2 early warning is not the selected engine's sixth-cycle diagnosis."""
    components = PersistenceComponents(target_map(), 1, NOW)
    first = components.observe(SensorInput("binary_sensor.room", "on", NOW))
    components.observe(SensorInput(
        "binary_sensor.room", "off", NOW + timedelta(seconds=1),
    ))
    flap = components.observe(SensorInput(
        "binary_sensor.room", "on", NOW + timedelta(seconds=2),
    ))
    assert first.policy_events == flap.policy_events == ()
    assert flap.disposition == "correlated_reassertion"
    assert any(row.reason == "impossible_cadence" for row in flap.policy_decisions)
    assert flap.snapshot.traversal_tokens == ()
    warning, = flap.snapshot.reliability_warning_occurrences
    assert warning.reason == "impossible_cadence" and warning.node_id == "room"
    assert warning.first_observed_at == NOW + timedelta(seconds=2)


def test_component_confirmed_arrival_defers_real_learning_until_after_publication(
) -> None:
    """O/PRED007: nonempty real confirmed-route work, not an empty-queue order spy.

This component guarantee does not waive the separately retained current-engine
predrain red in test_zone_model_handoff (actual restored fallback continuation).
"""
    components = PersistenceComponents(correlated_continuity_map(), 1, NOW)
    components.observe(SensorInput("binary_sensor.bottom", "on", NOW))
    components.observe(SensorInput(
        "binary_sensor.top", "on", NOW + timedelta(seconds=1),
    ))
    prepared = prepare_component_arrival(
        components, SensorInput(
            "binary_sensor.bathroom", "on", NOW + timedelta(seconds=2),
        ),
    )
    assert prepared.authorization.authorized
    assert prepared.authorization.track_confidence == "confirmed"
    assert prepared.authorization.provenance_kind == "adjacent"
    assert prepared.support.transition.supports
    old_supports = components.snapshot.anonymous_supports
    before = deepcopy(components.prediction_manager.chain.counts)
    published: list[str] = []

    def publish(*_args: object) -> None:
        published.append("publication")
        assert components.snapshot.anonymous_supports == old_supports
        assert not components.learning
        assert components.prediction_manager.chain.counts == before

    _decisions, events, failure = publish_component_arrival(
        components, prepared, publish,
    )
    assert failure is None
    assert published == ["publication"]
    assert [(event.zone, event.kind) for event in events] == [("bathroom", "acquired")]
    commit_component_arrival(components, prepared)
    assert components.learning == [prepared.authorization]
    assert components.prediction_manager.chain.counts == before
    assert components.snapshot.anonymous_supports != old_supports
    components.commit_prediction_learning()
    assert not components.learning
    assert components.prediction_manager.chain.counts["top"]["bathroom"] == 1
    assert components.prediction_manager.chain.counts != before


@pytest.mark.parametrize("count", (1, 2))
def test_selected_pair_publication_is_leading_only_and_one_slot(count: int) -> None:
    """PATH001/003/004: actual registered runtime writes, not private policy aliases."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), count)
        replay.send("binary_sensor.hall", "on", NOW)
        at = NOW + timedelta(seconds=2)
        assert replay.send("binary_sensor.room", "on", at).active("room")
        assert replay.edges_for("hall") == ()
        assert replay.edges_for("room") == (ActiveEdge(at, "room", True),)
        snapshot = replay.inference_snapshot()
        paths = tuple(path for path in snapshot.selected_paths if path is not None)
        assert len(paths) == 1 and len(snapshot.selected_paths) == count
        assert paths[0].track_confidence == "provisional"
        assert paths[0].endpoint.node_id == "room"
        assert snapshot.traversal_tokens == ()
        assert snapshot.anonymous_supports == ()


def test_selected_correlated_hallway_continuity_uses_original_microseconds() -> None:
    """PATH003 public counterpart of the historical token45/trust60 component case."""
    bottom_at = NOW
    top_at = NOW + timedelta(seconds=7, microseconds=93785)
    top_off_at = top_at + timedelta(seconds=43, microseconds=488547)
    token_expiry = top_at + timedelta(seconds=45)
    reasserted_at = top_off_at + timedelta(seconds=2, microseconds=200084)
    bathroom_at = reasserted_at + timedelta(seconds=6, microseconds=712904)
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(correlated_continuity_map(), 2)
        replay.send("binary_sensor.bottom", "on", bottom_at)
        replay.send("binary_sensor.top", "on", top_at)
        replay.send(
            "binary_sensor.bottom", "off",
            bottom_at + timedelta(seconds=21, microseconds=339468),
        )
        replay.send("binary_sensor.top", "off", top_off_at)
        replay.advance(token_expiry + timedelta(milliseconds=50))
        before = replay.inference_snapshot()
        path, unlocated = before.selected_paths
        assert path is not None and unlocated is None
        assert path.endpoint.node_id == "top"
        assert before.traversal_tokens == before.retained_traversal_tokens == ()
        assert replay.send("binary_sensor.top", "on", reasserted_at).active("top")
        assert replay.send("binary_sensor.bathroom", "on", bathroom_at).active(
            "bathroom",
        )
        assert replay.edges_for("bottom") == ()
        assert replay.edges_for("top") == (ActiveEdge(top_at, "top", True),)
        assert replay.input_edges_for("bathroom") == (
            ActiveEdge(bathroom_at, "bathroom", True),
        )
        final, unlocated = replay.inference_snapshot().selected_paths
        assert final is not None and unlocated is None
        assert final.track_confidence == "confirmed"
        assert tuple(visit.node_id for visit in final.visits) == (
            "bottom", "top", "bathroom",
        )


@pytest.mark.parametrize("count", (0, 1, 2))
def test_interaction_public_immediacy_obeys_categorical_count(count: int) -> None:
    """EVID011/PATH001: public local pulse needs no support; count0 still vetoes it."""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(interaction_map(), count)
        at = NOW + timedelta(seconds=1)
        result = replay.observe(SensorInput("event.room_scene_001", "pressed", at))
        assert result.active("room") is (count > 0)
        assert replay.input_edges_for("room") == (
            (ActiveEdge(at, "room", True),) if count else ()
        )
        snapshot = replay.inference_snapshot()
        assert len(snapshot.selected_paths) == count
        assert sum(path is not None for path in snapshot.selected_paths) == min(
            1, count,
        )
        assert snapshot.traversal_tokens == ()
        assert snapshot.anonymous_supports == ()
        assert snapshot.belief_states[0].log_odds == (
            30.0 if count else pytest.approx(math.log(0.05 / 0.95))
        )


def test_runtime_supported_edge_precedes_real_persistence_materialization() -> None:
    """PERF001/004: actual runtime schedules a nonempty strict payload after ON.

The storage double only owns HA's delayed-save boundary; it does not model an
engine, bypass validation, or substitute a marker for actual serialization.
"""
    with RuntimeScenario(NOW) as scenario:
        replay = scenario.create(target_map(), 1)
        replay.send("binary_sensor.hall", "on", NOW)
        # Import after the real runtime adapters have been installed by the replay.
        from custom_components.predictive_controls import occupancy_tracker

        at = NOW + timedelta(seconds=2)
        saved: list[dict[str, object]] = []
        schedules: list[tuple[datetime, bool]] = []
        serialization_frontiers: list[datetime] = []
        serialize: Callable[[PredictiveMap, ZoneModelEngine], dict[str, object]] = (
            serialize_target_state
        )
        installed_serializer: object = vars(occupancy_tracker)["serialize_target_state"]
        assert installed_serializer is serialize

        def observe_serialization(
            predictive_map: PredictiveMap, engine: ZoneModelEngine,
        ) -> dict[str, object]:
            # Observe the actual production call site, not merely our Store double.
            # An extra prepublication serialization must fail even if later saves
            # still have the correct timing and an otherwise valid payload.
            assert replay.input_edges_for("room") == (ActiveEdge(at, "room", True),)
            serialization_frontiers.append(scenario.clock.now)
            return serialize(predictive_map, engine)

        scenario.patch.setattr(
            occupancy_tracker, "serialize_target_state", observe_serialization,
        )

        def delay_save(factory: Callable[[], dict[str, object]], delay: float) -> None:
            schedules.append((scenario.clock.now, replay.view().active("room")))
            scenario.clock.schedule(
                timedelta(seconds=delay), lambda _at: saved.append(factory()),
            )

        async def save(payload: dict[str, object]) -> None:
            saved.append(payload)

        scenario.patch.setattr(replay.runtime, "_transition_store", SimpleNamespace(
            async_delay_save=delay_save, async_save=save,
        ))
        replay.send("binary_sensor.room", "on", at)
        assert replay.input_edges_for("room") == (ActiveEdge(at, "room", True),)
        assert schedules == [(at, True)]
        assert saved == []
        assert serialization_frontiers == []
        replay.advance(at + timedelta(seconds=1))
        assert serialization_frontiers == [at + timedelta(seconds=1)]
        payload, = saved
        original = deepcopy(payload)
        restored = restore_target_state(target_map(), payload, at)
        assert serialize_target_state(target_map(), restored) == original == payload
        assert any(row.zone == "room" and row.reason == "acquired"
                   for row in restored.audit_rows)
        assert restored.snapshot.anonymous_supports == ()
