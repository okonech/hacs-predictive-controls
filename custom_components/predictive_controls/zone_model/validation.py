"""Pure cross-component checks shared by strict restore and qualification.

These checks do not restore or normalize components, reconcile selection, advance
time, or grant authority. Callers supply immutable snapshot tuples and validated
map/node configuration. Component-local readers still own their own shape checks;
passing this boundary alone does not certify a current-engine snapshot.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from ..const import PRODUCT_MAX_OCCUPANTS
from ..model import PredictiveMap
from .count import SEEN_EVENT_LIMIT
from .policy import POLICY_CALIBRATIONS
from .profiles import ENTRY_BOUNDARY, SHARED_PROFILES
from .supported_gap_acquisition import gap_geometry_valid, original_handoff_valid
from .supports import AnonymousSupportTracker
from .traversal import TraversalFrontier
from .types import (
    CountSupport,
    EpisodeState,
    PhysicalNode,
    TraversalToken,
    ZoneModelSnapshot,
    require_utc,
)


def episode_reference(
    episode_id: str,
    states: Mapping[str, EpisodeState],
    frontier: datetime,
    *,
    exact: bool,
    selected: bool = False,
) -> tuple[EpisodeState, datetime]:
    """Resolve current/historical identity without inventing an episode."""
    for node_id in sorted(states, key=len, reverse=True):
        prefix = f"{node_id}:"
        if not episode_id.startswith(prefix):
            continue
        raw_generation, separator, raw_at = episode_id[len(prefix) :].partition(
            ":"
        )
        try:
            generation = int(raw_generation)
            created_at = datetime.fromisoformat(raw_at)
        except ValueError as exc:
            raise ValueError("Episode reference is malformed") from exc
        require_utc(created_at, "Episode reference time")
        state = states[node_id]
        if (
            not separator
            or not 1 <= generation <= state.generation
            or created_at > frontier
            or (
                generation < state.generation
                and state.started_at is not None
                and (created_at > state.started_at
                    or (created_at == state.started_at and not selected))
            )
            or (
                generation == state.generation
                and state.episode_id != episode_id
            )
            or (exact and state.episode_id != episode_id)
        ):
            raise ValueError("Episode reference is outside stored state")
        return state, created_at
    raise ValueError("Episode reference has no stored physical node")


def bounded_path_step(predictive_map: PredictiveMap, source: str, target: str) -> bool:
    """Preserve the legacy one/two-edge structural path predicate."""
    if source == target:
        return False
    neighbors = set(predictive_map.neighbors(source))
    if target in neighbors:
        return True
    return any(target in predictive_map.neighbors(node_id) for node_id in neighbors)


def direct_different_zone_pair(
    predictive_map: PredictiveMap, path: tuple[str, ...],
) -> bool:
    """A handoff is one physical edge, never a bounded missed-edge path."""
    return bool(
        len(path) == 2
        and path[0] != path[1]
        and all(node_id in predictive_map.nodes for node_id in path)
        and path[1] in predictive_map.neighbors(path[0])
        and predictive_map.nodes[path[0]].occupancy_zone
        != predictive_map.nodes[path[1]].occupancy_zone
    )


@dataclass(frozen=True)
class SnapshotValidator:
    """Read-only dependencies; strength must be the real support predicate.

    ``validate`` preserves the strict reader's complete tail ordering. Individual
    methods expose the same narrower boundaries for component qualifications.
    ``validate_tokens`` returns fresh active/retained indexes for subsequent
    cross-links; it never modifies the supplied snapshot or component trackers.
    """

    predictive_map: PredictiveMap
    nodes: tuple[PhysicalNode, ...]
    confirmed_strength: Callable[[TraversalToken], bool]

    def validate(self, snapshot: ZoneModelSnapshot) -> None:
        """Count control -> tokens -> outward -> uses -> supports -> conflicts."""
        self.validate_count_control(snapshot)
        tokens, retained_tokens = self.validate_tokens(snapshot)
        self.validate_outward(snapshot)
        self.validate_current_pending_uses(snapshot, tokens, retained_tokens)
        self.validate_support_snapshot(snapshot, tokens, retained_tokens)
        self.validate_count_snapshot(snapshot)

    def validate_count_control(self, snapshot: ZoneModelSnapshot) -> None:
        """Check event identity/frontiers and the calibrated count window."""
        at = snapshot.updated_at
        count = snapshot.count_state
        if (count.last_event_at is None) != (count.last_event_id is None):
            raise ValueError("Count snapshot event identity is incomplete")
        if any(
            value is not None and value > at
            for value in (count.last_event_at, count.positive_transition_at)
        ):
            raise ValueError("Count snapshot is newer than its model frontier")
        if (
            count.last_event_id is not None
            and count.last_event_id not in count.seen_event_ids
        ) or len(count.seen_event_ids) > SEEN_EVENT_LIMIT:
            raise ValueError("Count snapshot event sequence is inconsistent")
        if (
            count.positive_transition_at is not None
            and count.positive_transition_until
            != count.positive_transition_at
            + ENTRY_BOUNDARY.traversal_context_window
        ):
            raise ValueError("Count transition expiry is not calibration-derived")

    def validate_tokens(self, snapshot: ZoneModelSnapshot) -> tuple[
        dict[str, TraversalToken], dict[str, TraversalToken],
    ]:
        """Validate actual active/dormant episode-bound token authority."""
        at = snapshot.updated_at
        episodes = {state.node_id: state for state in snapshot.episode_states}
        physical_nodes = {node.node_id: node for node in self.nodes}
        allowed_provenance = {
            "adjacent",
            "adjacent_pair",
            "boundary",
            "local_interaction",
            "missed_edge",
            "same_zone",
            "settled_adjacent_transfer",
            "settled_endpoint",
        }
        tokens = {token.token_id: token for token in snapshot.traversal_tokens}
        retained_tokens = {
            token.token_id: token for token in snapshot.retained_traversal_tokens
        }
        if (
            len(tokens) != len(snapshot.traversal_tokens)
            or len(retained_tokens) != len(snapshot.retained_traversal_tokens)
            or set(tokens) & set(retained_tokens)
        ):
            raise ValueError("Traversal token snapshot is duplicated")
        for token in (
            *snapshot.traversal_tokens,
            *snapshot.retained_traversal_tokens,
        ):
            state, created_at = episode_reference(
                token.episode_id,
                episodes,
                at,
                exact=False,
            )
            profile = SHARED_PROFILES[token.profile_name]
            expected_valid_until = min(
                created_at + profile.traversal_context_window,
                created_at + profile.assertion_trust_horizon,
            )
            trust_until = created_at + profile.assertion_trust_horizon
            reopened_at = token.continuity_reopened_at
            if reopened_at is not None:
                expected_valid_until = min(
                    reopened_at + profile.traversal_context_window,
                    trust_until,
                )
            retained = token.token_id in retained_tokens
            physical_node = physical_nodes[state.node_id]
            interaction_episode = bool(physical_node.interaction_aliases)
            interaction_token = token.provenance_kind == "local_interaction"
            if (
                state.node_id != token.node_id
                or created_at != token.accepted_at
                or token.valid_until != expected_valid_until
                or (
                    reopened_at is not None
                    and not (
                        created_at + profile.hardware_hold_interval
                        <= reopened_at
                        < trust_until
                    )
                )
                or (retained and not token.valid_until <= at < trust_until)
                or (not retained and token.valid_until <= at)
            ):
                raise ValueError("Traversal token is not bound to its physical episode")
            if interaction_episode != interaction_token or (
                interaction_token
                and (
                    physical_node.reliability != 1.0
                    or token.track_confidence != "provisional"
                    or token.path_node_ids != (state.node_id,)
                    or not token.equivalent_confirmed_strength
                )
            ):
                raise ValueError("Interaction traversal token is incompatible")
            if state.cadence_warning and not (
                not retained
                and TraversalFrontier.preserves_warned_token(token, state, at)
            ):
                raise ValueError("Warned traversal token is not preservable")
            if token.provenance_kind not in allowed_provenance:
                raise ValueError("Traversal token provenance is incompatible")
            if token.track_confidence == "confirmed" and len(token.path_node_ids) != 3:
                raise ValueError("Confirmed traversal token lacks a bounded path")
            if token.provenance_kind == "settled_adjacent_transfer" and (
                token.track_confidence != "provisional"
                or not token.equivalent_confirmed_strength
                or not direct_different_zone_pair(
                    self.predictive_map, token.path_node_ids,
                )
            ):
                raise ValueError("Settled-adjacent traversal token is incompatible")
            if token.provenance_kind == "settled_endpoint" and not (
                (
                    token.track_confidence == "confirmed"
                    and len(token.path_node_ids) == 3
                )
                or (
                    token.track_confidence == "provisional"
                    and len(token.path_node_ids) == 1
                    and not token.equivalent_confirmed_strength
                )
            ):
                raise ValueError("Settled-endpoint traversal token is incompatible")
            if token.equivalent_confirmed_strength and (
                (
                    token.provenance_kind in {"boundary", "missed_edge"}
                    and len(token.path_node_ids) != 3
                )
                or (
                    token.provenance_kind == "local_interaction"
                    and len(token.path_node_ids) != 1
                )
                or token.provenance_kind
                not in {
                    "boundary", "local_interaction", "missed_edge",
                    "settled_adjacent_transfer",
                }
            ):
                raise ValueError("Equivalent traversal strength is incompatible")
            if any(
                node_id not in self.predictive_map.nodes
                for node_id in token.path_node_ids
            ):
                raise ValueError("Traversal token path contains an unknown node")
            if any(
                not bounded_path_step(self.predictive_map, left, right)
                for left, right in zip(
                    token.path_node_ids,
                    token.path_node_ids[1:],
                    strict=False,
                )
            ):
                raise ValueError("Traversal token path is graph-incompatible")
        return tokens, retained_tokens

    def validate_outward(self, snapshot: ZoneModelSnapshot) -> None:
        """Check the original combined source/target outward lifetime bound."""
        at = snapshot.updated_at
        episodes = {state.node_id: state for state in snapshot.episode_states}
        max_target_traversal = max(
            min(
                SHARED_PROFILES[node.profile_name].traversal_context_window,
                SHARED_PROFILES[node.profile_name].assertion_trust_horizon,
            )
            for node in self.nodes
        )
        for belief in snapshot.belief_states:
            outward = belief.outward_context
            if outward is None:
                continue
            state, created_at = episode_reference(
                outward.source_episode_id,
                episodes,
                at,
                exact=True,
            )
            source_profile = SHARED_PROFILES[state.profile_name]
            source_valid_until = min(
                created_at + source_profile.traversal_context_window,
                created_at + source_profile.assertion_trust_horizon,
            )
            if outward.valid_until > source_valid_until + max_target_traversal:
                raise ValueError("Outward context expiry exceeds its calibrated bound")

    def validate_current_pending_uses(
        self,
        snapshot: ZoneModelSnapshot,
        tokens: Mapping[str, TraversalToken],
        retained_tokens: Mapping[str, TraversalToken],
    ) -> None:
        """Bind current markers, pending candidates and uses to real episodes."""
        at = snapshot.updated_at
        episodes = {state.node_id: state for state in snapshot.episode_states}
        physical_nodes = {node.node_id: node for node in self.nodes}
        for token_id in snapshot.current_token_ids:
            current_token = tokens.get(token_id)
            if current_token is None:
                raise ValueError("Current traversal token does not exist")
            state = episodes[current_token.node_id]
            if (
                state.episode_id != current_token.episode_id
                or state.status != "asserted"
                or state.health_warning
                or state.cadence_warning
            ):
                raise ValueError("Current traversal token is not physically current")

        for candidate in snapshot.pending_candidates:
            state, created_at = episode_reference(
                candidate.episode_id,
                episodes,
                at,
                exact=True,
            )
            node = self.predictive_map.nodes[candidate.node_id]
            physical_profile = next(
                item for item in self.nodes if item.node_id == candidate.node_id
            )
            sensor_profile = SHARED_PROFILES[candidate.profile_name]
            expected_traversal = min(
                created_at + sensor_profile.traversal_context_window,
                created_at + sensor_profile.assertion_trust_horizon,
            )
            if (
                state.node_id != candidate.node_id
                or state.cadence_warning
                or state.health_warning
                or state.status in {"degraded", "unavailable"}
                or created_at != candidate.created_at
                or candidate.expires_at
                != created_at + sensor_profile.track_bootstrap_window
                or candidate.traversal_valid_until != expected_traversal
                or candidate.reliability != physical_profile.reliability
                or node.occupancy_zone != candidate.zone
            ):
                raise ValueError("Pending candidate is not bound to its episode")

        for use in snapshot.authorization_uses:
            traversal_source = tokens.get(use.token_id) or retained_tokens.get(
                use.token_id
            )
            if traversal_source is None or not (
                traversal_source.accepted_at <= use.authorized_at <= at
            ):
                raise ValueError("Traversal use has an incompatible source frontier")
            target_state, target_created_at = episode_reference(
                use.target_episode_id,
                episodes,
                at,
                exact=False,
            )
            if target_created_at > use.authorized_at:
                raise ValueError("Traversal use predates its target episode")
            if use.reason == "supported_gap_acquisition" and (
                target_created_at != use.authorized_at
                or not original_handoff_valid(
                    self.predictive_map, physical_nodes, traversal_source,
                    use.authorized_at, historical=True,
                )
                or not gap_geometry_valid(
                    self.predictive_map, physical_nodes, traversal_source.node_id,
                    target_state.node_id, traversal_source.accepted_at,
                    use.authorized_at,
                )
            ):
                raise ValueError("Supported-gap use lacks original bounded authority")

    def validate_support_snapshot(
        self,
        snapshot: ZoneModelSnapshot,
        active_tokens: Mapping[str, TraversalToken],
        retained_tokens: Mapping[str, TraversalToken],
    ) -> None:
        """Bind persisted supports to current physical and traversal state."""

        if len(snapshot.anonymous_supports) > PRODUCT_MAX_OCCUPANTS:
            raise ValueError("Anonymous-support snapshot exceeds its bound")
        episodes = {state.node_id: state for state in snapshot.episode_states}
        beliefs = {state.zone: state for state in snapshot.belief_states}
        tokens = {**active_tokens, **retained_tokens}
        bindings = {
            binding.token_id: binding.support_id
            for binding in snapshot.support_token_bindings
        }
        if any(token_id not in tokens for token_id in bindings):
            raise ValueError("Support-token binding is incompatible")
        for support in snapshot.anonymous_supports:
            node = next(
                (
                    physical
                    for physical in self.nodes
                    if physical.node_id == support.current_node_id
                ),
                None,
            )
            state = episodes.get(support.current_node_id)
            belief = beliefs.get(support.current_zone)
            if (
                node is None
                or node.zone != support.current_zone
                or state is None
                or belief is None
                or state.episode_id != support.current_episode_id
                or state.started_at is None
                or state.started_at > support.updated_at
                or support.updated_at > snapshot.updated_at
            ):
                raise ValueError("Anonymous-support endpoint is incompatible")
            origin_id = support.support_id.removeprefix("support:")
            origin_node = next(
                (
                    node_id
                    for node_id in sorted(episodes, key=len, reverse=True)
                    if origin_id.startswith(f"{node_id}:")
                ),
                None,
            )
            if origin_node is None:
                raise ValueError("Anonymous-support origin node is incompatible")
            origin_episode = origin_id[len(origin_node) + 1 :]
            origin_state, origin_at = episode_reference(
                origin_episode, episodes, snapshot.updated_at, exact=False
            )
            # Least-ID coalescence retains the minimum creation time across
            # members. Its bounded descendants cannot reconstruct that history.
            if (
                origin_state.node_id != origin_node
                or not support.created_at <= origin_at <= support.updated_at
            ):
                raise ValueError(
                    "Anonymous-support origin identity/time is incompatible"
                )
            origin_token = tokens.get(origin_id)
            if origin_token is not None and not self.confirmed_strength(origin_token):
                raise ValueError(
                    "Anonymous-support origin lacks valid creation strength"
                )
            untransferred = (
                origin_episode == support.current_episode_id
                and origin_node == support.current_node_id
                and support.created_at == support.updated_at
            )
            if untransferred and (
                (
                    origin_token is not None
                    and (
                        origin_token.provenance_kind != support.provenance_kind
                        or origin_token.path_node_ids != support.path_node_ids
                    )
                )
                or support.provenance_kind == "settled_adjacent_transfer"
                or (
                    support.provenance_kind == "adjacent"
                    and len(set(support.path_node_ids)) != 3
                )
            ):
                raise ValueError(
                    "Interaction or traversal support creation provenance "
                    "is incompatible"
                )
            path = support.path_node_ids
            interaction_support = support.provenance_kind == "local_interaction"
            if (
                bool(node.interaction_aliases) != interaction_support
                or (interaction_support and (node.reliability != 1.0 or len(path) != 1))
            ):
                raise ValueError("Interaction support provenance is incompatible")
            if (
                (
                    support.provenance_kind == "settled_adjacent_transfer"
                    and not direct_different_zone_pair(self.predictive_map, path)
                )
                or (
                    support.provenance_kind == "adjacent"
                    and len(path) not in {2, 3}
                )
                or (
                    support.provenance_kind in {"boundary", "missed_edge"}
                    and len(path) != 3
                )
            ):
                raise ValueError(
                    "Anonymous-support current provenance/path is incompatible"
                )
            target_tokens = tuple(
                tokens[token_id]
                for token_id, support_id in bindings.items()
                if support_id == support.support_id
                and tokens[token_id].node_id == support.current_node_id
                and tokens[token_id].episode_id == support.current_episode_id
            )
            for token in target_tokens:
                # Coalescence can leave a causally stale target binding, but
                # changing updated_at cannot excuse a contradictory endpoint.
                endpoint_rebind = token.provenance_kind == "settled_endpoint"
                if token.accepted_at > support.updated_at or (
                    endpoint_rebind
                    and not (
                        support.state == "settled"
                        and (
                            (
                                token.track_confidence == "confirmed"
                                and token.path_node_ids == path
                            )
                            or (
                                token.track_confidence == "provisional"
                                and len(path) == 2
                                and token.path_node_ids == (support.current_node_id,)
                            )
                        )
                    )
                ) or (
                    not endpoint_rebind
                    and (
                        token.provenance_kind != support.provenance_kind
                        or token.path_node_ids != path
                    )
                ):
                    raise ValueError("Anonymous-support target binding is incompatible")
            if support.state == "settled":
                if (
                    SHARED_PROFILES[node.profile_name].role != "stay"
                    or state.status not in {"asserted", "clearing", "clear"}
                    or state.health_warning
                    or state.cadence_warning
                    or belief.health_warning
                ):
                    raise ValueError("Settled anonymous support is incompatible")
                continue
            if not target_tokens or all(
                token.valid_until != support.valid_until
                or token.accepted_at != support.updated_at
                for token in target_tokens
            ):
                raise ValueError("Moving support lacks its target binding")

    def validate_count_snapshot(self, snapshot: ZoneModelSnapshot) -> None:
        """Require stored count conflicts to match current support evidence."""

        episodes = {state.node_id: state for state in snapshot.episode_states}
        supports = tuple(
            CountSupport(
                support.support_id,
                support.current_node_id,
                support.current_zone,
                support.path_node_ids,
            )
            for support in snapshot.anonymous_supports
        )
        for conflict in snapshot.count_conflicts:
            state = episodes.get(conflict.target_node_id)
            historical = (
                conflict.started_at,
                conflict.last_evaluated_at,
                conflict.degraded_at,
            )
            if (
                state is None
                or state.zone != conflict.target_zone
                or state.episode_id != conflict.target_episode_id
                or any(
                    value is not None and value > snapshot.updated_at
                    for value in historical
                )
                or (
                    state is not None
                    and conflict.deadline
                    != conflict.started_at
                    + POLICY_CALIBRATIONS[state.profile_name].release_dwell
                )
                or (
                    conflict.degraded_at is None
                    and conflict.support_ids
                    != tuple(
                        support.support_id
                        for support in supports
                        if support.endpoint_zone != conflict.target_zone
                        and conflict.target_node_id not in support.path_node_ids
                    )[: snapshot.count_state.expected_count]
                )
            ):
                raise ValueError("Count-conflict snapshot is incompatible")


def validate_component_snapshot(
    predictive_map: PredictiveMap,
    nodes: tuple[PhysicalNode, ...],
    snapshot: ZoneModelSnapshot,
) -> None:
    """Validate cross-links, not current selected-engine acceptance.

    The fresh tracker supplies only its unchanged read-only strength predicate;
    no component state is restored, reconciled, or otherwise changed here.
    Callers already owning a tracker can construct ``SnapshotValidator`` with
    that tracker's bound ``_confirmed_strength`` method instead.
    """
    tracker = AnonymousSupportTracker(predictive_map, nodes)
    SnapshotValidator(
        predictive_map, nodes, tracker._confirmed_strength,
    ).validate(snapshot)
