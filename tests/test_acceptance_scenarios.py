from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)
from tests.test_zone_model_engine import target_map

NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def occupied_engine() -> ZoneModelEngine:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    return engine


def test_s16_s17_positive_count_changes_invent_no_zone_and_select_no_release() -> None:
    engine = occupied_engine()

    increased = engine.observe_count(
        CountInput("count:2", 2, True, NOW + timedelta(seconds=3))
    )
    decreased = engine.observe_count(
        CountInput("count:1", 1, True, NOW + timedelta(seconds=4))
    )

    assert increased.policy_events == ()
    assert decreased.policy_events == ()
    assert {state.zone: state.active for state in decreased.snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }


def test_s18_count_zero_clears_policy_frontier_and_prediction_inputs() -> None:
    engine = occupied_engine()

    result = engine.observe_count(
        CountInput("count:0", 0, True, NOW + timedelta(seconds=3))
    )

    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("room", "released")
    ]
    assert result.snapshot.traversal_tokens == ()
    assert all(not state.active for state in result.snapshot.policy_states)


def test_s19_restart_preserves_active_seed_without_bootstrap_edge() -> None:
    engine = occupied_engine()
    payload = serialize_target_state(target_map(), engine)

    restored = restore_target_state(target_map(), payload, NOW + timedelta(minutes=1))

    assert restored.snapshot.policy_states[1].active is True
    assert restored.advance(NOW + timedelta(minutes=1)).policy_events == ()


def test_s20_corrupt_restore_is_atomic_and_diagnostic() -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    corrupt = deepcopy(payload)
    corrupt["map_fingerprint"] = "wrong"
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))

    assert not tracker.restore_state(corrupt, NOW + timedelta(seconds=3))
    assert tracker.diagnostics.restore_status == "rejected"
    assert tracker.diagnostics.beliefs == {}


def test_s26_prediction_state_cannot_change_occupancy_or_policy() -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    prediction = payload["prediction"]
    assert isinstance(prediction, dict)
    prediction["leases"] = []
    tracker = OccupancyTracker(target_map(), TrackerConfig(1))

    assert tracker.restore_state(payload, NOW + timedelta(seconds=3))
    assert tracker.diagnostics.policy_states["room"].active is True
    assert tracker.diagnostics.prediction_probabilities == {}


def test_s29_s30_elapsed_time_degrades_hall_but_preserves_held_stay() -> None:
    """Historical ID; HEALTH001/003 now keep this supported pair warning-free.

    Synthetic occupied_engine inputs and the two-hour retention checkpoint stay.
    The named unsupported inverse in test_reliability retains warning coverage.
    """
    engine = occupied_engine()

    result = engine.advance(NOW + timedelta(hours=2))

    assert {state.zone: state.active for state in result.snapshot.policy_states} == {
        "hall": False,
        "room": True,
    }
    episodes = {state.node_id: state for state in result.snapshot.episode_states}
    assert not episodes["hall"].health_warning
    assert not episodes["room"].health_warning
    assert result.snapshot.reliability_warning_occurrences == ()


def test_selected_endpoint_off_and_time_cannot_release_active_room() -> None:
    """Synthetic PATH002 equivalent; not a reconstructed historical S29 incident.

    Only hall ON0, room ON2, room OFF3 are supplied. No selected onward movement
    exists to displace the room endpoint. This extends the user-approved S29
    no-movement expectation to two hours without claiming captured incident data.
    """
    engine = occupied_engine()
    assert engine.snapshot.policy_states[1].active
    cleared = engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3))
    )
    assert cleared.snapshot.policy_states[1].active
    assert cleared.policy_events == ()

    for at in (NOW + timedelta(minutes=12), NOW + timedelta(hours=2)):
        result = engine.advance(at)
        assert result.snapshot.policy_states[1].active
        assert result.policy_events == ()


def test_s29_elapsed_time_and_low_confidence_preserve_public_keep_on() -> None:
    """Synthetic S29: user-approved PATH002 retention amendment, 2026-09-13.

    No sourced incident was established for the historical name. Preserve the
    hall ON0, room ON2, room OFF3 sequence and original 12-minute checkpoint:
    sensor OFF and elapsed time cannot remove the only selected endpoint.
    """

    engine = occupied_engine()
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))

    result = engine.advance(NOW + timedelta(minutes=12))

    assert {state.zone: state.active for state in result.snapshot.policy_states}[
        "room"
    ]
    assert result.policy_events == ()


def test_s30_asserted_local_motion_preserves_keep_on_through_expiry() -> None:
    """A current held room assertion remains strong bounded local evidence."""

    result = occupied_engine().advance(NOW + timedelta(hours=2))

    assert {state.zone: state.active for state in result.snapshot.policy_states}[
        "room"
    ]
    room = next(
        state for state in result.snapshot.episode_states if state.node_id == "room"
    )
    assert room.status == "asserted"
    assert not room.health_warning


def test_s31_sustained_room_confidence_survives_untracked_flaps() -> None:
    engine = occupied_engine()

    duplicate = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=3))
    )

    assert duplicate.disposition == "duplicate"
    assert duplicate.snapshot.policy_states[1].active is True
