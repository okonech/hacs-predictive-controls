"""Bounded anonymous traversal frontier and graph authorization."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime

from ..model import PredictiveMap
from .filter import ZoneBeliefFilter
from .profiles import SHARED_PROFILES
from .types import (
    AuthorizationUse,
    CountState,
    EpisodeEffect,
    EpisodeState,
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
        self._current: set[str] = set()
        self._uses: dict[tuple[str, str], AuthorizationUse] = {}
        self._advanced_at: datetime | None = None

    @property
    def tokens(self) -> tuple[TraversalToken, ...]:
        return tuple(sorted(self._tokens.values(), key=lambda item: item.token_id))

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

    def restore_snapshot(
        self,
        tokens: tuple[TraversalToken, ...],
        current_token_ids: tuple[str, ...],
        uses: tuple[AuthorizationUse, ...],
        at: datetime,
    ) -> None:
        self.validate_time(at)
        restored_tokens = {token.token_id: token for token in tokens}
        if len(restored_tokens) != len(tokens) or len(tokens) > self._token_limit:
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
            ):
                raise ValueError("Traversal token snapshot is incompatible")
        current = set(current_token_ids)
        if len(current) != len(current_token_ids) or not current <= set(
            restored_tokens
        ):
            raise ValueError("Current traversal token snapshot is incompatible")
        restored_uses = {(use.token_id, use.target_episode_id): use for use in uses}
        if len(restored_uses) != len(uses) or len(uses) > self._use_limit:
            raise ValueError("Traversal use snapshot is duplicated or exceeds bounds")
        if any(
            use.token_id not in restored_tokens or use.authorized_at > at
            for use in uses
        ):
            raise ValueError("Traversal use snapshot is incompatible")
        self._tokens = restored_tokens
        self._current = current
        self._uses = restored_uses
        self._advanced_at = at

    def issue(self, state: EpisodeState, effect: EpisodeEffect) -> TraversalToken:
        self.advance(effect.at)
        node = self._validated_episode(state)
        if (
            effect.kind != "positive"
            or effect.node_id != state.node_id
            or effect.episode_id != state.episode_id
            or state.status != "asserted"
            or state.traversal_valid_until is None
            or state.traversal_valid_until <= effect.at
        ):
            raise ValueError("Traversal token requires a current positive episode")
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
        )
        self._tokens[token_id] = token
        self._current.add(token_id)
        self._enforce_token_bound()
        return token

    def sync(self, state: EpisodeState, at: datetime) -> None:
        self.advance(at)
        self._validated_episode(state)
        token_id = f"{state.node_id}:{state.episode_id}"
        if token_id not in self._tokens:
            return
        if state.status in {"degraded", "unavailable"}:
            self._remove_token(token_id)
        elif state.status == "asserted" and not state.health_warning:
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
        candidates = tuple(
            token for token in self.tokens if token.episode_id != target.episode_id
        )
        reason = "disconnected"
        sources: tuple[TraversalToken, ...] = ()
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
            if token not in adjacent and self._missed_edge(token, target.node_id, at)
        )
        linked_episode_ids = {
            use.target_episode_id
            for use in self._uses.values()
            if use.token_id
            in {token.token_id for token in (*same_zone, *adjacent_current, *adjacent)}
            and use.target_episode_id != target.episode_id
        }
        linked = tuple(
            token for token in candidates if token.episode_id in linked_episode_ids
        )
        if same_zone:
            reason, sources = (
                "same_zone_other_node",
                self._unique_tokens((*same_zone, *adjacent, *missed, *linked)),
            )
        elif adjacent_current:
            reason, sources = (
                "adjacent_current",
                self._unique_tokens((*adjacent_current, *missed, *linked)),
            )
        elif adjacent:
            reason, sources = (
                "adjacent_recent",
                self._unique_tokens((*adjacent, *missed, *linked)),
            )
        elif self._boundary_authorized(target_node, at, count):
            reason = "boundary_reacquisition"
        else:
            if missed:
                reason, sources = "bounded_missed_edge", missed
            elif self._source_free_authorized(target, at, count, corroborating_states):
                reason = "source_free_corroborated"
        authorized = reason != "disconnected"
        new_uses: list[AuthorizationUse] = []
        if authorized:
            for token in sources:
                key = (token.token_id, target.episode_id)
                if key in self._uses:
                    continue
                use = AuthorizationUse(token.token_id, target.episode_id, reason, at)
                self._uses[key] = use
                new_uses.append(use)
            self._enforce_use_bound()
        return TraversalAuthorization(
            target.node_id,
            target.zone,
            target.episode_id,
            at,
            authorized,
            reason,
            sources,
            tuple(new_uses),
        )

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
            self._remove_token(token_id)
        self._advanced_at = at

    def clear(self, at: datetime) -> None:
        self.advance(at)
        self._tokens.clear()
        self._current.clear()
        self._uses.clear()

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

    def _source_free_authorized(
        self,
        target: EpisodeState,
        at: datetime,
        count: CountState | None,
        corroborating_states: Sequence[EpisodeState],
    ) -> bool:
        if (
            count is None
            or count.expected_count <= 0
            or target.health_warning
            or target.started_at is None
            or target.traversal_valid_until is None
            or not target.started_at <= at < target.traversal_valid_until
        ):
            return False
        profile = SHARED_PROFILES[target.profile_name]
        if profile.single_node_reacquisition:
            return True
        return any(
            state.node_id != target.node_id
            and state.zone == target.zone
            and state.status == "asserted"
            and not state.health_warning
            and state.started_at is not None
            and state.started_at <= at
            for state in corroborating_states
        )

    def _missed_edge(
        self, token: TraversalToken, target_node_id: str, at: datetime
    ) -> bool:
        elapsed = (at - token.accepted_at).total_seconds()
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
        self._current.discard(token_id)
        self._uses = {
            key: use for key, use in self._uses.items() if use.token_id != token_id
        }

    def _enforce_token_bound(self) -> None:
        while len(self._tokens) > self._token_limit:
            oldest = min(
                self._tokens.values(),
                key=lambda item: (item.valid_until, item.token_id),
            )
            self._remove_token(oldest.token_id)

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
