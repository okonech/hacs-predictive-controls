from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.episodes import (
    ORDINARY_EPISODE_PROFILE,
    SUSTAINED_EPISODE_PROFILE,
    EpisodeProfile,
    ObservationEpisodes,
)
from custom_components.predictive_controls.model import PredictiveMap

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "occupancy_behavior": "sustained",
                    "entities": {
                        "motion": "binary_sensor.office_motion",
                        "presence": "binary_sensor.office_presence",
                    },
                }
            }
        }
    )


def event(
    entity_id: str,
    state: str,
    seconds: float,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id,
        "office",
        "office",
        "first_floor",
        "room_occupancy",
        "sustained",
        "motion",
        state,
        NOW + timedelta(seconds=seconds),
        1.0,
    )


def profile(*, burst: float, stable: float) -> EpisodeProfile:
    return replace(
        SUSTAINED_EPISODE_PROFILE,
        burst_correlation_window=timedelta(seconds=burst),
        stable_clear_window=timedelta(seconds=stable),
    )


def test_burst_and_stable_clear_windows_have_independent_semantics() -> None:
    episodes = ObservationEpisodes(
        make_map(),
        {"office": profile(burst=2, stable=7)},
    )
    first = episodes.observe(event("binary_sensor.office_motion", "on", 0))
    episodes.observe(event("binary_sensor.office_motion", "off", 1))
    second = episodes.observe(event("binary_sensor.office_motion", "on", 4))

    assert first.disposition == "accepted_positive"
    assert second.disposition == "accepted_positive"
    assert second.state.episode_id != first.state.episode_id
    assert second.state.current_positive

    inverse = ObservationEpisodes(
        make_map(),
        {"office": profile(burst=7, stable=2)},
    )
    inverse.observe(event("binary_sensor.office_motion", "on", 0))
    inverse.observe(event("binary_sensor.office_motion", "off", 1))
    at_deadline = inverse.observe(event("binary_sensor.office_motion", "on", 3))
    assert at_deadline.disposition == "accepted_positive"


def test_flaps_emit_at_most_one_positive_and_one_clear_per_episode() -> None:
    episodes = ObservationEpisodes(
        make_map(),
        {"office": profile(burst=10, stable=20)},
    )
    kinds: list[str] = []
    for state, seconds in (("on", 0), ("off", 1), ("on", 2), ("off", 3), ("on", 4)):
        update = episodes.observe(event("binary_sensor.office_motion", state, seconds))
        kinds.extend(emission.kind for emission in update.emissions)

    assert kinds.count("positive") == 1
    assert kinds.count("clear") == 1


def test_aliases_form_one_effective_physical_node_process() -> None:
    episodes = ObservationEpisodes(make_map())
    first = episodes.observe(event("binary_sensor.office_motion", "on", 0))
    alias = episodes.observe(event("binary_sensor.office_presence", "on", 1))
    partial_clear = episodes.observe(event("binary_sensor.office_motion", "off", 2))
    effective_clear = episodes.observe(event("binary_sensor.office_presence", "off", 3))

    assert [emission.kind for emission in first.emissions] == ["positive"]
    assert alias.disposition == "correlated_alias"
    assert all(emission.kind == "duration" for emission in alias.emissions)
    assert partial_clear.disposition == "correlated_alias"
    assert all(emission.kind == "duration" for emission in partial_clear.emissions)
    assert effective_clear.disposition == "accepted_clear"


def test_unavailable_is_neutral_and_off_recovery_starts_stable_clear() -> None:
    episodes = ObservationEpisodes(make_map())
    episodes.observe(event("binary_sensor.office_motion", "on", 0))
    unavailable = episodes.observe(
        event("binary_sensor.office_motion", "unavailable", 1)
    )
    recovered_off = episodes.observe(event("binary_sensor.office_motion", "off", 2))

    assert unavailable.disposition == "neutral_availability"
    assert all(emission.kind == "duration" for emission in unavailable.emissions)
    assert unavailable.state.current_positive
    assert unavailable.state.endpoint_valid_until is None
    assert recovered_off.disposition == "accepted_clear"
    assert recovered_off.state.clear_deadline == NOW + timedelta(seconds=7)


def test_neutral_availability_and_repeated_clear_do_not_add_evidence() -> None:
    baseline = ObservationEpisodes(make_map())
    neutral = baseline.observe(event("binary_sensor.office_motion", "unavailable", 0))
    clear = baseline.observe(event("binary_sensor.office_motion", "off", 1))
    assert neutral.disposition == "neutral_availability"
    assert not neutral.emissions
    assert clear.disposition == "baseline_clear"

    episodes = ObservationEpisodes(make_map())
    episodes.observe(event("binary_sensor.office_motion", "on", 0))
    episodes.observe(event("binary_sensor.office_motion", "off", 1))
    repeated = episodes.observe(event("binary_sensor.office_presence", "off", 2))
    assert repeated.disposition == "correlated_clear"
    assert all(emission.kind == "duration" for emission in repeated.emissions)


def test_duration_is_partition_invariant_and_bounded() -> None:
    frequent = ObservationEpisodes(make_map())
    single = ObservationEpisodes(make_map())
    frequent.observe(event("binary_sensor.office_motion", "on", 0))
    single.observe(event("binary_sensor.office_motion", "on", 0))

    frequent_total = math.fsum(
        emission.occupied_log_likelihood
        for second in (100, 200, 300)
        for update in frequent.advance(NOW + timedelta(seconds=second))
        for emission in update.emissions
    )
    single_total = math.fsum(
        emission.occupied_log_likelihood
        for update in single.advance(NOW + timedelta(seconds=300))
        for emission in update.emissions
    )
    expected = SUSTAINED_EPISODE_PROFILE.duration_max_log_odds * (
        1.0 - math.exp(-1.0)
    )

    assert frequent_total == pytest.approx(expected)
    assert single_total == pytest.approx(expected)
    assert frequent.states == single.states


def test_duplicate_burst_and_timer_frequency_do_not_change_duration_evidence() -> None:
    burst = ObservationEpisodes(make_map())
    single = ObservationEpisodes(make_map())
    accepted = event("binary_sensor.office_motion", "on", 0)
    burst.observe(accepted)
    single.observe(accepted)
    for second in range(1, 11):
        duplicate = burst.observe(
            event("binary_sensor.office_motion", "on", second / 10)
        )
        assert duplicate.disposition == "duplicate"

    first = burst.advance(NOW + timedelta(seconds=60))
    assert not burst.advance(NOW + timedelta(seconds=60))
    delayed = single.advance(NOW + timedelta(seconds=60))

    assert first == delayed
    assert burst.states == single.states
    assert sum(
        emission.occupied_log_likelihood
        for update in first
        for emission in update.emissions
    ) < SUSTAINED_EPISODE_PROFILE.duration_max_log_odds


def test_delayed_timer_finalizes_at_event_time_deadline() -> None:
    episodes = ObservationEpisodes(make_map())
    episodes.observe(event("binary_sensor.office_motion", "on", 0))
    cleared = episodes.observe(event("binary_sensor.office_motion", "off", 30))
    assert cleared.state.clear_deadline == NOW + timedelta(seconds=35)

    delayed = episodes.advance(NOW + timedelta(minutes=10))[0]

    assert delayed.state.status == "finalized"
    assert delayed.state.finalized_at == NOW + timedelta(seconds=35)
    assert not episodes.advance(NOW + timedelta(minutes=10))


def test_stable_clear_boundary_is_independent_of_timer_order() -> None:
    first = ObservationEpisodes(make_map())
    second = ObservationEpisodes(make_map())
    for episodes in (first, second):
        episodes.observe(event("binary_sensor.office_motion", "on", 0))
        episodes.observe(event("binary_sensor.office_motion", "off", 1))

    first.advance(NOW + timedelta(seconds=6))
    first_update = first.observe(event("binary_sensor.office_motion", "on", 6))
    second_update = second.observe(event("binary_sensor.office_motion", "on", 6))

    assert first_update.disposition == "accepted_positive"
    assert second_update.disposition == "accepted_positive"
    assert first_update.state == second_update.state


@pytest.mark.parametrize("state", ("on", "off", "unavailable"))
def test_episode_state_round_trips_during_every_active_frontier(state: str) -> None:
    original = ObservationEpisodes(make_map())
    original.observe(event("binary_sensor.office_motion", "on", 0))
    original.advance(NOW + timedelta(seconds=2))
    if state != "on":
        original.observe(event("binary_sensor.office_motion", state, 3))

    restored = ObservationEpisodes(make_map())
    restored.restore(original.serialize())

    assert restored.states == original.states
    assert restored.advance(NOW + timedelta(seconds=6)) == original.advance(
        NOW + timedelta(seconds=6)
    )


def test_episode_restore_rejects_corruption_atomically() -> None:
    episodes = ObservationEpisodes(make_map())
    payload = episodes.serialize()
    corrupted = [{**item} for item in payload]
    corrupted[0]["profile"] = {}

    with pytest.raises(ValueError, match="profile"):
        episodes.restore(corrupted)
    assert episodes.serialize() == payload


def test_episode_profile_rejects_invalid_calibration() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        replace(
            SUSTAINED_EPISODE_PROFILE,
            burst_correlation_window=timedelta(seconds=-1),
        )
    with pytest.raises(ValueError, match="likelihoods"):
        replace(SUSTAINED_EPISODE_PROFILE, on_empty=0.0)
    with pytest.raises(ValueError, match="ceiling"):
        replace(SUSTAINED_EPISODE_PROFILE, duration_max_log_odds=math.inf)
    with pytest.raises(ValueError, match="tau"):
        replace(
            SUSTAINED_EPISODE_PROFILE,
            duration_tau=timedelta(0),
            duration_max_log_odds=1.0,
        )


def test_episode_event_validation_and_stale_input_are_model_neutral() -> None:
    episodes = ObservationEpisodes(make_map())
    accepted = episodes.observe(event("binary_sensor.office_motion", "on", 2))
    before = episodes.states
    stale = episodes.observe(event("binary_sensor.office_motion", "off", 1))
    duplicate = episodes.observe(event("binary_sensor.office_motion", "on", 3))

    assert accepted.state.endpoint_valid_until == NOW + timedelta(seconds=32)
    assert stale.disposition == "stale"
    assert duplicate.disposition == "duplicate"
    assert episodes.states == before

    invalid = event("binary_sensor.office_motion", "off", 4)
    with pytest.raises(ValueError, match="node is not"):
        episodes.observe(replace(invalid, node_id="missing"))
    with pytest.raises(ValueError, match="zone does not match"):
        episodes.observe(replace(invalid, zone="missing"))
    with pytest.raises(ValueError, match="not an alias"):
        episodes.observe(replace(invalid, entity_id="binary_sensor.missing"))
    with pytest.raises(ValueError, match="UTC"):
        episodes.observe(replace(invalid, event_at=datetime(2026, 7, 17)))


def test_ordinary_and_transition_profiles_emit_no_duration() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "ordinary": {
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": "binary_sensor.ordinary"},
                },
                "gate": {
                    "role": "transition_gate",
                    "entities": {"motion": "binary_sensor.gate"},
                },
            }
        }
    )
    episodes = ObservationEpisodes(predictive_map)
    for node_id in ("ordinary", "gate"):
        episodes.observe(
            OccupancyEvent(
                f"binary_sensor.{node_id}",
                node_id,
                node_id,
                None,
                "transition_gate" if node_id == "gate" else "room_occupancy",
                "transient" if node_id == "gate" else "ambiguous",
                "motion",
                "on",
                NOW,
                1.0,
            )
        )

    updates = episodes.advance(NOW + timedelta(hours=1))
    assert all(not update.emissions for update in updates)

    explicit = ObservationEpisodes(
        make_map(),
        {"office": ORDINARY_EPISODE_PROFILE},
    )
    explicit.observe(event("binary_sensor.office_motion", "on", 0))
    assert not explicit.advance(NOW + timedelta(hours=1))[0].emissions


def test_cold_snapshot_is_atomic_and_alias_order_independent() -> None:
    snapshot = (
        event("binary_sensor.office_motion", "off", 0),
        event("binary_sensor.office_presence", "on", 0),
    )
    first = ObservationEpisodes(make_map())
    second = ObservationEpisodes(make_map())

    first_updates = first.bootstrap(snapshot, cold_start=True)
    second_updates = second.bootstrap(tuple(reversed(snapshot)), cold_start=True)

    assert first.states == second.states
    assert first_updates == second_updates
    assert [
        emission.kind for update in first_updates for emission in update.emissions
    ] == ["positive"]
    assert first.bootstrap(snapshot, cold_start=True) == ()


def test_restored_alias_swap_does_not_create_edge_evidence() -> None:
    episodes = ObservationEpisodes(make_map())
    episodes.bootstrap(
        (
            event("binary_sensor.office_motion", "on", 0),
            event("binary_sensor.office_presence", "off", 0),
        ),
        cold_start=True,
    )
    swapped = episodes.bootstrap(
        (
            event("binary_sensor.office_motion", "off", 1),
            event("binary_sensor.office_presence", "on", 1),
        ),
        cold_start=False,
    )

    assert len(swapped) == 1
    assert all(emission.kind == "duration" for emission in swapped[0].emissions)
    assert swapped[0].state.current_positive
    assert swapped[0].state.clear_deadline is None


def test_snapshot_reconciles_every_episode_frontier_without_synthetic_edges() -> None:
    episodes = ObservationEpisodes(make_map())
    cold_clear = episodes.bootstrap(
        (event("binary_sensor.office_motion", "off", 0),),
        cold_start=True,
    )[0]
    assert cold_clear.state.status == "baseline"
    warm_clear = episodes.bootstrap(
        (event("binary_sensor.office_presence", "off", 1),),
        cold_start=False,
    )[0]
    assert warm_clear.state.last_inactive_at == NOW + timedelta(seconds=1)

    asserted = ObservationEpisodes(make_map())
    asserted.observe(event("binary_sensor.office_motion", "on", 0))
    alias_asserted = asserted.bootstrap(
        (event("binary_sensor.office_presence", "on", 1),),
        cold_start=False,
    )[0]
    assert alias_asserted.state.status == "asserted"
    cleared = asserted.bootstrap(
        (
            event("binary_sensor.office_motion", "off", 2),
            event("binary_sensor.office_presence", "off", 2),
        ),
        cold_start=False,
    )[0]
    assert [emission.kind for emission in cleared.emissions] == ["duration", "clear"]
    repeated_clear = asserted.bootstrap(
        (event("binary_sensor.office_motion", "unknown", 3),),
        cold_start=False,
    )[0]
    assert all(emission.kind == "duration" for emission in repeated_clear.emissions)
    unavailable = asserted.bootstrap(
        (event("binary_sensor.office_presence", "unavailable", 4),),
        cold_start=False,
    )[0]
    assert unavailable.state.status == "unavailable"

    one_clear = ObservationEpisodes(make_map())
    one_clear.observe(event("binary_sensor.office_motion", "on", 0))
    one_clear.bootstrap(
        (event("binary_sensor.office_motion", "off", 1),),
        cold_start=False,
    )
    second_alias_clear = one_clear.bootstrap(
        (event("binary_sensor.office_presence", "off", 2),),
        cold_start=False,
    )[0]
    assert all(emission.kind == "duration" for emission in second_alias_clear.emissions)

    correlated = ObservationEpisodes(make_map())
    correlated.observe(event("binary_sensor.office_motion", "on", 0))
    correlated.observe(event("binary_sensor.office_motion", "off", 1))
    resumed = correlated.bootstrap(
        (event("binary_sensor.office_motion", "on", 2),),
        cold_start=False,
    )[0]
    assert resumed.state.episode_id == "office@2026-07-17T00:00:00+00:00"
    assert not resumed.emissions


def test_snapshot_and_timer_validation_are_atomic_and_time_neutral() -> None:
    episodes = ObservationEpisodes(make_map())
    payload = episodes.serialize()
    duplicate = event("binary_sensor.office_motion", "off", 0)
    with pytest.raises(ValueError, match="duplicate"):
        episodes.bootstrap((duplicate, duplicate), cold_start=True)
    with pytest.raises(ValueError, match="UTC"):
        episodes.bootstrap(
            (replace(duplicate, event_at=datetime(2026, 7, 17)),),
            cold_start=True,
        )
    assert episodes.serialize() == payload

    episodes.observe(event("binary_sensor.office_motion", "on", 2))
    before = episodes.states
    assert not episodes.advance(NOW + timedelta(seconds=1))
    assert episodes.states == before


@pytest.mark.parametrize(
    ("kind", "message"),
    (
        ("not_list", "must be a list"),
        ("not_mapping", "must be a mapping"),
        ("node", "node"),
        ("duplicate", "duplicated"),
        ("zone", "zone"),
        ("aliases", "aliases"),
        ("alias_state", "alias state"),
        ("episode_id", "episode ID"),
        ("status", "status"),
        ("flag", "flags"),
        ("asserted", "asserted duration"),
        ("asserted_bool", "asserted duration"),
        ("duration", "duration likelihood"),
        ("duration_ceiling", "exceeds"),
        ("datetime_type", "datetime"),
        ("datetime_value", "datetime"),
        ("datetime_utc", "UTC"),
        ("baseline_active", "baseline"),
        ("deadline", "clear deadline"),
        ("ordering", "ordering"),
    ),
)
def test_episode_restore_rejects_invalid_payloads_atomically(
    kind: str,
    message: str,
) -> None:
    episodes = ObservationEpisodes(make_map())
    payload = episodes.serialize()
    corrupted: object
    item = {**payload[0]}
    if kind == "not_list":
        corrupted = "bad"
    elif kind == "not_mapping":
        corrupted = [1]
    elif kind == "duplicate":
        corrupted = [item, item]
    else:
        if kind == "node":
            item["node_id"] = "missing"
        elif kind == "zone":
            item["zone"] = "missing"
        elif kind == "aliases":
            item["raw_alias_states"] = {}
        elif kind == "alias_state":
            raw_aliases = item["raw_alias_states"]
            assert isinstance(raw_aliases, dict)
            aliases = {str(key): str(value) for key, value in raw_aliases.items()}
            aliases["binary_sensor.office_motion"] = "bad"
            item["raw_alias_states"] = aliases
        elif kind == "episode_id":
            item["episode_id"] = 1
        elif kind == "status":
            item["status"] = "bad"
        elif kind == "flag":
            item["current_positive"] = 1
        elif kind == "asserted":
            item["asserted_seconds"] = -1
        elif kind == "asserted_bool":
            item["asserted_seconds"] = True
        elif kind == "duration":
            item["applied_duration_log_odds"] = math.inf
        elif kind == "duration_ceiling":
            item["applied_duration_log_odds"] = (
                SUSTAINED_EPISODE_PROFILE.duration_max_log_odds + 1.0
            )
        elif kind == "datetime_type":
            item["last_event_at"] = 1
        elif kind == "datetime_value":
            item["last_event_at"] = "not-a-datetime"
        elif kind == "datetime_utc":
            item["last_event_at"] = "2026-07-17T00:00:00"
        elif kind == "baseline_active":
            item["current_positive"] = True
        elif kind == "deadline":
            item["clear_deadline"] = NOW.isoformat()
        else:
            item["episode_id"] = "episode"
            item["started_at"] = NOW.isoformat()
            item["last_event_at"] = (NOW - timedelta(seconds=1)).isoformat()
        corrupted = [item]

    with pytest.raises((TypeError, ValueError), match=message):
        episodes.restore(corrupted)
    assert episodes.serialize() == payload
