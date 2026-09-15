"""Synthetic STATE-001/002/008/009/010 extraction characterization.

These are authentic standalone episode/frontier/support/count records, not old
engine output or incident captures. Current-reader controls combine independently
issued ordinary tokens with unchanged selected state from the same map/events.
The pre-extraction tests exercise real reader/private pure boundaries; component
tests added after extraction exercise the very same production validation code.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.count import CountConflictTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.profiles import (
    SHARED_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountSupport,
    PendingAcquisitionCandidate,
    SensorInput,
    TraversalToken,
    ZoneModelSnapshot,
)
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
    validate_component_snapshot,
)

pytestmark = pytest.mark.target_model
START = datetime(2026, 6, 1, 10, tzinfo=UTC)
MICROSECOND = timedelta(microseconds=1)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def specimen(*, pending: bool = False) -> tuple[
    PredictiveMap, ZoneModelEngine, ZoneModelSnapshot, AnonymousSupportTracker,
]:
    """Build ordinary provenance independently, without changing engine state."""
    predictive_map = PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": "room_occupancy" if node in {"tip", "target"}
                else "transition_gate",
                "occupancy_behavior": "sustained" if node in {"tip", "target"}
                else "transient",
                "entities": {
                    "mmwave" if node in {"tip", "target"} else "motion":
                    f"binary_sensor.{node}",
                },
                "adjacent": adjacent,
            }
            for node, adjacent in (
                ("source", ["bridge", "target"]),
                ("bridge", ["source", "tip"]),
                ("tip", ["bridge"]),
                ("target", ["source"]),
                ("unrelated", []),
            )
        },
    })
    nodes = build_physical_nodes(predictive_map).nodes
    engine = ZoneModelEngine(predictive_map, 1, at(-1))
    baseline = tuple(
        SensorInput(alias, "off", at(-1)) for node in nodes for alias in node.aliases
    )
    engine.bootstrap_sensor_snapshot(baseline, at(-1))
    episodes = PhysicalEpisodes(nodes)
    episodes.restore_snapshot(engine.snapshot.episode_states)
    frontier = TraversalFrontier(predictive_map, nodes)
    supports = AnonymousSupportTracker(predictive_map, nodes)
    observations = [("source", 0), ("bridge", 2), ("tip", 4)]
    if pending:
        observations.append(("unrelated", 6))
    for node_id, seconds in observations:
        event = SensorInput(f"binary_sensor.{node_id}", "on", at(seconds))
        engine.observe(event)
        update = episodes.observe(event)
        effect, = update.effects
        authorization = frontier.authorize(update.state, effect.at, count=None)
        token = frontier.issue(update.state, effect, authorization) if (
            authorization.authorized
        ) else None
        supports.apply(
            effect.at, effect, authorization, token, episodes.states,
            engine.snapshot.belief_states, frontier.tokens, frontier.retained_tokens,
        )
    # This constructor deliberately does not install legacy support authority.
    snapshot = replace(
        engine.snapshot,
        traversal_tokens=frontier.tokens,
        current_token_ids=frontier.current_token_ids,
        authorization_uses=frontier.uses,
        pending_candidates=frontier.pending_candidates,
        retained_traversal_tokens=frontier.retained_tokens,
    )
    assert len(snapshot.traversal_tokens) == 3
    assert snapshot.authorization_uses
    assert supports.supports
    assert engine.snapshot.traversal_tokens == ()
    return predictive_map, engine, snapshot, supports


def restore(
    predictive_map: PredictiveMap, engine: ZoneModelEngine,
    snapshot: ZoneModelSnapshot,
) -> ZoneModelEngine:
    return ZoneModelEngine.restore(
        predictive_map, snapshot, (), snapshot.updated_at,
        prediction_state=engine.prediction_manager.serialize(),
    )


def replace_token(
    snapshot: ZoneModelSnapshot, token: TraversalToken,
) -> ZoneModelSnapshot:
    return replace(snapshot, traversal_tokens=tuple(
        token if item.token_id == token.token_id else item
        for item in snapshot.traversal_tokens
    ))


def test_current_reader_accepts_component_tokens_and_continues() -> None:
    predictive_map, engine, snapshot, _ = specimen()
    before = deepcopy(snapshot)
    original = engine.snapshot
    restored = restore(predictive_map, engine, snapshot)
    assert restored.snapshot == snapshot == before
    assert engine.snapshot == original
    control = restore(predictive_map, engine, snapshot)
    resumed = ZoneModelEngine.restore(
        predictive_map, snapshot, (), at(5),
        prediction_state=engine.prediction_manager.serialize(),
    )
    control.advance(at(5))
    assert resumed.snapshot == control.snapshot
    event = SensorInput("binary_sensor.target", "on", at(6))
    assert resumed.observe(event) == control.observe(event)
    assert next(p for p in resumed.snapshot.policy_states if p.zone == "target").active
    assert snapshot == before


@pytest.mark.parametrize(("mutation", "message"), [
    ("deadline", "physical episode"),
    ("node", "physical episode"),
    ("provenance", "provenance is incompatible"),
    ("confirmed", "Confirmed traversal token lacks"),
    ("equivalent", "Equivalent traversal strength"),
    ("path", "graph-incompatible"),
    ("duplicate", "snapshot is duplicated"),
    ("current", "Current traversal token does not exist"),
    ("use_source", "incompatible source frontier"),
    ("use_time", "predates its target episode"),
])
def test_current_reader_token_mutation_sensitivity(
    mutation: str, message: str,
) -> None:
    predictive_map, engine, snapshot, _ = specimen()
    assert restore(predictive_map, engine, snapshot).snapshot == snapshot
    token = next(t for t in snapshot.traversal_tokens if t.node_id == "source")
    changed = snapshot
    if mutation == "deadline":
        changed = replace_token(snapshot, replace(
            token, valid_until=token.valid_until + MICROSECOND,
        ))
    elif mutation == "node":
        changed = replace_token(snapshot, replace(token, node_id="unrelated"))
    elif mutation == "provenance":
        changed = replace_token(snapshot, replace(token, provenance_kind="forged"))
    elif mutation == "confirmed":
        changed = replace_token(snapshot, replace(token, track_confidence="confirmed"))
    elif mutation == "equivalent":
        changed = replace_token(snapshot, replace(
            token, equivalent_confirmed_strength=True,
        ))
    elif mutation == "path":
        changed = replace_token(snapshot, replace(
            token, path_node_ids=("unrelated", "source"),
        ))
    elif mutation == "duplicate":
        changed = replace(
            snapshot, traversal_tokens=(*snapshot.traversal_tokens, token),
        )
    elif mutation == "current":
        changed = replace(snapshot, current_token_ids=("missing",))
    elif mutation == "use_source":
        changed = replace(snapshot, authorization_uses=(replace(
            snapshot.authorization_uses[0], token_id="missing",
        ),))
    elif mutation == "use_time":
        use = next(u for u in snapshot.authorization_uses if u.authorized_at == at(4))
        changed = replace(snapshot, authorization_uses=(replace(
            use, authorized_at=at(3),
        ),))
    assert changed != snapshot
    before, receiver = deepcopy(changed), engine.snapshot
    with pytest.raises(ValueError, match=message):
        restore(predictive_map, engine, changed)
    assert changed == before
    assert engine.snapshot == receiver
    assert restore(predictive_map, engine, snapshot).snapshot == snapshot


@pytest.mark.parametrize("mutation", ["expiry", "reliability", "node"])
def test_current_reader_pending_mutation_sensitivity(mutation: str) -> None:
    predictive_map, engine, snapshot, _ = specimen(pending=True)
    assert restore(predictive_map, engine, snapshot).snapshot == snapshot
    candidate, = snapshot.pending_candidates
    changed_candidate = (
        replace(candidate, expires_at=candidate.expires_at + MICROSECOND)
        if mutation == "expiry" else
        replace(candidate, reliability=candidate.reliability / 2)
        if mutation == "reliability" else replace(candidate, node_id="target")
    )
    changed = replace(snapshot, pending_candidates=(changed_candidate,))
    before, receiver = deepcopy(changed), engine.snapshot
    with pytest.raises(ValueError, match="Pending candidate is not bound"):
        restore(predictive_map, engine, changed)
    assert changed == before and engine.snapshot == receiver


def test_episode_reference_exact_historical_and_selected_equality() -> None:
    _, _, snapshot, _ = specimen()
    state = next(s for s in snapshot.episode_states if s.node_id == "source")
    assert state.episode_id is not None
    states = {state.node_id: state}
    reference = ZoneModelEngine._episode_reference
    assert reference(state.episode_id, states, at(4), exact=True) == (state, at(0))
    newer = replace(state, generation=2, episode_id=f"source:2:{at(4).isoformat()}",
                    started_at=at(4))
    states["source"] = newer
    assert reference(state.episode_id, states, at(4), exact=False) == (newer, at(0))
    with pytest.raises(ValueError, match="outside stored state"):
        reference(state.episode_id, states, at(4), exact=True)
    equal = f"source:1:{at(4).isoformat()}"
    with pytest.raises(ValueError, match="outside stored state"):
        reference(equal, states, at(4), exact=False)
    assert reference(equal, states, at(4), exact=False, selected=True) == (newer, at(4))
    with pytest.raises(ValueError, match="malformed"):
        reference("source:bad:timestamp", states, at(4), exact=False)
    with pytest.raises(ValueError, match="no stored physical node"):
        reference("missing:1:timestamp", states, at(4), exact=False)


@pytest.mark.parametrize("mutation", ["endpoint", "origin", "binding", "strength"])
def test_pure_support_boundary_accepts_then_rejects(mutation: str) -> None:
    _, engine, snapshot, tracker = specimen()
    snapshot = replace(snapshot, anonymous_supports=tracker.supports,
                       support_token_bindings=tracker.bindings)
    tokens = {t.token_id: t for t in snapshot.traversal_tokens}
    engine._validate_support_snapshot(snapshot, tokens, {})
    support, = snapshot.anonymous_supports
    if mutation == "endpoint":
        changed = replace(snapshot, anonymous_supports=(replace(
            support, current_zone="target",
        ),))
        message = "endpoint is incompatible"
    elif mutation == "origin":
        changed = replace(snapshot, anonymous_supports=(replace(
            support, created_at=support.created_at - MICROSECOND,
            support_id="support:missing:missing:1:timestamp",
        ),), support_token_bindings=())
        message = "origin node is incompatible"
    elif mutation == "binding":
        changed = replace(snapshot, support_token_bindings=(replace(
            snapshot.support_token_bindings[0], token_id="missing",
        ),))
        message = "Support-token binding is incompatible"
    else:
        origin = tokens[support.support_id.removeprefix("support:")]
        tokens[origin.token_id] = replace(origin, track_confidence="provisional")
        changed = snapshot
        message = "origin lacks valid creation strength"
    before, receiver = deepcopy(changed), engine.snapshot
    with pytest.raises(ValueError, match=message):
        engine._validate_support_snapshot(changed, tokens, {})
    assert changed == before and engine.snapshot == receiver
    engine._validate_support_snapshot(
        snapshot, {t.token_id: t for t in snapshot.traversal_tokens}, {},
    )


def test_pure_count_boundary_and_current_strict_rejection() -> None:
    predictive_map, engine, snapshot, tracker = specimen()
    engine.observe(SensorInput("binary_sensor.target", "on", at(6)))
    snapshot = replace(engine.snapshot, anonymous_supports=tracker.supports)
    nodes = build_physical_nodes(predictive_map).nodes
    conflicts = CountConflictTracker()
    conflicts.evaluate(
        at(6), 1, nodes, snapshot.episode_states,
        tuple(CountSupport(s.support_id, s.current_node_id, s.current_zone,
                           s.path_node_ids) for s in tracker.supports),
        {n.zone: POLICY_CALIBRATIONS[n.profile_name].release_dwell for n in nodes},
    )
    conflict, = conflicts.conflicts
    snapshot = replace(snapshot, count_conflicts=(conflict,))
    engine._validate_count_snapshot(snapshot)
    changed = replace(snapshot, count_conflicts=(replace(
        conflict, deadline=conflict.deadline + MICROSECOND,
    ),))
    before, receiver = deepcopy(changed), engine.snapshot
    with pytest.raises(ValueError, match="Count-conflict snapshot is incompatible"):
        engine._validate_count_snapshot(changed)
    assert changed == before and engine.snapshot == receiver
    with pytest.raises(ValueError, match="cannot restore count degradation"):
        restore(predictive_map, engine, snapshot)
    engine._validate_count_snapshot(snapshot)


def warned_specimen() -> tuple[PredictiveMap, ZoneModelEngine, ZoneModelSnapshot]:
    """Authentic source warning plus its original independently issued token.

    Only source authority is included: this is an explicitly isolated component
    input, not a claim that the selected engine creates or preserves old tokens.
    """
    predictive_map, engine, snapshot, _ = specimen()
    nodes = build_physical_nodes(predictive_map).nodes
    episodes = PhysicalEpisodes(nodes)
    episodes.restore_snapshot(snapshot.episode_states)
    episodes.observe(SensorInput("binary_sensor.source", "off", at(8)))
    update = episodes.observe(SensorInput("binary_sensor.source", "on", at(9)))
    assert update.state.cadence_warning
    assert update.state.cadence_warning_reason == "impossible_cadence"
    original = next(t for t in snapshot.traversal_tokens if t.node_id == "source")
    snapshot = replace(
        snapshot, updated_at=at(9), episode_states=episodes.states,
        traversal_tokens=(original,), current_token_ids=(),
        authorization_uses=tuple(
            use for use in snapshot.authorization_uses
            if use.token_id == original.token_id
        ),
    )
    PhysicalEpisodes(nodes).restore_snapshot(snapshot.episode_states)
    validate_component_snapshot(predictive_map, nodes, snapshot)
    return predictive_map, engine, snapshot


def test_component_validation_is_pure_and_convenience_matches_explicit() -> None:
    predictive_map, engine, snapshot, tracker = specimen(pending=True)
    nodes = build_physical_nodes(predictive_map).nodes
    snapshot = replace(snapshot, anonymous_supports=tracker.supports,
                       support_token_bindings=tracker.bindings)
    before, receiver = deepcopy(snapshot), engine.snapshot
    tracker_before = (tracker.supports, tracker.bindings, tracker.latest_transition,
                      tracker.counters)
    validator = SnapshotValidator(predictive_map, nodes, tracker._confirmed_strength)
    tokens, retained = validator.validate_tokens(snapshot)
    validator.validate_current_pending_uses(snapshot, tokens, retained)
    validator.validate_support_snapshot(snapshot, tokens, retained)
    validator.validate_count_snapshot(snapshot)
    validator.validate(snapshot)
    validate_component_snapshot(predictive_map, nodes, snapshot)
    assert snapshot == before and engine.snapshot == receiver
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters) == tracker_before
    # Returned indexes are caller-owned, not a cache or back door into the snapshot.
    tokens.clear()
    assert len(snapshot.traversal_tokens) == 3
    validator.validate(snapshot)


@pytest.mark.parametrize("seconds", [20, 45])
def test_warned_component_continuation_preserves_original_half_open_deadline(
    seconds: int,
) -> None:
    predictive_map, _, snapshot = warned_specimen()
    before = deepcopy(snapshot)
    nodes = build_physical_nodes(predictive_map).nodes
    episodes = PhysicalEpisodes(nodes)
    episodes.restore_snapshot(snapshot.episode_states)
    frontier = TraversalFrontier(predictive_map, nodes)
    frontier.restore_snapshot(
        snapshot.traversal_tokens, snapshot.current_token_ids,
        snapshot.authorization_uses, snapshot.updated_at,
        snapshot.pending_candidates, snapshot.retained_traversal_tokens,
    )
    # Frontier.advance alone retains dormant lineage. Actual physical sync must
    # withdraw the warned original and its uses before the next external input.
    episodes.advance(at(seconds))
    for state in episodes.states:
        frontier.sync(state, at(seconds))
    update = episodes.observe(SensorInput("binary_sensor.target", "on", at(seconds)))
    authorization = frontier.authorize(update.state, at(seconds), count=None)
    assert authorization.authorized is (seconds < 45)
    if seconds < 45:
        assert authorization.reason == "adjacent_authorized"
        assert authorization.source_tokens == snapshot.traversal_tokens
        effect, = update.effects
        issued = frontier.issue(update.state, effect, authorization)
        assert issued.accepted_at == at(seconds)
        assert snapshot.traversal_tokens[0] in frontier.tokens
    else:
        assert authorization.reason == "track_bootstrap_pending"
        assert frontier.tokens == ()
        assert frontier.uses == ()
    assert snapshot == before


@pytest.mark.parametrize(("mutation", "message"), [
    ("current", "not physically current"),
    ("reopened", "Warned traversal token is not preservable"),
    ("premature_reopening", "not bound to its physical episode"),
    ("dormant", "Warned traversal token is not preservable"),
    ("pending", "Pending candidate is not bound"),
    ("extended", "not bound to its physical episode"),
    ("late_acceptance", "not bound to its physical episode"),
    ("provenance", "provenance is incompatible"),
    ("path", "graph-incompatible"),
])
def test_warned_component_cross_links_are_sensitive(
    mutation: str, message: str,
) -> None:
    predictive_map, engine, snapshot = warned_specimen()
    nodes = build_physical_nodes(predictive_map).nodes
    original, = snapshot.traversal_tokens
    state = next(s for s in snapshot.episode_states if s.node_id == original.node_id)
    profile = SHARED_PROFILES[original.profile_name]
    if mutation == "current":
        changed = replace(snapshot, current_token_ids=(original.token_id,))
    elif mutation == "reopened":
        reopened_at = original.accepted_at + profile.hardware_hold_interval
        changed = replace(replace_token(snapshot, replace(
            original, continuity_reopened_at=reopened_at,
            valid_until=min(
                reopened_at + profile.traversal_context_window,
                original.accepted_at + profile.assertion_trust_horizon,
            ),
        )), updated_at=reopened_at)
    elif mutation == "premature_reopening":
        changed = replace_token(snapshot, replace(
            original, continuity_reopened_at=at(8),
            valid_until=at(8) + profile.traversal_context_window,
        ))
    elif mutation == "dormant":
        changed = replace(
            snapshot, updated_at=original.valid_until, traversal_tokens=(),
            retained_traversal_tokens=(original,),
        )
    elif mutation == "pending":
        physical = next(n for n in nodes if n.node_id == original.node_id)
        changed = replace(snapshot, pending_candidates=(PendingAcquisitionCandidate(
            state.node_id, state.zone, state.profile_name, original.episode_id,
            original.accepted_at, original.accepted_at + profile.track_bootstrap_window,
            original.valid_until, physical.reliability,
        ),))
    elif mutation == "extended":
        changed = replace_token(snapshot, replace(
            original, valid_until=original.valid_until + MICROSECOND,
        ))
    elif mutation == "late_acceptance":
        changed = replace_token(snapshot, replace(
            original, accepted_at=original.accepted_at + MICROSECOND,
        ))
    elif mutation == "provenance":
        changed = replace_token(snapshot, replace(original, provenance_kind="forged"))
    else:
        changed = replace_token(snapshot, replace(
            original, path_node_ids=("unrelated", "source"),
        ))
    assert changed != snapshot
    before, receiver = deepcopy(changed), engine.snapshot
    with pytest.raises(ValueError, match=message):
        validate_component_snapshot(predictive_map, nodes, changed)
    assert changed == before and engine.snapshot == receiver
    validate_component_snapshot(predictive_map, nodes, snapshot)


def test_current_reader_still_rejects_accepted_legacy_warning_component() -> None:
    predictive_map, engine, snapshot = warned_specimen()
    before, receiver = deepcopy(snapshot), engine.snapshot
    with pytest.raises(ValueError, match="cannot restore legacy warnings"):
        restore(predictive_map, engine, snapshot)
    assert snapshot == before and engine.snapshot == receiver
    # A separate ordinary control still continues through the current reader.
    assert restore(predictive_map, engine, receiver).snapshot == receiver


def test_validation_keeps_count_then_token_then_current_failure_order() -> None:
    predictive_map, _, snapshot, tracker = specimen()
    nodes = build_physical_nodes(predictive_map).nodes
    validator = SnapshotValidator(predictive_map, nodes, tracker._confirmed_strength)
    token = snapshot.traversal_tokens[0]
    bad_token = replace_token(snapshot, replace(token, provenance_kind="forged"))
    bad_current = replace(bad_token, current_token_ids=("missing",))
    bad_count = replace(bad_current, count_state=replace(
        snapshot.count_state, last_event_at=at(0),
    ))
    with pytest.raises(ValueError, match="Count snapshot event identity is incomplete"):
        validator.validate(bad_count)
    with pytest.raises(ValueError, match="Traversal token provenance is incompatible"):
        validator.validate(bad_current)
    with pytest.raises(ValueError, match="Current traversal token does not exist"):
        validator.validate(replace(snapshot, current_token_ids=("missing",)))
    validator.validate(snapshot)
