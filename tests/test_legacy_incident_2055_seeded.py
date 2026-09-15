# Legacy qualification, not public incident acceptance (REQ-GOV-005, 2026-09-12).
# Source: tests/incidents/
# test_inc_2026_09_10_2055z_upstairs_bathroom_missed_after_hallway_flap.py
# Authentic TRAV020/filter/policy qualification; selected public replay unchanged.
# Original numeric/time/assertion contract: completion-legacy-mapping.md, L2055.

"""Retain the third September 10 lighting incident independently of the first two.

Approved captures: Homelab tmp/inc-2026-09-10-upstairs-{status,history,trace}.json.
Count 2 is observed; count 1 is synthetic. Generic hall--entrance--closet and
hall--bathroom preserve the material graph, profiles, reliability and ordering.
Office's clear is noncausal; its raw-on startup level is fixture-only, not an
invented earlier acquisition. Only target pre-belief is seeded from the audit;
no hidden production episode/token/support snapshot is claimed or fabricated.

Observed bathroom ordinary positive at 20:55:51.806096Z raised belief from
0.22530608076879483 to 0.8792240073516933 but stayed unauthorized/pending.
Recovery press 20:55:56.215000Z produced HA active at 56.218314 and light-on
56.305799. Consumer control_upstairs_bathroom_light_by_motion correctly ran
trace 49b9b06141695ee14dc6d498a8ecbacc. The press must not satisfy this replay.
REQ-TRAV-020 preserves only original historical adjacency, never episode
validity, renewed authority, source refresh or evidence from the flap.
"""

import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
)
from tests.legacy_qualification_fixture import restore_qualification
from tests.persistence_component_fixture import PersistenceComponents

WEIGHTS = {"hall": 0.85, "entrance": 0.8, "closet": 0.8,
           "bathroom": 0.7, "office": 0.75}


def _at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-10T{time}+00:00")


def _map() -> PredictiveMap:
    adjacency = {
        "hall": ["entrance", "bathroom", "office"],
        "entrance": ["hall", "closet"],
        "closet": ["entrance"],
        "bathroom": ["hall"],
        "office": ["hall"],
    }
    return PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": (
                    "transition_gate" if node in {"hall", "entrance"}
                    else "subzone_occupancy" if node == "closet"
                    else "room_occupancy"
                ),
                "occupancy_behavior": (
                    "transient" if node in {"hall", "entrance"}
                    else "sustained" if node == "closet" else "sticky"
                ),
                "entities": {
                    "motion" if node == "entrance" else "mmwave":
                    f"binary_sensor.{node}",
                },
                "initial_weight": WEIGHTS[node],
                "adjacent": neighbors,
            }
            for node, neighbors in adjacency.items()
        },
    })


@pytest.mark.target_model
@pytest.mark.parametrize("count", (2, 1))
def test_legacy_incident_2055_seeded(
    count: int,
) -> None:
    predictive_map = _map()
    engine = PersistenceComponents(predictive_map, count, _at("20:55:00"))
    engine.bootstrap_sensor_snapshot(tuple(
        SensorInput(f"binary_sensor.{node}", "on" if node == "office" else "off",
                    _at("20:55:00"), reliability=weight)
        for node, weight in WEIGHTS.items()
    ), _at("20:55:00"))

    for time, node, expected_reason in (
        ("20:55:32.824275", "hall", "track_bootstrap_pending"),
        ("20:55:36.229620", "entrance", "provisional_track_acquired"),
        ("20:55:39.457535", "closet", "track_confirmed"),
    ):
        result = engine.observe(SensorInput(
            f"binary_sensor.{node}", "on", _at(time), WEIGHTS[node],
        ))
        assert result.authorizations[0].reason == expected_reason

    original = next(t for t in engine.snapshot.traversal_tokens if t.node_id == "hall")
    assert original.accepted_at == _at("20:55:32.824275")
    assert original.valid_until == _at("20:56:17.824275")
    assert original.continuity_reopened_at is None
    assert all(
        b.token_id != original.token_id
        for b in engine.snapshot.support_token_bindings
    )
    engine.observe(SensorInput(
        "binary_sensor.hall", "off", _at("20:55:43.087332"), 0.85,
    ))
    flap = engine.observe(SensorInput(
        "binary_sensor.hall", "on", _at("20:55:43.938962"), 0.85,
    ))
    assert _at("20:55:43.938962") - _at("20:55:43.087332") == timedelta(
        microseconds=851630,
    )
    hall = next(s for s in flap.snapshot.episode_states if s.node_id == "hall")
    assert hall.episode_id == original.episode_id
    assert hall.cadence_warning_reason == "impossible_cadence"
    assert hall.cadence_warning and not hall.health_warning
    assert hall.traversal_valid_until is None
    assert not flap.authorizations
    assert not any(e.zone == "hall" for e in flap.policy_events)
    engine.observe(SensorInput(
        "binary_sensor.office", "off", _at("20:55:49.607010"), 0.75,
    ))

    target_at = _at("20:55:51.806096")
    press_at = _at("20:55:56.215000")
    assert original.valid_until - target_at == timedelta(seconds=26, microseconds=18179)
    # Fixture-only scalar seam, NOT a restorable production snapshot: history
    # does not contain the bathroom's old belief generation. Add no fake episode.
    engine.advance(target_at)
    before = 0.22530608076879483
    target_filter = engine.filters["bathroom"]
    target_filter._state = replace(
        target_filter.state, log_odds=math.log(before / (1 - before)),
    )
    assert not next(
        s for s in engine.snapshot.policy_states if s.zone == "bathroom"
    ).active
    arrival = engine.observe(SensorInput(
        "binary_sensor.bathroom", "on", target_at, 0.7,
    ))
    policy = next(s for s in arrival.snapshot.policy_states if s.zone == "bathroom")
    assert policy.active, (
        "Bathroom must acquire at detected entry before the recovery press",
        arrival.authorizations,
    )
    assert [
        (e.zone, e.kind, e.event_at)
        for e in arrival.policy_events if e.zone == "bathroom"
    ] == [
        ("bathroom", "acquired", target_at),
    ]
    authorization = arrival.authorizations[0]
    assert authorization.authorized and authorization.reason == "adjacent_authorized"
    assert original in authorization.source_tokens
    assert original.token_id not in arrival.snapshot.current_token_ids
    assert next(
        t for t in arrival.snapshot.traversal_tokens if t.token_id == original.token_id
    ) == original
    belief = next(s for s in arrival.snapshot.belief_states if s.zone == "bathroom")
    transition, = [c for c in belief.contributions if c.kind == "arrival_transition"]
    post_local = 1 / (1 + math.exp(-(belief.log_odds - transition.log_odds_delta)))
    assert post_local == pytest.approx(0.8792240073516933, abs=1e-12)
    assert belief.probability == pytest.approx(0.75 + 0.05 * post_local, abs=1e-12)
    before_press = engine.advance(press_at - timedelta(microseconds=1))
    assert next(
        s for s in before_press.snapshot.policy_states if s.zone == "bathroom"
    ).active

    # Same original token must roundtrip as NONCURRENT despite the flap. Reject
    # only its malformed expiry using the immutable real validator, not a mock.
    restored = restore_qualification(engine)
    assert restored.snapshot == engine.snapshot
    snapshot = engine.snapshot
    validator = SnapshotValidator(
        predictive_map, engine.nodes, engine.supports._confirmed_strength,
    )
    validator.validate_tokens(snapshot)
    malformed = replace(snapshot, traversal_tokens=tuple(
        replace(token, valid_until=token.valid_until + timedelta(microseconds=1))
        if token.token_id == original.token_id else token
        for token in snapshot.traversal_tokens
    ))
    with pytest.raises(ValueError, match="not bound to its physical episode"):
        validator.validate_tokens(malformed)
    assert engine.snapshot == snapshot
    for current in (engine, restored):
        current.advance(original.valid_until)
        assert not any(
            token.token_id == original.token_id
            for token in current.snapshot.traversal_tokens
        )
    assert restored.snapshot == engine.snapshot
