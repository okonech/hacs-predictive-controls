from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.profiles import SHARED_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    BeliefContribution,
    CountConflictState,
    CountSupport,
    EpisodeEffect,
    EpisodeState,
    PendingAcquisitionCandidate,
    PhysicalNode,
    ReliabilityWarningOccurrence,
    SensorInput,
    SupportTokenBinding,
    SupportTransition,
    SupportTransitionEvent,
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
    with pytest.raises(ValueError, match="Interaction aliases"):
        replace(node, interaction_aliases=("event.unmapped",))

    with pytest.raises(ValueError, match="Sensor reliability"):
        SensorInput("binary_sensor.node", "on", NOW, 0.0)
    with pytest.raises(ValueError, match="Episode reliability"):
        EpisodeEffect("node", "zone", "episode", "positive", NOW, 0.0)


def test_v4_cadence_effect_and_episode_validation_boundaries() -> None:
    effect = EpisodeEffect(
        "node",
        "zone",
        "episode",
        "sustained_flapping",
        NOW,
        0.8,
        "sustained_flapping",
    )
    contribution = BeliefContribution(
        NOW,
        "correlated_positive",
        "cleared_without_outward",
        "asserted",
        0.1,
        "episode",
    )
    frontier = NOW + timedelta(minutes=1)
    episode = EpisodeState(
        "node",
        "zone",
        "stay_presence",
        (("binary_sensor.node", "on"),),
        generation=2,
        episode_id="episode",
        status="asserted",
        started_at=frontier,
        last_event_at=frontier,
        advanced_at=frontier,
        cadence_warning=True,
        cadence_run_started_at=NOW,
        cadence_last_transition_at=frontier,
        cadence_cycle_count=1,
        cadence_correlated=True,
        cadence_warning_reason="sustained_flapping",
    )

    assert effect.warning_reason == "sustained_flapping"
    assert contribution.kind == "correlated_positive"
    assert episode.cadence_cycle_count == 1

    with pytest.raises(ValueError, match="identifiers"):
        replace(effect, node_id="")
    with pytest.raises(ValueError):
        replace(effect, warning_reason=None)
    with pytest.raises(ValueError, match="Cadence warning clear"):
        replace(effect, kind="cadence_warning_cleared", warning_reason=None)
    with pytest.raises(ValueError, match="Health effect"):
        replace(effect, kind="health_degraded", warning_reason=None)
    with pytest.raises(ValueError):
        EpisodeEffect(
            "node",
            "zone",
            "episode",
            "positive",
            NOW,
            warning_reason="sustained_flapping",
        )

    invalid_episodes: tuple[dict[str, object], ...] = (
        {"cadence_last_transition_at": None},
        {"cadence_cycle_count": 65536},
        {"profile_name": "stay_pir"},
        {"cadence_warning": False},
        {"cadence_warning_reason": "invalid"},
    )
    for changes in invalid_episodes:
        with pytest.raises(ValueError):
            changed(episode, changes)

    invalid_cadence_states: tuple[dict[str, object], ...] = (
        {"cadence_run_started_at": frontier + timedelta(seconds=1)},
        {
            "cadence_last_transition_at": frontier + timedelta(seconds=1),
        },
        {"cadence_cycle_count": True},
        {
            "cadence_run_started_at": None,
            "cadence_last_transition_at": None,
        },
        {"cadence_warning_reason": None},
        {"episode_id": None},
        {
            "cadence_run_started_at": None,
            "cadence_last_transition_at": None,
            "cadence_cycle_count": 0,
            "cadence_correlated": False,
        },
    )
    for changes in invalid_cadence_states:
        with pytest.raises(ValueError):
            changed(episode, changes)


def test_v4_reliability_warning_occurrence_validation_boundaries() -> None:
    cleared = ReliabilityWarningOccurrence(
        "node",
        "zone",
        "suspected_stuck",
        "count_conflict",
        NOW,
        NOW + timedelta(minutes=1),
        NOW + timedelta(minutes=1),
    )
    assert cleared.cleared_at == cleared.last_observed_at

    invalid_occurrences: tuple[dict[str, object], ...] = (
        {"node_id": ""},
        {"kind": "invalid"},
        {"kind": "flapping"},
        {"last_observed_at": NOW - timedelta(seconds=1)},
        {"cleared_at": NOW},
    )
    for changes in invalid_occurrences:
        with pytest.raises(ValueError):
            changed(cleared, changes)

    snapshot = ZoneModelEngine(target_map(), 1, NOW).snapshot
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(
            snapshot,
            reliability_warning_occurrences=(cleared, cleared),
        )


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


def test_v4_count_conflict_validation_boundaries() -> None:
    conflict = CountConflictState(
        "node",
        "zone",
        "episode",
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=30),
        ("support:one",),
    )
    invalid_conflict_changes: tuple[dict[str, object], ...] = (
        {"target_node_id": ""},
        {"last_evaluated_at": NOW - timedelta(seconds=1)},
        {"deadline": NOW, "last_evaluated_at": NOW},
        {"support_ids": ("support:one", "support:one")},
        {"support_ids": ()},
        {"degraded_at": NOW + timedelta(seconds=29)},
    )
    for changes in invalid_conflict_changes:
        with pytest.raises(ValueError):
            changed(conflict, changes)


def test_anonymous_support_record_validation_boundaries() -> None:
    support = AnonymousOccupancySupport(
        "support:room:episode",
        "settled",
        NOW,
        NOW + timedelta(seconds=2),
        "episode",
        "room",
        "zone",
        ("source", "hall", "room"),
        "adjacent",
        None,
        "settled",
    )
    invalid_support_changes: tuple[dict[str, object], ...] = (
        {"support_id": ""},
        {"support_id": "room:episode"},
        {"state": "invalid"},
        {"created_at": NOW.replace(tzinfo=None)},
        {"updated_at": NOW - timedelta(microseconds=1)},
        {"current_node_id": "other"},
        {"path_node_ids": ()},
        {"path_node_ids": ("one", "two", "three", "room")},
        {"valid_until": NOW + timedelta(seconds=30)},
        {"provenance_kind": "same_zone"},
        {"last_transition": "invalid"},
    )
    for changes in invalid_support_changes:
        with pytest.raises(ValueError):
            changed(support, changes)

    moving = changed(
        support,
        {
            "state": "moving",
            "valid_until": NOW + timedelta(seconds=30),
            "last_transition": "advanced",
        },
    )
    with pytest.raises(ValueError, match="requires an expiry"):
        replace(moving, valid_until=None)
    with pytest.raises(ValueError, match="must follow"):
        replace(moving, valid_until=moving.updated_at)

    binding = SupportTokenBinding("room:episode", support.support_id)
    projection = CountSupport(
        support.support_id,
        support.current_node_id,
        support.current_zone,
        support.path_node_ids,
    )
    event = SupportTransitionEvent(
        support.support_id,
        support.updated_at,
        "settled",
        "confirmed_stay",
    )
    assert SupportTransition((support,), (binding,), event).supports == (support,)
    assert projection.endpoint_zone == "zone"

    invalid_factories = (
        lambda: SupportTokenBinding("", support.support_id),
        lambda: SupportTokenBinding("token", "invalid"),
        lambda: replace(projection, support_id=""),
        lambda: replace(projection, support_id="invalid"),
        lambda: replace(projection, path_node_ids=("other",)),
        lambda: replace(event, support_id=""),
        lambda: replace(event, transition="invalid"),
        lambda: replace(event, coalesced_support_ids=("same", "same")),
        lambda: SupportTransition((support, support), (binding,)),
        lambda: SupportTransition((support,), (binding, binding)),
        lambda: SupportTransition(
            (support,), (SupportTokenBinding("other", "support:missing"),)
        ),
    )
    for factory in invalid_factories:
        with pytest.raises(ValueError):
            factory()


def test_v4_policy_phase_and_conflict_diagnostic_validation_boundaries() -> None:
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
            "count_conflict_support_ids": ("same", "same"),
            "reliability_result": "degraded",
        },
        {"reliability_result": "invalid"},
        {"count_conflict_support_ids": ("support:one",)},
    )
    for changes in invalid_row_changes:
        with pytest.raises(ValueError):
            changed(row, changes)


def test_v4_snapshot_auxiliary_state_must_be_unique_and_sorted() -> None:
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
    conflict = CountConflictState(
        "node",
        "room",
        "episode",
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=30),
        ("support:one",),
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
        {"count_conflicts": (conflict, conflict)},
        {"retained_traversal_tokens": (retained, retained)},
    )
    for changes in invalid_snapshots:
        with pytest.raises(ValueError, match="unique"):
            changed(snapshot, changes)
