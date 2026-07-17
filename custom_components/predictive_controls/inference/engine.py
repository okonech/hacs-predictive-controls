"""Production orchestration for exact occupancy inference."""

from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from ..const import PRODUCT_MAX_OCCUPANTS
from ..events import OccupancyEvent
from ..model import PredictiveMap
from ..occupancy_persistence import map_fingerprint
from ..occupancy_state import (
    PackedPolicyAuditContext,
    PolicyDecision,
    PredictionLease,
    ReleaseCause,
    ZonePolicyState,
)
from ..policy_audit import (
    pack_preencoded_policy_audit_payload,
    packed_policy_audit_context_from_storage,
    stored_policy_audit_context_payload,
    validate_target_policy_audit_context,
)
from ..prediction import PredictionManager
from .association import AugmentedLogMessage, EndpointFactor
from .count_transition import LogCountTransitionKernel
from .episodes import EpisodeEmission, ObservationEpisodes
from .factor_chain import ExactFactorChain, ZoneLikelihoodStep
from .operators import CompleteMoveOperators
from .policy import PosteriorEventPolicy, PosteriorPolicyAuditEntry
from .port import EngineDiagnostics
from .reducer import FactorChainEventReducer, FactorChainReplayState
from .replay import RetainedReplayCoordinator
from .state_space import CompactLogPosterior, StateSpace
from .support import InjectiveSupportResult, injective_support_result
from .types import (
    AugmentedStateKey,
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    MovementDisposition,
    SupportEventAtom,
    require_utc,
)

MAX_ACCEPTED_LATENESS = timedelta(seconds=2)
MAX_COHERENT_ENDPOINTS = 1_243
_ENGINE_SCHEMA = "exact-augmented-v6"
_REPLAY_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MOVEMENT_DISPOSITIONS = {
    "stay",
    "graph_valid",
    "unlocated",
    "missed_movement",
    "censored_graph_path",
}
_RELEASE_SUPPORT_DISPOSITIONS = {
    "stay",
    "graph_valid",
    "censored_graph_path",
    "missed_movement",
}


@dataclass(frozen=True)
class _ArrivalCorroboration:
    zone: str
    node_id: str
    episode_id: str | None
    current_positive: bool


@dataclass(frozen=True)
class _ArrivalSupportedCache:
    chain: ExactFactorChain
    corroborations: tuple[_ArrivalCorroboration, ...]
    targets: tuple[tuple[str, str], ...]
    probabilities: tuple[tuple[str, float], ...]


class ExactInferenceEngine:
    """Exact occupancy, movement, policy, and prediction engine."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        expected_occupants: int,
        *,
        policy: PosteriorEventPolicy | None = None,
    ) -> None:
        self._map = predictive_map
        self._zones = tuple(predictive_map.zones())
        self._posterior = self._unlocated_posterior(expected_occupants)
        self._reducer = FactorChainEventReducer(
            predictive_map,
            self._posterior.space,
        )
        self._chain = ExactFactorChain(
            self._posterior,
            operators=self._reducer.operators,
        )
        self._message = AugmentedLogMessage.from_posterior(self._posterior)
        self._episodes = ObservationEpisodes(predictive_map)
        self._replay: RetainedReplayCoordinator[
            FactorChainReplayState,
            FactorChainReplayState,
        ] | None = None
        self._event_disposition: str | None = None
        self._updated_at: datetime | None = None
        self._restore_rejection: str | None = None
        self._count_evidence_ids: frozenset[str] = frozenset()
        self._latest_count_control_at: datetime | None = None
        self._predictions = PredictionManager(predictive_map)
        self._processed_prediction_support_ids: frozenset[str] = frozenset()
        self._policy = policy
        self._last_policy_audit_context_at = _latest_audit_context_at(policy)
        self._migration_bootstrap_pending = False
        self._current_arrival_factors: tuple[tuple[str, EndpointFactor], ...] = ()
        self._arrival_supported_cache: _ArrivalSupportedCache | None = None
        self._count_marginals_cache: tuple[
            CompactLogPosterior,
            tuple[tuple[float, ...], ...],
        ] | None = None

    @property
    def policy(self) -> PosteriorEventPolicy | None:
        return self._policy

    @property
    def predictions(self) -> PredictionManager:
        return self._predictions

    @property
    def diagnostics(self) -> EngineDiagnostics:
        count_marginals = self._count_marginals()
        occupied_marginals = tuple(
            math.fsum(counts[1:]) for counts in count_marginals[: len(self._zones)]
        )
        most_likely = self._posterior.space.unrank(
            max(range(len(self._posterior)), key=self._posterior.__getitem__)
        )
        replay = self._replay
        unresolved = self._chain.unresolved_endpoint_count
        overloaded = unresolved > MAX_COHERENT_ENDPOINTS
        release_available, release_probabilities, _release_evidence = (
            self._release_safe_probabilities(overloaded)
        )
        return EngineDiagnostics(
            self._posterior.space.occupants,
            dict(
                zip(
                    self._zones,
                    occupied_marginals,
                    strict=True,
                )
            ),
            {zone: count_marginals[index] for index, zone in enumerate(self._zones)},
            self._posterior.normalization,
            0.0,
            self._event_disposition,
            self._updated_at,
            self._episodes.states,
            self._restore_rejection,
            unresolved,
            len(self._chain.steps),
            0 if replay is None else len(replay.retained),
            0 if replay is None else len(replay.consumed_endpoint_ids),
            overloaded,
            self._arrival_supported_probabilities(),
            release_available,
            release_probabilities,
            self._predictions.leases,
            self._predictions.probabilities,
            self._predictions.chain.counts,
            self._predictions.route_counts,
            self._predictions.route_diagnostics,
            {} if self._policy is None else self._policy.states,
            () if self._policy is None else self._policy.last_decisions,
            {
                zone: most_likely[index]
                for index, zone in enumerate(self._zones)
            },
            () if self._policy is None else self._policy.audit,
        )

    def ensure(self, now: datetime) -> None:
        if self._updated_at is None:
            self._updated_at = now

    def observe(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool,
    ) -> EngineDiagnostics:
        return self.observe_received(
            event,
            receive_at=event.event_at,
            emit_activation=emit_activation,
        )

    def observe_received(
        self,
        event: OccupancyEvent,
        *,
        receive_at: datetime,
        emit_activation: bool,
    ) -> EngineDiagnostics:
        self._clear_current_arrival()
        self._validate_zone(event.zone)
        replay = self._ensure_replay(receive_at)
        previous_result = replay.replay_result
        evidence_id = _event_id(event)
        replay_disposition = replay.accept(
            event,
            evidence_id,
            receive_at,
            _endpoint_id(event) if event.state == "on" else None,
        )
        if replay_disposition == "accepted":
            accepted = next(
                item for item in replay.retained if item.evidence_id == evidence_id
            )
            if previous_result is not None and replay.retained[-1] == accepted:
                state = replay.replay_incremental(
                    (accepted,),
                    self._reducer.reduce,
                )
                disposition_state = state
            else:
                adjacent = replay.replay_adjacent_insertion(
                    accepted,
                    self._reducer.reduce,
                )
                if adjacent is None:
                    state = replay.replay(self._reducer.reduce)
                    disposition_state = state
                else:
                    state, disposition_state = adjacent
            state = self._compact_replay(replay, state)
            self._event_disposition = dict(disposition_state.dispositions)[
                evidence_id
            ]
            self._updated_at = replay.posterior_event_at
        else:
            state = replay.replay_result or replay.finalized_base
            self._event_disposition = replay_disposition
        self._apply_replay_state(state, replay.watermark)
        if self._event_disposition == "accepted_positive":
            matches = tuple(
                step
                for step in self._chain.steps
                if isinstance(step, EndpointFactor)
                and step.endpoint.token_id == _endpoint_id(event)
                and step.target_zone == event.zone
            )
            if len(matches) != 1:
                raise ValueError(
                    "Accepted positive input must resolve to one endpoint factor"
                )
            self._current_arrival_factors = ((event.zone, matches[0]),)
            self._arrival_supported_cache = None
        if replay_disposition == "accepted":
            self._apply_policy(receive_at, emit_activation=emit_activation)
        return self.diagnostics

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> EngineDiagnostics:
        self._clear_current_arrival()
        for event in events:
            self._validate_zone(event.zone)
        updates = self._episodes.bootstrap(events, cold_start=cold_start)
        for update in updates:
            self._apply_emissions(update.emissions)
        self._chain = ExactFactorChain(
            self._posterior,
            operators=self._reducer.operators,
        )
        self._reset_replay()
        accepted_updates = tuple(
            update for update in updates if update.disposition == "snapshot_reconciled"
        )
        if accepted_updates:
            accepted_nodes = {update.state.node_id for update in accepted_updates}
            accepted_times = tuple(
                event.event_at for event in events if event.node_id in accepted_nodes
            )
            self._updated_at = max(accepted_times)
            self._event_disposition = "snapshot_reconciled"
        elif updates:
            self._event_disposition = updates[-1].disposition
        if self._migration_bootstrap_pending:
            self._migration_bootstrap_pending = False
        else:
            self._apply_policy(
                self._updated_at or datetime.now(tz=UTC),
                emit_activation=False,
            )
        return self.diagnostics

    def migrate_legacy_state(
        self,
        policy_states: Mapping[str, ZonePolicyState],
        transition_counts: Mapping[str, Mapping[str, object]],
        route_counts: Mapping[tuple[str, ...], Mapping[str, float]],
    ) -> EngineDiagnostics:
        """Preserve safe legacy ownership and learned counts without evidence."""

        self._clear_current_arrival()
        if self._policy is None:
            raise ValueError("Target policy is unavailable for legacy migration")
        migrated_policy = PosteriorEventPolicy(
            self._zones,
            activation_threshold=self._policy.activation_threshold,
            release_threshold=self._policy.release_threshold,
            activation_window=self._policy.activation_window,
        )
        migrated_policy.restore_states(
            {
                zone: ZonePolicyState(
                    keep_on=bool(policy_states.get(zone, ZonePolicyState()).keep_on),
                    reason=(
                        "migrated legacy ownership"
                        if policy_states.get(zone, ZonePolicyState()).keep_on
                        else "no trusted occupancy"
                    ),
                )
                for zone in self._zones
            }
        )
        migrated_predictions = PredictionManager(self._map)
        migrated_predictions.chain.restore_counts(transition_counts)
        migrated_predictions.restore_route_state(
            cast(dict[tuple[str, ...], dict[str, float]], dict(route_counts)), ()
        )

        self._policy = migrated_policy
        self._last_policy_audit_context_at = _latest_audit_context_at(migrated_policy)
        self._predictions = migrated_predictions
        self._migration_bootstrap_pending = True
        self._event_disposition = "legacy_v5_migrated"
        self._restore_rejection = None
        return self.diagnostics

    def finalize(self, now: datetime) -> bool:
        self._clear_current_arrival()
        replay = self._replay
        if replay is None or not replay.advance_watermark(now):
            return False if self._policy is None else self._policy.expire(now)
        state = replay.replay_result or replay.finalized_base
        state = self._compact_replay(replay, state)
        self._apply_replay_state(state, replay.watermark)
        self._event_disposition = "watermark_advanced"
        self._apply_policy(now, emit_activation=False)
        return True

    def reconcile_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
        *,
        reconcile_policy: bool,
    ) -> EngineDiagnostics:
        self._clear_current_arrival()
        del reconcile_policy
        if not self._accept_count_control(now, evidence_id):
            return self.diagnostics
        previous_occupants = self._chain.space.occupants
        self._message = AugmentedLogMessage.from_posterior(self._chain.posterior)
        self._message = LogCountTransitionKernel.reconcile_augmented(
            self._message,
            expected_occupants,
        )
        self._reset_reducer_for_message()
        self._predictions.reconcile_count(previous_occupants, expected_occupants)
        self._updated_at = now
        self._event_disposition = "accepted_count_control"
        self._commit_count_control(now, evidence_id)
        self._apply_policy(now, emit_activation=False)
        return self.diagnostics

    def enter_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
    ) -> EngineDiagnostics:
        self._clear_current_arrival()
        del expected_occupants
        if not self._accept_count_control(now, evidence_id):
            return self.diagnostics
        self._message = AugmentedLogMessage.from_posterior(self._chain.posterior)
        self._message = LogCountTransitionKernel.reconcile_augmented(
            self._message,
            0,
        )
        self._reset_reducer_for_message()
        self._updated_at = now
        self._event_disposition = "unsupported_count"
        self._commit_count_control(now, evidence_id)
        self._apply_policy(now, emit_activation=False)
        return self.diagnostics

    def serialize(
        self,
        now: datetime,
        transition_counts: Mapping[str, Mapping[str, float]],
    ) -> object:
        del transition_counts
        self.ensure(now)
        if self._policy is not None:
            self._policy.expire(now)
        self._message = AugmentedLogMessage.from_posterior(self._posterior)
        return {
            "schema": _ENGINE_SCHEMA,
            "map_fingerprint": map_fingerprint(self._map),
            "zones": list(self._zones),
            "occupants": self._posterior.space.occupants,
            "log_probabilities": list(self._posterior),
            "message": _encode_message(self._message),
            "chain": _encode_chain(self._chain),
            "event_disposition": self._event_disposition,
            "episodes": self._episodes.serialize(),
            "replay": None
            if self._replay is None
            else self._replay.serialize(
                self._encode_replay_state,
                self._encode_replay_state,
            ),
            "count_evidence_ids": sorted(self._count_evidence_ids),
            "latest_count_control_at": None
            if self._latest_count_control_at is None
            else self._latest_count_control_at.isoformat(),
            "prediction_leases": [
                _encode_prediction_lease(lease)
                for lease in self._predictions.leases
            ],
            "route_transition_counts": self._predictions.chain.counts,
            "route_counts": [
                {
                    "prefix": list(prefix),
                    "targets": targets,
                }
                for prefix, targets in self._predictions.route_counts.items()
            ],
            "route_contexts": [
                list(context) for context in self._predictions.route_contexts
            ],
            "processed_prediction_support_ids": sorted(
                self._processed_prediction_support_ids
            ),
            "policy": None if self._policy is None else _encode_policy(self._policy),
            "migration_bootstrap_pending": self._migration_bootstrap_pending,
            "updated_at": None
            if self._updated_at is None
            else self._updated_at.isoformat(),
        }

    def restore(self, restored: object) -> EngineDiagnostics:
        try:
            (
                message,
                chain,
                episodes,
                replay,
                count_evidence_ids,
                latest_count_control_at,
                predictions,
                processed_prediction_support_ids,
                policy,
                migration_bootstrap_pending,
                disposition,
                updated_at,
            ) = self._validate_restore(restored)
        except (TypeError, ValueError) as exc:
            self._restore_rejection = str(exc)
            raise
        self._message = message
        self._posterior = chain.posterior
        self._chain = chain
        self._episodes = episodes
        self._reducer = FactorChainEventReducer(
            self._map,
            message.space,
            chain.operators,
        )
        self._replay = replay
        self._count_evidence_ids = count_evidence_ids
        self._latest_count_control_at = latest_count_control_at
        self._predictions = predictions
        self._processed_prediction_support_ids = processed_prediction_support_ids
        self._policy = policy
        self._last_policy_audit_context_at = _latest_audit_context_at(policy)
        self._migration_bootstrap_pending = migration_bootstrap_pending
        self._event_disposition = disposition
        self._updated_at = updated_at
        self._restore_rejection = None
        self._clear_current_arrival()
        return self.diagnostics

    def _validate_restore(
        self,
        restored: object,
    ) -> tuple[
        AugmentedLogMessage,
        ExactFactorChain,
        ObservationEpisodes,
        RetainedReplayCoordinator[FactorChainReplayState, FactorChainReplayState]
        | None,
        frozenset[str],
        datetime | None,
        PredictionManager,
        frozenset[str],
        PosteriorEventPolicy | None,
        bool,
        str | None,
        datetime | None,
    ]:
        if not isinstance(restored, Mapping):
            raise TypeError("Exact engine state must be a mapping")
        if restored.get("schema") != _ENGINE_SCHEMA:
            raise ValueError("Unsupported exact engine schema")
        if restored.get("map_fingerprint") != map_fingerprint(self._map):
            raise ValueError("Exact engine map fingerprint does not match")
        if restored.get("zones") != list(self._zones):
            raise ValueError("Exact engine zones do not match")
        occupants = restored.get("occupants")
        log_probabilities = restored.get("log_probabilities")
        if (
            not isinstance(occupants, int)
            or isinstance(occupants, bool)
            or not isinstance(log_probabilities, list)
        ):
            raise ValueError("Exact engine posterior is invalid")
        if not 0 <= occupants <= PRODUCT_MAX_OCCUPANTS:
            raise ValueError(
                "Exact engine occupant count must be between zero and two"
            )
        posterior = CompactLogPosterior.from_normalized(
            StateSpace(self._zones, occupants),
            log_probabilities,
        )
        message = _decode_message(restored.get("message"), posterior.space)
        projected = message.occupancy_posterior()
        if any(
            abs(math.exp(actual) - math.exp(expected)) > 1e-12
            for actual, expected in zip(projected, posterior, strict=True)
        ):
            raise ValueError("Exact projected posterior does not match message")
        operators = CompleteMoveOperators(posterior.space)
        chain = _decode_chain(
            restored.get("chain"),
            posterior.space,
            operators,
        )
        if any(
            abs(math.exp(actual) - math.exp(expected)) > 1e-12
            for actual, expected in zip(
                chain.posterior,
                posterior,
                strict=True,
            )
        ):
            raise ValueError("Exact current chain does not match posterior")
        disposition = restored.get("event_disposition")
        if disposition is not None and not isinstance(disposition, str):
            raise ValueError("Exact event disposition is invalid")
        raw_updated_at = restored.get("updated_at")
        if raw_updated_at is None:
            updated_at = None
        elif isinstance(raw_updated_at, str):
            try:
                updated_at = datetime.fromisoformat(raw_updated_at)
            except ValueError as exc:
                raise ValueError("Exact update time is invalid") from exc
            require_utc(updated_at, "Exact update time")
        else:
            raise ValueError("Exact update time is invalid")
        episodes = ObservationEpisodes(self._map)
        episodes.restore(restored.get("episodes"))
        raw_replay = restored.get("replay")
        replay: RetainedReplayCoordinator[
            FactorChainReplayState,
            FactorChainReplayState,
        ] | None = None
        if raw_replay is not None:
            base = FactorChainReplayState(chain, episodes.states)
            replay = RetainedReplayCoordinator(
                MAX_ACCEPTED_LATENESS,
                _REPLAY_EPOCH,
                _REPLAY_EPOCH,
                base,
            )
            replay.restore(
                raw_replay,
                lambda payload: self._decode_replay_state(
                    payload,
                    posterior.space,
                    operators,
                ),
                lambda payload: self._decode_replay_state(
                    payload,
                    posterior.space,
                    operators,
                ),
            )
            if replay.max_lateness != MAX_ACCEPTED_LATENESS:
                raise ValueError("Exact replay lateness is incompatible")
            current = replay.replay_result or replay.finalized_base
            if _encode_chain(current.chain) != _encode_chain(chain):
                raise ValueError("Exact replay result does not match current chain")
            if tuple(current.chain.posterior) != tuple(posterior):
                raise ValueError("Exact replay result does not match message")
            if current.episode_states != episodes.states:
                raise ValueError("Exact replay episodes do not match current state")
            chain = current.chain
        raw_count_ids = restored.get("count_evidence_ids")
        if not isinstance(raw_count_ids, list) or any(
            not isinstance(evidence_id, str) or not evidence_id
            for evidence_id in raw_count_ids
        ):
            raise ValueError("Exact count evidence IDs are invalid")
        if raw_count_ids != sorted(set(raw_count_ids)):
            raise ValueError("Exact count evidence IDs are not canonical")
        latest_count_control_at = _optional_datetime(
            restored.get("latest_count_control_at"),
            "count control time",
        )
        if raw_count_ids and latest_count_control_at is None:
            raise ValueError("Exact count control frontier is missing")
        predictions = PredictionManager(self._map)
        predictions.chain.restore_counts(
            _decode_transition_counts(restored.get("route_transition_counts"))
        )
        predictions.restore_leases(
            _decode_prediction_leases(restored.get("prediction_leases")),
            updated_at or _REPLAY_EPOCH,
        )
        predictions.restore_route_state(
            _decode_route_counts(restored.get("route_counts")),
            _decode_route_contexts(restored.get("route_contexts")),
        )
        raw_processed_support_ids = restored.get(
            "processed_prediction_support_ids"
        )
        if not isinstance(raw_processed_support_ids, list) or any(
            not isinstance(support_id, str) or not support_id
            for support_id in raw_processed_support_ids
        ):
            raise ValueError("Exact processed prediction support IDs are invalid")
        if raw_processed_support_ids != sorted(set(raw_processed_support_ids)):
            raise ValueError(
                "Exact processed prediction support IDs are not canonical"
            )
        policy = self._decode_policy(
            restored.get("policy"),
            updated_at or _REPLAY_EPOCH,
        )
        migration_bootstrap_pending = restored.get(
            "migration_bootstrap_pending",
            False,
        )
        if not isinstance(migration_bootstrap_pending, bool):
            raise ValueError("Exact migration bootstrap state is invalid")
        return (
            message,
            chain,
            episodes,
            replay,
            frozenset(raw_count_ids),
            latest_count_control_at,
            predictions,
            frozenset(raw_processed_support_ids),
            policy,
            migration_bootstrap_pending,
            disposition,
            updated_at,
        )

    def _decode_policy(
        self,
        value: object,
        now: datetime,
    ) -> PosteriorEventPolicy | None:
        if value is None:
            if self._policy is not None:
                raise ValueError("Exact policy state is missing")
            return None
        if not isinstance(value, Mapping):
            raise ValueError("Exact policy state is invalid")
        activation_threshold = _required_number(
            value.get("activation_threshold"),
            "policy activation threshold",
        )
        release_threshold = _required_number(
            value.get("release_threshold"),
            "policy release threshold",
        )
        activation_window_seconds = _required_number(
            value.get("activation_window_seconds"),
            "policy activation window",
        )
        if self._policy is not None and (
            activation_threshold != self._policy.activation_threshold
            or release_threshold != self._policy.release_threshold
            or activation_window_seconds
            != self._policy.activation_window.total_seconds()
        ):
            raise ValueError("Exact policy configuration is incompatible")
        policy = PosteriorEventPolicy(
            self._zones,
            activation_threshold=activation_threshold,
            release_threshold=release_threshold,
            activation_window=timedelta(seconds=activation_window_seconds),
        )
        raw_states = value.get("states")
        if not isinstance(raw_states, Mapping) or set(raw_states) != set(self._zones):
            raise ValueError("Exact policy zones do not match")
        policy.restore_states(
            {
                zone: _decode_policy_state(raw_states[zone])
                for zone in self._zones
            }
        )
        raw_audit = value.get("audit", [])
        if not isinstance(raw_audit, list):
            raise ValueError("Exact policy audit is invalid")
        validated_contexts: set[bytes] = set()
        operators_by_space: dict[
            tuple[tuple[str, ...], int],
            tuple[StateSpace, CompleteMoveOperators],
        ] = {}
        audit = tuple(
            _decode_policy_audit_entry(
                entry,
                validated_contexts,
                operators_by_space,
            )
            for entry in raw_audit
        )
        policy.restore_audit(audit, now)
        if policy.audit != audit:
            raise ValueError("Exact policy audit exceeds retention bounds")
        return policy

    def _unlocated_posterior(self, occupants: int) -> CompactLogPosterior:
        space = StateSpace(self._zones, occupants)
        return CompactLogPosterior.certain(
            space,
            (0,) * len(self._zones) + (occupants,),
        )

    def _validate_zone(self, zone: str) -> None:
        if zone not in self._zones:
            raise ValueError(f"Observation zone is not in the predictive map: {zone}")

    def _arrival_supported_probabilities(self) -> dict[str, float]:
        corroborations = tuple(
            _ArrivalCorroboration(
                state.zone,
                state.node_id,
                state.episode_id,
                state.current_positive,
            )
            for state in self._episodes.states
        )
        cached = self._arrival_supported_cache
        targets = tuple(
            (zone, factor.endpoint.token_id)
            for zone, factor in self._current_arrival_factors
        )
        if (
            cached is not None
            and cached.chain is self._chain
            and cached.corroborations == corroborations
            and cached.targets == targets
        ):
            return dict(cached.probabilities)
        probabilities = _arrival_supported_probabilities(
            self._chain,
            corroborations,
            dict(self._current_arrival_factors),
        )
        self._arrival_supported_cache = _ArrivalSupportedCache(
            self._chain,
            corroborations,
            targets,
            tuple(probabilities.items()),
        )
        return probabilities

    def _latest_arrival_factors(self) -> dict[str, EndpointFactor]:
        return _latest_arrival_factors(self._chain)

    def _release_safe_probabilities(
        self,
        overloaded: bool,
    ) -> tuple[bool, dict[str, float], dict[str, object]]:
        if overloaded or self._chain.unresolved_endpoint_count:
            return (
                False,
                {},
                {
                    "unavailable_reason": (
                        "overloaded" if overloaded else "unresolved_endpoints"
                    ),
                    "zones": {},
                },
            )
        message = self._chain.finalized_support_message()
        current_sustained_zones = {
            state.zone
            for state in self._episodes.states
            if state.current_positive
            and self._map.occupancy_behavior_for_node(
                self._map.nodes[state.node_id]
            )
            in {"sustained", "sticky"}
        }
        results: dict[str, InjectiveSupportResult] = {}
        probabilities: dict[str, float] = {}
        for zone in self._zones:
            if zone in current_sustained_zones:
                probabilities[zone] = 0.0
                continue
            result = injective_support_result(
                message,
                zone,
                lambda support: support.disposition
                in _RELEASE_SUPPORT_DISPOSITIONS,
            )
            results[zone] = result
            probabilities[zone] = result.probability
        return (
            True,
            probabilities,
            {
                "unavailable_reason": None,
                "zones": {
                    zone: (
                        {"veto": "sustained_positive", "strata": []}
                        if zone in current_sustained_zones
                        else _encode_support_result(results[zone])
                    )
                    for zone in self._zones
                },
            },
        )

    def _apply_policy(self, now: datetime, *, emit_activation: bool) -> None:
        if self._policy is None:
            return
        overloaded = self._chain.unresolved_endpoint_count > MAX_COHERENT_ENDPOINTS
        release_available, release_probabilities, release_evidence = (
            self._release_safe_probabilities(overloaded)
        )
        arrival_probabilities = self._arrival_supported_probabilities()
        capture_audit_context = (
            self._last_policy_audit_context_at is None
            or now
            >= self._last_policy_audit_context_at + timedelta(seconds=30)
        )

        def audit_context_factory() -> PackedPolicyAuditContext:
            context = self._target_policy_audit_context(
                now,
                arrival_probabilities,
                release_available,
                release_probabilities,
                release_evidence,
            )
            if (
                self._last_policy_audit_context_at is None
                or now > self._last_policy_audit_context_at
            ):
                self._last_policy_audit_context_at = now
            return context

        self._policy.apply(
            now,
            self._chain.space.occupants,
            arrival_probabilities,
            release_available,
            release_probabilities,
            emit_activation=emit_activation,
            arrival_evidence_ids=(
                {
                    zone: (factor.endpoint.token_id,)
                    for zone, factor in self._current_arrival_factors
                }
                if emit_activation
                else {}
            ),
            audit_context_factory=audit_context_factory,
            capture_audit_context=capture_audit_context,
        )

    def _target_policy_audit_context(
        self,
        now: datetime,
        arrival_probabilities: Mapping[str, float],
        release_available: bool,
        release_probabilities: Mapping[str, float],
        release_evidence: Mapping[str, object],
    ) -> PackedPolicyAuditContext:
        replay = self._replay
        policy = self._policy
        if policy is None:
            raise RuntimeError("Target policy is unavailable")
        count_marginals = self._count_marginals()
        sparse_vectors: dict[int, dict[str, object]] = {}
        sparse_entries: dict[
            bytes,
            list[tuple[CompactLogPosterior, list[object]]],
        ] = {}
        payload: dict[str, object] = {
            "schema": "exact-policy-audit-v2",
            "decision_at": now.isoformat(),
            "event_disposition": self._event_disposition,
            "updated_at": None
            if self._updated_at is None
            else self._updated_at.isoformat(),
            "map_fingerprint": map_fingerprint(self._map),
            "zones": list(self._zones),
            "occupants": self._posterior.space.occupants,
            "occupied_marginals": {
                zone: math.fsum(count_marginals[index][1:])
                for index, zone in enumerate(self._zones)
            },
            "count_marginals": {
                zone: list(count_marginals[index])
                for index, zone in enumerate(self._zones)
            },
            "arrival_supported": {
                "probabilities": dict(sorted(arrival_probabilities.items())),
                "targets": {
                    zone: factor.endpoint.token_id
                    for zone, factor in self._current_arrival_factors
                },
                "threshold": policy.activation_threshold,
            },
            "release_safe": {
                "available": release_available,
                "probabilities": dict(sorted(release_probabilities.items())),
                "threshold": policy.release_threshold,
                "evidence": dict(release_evidence),
            },
            "normalization": self._posterior.normalization,
            "pruned_probability": 0.0,
            "message": _encode_message(self._message),
            "chain": _encode_audit_chain(
                self._chain,
                sparse_vectors,
                sparse_entries,
            ),
            "episodes": self._episodes.serialize(),
            "replay": None
            if replay is None
            else replay.serialize(
                lambda state: self._encode_audit_replay_state(
                    state,
                    sparse_vectors,
                    sparse_entries,
                ),
                lambda state: self._encode_audit_replay_state(
                    state,
                    sparse_vectors,
                    sparse_entries,
                ),
            ),
            "count_evidence_ids": sorted(self._count_evidence_ids),
            "latest_count_control_at": None
            if self._latest_count_control_at is None
            else self._latest_count_control_at.isoformat(),
            "prediction_leases": [
                _encode_prediction_lease(lease)
                for lease in self._predictions.leases
            ],
            "route_transition_counts": self._predictions.chain.counts,
            "route_counts": [
                {"prefix": list(prefix), "targets": targets}
                for prefix, targets in self._predictions.route_counts.items()
            ],
            "route_contexts": [
                list(context) for context in self._predictions.route_contexts
            ],
            "processed_prediction_support_ids": sorted(
                self._processed_prediction_support_ids
            ),
            "policy_states": {
                zone: _encode_policy_state(state)
                for zone, state in policy.states.items()
            },
            "performance": {
                "configuration_count": len(self._posterior.space),
                "factor_step_count": len(self._chain.steps),
                "unresolved_assignment_count": (
                    self._chain.unresolved_endpoint_count
                ),
                "retained_input_count": 0
                if replay is None
                else len(replay.retained),
                "consumed_endpoint_count": 0
                if replay is None
                else len(replay.consumed_endpoint_ids),
                "overloaded": (
                    self._chain.unresolved_endpoint_count
                    > MAX_COHERENT_ENDPOINTS
                ),
                "prediction_used_for_policy": False,
            },
        }
        return pack_preencoded_policy_audit_payload(payload)

    def _count_marginals(self) -> tuple[tuple[float, ...], ...]:
        cached = self._count_marginals_cache
        if cached is not None and cached[0] is self._posterior:
            return cached[1]
        marginals = self._posterior.count_marginals()
        self._count_marginals_cache = (self._posterior, marginals)
        return marginals

    def _apply_emissions(self, emissions: tuple[EpisodeEmission, ...]) -> None:
        self._arrival_supported_cache = None
        for emission in emissions:
            self._message = self._message.apply_zone_likelihood(
                self._message.space.location_index(emission.zone),
                empty_log_likelihood=emission.empty_log_likelihood,
                occupied_log_likelihood=emission.occupied_log_likelihood,
            )
        self._posterior = self._message.occupancy_posterior()

    def _ensure_replay(
        self,
        receive_at: datetime,
    ) -> RetainedReplayCoordinator[FactorChainReplayState, FactorChainReplayState]:
        require_utc(receive_at, "Exact observation receive time")
        if self._replay is None:
            watermark = receive_at - MAX_ACCEPTED_LATENESS
            base = FactorChainReplayState(self._chain, self._episodes.states)
            self._replay = RetainedReplayCoordinator(
                MAX_ACCEPTED_LATENESS,
                watermark,
                watermark,
                base,
            )
        return self._replay

    def _apply_replay_state(
        self,
        state: FactorChainReplayState,
        watermark: datetime,
    ) -> None:
        self._arrival_supported_cache = None
        projected, consumed = self._reducer.advance(state, watermark)
        if self._replay is not None:
            self._replay.register_consumed_endpoints(consumed)
            self._replay.replace_replay_result(projected)
        self._chain = projected.chain
        self._posterior = self._chain.posterior
        self._episodes.restore_snapshot(projected.episode_states)
        self._process_finalized_prediction_support(watermark)

    def _process_finalized_prediction_support(self, watermark: datetime) -> None:
        if self._chain.unresolved_endpoint_count:
            return
        message = self._chain.finalized_support_message()
        supports = {
            support
            for key, _ in message.entries
            for support in key.supports
            if support.support_event_id
            not in self._processed_prediction_support_ids
        }
        def support_mass(support: SupportEventAtom) -> float:
            def contains_support(
                key: AugmentedStateKey,
                target: SupportEventAtom = support,
            ) -> bool:
                return target in key.supports

            return message.support_probability(contains_support)

        weighted = tuple(
            (support, support_mass(support))
            for support in sorted(supports, key=lambda item: item.support_event_id)
        )
        if not weighted:
            self._predictions.expire(watermark)
            return
        self._predictions.apply_finalized_supports(weighted, watermark)
        self._predictions.learn_finalized_supports(weighted)
        self._processed_prediction_support_ids = frozenset(
            {
                *self._processed_prediction_support_ids,
                *(support.support_event_id for support, _ in weighted),
            }
        )

    def _compact_replay(
        self,
        replay: RetainedReplayCoordinator[
            FactorChainReplayState,
            FactorChainReplayState,
        ],
        current: FactorChainReplayState,
    ) -> FactorChainReplayState:
        posterior_at = replay.posterior_event_at
        if posterior_at is None:
            return current
        through = min(replay.watermark, posterior_at)
        if through <= replay.finalized_base_through:
            return current
        prefix = tuple(
            item for item in replay.retained if item.event.event_at <= through
        )
        folded = self._reducer.reduce(replay.finalized_base, prefix)
        finalized, consumed = self._reducer.advance(folded, through)
        replay.commit_finalized_base(
            finalized,
            through,
            consumed,
            preserve_checkpoint=(
                not prefix
                and finalized.chain is replay.finalized_base.chain
                and finalized.episode_states == replay.finalized_base.episode_states
                and finalized.dispositions == replay.finalized_base.dispositions
            ),
        )
        projected, projected_consumed = self._reducer.advance(current, through)
        replay.register_consumed_endpoints(projected_consumed)
        replay.replace_replay_result(projected)
        return projected

    def _reset_reducer_for_message(self) -> None:
        self._arrival_supported_cache = None
        self._posterior = self._message.occupancy_posterior()
        self._reducer = FactorChainEventReducer(self._map, self._posterior.space)
        self._chain = ExactFactorChain(
            self._posterior,
            operators=self._reducer.operators,
        )
        self._reset_replay()

    def _reset_replay(self) -> None:
        self._replay = None

    def _clear_current_arrival(self) -> None:
        self._current_arrival_factors = ()
        self._arrival_supported_cache = None

    def _accept_count_control(self, now: datetime, evidence_id: str) -> bool:
        require_utc(now, "Exact count control time")
        if not evidence_id:
            raise ValueError("Exact count evidence ID must be non-empty")
        if evidence_id in self._count_evidence_ids:
            self._event_disposition = "duplicate_count_control"
            return False
        if (
            self._latest_count_control_at is not None
            and now <= self._latest_count_control_at
        ):
            self._event_disposition = "stale_count_control"
            return False
        return True

    def _commit_count_control(self, now: datetime, evidence_id: str) -> None:
        self._count_evidence_ids = self._count_evidence_ids.union((evidence_id,))
        self._latest_count_control_at = now

    def _encode_replay_state(self, state: FactorChainReplayState) -> object:
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(state.episode_states)
        return {
            "chain": _encode_chain(state.chain),
            "episodes": episodes.serialize(),
            "dispositions": [list(item) for item in state.dispositions],
        }

    def _encode_audit_replay_state(
        self,
        state: FactorChainReplayState,
        sparse_vectors: dict[int, dict[str, object]],
        sparse_entries: dict[
            bytes,
            list[tuple[CompactLogPosterior, list[object]]],
        ],
    ) -> object:
        episodes = ObservationEpisodes(self._map)
        episodes.restore_snapshot(state.episode_states)
        return {
            "chain": _encode_audit_chain(
                state.chain,
                sparse_vectors,
                sparse_entries,
            ),
            "episodes": episodes.serialize(),
            "dispositions": [list(item) for item in state.dispositions],
        }

    def _decode_replay_state(
        self,
        payload: object,
        space: StateSpace,
        operators: CompleteMoveOperators,
    ) -> FactorChainReplayState:
        if not isinstance(payload, Mapping):
            raise TypeError("Exact replay fold state must be a mapping")
        chain = _decode_chain(payload.get("chain"), space, operators)
        episodes = ObservationEpisodes(self._map)
        episodes.restore(payload.get("episodes"))
        raw_dispositions = payload.get("dispositions")
        if not isinstance(raw_dispositions, list):
            raise ValueError("Exact replay dispositions must be a list")
        dispositions: list[tuple[str, str]] = []
        for raw in raw_dispositions:
            if (
                not isinstance(raw, list)
                or len(raw) != 2
                or not all(isinstance(value, str) and value for value in raw)
            ):
                raise ValueError("Exact replay disposition is invalid")
            dispositions.append((raw[0], raw[1]))
        return FactorChainReplayState(chain, episodes.states, tuple(dispositions))


def _arrival_supported_probabilities(
    chain: ExactFactorChain,
    corroborations: tuple[_ArrivalCorroboration, ...],
    latest_factors: Mapping[str, EndpointFactor] | None = None,
) -> dict[str, float]:
    probabilities: dict[str, float] = {}
    for zone, factor in (
        _latest_arrival_factors(chain) if latest_factors is None else latest_factors
    ).items():
        target_index = factor.target_index
        endpoint_id = factor.endpoint.token_id

        target_occupied = _target_occupied_predicate(target_index)

        queries = [
            (
                lambda atom: atom.disposition
                in {"graph_valid", "censored_graph_path", "unlocated"},
                target_occupied,
            )
        ]
        terminal_queries = [
            (
                lambda alternative: alternative.disposition
                in {"graph_valid", "censored_graph_path", "unlocated"},
                target_occupied,
            )
        ]
        independently_corroborated = any(
            state.zone == zone
            and state.current_positive
            and state.episode_id is not None
            and state.node_id != factor.endpoint.node_id
            and state.episode_id != endpoint_id
            for state in corroborations
        )
        if independently_corroborated:
            queries.append(
                (
                    lambda atom: atom.disposition == "stay",
                    target_occupied,
                )
            )
            terminal_queries.append(
                (
                    lambda alternative: alternative.disposition == "stay",
                    target_occupied,
                )
            )
            for alternative in factor.alternatives:
                source_index = alternative.source_index
                if (
                    alternative.disposition != "missed_movement"
                    or source_index is None
                ):
                    continue

                queries.append(
                    (
                        _assignment_alternative_predicate(
                            alternative.alternative_id
                        ),
                        _strict_relocation_predicate(
                            source_index,
                            target_index,
                        ),
                    )
                )
                terminal_queries.append(
                    (
                        _terminal_alternative_predicate(
                            alternative.alternative_id
                        ),
                        _strict_relocation_predicate(
                            source_index,
                            target_index,
                        ),
                    )
                )
        query_probabilities = (
            chain.terminal_alternative_and_configuration_probabilities(
                endpoint_id,
                terminal_queries,
            )
            if chain.steps and chain.steps[-1] is factor
            else chain.assignment_and_terminal_probabilities(endpoint_id, queries)
        )
        probability = math.fsum(
            query_probabilities
        )
        if probability < -1e-12 or probability > 1.0 + 1e-12:
            raise ValueError("Arrival-supported probability is out of range")
        probabilities[zone] = min(1.0, max(0.0, probability))
    return probabilities


def _assignment_alternative_predicate(
    alternative_id: str,
) -> Callable[[EndpointAssignmentAtom], bool]:
    def matches(atom: EndpointAssignmentAtom) -> bool:
        return atom.alternative_id == alternative_id

    return matches


def _terminal_alternative_predicate(
    alternative_id: str,
) -> Callable[[EndpointAlternative], bool]:
    def matches(alternative: EndpointAlternative) -> bool:
        return alternative.alternative_id == alternative_id

    return matches


def _strict_relocation_predicate(
    source_index: int,
    target_index: int,
) -> Callable[[tuple[int, ...]], bool]:
    def matches(configuration: tuple[int, ...]) -> bool:
        return (
            configuration[source_index] == 0
            and configuration[target_index] > 0
        )

    return matches


def _target_occupied_predicate(
    target_index: int,
) -> Callable[[tuple[int, ...]], bool]:
    def matches(configuration: tuple[int, ...]) -> bool:
        return configuration[target_index] > 0

    return matches


def _latest_arrival_factors(
    chain: ExactFactorChain,
) -> dict[str, EndpointFactor]:
    latest: dict[str, EndpointFactor] = {}
    for step in chain.steps:
        if not isinstance(step, EndpointFactor):
            continue
        current = latest.get(step.target_zone)
        if current is None or (
            step.endpoint.event_at,
            step.endpoint.token_id,
        ) > (
            current.endpoint.event_at,
            current.endpoint.token_id,
        ):
            latest[step.target_zone] = step
    return latest


def _event_id(event: OccupancyEvent) -> str:
    return f"{event.entity_id}@{event.event_at.isoformat()}:{event.state}"


def _endpoint_id(event: OccupancyEvent) -> str:
    return f"{event.node_id}@{event.event_at.isoformat()}"


def _encode_chain(chain: ExactFactorChain) -> dict[str, object]:
    return {
        "occupants": chain.space.occupants,
        "base": list(chain.base),
        "base_message": _encode_message(chain.base_message),
        "posterior": list(chain.posterior),
        "steps": [_encode_factor_step(step) for step in chain.steps],
    }


def _encode_audit_chain(
    chain: ExactFactorChain,
    sparse_vectors: dict[int, dict[str, object]],
    sparse_entries: dict[
        bytes,
        list[tuple[CompactLogPosterior, list[object]]],
    ],
) -> dict[str, object]:
    return {
        "occupants": chain.space.occupants,
        "base": _encode_sparse_log_vector(
            chain.base,
            sparse_vectors,
            sparse_entries,
        ),
        "base_message": _encode_message(chain.base_message),
        "posterior": _encode_sparse_log_vector(
            chain.posterior,
            sparse_vectors,
            sparse_entries,
        ),
        "steps": [_encode_factor_step(step) for step in chain.steps],
    }


def _encode_sparse_log_vector(
    values: CompactLogPosterior,
    sparse_vectors: dict[int, dict[str, object]],
    sparse_entries: dict[
        bytes,
        list[tuple[CompactLogPosterior, list[object]]],
    ],
) -> dict[str, object]:
    identity = id(values)
    cached = sparse_vectors.get(identity)
    if cached is not None:
        return cached
    candidates = sparse_entries.setdefault(values.exact_digest(), [])
    shared_entries = next(
        (
            entries
            for candidate, entries in candidates
            if values.exact_values_equal(candidate)
        ),
        None,
    )
    if shared_entries is None:
        shared_entries = [
            [rank, value]
            for rank, value in enumerate(values)
            if value != -math.inf
        ]
        candidates.append((values, shared_entries))
    encoded: dict[str, object] = {
        "encoding": "sparse-log-vector-v1",
        "length": len(values),
        "default": {"__exact_float__": "negative_infinity"},
        "entries": shared_entries,
    }
    sparse_vectors[identity] = encoded
    return encoded


def _decode_chain(
    payload: object,
    space: StateSpace,
    operators: CompleteMoveOperators,
) -> ExactFactorChain:
    if not isinstance(payload, Mapping):
        raise TypeError("Exact factor chain must be a mapping")
    if payload.get("occupants") != space.occupants:
        raise ValueError("Exact factor-chain occupant count is invalid")
    raw_base = payload.get("base")
    raw_base_message = payload.get("base_message")
    raw_posterior = payload.get("posterior")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("Exact factor-chain state is invalid")
    base = CompactLogPosterior.from_normalized(
        space,
        _decode_log_vector(raw_base, space),
    )
    base_message = _decode_message(raw_base_message, space)
    reconstructed = ExactFactorChain(
        base,
        tuple(_decode_factor_step(step) for step in raw_steps),
        operators,
        base_message=base_message,
    )
    return reconstructed.with_persisted_posterior(
        CompactLogPosterior.from_normalized(
            space,
            _decode_log_vector(raw_posterior, space),
        )
    )


def _decode_log_vector(
    value: object,
    space: StateSpace,
) -> list[float] | array[float]:
    if isinstance(value, list):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("Exact factor-chain state is invalid")
    if (
        value.get("encoding") != "sparse-log-vector-v1"
        or value.get("length") != len(space)
        or value.get("default") != -math.inf
    ):
        raise ValueError("Exact sparse log vector is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Exact sparse log vector is invalid")
    output = array("d", [-math.inf]) * len(space)
    previous_rank = -1
    for entry in entries:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], int)
            or isinstance(entry[0], bool)
            or not previous_rank < entry[0] < len(space)
            or not isinstance(entry[1], int | float)
            or isinstance(entry[1], bool)
            or not math.isfinite(entry[1])
        ):
            raise ValueError("Exact sparse log vector is invalid")
        rank = entry[0]
        output[rank] = float(entry[1])
        previous_rank = rank
    return output


def _encode_factor_step(step: ZoneLikelihoodStep | EndpointFactor) -> object:
    if isinstance(step, ZoneLikelihoodStep):
        return {
            "kind": "likelihood",
            "zone_index": step.zone_index,
            "empty_log_likelihood": step.empty_log_likelihood,
            "occupied_log_likelihood": step.occupied_log_likelihood,
            "event_at": step.event_at.isoformat(),
        }
    return {
        "kind": "endpoint",
        "endpoint_id": step.endpoint.token_id,
        "node_id": step.endpoint.node_id,
        "event_at": step.endpoint.event_at.isoformat(),
        "target_index": step.target_index,
        "target_zone": step.target_zone,
        "alternatives": [_encode_alternative(alt) for alt in step.alternatives],
        "empty_log_likelihood": step.empty_log_likelihood,
        "occupied_log_likelihood": step.occupied_log_likelihood,
        "reserved_source_indexes": sorted(step.reserved_source_indexes),
    }


def _latest_audit_context_at(
    policy: PosteriorEventPolicy | None,
) -> datetime | None:
    if policy is None:
        return None
    return max(
        (
            entry.decision_at
            for entry in policy.audit
            if entry.context is not None
        ),
        default=None,
    )


def _decode_factor_step(payload: object) -> ZoneLikelihoodStep | EndpointFactor:
    if not isinstance(payload, Mapping):
        raise ValueError("Exact factor step must be a mapping")
    kind = payload.get("kind")
    if kind == "likelihood":
        return ZoneLikelihoodStep(
            _required_int(payload.get("zone_index"), "likelihood zone"),
            _required_number(
                payload.get("empty_log_likelihood"),
                "empty likelihood",
            ),
            _required_number(
                payload.get("occupied_log_likelihood"),
                "occupied likelihood",
            ),
            _required_datetime(payload.get("event_at"), "likelihood event time"),
        )
    if kind != "endpoint":
        raise ValueError("Exact factor step kind is invalid")
    raw_alternatives = payload.get("alternatives")
    if not isinstance(raw_alternatives, list):
        raise ValueError("Exact endpoint alternatives are invalid")
    return EndpointFactor(
        EndpointToken(
            _required_string(payload.get("endpoint_id"), "endpoint ID"),
            _required_string(payload.get("node_id"), "endpoint node"),
            _required_datetime(payload.get("event_at"), "endpoint event time"),
        ),
        _required_int(payload.get("target_index"), "endpoint target"),
        _required_string(payload.get("target_zone"), "endpoint target zone"),
        tuple(_decode_alternative(alt) for alt in raw_alternatives),
        _required_number(payload.get("empty_log_likelihood"), "empty likelihood"),
        _required_number(
            payload.get("occupied_log_likelihood"),
            "occupied likelihood",
        ),
        frozenset(
            _required_int(index, "endpoint reserved source")
            for index in _optional_int_list(
                payload.get("reserved_source_indexes"),
                "endpoint reserved sources",
            )
        ),
    )


def _encode_alternative(alternative: EndpointAlternative) -> dict[str, object]:
    return {
        "alternative_id": alternative.alternative_id,
        "disposition": alternative.disposition,
        "source_index": alternative.source_index,
        "source_node_id": alternative.source_node_id,
        "route_nodes": list(alternative.route_nodes),
        "log_weight": alternative.log_weight,
        "deadline": alternative.deadline.isoformat(),
        "evidence_ids": list(alternative.evidence_ids),
    }


def _decode_alternative(payload: object) -> EndpointAlternative:
    if not isinstance(payload, Mapping):
        raise ValueError("Exact endpoint alternative must be a mapping")
    source_index = payload.get("source_index")
    source_node_id = payload.get("source_node_id")
    return EndpointAlternative(
        _required_string(payload.get("alternative_id"), "alternative ID"),
        _decode_disposition(payload.get("disposition")),
        None
        if source_index is None
        else _required_int(source_index, "alternative source"),
        None
        if source_node_id is None
        else _required_string(source_node_id, "alternative source node"),
        _string_tuple(payload.get("route_nodes"), "alternative route nodes"),
        _required_number(payload.get("log_weight"), "alternative log weight"),
        _required_datetime(payload.get("deadline"), "alternative deadline"),
        _string_tuple(payload.get("evidence_ids"), "alternative evidence IDs"),
    )


def _encode_message(message: AugmentedLogMessage) -> dict[str, object]:
    return {
        "occupants": message.space.occupants,
        "entries": [
            {
                "occupancy_rank": key.occupancy_rank,
                "contexts": [_encode_assignment(atom) for atom in key.contexts],
                "supports": [_encode_support(atom) for atom in key.supports],
                "log_mass": log_mass,
            }
            for key, log_mass in message.entries
        ],
    }


def _decode_message(payload: object, space: StateSpace) -> AugmentedLogMessage:
    if not isinstance(payload, Mapping):
        raise TypeError("Exact augmented message must be a mapping")
    if payload.get("occupants") != space.occupants:
        raise ValueError("Exact augmented message occupant count is invalid")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Exact augmented message entries must be a list")
    entries: list[tuple[AugmentedStateKey, float]] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("Exact augmented entry must be a mapping")
        rank = raw.get("occupancy_rank")
        log_mass = raw.get("log_mass")
        contexts = raw.get("contexts")
        supports = raw.get("supports")
        if (
            not isinstance(rank, int)
            or isinstance(rank, bool)
            or not isinstance(log_mass, int | float)
            or isinstance(log_mass, bool)
            or not isinstance(contexts, list)
            or not isinstance(supports, list)
        ):
            raise ValueError("Exact augmented entry is invalid")
        entries.append(
            (
                AugmentedStateKey(
                    rank,
                    tuple(_decode_assignment(atom) for atom in contexts),
                    tuple(_decode_support(atom) for atom in supports),
                ),
                float(log_mass),
            )
        )
    return AugmentedLogMessage(space, entries)


def _encode_assignment(atom: EndpointAssignmentAtom) -> dict[str, object]:
    return {
        "endpoint_id": atom.endpoint_id,
        "alternative_id": atom.alternative_id,
        "disposition": atom.disposition,
        "predecessor_rank": atom.predecessor_rank,
        "successor_rank": atom.successor_rank,
        "source_index": atom.source_index,
        "target_index": atom.target_index,
        "source_node_id": atom.source_node_id,
        "target_node_id": atom.target_node_id,
        "route_nodes": list(atom.route_nodes),
        "deadline": atom.deadline.isoformat(),
        "evidence_ids": list(atom.evidence_ids),
    }


def _decode_assignment(payload: object) -> EndpointAssignmentAtom:
    if not isinstance(payload, Mapping):
        raise ValueError("Exact assignment atom must be a mapping")
    disposition = _decode_disposition(payload.get("disposition"))
    source_index = payload.get("source_index")
    source_node_id = payload.get("source_node_id")
    return EndpointAssignmentAtom(
        _required_string(payload.get("endpoint_id"), "assignment endpoint"),
        _required_string(payload.get("alternative_id"), "assignment alternative"),
        disposition,
        _required_int(payload.get("predecessor_rank"), "assignment predecessor"),
        _required_int(payload.get("successor_rank"), "assignment successor"),
        None
        if source_index is None
        else _required_int(source_index, "assignment source"),
        _required_int(payload.get("target_index"), "assignment target"),
        None
        if source_node_id is None
        else _required_string(source_node_id, "assignment source node"),
        _required_string(payload.get("target_node_id"), "assignment target node"),
        _string_tuple(payload.get("route_nodes"), "assignment route nodes"),
        _required_datetime(payload.get("deadline"), "assignment deadline"),
        _string_tuple(payload.get("evidence_ids"), "assignment evidence IDs"),
    )


def _encode_support(atom: SupportEventAtom) -> dict[str, object]:
    return {
        "support_event_id": atom.support_event_id,
        "disposition": atom.disposition,
        "origin_zone": atom.origin_zone,
        "destination_zone": atom.destination_zone,
        "route_nodes": list(atom.route_nodes),
        "endpoint_ids": list(atom.endpoint_ids),
        "episode_ids": list(atom.episode_ids),
        "valid_from": atom.valid_from.isoformat(),
        "valid_until": atom.valid_until.isoformat(),
        "learning_eligible": atom.learning_eligible,
    }


def _decode_support(payload: object) -> SupportEventAtom:
    if not isinstance(payload, Mapping):
        raise ValueError("Exact support atom must be a mapping")
    learning_eligible = payload.get("learning_eligible")
    if not isinstance(learning_eligible, bool):
        raise ValueError("Exact support eligibility is invalid")
    return SupportEventAtom(
        _required_string(payload.get("support_event_id"), "support event"),
        _decode_disposition(payload.get("disposition")),
        _required_string(payload.get("origin_zone"), "support origin"),
        _required_string(payload.get("destination_zone"), "support destination"),
        _string_tuple(payload.get("route_nodes"), "support route nodes"),
        _string_tuple(payload.get("endpoint_ids"), "support endpoint IDs"),
        _string_tuple(payload.get("episode_ids"), "support episode IDs"),
        _required_datetime(payload.get("valid_from"), "support validity start"),
        _required_datetime(payload.get("valid_until"), "support validity end"),
        learning_eligible,
    )


def _decode_disposition(value: object) -> MovementDisposition:
    if not isinstance(value, str) or value not in _MOVEMENT_DISPOSITIONS:
        raise ValueError("Exact movement disposition is invalid")
    return cast(MovementDisposition, value)


def _encode_prediction_lease(lease: PredictionLease) -> dict[str, object]:
    return {
        "path_key": list(lease.path_key),
        "target_zone": lease.target_zone,
        "probability": lease.probability,
        "expires_at": lease.expires_at.isoformat(),
        "reason": lease.reason,
    }


def _encode_support_result(result: InjectiveSupportResult) -> dict[str, object]:
    return {
        "probability": result.probability,
        "strata": [
            {
                "occupancy_rank": stratum.occupancy_rank,
                "probability": stratum.probability,
                "qualifies": stratum.qualifies,
                "matching": [
                    {
                        "destination_zone": slot.destination_zone,
                        "occurrence": slot.occurrence,
                        "support_event_id": slot.support_event_id,
                        "endpoint_ids": list(slot.endpoint_ids),
                        "episode_ids": list(slot.episode_ids),
                    }
                    for slot in stratum.matching
                ],
                "reasons": list(stratum.reasons),
            }
            for stratum in result.strata
        ],
    }


def _encode_policy(policy: PosteriorEventPolicy) -> dict[str, object]:
    return {
        "activation_threshold": policy.activation_threshold,
        "release_threshold": policy.release_threshold,
        "activation_window_seconds": policy.activation_window.total_seconds(),
        "states": {
            zone: _encode_policy_state(state)
            for zone, state in policy.states.items()
        },
        "audit": [_encode_policy_audit_entry(entry) for entry in policy.audit],
    }


def _encode_policy_state(state: ZonePolicyState) -> dict[str, object]:
    return {
        "keep_on": state.keep_on,
        "activation_expires_at": None
        if state.activation_expires_at is None
        else state.activation_expires_at.isoformat(),
        "last_trusted_at": None
        if state.last_trusted_at is None
        else state.last_trusted_at.isoformat(),
        "last_release_cause": None
        if state.last_release_cause is None
        else state.last_release_cause.value,
        "recovery_eligible": state.recovery_eligible,
        "reason": state.reason,
        "evidence_ids": list(state.evidence_ids),
        "blocked_episode_ids": list(state.blocked_episode_ids),
    }


def _encode_policy_audit_entry(
    entry: PosteriorPolicyAuditEntry,
) -> dict[str, object]:
    decision = entry.decision
    return {
        "decision_at": entry.decision_at.isoformat(),
        "zone": decision.zone,
        "action": decision.action,
        "accepted": decision.accepted,
        "reason_code": decision.reason_code,
        "gate_values": dict(decision.gate_values),
        "evidence_ids": list(decision.evidence_ids),
        "prior_active": entry.prior_active,
        "resulting_active": entry.resulting_active,
        "context": stored_policy_audit_context_payload(entry.context),
    }


def _decode_policy_audit_entry(
    value: object,
    validated_contexts: set[bytes] | None = None,
    operators_by_space: dict[
        tuple[tuple[str, ...], int],
        tuple[StateSpace, CompleteMoveOperators],
    ]
    | None = None,
) -> PosteriorPolicyAuditEntry:
    if not isinstance(value, Mapping):
        raise ValueError("Exact policy audit entry is invalid")
    accepted = value.get("accepted")
    prior_active = value.get("prior_active")
    resulting_active = value.get("resulting_active")
    if not all(
        isinstance(flag, bool)
        for flag in (accepted, prior_active, resulting_active)
    ):
        raise ValueError("Exact policy audit flags are invalid")
    accepted = cast(bool, accepted)
    prior_active = cast(bool, prior_active)
    resulting_active = cast(bool, resulting_active)
    raw_gate_values = value.get("gate_values")
    if not isinstance(raw_gate_values, Mapping) or any(
        not isinstance(key, str)
        or not isinstance(gate_value, str | bool | int | float)
        or (
            isinstance(gate_value, int | float)
            and not isinstance(gate_value, bool)
            and not math.isfinite(gate_value)
        )
        for key, gate_value in raw_gate_values.items()
    ):
        raise ValueError("Exact policy audit gates are invalid")
    decision = PolicyDecision(
        _required_string(value.get("zone"), "policy audit zone"),
        _required_string(value.get("action"), "policy audit action"),
        accepted,
        _required_string(value.get("reason_code"), "policy audit reason"),
        dict(raw_gate_values),
        _string_tuple(value.get("evidence_ids"), "policy audit evidence IDs"),
    )
    raw_context = value.get("context")
    context = None
    if raw_context is not None:
        if not isinstance(raw_context, Mapping):
            raise ValueError("Exact policy audit context is invalid")
        context = packed_policy_audit_context_from_storage(raw_context)
        if (
            validated_contexts is None
            or context.compressed_json not in validated_contexts
        ):
            expanded_context = validate_target_policy_audit_context(context)
            _validate_target_policy_audit_semantics(
                expanded_context,
                operators_by_space,
            )
            if validated_contexts is not None:
                validated_contexts.add(context.compressed_json)
    return PosteriorPolicyAuditEntry(
        _required_datetime(value.get("decision_at"), "policy audit time"),
        decision,
        prior_active,
        resulting_active,
        context,
    )


def _validate_target_policy_audit_semantics(
    context: Mapping[str, object],
    operators_by_space: dict[
        tuple[tuple[str, ...], int],
        tuple[StateSpace, CompleteMoveOperators],
    ]
    | None = None,
) -> None:
    zones = context.get("zones")
    occupants = context.get("occupants")
    normalization = context.get("normalization")
    pruned_probability = context.get("pruned_probability")
    arrival_supported = context.get("arrival_supported")
    release_safe = context.get("release_safe")
    if (
        not isinstance(zones, list)
        or not zones
        or any(not isinstance(zone, str) or not zone for zone in zones)
        or len(set(zones)) != len(zones)
        or not isinstance(occupants, int)
        or isinstance(occupants, bool)
        or not 0 <= occupants <= 5
        or not isinstance(normalization, int | float)
        or isinstance(normalization, bool)
        or abs(float(normalization) - 1.0) > 1e-12
        or pruned_probability != 0.0
        or not isinstance(arrival_supported, Mapping)
        or not isinstance(release_safe, Mapping)
    ):
        raise ValueError("Exact policy audit context semantics are invalid")
    operator_key = (tuple(zones), occupants)
    cached = None if operators_by_space is None else operators_by_space.get(
        operator_key
    )
    if cached is None:
        space = StateSpace(tuple(zones), occupants)
        operators = CompleteMoveOperators(space)
        if operators_by_space is not None:
            operators_by_space[operator_key] = (space, operators)
    else:
        space, operators = cached
    chain = _decode_chain(
        context.get("chain"),
        space,
        operators,
    )
    corroborations = _decode_audit_corroborations(context.get("episodes"))
    raw_arrivals = arrival_supported.get("probabilities")
    factors: dict[str, EndpointFactor]
    if context.get("schema") == "exact-policy-audit-v1":
        factors = _latest_arrival_factors(chain)
    else:
        raw_targets = arrival_supported.get("targets")
        if (
            not isinstance(raw_arrivals, Mapping)
            or not isinstance(raw_targets, Mapping)
            or set(raw_targets) != set(raw_arrivals)
        ):
            raise ValueError(
                "Exact policy audit arrival-supported evidence is invalid"
            )
        factors = {}
        for zone, target_id in raw_targets.items():
            if (
                zone not in zones
                or not isinstance(target_id, str)
                or not target_id
            ):
                raise ValueError(
                    "Exact policy audit arrival-supported evidence is invalid"
                )
            matches = tuple(
                step
                for step in chain.steps
                if isinstance(step, EndpointFactor)
                and step.endpoint.token_id == target_id
                and step.target_zone == zone
            )
            if len(matches) != 1:
                raise ValueError(
                    "Exact policy audit arrival-supported evidence is invalid"
                )
            factors[str(zone)] = matches[0]
    expected_arrivals = _arrival_supported_probabilities(
        chain,
        corroborations,
        factors,
    )
    if not isinstance(raw_arrivals, Mapping) or set(raw_arrivals) != set(
        expected_arrivals
    ):
        raise ValueError("Exact policy audit arrival-supported evidence is invalid")
    for zone, expected_probability in expected_arrivals.items():
        actual_probability = raw_arrivals.get(zone)
        if (
            not isinstance(actual_probability, int | float)
            or isinstance(actual_probability, bool)
            or not math.isfinite(actual_probability)
            or abs(float(actual_probability) - expected_probability) > 1e-12
        ):
            raise ValueError("Exact policy audit arrival-supported evidence is invalid")
    probabilities = release_safe.get("probabilities")
    evidence = release_safe.get("evidence")
    if not isinstance(probabilities, Mapping) or not isinstance(evidence, Mapping):
        raise ValueError("Exact policy audit release-safe evidence is invalid")
    raw_zone_evidence = evidence.get("zones")
    if not isinstance(raw_zone_evidence, Mapping):
        raise ValueError("Exact policy audit release-safe evidence is invalid")
    for zone, raw_probability in probabilities.items():
        if (
            zone not in zones
            or not isinstance(raw_probability, int | float)
            or isinstance(raw_probability, bool)
            or not math.isfinite(raw_probability)
            or not 0.0 <= raw_probability <= 1.0
        ):
            raise ValueError("Exact policy audit release-safe evidence is invalid")
        raw_result = raw_zone_evidence.get(zone)
        if not isinstance(raw_result, Mapping):
            raise ValueError("Exact policy audit release-safe evidence is invalid")
        veto = raw_result.get("veto")
        if veto == "sustained_positive":
            if raw_probability != 0.0 or raw_result.get("strata") != []:
                raise ValueError("Exact policy audit release-safe evidence is invalid")
            continue
        raw_result_probability = raw_result.get("probability")
        strata = raw_result.get("strata")
        if (
            not isinstance(raw_result_probability, int | float)
            or isinstance(raw_result_probability, bool)
            or not isinstance(strata, list)
        ):
            raise ValueError("Exact policy audit release-safe evidence is invalid")
        qualifying_masses: list[float] = []
        for stratum in strata:
            if not isinstance(stratum, Mapping):
                raise ValueError("Exact policy audit release-safe evidence is invalid")
            rank = stratum.get("occupancy_rank")
            mass = stratum.get("probability")
            qualifies = stratum.get("qualifies")
            matching = stratum.get("matching")
            reasons = stratum.get("reasons")
            if (
                not isinstance(rank, int)
                or isinstance(rank, bool)
                or not 0 <= rank < len(space)
                or not isinstance(mass, int | float)
                or isinstance(mass, bool)
                or not math.isfinite(mass)
                or not 0.0 <= mass <= 1.0
                or not isinstance(qualifies, bool)
                or not isinstance(matching, list)
                or not isinstance(reasons, list)
                or any(not isinstance(reason, str) for reason in reasons)
            ):
                raise ValueError("Exact policy audit release-safe evidence is invalid")
            if qualifies:
                _validate_support_matching(space, rank, matching)
                if reasons:
                    raise ValueError(
                        "Exact policy audit release-safe evidence is invalid"
                    )
                qualifying_masses.append(float(mass))
            elif matching or not reasons:
                raise ValueError("Exact policy audit release-safe evidence is invalid")
        recomputed = math.fsum(qualifying_masses)
        if (
            abs(recomputed - float(raw_result_probability)) > 1e-12
            or abs(recomputed - float(raw_probability)) > 1e-12
        ):
            raise ValueError("Exact policy audit release-safe evidence is invalid")


def _decode_audit_corroborations(
    value: object,
) -> tuple[_ArrivalCorroboration, ...]:
    if not isinstance(value, list):
        raise ValueError("Exact policy audit episode evidence is invalid")
    output: list[_ArrivalCorroboration] = []
    for raw_state in value:
        if not isinstance(raw_state, Mapping):
            raise ValueError("Exact policy audit episode evidence is invalid")
        zone = raw_state.get("zone")
        node_id = raw_state.get("node_id")
        episode_id = raw_state.get("episode_id")
        current_positive = raw_state.get("current_positive")
        if (
            not isinstance(zone, str)
            or not isinstance(node_id, str)
            or (episode_id is not None and not isinstance(episode_id, str))
            or not isinstance(current_positive, bool)
        ):
            raise ValueError("Exact policy audit episode evidence is invalid")
        output.append(
            _ArrivalCorroboration(
                zone,
                node_id,
                episode_id,
                current_positive,
            )
        )
    return tuple(output)


def _validate_support_matching(
    space: StateSpace,
    occupancy_rank: int,
    matching: list[object],
) -> None:
    configuration = space.unrank(occupancy_rank)
    expected_zones = [
        zone
        for zone, count in zip(
            space.zones,
            configuration[: space.unlocated_index],
            strict=True,
        )
        for _ in range(count)
    ]
    support_ids: list[str] = []
    endpoint_ids: list[str] = []
    episode_ids: list[str] = []
    actual_zones: list[str] = []
    for raw_slot in matching:
        if not isinstance(raw_slot, Mapping):
            raise ValueError("Exact policy audit release-safe evidence is invalid")
        zone = raw_slot.get("destination_zone")
        support_id = raw_slot.get("support_event_id")
        raw_endpoint_ids = raw_slot.get("endpoint_ids")
        raw_episode_ids = raw_slot.get("episode_ids")
        if (
            not isinstance(zone, str)
            or not isinstance(support_id, str)
            or not isinstance(raw_endpoint_ids, list)
            or any(not isinstance(item, str) for item in raw_endpoint_ids)
            or not isinstance(raw_episode_ids, list)
            or any(not isinstance(item, str) for item in raw_episode_ids)
        ):
            raise ValueError("Exact policy audit release-safe evidence is invalid")
        actual_zones.append(zone)
        support_ids.append(support_id)
        endpoint_ids.extend(raw_endpoint_ids)
        episode_ids.extend(raw_episode_ids)
    if (
        actual_zones != expected_zones
        or len(set(support_ids)) != len(support_ids)
        or len(set(endpoint_ids)) != len(endpoint_ids)
        or len(set(episode_ids)) != len(episode_ids)
    ):
        raise ValueError("Exact policy audit release-safe evidence is invalid")


def _decode_policy_state(value: object) -> ZonePolicyState:
    if not isinstance(value, Mapping):
        raise ValueError("Exact policy zone state is invalid")
    keep_on = value.get("keep_on")
    recovery_eligible = value.get("recovery_eligible")
    if not isinstance(keep_on, bool) or not isinstance(recovery_eligible, bool):
        raise ValueError("Exact policy zone flags are invalid")
    raw_cause = value.get("last_release_cause")
    if raw_cause is None:
        cause = None
    elif isinstance(raw_cause, str):
        try:
            cause = ReleaseCause(raw_cause)
        except ValueError as exc:
            raise ValueError("Exact policy release cause is invalid") from exc
    else:
        raise ValueError("Exact policy release cause is invalid")
    return ZonePolicyState(
        keep_on,
        _optional_datetime(
            value.get("activation_expires_at"),
            "policy activation expiry",
        ),
        _optional_datetime(value.get("last_trusted_at"), "policy trusted time"),
        cause,
        recovery_eligible,
        _required_string(value.get("reason"), "policy reason"),
        _string_tuple(value.get("evidence_ids"), "policy evidence IDs"),
        _string_tuple(
            value.get("blocked_episode_ids"),
            "policy blocked episode IDs",
        ),
    )


def _decode_prediction_leases(value: object) -> tuple[PredictionLease, ...]:
    if not isinstance(value, list):
        raise ValueError("Exact prediction leases are invalid")
    leases: list[PredictionLease] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("Exact prediction lease must be a mapping")
        path_key = raw.get("path_key")
        if (
            not isinstance(path_key, list)
            or len(path_key) != 3
            or not isinstance(path_key[0], str)
            or not path_key[0]
            or (path_key[1] is not None and not isinstance(path_key[1], str))
            or not isinstance(path_key[2], str)
            or not path_key[2]
        ):
            raise ValueError("Exact prediction path key is invalid")
        probability = _required_number(
            raw.get("probability"),
            "prediction probability",
        )
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Exact prediction probability is invalid")
        leases.append(
            PredictionLease(
                (path_key[0], path_key[1], path_key[2]),
                _required_string(raw.get("target_zone"), "prediction target"),
                probability,
                _required_datetime(raw.get("expires_at"), "prediction expiry"),
                _required_string(raw.get("reason"), "prediction reason"),
            )
        )
    return tuple(leases)


def _decode_transition_counts(
    value: object,
) -> dict[str, dict[str, float]]:
    if not isinstance(value, Mapping):
        raise ValueError("Exact route transition counts are invalid")
    counts: dict[str, dict[str, float]] = {}
    for source, raw_targets in value.items():
        if not isinstance(source, str) or not source or not isinstance(
            raw_targets, Mapping
        ):
            raise ValueError("Exact route transition counts are invalid")
        targets: dict[str, float] = {}
        for target, raw_count in raw_targets.items():
            if not isinstance(target, str) or not target:
                raise ValueError("Exact route transition target is invalid")
            count = _required_number(raw_count, "route transition count")
            if count < 0.0:
                raise ValueError("Exact route transition count is invalid")
            targets[target] = count
        counts[source] = targets
    return counts


def _decode_route_counts(
    value: object,
) -> dict[tuple[str, ...], dict[str, float]]:
    if not isinstance(value, list):
        raise ValueError("Exact route counts are invalid")
    counts: dict[tuple[str, ...], dict[str, float]] = {}
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("Exact route count must be a mapping")
        prefix = _string_tuple(raw.get("prefix"), "route prefix")
        raw_targets = raw.get("targets")
        if not isinstance(raw_targets, Mapping):
            raise ValueError("Exact route count targets are invalid")
        if prefix in counts:
            raise ValueError("Exact route prefixes must be unique")
        targets: dict[str, float] = {}
        for target, raw_count in raw_targets.items():
            if not isinstance(target, str) or not target:
                raise ValueError("Exact route count target is invalid")
            count = _required_number(raw_count, "route count")
            if count <= 0.0:
                raise ValueError("Exact route count is invalid")
            targets[target] = count
        counts[prefix] = targets
    return counts


def _decode_route_contexts(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ValueError("Exact route contexts are invalid")
    return tuple(_string_tuple(context, "route context") for context in value)


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Exact {label} is invalid")
    return value


def _required_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Exact {label} is invalid")
    return value


def _required_number(value: object, label: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or math.isnan(float(value))
        or float(value) == math.inf
    ):
        raise ValueError(f"Exact {label} is invalid")
    return float(value)


def _optional_int_list(value: object, label: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Exact {label} are invalid")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"Exact {label} are invalid")
    return tuple(value)


def _required_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Exact {label} is invalid")
    try:
        restored = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Exact {label} is invalid") from exc
    require_utc(restored, f"Exact {label}")
    return restored


def _optional_datetime(value: object, label: str) -> datetime | None:
    return None if value is None else _required_datetime(value, label)
