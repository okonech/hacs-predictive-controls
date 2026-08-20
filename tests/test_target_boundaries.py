from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.automation_summary import (
    _explanation,
    _status,
    _top_prediction,
)
from custom_components.predictive_controls.model import ZoneConfig
from custom_components.predictive_controls.occupancy_settings import (
    authoritative_occupants_from_state_value,
)
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
    _as_utc,
    _status_for_probability,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    LegacyV2Seed,
    legacy_target_map_fingerprint,
    migrate_v2_seed,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)
from tests.test_confidence import event
from tests.test_zone_model_engine import target_map
from tests.test_zone_model_persistence import legacy_v2_payload

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_summary_and_facade_scalar_boundaries() -> None:
    assert _as_utc(datetime(2026, 7, 18, 12, 0)).tzinfo is UTC
    assert _top_prediction({"a": 0.4, "b": 0.4}) == ("b", 0.4)
    assert _explanation(("a", "b", "c", "d"), "next_zone", 0.75) == (
        "Probably occupied: A, B, C +1 more. Next likely zone: Next Zone (75%)."
    )
    assert [_status(value) for value in (0.9, 0.7, 0.4, 0.1, 0.0)] == [
        "confirmed",
        "probable",
        "possible",
        "suspect",
        "rejected",
    ]
    assert [_status_for_probability(value) for value in (0.9, 0.7, 0.4, 0.1, 0.0)] == [
        "confirmed",
        "probable",
        "possible",
        "suspect",
        "rejected",
    ]
    assert authoritative_occupants_from_state_value(None) is None


def test_tracker_validation_bootstrap_advancement_and_transient_expiry() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OccupancyTracker(target_map(), TrackerConfig(-1))
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    with pytest.raises(ValueError, match="non-negative"):
        tracker.reconcile_expected_occupants(-1, NOW)
    with pytest.raises(ValueError, match="above two"):
        tracker.reject_unsupported_count(2, NOW)

    tracker.bootstrap_state(
        (event("hall", "hall", "off", NOW),),
        cold_start=True,
    )
    tracker.bootstrap_state(
        (event("hall", "hall", "off", NOW),),
        cold_start=False,
    )
    tracker.bootstrap_state(
        (event("hall", "hall", "off", NOW + timedelta(seconds=1)),),
        cold_start=False,
    )
    assert tracker.expire_transient_state(NOW + timedelta(seconds=2)) is False
    tracker.observe(event("hall", "hall", "on", NOW + timedelta(seconds=3)))
    assert tracker.expire_transient_state(NOW + timedelta(minutes=2)) is True

    empty = OccupancyTracker(target_map(), TrackerConfig(1))
    empty.bootstrap_state((), cold_start=True)


def test_tracker_empty_store_schema6_migration_and_prediction_restore_failure() -> None:
    empty = OccupancyTracker(target_map(), TrackerConfig(1))
    assert empty.occupancy_store_data(NOW)["schema"] == "zone-belief-v4"
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    schema6 = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(target_map()),
        "occupants": 1,
        "policy": {
            "states": {
                "hall": {"keep_on": False},
                "room": {"keep_on": True},
            }
        },
    }
    assert tracker.restore_state(schema6, NOW)
    assert tracker.diagnostics.restore_status == "schema6_pending"
    tracker.bootstrap_state(
        (
            event("hall", "hall", "off", NOW),
            event("room", "room", "on", NOW),
        ),
        cold_start=False,
    )
    assert tracker.diagnostics.restore_status == "schema6_migrated"

    payload = tracker.occupancy_store_data(NOW)
    invalid_prediction = deepcopy(payload)
    invalid_prediction["prediction"] = []
    rejected = OccupancyTracker(target_map(), TrackerConfig(1))
    rejected.observe(event("hall", "hall", "on", NOW))
    before = rejected.diagnostics.beliefs
    assert not rejected.restore_state(invalid_prediction, NOW)
    assert rejected.diagnostics.restore_status == "rejected"
    assert rejected.diagnostics.beliefs == before

    without_prediction = deepcopy(payload)
    without_prediction.pop("prediction")
    missing = OccupancyTracker(target_map(), TrackerConfig(1))
    assert not missing.restore_state(without_prediction, NOW)
    assert missing.diagnostics.restore_status == "rejected"


def test_tracker_rejects_corrupt_schema6_before_deferred_cold_bootstrap() -> None:
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    corrupt = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": "wrong",
        "occupants": 1,
    }

    assert not tracker.restore_state(corrupt, NOW)
    assert tracker.diagnostics.restore_status == "rejected"
    tracker.bootstrap_state(
        (
            event("hall", "hall", "off", NOW),
            event("room", "room", "on", NOW),
        ),
        cold_start=True,
    )

    assert tracker.diagnostics.restore_status == "rejected"
    assert set(tracker.diagnostics.beliefs) == {"hall", "room"}


def test_tracker_rejects_schema6_seed_for_zone_without_physical_filter() -> None:
    predictive_map = target_map()
    predictive_map.zone_configs["ghost"] = ZoneConfig("ghost")
    tracker = OccupancyTracker(predictive_map, TrackerConfig(1))
    payload = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(predictive_map),
        "occupants": 1,
        "policy": {"states": {"ghost": {"keep_on": True}}},
    }

    assert not tracker.restore_state(payload, NOW)
    assert tracker.diagnostics.restore_status == "rejected"


def test_tracker_rejects_v2_seed_for_zone_without_physical_filter() -> None:
    predictive_map = target_map()
    predictive_map.zone_configs["ghost"] = ZoneConfig("ghost")
    payload = legacy_v2_payload(traversal_reason="adjacent_current")
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    policy_states = snapshot["policy_states"]
    assert isinstance(policy_states, list) and policy_states
    ghost = deepcopy(policy_states[0])
    assert isinstance(ghost, dict)
    ghost["zone"] = "ghost"
    ghost["active"] = False
    policy_states.append(ghost)
    tracker = OccupancyTracker(predictive_map, TrackerConfig(1))

    assert not tracker.restore_state(payload, NOW)
    assert tracker.diagnostics.restore_status == "rejected"


def test_tracker_defers_valid_v2_migration_and_rejects_invalid_v2_seed() -> None:
    payload = legacy_v2_payload(traversal_reason="adjacent_current")
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))

    assert tracker.restore_state(payload, NOW)
    assert tracker.diagnostics.restore_status == "v2_pending"
    tracker.bootstrap_state(
        (
            event("hall", "hall", "off", NOW),
            event("room", "room", "on", NOW),
        ),
        cold_start=False,
    )
    assert tracker.diagnostics.restore_status == "v2_migrated"
    assert tracker.config.expected_occupants == 1

    invalid = deepcopy(payload)
    invalid["map_fingerprint"] = "wrong"
    rejected = OccupancyTracker(target_map(), TrackerConfig(1))
    assert not rejected.restore_state(invalid, NOW)
    assert rejected.diagnostics.restore_status == "rejected"


@pytest.mark.parametrize("legacy_kind", ("schema6", "v2"))
def test_deferred_migration_uses_reconciled_authoritative_count(
    legacy_kind: str,
) -> None:
    if legacy_kind == "schema6":
        payload: dict[str, object] = {
            "schema": "exact-augmented-v6",
            "map_fingerprint": legacy_target_map_fingerprint(target_map()),
            "occupants": 1,
            "policy": {"states": {"room": {"keep_on": True}}},
        }
    else:
        payload = legacy_v2_payload(traversal_reason="adjacent_current")
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))

    assert tracker.restore_state(payload, NOW)
    tracker.reconcile_expected_occupants(2, NOW + timedelta(seconds=1))
    tracker.bootstrap_state(
        (
            event("hall", "hall", "off", NOW + timedelta(seconds=2)),
            event("room", "room", "on", NOW + timedelta(seconds=2)),
        ),
        cold_start=False,
    )

    assert tracker.config.expected_occupants == 2
    assert tracker.diagnostics.expected_occupants == 2
    assert tracker.diagnostics.restore_status == f"{legacy_kind}_migrated"


@pytest.mark.parametrize(
    ("seed", "authoritative"),
    ((LegacyV2Seed(1, {}), True), (LegacyV2Seed(3, {}), None)),
)
def test_v2_migration_rejects_invalid_stored_or_authoritative_count(
    seed: LegacyV2Seed,
    authoritative: int | None,
) -> None:
    with pytest.raises(ValueError, match="Migration occupant count"):
        migrate_v2_seed(
            target_map(),
            seed,
            (),
            NOW,
            expected_count=authoritative,
        )


def test_tracker_adopts_restored_count_as_reconciliation_frontier() -> None:
    stored = ZoneModelEngine(target_map(), 2, NOW)
    payload = serialize_target_state(target_map(), stored)
    tracker = OccupancyTracker(target_map(), TrackerConfig(0))

    assert tracker.restore_state(payload, NOW)
    assert tracker.config.expected_occupants == 2
    assert tracker.requested_expected_occupants == 2

    tracker.reconcile_expected_occupants(0, NOW, evidence_id="external_zero")
    assert tracker.config.expected_occupants == 0
    assert tracker.requested_expected_occupants == 0
    assert all(not state.active for state in tracker.policy_states.values())


def test_tracker_no_engine_learning_commit_and_active_hold_are_bounded() -> None:
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    tracker.commit_prediction_learning()
    tracker.observe(event("hall", "hall", "on", NOW))
    tracker.observe(event("room", "room", "on", NOW + timedelta(seconds=2)))
    tracker.observe(event("room", "room", "off", NOW + timedelta(seconds=40)))
    tracker.refresh_active(NOW + timedelta(seconds=45))

    held = tracker.observe(
        event("room", "room", "on", NOW + timedelta(seconds=50))
    )

    assert held.current.explanation["active"] is True


def test_tracker_refresh_builds_timer_updates_and_recent_event_bound() -> None:
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    for index in range(26):
        state = "on" if index % 2 == 0 else "off"
        tracker.observe(
            event("hall", "hall", state, NOW + timedelta(seconds=index * 10))
        )
    assert len(tracker.recent_events) == 25
    updates = tracker.refresh_active(NOW + timedelta(hours=1))
    assert updates
    assert all(update.event.entity_id == "timer.zone_model" for update in updates)
    assert tracker.state_for_zone("missing").zone == "missing"
    assert tracker.refresh_active(NOW + timedelta(hours=1)) == ()


def test_tracker_prebootstrap_reason_and_snapshot_sort_guards() -> None:
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))
    assert tracker._policy_reason("room") == "no evidence"  # noqa: SLF001
    snapshot = ZoneModelEngine(target_map(), 1, NOW).snapshot
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(snapshot, belief_states=tuple(reversed(snapshot.belief_states)))
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(snapshot, current_token_ids=("same", "same"))


def test_engine_validation_stale_count_and_unavailable_paths() -> None:
    with pytest.raises(ValueError, match="active seed"):
        ZoneModelEngine(target_map(), 1, NOW, active_seed={"missing": True})
    with pytest.raises(ValueError, match="active seed"):
        ZoneModelEngine(target_map(), 1, NOW, active_seed={"room": 1})  # type: ignore[dict-item]

    engine = ZoneModelEngine(target_map(), 1, NOW)
    with pytest.raises(ValueError, match="share one frontier"):
        engine.bootstrap_sensor_snapshot(
            (SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=1)),),
            NOW,
        )
    unavailable = engine.observe(SensorInput("binary_sensor.hall", "unavailable", NOW))
    episode_by_node = {
        state.node_id: state for state in unavailable.snapshot.episode_states
    }
    assert episode_by_node["hall"].alias_states == (
        ("binary_sensor.hall", "unavailable"),
    )
    stale_count = engine.observe_count(
        CountInput("stale", 1, True, NOW - timedelta(seconds=1))
    )
    assert stale_count.disposition == "stale"
    stale_advance = engine.advance(NOW - timedelta(seconds=1))
    assert stale_advance.disposition == "stale"
    with pytest.raises(ValueError, match="cannot precede"):
        engine.advance(
            NOW + timedelta(seconds=2),
            processing_at=NOW + timedelta(seconds=1),
        )


def test_engine_restore_rejects_time_zone_and_audit_incompatibility() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    snapshot = engine.snapshot
    with pytest.raises(ValueError, match="predates"):
        ZoneModelEngine.restore(
            target_map(), snapshot, engine.audit_rows, NOW - timedelta(seconds=1)
        )
    with pytest.raises(ValueError, match="zones"):
        ZoneModelEngine.restore(
            target_map(),
            replace(snapshot, belief_states=snapshot.belief_states[:-1]),
            engine.audit_rows,
            NOW,
        )
    incompatible = replace(
        engine.audit_rows[0],
        zone="missing",
    )
    with pytest.raises(ValueError, match="audit row"):
        ZoneModelEngine.restore(target_map(), snapshot, (incompatible,), NOW)
    future = replace(
        engine.audit_rows[0],
        event_at=NOW + timedelta(seconds=1),
        processing_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="audit row"):
        ZoneModelEngine.restore(target_map(), snapshot, (future,), NOW)


def test_engine_duplicate_count_and_pending_episode_effects() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=1)))
    count_engine = ZoneModelEngine(target_map(), 0, NOW)
    result = count_engine.observe_count(
        CountInput("same", 1, True, NOW + timedelta(seconds=10))
    )
    assert result.disposition == "accepted"
    duplicate = count_engine.observe_count(
        CountInput("same", 1, True, NOW + timedelta(seconds=11))
    )
    assert duplicate.disposition == "duplicate"


def test_engine_bootstrap_unavailable_recovery_and_pending_count_effects() -> None:
    unavailable = ZoneModelEngine(target_map(), 1, NOW)
    unavailable.bootstrap_sensor_snapshot(
        (SensorInput("binary_sensor.hall", "unavailable", NOW),), NOW
    )
    hall_belief = {state.zone: state for state in unavailable.snapshot.belief_states}[
        "hall"
    ]
    assert hall_belief.context == "unavailable"

    recovered = ZoneModelEngine(target_map(), 1, NOW)
    recovered.observe(SensorInput("binary_sensor.hall", "on", NOW))
    recovered.advance(NOW + timedelta(minutes=20))
    recovered.observe(
        SensorInput("binary_sensor.hall", "unavailable", NOW + timedelta(minutes=21))
    )
    result = recovered.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(minutes=22))
    )
    assert not {state.node_id: state for state in result.snapshot.episode_states}[
        "hall"
    ].health_warning

    pending = ZoneModelEngine(target_map(), 1, NOW)
    pending.observe(SensorInput("binary_sensor.hall", "on", NOW))
    pending.observe(
        SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=1))
    )
    counted = pending.observe_count(
        CountInput("increase", 2, True, NOW + timedelta(seconds=6))
    )
    assert counted.disposition == "accepted"
