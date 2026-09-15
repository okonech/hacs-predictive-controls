"""Explicit COUNT-009 component transactions, not a legacy engine mode.

The selected engine deliberately never applies count-driven health degradation
(HEALTH-003). These named laboratory steps retain the real conflict tracker,
episode recovery, support, filter and policy calibration in isolation. They reuse
PersistenceComponents; there is no engine subclass, synthetic support/count,
copied validator, selected-path switch, or production scheduling claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneBeliefState,
    ZoneModelResult,
)
from tests.persistence_component_fixture import PersistenceComponents


def reconcile_count_conflicts(
    components: PersistenceComponents, at: datetime, *,
    local_effect: EpisodeEffect | None = None,
    authorization: TraversalAuthorization | None = None,
) -> None:
    """Ask the real tracker, then deliver its diagnoses/recoveries exactly once.

The tracker owns eligibility, support identity, dwell and cancellation. Episodes
own recovery effects at stable clear/unavailability; loss of the original support
set instead needs their explicit recover_count_conflict operation. Preserve the
old conflict for its recovery audit rather than inventing a new support basis.
"""
    assert components.updated_at == at
    previous = components.conflicts.conflicts
    due = components.conflicts.evaluate(
        at, components.count.state.expected_count, components.nodes,
        components.episodes.states, components.supports.count_supports(),
        {zone: POLICY_CALIBRATIONS[belief.state.profile_name].release_dwell
         for zone, belief in components.filters.items()},
        local_effect=local_effect, authorization=authorization,
    )
    for old in previous:
        if old.degraded_at is None:
            continue
        if any(
            current.target_episode_id == old.target_episode_id
            and current.support_ids == old.support_ids
            and current.degraded_at is not None
            for current in components.conflicts.conflicts
        ):
            continue
        state = next(s for s in components.episodes.states
                     if s.node_id == old.target_node_id)
        if state.episode_id != old.target_episode_id:
            continue
        if state.status == "degraded" and state.degradation_reason == "count_conflict":
            recovered = components.episodes.recover_count_conflict(
                state.node_id, old.target_episode_id, at,
            )
            state = recovered.state
            for effect in recovered.effects:
                components._effect(state, effect)  # noqa: SLF001
        if not state.health_warning and state.degradation_reason is None:
            components.policies[state.zone].record_count_conflict(
                old, state, components.filters[state.zone].state,
                result="recovered", at=at, processing_at=at,
            )
    for conflict in due:
        update = components.episodes.apply_count_conflict(
            conflict.target_node_id, conflict.target_episode_id, at,
        )
        for effect in update.effects:
            components._effect(update.state, effect)  # noqa: SLF001
        components.policies[update.state.zone].record_count_conflict(
            conflict, update.state, components.filters[update.state.zone].state,
            result="degraded", at=at, processing_at=at,
        )


def evaluate_count_policies(
    components: PersistenceComponents, at: datetime,
    before: Mapping[str, ZoneBeliefState], *,
    state: EpisodeState | None = None,
    effect: EpisodeEffect | None = None,
    authorization: TraversalAuthorization | None = None,
) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
    """Evaluate real holds/dwell; sparse silence uses the real filter crossing.

Only an unchanged decay context may carry an earlier crossing. A newly cleared
or recovered context starts at its actual frontier, never in protected time.
"""
    decisions: list[PolicyDecision] = []
    events: list[PolicyEvent] = []
    for zone, policy in sorted(components.policies.items()):
        belief = components.filters[zone]
        old, current = before[zone], belief.state
        local = state is not None and state.zone == zone
        unchanged_context = (
            old.context == current.context
            and old.health_warning == current.health_warning
            and old.generation_episode_id == current.generation_episode_id
        )
        crossing = belief.threshold_crossed_at(
            old if unchanged_context else current,
            POLICY_CALIBRATIONS[current.profile_name].off_threshold, at,
        )
        if components.count.state.expected_count == 0:
            update = policy.apply_count_zero(at)
        else:
            update = policy.evaluate(
                at, old, current,
                local_state=state if local else None,
                local_effect=effect if local else None,
                authorization=authorization if local else None,
                below_threshold_since=crossing,
                pending_candidate=next(
                    (item for item in components.frontier.pending_candidates
                     if item.zone == zone), None,
                ),
                retained_endpoint_hold=any(
                    item.state == "settled" and item.current_zone == zone
                    for item in components.supports.supports
                ) and current.qualified_departure_at is None,
                asserted_stay_hold=any(
                    item.zone == zone and (
                        item.degradation_reason == "count_conflict"
                        and item.status in {"degraded", "clearing"}
                        or item.cadence_correlated
                        and item.status in {"asserted", "clearing"}
                    ) for item in components.episodes.states
                ),
            )
        decisions.append(update.decision)
        if update.event is not None:
            events.append(update.event)
    return tuple(decisions), tuple(events)


def advance_count_deadlines(
    components: PersistenceComponents, at: datetime,
) -> None:
    """Advance real effects, never promote a pending origin by polling its ON.

    PersistenceComponents._advance synchronizes *all* physical states, suitable
    for its persistence specimens but not the original count/movement lifecycle.
    Here only actual episode effects sync their node through _effect. An issued
    pending-origin token therefore stays historical until a real observation.
    """
    assert at >= components.updated_at
    due = sorted(
        ((effect, update.state) for update in components.episodes.advance(at)
         for effect in update.effects),
        key=lambda pair: (
            pair[0].at, pair[0].node_id,
            pair[0].kind == "health_recovered", pair[0].kind,
        ),
    )
    for effect, state in due:
        components._effect(state, effect)  # noqa: SLF001
    for belief in components.filters.values():
        belief.advance(at)
    components.frontier.advance(at)
    components.supports.advance(
        at, components.episodes.states, components.beliefs,
        components.frontier.tokens, components.frontier.retained_tokens,
    )
    components.updated_at = at


def advance_count_components(
    components: PersistenceComponents, at: datetime,
) -> ZoneModelResult:
    """Physical deadlines -> support reconciliation -> count -> policy."""
    before = {item.zone: item for item in components.beliefs}
    advance_count_deadlines(components, at)
    reconcile_count_conflicts(components, at)
    decisions, events = evaluate_count_policies(components, at, before)
    return ZoneModelResult("advanced", components.snapshot, events, decisions)


def observe_count_sensor(
    components: PersistenceComponents, event: SensorInput,
) -> ZoneModelResult:
    """Deliver actual effects; due diagnosis precedes same-frontier external OFF.

Unlike the generic persistence laboratory, this explicit count transaction passes
the actual local effect/authorization into conflict cancellation and records
recovery before evaluating holds. It is intentionally limited to these component
tests and does not reproduce the selected engine's publication/prediction paths.
"""
    if event.event_at < components.updated_at:
        return ZoneModelResult("stale", components.snapshot)
    before = {item.zone: item for item in components.beliefs}
    advance_count_deadlines(components, event.event_at)
    if event.state not in {"on", "pressed"}:
        reconcile_count_conflicts(components, event.event_at)
    update = components.episodes.observe(event)
    authorizations: list[TraversalAuthorization] = []
    last_effect = None
    for effect in update.effects:
        authorization, _ = components._effect(update.state, effect)  # noqa: SLF001
        if authorization is not None:
            authorizations.append(authorization)
        last_effect = effect
    if event.state in {"unknown", "unavailable"}:
        components.frontier.sync(update.state, event.event_at, invalidate=True)
        components.filters[update.state.zone].apply_unavailable(event.event_at)
    components.frontier.sync(update.state, event.event_at)
    components.supports.advance(
        event.event_at, components.episodes.states, components.beliefs,
        components.frontier.tokens, components.frontier.retained_tokens,
    )
    authorization = authorizations[-1] if authorizations else None
    reconcile_count_conflicts(
        components, event.event_at,
        local_effect=last_effect, authorization=authorization,
    )
    decisions, events = evaluate_count_policies(
        components, event.event_at, before, state=update.state,
        effect=last_effect, authorization=authorization,
    )
    return ZoneModelResult(
        update.disposition, components.snapshot, events, decisions,
        tuple(authorizations),
    )


def observe_count_control(
    components: PersistenceComponents, event: CountInput,
) -> ZoneModelResult:
    """Real count control/reset, then cancellation under the accepted count."""
    result = components.observe_count(event)
    reconcile_count_conflicts(components, event.event_at)
    return ZoneModelResult(
        result.disposition, components.snapshot,
        result.policy_events, result.policy_decisions,
    )
