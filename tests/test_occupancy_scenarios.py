from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.confidence import (
    ZoneConfidenceEngine,
    ZoneState,
)
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
                "upstairs_bathroom_motion": {
                    "zone": "upstairs_bathroom",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"motion": "binary_sensor.upstairs_bathroom_motion"},
                    "initial_weight": 0.7,
                    "adjacent": ["upstairs_hallway_motion"],
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
    assert states["garage"].status == "suspect"
    assert states["garage"].confidence < 0.35
    assert [track.zone for track in engine.tracks] == ["living_room"]
    assert states["guest_bedroom"].status == "rejected"
    assert states["master_bathroom"].status == "suspect"


def test_saturated_predictions_stay_inside_adjacent_zone_corridor() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=1)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    engine.apply_node_predictions(
        {"upstairs_hallway_motion": 0.60},
        source_node_id="office_motion",
    )
    assert engine.diagnostics.prediction_hints == {"upstairs_hallway": 0.60}

    office = event("office", node_id="office_motion", event_at=now)
    engine.observe(office)
    engine.apply_node_predictions(
        {
            "upstairs_hallway_motion": 0.60,
            "garage_motion": 0.40,
        },
        source_node_id="office_motion",
    )

    assert engine.diagnostics.prediction_hints == {"upstairs_hallway": 0.60}

    engine.apply_node_predictions(
        {"kitchen_motion": 0.90},
        source_node_id="garage_motion",
    )

    assert engine.diagnostics.prediction_hints == {}


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


def test_joining_occupied_room_can_fill_second_occupant_slot() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    shaila = event(
        "shaila_office",
        node_id="shaila_office_motion",
        event_at=now + timedelta(minutes=14),
    )
    engine.observe(shaila)
    engine.observe(
        replace(
            shaila,
            state="off",
            event_at=now + timedelta(minutes=14, seconds=30),
        )
    )

    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(minutes=15),
    )
    engine.observe(hallway)
    engine.observe(
        replace(
            hallway,
            state="off",
            event_at=now + timedelta(minutes=15, seconds=20),
        )
    )

    joined = replace(shaila, event_at=now + timedelta(minutes=16))
    engine.observe(joined)

    states = engine.states
    tracks = engine.tracks
    diagnostics = engine.diagnostics
    assert [track.zone for track in tracks] == ["shaila_office", "shaila_office"]
    assert states["shaila_office"].explanation["join_transition"] == {
        "zone": "shaila_office",
        "source_zone": "upstairs_hallway",
        "source_node_id": "upstairs_hallway_motion",
        "event_at": joined.event_at.isoformat(),
        "expires_at": (joined.event_at + timedelta(minutes=5)).isoformat(),
    }
    assert diagnostics.inferred_join_slots[0].source_zone == "upstairs_hallway"
    assert "competed" not in states["upstairs_hallway"].reason
    assert states["guest_bedroom"].status == "rejected"
    assert states["master_bathroom"].confidence < 0.10
    assert states["master_bathroom"].reason.count("shaila_office") == 2


def test_lone_motion_in_occupied_room_does_not_infer_joined_occupant() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    mark_stale_guest_and_bathroom(engine, now)

    shaila = event(
        "shaila_office",
        node_id="shaila_office_motion",
        event_at=now + timedelta(minutes=14),
    )
    engine.observe(shaila)
    engine.observe(
        replace(
            shaila,
            state="off",
            event_at=now + timedelta(minutes=14, seconds=30),
        )
    )
    engine.observe(replace(shaila, event_at=now + timedelta(minutes=16)))

    states = engine.states
    assert [track.zone for track in engine.tracks] == [
        "shaila_office",
        "master_bathroom",
    ]
    assert engine.diagnostics.inferred_join_slots == ()
    assert "join_transition" not in states["shaila_office"].explanation
    assert states["master_bathroom"].confidence > 0.70


def test_departure_through_transition_zone_decays_source_room() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=0)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    office = event("office", node_id="office_motion", event_at=now)
    engine.observe(office)
    engine.observe(replace(office, state="off", event_at=now + timedelta(minutes=1)))

    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(minutes=2),
    )
    engine.observe(hallway)
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(minutes=3)))

    kitchen = event(
        "kitchen",
        node_id="kitchen_motion",
        reliability=0.8,
        event_at=now + timedelta(minutes=4),
    )
    engine.observe(kitchen)

    states = engine.states
    assert states["office"].status == "suspect"
    assert states["office"].confidence == 0.149
    assert states["office"].explanation["type"] == "departure_decay"
    assert states["office"].explanation["departure"]["via_zone"] == "upstairs_hallway"
    assert engine.diagnostics.inferred_departures[0].destination_zone == "kitchen"


def test_cleared_room_after_adjacent_transition_decays_toward_active_track() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=1)
    now = datetime(2026, 6, 12, 19, 59, 28, tzinfo=UTC)

    office = event("office", node_id="office_motion", event_at=now)
    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(seconds=13),
    )
    bathroom = event(
        "upstairs_bathroom",
        node_id="upstairs_bathroom_motion",
        behavior="sticky",
        reliability=0.7,
        event_at=now + timedelta(seconds=16),
    )

    engine.observe(office)
    engine.observe(hallway)
    engine.observe(bathroom)
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(seconds=23)))
    engine.observe(replace(hallway, event_at=now + timedelta(seconds=29)))
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(seconds=39)))
    engine.observe(replace(bathroom, state="off", event_at=now + timedelta(seconds=57)))

    states = engine.states
    assert states["office"].status == "probable"
    assert states["upstairs_bathroom"].status == "suspect"
    assert states["upstairs_bathroom"].confidence < 0.35
    assert states["upstairs_bathroom"].explanation["type"] == "clear_transition_decay"
    assert states["upstairs_bathroom"].explanation["departure"] == {
        "zone": "upstairs_bathroom",
        "via_zone": "upstairs_hallway",
        "via_node_id": "upstairs_hallway_motion",
        "destination_zone": "office",
        "event_at": (now + timedelta(seconds=57)).isoformat(),
        "expires_at": (now + timedelta(minutes=5, seconds=57)).isoformat(),
    }
    assert engine.diagnostics.inferred_departures[0].zone == "upstairs_bathroom"


def test_cleared_room_without_adjacent_transition_uses_normal_clear_decay() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=0)
    now = datetime(2026, 6, 12, 19, 59, 28, tzinfo=UTC)

    bathroom = event(
        "upstairs_bathroom",
        node_id="upstairs_bathroom_motion",
        behavior="sticky",
        reliability=0.7,
        event_at=now,
    )

    engine.observe(bathroom)
    engine.observe(replace(bathroom, state="off", event_at=now + timedelta(minutes=1)))

    state = engine.states["upstairs_bathroom"]
    assert state.status == "possible"
    assert state.explanation["type"] == "event"
    assert engine.diagnostics.inferred_departures == ()


def test_cleared_room_without_evidence_timestamp_uses_normal_clear_decay() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=0)
    now = datetime(2026, 6, 12, 19, 59, 28, tzinfo=UTC)
    engine._states["upstairs_bathroom"] = ZoneState(
        zone="upstairs_bathroom",
        confidence=0.5,
        status="possible",
        occupancy_behavior="sticky",
    )

    bathroom_clear = event(
        "upstairs_bathroom",
        node_id="upstairs_bathroom_motion",
        behavior="sticky",
        state="off",
        event_at=now,
    )

    engine.observe(bathroom_clear)

    state = engine.states["upstairs_bathroom"]
    assert state.status == "possible"
    assert state.explanation["type"] == "event"
    assert engine.diagnostics.inferred_departures == ()


def test_cleared_room_needs_stronger_active_destination_to_decay() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=0)
    now = datetime(2026, 6, 12, 19, 59, 28, tzinfo=UTC)

    office = event("office", node_id="office_motion", event_at=now)
    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(seconds=13),
    )
    bathroom = event(
        "upstairs_bathroom",
        node_id="upstairs_bathroom_motion",
        behavior="sticky",
        signal_type="still_target",
        reliability=0.9,
        event_at=now + timedelta(seconds=16),
    )

    engine.observe(office)
    engine.observe(hallway)
    engine.observe(bathroom)
    engine.observe(replace(hallway, state="off", event_at=now + timedelta(seconds=23)))
    engine.observe(replace(bathroom, state="off", event_at=now + timedelta(seconds=57)))

    state = engine.states["upstairs_bathroom"]
    assert state.status == "probable"
    assert state.explanation["type"] == "event"
    assert engine.diagnostics.inferred_departures == ()


def test_transition_seconds_can_tighten_join_window() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
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
                    "adjacent": ["shaila_office_motion"],
                    "transition_seconds": {"shaila_office_motion": 20},
                },
            }
        }
    )
    engine = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    shaila = event(
        "shaila_office",
        node_id="shaila_office_motion",
        event_at=now,
    )
    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now + timedelta(seconds=30),
    )

    engine.observe(shaila)
    engine.observe(replace(shaila, state="off", event_at=now + timedelta(seconds=5)))
    engine.observe(hallway)
    engine.observe(replace(shaila, event_at=now + timedelta(seconds=55)))

    assert engine.diagnostics.inferred_join_slots == ()
    assert [track.zone for track in engine.tracks] == [
        "shaila_office",
        "upstairs_hallway",
    ]


def test_adjacent_motion_latches_entry_plausibility_for_target_zone() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=0)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    hallway = event(
        "upstairs_hallway",
        node_id="upstairs_hallway_motion",
        role="transition_gate",
        behavior="transient",
        reliability=0.85,
        event_at=now,
    )
    engine.observe(hallway)

    plausibilities = {
        plausibility.zone: plausibility
        for plausibility in engine.diagnostics.entry_plausibilities
    }
    assert sorted(plausibilities) == [
        "kitchen",
        "office",
        "shaila_office",
        "upstairs_bathroom",
    ]
    assert plausibilities["office"].source_zone == "upstairs_hallway"
    assert plausibilities["office"].source_node_id == "upstairs_hallway_motion"
    assert plausibilities["office"].expires_at == now + timedelta(seconds=30)

    assert not engine.expire_transient_state(now + timedelta(seconds=20))
    assert engine.expire_transient_state(now + timedelta(seconds=31))
    assert engine.diagnostics.entry_plausibilities == ()


def test_entry_plausibility_uses_configured_transition_seconds() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "hallway_motion": {
                    "zone": "hallway",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hallway_motion"},
                    "adjacent": ["closet_motion", "bathroom_motion"],
                    "transition_seconds": {
                        "closet_motion": 12,
                        "bathroom_motion": 45,
                    },
                },
                "closet_motion": {
                    "zone": "closet",
                    "entities": {"motion": "binary_sensor.closet_motion"},
                    "adjacent": ["hallway_motion"],
                },
                "bathroom_motion": {
                    "zone": "bathroom",
                    "entities": {"motion": "binary_sensor.bathroom_motion"},
                    "adjacent": ["hallway_motion"],
                },
            }
        }
    )
    engine = ZoneConfidenceEngine(predictive_map, expected_occupants=0)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    engine.observe(
        event(
            "hallway",
            node_id="hallway_motion",
            role="transition_gate",
            behavior="transient",
            event_at=now,
        )
    )

    plausibilities = {
        plausibility.zone: plausibility
        for plausibility in engine.diagnostics.entry_plausibilities
    }
    assert plausibilities["closet"].expires_at == now + timedelta(seconds=12)
    assert plausibilities["bathroom"].expires_at == now + timedelta(seconds=45)


def test_overlapping_signals_in_same_room_count_as_one_occupant() -> None:
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

    # The two radar signals overlap for a single person (a slow walker trips both
    # still and moving), so they must count as ONE occupant, not two. With only
    # one occupant accounted for, the count is not saturated and the stale
    # bathroom is not competed away.
    states = engine.states
    assert states["living_room"].status == "confirmed"
    assert [track.zone for track in engine.tracks].count("living_room") == 1
    assert states["master_bathroom"].confidence > 0.70
    assert "competed" not in states["master_bathroom"].reason


def test_multi_signal_room_does_not_crowd_out_a_second_occupant() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    # A second person settles in the office first.
    engine.observe(event("office", node_id="office_motion", event_at=now))

    # One person in the living room trips both radar signals.
    engine.observe(
        event(
            "living_room",
            node_id="living_still",
            entity_id="binary_sensor.living_still",
            role="anchor_sensor",
            behavior="sticky",
            signal_type="still_target",
            reliability=0.9,
            event_at=now + timedelta(seconds=1),
        )
    )
    engine.observe(
        event(
            "living_room",
            node_id="living_motion",
            entity_id="binary_sensor.living_motion",
            role="anchor_sensor",
            behavior="sticky",
            reliability=0.9,
            event_at=now + timedelta(seconds=2),
        )
    )

    # The living room's two overlapping signals must not fill both occupant slots
    # and hide the office; both real occupants are counted in distinct zones.
    track_zones = [track.zone for track in engine.tracks]
    assert set(track_zones) == {"living_room", "office"}
    assert track_zones.count("living_room") == 1


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


def test_partial_departure_from_joined_room_retains_occupancy() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    shaila = event("shaila_office", node_id="shaila_office_motion", event_at=now)
    engine.observe(shaila)

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

    # A second person transitions in and joins the occupied office.
    joined = replace(shaila, event_at=now + timedelta(seconds=60))
    engine.observe(joined)
    assert engine.diagnostics.inferred_join_slots

    # The joined office is now a saturated two-occupant track. That second person
    # walks off to the kitchen via the hallway while the first stays put. The
    # hallway breadcrumb links the kitchen back to the office, so the arrival is
    # a real move (not a non-adjacent false positive) and the extra-occupant slot
    # is released to follow the person.
    kitchen = event(
        "kitchen",
        node_id="kitchen_motion",
        reliability=0.8,
        event_at=now + timedelta(minutes=2),
    )
    engine.observe(kitchen)

    states = engine.states
    assert engine.diagnostics.inferred_join_slots == ()
    assert states["kitchen"].confidence > 0.34
    assert states["kitchen"].status in {"probable", "confirmed"}
    # The office is not abandoned; the remaining occupant keeps it occupied.
    assert states["shaila_office"].status in {"probable", "confirmed"}


def test_arrival_elsewhere_decrements_joined_room_without_abandoning() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    shaila = event("shaila_office", node_id="shaila_office_motion", event_at=now)
    engine.observe(shaila)

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

    joined = replace(shaila, event_at=now + timedelta(seconds=60))
    engine.observe(joined)
    assert engine.diagnostics.inferred_join_slots

    # The office sensor clears with no active destination yet, so no departure is
    # inferred and the extra-occupant slot persists on the still-confident zone.
    engine.observe(replace(shaila, state="off", event_at=now + timedelta(seconds=90)))
    assert engine.diagnostics.inferred_join_slots
    assert all(
        departure.zone != "shaila_office"
        for departure in engine.diagnostics.inferred_departures
    )

    # Someone now arrives in the office via the hallway. The inferred departure is
    # a handoff from the joined room: it decrements the extra occupant instead of
    # abandoning the room.
    hallway2 = replace(hallway, event_at=now + timedelta(minutes=2))
    engine.observe(hallway2)
    engine.observe(
        replace(hallway2, state="off", event_at=now + timedelta(minutes=2, seconds=15))
    )
    office = event(
        "office",
        node_id="office_motion",
        event_at=now + timedelta(minutes=2, seconds=20),
    )
    engine.observe(office)

    states = engine.states
    assert engine.diagnostics.inferred_join_slots == ()
    assert states["shaila_office"].explanation["type"] == "occupant_handoff"
    assert "one occupant left" in states["shaila_office"].reason
    assert states["shaila_office"].status in {"possible", "probable", "confirmed"}
    assert all(
        departure.zone != "shaila_office"
        for departure in engine.diagnostics.inferred_departures
    )


def test_join_slot_persists_while_occupied_and_clears_when_zone_empties() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    shaila = event("shaila_office", node_id="shaila_office_motion", event_at=now)
    engine.observe(shaila)

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

    joined = replace(shaila, event_at=now + timedelta(seconds=60))
    engine.observe(joined)
    assert engine.diagnostics.inferred_join_slots

    # Well past the old fixed 5-minute retention, but the room is still occupied,
    # so the extra-occupant slot must persist.
    engine.refresh_active(now + timedelta(minutes=10))
    engine.expire_transient_state(now + timedelta(minutes=10))
    assert engine.diagnostics.inferred_join_slots

    # The room fully empties and decays to rejected -> the join slot is cleared.
    engine.observe(
        replace(shaila, state="off", event_at=now + timedelta(minutes=10, seconds=30))
    )
    engine.refresh_active(now + timedelta(hours=4))
    engine.expire_transient_state(now + timedelta(hours=4))
    assert engine.diagnostics.inferred_join_slots == ()
    assert engine.states["shaila_office"].status == "rejected"


def test_multi_hop_trail_prevents_false_positive_cap() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    # Two occupants are settled: the count is saturated by the two office tracks.
    engine.observe(event("office", node_id="office_motion", event_at=now))
    engine.observe(
        event(
            "shaila_office",
            node_id="shaila_office_motion",
            event_at=now + timedelta(seconds=1),
        )
    )

    # A fresh motion trail runs office-cluster -> hallway -> kitchen. The kitchen
    # is two hops from the saturated tracks, so a fixed radius-1 corridor would
    # cap it as a non-adjacent false positive. The hallway breadcrumb links it,
    # so the trail-following corridor recognizes it as a real move.
    engine.observe(
        event(
            "upstairs_hallway",
            node_id="upstairs_hallway_motion",
            role="transition_gate",
            behavior="transient",
            reliability=0.85,
            event_at=now + timedelta(seconds=30),
        )
    )
    engine.observe(
        event(
            "kitchen",
            node_id="kitchen_motion",
            reliability=0.8,
            event_at=now + timedelta(seconds=45),
        )
    )

    states = engine.states
    assert states["kitchen"].confidence > 0.34
    assert states["kitchen"].status in {"probable", "confirmed"}
    assert "capped as suspect" not in states["kitchen"].reason


def test_disconnected_popup_is_capped_as_false_positive() -> None:
    engine = ZoneConfidenceEngine(make_house_map(), expected_occupants=2)
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    # Two occupants are settled in two rooms (count saturated).
    engine.observe(event("office", node_id="office_motion", event_at=now))
    engine.observe(
        event(
            "shaila_office",
            node_id="shaila_office_motion",
            event_at=now + timedelta(seconds=1),
        )
    )

    # Bathroom motion pops up with no connecting motion trail through the hallway.
    # Under full coverage a real move would have tripped the hallway, so with the
    # count already saturated this is a false positive and must be capped.
    engine.observe(
        event(
            "upstairs_bathroom",
            node_id="upstairs_bathroom_motion",
            behavior="sticky",
            reliability=0.7,
            event_at=now + timedelta(seconds=2),
        )
    )

    states = engine.states
    assert states["upstairs_bathroom"].confidence <= 0.34
    assert states["upstairs_bathroom"].status == "suspect"
    assert "capped as suspect" in states["upstairs_bathroom"].reason
