"""Explicit component orchestration for historical persistence qualifications.

Not an engine subclass, compatibility mode, historical capture, or current-reader
acceptance fixture. Real episode effects feed real filters/frontier/support/policy
and prediction components. There is deliberately no selection or PathHealth here:
the selected engine and its diagnostic thresholds are qualified separately.
Component JSON uses the production codecs and extracted production cross-link
checks; accepting it does NOT certify a current-engine snapshot.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import datetime

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import persistence
from custom_components.predictive_controls.zone_model.count import (
    CountConflictTracker,
    CountContext,
)
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.policy import (
    POLICY_CALIBRATIONS,
    PolicyAuditLog,
    ZonePolicy,
)
from custom_components.predictive_controls.zone_model.prediction import (
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    EpisodeEffect,
    EpisodeState,
    PolicyDecision,
    PolicyEvent,
    ReliabilityWarningOccurrence,
    SensorInput,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelResult,
    ZoneModelSnapshot,
)
from custom_components.predictive_controls.zone_model.validation import (
    validate_component_snapshot,
)

DecisionCallback = Callable[
    [PolicyEvent, PolicyDecision, TraversalAuthorization | None], None,
]


class PersistenceComponents:
    """Small explicit laboratory for component effects, not production scheduling.

    Cadence tests use one node per zone. The parent can reuse the public component
    attributes to construct support/count/handoff specimens without inheriting or
    altering ZoneModelEngine. This fixture does not promise engine publication
    ordering, multi-witness selection, or prediction-policy execution.
    """

    def __init__(self, predictive_map: PredictiveMap, count: int, at: datetime) -> None:
        build = build_physical_nodes(predictive_map)
        if build.errors:
            raise ValueError("; ".join(build.errors))
        self.predictive_map = predictive_map
        self.nodes = build.nodes
        self.episodes = PhysicalEpisodes(self.nodes)
        self.frontier = TraversalFrontier(predictive_map, self.nodes)
        self.supports = AnonymousSupportTracker(predictive_map, self.nodes)
        self.count = CountContext(count)
        self.conflicts = CountConflictTracker()
        self.filters = {
            node.zone: ZoneBeliefFilter(
                node.zone, BELIEF_PROFILES[node.profile_name], at,
            )
            for node in self.nodes
        }
        self.policies = {
            zone: ZonePolicy(zone, POLICY_CALIBRATIONS[item.state.profile_name], at)
            for zone, item in self.filters.items()
        }
        self.prediction_manager = TargetPredictionManager(predictive_map)
        self.learning: list[TraversalAuthorization] = []
        self.warnings: dict[tuple[str, str], ReliabilityWarningOccurrence] = {}
        self.updated_at = at

    @property
    def beliefs(self) -> tuple[ZoneBeliefState, ...]:
        return tuple(self.filters[zone].state for zone in sorted(self.filters))

    @property
    def snapshot(self) -> ZoneModelSnapshot:
        return ZoneModelSnapshot(
            self.updated_at, self.episodes.states, self.beliefs,
            self.frontier.tokens, self.frontier.current_token_ids, self.frontier.uses,
            self.count.state,
            tuple(self.policies[zone].state for zone in sorted(self.policies)),
            self.frontier.pending_candidates, self.conflicts.conflicts,
            self.frontier.retained_tokens, self.supports.supports,
            self.supports.bindings,
            tuple(self.warnings[key] for key in sorted(self.warnings)),
        )

    @property
    def audit_rows(self) -> tuple[PolicyDecision, ...]:
        return tuple(
            row for zone in sorted(self.policies)
            for row in self.policies[zone].audit.rows
        )

    @property
    def diagnostic_counters(self) -> dict[str, int]:
        return {**self.supports.counters, **self.conflicts.counters}

    def evaluate_count_conflicts(self, at: datetime) -> None:
        """Explicit legacy count laboratory step; never current engine health.

        Call after advancing the real episode/support components to ``at``.
        Evaluation, degradation and audit use their production component APIs.
        This is deliberately not enabled in ordinary cadence orchestration.
        """
        assert at == self.updated_at
        due = self.conflicts.evaluate(
            at, self.count.state.expected_count, self.nodes, self.episodes.states,
            self.supports.count_supports(),
            {zone: POLICY_CALIBRATIONS[item.state.profile_name].release_dwell
             for zone, item in self.filters.items()},
        )
        for conflict in due:
            update = self.episodes.apply_count_conflict(
                conflict.target_node_id, conflict.target_episode_id, at,
            )
            for effect in update.effects:
                self._effect(update.state, effect)
            self.policies[conflict.target_zone].record_count_conflict(
                conflict, update.state, self.filters[conflict.target_zone].state,
                result="degraded", at=at, processing_at=at,
            )

    def commit_prediction_learning(self) -> None:
        self.prediction_manager.commit(tuple(self.learning))
        self.learning.clear()

    def bootstrap_sensor_snapshot(
        self, events: Sequence[SensorInput], at: datetime,
    ) -> ZoneModelSnapshot:
        for event in events:
            update = self.episodes.observe(event)
            for effect in update.effects:
                if effect.kind == "positive" and self.count.state.expected_count:
                    self.filters[effect.zone].apply_positive(
                        effect.episode_id, effect.at, effect.reliability,
                    )
        self.frontier.clear(at)
        self.updated_at = at
        return self.snapshot

    def _warning(self, effect: EpisodeEffect) -> None:
        reason = effect.warning_reason
        assert reason is not None
        key = (effect.node_id, reason)
        old = self.warnings.get(key)
        if effect.kind in {"cadence_warning_cleared", "health_recovered"}:
            assert old is not None and old.cleared_at is None
            self.warnings[key] = replace(
                old, last_observed_at=effect.at, cleared_at=effect.at,
            )
        else:
            self.warnings[key] = ReliabilityWarningOccurrence(
                effect.node_id, effect.zone,
                "flapping" if effect.kind != "health_degraded" else "suspected_stuck",
                reason,
                old.first_observed_at if old is not None and old.cleared_at is None
                else effect.at,
                effect.at,
            )

    def _effect(
        self, state: EpisodeState, effect: EpisodeEffect,
    ) -> tuple[TraversalAuthorization | None, TraversalToken | None]:
        belief = self.filters[effect.zone]
        authorization = None
        token = None
        if effect.warning_reason is not None:
            self._warning(effect)
        if not self.count.state.expected_count:
            return None, None
        if effect.kind in {"positive", "correlated_positive", "interaction"}:
            if effect.kind == "interaction":
                belief.apply_interaction(effect.episode_id, effect.at)
                authorization = self.frontier.authorize_interaction(state, effect.at)
            elif effect.kind == "correlated_positive":
                belief.apply_correlated_positive(
                    effect.episode_id, effect.at, effect.reliability,
                )
                authorization = self.frontier.authorize_correlated_target(
                    state, effect.at,
                    settled_support=self.supports.settled_endpoint_for(state),
                    handoff_resolver=lambda: self.supports.settled_adjacent_for(
                        state, effect, self.episodes.states, self.beliefs,
                    ),
                )
            else:
                belief.apply_positive(effect.episode_id, effect.at, effect.reliability)
                authorization = self.frontier.authorize(
                    state, effect.at, count=self.count.state,
                    corroborating_states=self.episodes.states,
                    settled_support=self.supports.settled_endpoint_for(state),
                    handoff_resolver=lambda: self.supports.settled_adjacent_for(
                        state, effect, self.episodes.states, self.beliefs,
                    ),
                )
            if authorization.authorized:
                if effect.kind != "interaction":
                    belief.apply_arrival_transition(effect.episode_id, effect.at)
                if effect.kind != "correlated_positive":
                    token = self.frontier.issue(state, effect, authorization)
                elif (
                    self.supports.has_transfer_authority(authorization)
                    or authorization.settled_handoff is not None
                ):
                    token = self.frontier.issue_correlated_continuation(
                        state, effect, authorization, support_backed=True,
                    )
            if effect.kind == "positive" and authorization.settled_handoff is None:
                TraversalFrontier.apply_outward_context(
                    authorization, self.filters, effect.at, state.traversal_valid_until,
                )
        elif effect.kind == "stable_clear":
            if belief.state.generation_episode_id == effect.episode_id:
                belief.apply_stable_clear(
                    effect.episode_id, effect.at, effect.reliability,
                )
        elif effect.kind == "health_degraded":
            belief.apply_health_degraded(effect.episode_id, effect.at)
        elif effect.kind == "health_recovered":
            belief.apply_health_recovered(effect.episode_id, effect.at)
        elif effect.kind == "correlated_flap_ignored":
            if self.frontier.reopen_authorized_continuity(state, effect):
                belief.supersede_outward(effect.episode_id, effect.at)
        self.frontier.sync(state, effect.at)
        self.supports.apply(
            effect.at, effect, authorization, token, self.episodes.states,
            self.beliefs, self.frontier.tokens, self.frontier.retained_tokens,
        )
        return authorization, token

    def _advance(self, at: datetime) -> None:
        # Node iteration is not event order: a sparse advance can contain clear
        # deadlines from multiple physical nodes. Preserve actual effect times.
        due = sorted(
            ((effect, update.state)
             for update in self.episodes.advance(at) for effect in update.effects),
            key=lambda item: (item[0].at, item[0].node_id, item[0].kind),
        )
        for effect, state in due:
            self._effect(state, effect)
        for belief in self.filters.values():
            belief.advance(at)
        self.frontier.advance(at)
        for state in self.episodes.states:
            self.frontier.sync(state, at)
        self.supports.advance(
            at, self.episodes.states, self.beliefs,
            self.frontier.tokens, self.frontier.retained_tokens,
        )
        self.commit_prediction_learning()
        self.prediction_manager.prepare(
            at, self.count.state.expected_count, self.episodes.states, (),
        )
        self.updated_at = at

    def _policies(
        self, at: datetime, *, state: EpisodeState | None = None,
        effect: EpisodeEffect | None = None,
        authorization: TraversalAuthorization | None = None,
        callback: DecisionCallback | None = None, emit_events: bool = True,
        processing_at: datetime | None = None,
    ) -> tuple[tuple[PolicyDecision, ...], tuple[PolicyEvent, ...]]:
        decisions = []
        events = []
        for zone in sorted(self.policies):
            local = state is not None and state.zone == zone
            belief = self.filters[zone].state
            if self.count.state.expected_count == 0:
                update = self.policies[zone].apply_count_zero(at)
            else:
                update = self.policies[zone].evaluate(
                    at, belief, belief,
                    local_state=state if local else None,
                    local_effect=effect if local else None,
                    authorization=authorization if local else None,
                    pending_candidate=next(
                        (item for item in self.frontier.pending_candidates
                         if item.zone == zone), None,
                    ),
                    emit_event=emit_events, before_audit=callback,
                    processing_at=processing_at,
                    retained_endpoint_hold=any(
                        item.state == "settled" and item.current_zone == zone
                        for item in self.supports.supports
                    ) and belief.qualified_departure_at is None,
                    asserted_stay_hold=any(
                        item.zone == zone and (
                            item.degradation_reason == "count_conflict"
                            and item.status in {"degraded", "clearing"}
                            or item.cadence_correlated
                            and item.status in {"asserted", "clearing"}
                        )
                        for item in self.episodes.states
                    ),
                )
            decisions.append(update.decision)
            if update.event is not None:
                events.append(update.event)
        return tuple(decisions), tuple(events)

    def observe(
        self, event: SensorInput, *, decision_callback: DecisionCallback | None = None,
        processing_at: datetime | None = None,
    ) -> ZoneModelResult:
        if event.event_at < self.updated_at:
            return ZoneModelResult("stale", self.snapshot)
        self._advance(event.event_at)
        update = self.episodes.observe(event)
        if update.disposition == "duplicate":
            return ZoneModelResult(update.disposition, self.snapshot)
        authorizations = []
        last_effect = None
        for effect in update.effects:
            authorization, _ = self._effect(update.state, effect)
            if authorization is not None:
                authorizations.append(authorization)
            last_effect = effect
        if event.state in {"unknown", "unavailable"}:
            self.frontier.sync(update.state, event.event_at, invalidate=True)
            self.filters[update.state.zone].apply_unavailable(event.event_at)
        self.frontier.sync(update.state, event.event_at)
        if not self.count.state.expected_count:
            self.frontier.clear(event.event_at)
            for belief in self.filters.values():
                belief.apply_empty_baseline(event.event_at)
        self.supports.advance(
            event.event_at, self.episodes.states, self.beliefs,
            self.frontier.tokens, self.frontier.retained_tokens,
        )
        eligible = tuple(authorizations) if (
            last_effect is not None
            and last_effect.kind in {"positive", "interaction"}
        ) else ()
        self.prediction_manager.prepare(
            event.event_at, self.count.state.expected_count,
            self.episodes.states, eligible,
        )
        self.learning.extend(eligible)
        decisions, events = self._policies(
            event.event_at, state=update.state, effect=last_effect,
            authorization=authorizations[-1] if authorizations else None,
            callback=decision_callback,
            processing_at=processing_at,
        )
        return ZoneModelResult(
            update.disposition, self.snapshot, events, decisions, tuple(authorizations),
        )

    def advance(self, at: datetime, *, emit_events: bool = True) -> ZoneModelResult:
        self._advance(at)
        decisions, events = self._policies(at, emit_events=emit_events)
        return ZoneModelResult("advanced", self.snapshot, events, decisions)

    def observe_count(self, event: CountInput) -> ZoneModelResult:
        self._advance(event.event_at)
        update = self.count.observe(event)
        if update.categorical_zero:
            for reset in self.episodes.reset_cadence(event.event_at):
                for effect in reset.effects:
                    self._warning(effect)
            self.frontier.clear(event.event_at)
            self.supports.clear(event.event_at)
            self.conflicts.clear()
            self.prediction_manager.clear()
            self.learning.clear()
            for belief in self.filters.values():
                belief.apply_empty_baseline(event.event_at)
        decisions, events = self._policies(event.event_at)
        return ZoneModelResult(update.disposition, self.snapshot, events, decisions)


def component_wire(
    predictive_map: PredictiveMap, components: PersistenceComponents,
) -> dict[str, object]:
    """Real codec, explicitly tagged component document, not current inference."""
    return {
        "schema": "persistence-component-specimen",
        "map_fingerprint": persistence.target_map_fingerprint(predictive_map),
        "snapshot": persistence._json_value(asdict(components.snapshot)),
        "audit": [
            persistence._json_value(asdict(row)) for row in components.audit_rows
        ],
        "prediction": components.prediction_manager.serialize(),
    }


def decode_component_snapshot(value: object) -> ZoneModelSnapshot:
    """Compose existing field codecs, not the selected-engine envelope decoder.

    No legacy flags/defaults, selected ledger fabrication or validator copies:
    the component document has no selected model and promises no such acceptance.
    All actual component records use today's strict production field decoders.
    """
    data = persistence._mapping(value, "Component snapshot")
    return ZoneModelSnapshot(
        updated_at=persistence._datetime(data.get("updated_at"), "component frontier"),
        episode_states=tuple(
            persistence._decode_episode(row)
            for row in persistence._list(data, "episode_states")
        ),
        belief_states=tuple(
            persistence._decode_belief(row)
            for row in persistence._list(data, "belief_states")
        ),
        traversal_tokens=tuple(
            persistence._decode_token(row)
            for row in persistence._list(data, "traversal_tokens")
        ),
        current_token_ids=tuple(persistence._strings(
            data.get("current_token_ids"), "current token IDs",
        )),
        authorization_uses=tuple(
            persistence._decode_use(row)
            for row in persistence._list(data, "authorization_uses")
        ),
        count_state=persistence._decode_count(data.get("count_state")),
        policy_states=tuple(
            persistence._decode_policy_state(row)
            for row in persistence._list(data, "policy_states")
        ),
        pending_candidates=tuple(
            persistence._decode_pending_candidate(row)
            for row in persistence._list(data, "pending_candidates")
        ),
        count_conflicts=tuple(
            persistence._decode_count_conflict(row)
            for row in persistence._list(data, "count_conflicts")
        ),
        retained_traversal_tokens=tuple(
            persistence._decode_token(row)
            for row in persistence._list(data, "retained_traversal_tokens")
        ),
        anonymous_supports=tuple(
            persistence._decode_anonymous_support(row)
            for row in persistence._list(data, "anonymous_supports")
        ),
        support_token_bindings=tuple(
            persistence._decode_support_binding(row)
            for row in persistence._list(data, "support_token_bindings")
        ),
        reliability_warning_occurrences=tuple(
            persistence._decode_warning_occurrence(row)
            for row in persistence._list(data, "reliability_warning_occurrences")
        ),
    )


def restore_components(
    predictive_map: PredictiveMap, payload: object, restore_at: datetime,
) -> PersistenceComponents:
    """Validate before installing; caller input and existing receivers stay intact."""
    root = persistence._mapping(payload, "Component specimen")
    if root.get("schema") != "persistence-component-specimen":
        raise ValueError("Not a component specimen")
    if root.get("map_fingerprint") != persistence.target_map_fingerprint(
        predictive_map,
    ):
        raise ValueError("Component map fingerprint is incompatible")
    snapshot = decode_component_snapshot(root.get("snapshot"))
    if restore_at < snapshot.updated_at:
        raise ValueError("Component restore time predates stored state")
    candidate = PersistenceComponents(
        predictive_map, snapshot.count_state.expected_count, snapshot.updated_at,
    )
    candidate.episodes.restore_snapshot(snapshot.episode_states)
    validate_component_snapshot(predictive_map, candidate.nodes, snapshot)
    candidate.frontier.restore_snapshot(
        snapshot.traversal_tokens, snapshot.current_token_ids,
        snapshot.authorization_uses, snapshot.updated_at,
        snapshot.pending_candidates, snapshot.retained_traversal_tokens,
    )
    candidate.supports.restore(
        snapshot.anonymous_supports, snapshot.support_token_bindings,
        snapshot.updated_at,
    )
    candidate.count = CountContext.restore(snapshot.count_state)
    candidate.conflicts.restore(
        snapshot.count_conflicts, snapshot.count_state.expected_count,
    )
    candidate.filters = {
        state.zone: ZoneBeliefFilter.restore(BELIEF_PROFILES[state.profile_name], state)
        for state in snapshot.belief_states
    }
    audit = tuple(
        persistence._decode_policy_decision(row)
        for row in persistence._list(root, "audit")
    )
    candidate.policies = {}
    for state in snapshot.policy_states:
        log = PolicyAuditLog()
        for row in audit:
            if row.zone == state.zone:
                log.append(row)
        candidate.policies[state.zone] = ZonePolicy(
            state.zone, POLICY_CALIBRATIONS[state.profile_name], snapshot.updated_at,
            state=state, audit=log,
        )
    candidate.warnings = {
        (item.node_id, item.reason): item
        for item in snapshot.reliability_warning_occurrences
    }
    candidate.prediction_manager = TargetPredictionManager.restored(
        predictive_map, root.get("prediction"), snapshot.updated_at,
        strict_frontier=True,
    )
    if restore_at > snapshot.updated_at:
        candidate.advance(restore_at, emit_events=False)
    return candidate
