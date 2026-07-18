from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.types import (
    PhysicalNode,
    SensorInput,
)

NOW = datetime(2026, 7, 18, 9, tzinfo=UTC)


def sensor(
    entity_id: str,
    state: str,
    seconds: float,
) -> SensorInput:
    return SensorInput(entity_id, state, NOW + timedelta(seconds=seconds))


def episodes(*, profile: str = "transition_fast") -> PhysicalEpisodes:
    return PhysicalEpisodes(
        (
            PhysicalNode(
                "node",
                "zone",
                ("binary_sensor.a", "binary_sensor.b"),
                profile,
            ),
        )
    )


def test_aliases_and_same_state_callbacks_emit_one_positive() -> None:
    model = episodes()

    first = model.observe(sensor("binary_sensor.a", "on", 0))
    alias = model.observe(sensor("binary_sensor.b", "on", 1))
    duplicate = model.observe(sensor("binary_sensor.b", "on", 2))
    partial_clear = model.observe(sensor("binary_sensor.a", "off", 3))

    assert first.disposition == "accepted_positive"
    assert [effect.kind for effect in first.effects] == ["positive"]
    assert first.state.generation == 1
    assert first.state.hold_until == NOW + timedelta(seconds=15)
    assert first.state.traversal_valid_until == NOW + timedelta(seconds=45)
    assert alias.disposition == "correlated_alias"
    assert duplicate.disposition == "duplicate"
    assert partial_clear.disposition == "correlated_alias"
    assert not alias.effects and not duplicate.effects and not partial_clear.effects


@pytest.mark.parametrize(
    ("profile", "stable_clear_seconds"),
    [
        ("transition_fast", 5),
        ("stay_pir", 5),
        ("stay_presence", 10),
        ("entry_boundary", 5),
    ],
)
def test_stable_clear_is_delayed_and_frontier_is_idempotent(
    profile: str,
    stable_clear_seconds: int,
) -> None:
    model = episodes(profile=profile)
    model.observe(sensor("binary_sensor.a", "on", 0))
    clear = model.observe(sensor("binary_sensor.a", "off", 10))

    deadline = NOW + timedelta(seconds=10 + stable_clear_seconds)
    before = model.advance(deadline - timedelta(microseconds=1))[0]
    at_deadline = model.advance(deadline)[0]
    repeated = model.advance(deadline)[0]

    assert clear.disposition == "clear_pending"
    assert clear.effects == ()
    assert before.effects == ()
    assert at_deadline.state.status == "clear"
    assert [effect.kind for effect in at_deadline.effects] == ["stable_clear"]
    assert repeated.disposition == "unchanged"
    assert repeated.effects == ()


def test_flap_reassertion_reuses_episode_but_later_positive_starts_another() -> None:
    model = episodes()
    first = model.observe(sensor("binary_sensor.a", "on", 0))
    model.observe(sensor("binary_sensor.a", "off", 10))
    flap = model.observe(sensor("binary_sensor.a", "on", 12))
    model.observe(sensor("binary_sensor.a", "off", 20))
    later = model.observe(sensor("binary_sensor.a", "on", 24))

    assert flap.disposition == "correlated_reassertion"
    assert flap.state.episode_id == first.state.episode_id
    assert flap.state.traversal_valid_until == first.state.traversal_valid_until
    assert flap.effects == ()
    assert later.disposition == "accepted_positive"
    assert later.state.generation == 2
    assert [effect.kind for effect in later.effects] == ["positive"]


def test_unavailable_is_neutral_and_closes_traversal_authority() -> None:
    model = episodes()
    model.observe(sensor("binary_sensor.a", "on", 0))

    unavailable = model.observe(sensor("binary_sensor.a", "unavailable", 10))
    recovery_clear = model.observe(sensor("binary_sensor.a", "off", 11))

    assert unavailable.disposition == "neutral_availability"
    assert unavailable.state.status == "unavailable"
    assert unavailable.state.traversal_valid_until is None
    assert unavailable.effects == ()
    assert recovery_clear.disposition == "baseline_clear"
    assert recovery_clear.effects == ()


@pytest.mark.parametrize("unavailable_state", ["unknown", "unavailable"])
def test_availability_recovery_starts_a_new_episode(
    unavailable_state: str,
) -> None:
    model = episodes()
    first = model.observe(sensor("binary_sensor.a", "on", 0))
    model.observe(sensor("binary_sensor.a", unavailable_state, 10))

    recovered = model.observe(sensor("binary_sensor.a", "on", 11))

    assert recovered.disposition == "accepted_positive"
    assert recovered.state.generation == first.state.generation + 1
    assert [effect.kind for effect in recovered.effects] == ["positive"]


@pytest.mark.parametrize(
    "profile",
    ["transition_fast", "stay_pir", "stay_presence", "entry_boundary"],
)
def test_assertion_trust_horizon_degrades_once_for_every_profile(profile: str) -> None:
    model = episodes(profile=profile)
    asserted = model.observe(sensor("binary_sensor.a", "on", 0))
    horizon = asserted.state.assertion_trust_until
    assert horizon is not None

    before = model.advance(horizon - timedelta(microseconds=1))[0]
    degraded = model.advance(horizon)[0]
    repeated = model.advance(horizon + timedelta(hours=1))[0]

    assert before.effects == ()
    assert degraded.state.status == "degraded"
    assert degraded.state.traversal_valid_until is None
    assert [effect.kind for effect in degraded.effects] == ["health_degraded"]
    assert repeated.effects == ()


def test_new_episode_recovers_health_after_stuck_assertion() -> None:
    model = episodes()
    first = model.observe(sensor("binary_sensor.a", "on", 0))
    assert first.state.assertion_trust_until is not None
    model.advance(first.state.assertion_trust_until)
    model.observe(sensor("binary_sensor.a", "off", 61))
    model.advance(NOW + timedelta(seconds=66))

    recovered = model.observe(sensor("binary_sensor.a", "on", 70))

    assert recovered.state.status == "asserted"
    assert [effect.kind for effect in recovered.effects] == [
        "health_recovered",
        "positive",
    ]


def test_stale_duplicate_and_invalid_inputs_are_model_neutral() -> None:
    model = episodes()
    accepted = model.observe(sensor("binary_sensor.a", "on", 2))
    snapshot = model.states

    stale = model.observe(sensor("binary_sensor.a", "off", 1))
    duplicate = model.observe(sensor("binary_sensor.a", "on", 3))

    assert accepted.disposition == "accepted_positive"
    assert stale.disposition == "stale"
    assert duplicate.disposition == "duplicate"
    assert model.states == snapshot
    with pytest.raises(ValueError, match="not mapped"):
        model.observe(sensor("binary_sensor.missing", "on", 4))
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        model.advance(NOW.replace(tzinfo=None))


def test_snapshot_restore_and_time_advancement_are_deterministic() -> None:
    uninterrupted = episodes(profile="stay_pir")
    uninterrupted.observe(sensor("binary_sensor.a", "on", 0))
    uninterrupted.observe(sensor("binary_sensor.a", "off", 30))

    restored = episodes(profile="stay_pir")
    restored.restore_snapshot(uninterrupted.states)
    frontier = NOW + timedelta(seconds=35)

    assert restored.advance(frontier) == uninterrupted.advance(frontier)
    assert restored.states == uninterrupted.states
    with pytest.raises(ValueError, match="incompatible"):
        episodes().restore_snapshot(())


def test_constructor_rejects_duplicate_nodes_and_aliases() -> None:
    first = PhysicalNode("first", "zone", ("binary_sensor.first",), "stay_pir")
    duplicate_node = PhysicalNode(
        "first",
        "other",
        ("binary_sensor.other",),
        "stay_pir",
    )
    duplicate_alias = PhysicalNode(
        "second",
        "other",
        ("binary_sensor.first",),
        "stay_pir",
    )

    with pytest.raises(ValueError, match="nodes must be unique"):
        PhysicalEpisodes((first, duplicate_node))
    with pytest.raises(ValueError, match="aliases must map to one node"):
        PhysicalEpisodes((first, duplicate_alias))


def test_availability_and_baseline_clear_cover_alias_aggregation() -> None:
    model = episodes()
    baseline = model.observe(sensor("binary_sensor.a", "off", 0))
    model.observe(sensor("binary_sensor.a", "on", 1))
    model.observe(sensor("binary_sensor.b", "on", 2))
    partial_unavailable = model.observe(sensor("binary_sensor.a", "unknown", 3))

    assert baseline.disposition == "baseline_clear"
    assert partial_unavailable.disposition == "neutral_availability"
    assert partial_unavailable.state.status == "asserted"
    assert partial_unavailable.state.known_on


def test_unavailable_during_pending_clear_closes_traversal() -> None:
    model = episodes()
    model.observe(sensor("binary_sensor.a", "on", 0))
    clearing = model.observe(sensor("binary_sensor.a", "off", 10))
    unavailable = model.observe(sensor("binary_sensor.b", "unavailable", 11))

    assert clearing.state.traversal_valid_until is not None
    assert unavailable.state.status == "clearing"
    assert unavailable.state.traversal_valid_until is None


def test_stale_frontier_and_restore_validation_are_deterministic() -> None:
    model = episodes()
    model.observe(sensor("binary_sensor.a", "on", 2))
    state = model.states[0]

    assert model.advance(NOW + timedelta(seconds=1))[0].disposition == "stale"

    invalid_states = (
        replace(state, zone="other"),
        replace(state, profile_name="custom"),
        replace(state, status="invented"),
        replace(state, generation=-1),
        replace(state, generation=0),
        replace(state, episode_id=None),
        replace(state, episode_id="invented"),
        replace(state, hold_until=state.started_at),
        replace(state, assertion_trust_until=state.started_at),
        replace(state, traversal_valid_until=state.started_at),
        replace(state, advanced_at=None),
        replace(state, advanced_at=NOW, last_event_at=NOW + timedelta(seconds=2)),
        replace(state, alias_states=tuple(reversed(state.alias_states))),
        replace(
            state,
            alias_states=(
                ("binary_sensor.a", "off"),
                ("binary_sensor.b", "unknown"),
            ),
        ),
        replace(state, health_warning=True),
        replace(
            state,
            status="degraded",
            health_warning=False,
            degraded_at=None,
            traversal_valid_until=None,
        ),
        replace(
            state,
            status="clearing",
            alias_states=(
                ("binary_sensor.a", "off"),
                ("binary_sensor.b", "unknown"),
            ),
            clear_started_at=None,
            clear_deadline=None,
        ),
        replace(
            state,
            status="clear",
            alias_states=(
                ("binary_sensor.a", "off"),
                ("binary_sensor.b", "unknown"),
            ),
            clear_emitted=False,
            traversal_valid_until=None,
        ),
        replace(
            state,
            status="unavailable",
            alias_states=(
                ("binary_sensor.a", "unavailable"),
                ("binary_sensor.b", "unknown"),
            ),
        ),
        replace(
            state,
            alias_states=(
                ("binary_sensor.a", "on"),
                ("binary_sensor.a", "off"),
                ("binary_sensor.b", "unknown"),
            ),
        ),
        replace(
            state,
            alias_states=(
                ("binary_sensor.a", "invalid"),
                ("binary_sensor.b", "unknown"),
            ),
        ),
        replace(state, started_at=NOW.replace(tzinfo=None)),
    )
    messages = (
        "incompatible",
        "unknown profile",
        "status is invalid",
        "generation is invalid",
        "identity is invalid",
        "identity is incomplete",
        "identity is not deterministic",
        "hold frontier is inconsistent",
        "trust frontier is inconsistent",
        "traversal frontier is inconsistent",
        "event frontier is incomplete",
        "frontiers are inconsistent",
        "aliases are not deterministic",
        "Asserted episode snapshot is inconsistent",
        "health state is inconsistent",
        "Degraded episode snapshot is inconsistent",
        "Clearing episode snapshot is inconsistent",
        "clear state is inconsistent",
        "Unavailable episode snapshot has traversal authority",
        "aliases are duplicated",
        "alias state is invalid",
        "must be timezone-aware UTC",
    )
    for invalid_state, message in zip(invalid_states, messages, strict=True):
        target = episodes()
        with pytest.raises(ValueError, match=message):
            target.restore_snapshot((invalid_state,))


def test_restore_rejects_impossible_clear_and_degradation_frontiers() -> None:
    model = episodes()
    asserted = model.observe(sensor("binary_sensor.a", "on", 0)).state
    model.observe(sensor("binary_sensor.a", "off", 10))
    clearing = model.states[0]
    assert asserted.assertion_trust_until is not None
    model.restore_snapshot((asserted,))
    model.advance(asserted.assertion_trust_until)
    degraded = model.states[0]
    clear_model = episodes()
    clear_model.observe(sensor("binary_sensor.a", "on", 0))
    clear_model.observe(sensor("binary_sensor.a", "off", 10))
    clear_model.advance(NOW + timedelta(seconds=15))
    clear = clear_model.states[0]

    invalid_states = (
        replace(clearing, clear_deadline=clearing.clear_started_at),
        replace(degraded, degraded_at=degraded.started_at),
        replace(degraded, health_warning=False),
        replace(clear, clear_started_at=NOW + timedelta(seconds=10)),
        replace(
            clearing,
            alias_states=(
                ("binary_sensor.a", "on"),
                ("binary_sensor.b", "unknown"),
            ),
        ),
    )
    messages = (
        "clear frontier is inconsistent",
        "degradation time is inconsistent",
        "health state is inconsistent",
        "Clear episode snapshot is inconsistent",
        "Inactive episode snapshot has asserted aliases",
    )
    for invalid_state, message in zip(invalid_states, messages, strict=True):
        target = episodes()
        with pytest.raises(ValueError, match=message):
            target.restore_snapshot((invalid_state,))


def test_generation_zero_snapshot_restores_deterministically() -> None:
    source = episodes()
    target = episodes()

    target.restore_snapshot(source.states)

    assert target.states == source.states
