from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_replay import (
    history_events_from_states,
    replay_events,
)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_motion": {
                    "zone": "office",
                    "entities": {"motion": "binary_sensor.office_motion"},
                    "occupancy_behavior": "sustained",
                },
                "hall_motion": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "entities": {"motion": "binary_sensor.hall_motion"},
                    "occupancy_behavior": "transient",
                },
            }
        }
    )


def event(zone: str, state: str, event_at: datetime) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=f"binary_sensor.{zone}_motion",
        node_id=f"{zone}_motion",
        zone=zone,
        floor="first_floor",
        role="room_occupancy" if zone == "office" else "transition_gate",
        occupancy_behavior="sustained" if zone == "office" else "transient",
        signal_type="motion",
        state=state,
        event_at=event_at,
        reliability=0.8,
    )


def test_replay_events_applies_sorted_trace_and_snapshots_states() -> None:
    tracker = ZoneConfidenceEngine(make_map())
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    result = replay_events(
        tracker,
        (
            event("office", "off", now + timedelta(minutes=5)),
            event("office", "on", now),
        ),
    )

    assert len(result.steps) == 2
    assert result.steps[0].event.state == "on"
    assert result.steps[0].zone_states["office"].status == "probable"
    assert result.final_states["office"].status == "possible"


def test_replay_events_can_skip_refresh_between_events() -> None:
    tracker = ZoneConfidenceEngine(make_map())
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)

    result = replay_events(
        tracker,
        (event("office", "on", now), event("office", "off", now + timedelta(hours=1))),
        refresh_before_events=False,
    )

    assert result.final_states["office"].confidence == 0.432


def test_history_events_from_states_imports_home_assistant_history_rows() -> None:
    events = history_events_from_states(
        make_map(),
        [
            [
                {
                    "entity_id": "binary_sensor.office_motion",
                    "state": "on",
                    "last_changed": "2026-06-07T12:00:00+00:00",
                },
                {
                    "entity_id": "binary_sensor.office_motion",
                    "state": "off",
                    "last_changed": "2026-06-07T12:05:00Z",
                },
            ],
            {
                "entity_id": "binary_sensor.hall_motion",
                "state": "unknown",
                "last_changed": "2026-06-07T12:06:00+00:00",
            },
            {
                "entity_id": 123,
                "state": "on",
                "last_changed": "2026-06-07T12:07:00+00:00",
            },
            b"not a row",
            {
                "entity_id": "binary_sensor.missing",
                "state": "on",
                "last_changed": "2026-06-07T12:07:00+00:00",
            },
            {"entity_id": "binary_sensor.office_motion", "state": "on"},
        ],
    )

    assert [event.state for event in events] == ["on", "off"]
    assert events[1].event_at == datetime(2026, 6, 7, 12, 5, tzinfo=UTC)
