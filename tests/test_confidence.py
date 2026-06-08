from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.confidence import (
    CONFIDENCE_STATUSES,
    ZoneConfidenceEngine,
    clear_factor_for_event,
    on_confidence_floor,
    reason_for_event,
    reason_for_sustained_event,
    status_for_confidence,
    sustained_confidence_for_duration,
    sustained_ramp_seconds,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "foyer": {
                    "zone": "foyer",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.foyer"},
                    "initial_weight": 0.85,
                },
                "living_left": {
                    "zone": "living_room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"still_target": "binary_sensor.living_still"},
                    "initial_weight": 0.9,
                },
                "kitchen": {
                    "zone": "kitchen",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "initial_weight": 0.8,
                },
            }
        }
    )


def make_event(
    *,
    zone: str = "kitchen",
    role: str = "room_occupancy",
    signal_type: str = "motion",
    state: str = "on",
    reliability: float = 0.8,
    occupancy_behavior: str | None = None,
) -> OccupancyEvent:
    if occupancy_behavior is None:
        occupancy_behavior = {
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
        occupancy_behavior=occupancy_behavior,
        signal_type=signal_type,
        state=state,
        event_at=datetime(2026, 6, 7, tzinfo=UTC),
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
    assert status_for_confidence(0.0) == "rejected"
    assert status_for_confidence(0.2) == "suspect"
    assert status_for_confidence(0.5) == "possible"
    assert status_for_confidence(0.7) == "probable"
    assert status_for_confidence(0.9) == "confirmed"


def test_on_confidence_floor_uses_role_signal_and_reliability() -> None:
    transition = make_event(zone="foyer", role="transition_gate", reliability=0.85)
    ambiguous = make_event(role="ambiguous_open_plan", reliability=0.75)
    subzone = make_event(role="subzone_occupancy", reliability=0.8)
    still_target = make_event(
        zone="living_room",
        role="anchor_sensor",
        signal_type="still_target",
        reliability=0.9,
    )
    target = make_event(signal_type="target", reliability=0.9)
    zone_occupancy = make_event(signal_type="zone_occupancy", reliability=0.9)
    moving_target = make_event(
        role="transition_gate", signal_type="moving_target", reliability=0.9
    )
    capped_reliability = make_event(reliability=2.0)

    assert on_confidence_floor(transition) == 0.529
    assert on_confidence_floor(ambiguous) == 0.544
    assert on_confidence_floor(subzone) == 0.57
    assert on_confidence_floor(still_target) == 0.877
    assert on_confidence_floor(target) == 0.722
    assert on_confidence_floor(zone_occupancy) == 0.722
    assert on_confidence_floor(moving_target) == 0.605
    assert on_confidence_floor(capped_reliability) == 0.65


def test_clear_factor_keeps_anchor_still_confidence_longer() -> None:
    assert clear_factor_for_event(make_event(role="transition_gate")) == 0.25
    assert clear_factor_for_event(make_event(role="ambiguous_open_plan")) == 0.55
    assert clear_factor_for_event(make_event(role="subzone_occupancy")) == 0.70
    assert clear_factor_for_event(make_event(signal_type="still_target")) == 0.70
    assert (
        clear_factor_for_event(
            make_event(role="anchor_sensor", signal_type="still_target")
        )
        == 0.85
    )
    assert clear_factor_for_event(
        make_event(role="unknown_role", occupancy_behavior="")
    ) == 0.60


def test_legacy_role_fallbacks_without_occupancy_behavior() -> None:
    transition = make_event(role="transition_gate", occupancy_behavior="")
    ambiguous = make_event(role="ambiguous_open_plan", occupancy_behavior="")
    anchor = make_event(role="anchor_sensor", occupancy_behavior="")
    room = make_event(role="room_occupancy", occupancy_behavior="")

    assert clear_factor_for_event(transition) == 0.25
    assert clear_factor_for_event(ambiguous) == 0.55
    assert clear_factor_for_event(anchor) == 0.65
    assert clear_factor_for_event(room) == 0.70


def test_sustained_confidence_uses_behavior_caps_and_duration() -> None:
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

    assert sustained_confidence_for_duration(
        sustained, timedelta(minutes=2), 0.609
    ) == 0.697
    assert sustained_confidence_for_duration(
        sustained, timedelta(minutes=10), 0.609
    ) == 0.96
    assert sustained_confidence_for_duration(
        transient, timedelta(minutes=10), 0.529
    ) == 0.70
    assert sustained_confidence_for_duration(
        sticky, timedelta(minutes=10), 0.877
    ) == 0.99
    assert sustained_confidence_for_duration(
        make_event(signal_type="target"), timedelta(minutes=10), 0.617
    ) == 0.96
    assert sustained_confidence_for_duration(
        make_event(occupancy_behavior="unknown"), timedelta(minutes=10), 0.617
    ) == 0.90
    assert sustained_confidence_for_duration(
        sustained, timedelta(seconds=-30), 0.7
    ) == 0.7
    assert sustained_confidence_for_duration(
        sustained, timedelta(minutes=1), 0.98
    ) == 0.98
    assert sustained_ramp_seconds("unknown") == 600.0


def test_zone_confidence_engine_updates_and_records_recent_events() -> None:
    engine = ZoneConfidenceEngine(make_map())
    now = datetime(2026, 6, 7, tzinfo=UTC)
    on_event = make_event(state="on")
    off_event = replace(
        make_event(state="off"),
        event_at=now + timedelta(seconds=30),
    )

    first = engine.observe(on_event)
    second = engine.observe(off_event)

    assert first.previous.status == "rejected"
    assert first.current.status == "probable"
    assert first.current.occupancy_behavior == "sustained"
    assert first.current.active_since == on_event.event_at
    assert first.current.last_evidence_at == on_event.event_at
    assert second.current.status == "possible"
    assert second.current.active_since is None
    assert second.current.last_clear_at == off_event.event_at
    assert engine.states["kitchen"] == second.current
    assert engine.state_for_zone("kitchen") == second.current
    assert engine.state_for_zone("missing").status == "rejected"
    assert engine.recent_events == (on_event, off_event)


def test_zone_confidence_engine_increments_existing_confidence() -> None:
    engine = ZoneConfidenceEngine(make_map())
    event = make_event(state="on")

    first = engine.observe(event)
    second = engine.observe(
        replace(event, event_at=event.event_at + timedelta(seconds=5))
    )

    assert first.current.confidence == 0.617
    assert second.current.confidence == 0.681


def test_zone_confidence_engine_refreshes_active_duration() -> None:
    engine = ZoneConfidenceEngine(make_map())
    event = make_event(reliability=0.75)

    first = engine.observe(event)
    updates = engine.refresh_active(event.event_at + timedelta(minutes=10))

    assert first.current.confidence == 0.609
    assert len(updates) == 1
    assert updates[0].current.confidence == 0.96
    assert updates[0].current.status == "confirmed"
    assert updates[0].current.reason == (
        "motion active at kitchen for 10 min; sustained confidence is confirmed"
    )
    assert engine.refresh_active(event.event_at + timedelta(minutes=11)) == ()
    engine.observe(
        replace(event, state="off", event_at=event.event_at + timedelta(minutes=12))
    )
    assert engine.refresh_active(event.event_at + timedelta(minutes=13)) == ()


def test_zone_confidence_engine_caps_confidence_and_limits_recent_events() -> None:
    engine = ZoneConfidenceEngine(make_map())
    event = make_event(reliability=2.0)

    for offset in range(30):
        update = engine.observe(
            replace(event, event_at=event.event_at + timedelta(seconds=offset))
        )

    assert update.current.confidence == 1.0
    assert len(engine.recent_events) == 25
    assert engine.recent_events[0].event_at == event.event_at + timedelta(seconds=5)


def test_reason_for_event_describes_on_and_off_events() -> None:
    on_event = make_event(state="on")
    off_event = make_event(state="off")

    assert reason_for_event(on_event, 0.7) == (
        "motion active at kitchen; confidence is probable"
    )
    assert reason_for_event(off_event, 0.4) == (
        "motion cleared at kitchen; confidence decayed to possible"
    )
    assert reason_for_sustained_event(
        on_event, 0.9, on_event.event_at + timedelta(minutes=5)
    ) == "motion active at kitchen for 5 min; sustained confidence is confirmed"
