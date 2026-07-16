from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.inference.policy import (
    PosteriorEventPolicy,
)
from custom_components.predictive_controls.occupancy_state import (
    ReleaseCause,
    ZonePolicyState,
)

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def policy() -> PosteriorEventPolicy:
    return PosteriorEventPolicy(
        ("hall", "office"),
        activation_threshold=0.8,
        release_threshold=0.95,
    )


def test_arrival_threshold_sets_durable_ownership_and_optional_pulse() -> None:
    target = policy()

    states = target.apply(
        NOW,
        1,
        {"office": 0.8},
        False,
        {},
        emit_activation=True,
    )

    assert states["office"].keep_on
    assert states["office"].activation_expires_at == NOW + timedelta(seconds=5)
    assert target.last_decisions[-1].reason_code == "arrival_supported"
    target.expire(NOW + timedelta(seconds=5))
    assert target.states["office"].keep_on
    assert target.states["office"].activation_expires_at is None


def test_missing_or_low_events_retain_existing_ownership() -> None:
    target = policy()
    target.restore_states({"hall": ZonePolicyState(), "office": ZonePolicyState(True)})

    states = target.apply(NOW, 1, {}, False, {}, emit_activation=False)
    assert states["office"].keep_on
    states = target.apply(
        NOW + timedelta(seconds=1),
        1,
        {"hall": 0.79},
        True,
        {"office": 0.949},
        emit_activation=False,
    )

    assert states["office"].keep_on
    assert not states["hall"].keep_on


def test_finalized_release_threshold_clears_only_held_zone() -> None:
    target = policy()
    target.restore_states(
        {"hall": ZonePolicyState(), "office": ZonePolicyState(True)}
    )

    states = target.apply(
        NOW,
        2,
        {},
        True,
        {"hall": 1.0, "office": 0.95},
        emit_activation=False,
    )

    assert not states["office"].keep_on
    assert states["office"].last_release_cause is ReleaseCause.RELEASE_SAFE
    assert target.last_decisions[-1].reason_code == "release_safe"


def test_authoritative_zero_categorically_clears_all_ownership() -> None:
    target = policy()
    target.restore_states(
        {
            "hall": ZonePolicyState(True),
            "office": ZonePolicyState(True),
        }
    )

    states = target.apply(NOW, 0, {"office": 1.0}, False, {}, emit_activation=True)

    assert all(not state.keep_on for state in states.values())
    assert all(
        state.last_release_cause is ReleaseCause.AUTHORITATIVE_AWAY
        for state in states.values()
    )


def test_already_active_arrival_does_not_toggle_ownership() -> None:
    target = policy()
    original = ZonePolicyState(True, last_trusted_at=NOW)
    target.restore_states({"hall": ZonePolicyState(), "office": original})

    states = target.apply(
        NOW + timedelta(seconds=1),
        1,
        {"office": 1.0},
        False,
        {},
        emit_activation=True,
    )

    assert states["office"] == original
    assert target.last_decisions[-1].reason_code == "already_active"


def test_policy_validates_thresholds_and_restore_atomically() -> None:
    with pytest.raises(ValueError, match="activation threshold"):
        PosteriorEventPolicy(
            ("office",),
            activation_threshold=-0.1,
            release_threshold=1.0,
        )
    with pytest.raises(ValueError, match="release threshold"):
        PosteriorEventPolicy(
            ("office",),
            activation_threshold=0.0,
            release_threshold=1.1,
        )

    target = policy()
    before = target.states
    with pytest.raises(ValueError, match="zones"):
        target.restore_states({"office": ZonePolicyState(True)})
    assert target.states == before
