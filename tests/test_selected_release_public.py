"""POLICY014/PATH005 public runtime controls; synthetic, not captured incidents.

The 2026-09-13 approved release migration keeps the original ordering map and
source0/button200/pair800/middle804/tip806/sourceOFF810 inputs at reliability1.0.
Real runtime timers and ZoneActiveSensor writes qualify timer OFF1170 separately
from the engine's exact1166.484750 deadline and ignored-input-only red proof.
Peer, count-zero and reacquisition suffixes below are explicitly synthetic inverses.
Opaque restore proves inference continuation, not a Home Assistant process restart;
restore itself need not publish, so restored public checks use actual later writes.
"""

from __future__ import annotations

import json

import pytest

from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.runtime_replay import ActiveEdge, RuntimeReplay, RuntimeScenario
from tests.test_zone_model_endpoint_retention_ordering import (
    _at,
    _belief,
    _map,
    _policy,
)

pytestmark = pytest.mark.target_model


def _inputs(*, peer: bool = False) -> tuple[SensorInput, ...]:
    source = (SensorInput("binary_sensor.source", "on", _at(0)),)
    extra = (SensorInput("binary_sensor.peer", "on", _at(1)),) if peer else ()
    return source + extra + tuple(
        SensorInput(entity, state, _at(seconds))
        for entity, state, seconds in (
            ("event.button", "pressed", 200),
            ("binary_sensor.pair", "on", 800),
            ("binary_sensor.middle", "on", 804),
            ("binary_sensor.tip", "on", 806),
            ("binary_sensor.source", "off", 810),
        )
    )


def _drive(replay: RuntimeReplay, *, peer: bool = False) -> None:
    events = _inputs(peer=peer)
    for event in events:
        replay.observe(event)
    assert tuple(replay.normalized_inputs) == events
    assert replay.edges_for("room") == (
        ActiveEdge(_at(1 if peer else 200), "room", True),
    )


def _room_release_edges(replay: RuntimeReplay) -> tuple[ActiveEdge, ...]:
    return tuple(edge for edge in replay.edges_for("room") if not edge.active)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("trigger", ("timer", "duplicate_off", "invalid_count"))
def test_public_release_uses_real_five_second_timers(
    count: int, trigger: str,
) -> None:
    with RuntimeScenario(_at(0)) as scenario:
        replay = scenario.create(_map(), count)
        _drive(replay)
        for seconds in range(815, 1166, 5):
            if trigger == "duplicate_off":
                replay.send("binary_sensor.source", "off", _at(seconds))
            elif trigger == "invalid_count":
                replay.send("sensor.replay_people", "invalid", _at(seconds))
            else:
                replay.advance(_at(seconds))
            assert replay.view().active("room")
        replay.advance(_at(1169.999999))
        assert replay.view().active("room") and not _room_release_edges(replay)
        replay.advance(_at(1170))
        assert not replay.view().active("room")
        replay.advance(_at(1200))
        assert replay.edges_for("room") == (
            ActiveEdge(_at(200), "room", True),
            ActiveEdge(_at(1170), "room", False),
        )
        # Inactive/pending startup publications are not release edges. Qualify
        # every OFF write after the actual acquisition, with its real timestamp.
        released = tuple(
            w for w in replay.writes_for("room")
            if not w.active and w.at >= _at(200)
        )
        assert tuple((w.at, w.phase) for w in released) == (
            (_at(1170), "timer"), (_at(1200), "timer"),
        )
        # The later explanation update is still OFF, not another release edge.
        assert tuple(w.attributes["reason"] for w in released) == (
            "released", "inactive_below_on",
        )
        # These are actual registered callbacks, not direct engine.advance calls.
        assert tuple(
            at for at, callback in scenario.clock.executions
            if callback == "_async_expire_transient_state"
        ) == tuple(_at(seconds) for seconds in range(5, 1201, 5))
        assert replay.inference_snapshot().count_state.expected_count == count


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("restore_at", (1045, 1050))
def test_public_release_restore_straddles_crossing(
    count: int, restore_at: int,
) -> None:
    with RuntimeScenario(_at(0)) as scenario:
        live = scenario.create(_map(), count)
        _drive(live)
        live.advance(_at(restore_at))
        payload = live.checkpoint()
        restored = scenario.create(_map(), count)
        restored.restore(json.loads(json.dumps(payload, allow_nan=False)))
        assert restored.checkpoint() == payload
        pending = _policy(restored.inference_snapshot()).pending_release_since
        assert pending == (None if restore_at == 1045 else _at(1046.484750))
        # Restore is silent; wait for normal registered publication, not a forced
        # read/write or an assertion that inference restore is an HA restart.
        live.advance(_at(1165))
        assert live.view().active("room") and restored.view().active("room")
        assert not _room_release_edges(live) and not _room_release_edges(restored)
        live.advance(_at(1200))
        for replay in (live, restored):
            assert not replay.view().active("room")
            assert _room_release_edges(replay) == (
                ActiveEdge(_at(1170), "room", False),
            )
            assert tuple(w.phase for w in replay.writes_for("room")
                         if w.at == _at(1170)) == ("timer",)
        assert live.inference_snapshot() == restored.inference_snapshot()


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("withdrawal", ("held", "unknown", "stable_clear", "zero"))
def test_public_peer_protection_and_zero_override(
    count: int, withdrawal: str,
) -> None:
    with RuntimeScenario(_at(0)) as scenario:
        replay = scenario.create(_map(), count)
        _drive(replay, peer=True)
        replay.advance(_at(1200))
        assert replay.edges_for("room") == (ActiveEdge(_at(1), "room", True),)
        assert _belief(replay.inference_snapshot()).physical_hold
        assert _policy(replay.inference_snapshot()).pending_release_since is None
        if withdrawal == "zero":
            replay.send("sensor.replay_people", "0", _at(1201))
            assert not replay.view().active("room")
            assert _room_release_edges(replay) == (
                ActiveEdge(_at(1201), "room", False),
            )
            assert replay.writes_for("room")[-1].phase == "input"
        elif withdrawal == "unknown":
            replay.send("binary_sensor.peer", "unknown", _at(1500))
            assert not _belief(replay.inference_snapshot()).physical_hold
        elif withdrawal == "stable_clear":
            # Additional synthetic alias baseline while peer is still ON makes
            # this a genuine all-alias stable clear, unlike the original86 cases.
            replay.send("binary_sensor.peer_alias", "off", _at(1499))
            replay.send("binary_sensor.peer", "off", _at(1500))
            replay.advance(_at(1509.999999))
            assert _belief(replay.inference_snapshot()).physical_hold
            assert replay.view().active("room")
            replay.advance(_at(1510))
            assert not _belief(replay.inference_snapshot()).physical_hold
            assert replay.view().active("room")
        if withdrawal in {"unknown", "stable_clear"}:
            ended = 1500 if withdrawal == "unknown" else 1510
            replay.advance(_at(ended + 120))
            assert replay.view().active("room")  # No protected time in dwell.
            assert not _room_release_edges(replay)
        replay.advance(_at(2100))
        if withdrawal == "held":
            assert replay.view().active("room") and not _room_release_edges(replay)
        else:
            assert not replay.view().active("room")
            edges = _room_release_edges(replay)
            assert len(edges) == 1
            if withdrawal != "zero":
                assert edges[0].at > _at(ended + 120)


@pytest.mark.parametrize("count", (1, 2))
def test_public_reacquisition_cancels_pending_release(count: int) -> None:
    with RuntimeScenario(_at(0)) as scenario:
        replay = scenario.create(_map(), count)
        _drive(replay)
        replay.advance(_at(1100))
        assert replay.view().active("room")
        assert _policy(replay.inference_snapshot()).pending_release_since == (
            _at(1046.484750)
        )
        # Genuine fresh input, not a duplicate or a fabricated inference reset.
        replay.observe(SensorInput("binary_sensor.source", "on", _at(1101)))
        assert replay.view().active("room")
        renewed = replay.inference_snapshot()
        assert _policy(renewed).pending_release_since is None
        assert _belief(renewed).path_displaced_at is None
        assert _belief(renewed).physical_hold
        replay.advance(_at(2100))
        assert replay.edges_for("room") == (ActiveEdge(_at(200), "room", True),)
        assert replay.view().active("room")
        assert tuple(replay.normalized_inputs) == _inputs() + (
            SensorInput("binary_sensor.source", "on", _at(1101)),
        )
