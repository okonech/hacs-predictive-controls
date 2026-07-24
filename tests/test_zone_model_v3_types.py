from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.profiles import SHARED_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    CountConflictState,
    EpisodeEffect,
    PendingAcquisitionCandidate,
    PhysicalNode,
    SensorInput,
    StrongTrackedFront,
    TraversalAuthorization,
    TraversalToken,
)
from tests.test_zone_model_diagnostics import decision
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def changed[T](value: T, changes: dict[str, object]) -> T:
    return cast(T, replace(cast(Any, value), **changes))


def test_v3_profile_and_physical_input_validation_boundaries() -> None:
    assert SHARED_PROFILES["stay_pir"].single_node_reacquisition
    assert not SHARED_PROFILES["transition_fast"].single_node_reacquisition

    node = PhysicalNode("node", "zone", ("binary_sensor.node",), "stay_pir")
    for changes in ({"reliability": 0.0}, {"route_prior_weight": 0.0}):
        with pytest.raises(ValueError):
            replace(node, **changes)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Sensor reliability"):
        SensorInput("binary_sensor.node", "on", NOW, 0.0)
    with pytest.raises(ValueError, match="Episode reliability"):
        EpisodeEffect("node", "zone", "episode", "positive", NOW, 0.0)


def test_v3_traversal_token_and_pending_validation_boundaries() -> None:
    token = TraversalToken(
        "token",
        "node",
        "zone",
        "stay",
        "stay_pir",
        "episode",
        NOW,
        NOW + timedelta(seconds=30),
        path_node_ids=("node",),
    )
    invalid_token_changes: tuple[dict[str, object], ...] = (
        {"track_confidence": "invalid"},
        {"path_node_ids": ()},
        {"path_node_ids": ("",)},
        {"provenance_kind": ""},
        {"equivalent_confirmed_strength": 1},
    )
    for changes in invalid_token_changes:
        with pytest.raises(ValueError):
            changed(token, changes)

    pending = PendingAcquisitionCandidate(
        "node",
        "zone",
        "stay_pir",
        "episode",
        NOW,
        NOW + timedelta(seconds=30),
        NOW + timedelta(seconds=20),
        1.0,
    )
    invalid_pending_changes: tuple[dict[str, object], ...] = (
        {"node_id": ""},
        {"profile_name": "invalid"},
        {"expires_at": NOW},
        {"traversal_valid_until": NOW},
        {"reliability": 0.0},
    )
    for changes in invalid_pending_changes:
        with pytest.raises(ValueError):
            changed(pending, changes)


def test_v3_traversal_authorization_provenance_is_all_or_nothing() -> None:
    rejected = TraversalAuthorization(
        "node", "zone", "episode", NOW, False, "track_bootstrap_pending"
    )
    invalid: tuple[dict[str, object], ...] = (
        {"authorized": True},
        {"authorized": True, "track_confidence": "provisional"},
        {
            "authorized": True,
            "track_confidence": "provisional",
            "path_node_ids": ("node",),
        },
        {"track_confidence": "provisional"},
    )
    for changes in invalid:
        with pytest.raises(ValueError):
            changed(rejected, changes)


def test_v3_strong_front_and_count_conflict_validation_boundaries() -> None:
    front = StrongTrackedFront(
        "front",
        ("token",),
        ("node",),
        ("zone",),
        ("episode",),
        NOW + timedelta(seconds=30),
    )
    with pytest.raises(ValueError, match="ID"):
        replace(front, front_id="")
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(front, token_ids=("token", "token"))

    conflict = CountConflictState(
        "node",
        "zone",
        "episode",
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=30),
        ("front",),
    )
    invalid_conflict_changes: tuple[dict[str, object], ...] = (
        {"target_node_id": ""},
        {"last_evaluated_at": NOW - timedelta(seconds=1)},
        {"deadline": NOW, "last_evaluated_at": NOW},
        {"strong_front_ids": ("front", "front")},
        {"strong_front_ids": ()},
        {"degraded_at": NOW + timedelta(seconds=29)},
    )
    for changes in invalid_conflict_changes:
        with pytest.raises(ValueError):
            changed(conflict, changes)


def test_v3_policy_phase_and_conflict_diagnostic_validation_boundaries() -> None:
    state = next(
        item
        for item in ZoneModelEngine(target_map(), 1, NOW).snapshot.policy_states
        if item.zone == "room"
    )
    invalid_state_changes: tuple[dict[str, object], ...] = (
        {"phase": "invalid"},
        {"prediction_source_episode_id": ""},
        {"prediction_probability": -1.0},
        {"phase": "predicted", "active": True},
        {"prediction_probability": 0.5},
        {"phase": "inactive", "active": True},
        {"phase": "active", "active": False},
    )
    for changes in invalid_state_changes:
        with pytest.raises(ValueError):
            changed(state, changes)

    row = decision(NOW)
    invalid_row_changes: tuple[dict[str, object], ...] = (
        {
            "count_conflict_front_ids": ("same", "same"),
            "reliability_result": "degraded",
        },
        {"reliability_result": "invalid"},
        {"count_conflict_front_ids": ("front",)},
    )
    for changes in invalid_row_changes:
        with pytest.raises(ValueError):
            changed(row, changes)


def test_v3_snapshot_auxiliary_state_must_be_unique_and_sorted() -> None:
    snapshot = ZoneModelEngine(target_map(), 1, NOW).snapshot
    pending = PendingAcquisitionCandidate(
        "node",
        "room",
        "stay_pir",
        "episode",
        NOW,
        NOW + timedelta(seconds=30),
        NOW + timedelta(seconds=20),
        1.0,
    )
    front = StrongTrackedFront(
        "front",
        ("token",),
        ("node",),
        ("room",),
        ("episode",),
        NOW + timedelta(seconds=30),
    )
    conflict = CountConflictState(
        "node",
        "room",
        "episode",
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=30),
        ("front",),
    )
    retained = TraversalToken(
        "node:episode",
        "node",
        "room",
        "stay",
        "stay_pir",
        "episode",
        NOW,
        NOW + timedelta(seconds=90),
        path_node_ids=("node",),
    )
    invalid_snapshots: tuple[dict[str, object], ...] = (
        {"pending_candidates": (pending, pending)},
        {"strong_fronts": (front, front)},
        {"count_conflicts": (conflict, conflict)},
        {"retained_traversal_tokens": (retained, retained)},
    )
    for changes in invalid_snapshots:
        with pytest.raises(ValueError, match="unique"):
            changed(snapshot, changes)
