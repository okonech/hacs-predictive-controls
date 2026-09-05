from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.filter import (
    probability_to_log_odds,
)
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
def test_inc_2026_08_23_0556z_asserted_stay_never_releases_for_count_conflict() -> None:
    target_on_at = datetime(2026, 8, 23, 5, 56, 40, 122876, tzinfo=UTC)
    conflict_started_at = datetime(2026, 8, 23, 5, 56, 43, 75447, tzinfo=UTC)
    conflict_deadline = datetime(2026, 8, 23, 5, 58, 43, 75447, tzinfo=UTC)
    release_pending_at = datetime(2026, 8, 23, 6, 4, 11, 52856, tzinfo=UTC)
    observed_release_at = datetime(2026, 8, 23, 6, 6, 13, 173267, tzinfo=UTC)
    setup_at = target_on_at - timedelta(minutes=1)
    predictive_map = conflict_map(
        target_presence=True,
        target_reliability=0.7,
    )
    engine = ZoneModelEngine(
        predictive_map,
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
    ):
        engine.observe(SensorInput(f"binary_sensor.{node_id}", "on", event_at))
    engine.observe(
        SensorInput(
            "binary_sensor.target_source",
            "on",
            target_on_at - timedelta(seconds=1),
        )
    )
    engine.observe(SensorInput("binary_sensor.target", "on", target_on_at))
    acquired_snapshot = engine.snapshot
    engine = ZoneModelEngine.restore(
        predictive_map,
        replace(
            acquired_snapshot,
            belief_states=tuple(
                replace(
                    state,
                    log_odds=probability_to_log_odds(0.7793789008408025),
                )
                if state.zone == "target"
                else state
                for state in acquired_snapshot.belief_states
            ),
        ),
        (),
        target_on_at,
    )

    acquired = next(
        state for state in engine.snapshot.policy_states if state.zone == "target"
    )
    acquired_belief = next(
        state for state in engine.snapshot.belief_states if state.zone == "target"
    )
    assert acquired_belief.probability == pytest.approx(
        0.7793789008408025,
        abs=0.02,
    )
    assert acquired.active
    engine.advance(conflict_started_at)
    conflict = engine.snapshot.count_conflicts[0]
    assert conflict.started_at == conflict_started_at
    assert conflict.deadline == conflict_deadline
    evaluations = [
        engine.advance(conflict_deadline),
        engine.advance(release_pending_at),
    ]
    degraded_belief = next(
        state
        for state in evaluations[0].snapshot.belief_states
        if state.zone == "target"
    )
    assert degraded_belief.probability == pytest.approx(
        0.7959950372145533,
        abs=0.02,
    )
    retained = engine.advance(observed_release_at)
    evaluations.append(retained)
    target = next(
        state for state in retained.snapshot.episode_states if state.node_id == "target"
    )
    target_policy = next(
        state for state in retained.snapshot.policy_states if state.zone == "target"
    )
    target_belief = next(
        state for state in retained.snapshot.belief_states if state.zone == "target"
    )

    assert target_belief.probability == pytest.approx(
        0.21639972587294073,
        abs=0.02,
    )
    assert target_policy.active
    assert not any(
        event.zone == "target" and event.kind == "released"
        for result in evaluations
        for event in result.policy_events
    )
    assert target.known_on
    assert target.status == "degraded"
    assert target.health_warning
    assert target.degradation_reason == "count_conflict"
    assert target.traversal_valid_until is None
