"""Synthetic scalar/policy/support contracts, not incident or lighting scenarios.

REQ-BELIEF-003/006/007/008/010, PATH003/004, POLICY001/002/005/007/014,
COUNT008/011 and TRAV016/018. PhysicalEpisodes, SelectedPaths and the actual
filter/policy/support components supply accepted controls. Legacy component
fixtures are consumed read-only; they do not model the selected engine.
See completion-scalar-retention.md for the pre-edit coverage/behavior ledger.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    ZonePolicy,
)
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPaths,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.types import (
    AnonymousOccupancySupport,
    EpisodeEffect,
    EpisodeState,
    PolicyUpdate,
    SensorInput,
    SupportTokenBinding,
    SupportTransitionEvent,
    TraversalAuthorization,
    ZoneBeliefState,
)
from tests.handoff_component_fixture import handoff_proposal
from tests.persistence_component_fixture import PersistenceComponents

pytestmark = pytest.mark.target_model

_NOW = datetime(2026, 9, 14, tzinfo=UTC)
_US = timedelta(microseconds=1)

type _SupportState = tuple[
    tuple[AnonymousOccupancySupport, ...],
    tuple[SupportTokenBinding, ...],
    SupportTransitionEvent | None,
    dict[str, int],
]


def _at(seconds: float) -> datetime:
    return _NOW + timedelta(seconds=seconds)


def _pair_map(*, aliases: bool = False, interaction: bool = False) -> PredictiveMap:
    entities = {"interaction": "event.b"} if interaction else {
        "motion": "binary_sensor.b",
    }
    if aliases:
        entities["pir"] = "binary_sensor.b_alias"
    return PredictiveMap.from_mapping({"nodes": {
        "a": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.a"}, "adjacent": ["b"],
        },
        "b": {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": entities, "adjacent": ["a"],
        },
    }})


@dataclass
class _Target:
    episodes: PhysicalEpisodes
    selected: SelectedPaths
    filter: ZoneBeliefFilter
    state: EpisodeState
    effect: EpisodeEffect
    authorization: TraversalAuthorization
    before: ZoneBeliefState


def _target(*, aliases: bool = False, interaction: bool = False) -> _Target:
    """Produce real physical evidence and its accepted selected authorization."""
    mapping = _pair_map(aliases=aliases, interaction=interaction)
    build = build_physical_nodes(mapping)
    assert not build.errors
    episodes = PhysicalEpisodes(build.nodes)
    selected = SelectedPaths(mapping, build.nodes, 1)
    if not interaction:
        origin = episodes.observe(SensorInput("binary_sensor.a", "on", _at(0)))
        origin_effect, = origin.effects
        assert selected.observe(origin_effect, origin.state, episodes.states) is None
    episodes.advance(_at(1))
    before_states = episodes.states
    update = episodes.observe(SensorInput(
        "event.b" if interaction else "binary_sensor.b",
        "pressed" if interaction else "on", _at(1),
    ))
    effect, = update.effects
    authorization = selected.observe(
        effect, update.state, episodes.states, before=before_states,
    )
    assert authorization is not None and authorization.reason == "selected_path"
    profile = BELIEF_PROFILES[update.state.profile_name]
    filter_ = ZoneBeliefFilter("b", profile, _at(0))
    before = filter_.advance(effect.at)
    if interaction:
        assert effect.kind == "interaction" and update.state.status == "clearing"
        filter_.apply_interaction(effect.episode_id, effect.at)
        assert filter_.state.log_odds == 30.0
        assert authorization.selected_source_episode_ids == ()
    else:
        assert effect.kind == "positive" and update.state.status == "asserted"
        filter_.apply_positive(effect.episode_id, effect.at)
        filter_.apply_arrival_transition(effect.episode_id, effect.at)
        assert authorization.selected_source_episode_ids
    threshold = POLICY_CALIBRATIONS[profile.profile_id].on_threshold
    assert filter_.state.probability >= threshold
    assert ZoneBeliefFilter.restore(profile, filter_.state).state == filter_.state
    return _Target(
        episodes, selected, filter_, update.state, effect, authorization, before,
    )


def _evaluate_target(policy: ZonePolicy, target: _Target) -> PolicyUpdate:
    return policy.evaluate(
        target.effect.at, target.before, target.filter.state,
        local_state=target.state, local_effect=target.effect,
        authorization=target.authorization,
    )


def _acquired(target: _Target) -> ZonePolicy:
    policy = ZonePolicy("b", POLICY_CALIBRATIONS[target.state.profile_name], _at(0))
    evidence = target.filter.state
    update = _evaluate_target(policy, target)
    assert update.state.active and update.state.activation_provenance == "evidence"
    assert update.event is not None and update.event.kind == "acquired"
    assert update.decision.reason == "acquired"
    assert target.filter.state == evidence
    return policy


@pytest.mark.parametrize("reset", (False, True), ids=("bootstrap", "count-zero"))
def test_displacement_without_generation_preserves_empty_baseline(reset: bool) -> None:
    target = _target()
    profile = BELIEF_PROFILES[target.state.profile_name]
    filter_ = target.filter if reset else ZoneBeliefFilter("b", profile, _at(0))
    if reset:
        filter_.apply_empty_baseline(_at(2))
    before = filter_.state
    control = ZoneBeliefFilter.restore(profile, before)

    displaced = filter_.displace_path(_at(10))

    assert displaced == control.advance(_at(10))
    assert displaced.probability == pytest.approx(profile.prior_probability)
    assert displaced.generation_episode_id is None
    assert displaced.path_displaced_at is None
    assert displaced.qualified_departure_at is None
    assert displaced.contributions == ()
    assert displaced.physical_hold is False
    assert filter_.displace_path(_at(10)) == displaced
    restored = ZoneBeliefFilter.restore(profile, displaced)
    assert restored.advance(_at(20)) == filter_.advance(_at(20))


def test_displacement_rejects_pre_generation_and_preserves_first_frontier() -> None:
    target = _target()
    filter_ = target.filter
    profile = BELIEF_PROFILES[target.state.profile_name]
    before = filter_.state
    physical_before = target.episodes.states
    control = ZoneBeliefFilter.restore(profile, before)

    with pytest.raises(ValueError, match="^Path displacement precedes its generation$"):
        filter_.displace_path(target.effect.at - _US)

    assert filter_.state == before == control.state
    assert target.episodes.states == physical_before
    first = filter_.displace_path(target.effect.at)
    assert first == replace(before, path_displaced_at=target.effect.at)
    assert first.log_odds == before.log_odds
    assert first.contributions == before.contributions
    assert filter_.displace_path(target.effect.at) == first
    restored = ZoneBeliefFilter.restore(profile, first)
    repeated = filter_.displace_path(_at(20))
    assert repeated == restored.advance(_at(20))
    assert repeated.path_displaced_at == target.effect.at
    assert repeated.probability < first.probability
    assert target.episodes.states == physical_before


def _crossing(filter_: ZoneBeliefFilter, start: ZoneBeliefState) -> datetime:
    """Independent exponential oracle, plus tight first-crossing bracketing."""
    profile = BELIEF_PROFILES[start.profile_name]
    calibration = profile.cleared_with_outward
    threshold = POLICY_CALIBRATIONS[start.profile_name].off_threshold
    assert start.path_displaced_at is not None and not start.physical_hold
    assert calibration.baseline_probability < threshold < start.probability
    seconds = calibration.time_constant.total_seconds() * math.log(
        (start.probability - calibration.baseline_probability)
        / (threshold - calibration.baseline_probability)
    )
    analytic = start.last_updated_at + timedelta(seconds=seconds)
    untouched = filter_.state
    end = start.last_updated_at + timedelta(minutes=5)
    crossed = filter_.threshold_crossed_at(start, threshold, end)
    assert crossed is not None and abs(crossed - analytic) <= _US
    before = ZoneBeliefFilter.restore(profile, start).advance(crossed - _US)
    exact = ZoneBeliefFilter.restore(profile, start).advance(crossed)
    assert before.probability > threshold >= exact.probability
    assert filter_.threshold_crossed_at(start, threshold, crossed - _US) is None
    assert filter_.threshold_crossed_at(start, threshold, crossed) == crossed
    assert filter_.threshold_crossed_at(exact, threshold, end) == crossed
    assert filter_.state == untouched
    return crossed


def _elapsed_policy(
    policy: ZonePolicy, filter_: ZoneBeliefFilter, at: datetime, crossing: datetime,
) -> PolicyUpdate:
    before = filter_.state
    after = filter_.advance(at)
    update = policy.evaluate(
        at, before, after, local_state=None, local_effect=None,
        authorization=None, below_threshold_since=crossing,
    )
    assert filter_.state == after  # Policy cannot rewrite the scalar evidence.
    return update


def test_displaced_scalar_crossing_requires_full_dwell() -> None:
    target = _target()
    policy = _acquired(target)
    physical_before = target.episodes.states
    start = target.filter.displace_path(_at(2))
    crossing = _crossing(target.filter, start)
    profile = BELIEF_PROFILES[start.profile_name]
    assert _crossing(ZoneBeliefFilter.restore(profile, start), start) == crossing
    assert start.context == "asserted"
    assert start.asserted_episode_id == target.effect.episode_id

    pending = _elapsed_policy(policy, target.filter, crossing, crossing)
    assert pending.state.active and pending.event is None
    assert pending.decision.reason == "release_pending"
    assert pending.state.pending_release_since == crossing
    calibration = POLICY_CALIBRATIONS[start.profile_name]
    restored_filter = ZoneBeliefFilter.restore(profile, target.filter.state)
    restored_policy = ZonePolicy("b", calibration, crossing, state=policy.state)
    deadline = crossing + calibration.release_dwell
    for at in (deadline - _US, deadline, deadline + _US):
        update = _elapsed_policy(policy, target.filter, at, crossing)
        restored = _elapsed_policy(restored_policy, restored_filter, at, crossing)
        assert update == restored
        if at < deadline:
            assert update.state.active and update.event is None
            assert update.state.pending_release_since == crossing
        elif at == deadline:
            assert not update.state.active
            assert update.state.pending_release_since is None
            assert update.event is not None and update.event.kind == "released"
            assert update.event.event_at == deadline
            assert update.decision.reason == "released"
        else:
            assert not update.state.active and update.event is None
    assert target.episodes.states == physical_before


def test_qualified_reacquisition_cancels_displaced_release() -> None:
    target = _target()
    policy = _acquired(target)
    start = target.filter.displace_path(_at(2))
    crossing = _crossing(target.filter, start)
    pending = _elapsed_policy(policy, target.filter, crossing, crossing)
    assert pending.state.pending_release_since == crossing
    calibration = POLICY_CALIBRATIONS[start.profile_name]
    old_deadline = crossing + calibration.release_dwell
    at = crossing + timedelta(seconds=10)
    profile = BELIEF_PROFILES[start.profile_name]
    restored_filter = ZoneBeliefFilter.restore(profile, target.filter.state)
    restored_policy = ZonePolicy("b", calibration, crossing, state=policy.state)

    # Genuine availability loss and recovery create a new physical generation;
    # no synthetic OFF or hand-edited episode is needed for this component test.
    target.episodes.advance(at)
    target.episodes.observe(SensorInput("binary_sensor.b", "unavailable", at))
    target.selected.reconcile(target.episodes.states, at)
    before_states = target.episodes.states
    fresh = target.episodes.observe(SensorInput("binary_sensor.b", "on", at))
    effect, = fresh.effects
    assert effect.kind == "positive" and effect.episode_id != target.effect.episode_id
    authorization = target.selected.observe(
        effect, fresh.state, target.episodes.states, before=before_states,
    )
    assert authorization is not None and authorization.authorized
    outcomes: list[PolicyUpdate] = []
    for filter_, projection in (
        (target.filter, policy), (restored_filter, restored_policy),
    ):
        before = filter_.advance(at)
        filter_.apply_unavailable(at)
        filter_.apply_positive(effect.episode_id, at)
        filter_.apply_arrival_transition(effect.episode_id, at)
        unassigned = filter_.state
        assert unassigned.path_displaced_at == at
        rebound = filter_.restore_path(at)
        assert rebound == replace(unassigned, path_displaced_at=None)
        assert filter_.restore_path(at) == rebound
        update = projection.evaluate(
            at, before, rebound, local_state=fresh.state, local_effect=effect,
            authorization=authorization,
        )
        assert update.state.active and update.state.pending_release_since is None
        assert update.event is not None and update.event.kind == "refreshed"
        assert update.event.episode_id == effect.episode_id
        duplicate = projection.evaluate(
            at, rebound, rebound, local_state=fresh.state, local_effect=effect,
            authorization=authorization,
        )
        assert duplicate.event is None and duplicate.state == update.state
        assert filter_.state == rebound
        outcomes.append(update)
    assert outcomes[0] == outcomes[1]
    continued = _elapsed_policy(policy, target.filter, old_deadline, crossing)
    restored = _elapsed_policy(restored_policy, restored_filter, old_deadline, crossing)
    assert continued == restored
    assert continued.state.active and continued.state.pending_release_since is None
    assert continued.event is None


@pytest.mark.parametrize("mismatch", ("missing", "older-generation", "later-alias"))
def test_selected_policy_rejects_wrong_physical_frontier(mismatch: str) -> None:
    target = _target(aliases=True)
    accepted = _acquired(target)
    assert accepted.state.activation_source_episode_ids == (
        target.authorization.selected_source_episode_ids
    )
    candidate: EpisodeState | None
    if mismatch == "missing":
        candidate = None
    elif mismatch == "older-generation":
        # Another real observation, deliberately supplied to the wrong operation.
        mapping = _pair_map(aliases=True)
        build = build_physical_nodes(mapping)
        older = PhysicalEpisodes(build.nodes)
        candidate = older.observe(SensorInput("binary_sensor.b", "on", _at(0))).state
        assert candidate.started_at != target.effect.at
    else:
        alias = target.episodes.observe(
            SensorInput("binary_sensor.b_alias", "on", _at(2)),
        )
        candidate = alias.state
        assert not alias.effects and candidate.episode_id == target.state.episode_id
        assert candidate.started_at == target.effect.at
        assert candidate.last_event_at == _at(2)
    physical_before = target.episodes.states
    evidence = target.filter.state
    original = deepcopy((target.authorization, candidate, target.effect))
    policy = ZonePolicy("b", POLICY_CALIBRATIONS[target.state.profile_name], _at(0))
    assert not policy._authorization_valid(
        target.effect.at, candidate, target.authorization,
    )
    rejected = policy.evaluate(
        target.effect.at, target.before, evidence,
        local_state=candidate, local_effect=target.effect,
        authorization=target.authorization,
    )
    assert not rejected.state.active and rejected.state.phase == "inactive"
    assert rejected.state.refresh_dedup == () and rejected.event is None
    assert rejected.decision.reason == "acquisition_unauthorized"
    if mismatch == "later-alias":
        # The generic trust gate accepts this same generation: the selected
        # last-event guard, not an unrelated setup rejection, keeps it OFF.
        assert rejected.decision.local_trustworthy
    assert (target.authorization, candidate, target.effect) == original
    assert target.filter.state == evidence and target.episodes.states == physical_before
    continuation = _evaluate_target(policy, target)
    assert continuation.state == accepted.state
    assert continuation.event is not None and continuation.event.kind == "acquired"


def test_source_free_selected_authority_requires_interaction_state() -> None:
    interaction = _target(interaction=True)
    legitimate = _acquired(interaction)
    assert legitimate.state.activation_source_episode_ids == ()
    ordinary = _target()
    # This is a valid record shape, not a forged sensor state. Only the policy
    # consumer has the physical kind needed to reject the unsupported singleton.
    singleton = replace(
        interaction.authorization,
        target_episode_id=ordinary.effect.episode_id,
        authorized_at=ordinary.effect.at,
    )
    assert singleton.path_node_ids == (ordinary.state.node_id,)
    assert singleton.selected_source_episode_ids == ()
    assert singleton.target_node_id == ordinary.state.node_id
    assert singleton.target_zone == ordinary.state.zone
    assert singleton.target_episode_id == ordinary.state.episode_id
    evidence = ordinary.filter.state
    physical_before = ordinary.episodes.states
    policy = ZonePolicy("b", POLICY_CALIBRATIONS[ordinary.state.profile_name], _at(0))
    assert not policy._authorization_valid(
        ordinary.effect.at, ordinary.state, singleton,
    )
    rejected = policy.evaluate(
        ordinary.effect.at, ordinary.before, evidence, local_state=ordinary.state,
        local_effect=ordinary.effect, authorization=singleton,
    )
    assert rejected.decision.local_trustworthy
    assert rejected.decision.reason == "acquisition_unauthorized"
    assert not rejected.state.active and rejected.event is None
    assert ordinary.filter.state == evidence
    assert ordinary.episodes.states == physical_before
    accepted = _evaluate_target(policy, ordinary)
    assert accepted.state.active and accepted.event is not None
    assert accepted.event.kind == "acquired"


def _support_state(tracker: AnonymousSupportTracker) -> _SupportState:
    return (
        tracker.supports, tracker.bindings, tracker.latest_transition, tracker.counters,
    )


@pytest.mark.parametrize("correlated", (False, True), ids=("ordinary", "correlated"))
def test_support_prepare_requires_live_target_atomically(correlated: bool) -> None:
    proposal = handoff_proposal(correlated=correlated)
    tracker, effect, authorization, token, episodes, beliefs, retained = proposal
    before = _support_state(tracker)
    inputs = deepcopy((effect, authorization, token, episodes, beliefs, retained))
    valid = tracker.prepare(
        effect.at, effect, authorization, token, episodes, beliefs, (token,), retained,
    )
    assert _support_state(tracker) == before
    assert len(valid.transition.supports) == 1
    assert valid.transition.supports[0].current_episode_id == effect.episode_id

    with pytest.raises(
        ValueError, match="^Support application requires its live target token$",
    ):
        tracker.prepare(
            effect.at, effect, authorization, token, episodes, beliefs, (), retained,
        )

    assert _support_state(tracker) == before
    assert (effect, authorization, token, episodes, beliefs, retained) == inputs
    committed = tracker.commit_prepared(valid)
    assert committed == valid.transition
    support, = tracker.supports
    assert support.support_id == before[0][0].support_id
    assert support.current_node_id == effect.node_id
    binding = SupportTokenBinding(token.token_id, support.support_id)
    assert tracker.bindings == (binding,)
    assert tracker.counters["support_transferred"] == 1
    assert tracker.counters["support_created"] == 0


@pytest.mark.parametrize("correlated", (False, True), ids=("ordinary", "correlated"))
@pytest.mark.parametrize("missing", ("effect", "token", "both"))
def test_settled_handoff_requires_effect_and_token_atomically(
    correlated: bool, missing: str,
) -> None:
    proposal = handoff_proposal(correlated=correlated)
    tracker, effect, authorization, token, episodes, beliefs, retained = proposal
    assert authorization.settled_handoff is not None
    before = _support_state(tracker)
    inputs = deepcopy((effect, authorization, token, episodes, beliefs, retained))
    valid = tracker.prepare(
        effect.at, effect, authorization, token, episodes, beliefs, (token,), retained,
    )
    assert _support_state(tracker) == before

    with pytest.raises(
        ValueError, match="^Settled transfer requires a target effect/token$",
    ):
        tracker.prepare(
            effect.at, None if missing in {"effect", "both"} else effect,
            authorization, None if missing in {"token", "both"} else token,
            episodes, beliefs, (token,), retained,
        )

    assert _support_state(tracker) == before
    assert (effect, authorization, token, episodes, beliefs, retained) == inputs
    committed = tracker.commit_prepared(valid)
    assert committed == valid.transition
    support, = tracker.supports
    assert support.support_id == before[0][0].support_id
    assert support.current_episode_id == effect.episode_id
    binding = SupportTokenBinding(token.token_id, support.support_id)
    assert tracker.bindings == (binding,)
    assert tracker.counters["support_transferred"] == 1
    after = _support_state(tracker)
    with pytest.raises(
        ValueError, match="^Prepared support update is stale or already committed$",
    ):
        tracker.commit_prepared(valid)
    assert _support_state(tracker) == after


def _support_components() -> PersistenceComponents:
    mapping = PredictiveMap.from_mapping({"nodes": {
        "a": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.a"}, "adjacent": ["b"],
        },
        "b": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.b"}, "adjacent": ["a", "c"],
        },
        "c": {
            "role": "room_occupancy", "occupancy_behavior": "sustained",
            "entities": {"mmwave": "binary_sensor.c"}, "adjacent": ["b", "d"],
        },
        "d": {
            "role": "transition_gate", "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.d"}, "adjacent": ["c"],
        },
    }})
    owners = PersistenceComponents(mapping, 1, _NOW)
    for seconds, node in enumerate(("a", "b", "c")):
        owners.observe(SensorInput(f"binary_sensor.{node}", "on", _at(seconds)))
    support, = owners.supports.supports
    assert support.state == "settled" and support.current_node_id == "c"
    assert support.path_node_ids == ("a", "b", "c")
    assert support.valid_until is None
    assert owners.supports.counters["support_created"] == 1
    return owners


@pytest.mark.parametrize("level", ("unknown", "unavailable"))
def test_moving_support_requires_current_target_token(level: str) -> None:
    owners = _support_components()
    control = _support_components()
    settled, = owners.supports.supports
    for components in (owners, control):
        result = components.observe(SensorInput("binary_sensor.d", "on", _at(3)))
        authorization, = result.authorizations
        assert authorization.authorized
        assert authorization.path_node_ids == ("b", "c", "d")
        moving, = components.supports.supports
        assert moving.support_id == settled.support_id and moving.state == "moving"
        assert moving.current_node_id == "d" and moving.updated_at == _at(3)
    moving, = owners.supports.supports
    assert moving.valid_until is not None and moving.valid_until > _at(4)
    current = next(token for token in owners.frontier.tokens if token.node_id == "d")
    assert current.episode_id == moving.current_episode_id
    assert current.accepted_at == moving.updated_at
    assert current.valid_until == moving.valid_until
    binding = SupportTokenBinding(current.token_id, moving.support_id)
    assert binding in owners.supports.bindings

    control.advance(_at(4))
    assert control.supports.supports == (moving,)
    assert control.supports.count_supports()[0].endpoint_zone == "d"
    count_before = owners.count.state
    owners.observe(SensorInput("binary_sensor.d", level, _at(4)))
    assert all(token.node_id != "d" for token in owners.frontier.tokens)
    assert owners.supports.supports == () and owners.supports.bindings == ()
    assert owners.supports.count_supports() == ()
    assert owners.supports.latest_transition == SupportTransitionEvent(
        moving.support_id, _at(4), "removed", "missing_target_token",
    )
    assert owners.count.state == count_before
    assert owners.supports.counters["support_created"] == 1
    assert owners.supports.counters["support_transferred"] == 1
    owners.observe(SensorInput("binary_sensor.d", "on", _at(5)))
    assert owners.supports.supports == () and owners.supports.count_supports() == ()

    # Inverse: an authentic settled endpoint needs no live token or high scalar.
    retained = _support_components()
    retained.observe(SensorInput("binary_sensor.c", "off", _at(3)))
    retained.advance(_at(7200))
    assert retained.frontier.tokens == ()
    threshold = POLICY_CALIBRATIONS["stay_presence"].off_threshold
    assert retained.filters["c"].state.probability < threshold
    assert retained.supports.supports == (settled,)
    reacquired = retained.observe(SensorInput("binary_sensor.c", "on", _at(7201)))
    assert any(
        a.reason == "settled_endpoint_reacquired" for a in reacquired.authorizations
    )
    rebound, = retained.supports.supports
    assert rebound.support_id == settled.support_id and rebound.state == "settled"
    assert rebound.current_episode_id != settled.current_episode_id
    assert rebound.updated_at == _at(7201) and rebound.valid_until is None
    assert retained.supports.counters["support_created"] == 1
