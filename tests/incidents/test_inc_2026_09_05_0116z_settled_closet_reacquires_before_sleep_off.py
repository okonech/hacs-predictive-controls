from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_05_0116z_settled_closet_reacquires_before_sleep_off(
    authoritative_count: int,
) -> None:
    top_at = _at("2026-09-05T01:16:30.919930Z")
    entrance_at = _at("2026-09-05T01:16:40.028350Z")
    closet_at = _at("2026-09-05T01:16:41.843671Z")
    closet_clear_at = _at("2026-09-05T01:20:19.951114Z")
    observed_release_at = _at("2026-09-05T02:11:17.196879Z")
    model_release_at = _at("2026-09-05T02:11:41.735890Z")
    final_positive_at = _at("2026-09-05T04:36:47.492407Z")
    sleep_off_at = _at("2026-09-05T04:36:57.807707Z")
    cycles = (
        ("2026-09-05T02:33:34.245790Z", "2026-09-05T02:34:11.705370Z"),
        ("2026-09-05T02:43:06.437320Z", "2026-09-05T02:43:37.183604Z"),
        ("2026-09-05T02:47:02.099069Z", "2026-09-05T02:47:47.365877Z"),
        ("2026-09-05T02:49:28.480235Z", "2026-09-05T02:49:58.897750Z"),
        ("2026-09-05T03:16:16.123061Z", "2026-09-05T03:16:55.657163Z"),
        ("2026-09-05T03:38:25.313667Z", "2026-09-05T03:38:58.715883Z"),
        ("2026-09-05T03:39:36.020506Z", "2026-09-05T03:40:33.419418Z"),
        ("2026-09-05T03:41:37.560492Z", "2026-09-05T03:42:16.338295Z"),
        ("2026-09-05T04:24:46.940438Z", "2026-09-05T04:25:40.600856Z"),
        ("2026-09-05T04:26:52.802550Z", "2026-09-05T04:27:24.293763Z"),
        ("2026-09-05T04:27:45.326833Z", "2026-09-05T04:28:44.373954Z"),
        ("2026-09-05T04:32:10.853858Z", "2026-09-05T04:32:41.255209Z"),
        ("2026-09-05T04:33:41.992391Z", "2026-09-05T04:34:42.398511Z"),
    )
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["top", "closet"],
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
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        top_at - timedelta(seconds=1),
    )

    engine.observe(SensorInput("binary_sensor.top", "on", top_at))
    engine.observe(SensorInput("binary_sensor.entrance", "on", entrance_at))
    tracked = engine.observe(SensorInput("binary_sensor.closet", "on", closet_at))
    engine.observe(SensorInput("binary_sensor.closet", "off", closet_clear_at))
    observed_release = engine.advance(observed_release_at)
    released = engine.advance(model_release_at)
    cycle_results = []
    for asserted_at, cleared_at in cycles:
        cycle_results.append(
            engine.observe(
                SensorInput("binary_sensor.closet", "on", _at(asserted_at))
            )
        )
        engine.observe(SensorInput("binary_sensor.closet", "off", _at(cleared_at)))

    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        engine.snapshot.updated_at,
    )
    reacquired = engine.observe(
        SensorInput("binary_sensor.closet", "on", final_positive_at)
    )
    restored_reacquired = restored.observe(
        SensorInput("binary_sensor.closet", "on", final_positive_at)
    )
    sleep_off = engine.advance(sleep_off_at)
    restored_sleep_off = restored.advance(sleep_off_at)

    assert [(event.zone, event.kind) for event in tracked.policy_events] == [
        ("closet", "acquired")
    ]
    released_policy = next(
        state for state in released.snapshot.policy_states if state.zone == "closet"
    )
    released_belief = next(
        state for state in released.snapshot.belief_states if state.zone == "closet"
    )
    observed_release_policy = next(
        state
        for state in observed_release.snapshot.policy_states
        if state.zone == "closet"
    )
    assert observed_release_policy.active is True
    assert released_policy.active is False, (
        released_belief.probability,
        released_policy.pending_release_since,
    )
    sleep_off_policy = next(
        state for state in sleep_off.snapshot.policy_states if state.zone == "closet"
    )
    assert sleep_off_policy.active is True
    post_release_acquisitions = [
        event
        for result in (*cycle_results, reacquired)
        for event in result.policy_events
        if event.zone == "closet" and event.kind == "acquired"
    ]
    assert len(post_release_acquisitions) == 1
    assert post_release_acquisitions[0].event_at <= final_positive_at
    reacquired_policy = next(
        state
        for state in reacquired.snapshot.policy_states
        if state.zone == "closet"
    )
    assert reacquired_policy.active is True
    assert restored_reacquired.snapshot == reacquired.snapshot
    assert restored_sleep_off.snapshot == sleep_off.snapshot
    assert len(sleep_off.snapshot.anonymous_supports) == 1
    assert not any(
        token.episode_id
        == next(
            state.episode_id
            for state in reacquired.snapshot.episode_states
            if state.node_id == "closet"
        )
        for token in reacquired.snapshot.traversal_tokens
    )
