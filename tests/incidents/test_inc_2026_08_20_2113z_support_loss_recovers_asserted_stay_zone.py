from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import SensorInput


def conflict_map(
    *,
    target_presence: bool = False,
    target_reliability: float = 1.0,
) -> PredictiveMap:
    target_signal = "mmwave" if target_presence else "motion"
    nodes: dict[str, object] = {
        "target_source": {
            "zone": "target_source",
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.target_source"},
            "adjacent": ["target"],
        },
        "target": {
            "zone": "target",
            "entities": {target_signal: "binary_sensor.target"},
            "adjacent": ["target_source"],
            "initial_weight": target_reliability,
        },
    }
    for prefix in ("a", "d"):
        first, middle, stay = prefix, f"{prefix}m", f"{prefix}s"
        nodes[first] = {
            "zone": first,
            "entities": {"motion": f"binary_sensor.{first}"},
            "adjacent": [middle],
        }
        nodes[middle] = {
            "zone": middle,
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": f"binary_sensor.{middle}"},
            "adjacent": [first, stay],
        }
        nodes[stay] = {
            "zone": stay,
            "entities": {"motion": f"binary_sensor.{stay}"},
            "adjacent": [middle],
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


@pytest.mark.target_model
def test_inc_2026_08_20_2113z_support_loss_recovers_asserted_stay_zone() -> None:
    target_on_at = datetime(2026, 8, 20, 21, 13, 22, 395673, tzinfo=UTC)
    conflict_started_at = datetime(2026, 8, 20, 21, 13, 27, 131114, tzinfo=UTC)
    degraded_at = datetime(2026, 8, 20, 21, 15, 27, 764256, tzinfo=UTC)
    support_lost_at = datetime(2026, 8, 20, 21, 17, 7, 784372, tzinfo=UTC)
    observed_release_at = datetime(2026, 8, 20, 21, 23, 2, 849850, tzinfo=UTC)
    setup_at = target_on_at - timedelta(minutes=1)
    engine = ZoneModelEngine(
        conflict_map(target_presence=True),
        2,
        setup_at,
    )
    for node_id, event_at in (
        ("a", setup_at),
        ("am", setup_at + timedelta(seconds=1)),
        ("as", setup_at + timedelta(seconds=2)),
        ("d", setup_at + timedelta(seconds=3)),
        ("dm", setup_at + timedelta(seconds=4)),
        ("ds", setup_at + timedelta(seconds=5)),
        ("target_source", datetime(2026, 8, 20, 21, 13, 16, 5579, tzinfo=UTC)),
        ("target", target_on_at),
    ):
        engine.observe(SensorInput(f"binary_sensor.{node_id}", "on", event_at))

    acquired = engine.snapshot
    engine.advance(conflict_started_at)
    conflict = engine.snapshot.count_conflicts[0]
    assert conflict.started_at == conflict_started_at
    assert conflict.deadline == conflict_started_at + timedelta(minutes=2)
    degraded = engine.advance(degraded_at)
    engine.observe(
        SensorInput(
            "binary_sensor.ds",
            "unavailable",
            support_lost_at,
        )
    )

    assert len(engine.snapshot.anonymous_supports) == 1
    assert engine.snapshot.count_conflicts == ()
    recovery_row = next(
        row
        for row in engine.audit_rows
        if row.zone == "target" and row.reason == "stuck_conflict_cleared"
    )
    assert recovery_row.event_at == support_lost_at
    assert recovery_row.count_conflict_support_ids == conflict.support_ids
    assert recovery_row.reliability_result == "recovered"
    retained = engine.advance(observed_release_at)
    target = next(
        state for state in retained.snapshot.episode_states if state.node_id == "target"
    )
    target_policy = next(
        state for state in retained.snapshot.policy_states if state.zone == "target"
    )

    assert target.known_on
    assert not target.health_warning
    assert next(
        state for state in acquired.policy_states if state.zone == "target"
    ).active
    assert target_policy.active
    assert not any(
        event.zone == "target" and event.kind == "released"
        for result in (degraded, retained)
        for event in result.policy_events
    )
