"""Synthetic PATH006 integration and retained TRAV021 component guarantees.

All122 original IDs/matrices retained; pre-edit and final guarantee mappings live
in docs/spec/completion-gap-mapping.md. The57 passing selector tests are unchanged.
Current observations reject unseen-middle target212, but ordinary target evidence
may seed a fresh independent next213 pair. Legacy gap target-only authority,
budgets and historical provenance are separately qualified on real components.
No captured incident, engine legacy mode, or selected-path reconstruction.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import persistence
from custom_components.predictive_controls.zone_model import (
    supported_gap_acquisition as gap_module,
)
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    _target_map_fingerprint_payload,
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.profiles import SHARED_PROFILES
from custom_components.predictive_controls.zone_model.supported_gap_acquisition import (
    gap_geometry_valid,
    original_handoff_valid,
    select_supported_gap_source,
)
from custom_components.predictive_controls.zone_model.types import (
    AuthorizationUse,
    CountInput,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    SupportTokenBinding,
    TraversalAuthorization,
    TraversalToken,
)
from custom_components.predictive_controls.zone_model.validation import (
    SnapshotValidator,
)
from tests.gap_component_fixture import (
    GapComponents,
    gap_source_components,
    gap_target_components,
)
from tests.gap_lifecycle_fixture import (
    before_component_gap,
    component_gap,
    prepare_gap_target,
    select_component_gap,
    watch_support_transaction,
)
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    decode_component_snapshot,
    restore_components,
)

pytestmark = pytest.mark.target_model
NOW = datetime(2026, 9, 1, tzinfo=UTC)
REASON = "supported_gap_acquisition"


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def gap_map(
    timings: dict[str, dict[str, float]] | None = None,
    *,
    alternate: bool = False,
) -> PredictiveMap:
    adjacency = {
        "seed": ["bridge"], "bridge": ["seed", "stay"],
        "stay": ["bridge", "source"], "source": ["stay", "middle"],
        "middle": ["source", "target"], "target": ["middle", "next"],
        "next": ["target"],
    }
    if alternate:
        adjacency["z_middle"] = ["source", "target"]
        adjacency["source"].append("z_middle")
        adjacency["target"].append("z_middle")
    return PredictiveMap.from_mapping({"nodes": {
        node: {
            "role": "anchor_sensor" if node in {"stay", "target", "next"}
            else "transition_gate",
            "occupancy_behavior": "sticky" if node in {"stay", "target", "next"}
            else "transient",
            "entities": {"mmwave": f"binary_sensor.{node}"},
            "adjacent": neighbors,
            "transition_seconds": (timings or {}).get(node, {}),
        }
        for node, neighbors in adjacency.items()
    }})


def before_gap(
    *, count: int = 2, correlated: bool = False,
    predictive_map: PredictiveMap | None = None,
) -> ZoneModelEngine:
    """Original0..200 observations, now qualified against actual selected authority."""

    engine = ZoneModelEngine(predictive_map or gap_map(), count, NOW)
    for seconds, node, state in (
        (0, "seed", "on"), (1, "bridge", "on"), (2, "stay", "on"),
        (10, "seed", "off"), (11, "bridge", "off"),
    ):
        engine.observe(SensorInput(f"binary_sensor.{node}", state, at(seconds)))
    if correlated:
        engine.observe(SensorInput("binary_sensor.target", "on", at(160)))
        engine.observe(SensorInput("binary_sensor.target", "off", at(161)))
    result = engine.observe(SensorInput("binary_sensor.source", "on", at(200)))
    authorization, = result.authorizations
    assert authorization.reason == "selected_path" and authorization.authorized
    assert authorization.path_node_ids[-2:] == ("stay", "source")
    assert not engine.snapshot.anonymous_supports
    assert not engine.snapshot.traversal_tokens
    assert len(engine.snapshot.selected_paths) == count
    path, = (p for p in engine.snapshot.selected_paths if p is not None)
    assert path.visits[-1].node_id == "source"
    assert not any(
        p.active for p in engine.snapshot.policy_states if p.zone == "target"
    )
    engine.commit_prediction_learning()
    return engine


def select(
    engine: ZoneModelEngine | GapComponents,
    target: EpisodeState, effect: EpisodeEffect,
    **overrides: Any,
) -> TraversalToken | None:
    inputs: dict[str, Any] = {
        "predictive_map": engine._map,
        "nodes": {node.node_id: node for node in engine._nodes},
        "target": target, "effect": effect, "count": engine.snapshot.count_state,
        "tokens": engine.snapshot.traversal_tokens,
        "episodes": engine.snapshot.episode_states,
        "supports": engine.snapshot.anonymous_supports,
        "bindings": engine.snapshot.support_token_bindings,
    }
    inputs.update(overrides)
    return select_supported_gap_source(**inputs)


def historical_gap_policy_payload(
    current: dict[str, object], historical: dict[str, object], *, audit: bool = True,
) -> dict[str, object]:
    """Compatible structural composite, not a claim of selected gap reachability.

    Only the real component target policy and its sourced audit row are donated.
    Every current physical/selection/health/hold/count/prediction field is intact.
    """
    composite = deepcopy(current)
    legacy = persistence._mapping(historical["snapshot"], "component")
    target = next(
        entry for entry in persistence._list(legacy, "policy_states")
        if persistence._mapping(entry, "policy")["zone"] == "target"
    )
    snapshot = dict(persistence._mapping(composite["snapshot"], "snapshot"))
    snapshot["policy_states"] = [
        target if persistence._mapping(entry, "policy")["zone"] == "target"
        else entry for entry in persistence._list(snapshot, "policy_states")
    ]
    composite["snapshot"] = snapshot
    composite["audit"] = sorted(
        [*persistence._list(composite, "audit"), *(
            entry for entry in persistence._list(historical, "audit")
            if persistence._mapping(entry, "audit")["traversal_reason"] == REASON
        )],
        key=lambda entry: persistence._decode_policy_decision(entry).event_at,
    ) if audit else []
    return composite


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("correlated", (False, True))
def test_gap_runtime_target_only_and_no_chaining(count: int, correlated: bool) -> None:
    """PATH006 rejects the jump, not a later independently supported ordinary pair."""
    engine = before_gap(count=count, correlated=correlated)
    engine.advance(at(212))
    before = engine.snapshot
    prediction = deepcopy(engine.prediction_manager.serialize())
    counters = engine.diagnostic_counters
    result = engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    authorization, = result.authorizations
    assert not authorization.authorized
    assert authorization.reason == (
        "untracked_rejected" if correlated else "track_bootstrap_pending"
    )
    assert not authorization.source_tokens and not authorization.new_uses
    assert not authorization.path_node_ids and authorization.provenance_kind is None
    assert not result.policy_events
    assert not next(
        p for p in result.snapshot.policy_states if p.zone == "target"
    ).active
    assert result.snapshot.selected_paths == before.selected_paths
    assert result.snapshot.traversal_tokens == before.traversal_tokens == ()
    assert result.snapshot.retained_traversal_tokens == before.retained_traversal_tokens
    assert result.snapshot.anonymous_supports == before.anonymous_supports == ()
    assert result.snapshot.support_token_bindings == before.support_token_bindings
    assert result.snapshot.authorization_uses == before.authorization_uses
    assert engine.diagnostic_counters == counters
    assert not engine._pending_prediction_learning
    assert engine.prediction_manager.serialize()["counts"] == prediction["counts"]
    assert not result.snapshot.selected_prediction_grants
    warning, = result.snapshot.reliability_warning_occurrences
    assert (warning.node_id, warning.kind, warning.reason) == (
        "target", "unsupported_jump", "unsupported_jump",
    )
    assert warning.first_observed_at == warning.last_observed_at == at(212)
    assert warning.cleared_at is None
    target_source = next(s for s in result.snapshot.selected_sources
                         if s.node_id == "target")
    assert target_source.origin == ("correlated" if correlated else "ordinary")
    repeated = engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    assert repeated.disposition == "duplicate" and not repeated.policy_events
    assert repeated.snapshot == result.snapshot
    next_result = engine.observe(SensorInput("binary_sensor.next", "on", at(213)))
    leading, = next_result.authorizations
    assert leading.authorized is not correlated
    assert [(e.zone, e.kind) for e in next_result.policy_events] == (
        [] if correlated else [("next", "acquired")]
    )
    assert not next(p for p in next_result.snapshot.policy_states
                    if p.zone == "target").active
    if not correlated:
        assert leading.reason == "selected_path"
        assert leading.path_node_ids == ("target", "next")
        assert leading.selected_source_episode_ids == (authorization.target_episode_id,)
    else:
        assert next_result.snapshot.selected_paths == before.selected_paths
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize()["counts"] == prediction["counts"]


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("correlated", (False, True))
def test_legacy_gap_target_only_and_no_chaining(count: int, correlated: bool) -> None:
    """Original positive oracle at the authentic, nonselected component boundary."""
    components = before_component_gap(
        gap_map(), NOW, count=count, correlated=correlated,
    )
    components.advance(at(212))
    before = components.snapshot
    prediction = deepcopy(components.prediction_manager.serialize())
    counters = components.diagnostic_counters
    result = component_gap(
        components, SensorInput("binary_sensor.target", "on", at(212)),
    )
    authorization, = result.authorizations
    assert authorization.reason == authorization.provenance_kind == REASON
    assert authorization.path_node_ids == ("target",)
    assert authorization.track_confidence == "provisional"
    assert not authorization.equivalent_confirmed_strength
    source, = authorization.source_tokens
    assert source.node_id == "source"
    assert authorization.new_uses == (
        AuthorizationUse(
            source.token_id, authorization.target_episode_id, REASON, at(212)
        ),
    )
    assert [(event.zone, event.kind) for event in result.policy_events] == [
        ("target", "acquired")
    ]
    belief = next(b for b in result.snapshot.belief_states if b.zone == "target")
    assert belief.probability >= .75
    assert result.snapshot.traversal_tokens == before.traversal_tokens
    assert result.snapshot.retained_traversal_tokens == before.retained_traversal_tokens
    assert result.snapshot.anonymous_supports == before.anonymous_supports
    assert result.snapshot.support_token_bindings == before.support_token_bindings
    assert components.diagnostic_counters == counters
    assert all(c.node_id != "target" for c in result.snapshot.pending_candidates)
    assert tuple(
        b for b in result.snapshot.belief_states if b.zone != "target"
    ) == tuple(
        b for b in before.belief_states if b.zone != "target"
    )
    assert not components.learning
    assert components.prediction_manager.serialize() == prediction
    repeated = components.observe(SensorInput("binary_sensor.target", "on", at(212)))
    assert repeated.disposition == "duplicate" and not repeated.policy_events
    assert components.snapshot.authorization_uses == result.snapshot.authorization_uses
    next_result = components.observe(SensorInput("binary_sensor.next", "on", at(213)))
    assert not next_result.authorizations[0].authorized
    assert not any(e.zone == "next" for e in next_result.policy_events)


@pytest.mark.parametrize("correlated", (False, True))
def test_gap_no_support_apply_arguments_even_for_exact_endpoint(
    correlated: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = before_gap(correlated=correlated)
    engine.advance(at(212))
    before = engine.snapshot
    calls, prepared, committed = watch_support_transaction(
        engine._supports, monkeypatch,
    )
    result = engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    assert not result.authorizations[0].authorized
    assert len(calls) == len(prepared) == len(committed) == 1
    assert prepared[0] is committed[0]
    effect, authorization, token = calls[0]
    assert token is None
    if correlated:
        assert effect is None and authorization is None
    else:
        assert effect is not None and effect.kind == "positive"
        assert authorization == result.authorizations[0]
    assert result.snapshot.anonymous_supports == before.anonymous_supports
    assert result.snapshot.support_token_bindings == before.support_token_bindings

    # The real legacy target-only transaction must neutralize even ordinary
    # positive input; test the called prepare/commit methods, never unused apply.
    components = before_component_gap(gap_map(), NOW, correlated=correlated)
    components.advance(at(212))
    baseline = components.snapshot
    inputs, proposals, commits = watch_support_transaction(
        components.supports, monkeypatch,
    )
    legacy = component_gap(
        components, SensorInput("binary_sensor.target", "on", at(212)),
    )
    assert legacy.authorizations[0].reason == REASON
    assert inputs == [(None, None, None)]
    assert len(proposals) == len(commits) == 1 and proposals[0] is commits[0]
    assert legacy.snapshot.anonymous_supports == baseline.anonymous_supports
    assert legacy.snapshot.support_token_bindings == baseline.support_token_bindings


def test_gap_neutral_prepare_cannot_rebind_actual_settled_target() -> None:
    """Qualify the dangerous exact-endpoint branch independently of the spy."""
    components = PersistenceComponents(gap_map(), 2, NOW)
    for seconds, node, state in (
        (0, "source", "on"), (1, "middle", "on"),
        (2, "target", "on"), (3, "target", "off"),
    ):
        components.observe(SensorInput(f"binary_sensor.{node}", state, at(seconds)))
    components.advance(at(1000), emit_events=False)
    old, = components.supports.supports
    assert old.state == "settled" and old.current_node_id == "target"
    assert old.path_node_ids == ("source", "middle", "target")
    update = components.episodes.observe(
        SensorInput("binary_sensor.target", "on", at(1000)),
    )
    effect, = update.effects
    assert effect.kind == "positive" and effect.episode_id != old.current_episode_id
    components.filters["target"].apply_positive(
        effect.episode_id, effect.at, effect.reliability,
    )
    components.filters["target"].apply_arrival_transition(effect.episode_id, effect.at)
    before = components.snapshot
    dangerous = components.supports.prepare(
        effect.at, effect, None, None, components.episodes.states,
        components.beliefs, components.frontier.tokens,
        components.frontier.retained_tokens,
    )
    rebound, = dangerous.transition.supports
    assert rebound.current_episode_id == effect.episode_id
    assert rebound.updated_at == effect.at and rebound.support_id == old.support_id
    assert rebound != old
    neutral = components.supports.prepare(
        effect.at, None, None, None, components.episodes.states,
        components.beliefs, components.frontier.tokens,
        components.frontier.retained_tokens,
    )
    assert neutral.transition.supports == (old,)
    assert components.snapshot == before  # preparation is detached
    components.supports.commit_prepared(neutral)
    assert components.snapshot == before


@pytest.mark.parametrize("correlated", (False, True))
def test_gap_callback_failure_commits_without_learning(correlated: bool) -> None:
    engine = before_gap(correlated=correlated)
    engine.advance(at(212))
    rejected_callbacks: list[PolicyEvent] = []

    def unexpected(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        rejected_callbacks.append(event)
        pytest.fail("rejected gap invoked an acquisition callback")

    rejected = engine.observe(
        SensorInput("binary_sensor.target", "on", at(212)),
        decision_callback=unexpected,
    )
    assert not rejected.authorizations[0].authorized
    assert not rejected.policy_events and not rejected_callbacks

    # Independent positive: a genuinely observed middle211 makes target212
    # adjacent, for both ordinary and correlated target evidence.
    accepted = before_gap(correlated=correlated)
    accepted.observe(SensorInput("binary_sensor.middle", "on", at(211)))
    counts = deepcopy(accepted.prediction_manager.serialize()["counts"])
    callbacks: list[PolicyEvent] = []

    def fail(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "target" and decision.active_after
        assert authorization is not None and authorization.reason == "selected_path"
        assert authorization.path_node_ids[-2:] == ("middle", "target")
        assert next(
            p for p in accepted.snapshot.policy_states if p.zone == "target"
        ).active
        assert not accepted.snapshot.traversal_tokens
        assert not accepted.snapshot.anonymous_supports
        callbacks.append(event)
        raise RuntimeError("synthetic publication failure")

    with pytest.raises(RuntimeError, match="synthetic publication"):
        accepted.observe(
            SensorInput("binary_sensor.target", "on", at(212)), decision_callback=fail
        )
    assert len(callbacks) == 1
    assert next(p for p in accepted.snapshot.policy_states if p.zone == "target").active
    assert not accepted.snapshot.authorization_uses
    assert not accepted._pending_prediction_learning
    assert accepted.prediction_manager.serialize()["counts"] == counts
    restored = restore_target_state(
        accepted._map, serialize_target_state(accepted._map, accepted), at(212)
    )
    assert restored.snapshot == accepted.snapshot
    control = before_gap(correlated=correlated)
    control.observe(SensorInput("binary_sensor.middle", "on", at(211)))
    control.observe(SensorInput("binary_sensor.target", "on", at(212)))
    assert serialize_target_state(control._map, control) == serialize_target_state(
        accepted._map, accepted,
    )
    event = SensorInput("binary_sensor.next", "on", at(213))
    assert restored.observe(event) == accepted.observe(event) == control.observe(event)


@pytest.mark.parametrize("correlated", (False, True))
def test_legacy_gap_callback_failure_commits_use_without_learning(
    correlated: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Original callback-exception guarantee, separately from selected adjacency."""
    components = before_component_gap(gap_map(), NOW, correlated=correlated)
    components.advance(at(212))
    before = components.snapshot
    prediction = deepcopy(components.prediction_manager.serialize())
    inputs, proposals, commits = watch_support_transaction(
        components.supports, monkeypatch,
    )
    calls: list[PolicyEvent] = []

    def fail(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        assert event.zone == "target" and event.kind == "acquired"
        assert decision.active_after
        assert authorization is not None and authorization.reason == REASON
        assert components.snapshot.traversal_tokens == before.traversal_tokens
        assert components.snapshot.anonymous_supports == before.anonymous_supports
        assert not commits and len(proposals) == 1
        calls.append(event)
        raise RuntimeError("synthetic publication failure")

    with pytest.raises(RuntimeError, match="^synthetic publication failure$"):
        component_gap(
            components, SensorInput("binary_sensor.target", "on", at(212)),
            decision_callback=fail,
        )
    assert len(calls) == 1 and inputs == [(None, None, None)]
    assert len(commits) == 1 and commits[0] is proposals[0]
    assert components.policies["target"].state.active
    assert components.snapshot.traversal_tokens == before.traversal_tokens
    assert components.snapshot.anonymous_supports == before.anonymous_supports
    assert components.snapshot.support_token_bindings == before.support_token_bindings
    assert len(components.snapshot.authorization_uses) == (
        len(before.authorization_uses) + 1
    )
    assert not components.learning
    assert components.prediction_manager.serialize() == prediction
    restored = restore_components(
        components.predictive_map,
        component_wire(components.predictive_map, components), at(212),
    )
    assert restored.snapshot == components.snapshot
    control = before_component_gap(gap_map(), NOW, correlated=correlated)
    control.advance(at(212))
    component_gap(control, SensorInput("binary_sensor.target", "on", at(212)))
    assert component_wire(control.predictive_map, control) == component_wire(
        components.predictive_map, components,
    )
    event = SensorInput("binary_sensor.target", "off", at(213))
    assert restored.observe(event) == components.observe(event) == control.observe(
        event,
    )


@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize(
    "restore_second", (200, 212, 229.999999, 230, 244.999999, 245, 260)
)
def test_gap_restore_roundtrip(
    count: int, correlated: bool, restore_second: float,
) -> None:
    engine = before_gap(count=count, correlated=correlated)
    if restore_second == 200:
        restored = restore_target_state(
            engine._map, serialize_target_state(engine._map, engine), at(200)
        )
        event = SensorInput("binary_sensor.target", "on", at(212))
        assert restored.observe(event) == engine.observe(event)
    else:
        engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
        payload = serialize_target_state(engine._map, engine)
        restored = restore_target_state(engine._map, payload, at(restore_second))
        if restore_second > 212:
            engine.advance(at(restore_second), emit_events=False)
        assert restored.snapshot == engine.snapshot
    payload = serialize_target_state(engine._map, engine)
    assert serialize_target_state(engine._map, restored) == payload
    payload["audit"] = []  # Historical policy must stand without retained audit.
    restored_without_audit = restore_target_state(
        engine._map, payload, engine.snapshot.updated_at
    )
    assert restored_without_audit.snapshot == engine.snapshot
    assert not next(
        p for p in engine.snapshot.policy_states if p.zone == "target"
    ).active
    warning, = engine.snapshot.reliability_warning_occurrences
    assert warning.reason == "unsupported_jump" and warning.cleared_at is None
    assert warning.first_observed_at == warning.last_observed_at == at(212)
    assert len(engine.snapshot.selected_paths) == count
    path, = (p for p in engine.snapshot.selected_paths if p is not None)
    assert path.visits[-1].node_id == "source"
    assert not engine.snapshot.authorization_uses
    assert not engine.snapshot.traversal_tokens

    # Retain the historical positive lifetime at every original frontier too.
    # Source expires245/use260, but actual target policy remains independently
    # valid with no retained audit. None of these records grant current movement.
    components = before_component_gap(
        engine._map, NOW, count=count, correlated=correlated,
    )
    target_event = SensorInput("binary_sensor.target", "on", at(212))
    if restore_second == 200:
        legacy_restored = restore_components(
            engine._map, component_wire(engine._map, components), at(200),
        )
        assert component_gap(legacy_restored, target_event) == component_gap(
            components, target_event,
        )
    else:
        component_gap(components, target_event)
        legacy_restored = restore_components(
            engine._map, component_wire(engine._map, components), at(restore_second),
        )
        if restore_second > 212:
            components.advance(at(restore_second), emit_events=False)
    legacy_payload = component_wire(engine._map, components)
    assert component_wire(engine._map, legacy_restored) == legacy_payload
    legacy_payload["audit"] = []
    legacy_no_audit = restore_components(
        engine._map, legacy_payload, components.updated_at,
    )
    assert legacy_no_audit.snapshot == legacy_restored.snapshot == components.snapshot
    historical_policy = components.policies["target"].state
    assert historical_policy.active and historical_policy.activation_reason == REASON
    assert historical_policy.activation_at == at(212)
    assert bool(components.frontier.tokens) is (restore_second < 245)
    assert bool(components.supports.supports) is (restore_second < 245)
    assert bool(components.frontier.uses) is (restore_second < 260)
    for retain_audit in (True, False):
        composite = historical_gap_policy_payload(
            payload, component_wire(engine._map, components), audit=retain_audit,
        )
        frozen = deepcopy(composite)
        historical = restore_target_state(
            engine._map, composite, engine.snapshot.updated_at,
        )
        assert historical.snapshot == replace(
            engine.snapshot, policy_states=tuple(
                historical_policy if p.zone == "target" else p
                for p in engine.snapshot.policy_states
            ),
        )
        assert composite == frozen
    continuation_at = at(max(212, restore_second) + 1)
    legacy_event = SensorInput("binary_sensor.target", "off", continuation_at)
    assert components.observe(legacy_event) == legacy_restored.observe(
        legacy_event,
    ) == legacy_no_audit.observe(legacy_event)
    # Beyond legacy230/245 expiries, no fabricated movement or warning time.
    event = SensorInput("binary_sensor.next", "on", at(max(212, restore_second) + 1))
    continued = engine.observe(event)
    assert restored.observe(event) == restored_without_audit.observe(event) == continued
    assert continued.authorizations[0].authorized is not correlated
    assert not next(
        p for p in continued.snapshot.policy_states if p.zone == "target"
    ).active


def test_gap_isolated_count_zero_does_not_enter_acquisition() -> None:
    engine = before_gap()
    engine.observe_count(CountInput("empty", 0, True, at(210)))
    result = engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    assert not result.authorizations and not result.policy_events
    assert not result.snapshot.traversal_tokens
    assert not result.snapshot.anonymous_supports
    assert not result.snapshot.authorization_uses
    assert all(not p.active for p in result.snapshot.policy_states)
    basis, target, effect = gap_target_components(gap_map(), NOW)
    assert select(basis, target, effect, count=CountState(0)) is None
    assert not any(result.snapshot.selected_paths)
    assert not result.snapshot.reliability_warning_occurrences


@pytest.mark.parametrize(("timings", "age", "expected"), (
    ({}, -1, False), ({}, 0, False), ({}, .000001, True),
    ({}, 29.999999, True), ({}, 30, False), ({}, 31, False),
    ({"source": {"middle": 4}, "middle": {"target": 6}}, 9.999999, True),
    ({"source": {"middle": 4}, "middle": {"target": 6}}, 10, False),
    ({"source": {"middle": 1}}, 15.999999, True),
    ({"source": {"middle": 1}}, 16, False),
    ({"source": {"middle": 100}, "middle": {"target": 100}}, 29.999999, True),
    ({"source": {"middle": 100}, "middle": {"target": 100}}, 30, False),
    ({"middle": {"source": 1}, "target": {"middle": 1}}, 12, True),
))
def test_gap_directed_timing_and_half_open_budget(
    timings: dict[str, dict[str, float]], age: float, expected: bool,
) -> None:
    engine = gap_source_components(gap_map(timings), NOW)
    assert gap_geometry_valid(
        engine._map, {n.node_id: n for n in engine._nodes},
        "source", "target", at(200), at(200 + age),
    ) is expected


def test_gap_all_routes_not_first_bfs_hit() -> None:
    predictive_map = gap_map(
        {"source": {"middle": 1}, "middle": {"target": 1}}, alternate=True
    )
    engine, target, effect = gap_target_components(predictive_map, NOW)
    assert select(engine, target, effect) is not None


@pytest.mark.parametrize("field", (
    "tokens", "bindings", "supports", "health", "cadence", "clear", "raw_off",
    "wrong_episode", "wrong_zone", "wrong_start", "wrong_deadline",
    "reopened", "confirmed", "nonequivalent", "provenance", "path",
    "support_endpoint", "support_episode", "support_path", "support_provenance",
    "support_update", "support_deadline", "support_settled",
))
def test_gap_source_and_binding_fail_closed(field: str) -> None:
    engine, target, effect = gap_target_components(gap_map(), NOW)
    source, = engine.snapshot.traversal_tokens
    source_state = next(
        e for e in engine.snapshot.episode_states if e.node_id == "source"
    )
    support, = engine.snapshot.anonymous_supports
    overrides: dict[str, Any] = {}
    if field in {"tokens", "bindings", "supports"}:
        overrides[field] = ()
    elif field in {
        "health", "cadence", "clear", "raw_off", "wrong_episode", "wrong_zone",
        "wrong_start", "wrong_deadline",
    }:
        changes = cast(dict[str, Any], {
            "health": {"health_warning": True},
            "cadence": {
                "cadence_warning": True, "cadence_warning_reason": "impossible_cadence"
            },
            "clear": {"status": "clearing"},
            "raw_off": {"alias_states": (("binary_sensor.source", "off"),)},
            "wrong_episode": {"episode_id": "different"},
            "wrong_zone": {"zone": "stay"},
            "wrong_start": {"started_at": at(201)},
            "wrong_deadline": {"traversal_valid_until": at(244)},
        }[field])
        overrides["episodes"] = tuple(
            replace(e, **changes) if e == source_state else e
            for e in engine.snapshot.episode_states
        )
    elif field.startswith("support_"):
        changes = cast(dict[str, Any], {
            "support_endpoint": {"current_node_id": "stay"},
            "support_episode": {"current_episode_id": "different"},
            "support_path": {"path_node_ids": ("source",)},
            "support_provenance": {"provenance_kind": "adjacent"},
            "support_update": {"updated_at": at(201)},
            "support_deadline": {"valid_until": at(244)},
            "support_settled": {"state": "settled", "valid_until": None},
        }[field])
        if field == "support_endpoint":
            changes["path_node_ids"] = ("stay",)
        overrides["supports"] = (replace(support, **changes),)
    else:
        changes = cast(dict[str, Any], {
            "reopened": {"continuity_reopened_at": at(210)},
            "confirmed": {"track_confidence": "confirmed"},
            "nonequivalent": {"equivalent_confirmed_strength": False},
            "provenance": {"provenance_kind": "adjacent"},
            "path": {"path_node_ids": ("seed", "source")},
        }[field])
        overrides["tokens"] = (replace(source, **changes),)
    assert select(engine, target, effect, **overrides) is None


@pytest.mark.parametrize("field", (
    "health", "cadence", "raw_off", "started", "expired", "wrong_effect", "interaction",
))
def test_gap_target_eligibility(field: str) -> None:
    engine, target, effect = gap_target_components(gap_map(), NOW)
    if field == "interaction":
        nodes = {n.node_id: n for n in engine._nodes}
        nodes["target"] = replace(
            nodes["target"], interaction_aliases=nodes["target"].aliases
        )
        assert select(engine, target, effect, nodes=nodes) is None
        return
    if field == "wrong_effect":
        effect = replace(effect, kind="correlated_flap_ignored")
    else:
        changes = cast(dict[str, Any], {
            "health": {"health_warning": True},
            "cadence": {
                "cadence_warning": True, "cadence_warning_reason": "impossible_cadence"
            },
            "raw_off": {"alias_states": (("binary_sensor.target", "off"),)},
            "started": {"started_at": at(211)},
            "expired": {"traversal_valid_until": at(212)},
        }[field])
        target = replace(target, **changes)
    assert select(engine, target, effect) is None


def test_gap_ambiguity_is_sources_not_routes() -> None:
    engine, target, effect = gap_target_components(gap_map(alternate=True), NOW)
    source, = engine.snapshot.traversal_tokens
    assert select(engine, target, effect, tokens=(source, source)) == source
    # Independent synthetic component origin, not a cloned engine-owned support.
    nodes = {n.node_id: n for n in engine._nodes}
    mapping: dict[str, Any] = {"nodes": {
        node_id: {
            "role": n.role, "entities": n.entities, "adjacent": list(n.adjacent),
            "occupancy_behavior": engine._map.occupancy_behavior_for_node(n),
        }
        for node_id, n in engine._map.nodes.items()
    }}
    mapping["nodes"]["other"] = {
        "role": "transition_gate", "entities": {"mmwave": "binary_sensor.other"},
        "adjacent": ["other_stay", "middle"], "occupancy_behavior": "transient",
    }
    mapping["nodes"]["other_stay"] = {
        "role": "anchor_sensor", "entities": {"mmwave": "binary_sensor.other_stay"},
        "adjacent": ["bridge", "other"], "occupancy_behavior": "sticky",
    }
    mapping["nodes"]["bridge"]["adjacent"].append("other_stay")
    mapping["nodes"]["middle"]["adjacent"].append("other")
    predictive_map = PredictiveMap.from_mapping(mapping)
    other = gap_source_components(
        predictive_map, at(-1), source_id="other", stay_id="other_stay",
    )
    second, = other.snapshot.traversal_tokens
    nodes = {n.node_id: n for n in other._nodes}
    other_state = next(
        s for s in other.snapshot.episode_states if s.node_id == "other"
    )
    other_origin = next(
        s for s in other.snapshot.episode_states if s.node_id == "other_stay"
    )
    support, = engine.snapshot.anonymous_supports
    other_support, = other.snapshot.anonymous_supports
    overrides = {
        "predictive_map": predictive_map, "nodes": nodes,
        "episodes": (*engine.snapshot.episode_states, other_state, other_origin),
        "supports": (support, other_support),
        "bindings": (
            *engine.snapshot.support_token_bindings,
            SupportTokenBinding(second.token_id, other_support.support_id),
        ),
    }
    assert select(engine, target, effect, tokens=(second,), **overrides) == second
    assert select(engine, target, effect, tokens=(source, second), **overrides) is None


@pytest.mark.parametrize("historical", (False, True))
def test_gap_original_expiry_independent_of_thirty_second_cap(historical: bool) -> None:
    engine = gap_source_components(gap_map(), NOW)
    source, = engine.snapshot.traversal_tokens
    nodes = {n.node_id: n for n in engine._nodes}
    assert original_handoff_valid(
        engine._map, nodes, source, at(244.999999), historical=historical
    )
    assert not original_handoff_valid(
        engine._map, nodes, source, at(245), historical=historical
    )
    assert not original_handoff_valid(
        engine._map, nodes, replace(source, valid_until=at(246)), at(212),
        historical=historical,
    )


def test_gap_ordinary_missed_edge_excludes_only_handoff_provenance() -> None:
    components = before_component_gap(gap_map({
        "source": {"middle": 15}, "middle": {"target": 15},
    }), NOW)
    _, target, effect, qualified = prepare_gap_target(
        components, SensorInput("binary_sensor.target", "on", at(212)),
    )
    assert qualified.authorized and qualified.reason == REASON
    source, = components.snapshot.traversal_tokens
    assert not components.frontier._missed_edge(source, "target", effect.at, None)
    provisional = replace(
        source, provenance_kind="adjacent", equivalent_confirmed_strength=False
    )
    assert components.frontier._missed_edge(provisional, "target", effect.at, None)
    # Explicit timing cannot bypass missing support in the component late fallback.
    components.supports.clear(effect.at, "synthetic_missing_support")
    authorization = components.frontier.authorize(
        target, effect.at, count=CountState(2),
        gap_resolver=lambda: select_component_gap(components, target, effect),
    )
    assert not authorization.authorized


def test_gap_token_issuer_rejects_target_only_authority() -> None:
    components = before_component_gap(gap_map(), NOW)
    _, target, effect, authorization = prepare_gap_target(
        components, SensorInput("binary_sensor.target", "on", at(212)),
    )
    assert authorization.authorized and authorization.reason == REASON
    before = components.snapshot
    with pytest.raises(ValueError, match="authorized current positive"):
        components.frontier.issue(target, effect, authorization)
    assert components.snapshot == before


@pytest.mark.parametrize("change", (
    {"track_confidence": "confirmed"}, {"equivalent_confirmed_strength": True},
    {"path_node_ids": ("source", "target")}, {"source_tokens": ()},
    {"authorized": False}, {"provenance_kind": "adjacent"},
    {"reason": "adjacent_authorized"},
))
def test_gap_authorization_shape_is_strict(change: dict[str, Any]) -> None:
    components = before_component_gap(gap_map(), NOW)
    authorization, = component_gap(
        components,
        SensorInput("binary_sensor.target", "on", at(212))
    ).authorizations
    assert authorization.authorized and authorization.reason == REASON
    assert replace(authorization) == authorization
    with pytest.raises(ValueError, match="Supported-gap"):
        replace(authorization, **change)


@pytest.mark.parametrize("field", (
    "policy_source", "policy_path", "policy_confidence", "policy_provenance",
    "use_time", "use_target", "use_source_provenance", "use_reopened_before",
    "audit_source", "audit_time", "audit_count", "token_provenance",
    "support_provenance",
))
def test_gap_malformed_restore_rejects_atomically(field: str) -> None:
    """Original mutation reaches its actual predicate after an accepted baseline.

Policy uses an accepted current structural composite: only the authentic legacy
target policy is substituted, never selected history, holds, health or grants.
Use/token predicates are the extracted production validator; audit is the actual
engine audit predicate. No absent selected envelope can mask a deeper mutation.
"""
    components = before_component_gap(gap_map(), NOW)
    component_gap(components, SensorInput("binary_sensor.target", "on", at(212)))
    original = component_wire(components.predictive_map, components)
    pristine = restore_components(components.predictive_map, original, at(212))
    assert pristine.snapshot == components.snapshot
    engine = before_gap()
    engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    current_before = serialize_target_state(engine._map, engine)
    current_control = restore_target_state(engine._map, current_before, at(212))
    validator = SnapshotValidator(
        components.predictive_map, components.nodes,
        components.supports._confirmed_strength,
    )
    validator.validate(components.snapshot)

    def validate(document: dict[str, object]) -> None:
        frozen = deepcopy(document)
        decoded = decode_component_snapshot(document["snapshot"])
        if field.startswith("policy_"):
            # Actual raw selected history remains intact and passes the entire
            # strict reader BEFORE we ask it to reject a historical policy field.
            composite = historical_gap_policy_payload(current_before, document)
            frozen_composite = deepcopy(composite)
            try:
                restored = restore_target_state(engine._map, composite, at(212))
                legacy_policy = next(
                    p for p in decoded.policy_states if p.zone == "target"
                )
                assert restored.snapshot == replace(
                    engine.snapshot, policy_states=tuple(
                        legacy_policy if p.zone == "target" else p
                        for p in engine.snapshot.policy_states
                    ),
                )
            finally:
                assert composite == frozen_composite
        elif field.startswith("audit_"):
            audit_row = next(
                persistence._decode_policy_decision(entry)
                for entry in persistence._list(document, "audit")
                if persistence._mapping(entry, "audit")["traversal_reason"] == REASON
            )
            engine._validate_interaction_audit(
                audit_row, {state.node_id: state for state in decoded.episode_states},
                decoded.updated_at,
            )
        elif field.startswith("use_"):
            validator.validate_current_pending_uses(
                decoded, {item.token_id: item for item in decoded.traversal_tokens},
                {item.token_id: item for item in decoded.retained_traversal_tokens},
            )
        elif field == "token_provenance":
            validator.validate_tokens(decoded)
        else:
            # The strict record codec already rejects the unsupported gap
            # provenance. A separate valid-shape inverse below reaches crosslinks.
            active, retained = validator.validate_tokens(decoded)
            validator.validate_support_snapshot(decoded, active, retained)
        assert document == frozen

    validate(original)
    payload: Any = deepcopy(original)
    snapshot = payload["snapshot"]
    policy = next(p for p in snapshot["policy_states"] if p["zone"] == "target")
    use = next(u for u in snapshot["authorization_uses"] if u["reason"] == REASON)
    token, = snapshot["traversal_tokens"]
    row = next(r for r in payload["audit"] if r["traversal_reason"] == REASON)
    if field == "policy_source":
        policy["activation_source_episode_ids"] = []
    elif field == "policy_path":
        policy["activation_path_node_ids"] = ["source", "target"]
    elif field == "policy_confidence":
        policy["activation_track_confidence"] = "confirmed"
    elif field == "policy_provenance":
        policy["activation_provenance_kind"] = "missed_edge"
    elif field == "use_time":
        use["authorized_at"] = at(211).isoformat()
    elif field == "use_target":
        use["target_episode_id"] = token["episode_id"]
    elif field == "use_source_provenance":
        token["provenance_kind"] = "adjacent"
        token["equivalent_confirmed_strength"] = False
    elif field == "use_reopened_before":
        token["continuity_reopened_at"] = at(211).isoformat()
        token["valid_until"] = at(256).isoformat()
        snapshot["anonymous_supports"] = []
        snapshot["support_token_bindings"] = []
    elif field == "audit_source":
        row["evidence_ids"] = [row["episode_id"]]
    elif field == "audit_time":
        row["event_at"] = at(211).isoformat()
    elif field == "audit_count":
        row["count_zero"] = True
    elif field == "token_provenance":
        token["provenance_kind"] = REASON
    else:
        snapshot["anonymous_supports"][0]["provenance_kind"] = REASON
    policy_error = "Evidence-active policy is not bound to its acquisition episode"
    expected_errors = {
        "policy_source": policy_error,
        "policy_path": policy_error,
        "policy_confidence": policy_error,
        "policy_provenance": policy_error,
        "use_time": "Traversal use predates its target episode",
        "use_target": "Supported-gap use lacks original bounded authority",
        "use_source_provenance": "Supported-gap use lacks original bounded authority",
        "use_reopened_before": "Supported-gap use lacks original bounded authority",
        "audit_source": "Supported-gap audit identity is incomplete",
        "audit_time": "Supported-gap audit is not episode-derived",
        "audit_count": "Supported-gap audit identity is incomplete",
        "token_provenance": "Traversal token provenance is incompatible",
        "support_provenance": "Anonymous-support provenance is invalid",
    }
    frozen_payload = deepcopy(payload)
    with pytest.raises(ValueError, match=f"^{expected_errors[field]}$"):
        validate(payload)
    assert payload == frozen_payload
    assert component_wire(components.predictive_map, components) == original
    assert serialize_target_state(engine._map, engine) == current_before
    validate(original)
    event = SensorInput("binary_sensor.target", "off", at(213))
    assert components.observe(event) == pristine.observe(event)
    assert engine.observe(event) == current_control.observe(event)


def test_gap_support_provenance_crosslink_has_independent_valid_shape_control() -> None:
    """Record rejection must not replace the deeper target-binding guarantee."""
    components = before_component_gap(gap_map(), NOW)
    component_gap(components, SensorInput("binary_sensor.target", "on", at(212)))
    validator = SnapshotValidator(
        components.predictive_map, components.nodes,
        components.supports._confirmed_strength,
    )
    snapshot = components.snapshot
    active, retained = validator.validate_tokens(snapshot)
    validator.validate_support_snapshot(snapshot, active, retained)
    support, = snapshot.anonymous_supports
    # Adjacent is independently valid on a two-node transferred support, but
    # contradicts its handoff-provenance target token, unlike invalid REASON.
    malformed = replace(snapshot, anonymous_supports=(
        replace(support, provenance_kind="adjacent"),
    ))
    with pytest.raises(
        ValueError, match="^Anonymous-support target binding is incompatible$",
    ):
        validator.validate_support_snapshot(malformed, active, retained)
    assert components.snapshot == snapshot
    validator.validate_support_snapshot(snapshot, active, retained)


def test_gap_later_reopening_preserves_historical_use() -> None:
    components = before_component_gap(gap_map(), NOW)
    component_gap(components, SensorInput("binary_sensor.target", "on", at(212)))
    components.observe(SensorInput("binary_sensor.source", "off", at(243)))
    components.observe(SensorInput("binary_sensor.source", "on", at(246)))
    source, = components.snapshot.traversal_tokens
    assert source.continuity_reopened_at == at(246)
    assert any(use.reason == REASON for use in components.snapshot.authorization_uses)
    original_use, = (
        u for u in components.snapshot.authorization_uses if u.reason == REASON
    )
    assert original_use.authorized_at == at(212)
    component_payload = component_wire(components.predictive_map, components)
    component_restored = restore_components(
        components.predictive_map, component_payload, at(246),
    )
    assert component_restored.snapshot == components.snapshot
    assert component_restored.observe(
        SensorInput("binary_sensor.target", "off", at(247)),
    ) == components.observe(SensorInput("binary_sensor.target", "off", at(247)))

    # Same physical stream under PATH006: no invented historical gap use.
    engine = before_gap()
    engine.observe(SensorInput("binary_sensor.target", "on", at(212)))
    engine.observe(SensorInput("binary_sensor.source", "off", at(243)))
    engine.observe(SensorInput("binary_sensor.source", "on", at(246)))
    assert not engine.snapshot.traversal_tokens
    assert not engine.snapshot.authorization_uses
    assert not next(
        p for p in engine.snapshot.policy_states if p.zone == "target"
    ).active
    payload = serialize_target_state(engine._map, engine)
    restored = restore_target_state(engine._map, payload, at(246))
    assert restored.snapshot == engine.snapshot
    event = SensorInput("binary_sensor.next", "on", at(247))
    continued = engine.observe(event)
    assert restored.observe(event) == continued
    assert [(e.zone, e.kind) for e in continued.policy_events] == [("next", "acquired")]
    assert not any(
        use.reason == REASON for use in continued.snapshot.authorization_uses
    )


def test_gap_fingerprint_current_only_rejects_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = before_gap()
    current = _target_map_fingerprint_payload(engine._map)
    assert type(current["supported_gap_acquisition_version"]) is int
    assert current.pop("supported_gap_acquisition_version") == 1
    historical = _target_map_fingerprint_payload(engine._map, pre_feature=True)
    assert "supported_gap_acquisition_version" not in historical
    payload = serialize_target_state(engine._map, engine)
    accepted = restore_target_state(engine._map, payload, at(200))
    assert accepted.snapshot == engine.snapshot
    valid_payload = deepcopy(payload)
    payload["map_fingerprint"] = hashlib.sha256(
        json.dumps(current, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    def fail_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("incompatible inference reached decoding")

    # Parent-package reload must not redirect the decoder interception.
    monkeypatch.setattr(persistence, "_decode_snapshot", fail_decode)
    with pytest.raises(ValueError, match="fingerprint"):
        restore_target_state(engine._map, payload, at(200))
    with pytest.raises(
        pytest.fail.Exception, match="^incompatible inference reached decoding$",
    ):
        restore_target_state(engine._map, valid_payload, at(200))


@pytest.mark.parametrize("case", (
    "adjacent", "same_zone", "three_edges", "disconnected", "missing_node",
    "stay_middle", "interaction_middle", "interaction_source", "stay_source",
))
def test_gap_geography_and_roles_fail_closed(case: str) -> None:
    engine = gap_source_components(gap_map(), NOW)
    nodes = {node.node_id: node for node in engine._nodes}
    source_id, target_id = "source", "target"
    if case == "adjacent":
        target_id = "middle"
    elif case == "same_zone":
        nodes["target"] = replace(nodes["target"], zone="source")
    elif case == "three_edges":
        target_id = "next"
    elif case == "disconnected":
        target_id = "seed"
    elif case == "missing_node":
        target_id = "absent"
    elif case == "stay_middle":
        nodes["middle"] = replace(nodes["middle"], profile_name="stay_pir")
    elif case in {"interaction_middle", "interaction_source"}:
        node_id = "middle" if case == "interaction_middle" else "source"
        nodes[node_id] = replace(
            nodes[node_id], interaction_aliases=nodes[node_id].aliases
        )
    else:
        nodes["source"] = replace(nodes["source"], profile_name="stay_pir")
    assert not gap_geometry_valid(
        engine._map, nodes, source_id, target_id, at(200), at(212)
    )


@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize("seconds,expected", ((229.999999, True), (230, False)))
def test_gap_runtime_budget_boundary(
    correlated: bool, seconds: float, expected: bool,
) -> None:
    engine = before_gap(correlated=correlated, predictive_map=gap_map({
        "source": {"middle": 100}, "middle": {"target": 100},
    }))
    result = engine.observe(SensorInput("binary_sensor.target", "on", at(seconds)))
    authorization, = result.authorizations
    assert not authorization.authorized and authorization.reason != REASON
    assert not result.policy_events
    assert not next(
        p for p in result.snapshot.policy_states if p.zone == "target"
    ).active
    warning, = result.snapshot.reliability_warning_occurrences
    assert warning.reason == "unsupported_jump"
    assert warning.first_observed_at == warning.last_observed_at == at(seconds)
    assert warning.cleared_at is None
    components = before_component_gap(engine._map, NOW, correlated=correlated)
    legacy = component_gap(
        components, SensorInput("binary_sensor.target", "on", at(seconds)),
    )
    bounded, = legacy.authorizations
    assert bounded.authorized is expected
    assert (bounded.reason == REASON) is expected
    assert [(e.zone, e.kind) for e in legacy.policy_events] == (
        [("target", "acquired")] if expected else []
    )


def test_gap_original_expiry_with_shortened_shared_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the original-token boundary below the independent 30-second cap.
    profile = SHARED_PROFILES["transition_fast"]
    engine = gap_source_components(gap_map(), NOW)
    # Shared profiles are immutable; replace only this helper's module reference,
    # not global runtime calibration or the real handoff fixture.
    monkeypatch.setattr(
        gap_module, "SHARED_PROFILES",
        {**SHARED_PROFILES, "transition_fast": replace(
            profile, traversal_context_window=timedelta(seconds=10)
        )},
    )
    nodes = {n.node_id: n for n in engine._nodes}
    assert gap_geometry_valid(
        engine._map, nodes, "source", "target", at(200), at(209.999999)
    )
    assert not gap_geometry_valid(
        engine._map, nodes, "source", "target", at(200), at(210)
    )

