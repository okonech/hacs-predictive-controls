"""User-reported issue: original wording unavailable; retained-test reconstruction.
User expected: a cleared/fresh transition episode must not retain an active warning.
Observed: retained Aug23 fixture records the hall cadence sequence beginning
23:18:09.318691Z and recovery at 23:19:42.568890Z, with a stale-warning expectation.
Source: /tmp/black-box-migration-baseline.json, Aug23 2318Z original source.
Test scope: warning-only public Reliability sensor, not light state or Problem.
The generic two-node map is reconstructed; the first retained ON is the origin.
All five original inputs/order and effective reliability 1.0 remain. No new setup,
forced diagnostic write or checkpoint shift. 2026-09-12 user-approved amendment:
the original two completed quick cycles must NOT warn. Separate synthetic extensions
complete five/six cycles and check the actual sampled warning and hourly recovery.
The original stale-warning report remains provenance, not current threshold policy.
2026-09-16 user-approved recalibration: preserve the original primary and5/6-cycle
extensions as quiet cases; add9/10 boundaries and20minute warning recovery.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import InputDelivery, RuntimeScenario


def target_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["room"],
                },
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


@pytest.mark.target_model
@pytest.mark.scenario
@pytest.mark.parametrize("checkpoint", ("warned", "stable_clear", "recovered"))
def test_inc_2026_08_23_2318z_fresh_transition_episode_clears_cadence_warning(
    checkpoint: str,
) -> None:
    asserted_at = datetime(2026, 8, 23, 23, 18, 9, 318691, tzinfo=UTC)
    cleared_at = datetime(2026, 8, 23, 23, 18, 22, 409960, tzinfo=UTC)
    warned_at = datetime(2026, 8, 23, 23, 18, 23, 996249, tzinfo=UTC)
    final_clear_at = datetime(2026, 8, 23, 23, 18, 35, 938992, tzinfo=UTC)
    stable_clear_at = final_clear_at + timedelta(seconds=5)
    recovered_at = datetime(2026, 8, 23, 23, 19, 42, 568890, tzinfo=UTC)

    with RuntimeScenario(asserted_at) as scenario:
        replay = scenario.create(target_map(), 1).watch_reliability()
        replay.observe(SensorInput("binary_sensor.hall", "on", asserted_at))
        replay.observe(SensorInput("binary_sensor.hall", "off", cleared_at))
        replay.observe(SensorInput("binary_sensor.hall", "on", warned_at))
        warned = replay.reliability_attributes
        replay.observe(SensorInput("binary_sensor.hall", "off", final_clear_at))
        replay.advance(stable_clear_at)
        stable_clear = replay.reliability_attributes
        replay.observe(SensorInput("binary_sensor.hall", "on", recovered_at))
        recovered = replay.reliability_attributes

        expected_inputs = tuple(SensorInput(
            "binary_sensor.hall", state, datetime.fromisoformat(at),
            reliability=1.0,
        ) for state, at in (
            ("on", "2026-08-23T23:18:09.318691+00:00"),
            ("off", "2026-08-23T23:18:22.409960+00:00"),
            ("on", "2026-08-23T23:18:23.996249+00:00"),
            ("off", "2026-08-23T23:18:35.938992+00:00"),
            ("on", "2026-08-23T23:19:42.568890+00:00"),
        ))
        assert replay.deliveries == tuple(InputDelivery(
            event.entity_id, event.state, event.event_at, event.event_at,
            event.event_at, event, event, False, True,
        ) for event in expected_inputs)
        published = {
            "warned": warned, "stable_clear": stable_clear, "recovered": recovered,
        }[checkpoint]
        if checkpoint == "warned":
            # The original checkpoint precedes the first scheduled publication.
            assert published is None
            assert replay.reliability_writes[0].at == asserted_at + timedelta(
                seconds=30,
            )
        else:
            assert published is not None
            assert published["active_count"] == 0
            assert published["warnings"] == []
        assert all(write.value == 0 and write.attributes["warnings"] == []
                   for write in replay.reliability_writes)
        assert replay.edges == []


@pytest.mark.target_model
@pytest.mark.scenario
@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("cycles", (5, 6, 9, 10))
def test_aug23_2318z_synthetic_cycle_warning_boundary(
    count: int, cycles: int,
) -> None:
    """Original five inputs, then explicitly synthetic OFF/ON cycles within20min."""
    origin = datetime(2026, 8, 23, 23, 18, 9, 318691, tzinfo=UTC)
    first_off = datetime(2026, 8, 23, 23, 18, 22, 409960, tzinfo=UTC)
    recovered = datetime(2026, 8, 23, 23, 19, 42, 568890, tzinfo=UTC)
    events = [SensorInput("binary_sensor.hall", state, datetime.fromisoformat(at))
              for state, at in (
                  ("on", "2026-08-23T23:18:09.318691+00:00"),
                  ("off", "2026-08-23T23:18:22.409960+00:00"),
                  ("on", "2026-08-23T23:18:23.996249+00:00"),
                  ("off", "2026-08-23T23:18:35.938992+00:00"),
                  ("on", "2026-08-23T23:19:42.568890+00:00"),
              )]
    # The last original ON begins cycle three. Complete it and later cycles.
    for index in range(cycles - 2):
        on_at = recovered + timedelta(seconds=30 * index)
        if index:
            events.append(SensorInput("binary_sensor.hall", "on", on_at))
        events.append(SensorInput(
            "binary_sensor.hall", "off", on_at + timedelta(seconds=13),
        ))
    last_off = events[-1].event_at
    sample_at = origin + timedelta(
        seconds=30 * (int((last_off - origin).total_seconds()) // 30 + 1),
    )
    with RuntimeScenario(origin) as scene:
        replay = scene.create(target_map(), count).watch_reliability()
        for event in events:
            replay.observe(event)
        replay.advance(sample_at)
        published = replay.reliability_attributes
        assert published is not None
        assert replay.reliability_writes[-1].at == sample_at
        assert published["active_count"] == (1 if cycles == 10 else 0)
        rows = cast(list[dict[str, object]], published["warnings"])
        if cycles < 10:
            assert rows == []
        else:
            assert len(rows) == 1
            assert rows[0]["node_id"] == "hall"
            assert rows[0]["kind"] == "flapping"
            assert rows[0]["active_reasons"] == ["sustained_flapping"]
            assert rows[0]["first_observed_at"] == last_off.isoformat()
            assert rows[0]["active"] is True
        assert all(write.value == 0 for write in replay.reliability_writes
                   if write.at < last_off)
        # Expiring the first completion leaves fewer than ten in20minutes.
        expires_at = first_off + timedelta(minutes=20)
        recovery_sample = origin + timedelta(
            seconds=30 * (int((expires_at - origin).total_seconds()) // 30 + 1),
        )
        replay.advance(recovery_sample)
        cleared = replay.reliability_attributes
        assert cleared is not None and cleared["active_count"] == 0
        if cycles == 10:
            history = cast(list[dict[str, object]], cleared["warnings"])
            assert len(history) == 1 and history[0]["active"] is False
            assert history[0]["cleared_at"] == expires_at.isoformat()
        else:
            assert cleared["warnings"] == []
        assert replay.normalized_inputs == events
        assert replay.edges == []
