"""Bounded anonymous occupancy support for count-conflict evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from ..const import PRODUCT_MAX_OCCUPANTS
from ..model import PredictiveMap
from .policy import POLICY_CALIBRATIONS
from .profiles import SHARED_PROFILES
from .types import (
    AnonymousOccupancySupport,
    CountSupport,
    EpisodeEffect,
    EpisodeState,
    PhysicalNode,
    SupportTokenBinding,
    SupportTransition,
    SupportTransitionEvent,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
    require_utc,
)

DIAGNOSTIC_COUNTER_LIMIT = 2**31 - 1


class AnonymousSupportTracker:
    """Track count-only movement lineage without occupant identity."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        nodes: Sequence[PhysicalNode],
        *,
        support_limit: int = PRODUCT_MAX_OCCUPANTS,
    ) -> None:
        if support_limit <= 0:
            raise ValueError("Anonymous-support limit must be positive")
        self._map = predictive_map
        self._nodes = {node.node_id: node for node in nodes}
        if len(self._nodes) != len(nodes) or any(
            node_id not in predictive_map.nodes for node_id in self._nodes
        ):
            raise ValueError("Anonymous-support physical nodes are incompatible")
        self._support_limit = support_limit
        self._supports: tuple[AnonymousOccupancySupport, ...] = ()
        self._bindings: tuple[SupportTokenBinding, ...] = ()
        self._latest_transition: SupportTransitionEvent | None = None
        self._advanced_at: datetime | None = None
        self._counters = {
            "support_created": 0,
            "support_transferred": 0,
            "support_coalesced": 0,
            "support_expired": 0,
            "support_stale_binding_ignored": 0,
        }

    @property
    def supports(self) -> tuple[AnonymousOccupancySupport, ...]:
        return self._supports

    @property
    def bindings(self) -> tuple[SupportTokenBinding, ...]:
        return self._bindings

    @property
    def latest_transition(self) -> SupportTransitionEvent | None:
        return self._latest_transition

    @property
    def support_limit(self) -> int:
        return self._support_limit

    @property
    def counters(self) -> dict[str, int]:
        return dict(self._counters)

    def advance(
        self,
        at: datetime,
        episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState],
        active_tokens: Sequence[TraversalToken],
        retained_tokens: Sequence[TraversalToken],
    ) -> SupportTransition:
        next_state = self._advanced_state(
            at,
            episodes,
            beliefs,
            active_tokens,
            retained_tokens,
        )
        return self._commit(next_state, at)

    def apply(
        self,
        at: datetime,
        effect: EpisodeEffect | None,
        authorization: TraversalAuthorization | None,
        issued_target_token: TraversalToken | None,
        episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState],
        active_tokens: Sequence[TraversalToken],
        retained_tokens: Sequence[TraversalToken],
    ) -> SupportTransition:
        next_state = self._advanced_state(
            at,
            episodes,
            beliefs,
            active_tokens,
            retained_tokens,
        )
        if effect is not None and effect.kind in {"interaction", "positive"}:
            next_state = self._rebind_settled_endpoint(
                next_state,
                effect,
                issued_target_token,
                at,
            )
        if (
            effect is None
            or effect.kind not in {"interaction", "positive"}
            or authorization is None
            or not authorization.authorized
            or issued_target_token is None
        ):
            return self._commit(next_state, at)
        self._validate_application(effect, authorization, issued_target_token, at)

        supports = {item.support_id: item for item in next_state.supports}
        bindings = {item.token_id: item.support_id for item in next_state.bindings}
        source_ids: set[str] = set()
        ineligible_source_token_ids: set[str] = set()
        stale_source_token_ids: set[str] = set()
        path_source_nodes = frozenset(authorization.path_node_ids[:-1])
        for token in authorization.source_tokens:
            if token.node_id not in path_source_nodes:
                ineligible_source_token_ids.add(token.token_id)
                continue
            source_id, stale = self._binding_authority(token, supports, bindings)
            if source_id is not None:
                source_ids.add(source_id)
            elif stale:
                ineligible_source_token_ids.add(token.token_id)
                stale_source_token_ids.add(token.token_id)
        selected_source_ids = tuple(sorted(source_ids))
        latest = next_state.latest_transition
        support_id: str | None = None
        if selected_source_ids:
            support_id, supports, bindings, latest = self._coalesce(
                selected_source_ids,
                supports,
                bindings,
                at,
                "source_set_merge",
            )
            source = supports[support_id]
            settled = self._settlement_eligible(
                issued_target_token,
                episodes,
                beliefs,
            )
            transition = "settled" if settled else "advanced"
            supports[support_id] = AnonymousOccupancySupport(
                support_id,
                "settled" if settled else "moving",
                source.created_at,
                at,
                issued_target_token.episode_id,
                issued_target_token.node_id,
                issued_target_token.zone,
                issued_target_token.path_node_ids,
                issued_target_token.provenance_kind,
                None if settled else issued_target_token.valid_until,
                transition,
            )
            latest = SupportTransitionEvent(
                support_id,
                at,
                transition,
                "authorized_target",
                selected_source_ids if len(selected_source_ids) > 1 else (),
            )
        elif (
            len(supports) < self._support_limit
            and self._confirmed_strength(issued_target_token)
            and self._settlement_eligible(issued_target_token, episodes, beliefs)
        ):
            support_id = f"support:{issued_target_token.token_id}"
            supports[support_id] = AnonymousOccupancySupport(
                support_id,
                "settled",
                issued_target_token.accepted_at,
                at,
                issued_target_token.episode_id,
                issued_target_token.node_id,
                issued_target_token.zone,
                issued_target_token.path_node_ids,
                issued_target_token.provenance_kind,
                None,
                "created",
            )
            latest = SupportTransitionEvent(
                support_id,
                at,
                "created",
                "confirmed_stay",
            )

        if support_id is not None:
            for token in (*authorization.source_tokens, issued_target_token):
                if token.token_id in ineligible_source_token_ids:
                    continue
                bindings[token.token_id] = support_id
        supports, bindings, latest = self._coalesce_current_components(
            supports,
            bindings,
            active_tokens,
            at,
            latest,
        )
        supports, bindings, latest = self._coalesce_settled_zones(
            supports,
            bindings,
            at,
            latest,
        )
        return self._commit(
            self._transition(supports, bindings, latest),
            at,
            stale_binding_ignored=len(stale_source_token_ids),
        )

    def clear(
        self,
        at: datetime,
        reason: str = "count_zero",
    ) -> SupportTransition:
        self._validate_time(at)
        latest = None
        if self._supports:
            latest = SupportTransitionEvent(
                self._supports[0].support_id,
                at,
                "removed",
                reason,
            )
        return self._commit(SupportTransition((), (), latest), at)

    def restore(
        self,
        supports: tuple[AnonymousOccupancySupport, ...],
        bindings: tuple[SupportTokenBinding, ...],
        at: datetime,
    ) -> None:
        self._validate_time(at)
        candidate = SupportTransition(supports, bindings)
        if len(candidate.supports) > self._support_limit:
            raise ValueError("Anonymous-support restore exceeds its bound")
        for support in candidate.supports:
            if support.updated_at > at or not self._path_compatible(
                support.path_node_ids
            ):
                raise ValueError("Anonymous-support restore is incompatible")
            node = self._nodes.get(support.current_node_id)
            if node is None or node.zone != support.current_zone:
                raise ValueError("Anonymous-support endpoint is incompatible")
            if support.state == "moving" and support.valid_until is not None:
                if support.valid_until <= at:
                    raise ValueError("Moving support is expired at restore")
        self._supports = candidate.supports
        self._bindings = candidate.bindings
        self._latest_transition = None
        self._advanced_at = at
        self._counters = dict.fromkeys(self._counters, 0)

    def count_supports(self) -> tuple[CountSupport, ...]:
        return tuple(
            CountSupport(
                support.support_id,
                support.current_node_id,
                support.current_zone,
                support.path_node_ids,
            )
            for support in self._supports
        )

    def _rebind_settled_endpoint(
        self,
        state: SupportTransition,
        effect: EpisodeEffect,
        issued_target_token: TraversalToken | None,
        at: datetime,
    ) -> SupportTransition:
        matches = tuple(
            support
            for support in state.supports
            if support.state == "settled"
            and support.current_node_id == effect.node_id
            and support.current_zone == effect.zone
        )
        if len(matches) != 1 or matches[0].current_episode_id == effect.episode_id:
            return state
        support = matches[0]
        supports = {item.support_id: item for item in state.supports}
        supports[support.support_id] = replace(
            support,
            updated_at=at,
            current_episode_id=effect.episode_id,
            last_transition="settled",
        )
        bindings = {
            item.token_id: item.support_id for item in state.bindings
        }
        if issued_target_token is not None:
            bindings[issued_target_token.token_id] = support.support_id
        return self._transition(
            supports,
            bindings,
            SupportTransitionEvent(
                support.support_id,
                at,
                "settled",
                "same_endpoint_reassertion",
            ),
        )

    def _advanced_state(
        self,
        at: datetime,
        episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState],
        active_tokens: Sequence[TraversalToken],
        retained_tokens: Sequence[TraversalToken],
    ) -> SupportTransition:
        self._validate_time(at)
        state_by_node = self._unique_by(episodes, "node_id", "episode")
        belief_by_zone = self._unique_by(beliefs, "zone", "belief")
        all_tokens = (*active_tokens, *retained_tokens)
        token_by_id = self._unique_by(all_tokens, "token_id", "traversal token")

        supports: dict[str, AnonymousOccupancySupport] = {}
        latest = self._latest_transition
        for support in self._supports:
            remove_reason: str | None = None
            if support.state == "moving":
                if support.valid_until is None or support.valid_until <= at:
                    remove_reason = "moving_expiry"
            elif not self._settled_support_valid(
                support,
                state_by_node,
                belief_by_zone,
                allow_episode_rebind=True,
            ):
                remove_reason = self._settled_removal_reason(
                    support,
                    state_by_node,
                    belief_by_zone,
                )
            if remove_reason is None:
                supports[support.support_id] = support
            else:
                latest = SupportTransitionEvent(
                    support.support_id,
                    at,
                    "removed",
                    remove_reason,
                )

        bindings = {
            item.token_id: item.support_id
            for item in self._bindings
            if item.token_id in token_by_id and item.support_id in supports
        }
        supports, bindings, latest = self._coalesce_current_components(
            supports,
            bindings,
            active_tokens,
            at,
            latest,
        )
        supports, bindings, latest = self._coalesce_settled_zones(
            supports,
            bindings,
            at,
            latest,
        )
        return self._transition(supports, bindings, latest)

    def _settlement_eligible(
        self,
        token: TraversalToken,
        episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState],
    ) -> bool:
        state_by_node = self._unique_by(episodes, "node_id", "episode")
        belief_by_zone = self._unique_by(beliefs, "zone", "belief")
        support = AnonymousOccupancySupport(
            f"support:{token.token_id}",
            "settled",
            token.accepted_at,
            token.accepted_at,
            token.episode_id,
            token.node_id,
            token.zone,
            token.path_node_ids,
            token.provenance_kind,
            None,
            "settled",
        )
        return self._settled_support_valid(support, state_by_node, belief_by_zone)

    def _settled_support_valid(
        self,
        support: AnonymousOccupancySupport,
        state_by_node: Mapping[str, EpisodeState],
        belief_by_zone: Mapping[str, ZoneBeliefState],
        *,
        allow_episode_rebind: bool = False,
    ) -> bool:
        node = self._nodes.get(support.current_node_id)
        state = state_by_node.get(support.current_node_id)
        belief = belief_by_zone.get(support.current_zone)
        return bool(
            node is not None
            and node.zone == support.current_zone
            and SHARED_PROFILES[node.profile_name].role == "stay"
            and state is not None
            and (
                allow_episode_rebind
                or state.episode_id == support.current_episode_id
            )
            and state.status in {"asserted", "clearing", "clear"}
            and not state.health_warning
            and not state.cadence_warning
            and belief is not None
            and not belief.health_warning
            and (
                state.status != "clear"
                or (
                    belief.outward_context is None
                    and belief.context != "cleared_with_outward"
                )
            )
            and belief.probability
            >= POLICY_CALIBRATIONS[node.profile_name].on_threshold
        )

    def _settled_removal_reason(
        self,
        support: AnonymousOccupancySupport,
        state_by_node: Mapping[str, EpisodeState],
        belief_by_zone: Mapping[str, ZoneBeliefState],
    ) -> str:
        state = state_by_node.get(support.current_node_id)
        belief = belief_by_zone.get(support.current_zone)
        if state is None or state.status == "unavailable":
            return "unavailable"
        if state.health_warning or (belief is not None and belief.health_warning):
            return "health_warning"
        if state.cadence_warning:
            return "cadence_warning"
        if state.status == "clear" and (
            belief is None
            or belief.outward_context is not None
            or belief.context == "cleared_with_outward"
        ):
            return "outward_clear"
        if state.status not in {"asserted", "clearing"}:
            return "belief_below_threshold"
        return "belief_below_threshold"

    def _coalesce_current_components(
        self,
        supports: dict[str, AnonymousOccupancySupport],
        bindings: dict[str, str],
        active_tokens: Sequence[TraversalToken],
        at: datetime,
        latest: SupportTransitionEvent | None,
    ) -> tuple[
        dict[str, AnonymousOccupancySupport],
        dict[str, str],
        SupportTransitionEvent | None,
    ]:
        groups: list[list[TraversalToken]] = []
        confirmed = sorted(
            (token for token in active_tokens if self._confirmed_strength(token)),
            key=lambda token: token.token_id,
        )
        for token in confirmed:
            connected = [
                index
                for index, group in enumerate(groups)
                if self._connected_paths(
                    token.path_node_ids,
                    tuple(node for item in group for node in item.path_node_ids),
                )
            ]
            if not connected:
                groups.append([token])
                continue
            first = connected[0]
            groups[first].append(token)
            for index in reversed(connected[1:]):
                groups[first].extend(groups.pop(index))
        for group in groups:
            support_ids = tuple(
                sorted(
                    {
                        support_id
                        for token in group
                        if (
                            support_id := self._binding_authority(
                                token,
                                supports,
                                bindings,
                            )[0]
                        )
                        is not None
                    }
                )
            )
            if len(support_ids) > 1:
                _winner, supports, bindings, latest = self._coalesce(
                    support_ids,
                    supports,
                    bindings,
                    at,
                    "connected_component",
                )
        return supports, bindings, latest

    @staticmethod
    def _binding_authority(
        token: TraversalToken,
        supports: Mapping[str, AnonymousOccupancySupport],
        bindings: Mapping[str, str],
    ) -> tuple[str | None, bool]:
        support_id = bindings.get(token.token_id)
        support = None if support_id is None else supports.get(support_id)
        if support is None:
            return None, False
        if token.accepted_at < support.updated_at:
            return None, True
        return support_id, False

    def _coalesce_settled_zones(
        self,
        supports: dict[str, AnonymousOccupancySupport],
        bindings: dict[str, str],
        at: datetime,
        latest: SupportTransitionEvent | None,
    ) -> tuple[
        dict[str, AnonymousOccupancySupport],
        dict[str, str],
        SupportTransitionEvent | None,
    ]:
        by_zone: dict[str, list[str]] = {}
        for support in supports.values():
            if support.state == "settled":
                by_zone.setdefault(support.current_zone, []).append(support.support_id)
        for support_ids in by_zone.values():
            if len(support_ids) > 1:
                _winner, supports, bindings, latest = self._coalesce(
                    tuple(sorted(support_ids)),
                    supports,
                    bindings,
                    at,
                    "same_zone",
                )
        return supports, bindings, latest

    def _coalesce(
        self,
        support_ids: tuple[str, ...],
        supports: dict[str, AnonymousOccupancySupport],
        bindings: dict[str, str],
        at: datetime,
        reason: str,
    ) -> tuple[
        str,
        dict[str, AnonymousOccupancySupport],
        dict[str, str],
        SupportTransitionEvent,
    ]:
        present = tuple(
            support_id for support_id in support_ids if support_id in supports
        )
        if not present:
            raise ValueError("Support coalescence requires a current support")
        winner = min(present)
        endpoint = max(
            (supports[support_id] for support_id in present),
            key=lambda support: (support.updated_at, support.support_id),
        )
        supports[winner] = replace(
            endpoint,
            support_id=winner,
            created_at=min(supports[value].created_at for value in present),
            updated_at=max(at, endpoint.updated_at),
            last_transition="coalesced",
        )
        for support_id in present:
            if support_id != winner:
                supports.pop(support_id)
        for token_id, support_id in tuple(bindings.items()):
            if support_id in present:
                bindings[token_id] = winner
        event = SupportTransitionEvent(
            winner,
            at,
            "coalesced",
            reason,
            tuple(sorted(present)),
        )
        return winner, supports, bindings, event

    def _transition(
        self,
        supports: Mapping[str, AnonymousOccupancySupport],
        bindings: Mapping[str, str],
        latest: SupportTransitionEvent | None,
    ) -> SupportTransition:
        if len(supports) > self._support_limit:
            raise ValueError("Anonymous-support state exceeds its bound")
        return SupportTransition(
            tuple(supports[support_id] for support_id in sorted(supports)),
            tuple(
                SupportTokenBinding(token_id, bindings[token_id])
                for token_id in sorted(bindings)
            ),
            latest,
        )

    def _commit(
        self,
        transition: SupportTransition,
        at: datetime,
        *,
        stale_binding_ignored: int = 0,
    ) -> SupportTransition:
        previous = {support.support_id: support for support in self._supports}
        current = {support.support_id: support for support in transition.supports}
        self._increment_counter(
            "support_created",
            len(set(current) - set(previous)),
        )
        self._increment_counter(
            "support_transferred",
            sum(
                previous[support_id].current_node_id
                != current[support_id].current_node_id
                for support_id in set(previous) & set(current)
            ),
        )
        self._increment_counter(
            "support_expired",
            sum(
                support_id not in current
                and support.state == "moving"
                and support.valid_until is not None
                and support.valid_until <= at
                for support_id, support in previous.items()
            ),
        )
        latest = transition.latest_transition
        if latest is not self._latest_transition and latest is not None:
            self._increment_counter(
                "support_coalesced",
                max(0, len(latest.coalesced_support_ids) - 1),
            )
        self._increment_counter(
            "support_stale_binding_ignored",
            stale_binding_ignored,
        )
        self._supports = transition.supports
        self._bindings = transition.bindings
        self._latest_transition = latest
        self._advanced_at = at
        return transition

    def _increment_counter(self, name: str, amount: int) -> None:
        self._counters[name] = min(
            DIAGNOSTIC_COUNTER_LIMIT,
            self._counters[name] + amount,
        )

    def _validate_application(
        self,
        effect: EpisodeEffect,
        authorization: TraversalAuthorization,
        token: TraversalToken,
        at: datetime,
    ) -> None:
        if (
            effect.at != at
            or authorization.authorized_at != at
            or token.accepted_at != at
            or effect.episode_id != authorization.target_episode_id
            or effect.episode_id != token.episode_id
            or effect.node_id != authorization.target_node_id
            or effect.node_id != token.node_id
            or effect.zone != authorization.target_zone
            or effect.zone != token.zone
            or authorization.path_node_ids != token.path_node_ids
            or authorization.provenance_kind != token.provenance_kind
        ):
            raise ValueError("Anonymous-support application inputs are inconsistent")

    def _validate_time(self, at: datetime) -> None:
        require_utc(at, "Anonymous-support frontier")
        if self._advanced_at is not None and at < self._advanced_at:
            raise ValueError("Anonymous-support frontier cannot move backward")

    def _path_compatible(self, path: Sequence[str]) -> bool:
        return bool(
            path
            and len(path) <= 3
            and all(node_id in self._nodes for node_id in path)
            and all(
                right in self._map.neighbors(left)
                for left, right in zip(path, path[1:], strict=False)
            )
        )

    def _connected_paths(
        self,
        left: Sequence[str],
        right: Sequence[str],
    ) -> bool:
        right_nodes = set(right)
        return bool(
            set(left) & right_nodes
            or any(
                neighbor in right_nodes
                for node_id in left
                for neighbor in self._map.neighbors(node_id)
            )
        )

    def _confirmed_strength(self, token: TraversalToken) -> bool:
        return bool(
            (
                token.track_confidence == "confirmed"
                and token.provenance_kind == "adjacent"
                and len(token.path_node_ids) == 3
                and len(set(token.path_node_ids)) == 3
                and self._path_compatible(token.path_node_ids)
            )
            or (
                token.equivalent_confirmed_strength
                and (
                    (
                        token.provenance_kind in {"boundary", "missed_edge"}
                        and self._path_compatible(token.path_node_ids)
                    )
                    or (
                        token.provenance_kind == "local_interaction"
                        and len(token.path_node_ids) == 1
                    )
                )
            )
        )

    @staticmethod
    def _unique_by[T](
        items: Sequence[T],
        attribute: str,
        label: str,
    ) -> dict[str, T]:
        result = {str(getattr(item, attribute)): item for item in items}
        if len(result) != len(items):
            raise ValueError(f"Anonymous-support {label} inputs must be unique")
        return result
