"""Explicit legacy component transactions; never a selected-engine simulator.

REQ-TRAV-018/COUNT-011 qualify prepare -> policy callback -> support commit ->
count at the component boundary. PersistenceComponents.observe deliberately has
different scheduling. These narrow steps use its actual components, with no
engine inheritance, private engine aliases, selection switches or reader bypass.
"""

from __future__ import annotations

from dataclasses import dataclass

from custom_components.predictive_controls.zone_model.supports import (
    PreparedSupportUpdate,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
)
from tests.persistence_component_fixture import DecisionCallback, PersistenceComponents


@dataclass(frozen=True)
class PreparedArrival:
    """Operation-local component proof, not persisted or production authority."""

    disposition: str
    state: EpisodeState
    effect: EpisodeEffect
    authorization: TraversalAuthorization
    support: PreparedSupportUpdate


def prepare_component_arrival(
    components: PersistenceComponents, event: SensorInput,
) -> PreparedArrival:
    """Advance actual deadlines, then prepare one fresh physical target."""
    assert event.state in {"on", "pressed"}
    assert event.event_at >= components.updated_at
    components.advance(event.event_at, emit_events=False)
    update = components.episodes.observe(event)
    effect, = update.effects
    assert effect.kind in {"positive", "correlated_positive", "interaction"}
    state = update.state
    belief = components.filters[state.zone]
    if effect.kind == "interaction":
        belief.apply_interaction(effect.episode_id, effect.at)
        authorization = components.frontier.authorize_interaction(state, effect.at)
    else:
        if effect.kind == "correlated_positive":
            belief.apply_correlated_positive(
                effect.episode_id, effect.at, effect.reliability,
            )
            authorization = components.frontier.authorize_correlated_target(
                state, effect.at,
                settled_support=components.supports.settled_endpoint_for(state),
                handoff_resolver=lambda: components.supports.settled_adjacent_for(
                    state, effect, components.episodes.states, components.beliefs,
                ),
            )
        else:
            belief.apply_positive(effect.episode_id, effect.at, effect.reliability)
            authorization = components.frontier.authorize(
                state, effect.at, count=components.count.state,
                corroborating_states=components.episodes.states,
                settled_support=components.supports.settled_endpoint_for(state),
                handoff_resolver=lambda: components.supports.settled_adjacent_for(
                    state, effect, components.episodes.states, components.beliefs,
                ),
            )
        if authorization.authorized:
            belief.apply_arrival_transition(effect.episode_id, effect.at)
    token = None
    if authorization.authorized:
        if effect.kind != "correlated_positive":
            token = components.frontier.issue(state, effect, authorization)
        elif (
            components.supports.has_transfer_authority(authorization)
            or authorization.settled_handoff is not None
        ):
            token = components.frontier.issue_correlated_continuation(
                state, effect, authorization, support_backed=True,
            )
    if effect.kind == "positive" and authorization.settled_handoff is None:
        TraversalFrontier.apply_outward_context(
            authorization, components.filters, effect.at, state.traversal_valid_until,
        )
    components.frontier.sync(state, effect.at)
    if authorization.settled_handoff is not None:
        # Settled source identity survives origin eviction. Prune actual dangling
        # bindings before preparation; do not erase a moving source's frozen basis.
        components.supports.advance(
            effect.at, components.episodes.states, components.beliefs,
            components.frontier.tokens, components.frontier.retained_tokens,
        )
    prepared = components.supports.prepare(
        effect.at, effect, authorization, token, components.episodes.states,
        components.beliefs, components.frontier.tokens,
        components.frontier.retained_tokens,
    )
    return PreparedArrival(update.disposition, state, effect, authorization, prepared)


def publish_component_arrival(
    components: PersistenceComponents, prepared: PreparedArrival,
    callback: DecisionCallback | None = None,
) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...], Exception | None]:
    """Real policies see prospective support; callback sees uncommitted support."""
    failure: Exception | None = None

    def capture(
        event: PolicyEvent, decision: PolicyDecision,
        authorization: TraversalAuthorization | None,
    ) -> None:
        nonlocal failure
        if callback is not None and failure is None:
            try:
                callback(event, decision, authorization)
            except Exception as exc:
                failure = exc

    decisions: list[PolicyDecision] = []
    events: list[PolicyEvent] = []
    for zone, policy in sorted(components.policies.items()):
        local = zone == prepared.state.zone
        belief = components.filters[zone].state
        result = policy.evaluate(
            prepared.effect.at, belief, belief,
            local_state=prepared.state if local else None,
            local_effect=prepared.effect if local else None,
            authorization=prepared.authorization if local else None,
            pending_candidate=next(
                (item for item in components.frontier.pending_candidates
                 if item.zone == zone), None,
            ),
            retained_endpoint_hold=any(
                item.state == "settled" and item.current_zone == zone
                for item in prepared.support.transition.supports
            ) and belief.qualified_departure_at is None,
            before_audit=capture,
        )
        decisions.append(result.decision)
        if result.event is not None:
            events.append(result.event)
    return tuple(decisions), tuple(events), failure


def commit_component_arrival(
    components: PersistenceComponents, prepared: PreparedArrival,
) -> None:
    """Commit the owner/revision-bound proposal once, then real count evaluation."""
    components.supports.commit_prepared(prepared.support)
    components.evaluate_count_conflicts(prepared.effect.at)
    authorization = prepared.authorization
    if (
        prepared.effect.kind == "positive"
        and authorization.authorized
        and authorization.track_confidence == "confirmed"
        and authorization.provenance_kind == "adjacent"
    ):
        components.prediction_manager.prepare(
            prepared.effect.at, components.count.state.expected_count,
            components.episodes.states, (authorization,),
        )
        components.learning.append(authorization)


def component_arrival(
    components: PersistenceComponents, event: SensorInput, *,
    decision_callback: DecisionCallback | None = None,
) -> ZoneModelResult:
    """Compose the three explicitly named steps for a fresh component arrival."""
    prepared = prepare_component_arrival(components, event)
    decisions, events, failure = publish_component_arrival(
        components, prepared, decision_callback,
    )
    commit_component_arrival(components, prepared)
    result = ZoneModelResult(
        prepared.disposition, components.snapshot, events, decisions,
        (prepared.authorization,),
    )
    if failure is not None:
        raise failure
    return result
