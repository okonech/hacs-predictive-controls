"""User-reported issue: original user quote unavailable in retained evidence.
User expected: reconstructed from the frozen regression, a new closet ON at
12:16:24.972720Z and retention through the 12:16:56.291116Z sleep checkpoint.
Observed: retained Sept8 regression describes missed closet return after bathroom
presence; this public replay proves the control signal, not physical actuation.
Source: original source in /tmp/black-box-migration-baseline.json, SHA256
a6da007601d094950adac4a6bb282736ef579e9ec027703554dffa16a64e80ea.
Test scope: original material inputs, false-ON/retention oracles and opaque
continuation for counts 1/2. The 10:00 walk/clears, 11:00 checkpoint and twenty
long-stay age/count/restart extensions are SYNTHETIC, not captured live history.
2026-09-12 approved migration: real runtime timers and public active edges replace
support/token/reason prerequisites, without retiming inputs or relaxing new-ON.
2026-09-13 named Section16/REQ-GOV-005 amendment: the original replay actually
acquires at 12:13:34.142281Z. Require that input-phase ON and uninterrupted
retention through return/sleep, not a second ON while already active. Preserve
all 14 inputs and the original restore frontier. A separately SYNTHETIC no-return
inverse keeps only the 11-input prefix and requires timer OFF at 12:20:19Z.
The separate tests/test_legacy_incident_sept8_qualification.py retains all original
source/helpers: 20 correlated donor composites + 1 token-only + 2 profile-mutating
120-second cases collected there; the old primary is retained but not collected.
No private seed or manual prediction-learning operation belongs in these replays.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario

# Compatibility only: the unchanged persistence qualification imports this helper
# through this module. Neither public test below calls it or inspects model state.
from tests.test_legacy_incident_sept8_qualification import (
    _engine_with_settled_bathroom_support as _engine_with_settled_bathroom_support,
)


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["top", "closet"],
                    "initial_weight": 0.8,
                },
                "closet": {
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["entrance", "bathroom"],
                    "initial_weight": 0.8,
                },
                "bathroom": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.bathroom"},
                    "adjacent": ["closet"],
                    "initial_weight": 0.7,
                },
            }
        }
    )


def _synthetic_setup(replays: tuple[RuntimeReplay, ...]) -> list[SensorInput]:
    """Original 10:00 route and clears, mirrored in chronological input order."""
    route_at = _at("2026-09-08T10:00:00Z")
    inputs = []
    for state, start in (("on", 0), ("off", 10)):
        for offset, entity_id in enumerate(
            (
                "binary_sensor.top", "binary_sensor.entrance",
                "binary_sensor.closet", "binary_sensor.bathroom",
            ),
            start=start,
        ):
            # Historical SensorInput default was 1.0, not the map's lower weight.
            event = SensorInput(
                entity_id, state, route_at + timedelta(seconds=offset),
                reliability=1.0,
            )
            inputs.append(event)
            for replay in replays:
                replay.observe(event)
    for replay in replays:
        replay.advance(_at("2026-09-08T11:00:00Z"))
    return inputs


def _assert_inputs(replay: RuntimeReplay, expected: list[SensorInput]) -> None:
    """Check actual normalization/receipt, including duplicates and reliability."""
    assert replay.normalized_inputs == expected
    assert len(replay.deliveries) == len(expected)
    for delivery, event in zip(replay.deliveries, expected, strict=True):
        assert delivery.delivered and not delivery.is_count
        assert delivery.entity_id == event.entity_id
        assert delivery.raw_state == event.state
        assert delivery.callback_at == delivery.processing_at == event.event_at
        assert delivery.event_at == event.event_at
        assert delivery.normalized == delivery.retained_input == event
        assert event.reliability == 1.0


@pytest.mark.scenario
@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_08_1213z_stay_presence_authority_expires_before_closet_return(
    authoritative_count: int,
) -> None:
    closet_at = _at("2026-09-08T12:13:34.142281Z")
    bathroom_at = _at("2026-09-08T12:14:24.044050Z")
    closet_clear_at = _at("2026-09-08T12:14:52.365745Z")
    target_at = _at("2026-09-08T12:16:24.972720Z")
    restore_at = target_at - timedelta(microseconds=1)
    sleep_off_at = _at("2026-09-08T12:16:56.291116Z")
    assert target_at - bathroom_at == timedelta(seconds=120, microseconds=928670)

    with RuntimeScenario(_at("2026-09-08T10:00:00Z") - timedelta(seconds=1)) as scene:
        live = scene.create(_incident_map(), authoritative_count)
        restored = scene.create(_incident_map(), authoritative_count)
        branches = (live, restored)
        inputs = _synthetic_setup(branches)
        for event in (
            SensorInput("binary_sensor.closet", "on", closet_at),
            SensorInput("binary_sensor.bathroom", "on", bathroom_at),
            SensorInput("binary_sensor.closet", "off", closet_clear_at),
        ):
            inputs.append(event)
            for replay in branches:
                replay.observe(event)
        live.advance(restore_at)
        assert all(replay.view().active("closet") for replay in branches)
        # Same origin, raw-state prefix and publications; restore does not rephase
        # recurring callbacks. Payload stays opaque (not a full HA process restart).
        restored.restore(json.loads(json.dumps(live.checkpoint())))
        suffix_starts = tuple(len(replay.edges) for replay in branches)
        return_views = []
        for event in (
            SensorInput("binary_sensor.closet", "on", target_at),
            SensorInput(
                "binary_sensor.entrance", "on", _at("2026-09-08T12:16:30.116610Z")
            ),
            SensorInput(
                "binary_sensor.top", "on", _at("2026-09-08T12:16:31.748532Z")
            ),
        ):
            inputs.append(event)
            for replay in branches:
                view = replay.observe(event)
                if event.event_at == target_at:
                    return_views.append(view)
        live.advance(sleep_off_at)
        # Named approval changes only the edge oracle, never the original suffix.
        assert len(inputs) == 14
        for replay, returned in zip(branches, return_views, strict=True):
            _assert_inputs(replay, inputs)
            assert returned.active("closet")
            assert replay.view().active("closet")
            assert tuple(
                edge for edge in replay.input_edges_for("closet")
                if edge.at == closet_at
            ) == (ActiveEdge(closet_at, "closet", True),), replay.edges_for("closet")
            # No release/reacquisition, including no new edge at the return input.
            assert tuple(
                edge for edge in replay.edges_for("closet") if edge.at >= closet_at
            ) == (ActiveEdge(closet_at, "closet", True),)
        assert live.view() == restored.view()
        assert live.edges[suffix_starts[0]:] == restored.edges[suffix_starts[1]:]


@pytest.mark.scenario
@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_synthetic_no_return_releases_closet_with_opaque_restore(
    authoritative_count: int,
) -> None:
    """Section16/PATH004/005/STATE009 inverse, not additional captured history.

    Keep setup8 + prefix3 exactly; omit all return/entrance/top suffix inputs.
    The 10:00-minus-1s timer origin fixes the public OFF at 12:20:19Z, not the
    internal threshold crossing. Both branches retain the original timer phase.
    """
    closet_at = _at("2026-09-08T12:13:34.142281Z")
    restore_at = _at("2026-09-08T12:16:24.972720Z") - timedelta(microseconds=1)
    release_at = _at("2026-09-08T12:20:19Z")
    with RuntimeScenario(_at("2026-09-08T10:00:00Z") - timedelta(seconds=1)) as scene:
        live = scene.create(_incident_map(), authoritative_count)
        restored = scene.create(_incident_map(), authoritative_count)
        branches = (live, restored)
        inputs = _synthetic_setup(branches)
        for event in (
            SensorInput("binary_sensor.closet", "on", closet_at),
            SensorInput(
                "binary_sensor.bathroom", "on", _at("2026-09-08T12:14:24.044050Z")
            ),
            SensorInput(
                "binary_sensor.closet", "off", _at("2026-09-08T12:14:52.365745Z")
            ),
        ):
            inputs.append(event)
            for replay in branches:
                replay.observe(event)
        assert len(inputs) == 11
        live.advance(restore_at)
        restored.restore(json.loads(json.dumps(live.checkpoint())))
        suffix_starts = tuple(len(replay.edges) for replay in branches)
        assert all(replay.view().active("closet") for replay in branches)
        live.advance(release_at - timedelta(microseconds=1))
        assert all(replay.view().active("closet") for replay in branches)
        live.advance(release_at)
        assert all(not replay.view().active("closet") for replay in branches)
        live.advance(restore_at + timedelta(hours=2))
        for replay in branches:
            _assert_inputs(replay, inputs)
            assert not replay.view().active("closet")
            assert tuple(
                edge for edge in replay.input_edges_for("closet")
                if edge.at >= closet_at
            ) == (ActiveEdge(closet_at, "closet", True),)
            assert tuple(
                edge for edge in replay.edges_for("closet") if edge.at >= closet_at
            ) == (
                ActiveEdge(closet_at, "closet", True),
                ActiveEdge(release_at, "closet", False),
            )
            assert any(
                write.at == release_at and write.phase == "timer" and not write.active
                for write in replay.writes_for("closet")
            )
        assert live.view() == restored.view()
        assert live.edges[suffix_starts[0]:] == restored.edges[suffix_starts[1]:]


@pytest.mark.scenario
@pytest.mark.target_model
@pytest.mark.parametrize("source_age", (180, 300, 1800, 7200, 86400))
@pytest.mark.parametrize("authoritative_count", (1, 2))
@pytest.mark.parametrize("restored", (False, True), ids=("uninterrupted", "restored"))
def test_long_stay_adjacent_detection_publishes_new_on(
    source_age: int,
    authoritative_count: int,
    restored: bool,
) -> None:
    """Synthetic ordinary replacement: 5 original ages × 2 counts × 2 restarts."""
    source_at = _at("2026-09-08T12:00:00Z")
    target_at = source_at + timedelta(seconds=source_age)
    frontier = target_at - timedelta(microseconds=1)
    with RuntimeScenario(_at("2026-09-08T10:00:00Z") - timedelta(seconds=1)) as scene:
        live = scene.create(_incident_map(), authoritative_count)
        recovered = scene.create(_incident_map(), authoritative_count)
        branches = (live, recovered)
        inputs = _synthetic_setup(branches)
        source = SensorInput("binary_sensor.bathroom", "on", source_at)
        inputs.append(source)
        for replay in branches:
            replay.observe(source)
        live.advance(frontier)
        if restored:
            # Original optional T-1us round trip; preserve both scheduler phases.
            recovered.restore(live.checkpoint())
        before = tuple(replay.view() for replay in branches)
        starts = tuple(len(replay.edges) for replay in branches)
        target = SensorInput("binary_sensor.closet", "on", target_at)
        inputs.append(target)
        for replay in branches:
            replay.observe(target)
        # Original always-present post-target round trip and duplicate at T.
        recovered.restore(live.checkpoint())
        inputs.append(target)
        for replay in branches:
            replay.observe(target)
        for replay, previous, start in zip(branches, before, starts, strict=True):
            _assert_inputs(replay, inputs)
            assert not previous.active("closet"), replay.edges_for("closet")
            assert replay.view().active("closet")
            assert tuple(
                edge for edge in replay.input_edges_for("closet")
                if edge.at == target_at
            ) == (ActiveEdge(target_at, "closet", True),), replay.edges_for("closet")
            assert tuple(replay.edges[start:]) == (
                ActiveEdge(target_at, "closet", True),
            )
            assert tuple(
                edge for edge in replay.edges_for("closet") if edge.at >= source_at
            ) == (ActiveEdge(target_at, "closet", True),)
        assert live.view() == recovered.view()
        assert live.edges[starts[0]:] == recovered.edges[starts[1]:]
