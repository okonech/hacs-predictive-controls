"""Bounded anonymous traversal frontier and graph authorization."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from ..model import PredictiveMap
from .filter import ZoneBeliefFilter
from .profiles import SHARED_PROFILES
from .types import (
    AuthorizationUse,
    CountState,
    EpisodeEffect,
    EpisodeState,
    PendingAcquisitionCandidate,
    PhysicalNode,
    TraversalAuthorization,
    TraversalToken,
    require_utc,
)

TOKEN_LIMIT = 64
USE_LIMIT = 256


class TraversalFrontier:
    """Retain finite episode tokens without occupant identity or global use."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        nodes: Sequence[PhysicalNode],
        *,
        token_limit: int = TOKEN_LIMIT,
        use_limit: int = USE_LIMIT,
    ) -> None:
        if token_limit <= 0 or use_limit <= 0:
            raise ValueError("Traversal bounds must be positive")
        self._map = predictive_map
        self._nodes = {node.node_id: node for node in nodes}
        if len(self._nodes) != len(nodes):
            raise ValueError("Traversal physical nodes must be unique")
        if any(node_id not in predictive_map.nodes for node_id in self._nodes):
            raise ValueError("Traversal physical node is absent from the map")
        self._token_limit = token_limit
        self._use_limit = use_limit
        self._tokens: dict[str, TraversalToken] = {}
        self._retained: dict[str, TraversalToken] = {}
        self._current: set[str] = set()
        self._uses: dict[tuple[str, str], AuthorizationUse] = {}
        self._pending_by_zone: dict[str, PendingAcquisitionCandidate] = {}
        self._expired_pending: dict[
            tuple[str, str], PendingAcquisitionCandidate
        ] = {}
        self._advanced_at: datetime | None = None

    @property
    def tokens(self) -> tuple[TraversalToken, ...]:
        return tuple(sorted(self._tokens.values(), key=lambda item: item.token_id))

    @property
    def retained_tokens(self) -> tuple[TraversalToken, ...]:
        """Authorized but currently unusable episode lineage."""

        return tuple(sorted(self._retained.values(), key=lambda item: item.token_id))

    @property
    def uses(self) -> tuple[AuthorizationUse, ...]:
        return tuple(
            sorted(
                self._uses.values(),
                key=lambda item: (
                    item.authorized_at,
                    item.token_id,
                    item.target_episode_id,
                ),
            )
        )

    @property
    def current_token_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._current))

    @property
    def pending_candidates(self) -> tuple[PendingAcquisitionCandidate, ...]:
        return tuple(
            self._pending_by_zone[zone] for zone in sorted(self._pending_by_zone)
        )

    def take_expired_pending(self) -> tuple[PendingAcquisitionCandidate, ...]:
        """Drain candidates that crossed their deadline since the last operation."""

        expired = tuple(
            sorted(
                self._expired_pending.values(),
                key=lambda item: (item.expires_at, item.zone, item.node_id),
            )
        )
        self._expired_pending.clear()
        return expired

    def restore_snapshot(
        self,
        tokens: tuple[TraversalToken, ...],
        current_token_ids: tuple[str, ...],
        uses: tuple[AuthorizationUse, ...],
        at: datetime,
        pending_candidates: tuple[PendingAcquisitionCandidate, ...] = (),
        retained_tokens: tuple[TraversalToken, ...] = (),
    ) -> None:
        self.validate_time(at)
        restored_tokens = {token.token_id: token for token in tokens}
        restored_retained = {token.token_id: token for token in retained_tokens}
        if (
            len(restored_tokens) != len(tokens)
            or len(restored_retained) != len(retained_tokens)
            or set(restored_tokens) & set(restored_retained)
            or len(tokens) + len(retained_tokens) > self._token_limit
        ):
            raise ValueError("Traversal token snapshot is duplicated or exceeds bounds")
        for token in tokens:
            node = self._nodes.get(token.node_id)
            if (
                node is None
                or token.zone != node.zone
                or token.profile_name != node.profile_name
                or token.role != SHARED_PROFILES[node.profile_name].role
                or token.token_id != f"{token.node_id}:{token.episode_id}"
                or token.accepted_at > at
                or token.valid_until <= at
                or not self._token_timing_valid(token)
                or token.path_node_ids[-1] != token.node_id
            ):
                raise ValueError("Traversal token snapshot is incompatible")
        for token in retained_tokens:
            node = self._nodes.get(token.node_id)
            continuity_until = self._continuity_until(token)
            if (
                node is None
                or token.zone != node.zone
                or token.profile_name != node.profile_name
                or token.role != SHARED_PROFILES[node.profile_name].role
                or token.token_id != f"{token.node_id}:{token.episode_id}"
                or token.accepted_at > at
                or token.valid_until > at
                or continuity_until <= at
                or not self._token_timing_valid(token)
                or token.path_node_ids[-1] != token.node_id
            ):
                raise ValueError("Retained traversal snapshot is incompatible")
        current = set(current_token_ids)
        if len(current) != len(current_token_ids) or not current <= set(
            restored_tokens
        ):
            raise ValueError("Current traversal token snapshot is incompatible")
        restored_uses = {(use.token_id, use.target_episode_id): use for use in uses}
        if len(restored_uses) != len(uses) or len(uses) > self._use_limit:
            raise ValueError("Traversal use snapshot is duplicated or exceeds bounds")
        known_token_ids = set(restored_tokens) | set(restored_retained)
        if any(
            use.token_id not in known_token_ids or use.authorized_at > at
            for use in uses
        ):
            raise ValueError("Traversal use snapshot is incompatible")
        pending_by_zone = {item.zone: item for item in pending_candidates}
        if len(pending_by_zone) != len(pending_candidates):
            raise ValueError("Pending candidate snapshot is duplicated")
        for candidate in pending_candidates:
            node = self._nodes.get(candidate.node_id)
            if (
                node is None
                or node.zone != candidate.zone
                or node.profile_name != candidate.profile_name
                or candidate.created_at > at
                or candidate.expires_at <= at
            ):
                raise ValueError("Pending candidate snapshot is incompatible")
        self._tokens = restored_tokens
        self._retained = restored_retained
        self._current = current
        self._uses = restored_uses
        self._pending_by_zone = pending_by_zone
        self._advanced_at = at

    def reopen_authorized_continuity(
        self,
        state: EpisodeState,
        effect: EpisodeEffect,
    ) -> bool:
        """Reopen one authorized correlated episode without adding evidence."""

        self.advance(effect.at)
        self._validated_episode(state)
        if (
            effect.kind != "correlated_flap_ignored"
            or effect.node_id != state.node_id
            or effect.zone != state.zone
            or effect.episode_id != state.episode_id
            or state.status != "asserted"
            or state.health_warning
            or state.cadence_warning
            or state.hold_until is None
            or effect.at < state.hold_until
            or state.assertion_trust_until is None
            or effect.at >= state.assertion_trust_until
        ):
            return False
        token_id = f"{state.node_id}:{state.episode_id}"
        token = self._tokens.get(token_id)
        if token is not None:
            self._current.add(token_id)
            return True
        token = self._retained.pop(token_id, None)
        if token is None:
            return False
        valid_until = min(
            effect.at + SHARED_PROFILES[state.profile_name].traversal_context_window,
            state.assertion_trust_until,
        )
        self._tokens[token_id] = replace(
            token,
            valid_until=valid_until,
            continuity_reopened_at=effect.at,
        )
        self._current.add(token_id)
        self._enforce_token_bound()
        return True

    def issue(
        self,
        state: EpisodeState,
        effect: EpisodeEffect,
        authorization: TraversalAuthorization,
    ) -> TraversalToken:
        self.advance(effect.at)
        node = self._validated_episode(state)
        if (
            effect.kind not in {"interaction", "positive"}
            or effect.node_id != state.node_id
            or effect.episode_id != state.episode_id
            or state.status not in {"asserted", "clearing"}
            or state.traversal_valid_until is None
            or state.traversal_valid_until <= effect.at
            or not authorization.authorized
            or authorization.target_episode_id != effect.episode_id
            or authorization.track_confidence is None
            or authorization.provenance_kind is None
        ):
            raise ValueError(
                "Traversal token requires an authorized current positive episode"
            )
        token_id = f"{state.node_id}:{state.episode_id}"
        existing = self._tokens.get(token_id)
        if existing is not None:
            return existing
        token = TraversalToken(
            token_id,
            state.node_id,
            state.zone,
            SHARED_PROFILES[node.profile_name].role,
            state.profile_name,
            state.episode_id or "",
            effect.at,
            state.traversal_valid_until,
            authorization.track_confidence,
            authorization.path_node_ids,
            authorization.provenance_kind,
            authorization.equivalent_confirmed_strength,
        )
        self._tokens[token_id] = token
        self._current.add(token_id)
        self._enforce_token_bound()
        return token

    def authorize_interaction(
        self,
        target: EpisodeState,
        at: datetime,
    ) -> TraversalAuthorization:
        """Authorize one trustworthy local human-interaction pulse."""

        self.advance(at)
        self._validated_episode(target)
        if (
            target.status != "clearing"
            or target.episode_id is None
            or target.started_at != at
            or target.traversal_valid_until is None
            or target.traversal_valid_until <= at
            or target.health_warning
            or target.cadence_warning
        ):
            raise ValueError("Interaction authorization requires a fresh pulse")
        self._pending_by_zone.pop(target.zone, None)
        return TraversalAuthorization(
            target.node_id,
            target.zone,
            target.episode_id,
            at,
            True,
            "local_interaction",
            (),
            (),
            "provisional",
            (target.node_id,),
            "local_interaction",
            True,
        )

    def sync(self, state: EpisodeState, at: datetime) -> None:
        self.advance(at)
        self._validated_episode(state)
        if state.status in {"degraded", "unavailable"} or state.cadence_warning:
            self._pending_by_zone = {
                zone: candidate
                for zone, candidate in self._pending_by_zone.items()
                if candidate.node_id != state.node_id
            }
            token_ids = tuple(
                token_id
                for token_id, token in (*self._tokens.items(), *self._retained.items())
                if token.node_id == state.node_id
            )
            for token_id in token_ids:
                self._remove_token(token_id)
            return
        token_id = f"{state.node_id}:{state.episode_id}"
        if token_id not in self._tokens:
            return
        if state.status == "asserted" and not state.health_warning:
            self._current.add(token_id)
        else:
            self._current.discard(token_id)

    def authorize(
        self,
        target: EpisodeState,
        at: datetime,
        *,
        count: CountState | None,
        corroborating_states: Sequence[EpisodeState] = (),
    ) -> TraversalAuthorization:
        self.advance(at)
        target_node = self._validated_episode(target)
        if target.status != "asserted" or target.episode_id is None:
            raise ValueError("Traversal target must be a current positive episode")
        if not self._target_trustworthy(target, at):
            return TraversalAuthorization(
                target.node_id,
                target.zone,
                target.episode_id,
                at,
                False,
                "untracked_rejected",
            )
        source_states: dict[tuple[str, str], EpisodeState] = {}
        for state in corroborating_states:
            if state.episode_id is None:
                continue
            key = (state.node_id, state.episode_id)
            if key in source_states:
                raise ValueError(
                    "Corroborating episode states contain duplicate identity"
                )
            source_states[key] = state
        return self._authorize_from_context(
            target,
            target_node,
            at,
            count=count,
            remember_pending=True,
            fallback_reason="track_bootstrap_pending",
            source_states=source_states,
        )

    def authorize_correlated_target(
        self,
        target: EpisodeState,
        at: datetime,
    ) -> TraversalAuthorization:
        """Authorize correlated target evidence without creating source authority."""

        self.advance(at)
        target_node = self._validated_episode(target)
        if (
            target.status != "asserted"
            or target.episode_id is None
            or not target.cadence_correlated
        ):
            raise ValueError("Correlated traversal target must be a current episode")
        if not self._target_trustworthy(
            target,
            at,
            allow_cadence_warning=True,
        ):
            return TraversalAuthorization(
                target.node_id,
                target.zone,
                target.episode_id,
                at,
                False,
                "untracked_rejected",
            )
        return self._authorize_from_context(
            target,
            target_node,
            at,
            count=None,
            remember_pending=False,
            fallback_reason="untracked_rejected",
            source_states={},
        )

    def _authorize_from_context(
        self,
        target: EpisodeState,
        target_node: PhysicalNode,
        at: datetime,
        *,
        count: CountState | None,
        remember_pending: bool,
        fallback_reason: str,
        source_states: Mapping[tuple[str, str], EpisodeState],
    ) -> TraversalAuthorization:
        assert target.episode_id is not None
        target_episode_id = target.episode_id
        candidates = tuple(
            token for token in self.tokens if token.episode_id != target_episode_id
        )
        reason = fallback_reason
        sources: tuple[TraversalToken, ...] = ()
        confidence: str | None = None
        path: tuple[str, ...] = ()
        provenance: str | None = None
        equivalent_strength = False
        same_zone = tuple(
            token
            for token in candidates
            if token.zone == target.zone and token.node_id != target.node_id
        )
        adjacent = tuple(
            token
            for token in candidates
            if target.node_id in self._map.neighbors(token.node_id)
        )
        adjacent_current = tuple(
            token
            for token in adjacent
            if token.token_id in self._current and token.role in {"entry", "transition"}
        )
        missed = tuple(
            token
            for token in candidates
            if token not in adjacent
            and self._missed_edge(
                token,
                target.node_id,
                at,
                source_states.get((token.node_id, token.episode_id)),
            )
        )
        linked_episode_ids = {
            use.target_episode_id
            for use in self._uses.values()
            if use.token_id
            in {token.token_id for token in (*same_zone, *adjacent_current, *adjacent)}
            and use.target_episode_id != target_episode_id
        }
        linked = tuple(
            token for token in candidates if token.episode_id in linked_episode_ids
        )
        if same_zone:
            reason = "same_zone_authorized"
            direct_sources = self._unique_tokens(same_zone)
            source = self._best_token(direct_sources)
            sources = self._unique_tokens((*direct_sources, *linked))
            if target.node_id in self._map.neighbors(source.node_id):
                confidence, path = self._advance_path(source, target.node_id)
            else:
                confidence, path = "provisional", (target.node_id,)
            provenance = "same_zone"
        elif adjacent_current:
            direct_sources = self._unique_tokens(adjacent_current)
            source = self._best_token(direct_sources)
            sources = self._unique_tokens((*direct_sources, *linked))
            confidence, path = self._advance_path(source, target.node_id)
            reason = (
                "track_confirmed"
                if confidence == "confirmed"
                and source.track_confidence == "provisional"
                else "adjacent_authorized"
            )
            provenance = "adjacent"
        elif adjacent:
            direct_sources = self._unique_tokens(adjacent)
            source = self._best_token(direct_sources)
            sources = self._unique_tokens((*direct_sources, *linked))
            confidence, path = self._advance_path(source, target.node_id)
            reason = (
                "track_confirmed"
                if confidence == "confirmed"
                and source.track_confidence == "provisional"
                else "adjacent_authorized"
            )
            provenance = "adjacent"
        elif self._boundary_authorized(target_node, at, count):
            reason = "boundary_authorized"
            confidence, path, provenance = (
                "provisional",
                (target.node_id,),
                "boundary",
            )
            self._pending_by_zone.pop(target.zone, None)
        elif missed:
            sources = self._unique_tokens(missed)
            source = self._best_token(sources)
            confidence, path = self._advance_path(source, target.node_id)
            reason = "missed_edge_authorized"
            provenance = "missed_edge"
        elif (pending := self._pending_support(target, at)) is not None:
            self._pending_by_zone.pop(pending.zone, None)
            if pending.zone == target.zone:
                source = self._issue_pending_token(pending, target.node_id)
                sources = (source,)
                reason = "same_zone_authorized"
                confidence, path, provenance = (
                    "provisional",
                    (target.node_id,),
                    "same_zone",
                )
            else:
                source = self._issue_pending_token(pending, target.node_id)
                sources = (source,)
                reason = "provisional_track_acquired"
                confidence, path, provenance = (
                    "provisional",
                    (pending.node_id, target.node_id),
                    "adjacent_pair",
                )
        elif remember_pending:
            self._remember_pending(target, at, target_node.reliability)
        authorized = confidence is not None
        if authorized:
            self._pending_by_zone.pop(target.zone, None)
        new_uses: list[AuthorizationUse] = []
        if authorized:
            for token in sources:
                key = (token.token_id, target_episode_id)
                if key in self._uses:
                    continue
                use = AuthorizationUse(token.token_id, target_episode_id, reason, at)
                self._uses[key] = use
                new_uses.append(use)
            self._enforce_use_bound()
        return TraversalAuthorization(
            target.node_id,
            target.zone,
            target_episode_id,
            at,
            authorized,
            reason,
            sources,
            tuple(new_uses),
            confidence,
            path,
            provenance,
            equivalent_strength,
        )

    def _remember_pending(
        self,
        target: EpisodeState,
        at: datetime,
        reliability: float,
    ) -> None:
        assert target.episode_id is not None
        assert target.traversal_valid_until is not None
        profile = SHARED_PROFILES[target.profile_name]
        self._pending_by_zone[target.zone] = PendingAcquisitionCandidate(
            target.node_id,
            target.zone,
            target.profile_name,
            target.episode_id,
            at,
            at + profile.track_bootstrap_window,
            target.traversal_valid_until,
            reliability,
        )

    @staticmethod
    def _target_trustworthy(
        target: EpisodeState,
        at: datetime,
        *,
        allow_cadence_warning: bool = False,
    ) -> bool:
        return bool(
            target.status == "asserted"
            and not target.health_warning
            and (allow_cadence_warning or not target.cadence_warning)
            and target.started_at is not None
            and target.traversal_valid_until is not None
            and target.started_at <= at < target.traversal_valid_until
        )

    def _pending_support(
        self, target: EpisodeState, at: datetime
    ) -> PendingAcquisitionCandidate | None:
        candidates = tuple(
            item
            for item in self.pending_candidates
            if item.episode_id != target.episode_id
            and item.node_id != target.node_id
            and item.created_at <= at < item.expires_at
            and (
                item.zone == target.zone
                or target.node_id in self._map.neighbors(item.node_id)
            )
        )
        return min(
            candidates,
            key=lambda item: (item.created_at, item.node_id),
            default=None,
        )

    def _issue_pending_token(
        self,
        pending: PendingAcquisitionCandidate,
        target_node_id: str,
    ) -> TraversalToken:
        token_id = f"{pending.node_id}:{pending.episode_id}"
        existing = self._tokens.get(token_id)
        if existing is not None:
            return existing
        token = TraversalToken(
            token_id,
            pending.node_id,
            pending.zone,
            SHARED_PROFILES[pending.profile_name].role,
            pending.profile_name,
            pending.episode_id,
            pending.created_at,
            pending.traversal_valid_until,
            "provisional",
            (pending.node_id,),
            "adjacent_pair",
        )
        self._tokens[token_id] = token
        self._enforce_token_bound()
        return token

    @staticmethod
    def _best_token(tokens: Sequence[TraversalToken]) -> TraversalToken:
        return max(
            tokens,
            key=lambda token: (
                token.track_confidence == "confirmed",
                token.accepted_at,
                token.token_id,
            ),
        )

    def _advance_path(
        self, source: TraversalToken, target_node_id: str
    ) -> tuple[str, tuple[str, ...]]:
        sequence = (*source.path_node_ids, target_node_id)[-3:]
        distinct = len(set(sequence))
        confidence = (
            "confirmed"
            if source.track_confidence == "confirmed" or distinct >= 3
            else "provisional"
        )
        return confidence, sequence

    @staticmethod
    def _unique_tokens(tokens: Sequence[TraversalToken]) -> tuple[TraversalToken, ...]:
        return tuple(
            sorted(
                {token.token_id: token for token in tokens}.values(),
                key=lambda token: token.token_id,
            )
        )

    def validate_time(self, at: datetime) -> None:
        require_utc(at, "Traversal frontier time")
        if self._advanced_at is not None and at < self._advanced_at:
            raise ValueError("Traversal frontier cannot move backward")

    def advance(self, at: datetime) -> None:
        self.validate_time(at)
        expired = tuple(
            token_id
            for token_id, token in self._tokens.items()
            if token.valid_until <= at
        )
        for token_id in expired:
            token = self._tokens.pop(token_id)
            self._current.discard(token_id)
            if at < self._continuity_until(token):
                self._retained[token_id] = token
            else:
                self._remove_uses(token_id)
        expired_retained = tuple(
            token_id
            for token_id, token in self._retained.items()
            if self._continuity_until(token) <= at
        )
        for token_id in expired_retained:
            self._remove_token(token_id)
        expired_pending = tuple(
            candidate
            for candidate in self._pending_by_zone.values()
            if candidate.expires_at <= at
        )
        for candidate in expired_pending:
            self._expired_pending[(candidate.zone, candidate.episode_id)] = candidate
        self._pending_by_zone = {
            zone: candidate
            for zone, candidate in self._pending_by_zone.items()
            if candidate.expires_at > at
        }
        self._advanced_at = at

    def clear(self, at: datetime) -> None:
        self.advance(at)
        self._tokens.clear()
        self._retained.clear()
        self._current.clear()
        self._uses.clear()
        self._pending_by_zone.clear()
        self._expired_pending.clear()

    @staticmethod
    def apply_outward_context(
        authorization: TraversalAuthorization,
        filters: Mapping[str, ZoneBeliefFilter],
        at: datetime,
        target_valid_until: datetime | None = None,
    ) -> tuple[tuple[str, str], ...]:
        if not authorization.authorized:
            return ()
        registrations: list[tuple[str, str]] = []
        for token in authorization.source_tokens:
            source_filter = filters.get(token.zone)
            if source_filter is None:
                raise ValueError("Traversal source zone has no belief filter")
            if source_filter.state.generation_episode_id != token.episode_id:
                continue
            valid_until = max(
                token.valid_until,
                token.valid_until if target_valid_until is None else target_valid_until,
            )
            source_filter.register_outward(token.episode_id, valid_until, at)
            registrations.append((token.zone, token.episode_id))
        return tuple(registrations)

    def _boundary_authorized(
        self,
        target: PhysicalNode,
        at: datetime,
        count: CountState | None,
    ) -> bool:
        return bool(
            count is not None
            and count.expected_count > 0
            and count.positive_transition_at is not None
            and count.positive_transition_until is not None
            and count.positive_transition_at <= at < count.positive_transition_until
            and SHARED_PROFILES[target.profile_name].role == "entry"
        )

    def _missed_edge(
        self,
        token: TraversalToken,
        target_node_id: str,
        at: datetime,
        source_state: EpisodeState | None,
    ) -> bool:
        departure_at = token.accepted_at
        if (
            source_state is not None
            and source_state.status in {"clearing", "clear"}
            and source_state.last_event_at is not None
            and token.accepted_at < source_state.last_event_at <= at
        ):
            departure_at = source_state.last_event_at
        elapsed = (at - departure_at).total_seconds()
        queue = deque(((token.node_id, 0, 0.0),))
        visited = {token.node_id}
        while queue:
            node_id, hops, path_seconds = queue.popleft()
            if hops == 2:
                continue
            for neighbor in sorted(self._map.neighbors(node_id)):
                if neighbor in visited:
                    continue
                seconds = self._map.transition_seconds_between_nodes(node_id, neighbor)
                if seconds is None:
                    continue
                total = path_seconds + seconds
                if neighbor == target_node_id and hops + 1 == 2:
                    return elapsed <= total
                visited.add(neighbor)
                queue.append((neighbor, hops + 1, total))
        return False

    def _validated_episode(self, state: EpisodeState) -> PhysicalNode:
        node = self._nodes.get(state.node_id)
        if (
            node is None
            or node.zone != state.zone
            or node.profile_name != state.profile_name
        ):
            raise ValueError("Episode state is incompatible with traversal nodes")
        return node

    def _remove_token(self, token_id: str) -> None:
        self._tokens.pop(token_id, None)
        self._retained.pop(token_id, None)
        self._current.discard(token_id)
        self._remove_uses(token_id)

    def _remove_uses(self, token_id: str) -> None:
        self._uses = {
            key: use for key, use in self._uses.items() if use.token_id != token_id
        }

    def _enforce_token_bound(self) -> None:
        while len(self._tokens) + len(self._retained) > self._token_limit:
            if self._retained:
                oldest = min(
                    self._retained.values(),
                    key=lambda item: (self._continuity_until(item), item.token_id),
                )
            else:
                oldest = min(
                    self._tokens.values(),
                    key=lambda item: (item.valid_until, item.token_id),
                )
            self._remove_token(oldest.token_id)

    @staticmethod
    def _continuity_until(token: TraversalToken) -> datetime:
        return (
            token.accepted_at
            + SHARED_PROFILES[token.profile_name].assertion_trust_horizon
        )

    @staticmethod
    def _token_timing_valid(token: TraversalToken) -> bool:
        profile = SHARED_PROFILES[token.profile_name]
        trust_until = token.accepted_at + profile.assertion_trust_horizon
        reopened_at = token.continuity_reopened_at
        if reopened_at is None:
            expected = min(
                token.accepted_at + profile.traversal_context_window,
                trust_until,
            )
        else:
            if not (
                token.accepted_at + profile.hardware_hold_interval
                <= reopened_at
                < trust_until
            ):
                return False
            expected = min(
                reopened_at + profile.traversal_context_window,
                trust_until,
            )
        return token.valid_until == expected

    def _enforce_use_bound(self) -> None:
        while len(self._uses) > self._use_limit:
            oldest = min(
                self._uses.values(),
                key=lambda item: (
                    item.authorized_at,
                    item.token_id,
                    item.target_episode_id,
                ),
            )
            self._uses.pop((oldest.token_id, oldest.target_episode_id))
