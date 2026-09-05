from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    PolicyEvent,
    SensorInput,
)


@pytest.mark.target_model
def test_inc_2026_08_22_1745z_prearrival_token_cannot_release_asserted_target() -> None:
    bootstrap_at = datetime(2026, 8, 22, 17, 45, 13, tzinfo=UTC)
    predictive_map = PredictiveMap.from_mapping(
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
                "route_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.route_entry"},
                    "adjacent": ["shared_transition"],
                },
                "shared_transition": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"mmwave": "binary_sensor.shared_transition"},
                    "adjacent": [
                        "route_entry",
                        "retained_target",
                        "second_target",
                    ],
                },
                "retained_target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.retained_target"},
                    "adjacent": ["shared_transition"],
                    "initial_weight": 0.75,
                },
                "second_target": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.second_target"},
                    "adjacent": ["shared_transition"],
                },
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 2, bootstrap_at)
    engine.observe(
        SensorInput(
            "binary_sensor.independent_entry",
            "on",
            bootstrap_at + timedelta(microseconds=100000),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.independent_transition",
            "on",
            bootstrap_at + timedelta(microseconds=200000),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.independent_stay",
            "on",
            bootstrap_at + timedelta(microseconds=300000),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.route_entry",
            "on",
            datetime(2026, 8, 22, 17, 45, 15, 291907, tzinfo=UTC),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.shared_transition",
            "on",
            datetime(2026, 8, 22, 17, 45, 16, 259573, tzinfo=UTC),
        )
    )
    retained = engine.observe(
        SensorInput(
            "binary_sensor.retained_target",
            "on",
            datetime(2026, 8, 22, 17, 45, 22, 409954, tzinfo=UTC),
        )
    )
    retained_support = next(
        support
        for support in retained.snapshot.anonymous_supports
        if support.current_zone == "retained_target"
    )
    retained_belief = next(
        belief
        for belief in retained.snapshot.belief_states
        if belief.zone == "retained_target"
    )
    second = engine.observe(
        SensorInput(
            "binary_sensor.second_target",
            "on",
            datetime(2026, 8, 22, 17, 45, 24, 33458, tzinfo=UTC),
        )
    )
    conflict_at = datetime(2026, 8, 22, 17, 47, 28, 212891, tzinfo=UTC)
    engine.advance(conflict_at)
    release_at = datetime(2026, 8, 22, 17, 54, 58, 884915, tzinfo=UTC)
    policy_events: list[PolicyEvent] = []
    timer_at = conflict_at + timedelta(seconds=5)
    while timer_at < release_at:
        policy_events.extend(engine.advance(timer_at).policy_events)
        timer_at += timedelta(seconds=5)
    historical_release = engine.advance(release_at)
    policy_events.extend(historical_release.policy_events)
    release_check = engine.advance(release_at + timedelta(seconds=5))
    policy_events.extend(release_check.policy_events)

    retained_policy = next(
        state
        for state in release_check.snapshot.policy_states
        if state.zone == "retained_target"
    )
    second_policy = next(
        state
        for state in second.snapshot.policy_states
        if state.zone == "second_target"
    )
    moved_support = next(
        support
        for support in second.snapshot.anonymous_supports
        if support.support_id == retained_support.support_id
    )
    historical_belief = next(
        belief
        for belief in historical_release.snapshot.belief_states
        if belief.zone == "retained_target"
    )
    assert retained_policy.active
    assert not any(
        event.zone == "retained_target" and event.kind == "released"
        for event in policy_events
    )
    assert retained_support.updated_at > datetime(
        2026, 8, 22, 17, 45, 16, 259573, tzinfo=UTC
    )
    assert retained_belief.probability == pytest.approx(
        0.7812030651163774,
        abs=0.02,
    )
    assert historical_belief.probability >= 0.7
    assert moved_support.current_zone == "retained_target"
    assert second_policy.active
