"""REQ-PATH-005/POLICY-014: selected departure and retained release frontiers.

Synthetic real-engine sequences, not captured incidents. The 2026-09-13 approved
migration preserves all 86 IDs and physical inputs. Selected displacement replaces
legacy support/token qualification; physical presence is a separate hold. Unknown
aliases withdraw presence without stable clear. The approved crossing is
1046.484750s, with full 120s dwell and ordinary five-second timer OFF at 1170s.
Historical function names remain collection identities, not legacy premises.
No injected inference state or calibration changes are used.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeState,
    SensorInput,
    ZoneBeliefState,
    ZoneModelResult,
    ZoneModelSnapshot,
    ZonePolicyState,
)

pytestmark = pytest.mark.target_model
START = datetime(2026, 6, 1, tzinfo=UTC)
VARIANTS = (
    "advance", "same_zone_baseline_clear", "other_zone_baseline_clear",
    "duplicate_off", "duplicate_unknown_alias", "accepted_count",
    "duplicate_count", "invalid_count", "unavailable_count",
)


def _at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def _map() -> PredictiveMap:
    nodes: dict[str, object] = {
        node: {
            "zone": "room",
            "role": "anchor_sensor",
            "occupancy_behavior": "sticky",
            "entities": {
                "presence": f"binary_sensor.{node}",
                "mmwave": f"binary_sensor.{node}_alias",
            },
            "adjacent": ["pair"],
        }
        for node in ("source", "peer", "idle")
    }
    nodes.update({
        "button": {
            "zone": "room", "role": "room_occupancy",
            "occupancy_behavior": "sticky",
            "entities": {"interaction_scene_002": "event.button"},
            "adjacent": ["pair"],
        },
        "pair": {
            "role": "anchor_sensor", "occupancy_behavior": "sticky",
            "entities": {"presence": "binary_sensor.pair"},
            "adjacent": ["source", "peer", "idle", "button", "middle"],
        },
        "middle": {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"motion": "binary_sensor.middle"},
            "adjacent": ["pair", "tip"],
        },
        "tip": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.tip"},
            "adjacent": ["middle"],
        },
        "other": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.other"},
        },
    })
    return PredictiveMap.from_mapping({"nodes": nodes})


def _belief(snapshot: ZoneModelSnapshot) -> ZoneBeliefState:
    return next(state for state in snapshot.belief_states if state.zone == "room")


def _policy(snapshot: ZoneModelSnapshot) -> ZonePolicyState:
    return next(state for state in snapshot.policy_states if state.zone == "room")


def _episode(snapshot: ZoneModelSnapshot, node: str) -> EpisodeState:
    return next(state for state in snapshot.episode_states if state.node_id == node)


def _send(
    engine: ZoneModelEngine, node: str, state: str, seconds: float,
) -> ZoneModelResult:
    return engine.observe(SensorInput(f"binary_sensor.{node}", state, _at(seconds)))


def _departure(
    count: int, *, peer: bool = False, source_clear: float = 810,
    peer_clear: float | None = None,
) -> tuple[PredictiveMap, ZoneModelEngine]:
    predictive_map = _map()
    engine = ZoneModelEngine(predictive_map, count, _at(-1))
    engine.observe_count(CountInput("initial-count", count, True, _at(-1)))
    _send(engine, "source", "on", 0)
    if peer:
        _send(engine, "peer", "on", 1)
    acquired = engine.observe(SensorInput("event.button", "pressed", _at(200)))
    assert [(e.zone, e.kind) for e in acquired.policy_events] == [
        ("room", "refreshed" if peer else "acquired"),
    ]
    first = _send(engine, "pair", "on", 800)
    second = _send(engine, "middle", "on", 804)
    third = _send(engine, "tip", "on", 806)
    assert all(
        result.authorizations[0].reason == "selected_path"
        for result in (first, second, third)
    )
    assert first.authorizations[0].path_node_ids == (
        "peer" if peer else "source", "button", "pair",
    )
    assert second.authorizations[0].path_node_ids == ("button", "pair", "middle")
    assert third.authorizations[0].path_node_ids == ("pair", "middle", "tip")
    snapshot = third.snapshot
    assert _policy(snapshot).active and not _policy(snapshot).retained_endpoint_hold
    assert _belief(snapshot).physical_hold
    assert _belief(snapshot).path_displaced_at == _at(806)
    assert _belief(snapshot).qualified_departure_at is None
    assert (
        _belief(snapshot).generation_episode_id
        == _episode(snapshot, "peer" if peer else "source").episode_id
    )
    # Selected movement, not fabricated legacy token/support state, displaced
    # the endpoint. Reconciliation selects the actual physical witness, not button.
    assert not any(t.node_id == "source" for t in snapshot.traversal_tokens)
    if peer_clear is not None:
        _send(engine, "peer", "off", peer_clear)
    _send(engine, "source", "off", source_clear)
    assert _episode(engine.snapshot, "source").status == "unavailable"
    assert _episode(engine.snapshot, "source").clear_deadline is None
    assert _belief(engine.snapshot).physical_hold == (peer and peer_clear is None)
    return predictive_map, engine


def _restore(predictive_map: PredictiveMap, engine: ZoneModelEngine) -> ZoneModelEngine:
    before = engine.snapshot
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(
        predictive_map, json.loads(json.dumps(payload)), before.updated_at,
    )
    assert restored is not engine
    assert restored.snapshot == before
    assert serialize_target_state(predictive_map, restored) == payload
    return restored


def _trigger(engine: ZoneModelEngine, variant: str, seconds: float) -> ZoneModelResult:
    at = _at(seconds)
    count = engine.snapshot.count_state.expected_count
    if variant == "advance":
        return engine.advance(at)
    if variant == "same_zone_baseline_clear":
        result = _send(engine, "idle", "off", seconds)
        assert result.disposition == "baseline_clear"
        return result
    if variant == "other_zone_baseline_clear":
        result = _send(engine, "other", "off", seconds)
        assert result.disposition == "baseline_clear"
        return result
    if variant in {"duplicate_off", "duplicate_unknown_alias"}:
        result = _send(
            engine,
            "source" if variant == "duplicate_off" else "source_alias",
            "off" if variant == "duplicate_off" else "unknown", seconds,
        )
        assert result.disposition == "duplicate"
        return result
    return engine.observe_count(CountInput(
        "initial-count" if variant == "duplicate_count" else "later-count",
        None if variant == "invalid_count" else count,
        variant != "unavailable_count", at,
    ))


def _released(result: ZoneModelResult) -> bool:
    return any(e.zone == "room" and e.kind == "released" for e in result.policy_events)


def _assert_reader_and_noop_parity(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
) -> None:
    before = engine.snapshot
    payload = serialize_target_state(predictive_map, engine)
    assert serialize_target_state(predictive_map, engine) == payload
    assert engine.snapshot == before
    restored = _restore(predictive_map, engine)
    for candidate in (engine, restored):
        result = candidate.advance(before.updated_at)
        assert not result.policy_events and not result.authorizations
        assert result.snapshot.belief_states == before.belief_states
        assert result.snapshot.episode_states == before.episode_states
        assert result.snapshot.anonymous_supports == before.anonymous_supports
        assert result.snapshot.support_token_bindings == before.support_token_bindings
        assert result.snapshot.selected_paths == before.selected_paths
        assert result.snapshot.selected_sources == before.selected_sources
        assert _policy(result.snapshot).active == _policy(before).active
    assert engine.snapshot == restored.snapshot


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("variant", VARIANTS)
def test_qualified_release_frontier_matrix(count: int, variant: str) -> None:
    """Retain all 18 cases, each with coarse/fine/JSON-restored continuation."""
    predictive_map, coarse = _departure(count)
    fine = _restore(predictive_map, coarse)
    restored = _restore(predictive_map, coarse)
    proof = fine.advance(_at(820))
    assert _belief(proof.snapshot).path_displaced_at == _at(806)
    assert not _belief(proof.snapshot).physical_hold
    assert _episode(proof.snapshot, "source").status == "unavailable"
    assert not _released(proof)
    pending = fine.advance(_at(1100))
    assert _policy(pending.snapshot).active
    assert _policy(pending.snapshot).pending_release_since is not None
    results = [_trigger(engine, variant, 1200) for engine in (coarse, fine, restored)]
    # Public release, not merely a surviving private qualification marker.
    assert all(not _policy(result.snapshot).active for result in results)
    assert all(_released(result) for result in results)
    expected = _belief(results[1].snapshot)
    for engine, result in zip((coarse, fine, restored), results, strict=True):
        belief = _belief(result.snapshot)
        assert belief.path_displaced_at == _at(806)
        assert belief.qualified_departure_at is None
        assert not belief.physical_hold
        # Stored context can change on baseline input; displacement chooses the
        # effective outward decay independently of that diagnostic label.
        assert belief.probability == pytest.approx(expected.probability, abs=1e-12)
        assert result.snapshot.count_state.expected_count == count
        assert not _policy(result.snapshot).retained_endpoint_hold
        assert _policy(result.snapshot).pending_release_since is None
        _assert_reader_and_noop_parity(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("variant", (
    "advance", "same_zone_baseline_clear", "invalid_count",
))
def test_first_clear_cannot_qualify_while_same_zone_peer_is_clearing(
    count: int, variant: str,
) -> None:
    """Original ID: last peer withdrawal, not fictitious all-alias stable clear."""
    predictive_map, coarse = _departure(count, peer=True)
    assert _belief(coarse.snapshot).physical_hold
    _send(coarse, "peer", "off", 815)
    fine = _restore(predictive_map, coarse)
    restored = _restore(predictive_map, coarse)
    first = fine.advance(_at(820))
    assert _episode(first.snapshot, "peer").status == "unavailable"
    assert _episode(first.snapshot, "peer").clear_deadline is None
    assert _belief(first.snapshot).qualified_departure_at is None
    assert not _belief(first.snapshot).physical_hold
    assert not _policy(first.snapshot).retained_endpoint_hold
    # Preserve the original 820/825 checkpoints, without inventing deadlines.
    between = _restore(predictive_map, fine)
    second = fine.advance(_at(825))
    assert _belief(second.snapshot).path_displaced_at == _at(806)
    assert _episode(second.snapshot, "source").status == "unavailable"
    assert _episode(second.snapshot, "peer").status == "unavailable"
    assert _policy(fine.advance(_at(1100)).snapshot).pending_release_since is not None
    engines = (coarse, fine, restored, between)
    results = [_trigger(engine, variant, 1142) for engine in engines]
    # Original 1142 checkpoint remains ON; peer protection must not count as dwell.
    assert all(_policy(result.snapshot).active for result in results)
    assert not any(_released(result) for result in results)
    pending = _policy(results[1].snapshot).pending_release_since
    assert pending is not None
    for result in results:
        assert _belief(result.snapshot).path_displaced_at == _at(806)
        assert not _belief(result.snapshot).physical_hold
        candidate = _policy(result.snapshot).pending_release_since
        assert candidate is not None
        assert abs(candidate - pending) <= timedelta(microseconds=1)
    assert abs(pending - _at(1051.460546)) <= timedelta(microseconds=1)
    for engine in engines:
        before_deadline = engine.advance(_at(1170))
        assert _policy(before_deadline.snapshot).active
        assert not _released(before_deadline)
        final = engine.advance(_at(1200))
        assert not _policy(final.snapshot).active and _released(final)
        _assert_reader_and_noop_parity(predictive_map, engine)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("alias_at", (817, 824, 825.5))
def test_peer_clear_uses_physical_deadline_not_last_alias_event(
    count: int, alias_at: float,
) -> None:
    # Peer withdraws at815, source at816: each other alias is still unknown.
    # A later all-OFF baseline does not create or restart a stable-clear deadline.
    predictive_map, engine = _departure(
        count, peer=True, source_clear=816, peer_clear=815,
    )
    alias = _send(engine, "peer_alias", "off", alias_at)
    assert alias.disposition == "baseline_clear"
    state = _episode(engine.snapshot, "peer")
    assert state.last_event_at == _at(alias_at)
    assert state.status == "baseline" and state.clear_deadline is None
    assert not _belief(engine.snapshot).physical_hold
    fine = _restore(predictive_map, engine)
    fine.advance(_at(826))
    for candidate in (engine, fine, _restore(predictive_map, engine)):
        result = candidate.advance(_at(1200))
        assert _belief(result.snapshot).path_displaced_at == _at(806)
        assert _belief(result.snapshot).qualified_departure_at is None
        assert not _policy(result.snapshot).active
        _assert_reader_and_noop_parity(predictive_map, candidate)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("peer_state", ("on", "unavailable"))
def test_asserted_peer_veto_and_unavailability_invalidate_qualification(
    count: int, peer_state: str,
) -> None:
    predictive_map, engine = _departure(count, peer=True)
    if peer_state == "unavailable":
        _send(engine, "peer", peer_state, 812)
    restored = _restore(predictive_map, engine)
    for candidate in (engine, restored):
        result = candidate.advance(_at(1200))
        if peer_state == "on":
            assert _policy(result.snapshot).active
            assert _belief(result.snapshot).physical_hold
            assert not _policy(result.snapshot).retained_endpoint_hold
            assert _belief(result.snapshot).qualified_departure_at is None
        else:
            # Availability withdraws the witness; selected displacement still
            # governs effective decay regardless of the stored context label.
            assert _episode(result.snapshot, "peer").status == "unavailable"
            assert not _belief(result.snapshot).physical_hold
            assert _belief(result.snapshot).path_displaced_at == _at(806)
            assert _belief(result.snapshot).qualified_departure_at is None
            assert not _policy(result.snapshot).active and _released(result)


@pytest.mark.parametrize("count", (1, 2))
def test_true_availability_clear_does_not_restore_old_qualification(count: int) -> None:
    predictive_map, engine = _departure(count)
    assert _belief(engine.advance(_at(820)).snapshot).path_displaced_at == _at(806)
    engine.observe(SensorInput("event.button", "unavailable", _at(830)))
    unavailable = _belief(engine.snapshot)
    assert unavailable.context == "unavailable"
    assert unavailable.qualified_departure_at is None
    result = _send(engine, "idle", "off", 840)
    assert result.disposition == "baseline_clear"
    assert _belief(result.snapshot).context == "cleared_without_outward"
    assert _belief(result.snapshot).qualified_departure_at is None
    assert _belief(result.snapshot).path_displaced_at == _at(806)
    assert not _belief(result.snapshot).physical_hold
    _assert_reader_and_noop_parity(predictive_map, engine)


IGNORED_RELEASE_INPUTS = (
    "duplicate_off", "duplicate_unknown_alias", "duplicate_count",
    "invalid_count", "unavailable_count",
)


def _ignored_trigger(
    engine: ZoneModelEngine, variant: str, seconds: float,
) -> ZoneModelResult:
    if variant in {"invalid_count", "unavailable_count"}:
        event_id = f"ignored:{variant}:{seconds}"
        expected = (
            "duplicate" if event_id in engine.snapshot.count_state.seen_event_ids
            else "invalid" if variant == "invalid_count" else "unavailable"
        )
        result = engine.observe_count(CountInput(
            event_id,
            None if variant == "invalid_count"
            else engine.snapshot.count_state.expected_count,
            variant != "unavailable_count", _at(seconds),
        ))
        assert result.disposition == expected
        return result
    return _trigger(engine, variant, seconds)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("variant", IGNORED_RELEASE_INPUTS)
@pytest.mark.parametrize("cadence", ("coarse", "fine", "restored"))
def test_qualified_dwell_progress_survives_repeated_ignored_inputs(
    count: int, variant: str, cadence: str,
) -> None:
    """No ordinary timer primes the candidate's lower-threshold interval.

    Unlike the original matrix's advance(1100), every candidate operation is
    the selected ignored physical/count input. Strict JSON restart straddles
    qualification and the first threshold-crossing callback. The control alone
    uses ordinary five-second timers; inputs and calibration are identical.
    """
    predictive_map, candidate = _departure(count)
    timer = _restore(predictive_map, candidate)
    original_frontier: datetime | None = None
    timer_releases: list[datetime] = []
    for seconds in range(815, 1201, 5):
        result = timer.advance(_at(seconds))
        pending = _policy(result.snapshot).pending_release_since
        if original_frontier is None and pending is not None:
            original_frontier = pending
        timer_releases.extend(
            event.event_at for event in result.policy_events
            if event.zone == "room" and event.kind == "released"
        )
    assert original_frontier is not None
    assert abs(original_frontier - _at(1046.484750)) <= timedelta(microseconds=1)
    assert timer_releases == [_at(1170)]
    assert not _policy(timer.snapshot).active

    candidate_results: list[ZoneModelResult] = []
    for seconds in (1200,) if cadence == "coarse" else range(815, 1201, 5):
        candidate_results.append(_ignored_trigger(candidate, variant, seconds))
        if cadence == "restored" and seconds in {820, 1015, 1020, 1045, 1050, 1100}:
            candidate = _restore(predictive_map, candidate)
    final = candidate_results[-1]
    # Primary public failure: ignored callbacks must not postpone qualified OFF.
    assert not _policy(final.snapshot).active
    events = [
        event for result in candidate_results for event in result.policy_events
        if event.zone == "room"
    ]
    assert [(event.kind, event.event_at) for event in events] == [
        ("released", _at(1200) if cadence == "coarse" else timer_releases[0]),
    ]
    for result in candidate_results:
        assert not result.authorizations
        assert not any(
            event.kind in {"acquired", "refreshed"} for event in result.policy_events
        )
        # Rejection diagnostics/dedup IDs may advance; accepted count may not.
        assert replace(
            result.snapshot.count_state,
            diagnostics=timer.snapshot.count_state.diagnostics,
            seen_event_ids=timer.snapshot.count_state.seen_event_ids,
        ) == timer.snapshot.count_state
        if result.snapshot.updated_at >= _at(820):
            assert _belief(result.snapshot).path_displaced_at == _at(806)
            assert not _belief(result.snapshot).physical_hold
        pending = _policy(result.snapshot).pending_release_since
        if cadence != "coarse" and _at(1050) <= result.snapshot.updated_at < _at(1170):
            assert pending is not None
            assert abs(pending - original_frontier) <= timedelta(microseconds=1)
        else:
            assert pending is None
        assert not any(
            contribution.at > _at(810)
            and contribution.kind in {"local_positive", "local_interaction"}
            for contribution in _belief(result.snapshot).contributions
        )
    for node in ("source", "button", "peer", "idle"):
        assert _episode(final.snapshot, node) == _episode(timer.snapshot, node)
    assert final.snapshot.anonymous_supports == timer.snapshot.anonymous_supports
    assert (
        final.snapshot.support_token_bindings == timer.snapshot.support_token_bindings
    )
    assert final.snapshot.selected_paths == timer.snapshot.selected_paths
    assert final.snapshot.selected_sources == timer.snapshot.selected_sources
    assert _belief(final.snapshot).probability == pytest.approx(
        _belief(timer.snapshot).probability, abs=1e-12,
    )
    _assert_reader_and_noop_parity(predictive_map, candidate)


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("variant", IGNORED_RELEASE_INPUTS)
def test_qualified_dwell_frontier_is_idempotent_and_releases_at_deadline(
    count: int, variant: str,
) -> None:
    predictive_map, engine = _departure(count)
    for seconds in range(815, 1021, 5):
        _ignored_trigger(engine, variant, seconds)
    # Keep the old crossing checkpoint/no-op, then straddle the approved crossing.
    old_checkpoint = engine.snapshot
    assert _policy(old_checkpoint).pending_release_since is None
    old_noop = _ignored_trigger(engine, variant, 1020)
    assert replace(old_noop.snapshot, count_state=old_checkpoint.count_state) == (
        old_checkpoint
    )
    assert not old_noop.policy_events and not old_noop.policy_decisions
    for seconds in range(1025, 1051, 5):
        _ignored_trigger(engine, variant, seconds)
    pending = _policy(engine.snapshot).pending_release_since
    assert pending is not None
    assert pending == _at(1046.484750)
    assert _policy(engine.snapshot).active
    restored = _restore(predictive_map, engine)
    for candidate in (engine, restored):
        before = candidate.snapshot
        same = _ignored_trigger(candidate, variant, 1050)
        assert replace(same.snapshot, count_state=before.count_state) == before
        assert not same.policy_events and not same.policy_decisions
        assert not same.authorizations
        before = candidate.snapshot
        for stale_input in (
            SensorInput("binary_sensor.source", "off", _at(1015)),
            CountInput("stale-count", 0, True, _at(1015)),
        ):
            stale = (
                candidate.observe(stale_input) if isinstance(stale_input, SensorInput)
                else candidate.observe_count(stale_input)
            )
            assert stale.disposition == "stale" and stale.snapshot == before
            assert not stale.policy_events and not stale.policy_decisions
        deadline = pending + timedelta(seconds=120)
        assert deadline == _at(1166.484750)
        before_seconds = (deadline - START).total_seconds() - 0.000001
        just_before = _ignored_trigger(candidate, variant, before_seconds)
        assert _policy(just_before.snapshot).active and not _released(just_before)
        assert _policy(just_before.snapshot).pending_release_since == pending
        due = _ignored_trigger(candidate, variant, (deadline - START).total_seconds())
        assert not _policy(due.snapshot).active and _released(due)
        again = _ignored_trigger(candidate, variant, (deadline - START).total_seconds())
        assert (
            replace(again.snapshot, count_state=due.snapshot.count_state)
            == due.snapshot
        )
        assert not again.policy_events and not again.authorizations
        after = _ignored_trigger(
            candidate, variant, (deadline - START).total_seconds() + 0.000001,
        )
        assert not _policy(after.snapshot).active and not _released(after)
    assert engine.snapshot == restored.snapshot


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("variant", IGNORED_RELEASE_INPUTS)
def test_ignored_inputs_do_not_start_unqualified_endpoint_dwell(
    count: int, variant: str,
) -> None:
    predictive_map, engine = _departure(count, peer=True)
    for seconds in range(815, 1201, 5):
        result = _ignored_trigger(engine, variant, seconds)
        assert not result.authorizations
        assert not any(event.zone == "room" for event in result.policy_events)
        assert _policy(result.snapshot).active
        assert _belief(result.snapshot).physical_hold
        assert not _policy(result.snapshot).retained_endpoint_hold
        assert _belief(result.snapshot).path_displaced_at == _at(806)
        assert _policy(result.snapshot).pending_release_since is None
        assert _belief(result.snapshot).qualified_departure_at is None
        if seconds == 1020:
            engine = _restore(predictive_map, engine)
