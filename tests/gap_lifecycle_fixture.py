"""Standalone TRAV021 transactions, never a legacy ZoneModelEngine mode.

Replay the original synthetic observations through real persistence components.
The only added orchestration is the real frontier's late gap resolver and its
target-only prepare/policy/commit transaction. No copied selection/validation,
invented token, calibration change, or current-engine acceptance is implied.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.supported_gap_acquisition import (
    select_supported_gap_source,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
    PreparedSupportUpdate,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    SupportTransition,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
)
from tests.persistence_component_fixture import (
    DecisionCallback,
    PersistenceComponents,
    component_wire,
    restore_components,
)


def before_component_gap(
    predictive_map: PredictiveMap, origin: datetime, *, count: int = 2,
    correlated: bool = False,
) -> PersistenceComponents:
    """Real three-node settlement and source200 handoff; no inference seeding."""
    components = PersistenceComponents(predictive_map, count, origin)
    events = [
        (0, "seed", "on"), (1, "bridge", "on"), (2, "stay", "on"),
        (10, "seed", "off"), (11, "bridge", "off"),
    ]
    if correlated:
        events.extend(((160, "target", "on"), (161, "target", "off")))
    for seconds, node, state in events:
        components.observe(SensorInput(
            f"binary_sensor.{node}", state, origin + timedelta(seconds=seconds),
        ))
    result = components.observe(SensorInput(
        "binary_sensor.source", "on", origin + timedelta(seconds=200),
    ))
    authorization, = result.authorizations
    assert authorization.reason == "settled_adjacent_transfer"
    source, = components.frontier.tokens
    support, = components.supports.supports
    assert source.node_id == support.current_node_id == "source"
    assert source.valid_until == origin + timedelta(seconds=245)
    assert support.state == "moving" and source.equivalent_confirmed_strength
    components.commit_prediction_learning()
    restored = restore_components(
        predictive_map, component_wire(predictive_map, components),
        components.updated_at,
    )
    assert restored.snapshot == components.snapshot
    return components


def select_component_gap(
    components: PersistenceComponents, target: EpisodeState, effect: EpisodeEffect,
) -> TraversalToken | None:
    snapshot = components.snapshot
    return select_supported_gap_source(
        components.predictive_map, {node.node_id: node for node in components.nodes},
        target, effect, snapshot.count_state, snapshot.traversal_tokens,
        snapshot.episode_states, snapshot.anonymous_supports,
        snapshot.support_token_bindings,
    )


def prepare_gap_target(
    components: PersistenceComponents, event: SensorInput,
) -> tuple[str, EpisodeState, EpisodeEffect, TraversalAuthorization]:
    """Actual local observation and late component authorization, no issuance."""
    components.advance(event.event_at, emit_events=False)
    update = components.episodes.observe(event)
    effect, = update.effects
    assert effect.kind in {"positive", "correlated_positive"}
    belief = components.filters[effect.zone]
    if effect.kind == "positive":
        belief.apply_positive(effect.episode_id, effect.at, effect.reliability)
        authorization = components.frontier.authorize(
            update.state, effect.at, count=components.count.state,
            gap_resolver=lambda: select_component_gap(components, update.state, effect),
        )
    else:
        belief.apply_correlated_positive(
            effect.episode_id, effect.at, effect.reliability,
        )
        authorization = components.frontier.authorize_correlated_target(
            update.state, effect.at,
            gap_resolver=lambda: select_component_gap(components, update.state, effect),
        )
    if authorization.authorized:
        assert authorization.reason == "supported_gap_acquisition"
        belief.apply_arrival_transition(effect.episode_id, effect.at)
    components.frontier.sync(update.state, effect.at)
    return update.disposition, update.state, effect, authorization


def component_gap(
    components: PersistenceComponents, event: SensorInput, *,
    decision_callback: DecisionCallback | None = None,
) -> ZoneModelResult:
    """Explicit target-only component transaction; prediction is not submitted."""
    disposition, state, effect, authorization = prepare_gap_target(components, event)
    prepared = components.supports.prepare(
        effect.at, None, None, None, components.episodes.states,
        components.beliefs, components.frontier.tokens,
        components.frontier.retained_tokens,
    )
    failure: Exception | None = None

    def capture(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        nonlocal failure
        if decision_callback is not None and failure is None:
            try:
                decision_callback(event, decision, authorization)
            except Exception as exc:
                failure = exc

    decisions, events = components._policies(
        effect.at, state=state, effect=effect, authorization=authorization,
        callback=capture,
    )
    components.supports.commit_prepared(prepared)
    if failure is not None:
        raise failure
    return ZoneModelResult(
        disposition, components.snapshot, events, decisions, (authorization,),
    )


SupportInputs = tuple[
    EpisodeEffect | None, TraversalAuthorization | None, TraversalToken | None,
]


def watch_support_transaction(
    tracker: AnonymousSupportTracker, monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    list[SupportInputs], list[PreparedSupportUpdate], list[PreparedSupportUpdate],
]:
    """Spy the real prepare/commit boundary with checked production signatures."""
    original_prepare = tracker.prepare
    original_commit = tracker.commit_prepared
    calls: list[SupportInputs] = []
    prepared_calls: list[PreparedSupportUpdate] = []
    committed: list[PreparedSupportUpdate] = []

    def prepare(
        at: datetime, effect: EpisodeEffect | None,
        authorization: TraversalAuthorization | None,
        issued_target_token: TraversalToken | None,
        episodes: Sequence[EpisodeState], beliefs: Sequence[ZoneBeliefState],
        active_tokens: Sequence[TraversalToken],
        retained_tokens: Sequence[TraversalToken],
        *, prepared_handoff: SupportTransition | None = None,
    ) -> PreparedSupportUpdate:
        calls.append((effect, authorization, issued_target_token))
        proposal = original_prepare(
            at, effect, authorization, issued_target_token, episodes, beliefs,
            active_tokens, retained_tokens, prepared_handoff=prepared_handoff,
        )
        prepared_calls.append(proposal)
        return proposal

    def commit(proposal: PreparedSupportUpdate) -> SupportTransition:
        result = original_commit(proposal)
        committed.append(proposal)
        return result

    monkeypatch.setattr(tracker, "prepare", prepare)
    monkeypatch.setattr(tracker, "commit_prepared", commit)
    return calls, prepared_calls, committed
