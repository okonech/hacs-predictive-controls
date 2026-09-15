"""User-reported issue: original message unavailable; evidence reconstruction.
User expected: inferred from the retained regression, an asserted stay stays ON.
Observed: retained Aug20 fixture records a false-release frontier at 21:23:02.849850Z
after outside support loss at 21:17:07.784372Z; no physical actuation is replayed.
Source: original source in /tmp/black-box-migration-baseline.json (Aug20 2113Z).
Test scope: public target ON/no OFF through the original deadline. Generic map and
the six one-second outside-path inputs are synthetic setup, not captured history.
Original origin/count/map and every input remain; omitted SensorInput reliability
means 1.0. Old support/conflict/recovery-reason assertions are retired, not guarded.
No warning assertion substitutes for their unavailable public recovery semantics.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, InputDelivery, RuntimeScenario


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
@pytest.mark.scenario
def test_inc_2026_08_20_2113z_support_loss_recovers_asserted_stay_zone() -> None:
    target_on_at = datetime(2026, 8, 20, 21, 13, 22, 395673, tzinfo=UTC)
    conflict_started_at = datetime(2026, 8, 20, 21, 13, 27, 131114, tzinfo=UTC)
    degraded_at = datetime(2026, 8, 20, 21, 15, 27, 764256, tzinfo=UTC)
    support_lost_at = datetime(2026, 8, 20, 21, 17, 7, 784372, tzinfo=UTC)
    observed_release_at = datetime(2026, 8, 20, 21, 23, 2, 849850, tzinfo=UTC)
    setup_at = target_on_at - timedelta(minutes=1)
    with RuntimeScenario(setup_at) as scenario:
        replay = scenario.create(conflict_map(target_presence=True), 2)
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
            replay.observe(SensorInput(f"binary_sensor.{node_id}", "on", event_at))
        acquired = replay.view()
        conflict = replay.advance(conflict_started_at)
        degraded = replay.advance(degraded_at)
        recovered = replay.observe(
            SensorInput("binary_sensor.ds", "unavailable", support_lost_at)
        )
        retained = replay.advance(observed_release_at)

        # Independent literal expansion of the frozen input sequence, including
        # callback/receipt/occurrence identity and effective reliability 1.0.
        expected_inputs = tuple(SensorInput(
            entity, state, datetime.fromisoformat(at), reliability=1.0,
        ) for entity, state, at in (
            ("binary_sensor.a", "on", "2026-08-20T21:12:22.395673+00:00"),
            ("binary_sensor.am", "on", "2026-08-20T21:12:23.395673+00:00"),
            ("binary_sensor.as", "on", "2026-08-20T21:12:24.395673+00:00"),
            ("binary_sensor.d", "on", "2026-08-20T21:12:25.395673+00:00"),
            ("binary_sensor.dm", "on", "2026-08-20T21:12:26.395673+00:00"),
            ("binary_sensor.ds", "on", "2026-08-20T21:12:27.395673+00:00"),
            ("binary_sensor.target_source", "on", "2026-08-20T21:13:16.005579+00:00"),
            ("binary_sensor.target", "on", "2026-08-20T21:13:22.395673+00:00"),
            ("binary_sensor.ds", "unavailable", "2026-08-20T21:17:07.784372+00:00"),
        ))
        assert replay.deliveries == tuple(InputDelivery(
            event.entity_id, event.state, event.event_at, event.event_at,
            event.event_at, event, event, False, True,
        ) for event in expected_inputs)
        assert all(view.active("target") for view in (
            acquired, conflict, degraded, recovered, retained,
        )), replay.edges_for("target")
        assert replay.edges_for("target") == (ActiveEdge(target_on_at, "target", True),)
        assert replay.input_edges_for("target") == replay.edges_for("target")
