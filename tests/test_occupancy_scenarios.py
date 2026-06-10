from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap


def make_house_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_motion": {
                    "zone": "office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.office_motion"},
                    "initial_weight": 0.75,
                    "adjacent": ["upstairs_hallway_motion"],
                },
                "shaila_office_motion": {
                    "zone": "shaila_office",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.shaila_office_motion"},
                    "initial_weight": 0.75,
                    "adjacent": ["upstairs_hallway_motion"],
                },
                "upstairs_hallway_motion": {
                    "zone": "upstairs_hallway",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.upstairs_hallway_motion"},
                    "initial_weight": 0.85,
                    "adjacent": [
                        "office_motion",
                        "shaila_office_motion",
                        "kitchen_motion",
                    ],
                },
                "kitchen_motion": {
                    "zone": "kitchen",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.kitchen_motion"},
                    "initial_weight": 0.8,
                    "adjacent": ["upstairs_hallway_motion"],
                },
                "living_still": {
                    "zone": "living_room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"still_target": "binary_sensor.living_still"},
                    "initial_weight": 0.9,
                    "adjacent": [],
                },
                "living_motion": {
                    "zone": "living_room",
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"motion": "binary_sensor.living_motion"},
                    "initial_weight": 0.9,
                    "adjacent": [],
                },
                "guest_bedroom_motion": {
                    "zone": "guest_bedroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.guest_bedroom_motion"},
                    "initial_weight": 0.75,
                    "adjacent": [],
                },
                "master_bathroom_motion": {
                    "zone": "master_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"motion": "binary_sensor.master_bathroom_motion"},
                    "initial_weight": 0.7,
                    "adjacent": [],
                },
                "garage_motion": {
                    "zone": "garage",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.garage_motion"},
                    "initial_weight": 0.75,
                    "adjacent": [],
                },
            }
        }
    )


def event(
    zone: str,
    *,
    node_id: str | None = None,
    entity_id: str | None = None,
    role: str = "room_occupancy",
    behavior: str = "sustained",
    signal_type: str = "motion",
    state: str = "on",
    event_at: datetime | None = None,
    reliability: float = 0.75,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{node_id or zone}",
        node_id=node_id or zone,
        zone=zone,
        floor="second_floor",
        role=role,
        occupancy_behavior=behavior,
        signal_type=signal_type,
        state=state,
        event_at=event_at or datetime(2026, 6, 7, 12, tzinfo=UTC),
        reliability=reliability,
    )


def mark_stale_guest_and_bathroom(
    engine: ZoneConfidenceEngine, now: datetime
) -> None:
    guest = event(
        "guest_bedroom",
        node_id="guest_bedroom_motion",
        event_at=now,
    )
    engine.observe(guest)
    engine.observe(replace(guest, state="off", event_at=now + timedelta(minutes=1)))

    bathroom = event(
        "master_bathroom",
        node_id="master_bathroom_motion",
        behavior="sticky",
        reliability=0.7,
        event_at=now + timedelta(minutes=2),
    )
    engine.observe(bathroom)
    engine.refresh_active(now + timedelta(minutes=12))
    engine.observe(
        replace(bathroom, state="off", event_at=now + timedelta(minutes=13))
    )


def test_transition_sensor_corridor_is_preserved_while_source_room_drops() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=1)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    office = event("office", node_id="office_motion", event_at=now)
    engine.observe(office)
    engine.observe(replace(office, state="off", event_at=now + timedelta(seconds=20)))

    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(seconds=30),
    )
    engine.observe(hallway)
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(seconds=45)))

    kitchen = event(
        "kitchen",
        node_id="kitchen_motion",
        reliability=0.8,
        event_at=now + timedelta(seconds=60),
    )
    engine.observe(kitchen)

    states = engine.states
    assert states["kitchen"].status == "probable"
    assert states["upstairs_hallway"].confidence == 0.132
    assert "competed" not in states["upstairs_hallway"].reason
    assert states["office"].confidence < 0.20
    assert "competed" in states["office"].reason


def test_staying_put_still_target_survives_unrelated_false_positive() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=1)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    living = event(
        "living_room",
        node_id="living_still",
        entity_id="binary_sensor.living_still",
        role="anchor_sensor",
        behavior="sticky",
        signal_type="still_target",
        reliability=0.9,
        event_at=now + timedelta(minutes=14),
    )
    engine.observe(living)
    engine.refresh_active(now + timedelta(minutes=24))

    false_positive = event(
        "garage",
        node_id="garage_motion",
        event_at=now + timedelta(minutes=25),
    )
    engine.observe(false_positive)
    engine.observe(
        replace(
            false_positive,
            state="off",
            event_at=now + timedelta(minutes=25, seconds=5),
        )
    )

    states = engine.states
    assert states["living_room"].status == "confirmed"
    assert states["living_room"].confidence == 0.99
    assert states["garage"].status == "possible"
    assert states["guest_bedroom"].status == "rejected"
    assert states["master_bathroom"].status == "suspect"


def test_two_people_moving_in_separate_tracks_decay_unrelated_stale_rooms() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    shaila = event(
        "shaila_office",
        node_id="shaila_office_motion",
        event_at=now + timedelta(minutes=14),
    )
    engine.observe(shaila)

    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(minutes=15),
    )
    engine.observe(hallway)
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(minutes=16)))

    kitchen = event(
        "kitchen",
        node_id="kitchen_motion",
        reliability=0.8,
        event_at=now + timedelta(minutes=17),
    )
    engine.observe(kitchen)

    states = engine.states
    assert states["shaila_office"].status == "probable"
    assert states["kitchen"].status == "probable"
    assert "competed" not in states["upstairs_hallway"].reason
    assert states["guest_bedroom"].status == "rejected"
    assert states["master_bathroom"].status == "suspect"
    assert "shaila_office" in states["master_bathroom"].reason
    assert "kitchen" in states["master_bathroom"].reason


def test_two_independent_signals_in_same_room_can_fill_two_occupant_slots() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    living_still = event(
        "living_room",
        node_id="living_still",
        entity_id="binary_sensor.living_still",
        role="anchor_sensor",
        behavior="sticky",
        signal_type="still_target",
        reliability=0.9,
        event_at=now + timedelta(minutes=14),
    )
    living_motion = event(
        "living_room",
        node_id="living_motion",
        entity_id="binary_sensor.living_motion",
        role="anchor_sensor",
        behavior="sticky",
        reliability=0.9,
        event_at=now + timedelta(minutes=15),
    )
    engine.observe(living_still)
    engine.observe(living_motion)

    states = engine.states
    assert states["living_room"].status == "confirmed"
    assert states["guest_bedroom"].status == "rejected"
    assert states["master_bathroom"].status == "suspect"
    assert states["master_bathroom"].reason.count("living_room") == 2


def test_single_signal_in_same_room_does_not_fill_two_occupant_slots() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    living_still = event(
        "living_room",
        node_id="living_still",
        entity_id="binary_sensor.living_still",
        role="anchor_sensor",
        behavior="sticky",
        signal_type="still_target",
        reliability=0.9,
        event_at=now + timedelta(minutes=14),
    )
    engine.observe(living_still)

    states = engine.states
    assert states["living_room"].status == "confirmed"
    assert states["master_bathroom"].confidence > 0.70
    assert "competed" not in states["master_bathroom"].reason
