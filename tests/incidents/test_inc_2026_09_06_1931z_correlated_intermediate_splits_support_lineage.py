from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.status import (
    project_reliability_warnings,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


def incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "fixture_entry": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_entry"},
                    "adjacent": ["fixture_bridge"],
                },
                "fixture_bridge": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_bridge"},
                    "adjacent": [
                        "fixture_entry",
                        "master_bathroom_light_motion",
                    ],
                },
                "fixture_lower_route": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.fixture_lower_route"},
                    "adjacent": ["top_of_staircase_motion"],
                },
                "master_bathroom_light_motion": {
                    "zone": "master_bathroom",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.master_bathroom"},
                    "adjacent": [
                        "fixture_bridge",
                        "master_bedroom_closet",
                    ],
                    "initial_weight": 0.7,
                },
                "master_bedroom_closet": {
                    "role": "subzone_occupancy",
                    "entities": {"mmwave": "binary_sensor.master_bedroom_closet"},
                    "adjacent": [
                        "master_bathroom_light_motion",
                        "master_bedroom_entrance",
                    ],
                    "initial_weight": 0.8,
                },
                "master_bedroom_entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.master_bedroom_entrance"},
                    "adjacent": [
                        "master_bedroom_closet",
                        "top_of_staircase_motion",
                    ],
                    "initial_weight": 0.8,
                },
                "top_of_staircase_motion": {
                    "zone": "upstairs_hallway",
                    "role": "transition_gate",
                    "entities": {"mmwave": "binary_sensor.top_of_staircase"},
                    "adjacent": [
                        "fixture_lower_route",
                        "master_bedroom_entrance",
                        "shaila_office_fan_light",
                        "alex_office_motion",
                    ],
                    "initial_weight": 0.85,
                },
                "shaila_office_fan_light": {
                    "zone": "shaila_office",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.shaila_office"},
                    "adjacent": ["top_of_staircase_motion"],
                    "initial_weight": 0.75,
                },
                "alex_office_motion": {
                    "zone": "alex_office",
                    "role": "room_occupancy",
                    "entities": {"mmwave": "binary_sensor.alex_office"},
                    "adjacent": ["top_of_staircase_motion"],
                    "initial_weight": 0.75,
                },
            }
        }
    )


def observe(
    engine: ZoneModelEngine,
    entity_id: str,
    state: str,
    event_at: str,
) -> None:
    engine.observe(SensorInput(entity_id, state, datetime.fromisoformat(event_at)))


def engine_before_correlated_intermediate() -> ZoneModelEngine:
    engine = ZoneModelEngine(
        incident_map(),
        2,
        datetime(2026, 9, 6, 19, 22, 39, tzinfo=UTC),
    )

    # Fixture-only provenance for the retained closet cadence and bathroom support.
    observe(
        engine,
        "binary_sensor.master_bedroom_closet",
        "on",
        "2026-09-06T19:22:40Z",
    )
    observe(
        engine,
        "binary_sensor.master_bedroom_closet",
        "off",
        "2026-09-06T19:22:54.617693+00:00",
    )
    observe(engine, "binary_sensor.fixture_entry", "on", "2026-09-06T19:31:56Z")
    observe(engine, "binary_sensor.fixture_bridge", "on", "2026-09-06T19:31:57Z")
    observe(
        engine,
        "binary_sensor.master_bathroom",
        "on",
        "2026-09-06T19:31:58.382096+00:00",
    )

    observe(
        engine,
        "binary_sensor.master_bedroom_closet",
        "off",
        "2026-09-06T19:32:26.372683+00:00",
    )
    return engine


@pytest.mark.target_model
def test_inc_2026_09_06_1931z_correlated_intermediate_splits_support_lineage(
) -> None:
    engine = engine_before_correlated_intermediate()
    original_support_id = engine.snapshot.anonymous_supports[0].support_id
    correlated = engine.observe(
        SensorInput(
            "binary_sensor.master_bedroom_closet",
            "on",
            datetime.fromisoformat("2026-09-06T19:32:54.617692+00:00"),
        )
    )
    correlated_episode = next(
        episode
        for episode in correlated.snapshot.episode_states
        if episode.node_id == "master_bedroom_closet"
    )
    correlated_token_issued = any(
        token.episode_id == correlated_episode.episode_id
        for token in correlated.snapshot.traversal_tokens
    )
    correlated_support = correlated.snapshot.anonymous_supports[0]
    leases_after_correlated = engine.prediction_manager.leases
    pending_learning_after = tuple(
        engine._pending_prediction_learning  # noqa: SLF001
    )
    entrance = engine.observe(
        SensorInput(
            "binary_sensor.master_bedroom_entrance",
            "on",
            datetime.fromisoformat("2026-09-06T19:33:00.366187+00:00"),
        )
    )
    observe(
        engine,
        "binary_sensor.top_of_staircase",
        "on",
        "2026-09-06T19:33:00.967080+00:00",
    )
    shaila = engine.observe(
        SensorInput(
            "binary_sensor.shaila_office",
            "on",
            datetime.fromisoformat("2026-09-06T19:33:07.660283+00:00"),
        )
    )
    observe(
        engine,
        "binary_sensor.master_bathroom",
        "off",
        "2026-09-06T19:33:25.596498+00:00",
    )
    observe(
        engine,
        "binary_sensor.master_bedroom_closet",
        "off",
        "2026-09-06T19:33:34.928445+00:00",
    )
    observe(
        engine,
        "binary_sensor.shaila_office",
        "off",
        "2026-09-06T19:33:43.664305+00:00",
    )

    # Fixture-only clears and lower-route source make the later retained events
    # distinct while preserving their graph authorization.
    observe(
        engine,
        "binary_sensor.top_of_staircase",
        "off",
        "2026-09-06T19:33:44+00:00",
    )
    observe(
        engine,
        "binary_sensor.fixture_lower_route",
        "on",
        "2026-09-06T23:21:07+00:00",
    )
    observe(
        engine,
        "binary_sensor.top_of_staircase",
        "on",
        "2026-09-06T23:21:08.125213+00:00",
    )
    alex = engine.observe(
        SensorInput(
            "binary_sensor.alex_office",
            "on",
            datetime.fromisoformat("2026-09-06T23:21:13.297739+00:00"),
        )
    )
    engine.advance(alex.snapshot.updated_at + timedelta(microseconds=1))
    degraded_at = datetime.fromisoformat("2026-09-06T23:23:16.265017+00:00")
    degraded = engine.advance(degraded_at)

    warnings = project_reliability_warnings(
        degraded.snapshot.reliability_warning_occurrences,
        degraded_at,
    )
    assert not any(
        row["node_id"] == "alex_office_motion"
        and row["active"]
        and "count_conflict" in cast(list[str], row["active_reasons"])
        for row in warnings
    )

    assert correlated_episode.cadence_correlated
    assert correlated_token_issued
    assert correlated_support.support_id == original_support_id
    assert correlated_support.current_node_id == "master_bedroom_closet"
    assert all(
        lease.source_node_id != correlated_episode.node_id
        for lease in leases_after_correlated
    )
    assert all(
        authorization.target_episode_id != correlated_episode.episode_id
        for authorization in pending_learning_after
    )
    entrance_authorization = next(
        authorization
        for authorization in entrance.authorizations
        if authorization.target_node_id == "master_bedroom_entrance"
    )
    assert any(
        token.episode_id == correlated_episode.episode_id
        for token in entrance_authorization.source_tokens
    )
    shaila_supports = shaila.snapshot.anonymous_supports
    assert len(shaila_supports) == 1
    assert shaila_supports[0].support_id == original_support_id
    assert shaila_supports[0].current_node_id == "shaila_office_fan_light"
    alex_supports = alex.snapshot.anonymous_supports
    assert len(alex_supports) == 2
    assert any(
        support.current_node_id == "alex_office_motion"
        for support in alex_supports
    )
    assert next(
        authorization
        for authorization in alex.authorizations
        if authorization.target_node_id == "alex_office_motion"
    ).reason == "track_confirmed"
