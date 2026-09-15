"""User-reported issue: original message unavailable; retained-test reconstruction.
User expected: inferred from the regression, an asserted target must stay ON.
Observed: the retained Aug23 fixture records false release at 06:06:13.173267Z
during count conflict, not a complete captured production or actuation history.
Source: /tmp/black-box-migration-baseline.json, Aug23 0556Z original source.
Test scope: same generic map, synthetic six-input outside paths, origin/count and
actual sensor sequence. All effective input reliabilities stay 1.0 despite map 0.7.
Original scalar q=0.7793789008408025, deadline q=0.7959950372145533 and release
q=0.21639972587294073 (old tolerance 0.02) are provenance, never injected here.
Without historical latent state this is not exact posterior-equivalent replay.
The intact seeded boundary moved to tests/test_legacy_incident_aug23_seeded.py.
2026-09-12 user-approved health amendment: extend only the diagnostic observation
horizon to 610 seconds ON. The supported target must not warn; a separately labeled
synthetic unsupported target must warn at 600 seconds, sampled by 610 seconds.
The original retention timeline and separately retained seeded qualification stay.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import (
    ActiveEdge,
    InputDelivery,
    PublishedState,
    RuntimeReplay,
    RuntimeScenario,
)


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


def _replay_observations(
    *, observe_health_deadline: bool = False,
) -> tuple[RuntimeReplay, tuple[PublishedState, ...]]:
    """Replay only the frozen inputs; return captured publications after cleanup."""
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
    with RuntimeScenario(setup_at) as scenario:
        replay = scenario.create(predictive_map, 2).watch_reliability()
        for node_id, event_at in (
            ("a", setup_at),
            ("am", setup_at + timedelta(seconds=1)),
            ("as", setup_at + timedelta(seconds=2)),
            ("d", setup_at + timedelta(seconds=3)),
            ("dm", setup_at + timedelta(seconds=4)),
            ("ds", setup_at + timedelta(seconds=5)),
        ):
            replay.observe(SensorInput(f"binary_sensor.{node_id}", "on", event_at))
        replay.observe(SensorInput(
            "binary_sensor.target_source", "on", target_on_at - timedelta(seconds=1),
        ))
        acquired = replay.observe(SensorInput(
            "binary_sensor.target", "on", target_on_at,
        ))
        checkpoints = (
            acquired,
            replay.advance(conflict_started_at),
            replay.advance(conflict_deadline),
            replay.advance(release_pending_at),
            replay.advance(observed_release_at),
        )
        if observe_health_deadline:
            replay.advance(target_on_at + timedelta(seconds=610))
        expected_inputs = tuple(SensorInput(
            entity, "on", datetime.fromisoformat(at), reliability=1.0,
        ) for entity, at in (
            ("binary_sensor.a", "2026-08-23T05:55:40.122876+00:00"),
            ("binary_sensor.am", "2026-08-23T05:55:41.122876+00:00"),
            ("binary_sensor.as", "2026-08-23T05:55:42.122876+00:00"),
            ("binary_sensor.d", "2026-08-23T05:55:43.122876+00:00"),
            ("binary_sensor.dm", "2026-08-23T05:55:44.122876+00:00"),
            ("binary_sensor.ds", "2026-08-23T05:55:45.122876+00:00"),
            ("binary_sensor.target_source", "2026-08-23T05:56:39.122876+00:00"),
            ("binary_sensor.target", "2026-08-23T05:56:40.122876+00:00"),
        ))
        assert replay.deliveries == tuple(InputDelivery(
            event.entity_id, event.state, event.event_at, event.event_at,
            event.event_at, event, event, False, True,
        ) for event in expected_inputs)
    return replay, checkpoints


@pytest.mark.target_model
@pytest.mark.scenario
def test_inc_2026_08_23_0556z_asserted_stay_never_releases_for_count_conflict() -> None:
    replay, checkpoints = _replay_observations()
    assert all(view.active("target") for view in checkpoints), (
        replay.edges_for("target")
    )
    assert replay.edges_for("target") == (
        ActiveEdge(
            datetime(2026, 8, 23, 5, 56, 40, 122876, tzinfo=UTC), "target", True,
        ),
    )
    assert replay.input_edges_for("target") == replay.edges_for("target")


@pytest.mark.target_model
@pytest.mark.scenario
def test_aug23_0556z_supported_target_does_not_warn_after_610_seconds() -> None:
    """Original path-supported target is the no-warning control, not a stuck node."""
    replay, _ = _replay_observations(observe_health_deadline=True)
    published = replay.reliability_attributes
    assert published is not None
    assert replay.view().at == datetime(2026, 8, 23, 6, 6, 50, 122876, tzinfo=UTC)
    assert replay.reliability_writes[-1].at == datetime(
        2026, 8, 23, 6, 6, 40, 122876, tzinfo=UTC,
    )
    warnings = cast(list[dict[str, object]], published["warnings"])
    assert not any(row["node_id"] == "target" for row in warnings), published
    assert replay.view().active("target")
    assert tuple(edge.active for edge in replay.edges_for("target")) == (True,)


@pytest.mark.target_model
@pytest.mark.scenario
@pytest.mark.parametrize("count", (1, 2))
def test_aug23_0556z_synthetic_unsupported_presence_warns_by_610_seconds(
    count: int,
) -> None:
    """Synthetic inverse: same map/origin/target ON, no invented supporting walk."""
    on_at = datetime(2026, 8, 23, 5, 56, 40, 122876, tzinfo=UTC)
    with RuntimeScenario(on_at - timedelta(minutes=1)) as scene:
        replay = scene.create(
            conflict_map(target_presence=True, target_reliability=0.7), count,
        ).watch_reliability()
        event = SensorInput("binary_sensor.target", "on", on_at)
        replay.observe(event)
        replay.advance(on_at + timedelta(seconds=599))
        before = replay.reliability_attributes
        assert before is not None and before["active_count"] == 0
        assert before["warnings"] == []
        replay.advance(on_at + timedelta(seconds=600))
        qualified = replay.reliability_attributes
        assert qualified is not None and qualified["active_count"] == 1
        rows = cast(list[dict[str, object]], qualified["warnings"])
        assert len(rows) == 1
        assert rows[0]["node_id"] == "target"
        assert rows[0]["kind"] == "suspected_stuck"
        assert rows[0]["active_reasons"] == ["assertion_timeout"]
        assert rows[0]["first_observed_at"] == (
            on_at + timedelta(seconds=600)
        ).isoformat()
        assert rows[0]["active"] is True
        replay.advance(on_at + timedelta(seconds=610))
        assert replay.reliability_attributes == qualified
        assert replay.reliability_writes[-1].at == on_at + timedelta(seconds=600)
        assert replay.normalized_inputs == [event]
        assert not replay.view().active("target")
        assert replay.edges == []  # A diagnostic warning cannot activate a light.
