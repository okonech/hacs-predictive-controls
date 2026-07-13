from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.confidence import (
    CONFIDENCE_STATUSES,
    ZoneConfidenceEngine,
    clear_factor_for_event,
    conflict_confidence,
    on_confidence_floor,
    passive_confidence_for_duration,
    reason_for_clear_transition_decay,
    reason_for_conflict_decay,
    reason_for_departure_decay,
    reason_for_event,
    reason_for_inactive_decay,
    reason_for_sustained_event,
    status_for_confidence,
    sustained_cap_for_event,
    sustained_confidence_for_duration,
    sustained_ramp_seconds,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_scoring import (
    event_confidence,
    passive_decay_half_life_seconds,
    reason_for_occupant_handoff,
)
from custom_components.predictive_controls.occupancy_state import ZonePolicyState
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
    ZoneState,
)

NOW = datetime(2026, 6, 7, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office"],
                },
            }
        }
    )


def make_event(
    *,
    zone: str = "office",
    role: str = "room_occupancy",
    signal_type: str = "motion",
    state: str = "on",
    reliability: float = 0.8,
    occupancy_behavior: str | None = None,
) -> OccupancyEvent:
    behavior = occupancy_behavior
    if behavior is None:
        behavior = {
            "transition_gate": "transient",
            "ambiguous_open_plan": "ambiguous",
            "anchor_sensor": "sticky",
        }.get(role, "sustained")
    return OccupancyEvent(
        entity_id=f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor="first_floor",
        role=role,
        occupancy_behavior=behavior,
        signal_type=signal_type,
        state=state,
        event_at=NOW,
        reliability=reliability,
    )


def test_status_thresholds() -> None:
    assert CONFIDENCE_STATUSES == (
        "rejected",
        "suspect",
        "possible",
        "probable",
        "confirmed",
    )
    assert [status_for_confidence(value) for value in (0.0, 0.2, 0.5, 0.7, 0.9)] == [
        "rejected",
        "suspect",
        "possible",
        "probable",
        "confirmed",
    ]


def test_on_confidence_floor_uses_role_signal_and_reliability() -> None:
    events = (
        make_event(zone="foyer", role="transition_gate", reliability=0.85),
        make_event(role="ambiguous_open_plan", reliability=0.75),
        make_event(role="subzone_occupancy", reliability=0.8),
        make_event(
            zone="living_room",
            role="anchor_sensor",
            signal_type="still_target",
            reliability=0.9,
        ),
        make_event(signal_type="target", reliability=0.9),
        make_event(signal_type="zone_occupancy", reliability=0.9),
        make_event(
            role="transition_gate",
            signal_type="moving_target",
            reliability=0.9,
        ),
        make_event(reliability=2.0),
    )
    assert [on_confidence_floor(event) for event in events] == [
        0.529,
        0.544,
        0.57,
        0.877,
        0.722,
        0.722,
        0.605,
        0.65,
    ]


def test_clear_and_passive_scoring_cover_behavior_fallbacks() -> None:
    assert clear_factor_for_event(make_event(role="transition_gate")) == 0.25
    assert clear_factor_for_event(make_event(role="ambiguous_open_plan")) == 0.55
    assert clear_factor_for_event(make_event(role="subzone_occupancy")) == 1.0
    assert clear_factor_for_event(make_event(signal_type="still_target")) == 1.0
    assert (
        clear_factor_for_event(
            make_event(role="anchor_sensor", signal_type="still_target")
        )
        == 0.85
    )
    assert (
        clear_factor_for_event(make_event(role="unknown_role", occupancy_behavior=""))
        == 0.60
    )
    assert passive_decay_half_life_seconds("sustained") == 300.0
    assert (
        passive_confidence_for_duration("sustained", timedelta(hours=1), 0.426) == 0.0
    )
    assert passive_confidence_for_duration("sticky", timedelta(hours=2), 0.768) == 0.048
    assert (
        passive_confidence_for_duration("transient", timedelta(minutes=10), 0.7) == 0.0
    )
    assert (
        passive_confidence_for_duration("unknown", timedelta(minutes=10), 0.5) == 0.25
    )
    assert passive_confidence_for_duration("sustained", timedelta(0), 0.5) == 0.5
    assert passive_confidence_for_duration("sustained", timedelta(minutes=1), 0) == 0
    assert conflict_confidence(0.768) == 0.269
    assert conflict_confidence(0.02) == 0.0


def test_sustained_scoring_uses_behavior_caps_and_duration() -> None:
    sustained = make_event(reliability=0.75, occupancy_behavior="sustained")
    transient = make_event(
        role="transition_gate",
        reliability=0.75,
        occupancy_behavior="transient",
    )
    sticky = make_event(
        role="anchor_sensor",
        signal_type="still_target",
        reliability=0.9,
        occupancy_behavior="sticky",
    )
    assert (
        sustained_confidence_for_duration(sustained, timedelta(minutes=2), 0.609)
        == 0.697
    )
    assert (
        sustained_confidence_for_duration(sustained, timedelta(minutes=10), 0.609)
        == 0.96
    )
    assert (
        sustained_confidence_for_duration(transient, timedelta(minutes=10), 0.529)
        == 0.70
    )
    assert (
        sustained_confidence_for_duration(sticky, timedelta(minutes=10), 0.877) == 0.99
    )
    assert (
        sustained_confidence_for_duration(
            make_event(occupancy_behavior="unknown"),
            timedelta(minutes=10),
            0.617,
        )
        == 0.90
    )
    assert (
        sustained_confidence_for_duration(sustained, timedelta(seconds=-30), 0.7) == 0.7
    )
    assert (
        sustained_confidence_for_duration(sustained, timedelta(minutes=1), 0.98) == 0.98
    )
    assert sustained_ramp_seconds("unknown") == 600.0


def test_reason_helpers_remain_stable_diagnostics() -> None:
    on_event = make_event(state="on")
    off_event = make_event(state="off")
    assert reason_for_event(on_event, 0.7) == (
        "motion active at office; confidence is probable"
    )
    assert reason_for_event(off_event, 0.4) == (
        "motion cleared at office; confidence decayed to possible"
    )
    assert (
        reason_for_sustained_event(
            on_event,
            0.9,
            on_event.event_at + timedelta(minutes=5),
        )
        == "motion active at office for 5 min; sustained confidence is confirmed"
    )
    assert (
        reason_for_inactive_decay(
            ZoneState(zone="office", occupancy_behavior="sustained"),
            0.4,
            timedelta(minutes=3),
        )
        == "inactive for 3 min; sustained confidence decayed to possible"
    )


def test_legacy_scoring_boundaries_and_path_reasons() -> None:
    on_event = make_event(state="on", reliability=1.0)
    off_event = make_event(state="off", reliability=1.0)
    assert event_confidence(0.1, on_event) == on_confidence_floor(on_event)
    assert event_confidence(0.9, on_event) == 0.98
    assert event_confidence(0.99, on_event) == 1.0
    assert event_confidence(0.8, off_event) == 0.8
    assert (
        sustained_cap_for_event(
            make_event(signal_type="still_target", occupancy_behavior="transient")
        )
        == 0.99
    )
    assert (
        sustained_cap_for_event(
            make_event(signal_type="target", occupancy_behavior="transient")
        )
        == 0.95
    )
    assert (
        sustained_cap_for_event(
            make_event(signal_type="zone_occupancy", occupancy_behavior="transient")
        )
        == 0.95
    )
    assert (
        clear_factor_for_event(
            make_event(role="transition_gate", occupancy_behavior="")
        )
        == 0.25
    )
    assert (
        clear_factor_for_event(
            make_event(role="ambiguous_open_plan", occupancy_behavior="")
        )
        == 0.55
    )
    assert (
        clear_factor_for_event(
            make_event(
                role="anchor_sensor",
                signal_type="still_target",
                occupancy_behavior="",
            )
        )
        == 0.80
    )
    assert (
        clear_factor_for_event(make_event(role="anchor_sensor", occupancy_behavior=""))
        == 0.65
    )
    assert (
        clear_factor_for_event(make_event(role="room_occupancy", occupancy_behavior=""))
        == 1.0
    )
    state = ZoneState(zone="office", occupancy_behavior="sustained")
    assert reason_for_conflict_decay(state, 0.4, ("office", "kitchen")) == (
        "competed with stronger occupied tracks (office, kitchen); "
        "confidence decayed to possible"
    )
    assert reason_for_departure_decay(state, 0.4, "hall", "kitchen") == (
        "departure inferred via hall toward kitchen; confidence decayed to possible"
    )
    assert reason_for_clear_transition_decay(state, 0.4, "hall", "kitchen") == (
        "cleared after adjacent transition via hall while kitchen had stronger "
        "active evidence; confidence decayed to possible"
    )
    handoff_reason = reason_for_occupant_handoff(state, 0.4, "hall", "kitchen")
    assert handoff_reason == (
        "one occupant left via hall toward kitchen; "
        "remaining occupancy held at possible"
    )


def test_joint_facade_projects_events_and_bounds_history() -> None:
    engine = ZoneConfidenceEngine(make_map(), expected_occupants=1)
    office = make_event(reliability=0.9)

    first = engine.observe(office)
    duplicate = engine.observe(replace(office, event_at=NOW + timedelta(seconds=1)))
    for offset in range(2, 30):
        engine.observe(replace(office, event_at=NOW + timedelta(seconds=offset)))

    assert first.current.status == "confirmed"
    assert duplicate.current.confidence == pytest.approx(first.current.confidence)
    assert engine.diagnostics.joint_last_provenance is not None
    assert engine.diagnostics.joint_last_provenance.disposition == "duplicate"
    assert len(engine.recent_events) == 25
    assert engine.tracks == ()
    assert engine.diagnostics.tracks == ()


def test_joint_facade_refresh_expiry_count_and_unknown_zone() -> None:
    engine = ZoneConfidenceEngine(make_map(), expected_occupants=1)
    office = make_event(reliability=0.9)
    engine.observe(office)

    assert engine.expire_transient_state(NOW + timedelta(minutes=10))
    assert not engine.expire_transient_state(NOW + timedelta(minutes=11))
    assert engine.refresh_active(NOW + timedelta(minutes=12)) == ()
    assert engine.state_for_zone("missing") == ZoneState(zone="missing")

    engine.reconcile_expected_occupants(0, NOW + timedelta(minutes=12))
    assert engine.config.expected_occupants == 0
    assert engine.diagnostics.joint_posterior[0].key.positions == ()


def test_joint_facade_periodically_releases_stale_low_confidence_latch() -> None:
    engine = ZoneConfidenceEngine(make_map(), expected_occupants=1)
    engine.observe(
        make_event(
            zone="hall",
            role="transition_gate",
            reliability=0.9,
        )
    )
    assert engine.diagnostics.joint_occupied_marginals["office"] <= 0.10
    engine._joint_policy.restore_states(  # noqa: SLF001
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW - timedelta(minutes=20)
                if zone == "office"
                else None,
            )
            for zone in make_map().zones()
        }
    )

    assert engine.refresh_active(NOW + timedelta(minutes=20)) == ()
    assert engine.diagnostics.joint_policy_states["office"].keep_on
    assert engine.expire_transient_state(NOW + timedelta(minutes=20))

    state = engine.diagnostics.joint_policy_states["office"]
    assert not state.keep_on
    assert state.recovery_eligible
    assert state.last_release_cause == "provisional_false_off"


def test_joint_facade_validates_count_guards_before_filter_creation() -> None:
    assert TrackerConfig(expected_occupants=1).occupant_limit == 1
    assert TrackerConfig().occupant_limit is None
    with pytest.raises(ValueError, match="non-negative"):
        OccupancyTracker(make_map(), TrackerConfig(expected_occupants=-1))

    tracker = OccupancyTracker(make_map())
    assert not tracker.suppress_last_activation("runtime_limit")
    with pytest.raises(ValueError, match="non-negative"):
        tracker.reconcile_expected_occupants(-1, NOW)
    with pytest.raises(ValueError, match="above two"):
        tracker.reject_unsupported_count(2, NOW)

    unsupported = OccupancyTracker(
        make_map(),
        TrackerConfig(expected_occupants=3),
    )
    unsupported.reject_unsupported_count(4, NOW)
    assert unsupported.requested_expected_occupants == 4
