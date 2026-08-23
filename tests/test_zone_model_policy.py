from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.zone_model.filter import (
    probability_to_log_odds,
)
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    PolicyAuditLog,
    ZonePolicy,
)
from custom_components.predictive_controls.zone_model.prediction import PredictionLease
from custom_components.predictive_controls.zone_model.types import (
    CountConflictState,
    EpisodeEffect,
    EpisodeState,
    PendingAcquisitionCandidate,
    PolicyCalibration,
    PolicyUpdate,
    RefreshDedupEntry,
    TraversalAuthorization,
    ZoneBeliefState,
    ZonePolicyState,
)

NOW = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def belief(
    probability: float,
    at: datetime,
    *,
    profile: str = "stay_pir",
    zone: str = "room",
) -> ZoneBeliefState:
    return ZoneBeliefState(
        zone,
        profile,
        probability_to_log_odds(probability),
        at,
        "asserted",
    )


def episode(
    episode_id: str,
    at: datetime,
    *,
    profile: str = "stay_pir",
    zone: str = "room",
    status: str = "asserted",
    health_warning: bool = False,
) -> EpisodeState:
    return EpisodeState(
        "room_motion",
        zone,
        profile,
        (("binary_sensor.room_motion", "on"),),
        generation=1,
        episode_id=episode_id,
        status=status,
        started_at=at,
        last_event_at=at,
        advanced_at=at,
        traversal_valid_until=at + timedelta(minutes=2),
        health_warning=health_warning,
    )


def positive(state: EpisodeState, at: datetime) -> EpisodeEffect:
    return EpisodeEffect(
        state.node_id,
        state.zone,
        state.episode_id or "",
        "positive",
        at,
    )


def authorization(
    state: EpisodeState,
    at: datetime,
    *,
    authorized: bool = True,
) -> TraversalAuthorization:
    return TraversalAuthorization(
        state.node_id,
        state.zone,
        state.episode_id or "",
        at,
        authorized,
        "adjacent_authorized" if authorized else "track_bootstrap_pending",
        track_confidence="provisional" if authorized else None,
        path_node_ids=(state.node_id,) if authorized else (),
        provenance_kind="adjacent" if authorized else None,
    )


def acquire(
    policy: ZonePolicy,
    state: EpisodeState,
    at: datetime,
    *,
    probability: float = 0.7,
) -> PolicyUpdate:
    return policy.evaluate(
        at,
        belief(0.05, at),
        belief(probability, at),
        local_state=state,
        local_effect=positive(state, at),
        authorization=authorization(state, at),
        processing_at=at,
    )


def test_t02_exact_on_threshold_acquires_once_without_refresh() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    state = episode("room:1", NOW)

    update = acquire(policy, state, NOW)

    assert update.state.active is True
    assert update.event is not None and update.event.kind == "acquired"
    assert update.decision.reason == "acquired"
    duplicate = acquire(policy, state, NOW)
    assert duplicate.event is None
    assert duplicate.state.active is True


def test_high_belief_without_current_matching_authorization_stays_inactive() -> None:
    state = episode("room:1", NOW)
    cases = (
        None,
        authorization(state, NOW, authorized=False),
        replace(authorization(state, NOW), authorized_at=NOW - timedelta(seconds=1)),
        replace(authorization(state, NOW), target_episode_id="other"),
    )
    for candidate in cases:
        policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
        update = policy.evaluate(
            NOW,
            belief(0.05, NOW),
            belief(0.95, NOW),
            local_state=state,
            local_effect=positive(state, NOW),
            authorization=candidate,
            processing_at=NOW,
        )
        assert update.state.active is False
        assert update.event is None
        assert update.decision.reason == "acquisition_unauthorized"


@pytest.mark.parametrize(
    "state_change",
    [
        {"status": "degraded"},
        {"status": "unavailable"},
        {"health_warning": True},
        {"started_at": NOW + timedelta(seconds=1)},
        {"traversal_valid_until": NOW},
    ],
)
def test_untrustworthy_local_episode_cannot_acquire_or_refresh(
    state_change: dict[str, object],
) -> None:
    state = replace(episode("room:1", NOW), **state_change)  # type: ignore[arg-type]
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    update = policy.evaluate(
        NOW,
        belief(0.05, NOW),
        belief(0.95, NOW),
        local_state=state,
        local_effect=positive(state, NOW),
        authorization=authorization(state, NOW),
        processing_at=NOW,
    )
    assert update.state.active is False
    assert update.event is None


def test_t07_refreshes_once_per_distinct_episode_and_survives_restore() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    first = episode("room:1", NOW)
    acquire(policy, first, NOW)
    second_at = NOW + timedelta(seconds=10)
    second = episode("room:2", second_at)

    refreshed = policy.evaluate(
        second_at,
        belief(0.7, second_at),
        belief(0.8, second_at),
        local_state=second,
        local_effect=positive(second, second_at),
        authorization=None,
        processing_at=second_at,
    )
    duplicate = policy.evaluate(
        second_at,
        belief(0.8, second_at),
        belief(0.8, second_at),
        local_state=second,
        local_effect=positive(second, second_at),
        authorization=None,
        processing_at=second_at,
    )
    restored = ZonePolicy(
        "room", POLICY_CALIBRATIONS["stay_pir"], second_at, state=policy.state
    )
    replay = restored.evaluate(
        second_at,
        belief(0.8, second_at),
        belief(0.8, second_at),
        local_state=second,
        local_effect=positive(second, second_at),
        authorization=None,
        processing_at=second_at,
    )

    assert refreshed.event is not None and refreshed.event.kind == "refreshed"
    assert duplicate.event is None
    assert replay.event is None
    assert restored.bootstrap_events == ()


def test_refresh_dedup_expires_exclusively_and_is_bounded() -> None:
    entries = tuple(
        RefreshDedupEntry(
            f"episode:{index}",
            NOW + timedelta(seconds=index),
            NOW + timedelta(hours=12, seconds=index),
        )
        for index in range(256)
    )
    state = ZonePolicyState(
        "room",
        "stay_pir",
        True,
        NOW + timedelta(seconds=255),
        refresh_dedup=entries,
        phase="active",
        activation_provenance="evidence",
        activation_episode_id="episode:0",
        activation_at=NOW,
        activation_reason="boundary_authorized",
        activation_track_confidence="provisional",
        activation_path_node_ids=("room",),
        activation_provenance_kind="boundary",
    )
    at = NOW + timedelta(seconds=256)
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], at, state=state)
    fresh = episode("episode:256", at)
    update = policy.evaluate(
        at,
        belief(0.8, at),
        belief(0.8, at),
        local_state=fresh,
        local_effect=positive(fresh, at),
        authorization=None,
        processing_at=at,
    )
    assert update.event is not None and update.event.kind == "refreshed"
    assert len(update.state.refresh_dedup) == 256
    assert update.state.refresh_dedup[0].episode_id == "episode:1"

    expiry = NOW + timedelta(hours=12, seconds=256)
    replayed = episode("episode:256", expiry)
    expired = policy.evaluate(
        expiry,
        belief(0.8, expiry),
        belief(0.8, expiry),
        local_state=replayed,
        local_effect=positive(replayed, expiry),
        authorization=None,
        processing_at=expiry,
    )
    assert expired.event is not None and expired.event.kind == "refreshed"


def test_t04_release_dwell_is_inclusive_and_cancels_above_off_threshold() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    low = belief(0.3, NOW)
    started = policy.evaluate(
        NOW, low, low, local_state=None, local_effect=None, authorization=None
    )
    assert started.state.pending_release_since == NOW

    before = NOW + timedelta(seconds=59, milliseconds=999)
    held = policy.evaluate(
        before,
        belief(0.3, before),
        belief(0.3, before),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert held.state.active is True

    canceled_at = NOW + timedelta(seconds=59, milliseconds=999, microseconds=1)
    canceled = policy.evaluate(
        canceled_at,
        belief(0.3, canceled_at),
        belief(0.300001, canceled_at),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert canceled.state.pending_release_since is None

    restarted = policy.evaluate(
        NOW + timedelta(seconds=60),
        belief(0.3, NOW + timedelta(seconds=60)),
        belief(0.3, NOW + timedelta(seconds=60)),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    released = policy.evaluate(
        NOW + timedelta(seconds=120),
        belief(0.3, NOW + timedelta(seconds=120)),
        belief(0.3, NOW + timedelta(seconds=120)),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert restarted.state.active is True
    assert released.state.active is False
    assert released.event is not None and released.event.kind == "released"


def test_t05_t06_health_degradation_never_extends_pending_release() -> None:
    for profile in ("transition_fast", "stay_presence"):
        policy = ZonePolicy("room", POLICY_CALIBRATIONS[profile], NOW, active=True)
        low = belief(0.2, NOW, profile=profile)
        policy.evaluate(
            NOW, low, low, local_state=None, local_effect=None, authorization=None
        )
        dwell = POLICY_CALIBRATIONS[profile].release_dwell
        at = NOW + dwell
        degraded = episode(
            "room:1", at, profile=profile, status="degraded", health_warning=True
        )
        update = policy.evaluate(
            at,
            belief(0.2, at, profile=profile),
            belief(0.2, at, profile=profile),
            local_state=degraded,
            local_effect=None,
            authorization=None,
        )
        assert update.state.active is False
        assert update.state.pending_release_since is None


def test_asserted_stay_hold_cancels_and_restarts_full_release_dwell() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_presence"], NOW, active=True)
    low = belief(0.2, NOW, profile="stay_presence")
    started = policy.evaluate(
        NOW,
        low,
        low,
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert started.state.pending_release_since == NOW

    dwell = POLICY_CALIBRATIONS["stay_presence"].release_dwell
    held_at = NOW + dwell
    held = policy.evaluate(
        held_at,
        belief(0.2, held_at, profile="stay_presence"),
        belief(0.2, held_at, profile="stay_presence"),
        local_state=None,
        local_effect=None,
        authorization=None,
        asserted_stay_hold=True,
    )
    assert held.state.active
    assert held.state.pending_release_since is None
    assert held.decision.reason == "asserted_stay_hold"

    still_held_at = held_at + timedelta(hours=2)
    still_held = policy.evaluate(
        still_held_at,
        belief(0.2, still_held_at, profile="stay_presence"),
        belief(0.2, still_held_at, profile="stay_presence"),
        local_state=None,
        local_effect=None,
        authorization=None,
        asserted_stay_hold=True,
    )
    assert still_held.state.active
    assert still_held.state.pending_release_since is None

    clear_at = still_held_at + timedelta(seconds=1)
    restarted = policy.evaluate(
        clear_at,
        belief(0.2, clear_at, profile="stay_presence"),
        belief(0.2, clear_at, profile="stay_presence"),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert restarted.state.pending_release_since == clear_at

    released_at = clear_at + dwell
    released = policy.evaluate(
        released_at,
        belief(0.2, released_at, profile="stay_presence"),
        belief(0.2, released_at, profile="stay_presence"),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert not released.state.active
    assert released.event is not None and released.event.kind == "released"


def test_asserted_stay_hold_flag_must_be_boolean() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    with pytest.raises(ValueError, match="hold flag must be boolean"):
        policy.evaluate(
            NOW,
            belief(0.2, NOW),
            belief(0.2, NOW),
            local_state=None,
            local_effect=None,
            authorization=None,
            asserted_stay_hold=1,  # type: ignore[arg-type]
        )


def test_timer_cadence_does_not_change_release_boundary() -> None:
    direct = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    stepped = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    for policy in (direct, stepped):
        policy.evaluate(
            NOW,
            belief(0.2, NOW),
            belief(0.2, NOW),
            local_state=None,
            local_effect=None,
            authorization=None,
        )
    for seconds in range(10, 61, 10):
        at = NOW + timedelta(seconds=seconds)
        stepped.evaluate(
            at,
            belief(0.2, at),
            belief(0.2, at),
            local_state=None,
            local_effect=None,
            authorization=None,
        )
    at = NOW + timedelta(seconds=60)
    direct_update = direct.evaluate(
        at,
        belief(0.2, at),
        belief(0.2, at),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert direct_update.state == stepped.state


def test_refresh_during_pending_release_preserves_original_dwell() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    policy.evaluate(
        NOW,
        belief(0.2, NOW),
        belief(0.2, NOW),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    refreshed_at = NOW + timedelta(seconds=10)
    fresh = episode("room:2", refreshed_at)
    refreshed = policy.evaluate(
        refreshed_at,
        belief(0.2, refreshed_at),
        belief(0.2, refreshed_at),
        local_state=fresh,
        local_effect=positive(fresh, refreshed_at),
        authorization=None,
    )
    released_at = NOW + timedelta(seconds=60)
    released = policy.evaluate(
        released_at,
        belief(0.2, released_at),
        belief(0.2, released_at),
        local_state=None,
        local_effect=None,
        authorization=None,
    )

    assert refreshed.event is not None and refreshed.event.kind == "refreshed"
    assert refreshed.state.pending_release_since == NOW
    assert released.state.active is False
    assert released.event is not None and released.event.kind == "released"


def test_off_threshold_chatter_restarts_the_full_release_dwell() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    policy.evaluate(
        NOW,
        belief(0.29, NOW),
        belief(0.29, NOW),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    canceled_at = NOW + timedelta(seconds=10)
    policy.evaluate(
        canceled_at,
        belief(0.29, canceled_at),
        belief(0.31, canceled_at),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    restarted_at = NOW + timedelta(seconds=20)
    restarted = policy.evaluate(
        restarted_at,
        belief(0.31, restarted_at),
        belief(0.29, restarted_at),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    original_boundary = NOW + timedelta(seconds=60)
    still_held = policy.evaluate(
        original_boundary,
        belief(0.29, original_boundary),
        belief(0.29, original_boundary),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    new_boundary = restarted_at + timedelta(seconds=60)
    released = policy.evaluate(
        new_boundary,
        belief(0.29, new_boundary),
        belief(0.29, new_boundary),
        local_state=None,
        local_effect=None,
        authorization=None,
    )

    assert restarted.state.pending_release_since == restarted_at
    assert still_held.state.active is True
    assert released.state.active is False


def test_count_zero_releases_immediately_and_inactive_has_no_edge() -> None:
    active = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    released = active.apply_count_zero(NOW)
    assert released.state.active is False
    assert released.event is not None and released.event.kind == "released"
    assert released.decision.reason == "count_zero"

    inactive = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    unchanged = inactive.apply_count_zero(NOW)
    assert unchanged.state.active is False
    assert unchanged.event is None


def test_pending_expiry_audit_validates_zone_and_preserves_active_state() -> None:
    candidate = PendingAcquisitionCandidate(
        "room_motion",
        "room",
        "stay_pir",
        "room:1",
        NOW,
        NOW + timedelta(seconds=30),
        NOW + timedelta(seconds=20),
        1.0,
    )
    at = NOW + timedelta(seconds=30)
    active = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)

    decision = active.record_pending_expiry(
        candidate,
        belief(0.8, at),
        at=at,
        processing_at=at,
    )

    assert active.state.active is True
    assert decision.active_before is decision.active_after is True
    assert decision.reason == "untracked_expired"
    with pytest.raises(ValueError, match="incompatible"):
        active.record_pending_expiry(
            replace(candidate, zone="other"),
            belief(0.8, at),
            at=at,
            processing_at=at,
        )


def test_prediction_contradiction_releases_when_public_events_are_suppressed() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    lease = PredictionLease(
        "source",
        "current",
        "room_motion",
        "room",
        0.9,
        5.0,
        "source:1",
        NOW,
        NOW + timedelta(seconds=10),
        True,
        "test",
    )
    assert policy.apply_prediction(lease, belief(0.1, NOW)) is not None
    at = NOW + timedelta(seconds=1)
    unavailable = episode(
        "room:1",
        at,
        status="unavailable",
    )

    update = policy.evaluate(
        at,
        belief(0.1, at),
        belief(0.1, at),
        local_state=unavailable,
        local_effect=None,
        authorization=None,
        emit_event=False,
    )

    assert not update.state.active
    assert update.state.phase == "inactive"
    assert update.event is None
    assert update.decision.reason == "prediction_unconfirmed"


def test_profile_policy_calibration_is_shared_and_role_ordered() -> None:
    assert {item.on_threshold for item in POLICY_CALIBRATIONS.values()} == {0.7}
    assert {item.off_threshold for item in POLICY_CALIBRATIONS.values()} == {0.3}
    assert POLICY_CALIBRATIONS["entry_boundary"].release_dwell == timedelta(seconds=15)
    assert POLICY_CALIBRATIONS["transition_fast"].release_dwell == timedelta(seconds=15)
    assert POLICY_CALIBRATIONS["stay_pir"].release_dwell == timedelta(seconds=60)
    assert POLICY_CALIBRATIONS["stay_presence"].release_dwell == timedelta(seconds=120)


def test_policy_calibration_and_authorization_validate_direct_inputs() -> None:
    with pytest.raises(ValueError, match="Unknown policy profile"):
        PolicyCalibration("unknown", 0.7, 0.3, timedelta(seconds=60))
    with pytest.raises(ValueError, match="thresholds"):
        PolicyCalibration("stay_pir", 0.3, 0.3, timedelta(seconds=60))
    with pytest.raises(ValueError, match="finite and positive"):
        PolicyCalibration("stay_pir", 0.7, 0.3, timedelta(0))
    with pytest.raises(ValueError, match="finite and positive"):
        PolicyCalibration("stay_pir", 0.7, 0.3, timedelta(seconds=-1))

    state = episode("room:1", NOW)
    valid = authorization(state, NOW)
    with pytest.raises(ValueError, match="identifiers"):
        replace(valid, target_node_id="")
    with pytest.raises(ValueError, match="result"):
        replace(valid, authorized=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="result"):
        replace(valid, reason="")


def test_count_conflict_audit_and_prediction_reject_incompatible_inputs() -> None:
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    state = episode("room:1", NOW)
    conflict = CountConflictState(
        "other",
        "room",
        "room:1",
        NOW,
        NOW,
        NOW + timedelta(seconds=60),
        ("front",),
    )
    with pytest.raises(ValueError, match="incompatible"):
        policy.record_count_conflict(
            conflict,
            state,
            belief(0.8, NOW),
            result="degraded",
            at=NOW,
            processing_at=NOW,
        )

    immature = PredictionLease(
        "source",
        "current",
        "target",
        "room",
        1.0,
        4.0,
        "source:1",
        NOW,
        NOW + timedelta(seconds=10),
        False,
        "immature",
    )
    assert policy.apply_prediction(immature, belief(0.1, NOW)) is None


def test_policy_can_suppress_acquire_refresh_events_and_reject_bad_frontier() -> None:
    at = NOW + timedelta(seconds=1)
    state = episode("room:1", at)
    effect = positive(state, at)
    auth = authorization(state, at)
    policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    acquired = policy.evaluate(
        at,
        belief(0.2, at),
        belief(0.8, at),
        local_state=state,
        local_effect=effect,
        authorization=auth,
        emit_event=False,
    )
    assert acquired.state.active and acquired.event is None

    refreshed_at = at + timedelta(seconds=1)
    refreshed_state = episode("room:2", refreshed_at)
    refreshed = policy.evaluate(
        refreshed_at,
        belief(0.8, refreshed_at),
        belief(0.8, refreshed_at),
        local_state=refreshed_state,
        local_effect=positive(refreshed_state, refreshed_at),
        authorization=authorization(refreshed_state, refreshed_at),
        emit_event=False,
    )
    assert refreshed.decision.reason == "refreshed" and refreshed.event is None

    with pytest.raises(ValueError, match="frontier"):
        policy.evaluate(
            refreshed_at,
            belief(0.8, refreshed_at - timedelta(seconds=1)),
            belief(0.8, refreshed_at - timedelta(seconds=1)),
            local_state=None,
            local_effect=None,
            authorization=None,
        )


def test_refresh_and_policy_state_validate_restore_invariants() -> None:
    valid = RefreshDedupEntry("room:1", NOW, NOW + timedelta(hours=12))
    with pytest.raises(ValueError, match="episode ID"):
        replace(valid, episode_id="")
    with pytest.raises(ValueError, match="follow publication"):
        replace(valid, expires_at=NOW)

    with pytest.raises(ValueError, match="zone and profile"):
        ZonePolicyState("", "stay_pir", False, NOW)
    with pytest.raises(ValueError, match="boolean"):
        ZonePolicyState("room", "stay_pir", 1, NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="current active"):
        ZonePolicyState("room", "stay_pir", False, NOW, NOW)
    with pytest.raises(ValueError, match="current active"):
        ZonePolicyState("room", "stay_pir", True, NOW, NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="retains activation provenance"):
        ZonePolicyState(
            "room",
            "stay_pir",
            False,
            NOW,
            activation_provenance="evidence",
        )
    with pytest.raises(ValueError, match="exceeds"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW,
            refresh_dedup=tuple(
                RefreshDedupEntry(f"room:{index}", NOW, NOW + timedelta(hours=12))
                for index in range(257)
            ),
            phase="active",
            activation_provenance="evidence",
            activation_episode_id="room:1",
            activation_at=NOW,
            activation_reason="boundary_authorized",
            activation_track_confidence="provisional",
            activation_path_node_ids=("room",),
            activation_provenance_kind="boundary",
        )


def test_evidence_active_state_requires_complete_bounded_provenance() -> None:
    valid = ZonePolicyState(
        "room",
        "stay_pir",
        True,
        NOW,
        phase="active",
        activation_provenance="evidence",
        activation_episode_id="room:1",
        activation_at=NOW,
        activation_reason="boundary_authorized",
        activation_track_confidence="provisional",
        activation_path_node_ids=("room",),
        activation_provenance_kind="boundary",
    )
    for changes in (
        {"activation_episode_id": ""},
        {"activation_reason": ""},
        {"activation_provenance_kind": ""},
        {"activation_track_confidence": "invalid"},
        {"activation_path_node_ids": ("a", "b", "c", "d")},
        {"activation_path_node_ids": ("",)},
        {"activation_source_episode_ids": ("source", "source")},
        {"activation_source_episode_ids": ("",)},
        {"activation_reason": "invalid"},
        {"activation_at": NOW + timedelta(seconds=1)},
        {"activation_track_confidence": None},
        {"activation_provenance_kind": None},
    ):
        with pytest.raises(ValueError):
            replace(valid, **changes)

    with pytest.raises(ValueError, match="lacks acquisition evidence"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW,
            phase="active",
            activation_provenance="evidence",
        )
    with pytest.raises(ValueError, match="incompatible activation evidence"):
        ZonePolicyState(
            "room",
            "stay_pir",
            False,
            NOW,
            activation_path_node_ids=("room",),
        )

    confirmed = replace(
        valid,
        activation_reason="prediction_confirmed",
        activation_track_confidence=None,
        activation_provenance_kind="prediction_confirmation",
    )
    for changes in (
        {"activation_track_confidence": "confirmed"},
        {"activation_provenance_kind": "boundary"},
        {"activation_path_node_ids": ("hall", "room")},
        {"activation_source_episode_ids": ("hall:1",)},
    ):
        with pytest.raises(ValueError, match="lacks acquisition evidence"):
            replace(confirmed, **changes)
    refresh = RefreshDedupEntry("room:1", NOW, NOW + timedelta(hours=12))
    with pytest.raises(ValueError, match="unique"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW,
            refresh_dedup=(refresh, refresh),
            phase="active",
            activation_provenance="evidence",
            activation_episode_id="room:1",
            activation_at=NOW,
            activation_reason="boundary_authorized",
            activation_track_confidence="provisional",
            activation_path_node_ids=("room",),
            activation_provenance_kind="boundary",
        )
    later = RefreshDedupEntry(
        "room:2", NOW + timedelta(seconds=1), NOW + timedelta(hours=12)
    )
    with pytest.raises(ValueError, match="time ordered"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW + timedelta(seconds=1),
            refresh_dedup=(later, refresh),
            phase="active",
            activation_provenance="evidence",
            activation_episode_id="room:1",
            activation_at=NOW,
            activation_reason="boundary_authorized",
            activation_track_confidence="provisional",
            activation_path_node_ids=("room",),
            activation_provenance_kind="boundary",
        )
    with pytest.raises(ValueError, match="state frontier"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW,
            refresh_dedup=(later,),
            phase="active",
            activation_provenance="evidence",
            activation_episode_id="room:1",
            activation_at=NOW,
            activation_reason="boundary_authorized",
            activation_track_confidence="provisional",
            activation_path_node_ids=("room",),
            activation_provenance_kind="boundary",
        )
    with pytest.raises(ValueError, match="state frontier"):
        ZonePolicyState(
            "room",
            "stay_pir",
            True,
            NOW + timedelta(hours=12),
            refresh_dedup=(refresh,),
            phase="active",
            activation_provenance="evidence",
            activation_episode_id="room:1",
            activation_at=NOW,
            activation_reason="boundary_authorized",
            activation_track_confidence="provisional",
            activation_path_node_ids=("room",),
            activation_provenance_kind="boundary",
        )


def test_policy_constructor_and_frontier_validation() -> None:
    calibration = POLICY_CALIBRATIONS["stay_pir"]
    with pytest.raises(ValueError, match="zone"):
        ZonePolicy("", calibration, NOW)
    incompatible = ZonePolicyState("other", "stay_pir", False, NOW)
    with pytest.raises(ValueError, match="incompatible"):
        ZonePolicy("room", calibration, NOW, state=incompatible)
    future = ZonePolicyState("room", "stay_pir", False, NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="ahead"):
        ZonePolicy("room", calibration, NOW, state=future)
    audit = PolicyAuditLog()
    assert ZonePolicy("room", calibration, NOW, audit=audit).audit is audit

    policy = ZonePolicy("room", calibration, NOW)
    with pytest.raises(ValueError, match="frontier"):
        policy.evaluate(
            NOW,
            belief(0.1, NOW, zone="other"),
            belief(0.2, NOW),
            local_state=None,
            local_effect=None,
            authorization=None,
        )
    with pytest.raises(ValueError, match="backward"):
        policy.apply_count_zero(NOW - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="precede"):
        policy.apply_count_zero(NOW + timedelta(seconds=1), processing_at=NOW)


def test_policy_hold_and_matching_evidence_paths_are_explicit() -> None:
    inactive = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
    below = inactive.evaluate(
        NOW,
        belief(0.1, NOW),
        belief(0.69, NOW),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert below.decision.reason == "inactive_below_on"

    active = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW, active=True)
    held = active.evaluate(
        NOW,
        belief(0.8, NOW),
        belief(0.8, NOW),
        local_state=None,
        local_effect=None,
        authorization=None,
    )
    assert held.decision.reason == "active_hold"

    state = episode("room:1", NOW)
    mismatched_effects = (
        replace(positive(state, NOW), kind="stable_clear"),
        replace(positive(state, NOW), at=NOW - timedelta(microseconds=1)),
        replace(positive(state, NOW), node_id="other"),
        replace(positive(state, NOW), zone="other"),
        replace(positive(state, NOW), episode_id="other"),
    )
    for effect in mismatched_effects:
        policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
        update = policy.evaluate(
            NOW,
            belief(0.1, NOW),
            belief(0.9, NOW),
            local_state=state,
            local_effect=effect,
            authorization=authorization(state, NOW),
        )
        assert update.decision.reason == "acquisition_unauthorized"

    for candidate in (
        replace(authorization(state, NOW), target_node_id="other"),
        replace(authorization(state, NOW), target_zone="other"),
    ):
        policy = ZonePolicy("room", POLICY_CALIBRATIONS["stay_pir"], NOW)
        update = policy.evaluate(
            NOW,
            belief(0.1, NOW),
            belief(0.9, NOW),
            local_state=state,
            local_effect=positive(state, NOW),
            authorization=candidate,
        )
        assert update.decision.reason == "acquisition_unauthorized"
