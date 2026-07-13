from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.observation_model import (
    EntityEvidence,
    ObservationModel,
)

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_event(**changes: object) -> OccupancyEvent:
    values: dict[str, object] = {
        "entity_id": "binary_sensor.office_motion",
        "node_id": "office_motion",
        "zone": "office",
        "floor": "second_floor",
        "role": "room_occupancy",
        "occupancy_behavior": "sustained",
        "signal_type": "motion",
        "state": "on",
        "event_at": NOW,
        "reliability": 0.8,
    }
    values.update(changes)
    return OccupancyEvent(**values)  # type: ignore[arg-type]


def test_observation_scenario_replaces_flaps_and_deduplicates_same_source() -> None:
    model = ObservationModel(2, correlation_window=timedelta(minutes=5))
    on_event = make_event()

    accepted = model.prepare_delta(on_event)
    duplicate = model.prepare_delta(
        replace(on_event, event_at=NOW + timedelta(seconds=1))
    )
    cleared = model.prepare_delta(
        replace(on_event, state="off", event_at=NOW + timedelta(seconds=2))
    )
    new_episode = model.prepare_delta(
        replace(on_event, event_at=NOW + timedelta(minutes=10))
    )

    assert accepted.disposition == "accepted"
    assert accepted.log_likelihood_by_count[1] > accepted.log_likelihood_by_count[0]
    assert duplicate.disposition == "duplicate"
    assert duplicate.log_likelihood_by_count == (0.0, 0.0, 0.0)
    assert cleared.disposition == "replacement"
    assert cleared.log_likelihood_by_count[0] > cleared.log_likelihood_by_count[1]
    assert new_episode.disposition == "replacement"
    assert new_episode.evidence_episode_id.endswith("2026-07-12T12:10:00+00:00")
    assert model.entity_states[on_event.entity_id].state == "on"


@pytest.mark.parametrize(
    ("changes", "occupied_probability", "empty_probability"),
    (
        ({"signal_type": "still_target"}, 0.97, 0.02),
        ({"occupancy_behavior": "sticky"}, 0.97, 0.02),
        ({"occupancy_behavior": "transient"}, 0.85, 0.05),
        ({"role": "transition_gate"}, 0.85, 0.05),
        ({}, 0.97, 0.02),
        ({"occupancy_behavior": "ambiguous"}, 0.90, 0.04),
    ),
)
def test_observation_profiles_are_selected_by_sensor_semantics(
    changes: dict[str, object],
    occupied_probability: float,
    empty_probability: float,
) -> None:
    model = ObservationModel(1)
    event = make_event(reliability=1.0, **changes)

    provenance = model.prepare_delta(event)

    assert provenance.log_likelihood_by_count == pytest.approx(
        (math.log(empty_probability), math.log(occupied_probability))
    )


def test_observation_model_handles_neutral_states_counts_and_restore_validation() -> (
    None
):
    with pytest.raises(ValueError, match="non-negative"):
        ObservationModel(-1)
    model = ObservationModel(1)
    ignored = model.prepare_delta(make_event(state="unavailable"))
    assert ignored.disposition == "ignored"
    assert ignored.log_likelihood_by_count == (0.0, 0.0)

    model.set_expected_occupants(1)
    accepted = model.prepare_delta(make_event(reliability=2.0))
    assert accepted.log_likelihood_by_count == pytest.approx(
        (math.log(0.02), math.log(0.97))
    )
    model.set_expected_occupants(2)
    assert model.entity_states == {}
    low_reliability = model.prepare_delta(
        make_event(entity_id="binary_sensor.other", reliability=-1.0)
    )
    assert low_reliability.log_likelihood_by_count == pytest.approx(
        (math.log(0.5), math.log(0.5), math.log(0.5))
    )

    valid = {
        "binary_sensor.restored": EntityEvidence(
            "off",
            (math.log(0.5),) * 3,
            NOW,
            NOW,
        )
    }
    model.restore_entity_states(valid)
    assert model.entity_states == valid
    with pytest.raises(ValueError, match="vector length"):
        model.restore_entity_states(
            {"bad": replace(next(iter(valid.values())), log_likelihood_by_count=(0.0,))}
        )
    with pytest.raises(ValueError, match="non-negative"):
        model.set_expected_occupants(-1)


def test_duration_and_departure_ignore_missing_inactive_or_invalidated_episodes() -> (
    None
):
    model = ObservationModel(1)
    assert model.apply_duration_log_odds("missing", 1.0) == 0.0
    assert model.invalidate_asserted_episode("missing") == (0.0, 0.0)

    model.restore_entity_states(
        {
            "binary_sensor.orphan": EntityEvidence(
                "on",
                (math.log(0.02), math.log(0.97)),
                NOW,
                NOW,
            )
        }
    )
    assert model.apply_duration_log_odds("binary_sensor.orphan", 1.0) == 0.0
    assert model.invalidate_asserted_episode("binary_sensor.orphan") == (0.0, 0.0)

    off = make_event(state="off")
    model.prepare_delta(off)
    assert model.apply_duration_log_odds(off.entity_id, 1.0) == 0.0
    assert model.invalidate_asserted_episode(off.entity_id) == (0.0, 0.0)

    on = replace(off, state="on", event_at=NOW + timedelta(seconds=1))
    model.prepare_delta(on)
    assert model.invalidate_asserted_episode(on.entity_id) != (0.0, 0.0)
    assert model.apply_duration_log_odds(on.entity_id, 1.0) == 0.0
    assert model.invalidate_asserted_episode(on.entity_id) == (0.0, 0.0)


def test_snapshot_removes_previous_factor_for_unsupported_state() -> None:
    model = ObservationModel(1)
    model.prepare_delta(make_event())

    removed = model.prepare_snapshot_delta(make_event(state="unavailable"))

    assert removed.disposition == "replacement"
    assert removed.log_likelihood_by_count[0] > 0
    assert model.entity_states == {}

    zero_count = ObservationModel(0)
    zero_count.prepare_delta(make_event())
    assert zero_count.entity_states


def test_correlated_alias_clear_preserves_one_asserted_node_factor() -> None:
    model = ObservationModel(2)
    first = make_event(
        entity_id="binary_sensor.office_target",
        occupancy_behavior="ambiguous",
    )
    alias = make_event(
        entity_id="binary_sensor.office_still",
        occupancy_behavior="ambiguous",
        signal_type="still_target",
    )

    model.prepare_delta(first)
    correlated = model.prepare_delta(alias)
    cleared = model.prepare_delta(
        replace(first, state="off", event_at=NOW + timedelta(seconds=1))
    )

    assert correlated.disposition == "correlated_alias"
    assert correlated.log_likelihood_by_count != (0.0, 0.0, 0.0)
    assert cleared.log_likelihood_by_count == (0.0, 0.0, 0.0)
    assert model.entity_states[alias.entity_id].state == "on"

    removed_alias = model.prepare_snapshot_delta(
        replace(alias, state="unavailable", event_at=NOW + timedelta(seconds=2))
    )
    assert removed_alias.log_likelihood_by_count[0] > 0
