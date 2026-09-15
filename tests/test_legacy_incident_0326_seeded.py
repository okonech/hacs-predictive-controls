# Legacy qualification, not public incident acceptance (REQ-GOV-005, 2026-09-12).
# Source: tests/incidents/
# test_inc_2026_09_11_0326z_living_room_missed_after_expired_passage.py
# Scalar/token qualification now uses authentic components, not selected authority.
# See docs/spec/completion-legacy-mapping.md, L0326. Public replay is unchanged.

"""Fourth lighting report: retain the living-room missed arrival independently.

Approved Homelab captures: tmp/inc-2026-09-11-living-room-{status,history,
route-history,context,traces,trace,diagnostics}.json. The replay is self-contained;
it reads neither captures nor a live/sibling map. Count 2 is observed, 1 synthetic.
0326 is the first material cadence event, not a claimed occupant arrival time.

Generic names preserve entrance--dining--living-right, kitchen--entrance/dining,
foyer--dining, and guest--living-left. Four radar aliases are ONE physical lounge
node. The left radar stayed off. Map weights, profiles and the absence of directed
entry->passage->lounge timing are factual; empty startup is fixture-only.

03:42:19.506697 entrance acquires via kitchen-backed settled adjacent transfer.
03:42:32.109092 right radar is a trustworthy fresh correlated positive, but
untracked_rejected; observed q .14559229504345259 -> .16793252687103588 and both
living-room public active outputs remain off. The dining transition has been on
since03:39:48.881643: original45s token and60s health horizon expired. The fresh
entrance token is12.602395s old, but two edges away and provisional.

Manual recovery light-on03:43:37.707485 is unattributed in retained logbook,
consistent with the report, NOT a captured physical event pulse. Alex sleep off
and Shaila sleep on make the consumer's NOT(both asleep) guard permissive.
No active-on trace occurred at detection. Never feed the light state as evidence.
Expected acquisition requires a newly reviewed bounded contract; it must not
come from invented alias independence, expired passage authority or a timer.
"""

import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.gap_lifecycle_fixture import component_gap
from tests.persistence_component_fixture import PersistenceComponents


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-11T{time}+00:00")


def _map() -> PredictiveMap:
    adjacency = {
        "entry": ["passage", "stay"],
        "passage": ["entry", "stay", "foyer", "lounge"],
        "stay": ["entry", "passage"],
        "foyer": ["passage", "bottom"],
        "bottom": ["foyer", "guest"],
        "guest": ["bottom", "other_side"],
        "other_side": ["guest", "lounge"],
        "lounge": ["passage", "other_side"],
    }
    weights = {
        "entry": 0.75, "passage": 0.75, "stay": 0.8, "foyer": 0.85,
        "bottom": 0.85, "guest": 0.75, "other_side": 0.9, "lounge": 0.9,
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": (
                    "anchor_sensor" if node in {"lounge", "other_side"}
                    else "room_occupancy" if node in {"stay", "guest"}
                    else "transition_gate"
                ),
                "occupancy_behavior": (
                    "sticky" if node in {"lounge", "other_side"}
                    else "sustained" if node in {"stay", "guest"}
                    else "transient"
                ),
                "entities": (
                    {signal: f"binary_sensor.{node}_{alias}" for signal, alias in (
                        ("target", "target"), ("still_target", "still"),
                        ("moving_target", "moving"), ("zone_3_occupancy", "zone"),
                    )}
                    if node in {"lounge", "other_side"} else
                    {"motion" if node == "foyer" else "mmwave": f"binary_sensor.{node}"}
                ),
                "adjacent": neighbors,
                "initial_weight": weights[node],
                "transition_seconds": (
                    {"stay": 15, "foyer": 15} if node == "passage"
                    else {"passage": 15} if node in {"stay", "foyer"} else {}
                ),
            }
            for node, neighbors in adjacency.items()
        },
    })


EVENTS = (
    ("03:26:20.716997", "lounge_target", "on"),
    ("03:26:20.720525", "lounge_still", "on"),
    ("03:26:25.962230", "lounge_target", "off"),
    ("03:26:25.965546", "lounge_still", "off"),
    ("03:28:15.829137", "passage", "on"),
    ("03:28:25.704027", "passage", "off"),
    ("03:35:04.512882", "lounge_target", "on"),
    ("03:35:04.516210", "lounge_moving", "on"),
    ("03:35:05.513281", "lounge_moving", "off"),
    ("03:35:05.516724", "lounge_still", "on"),
    ("03:35:09.806851", "lounge_target", "off"),
    ("03:35:09.810259", "lounge_still", "off"),
    ("03:38:13.211815", "lounge_target", "on"),
    ("03:38:13.215339", "lounge_still", "on"),
    ("03:38:18.606532", "lounge_target", "off"),
    ("03:38:18.609795", "lounge_still", "off"),
    ("03:38:57.969102", "entry", "on"),
    ("03:39:03.659340", "guest", "on"),
    ("03:39:04.386957", "passage", "on"),
    ("03:39:05.070280", "stay", "on"),
    ("03:39:07.197953", "foyer", "on"),
    ("03:39:18.534318", "guest", "off"),
    ("03:39:18.955694", "foyer", "off"),
    ("03:39:28.474103", "foyer", "on"),
    ("03:39:39.994369", "foyer", "off"),
    ("03:39:43.224736", "passage", "off"),
    ("03:39:48.881643", "passage", "on"),
    ("03:40:11.172398", "foyer", "on"),
    ("03:40:22.047760", "entry", "off"),
    ("03:40:25.069714", "foyer", "off"),
    ("03:42:19.506697", "entry", "on"),
)


@pytest.mark.target_model
@pytest.mark.parametrize("count", (2, 1))
def test_legacy_incident_0326_seeded(
    count: int,
) -> None:
    predictive_map = _map()
    entities = {
        entity: node
        for node in predictive_map.nodes.values() for entity in node.entities.values()
    }
    engine = PersistenceComponents(predictive_map, count, _at("03:26:00"))
    engine.bootstrap_sensor_snapshot(tuple(
        SensorInput(entity, "off", _at("03:26:00"), node.reliability)
        for entity, node in entities.items()
    ), _at("03:26:00"))
    for time, alias, state in EVENTS:
        entity = f"binary_sensor.{alias}"
        engine.observe(SensorInput(
            entity, state, _at(time), entities[entity].reliability,
        ))

    target_at = _at("03:42:32.109092")
    recovery_at = _at("03:43:37.707485")
    engine.advance(target_at)
    # This scalar is the captured pre-target marginal, not an invented historical
    # episode/support snapshot. Keep real replay-generated provenance intact.
    before = 0.14559229504345259
    target_filter = engine.filters["lounge"]
    target_filter._state = replace(
        target_filter.state, log_odds=math.log(before / (1 - before)),
    )
    assert not next(
        p for p in engine.snapshot.policy_states if p.zone == "lounge"
    ).active
    entry_token, = (t for t in engine.snapshot.traversal_tokens if t.node_id == "entry")
    assert entry_token.accepted_at == _at("03:42:19.506697")
    assert target_at - entry_token.accepted_at == timedelta(
        seconds=12, microseconds=602395,
    )
    assert entry_token.valid_until == _at("03:43:04.506697")
    assert all(t.node_id != "passage" for t in engine.snapshot.traversal_tokens)
    passage = next(s for s in engine.snapshot.episode_states if s.node_id == "passage")
    assert passage.known_on and passage.health_warning

    # TRAV021's historical target-only component rule. Current PATH006 does not
    # inherit this rule; the unchanged public incident has real observed passage.
    arrival = component_gap(engine, SensorInput(
        "binary_sensor.lounge_target", "on", target_at, 0.9,
    ))
    policy = next(p for p in arrival.snapshot.policy_states if p.zone == "lounge")
    assert policy.active, (
        "Living room must acquire at detected entry, "
        "not 65.598393s later at manual recovery",
        arrival.authorizations,
        next(
            b.probability for b in arrival.snapshot.belief_states if b.zone == "lounge"
        ),
    )
    assert [
        (p.kind, p.event_at) for p in arrival.policy_events if p.zone == "lounge"
    ] == [("acquired", target_at)]
    assert next(
        s for s in arrival.snapshot.episode_states if s.node_id == "lounge"
    ).cadence_correlated
    assert recovery_at - target_at == timedelta(seconds=65, microseconds=598393)

    # The first same-device aliases after detection must not supply a second edge.
    for time, alias in (("03:42:32.112873", "moving"), ("03:42:32.116631", "still")):
        repeated = engine.observe(SensorInput(
            f"binary_sensor.lounge_{alias}", "on", _at(time), 0.9,
        ))
        assert not any(p.zone == "lounge" for p in repeated.policy_events)
    before_recovery = engine.advance(recovery_at - timedelta(microseconds=1))
    assert next(
        p for p in before_recovery.snapshot.policy_states if p.zone == "lounge"
    ).active


@pytest.mark.target_model
@pytest.mark.parametrize("offset_us", (29_999_999, 30_000_000, 44_999_999, 45_000_000))
def test_legacy_0326_gap_budget_and_original_expiry(offset_us: int) -> None:
    """TRAV021/STATE009 synthetic boundary; no retimed incident claim."""
    predictive_map = _map()
    components = PersistenceComponents(predictive_map, 2, _at("03:26:00"))
    entities = {
        entity: node
        for node in predictive_map.nodes.values() for entity in node.entities.values()
    }
    components.bootstrap_sensor_snapshot(tuple(
        SensorInput(entity, "off", _at("03:26:00"), node.reliability)
        for entity, node in entities.items()
    ), _at("03:26:00"))
    for time, alias, state in EVENTS:
        entity = f"binary_sensor.{alias}"
        components.observe(SensorInput(
            entity, state, _at(time), entities[entity].reliability,
        ))
    original, = (t for t in components.frontier.tokens if t.node_id == "entry")
    assert original.valid_until == _at("03:43:04.506697")
    event_at = original.accepted_at + timedelta(microseconds=offset_us)
    result = component_gap(
        components, SensorInput("binary_sensor.lounge_target", "on", event_at, 0.9),
    )
    authorization, = result.authorizations
    assert authorization.authorized is (offset_us < 30_000_000)
    assert any(t == original for t in result.snapshot.traversal_tokens) is (
        offset_us < 45_000_000
    )
    assert not any(t.node_id == "lounge" for t in result.snapshot.traversal_tokens)
    assert not components.learning
    assert not components.prediction_manager.leases
