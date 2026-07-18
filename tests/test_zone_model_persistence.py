from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    migrate_schema6_seed,
    restore_target_state,
    serialize_target_state,
    target_map_fingerprint,
)
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 23, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def occupied_engine() -> ZoneModelEngine:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    return engine


def engine_at_restart_frontier(frontier: str) -> ZoneModelEngine:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    if frontier == "traversal":
        return engine
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    if frontier == "assertion":
        return engine
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))
    if frontier == "clear":
        return engine
    engine.advance(NOW + timedelta(seconds=8))
    if frontier == "decay":
        return engine
    engine.advance(NOW + timedelta(seconds=560))
    return engine


def test_target_state_round_trips_deterministically() -> None:
    engine = occupied_engine()
    payload = serialize_target_state(target_map(), engine)

    restored = restore_target_state(target_map(), payload, engine.snapshot.updated_at)

    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert serialize_target_state(target_map(), restored) == payload


@pytest.mark.parametrize(
    ("frontier", "restore_offset"),
    (
        ("assertion", 3),
        ("clear", 8),
        ("traversal", 46),
        ("decay", 300),
        ("release_dwell", 660),
    ),
)
def test_restore_advances_each_frontier_exactly_once(
    frontier: str,
    restore_offset: int,
) -> None:
    engine = engine_at_restart_frontier(frontier)
    payload = serialize_target_state(target_map(), engine)
    restore_at = NOW + timedelta(seconds=restore_offset)
    uninterrupted = restore_target_state(
        target_map(), payload, engine.snapshot.updated_at
    )

    expected = uninterrupted.advance(restore_at)
    restored = restore_target_state(target_map(), payload, restore_at)

    assert restored.snapshot == expected.snapshot
    if frontier == "release_dwell":
        assert expected.policy_events[0].kind == "released"
        assert restored.audit_rows[-1].reason == "released"
        assert restored.audit_rows[-1].event_kind is None


def test_target_restore_rejects_incompatible_state_atomically() -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    wrong_map = deepcopy(payload)
    wrong_map["map_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="map fingerprint"):
        restore_target_state(target_map(), wrong_map, NOW + timedelta(seconds=2))

    invalid_nested = deepcopy(payload)
    snapshot = invalid_nested["snapshot"]
    assert isinstance(snapshot, dict)
    beliefs = snapshot["belief_states"]
    assert isinstance(beliefs, list) and isinstance(beliefs[0], dict)
    beliefs[0]["profile_name"] = "unknown"
    with pytest.raises(ValueError, match="Unknown belief profile"):
        restore_target_state(target_map(), invalid_nested, NOW + timedelta(seconds=2))


def test_schema6_migration_uses_only_active_seed_and_raw_snapshot() -> None:
    predictive_map = target_map()
    payload = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": target_map_fingerprint(predictive_map),
        "occupants": 1,
        "policy": {
            "states": {
                "hall": {"keep_on": False},
                "room": {"keep_on": True},
            }
        },
        "log_probabilities": [0.0],
        "message": {"ignored": "exact assignment is not imported"},
    }
    snapshot = (
        SensorInput("binary_sensor.hall", "off", NOW),
        SensorInput("binary_sensor.room", "on", NOW),
    )

    migrated = migrate_schema6_seed(predictive_map, payload, snapshot, NOW)

    assert {state.zone: state.active for state in migrated.snapshot.policy_states}[
        "room"
    ] is True
    assert migrated.snapshot.traversal_tokens == ()
    assert migrated.snapshot.authorization_uses == ()
    assert migrated.audit_rows == ()
    assert {state.zone: state.probability for state in migrated.snapshot.belief_states}[
        "room"
    ] > 0.7


def test_target_decoder_rejects_each_malformed_boundary() -> None:
    baseline = serialize_target_state(target_map(), occupied_engine())

    def rejected(mutator: object) -> None:
        payload = deepcopy(baseline)
        assert callable(mutator)
        mutator(payload)
        with pytest.raises(ValueError):
            restore_target_state(target_map(), payload, NOW + timedelta(seconds=2))

    rejected(lambda root: root.__setitem__("audit", {}))
    rejected(lambda root: root.__setitem__("snapshot", []))
    rejected(lambda root: root["snapshot"].__setitem__("episode_states", {}))
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__("node_id", 1)
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__("episode_id", 1)
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "alias_states", {}
        )
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "clear_emitted", 1
        )
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "generation", True
        )
    )
    rejected(
        lambda root: root["snapshot"]["belief_states"][0].__setitem__("log_odds", True)
    )
    rejected(lambda root: root["snapshot"].__setitem__("current_token_ids", [1]))
    rejected(
        lambda root: root["snapshot"]["count_state"].__setitem__("diagnostics", [])
    )
    rejected(lambda root: root["snapshot"].__setitem__("updated_at", 1))
    rejected(lambda root: root["snapshot"].__setitem__("updated_at", "not-a-date"))

    with pytest.raises(ValueError, match="string-keyed"):
        restore_target_state(target_map(), {1: "invalid"}, NOW)


@pytest.mark.parametrize(
    "update",
    (
        {"schema": "wrong"},
        {"map_fingerprint": "wrong"},
        {"occupants": True},
        {"policy": []},
        {"policy": {"states": {"room": {"keep_on": 1}}}},
    ),
)
def test_schema6_decoder_rejects_invalid_seed_fields(update: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": target_map_fingerprint(target_map()),
        "occupants": 1,
    }
    payload.update(update)
    with pytest.raises(ValueError):
        migrate_schema6_seed(target_map(), payload, (), NOW)


def test_schema6_seed_allows_absent_policy() -> None:
    payload = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": target_map_fingerprint(target_map()),
        "occupants": 1,
    }
    migrated = migrate_schema6_seed(target_map(), payload, (), NOW)
    assert all(not state.active for state in migrated.snapshot.policy_states)
