import math
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


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


@pytest.mark.target_model
def test_inc_2026_08_28_1545z_authorized_correlated_closet_acquires_before_sleep_off(
) -> None:
    predictive_map = correlated_arrival_incident_map()
    engine = ZoneModelEngine(
        predictive_map,
        2,
        datetime(2026, 8, 28, 15, 45, 6, 906293, tzinfo=UTC),
    )
    for entity_id, state, event_at, reliability in (
        (
            "binary_sensor.closet",
            "on",
            datetime(2026, 8, 28, 15, 45, 6, 906293, tzinfo=UTC),
            0.8,
        ),
        (
            "binary_sensor.closet",
            "off",
            datetime(2026, 8, 28, 15, 46, 48, 88053, tzinfo=UTC),
            0.8,
        ),
    ):
        engine.observe(SensorInput(entity_id, state, event_at, reliability))
    engine.advance(datetime(2026, 8, 28, 15, 46, 58, 88053, tzinfo=UTC))
    for entity_id, event_at, reliability in (
        (
            "binary_sensor.bottom",
            datetime(2026, 8, 28, 15, 47, 34, 3613, tzinfo=UTC),
            0.8,
        ),
        (
            "binary_sensor.hall",
            datetime(2026, 8, 28, 15, 47, 37, 229584, tzinfo=UTC),
            0.85,
        ),
        (
            "binary_sensor.entrance",
            datetime(2026, 8, 28, 15, 47, 56, 450011, tzinfo=UTC),
            0.8,
        ),
    ):
        engine.observe(SensorInput(entity_id, "on", event_at, reliability))

    target_at = datetime(2026, 8, 28, 15, 48, 0, 349791, tzinfo=UTC)
    engine = restore_incident_closet_belief(engine, predictive_map, target_at)
    supports_before = engine.snapshot.anonymous_supports
    leases_before = engine.prediction_manager.leases

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
    arrival_transitions = tuple(
        item
        for item in belief.contributions
        if item.kind == "arrival_transition" and item.episode_id == episode.episode_id
    )

    assert result.disposition == "accepted_correlated_positive"
    assert episode.cadence_correlated
    assert not episode.health_warning
    assert authorization.authorized
    assert authorization.reason == "adjacent_authorized"
    assert len(arrival_transitions) == 1
    post_local_log_odds = belief.log_odds - arrival_transitions[0].log_odds_delta
    post_local_probability = 1.0 / (1.0 + math.exp(-post_local_log_odds))
    assert post_local_probability == pytest.approx(0.676195601951254, abs=1e-12)
    assert belief.probability == pytest.approx(0.7838097800975627, abs=1e-12)
    assert policy.active
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("closet", "acquired")
    ]
    assert all(
        token.episode_id != episode.episode_id
        for token in result.snapshot.traversal_tokens
    )
    assert all(
        candidate.episode_id != episode.episode_id
        for candidate in result.snapshot.pending_candidates
    )
    assert result.snapshot.anonymous_supports == supports_before
    assert engine.prediction_manager.leases == leases_before
    assert not any(event.kind == "refreshed" for event in result.policy_events)

    engine.observe(
        SensorInput(
            "binary_sensor.closet",
            "off",
            datetime(2026, 8, 28, 15, 48, 51, 681142, tzinfo=UTC),
            0.8,
        )
    )
    sleep_off = engine.advance(
        datetime(2026, 8, 28, 15, 49, 16, 794454, tzinfo=UTC)
    )
    closet = next(
        state for state in sleep_off.snapshot.policy_states if state.zone == "closet"
    )
    assert closet.active
