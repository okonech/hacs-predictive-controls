"""Bounded prediction authorization derived from confirmed physical tracks."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ..markov import MARKOV_COUNT_LIMIT, MarkovChain
from ..model import PredictiveMap
from .types import (
    PREDICTION_MATURITY_PROBABILITY,
    PREDICTION_MATURITY_SUPPORT,
    EpisodeState,
    TraversalAuthorization,
    ZoneModelResult,
    require_utc,
)

LEASE_DURATION = timedelta(seconds=10)
LEASE_LIMIT = 64
MATURITY_PROBABILITY = PREDICTION_MATURITY_PROBABILITY
MATURITY_SUPPORT = PREDICTION_MATURITY_SUPPORT


@dataclass(frozen=True)
class PredictionLease:
    """One finite graph-adjacent prediction, mature or diagnostic-only."""

    source_node_id: str
    current_node_id: str
    target_node_id: str
    target_zone: str
    probability: float
    support: float
    source_episode_id: str
    created_at: datetime
    expires_at: datetime
    mature: bool
    reason: str


class TargetPredictionManager:
    """Learn confirmed routes and issue nonrenewing prediction leases."""

    def __init__(self, predictive_map: PredictiveMap) -> None:
        self._map = predictive_map
        self.chain = MarkovChain(predictive_map)
        self._leases: dict[tuple[str, str, str, str], PredictionLease] = {}

    @property
    def leases(self) -> tuple[PredictionLease, ...]:
        return tuple(self._leases[key] for key in sorted(self._leases))

    @property
    def probabilities(self) -> dict[str, float]:
        probabilities: dict[str, float] = {}
        for lease in self._leases.values():
            probabilities[lease.target_zone] = max(
                probabilities.get(lease.target_zone, 0.0), lease.probability
            )
        return dict(sorted(probabilities.items()))

    def prepare(
        self,
        at: datetime,
        expected_count: int,
        episode_states: tuple[EpisodeState, ...],
        authorizations: tuple[TraversalAuthorization, ...],
    ) -> tuple[PredictionLease, ...]:
        """Advance leases and return new mature activations without learning."""

        require_utc(at, "Prediction preparation time")
        self.expire(at)
        if expected_count == 0:
            self.clear()
            return ()
        state_by_node = {state.node_id: state for state in episode_states}
        self._cancel_on_source_health(state_by_node)
        self._cancel_on_target_evidence(episode_states)
        self._cancel_on_confirmed_departures(authorizations)
        created: list[PredictionLease] = []
        for authorization in authorizations:
            created.extend(self._create_leases(authorization, state_by_node))
        self._enforce_bound()

        # One source episode can authorize at most one public edge. Lower-ranked
        # and immature leases remain diagnostic only.
        by_episode: dict[str, list[PredictionLease]] = {}
        for lease in created:
            if lease.mature:
                by_episode.setdefault(lease.source_episode_id, []).append(lease)
        selected = [
            max(
                leases,
                key=lambda lease: (
                    lease.probability,
                    lease.support,
                    lease.target_node_id,
                ),
            )
            for leases in by_episode.values()
        ]
        return tuple(sorted(selected, key=lambda lease: lease.source_episode_id))

    def commit(
        self, authorizations: tuple[TraversalAuthorization, ...]
    ) -> None:
        """Commit route observations after the public fast path has published."""

        for authorization in authorizations:
            edge = self._confirmed_edge(authorization)
            if edge is not None:
                self.chain.observe(*edge)

    def apply(self, result: ZoneModelResult) -> None:
        """Compatibility helper for non-runtime callers: prepare, then learn."""

        self.prepare(
            result.snapshot.updated_at,
            result.snapshot.count_state.expected_count,
            result.snapshot.episode_states,
            result.authorizations,
        )
        self.commit(result.authorizations)

    def expire(self, at: datetime) -> bool:
        require_utc(at, "Prediction expiry time")
        expired = [key for key, lease in self._leases.items() if lease.expires_at <= at]
        for key in expired:
            del self._leases[key]
        return bool(expired)

    def clear(self) -> None:
        self._leases.clear()

    def serialize(self) -> dict[str, object]:
        return {
            "counts": self.chain.counts,
            "leases": [
                {
                    **asdict(lease),
                    "created_at": lease.created_at.isoformat(),
                    "expires_at": lease.expires_at.isoformat(),
                }
                for lease in self.leases
            ],
        }

    def restore(self, payload: object, at: datetime) -> None:
        require_utc(at, "Prediction restore time")
        if not isinstance(payload, dict):
            raise ValueError("Prediction state must be a mapping")
        counts = payload.get("counts")
        leases = payload.get("leases")
        if not isinstance(counts, dict) or not isinstance(leases, list):
            raise ValueError("Prediction state is invalid")
        self._validate_counts(counts)
        candidate = MarkovChain(self._map)
        candidate.restore_counts(counts)
        restored: dict[tuple[str, str, str, str], PredictionLease] = {}
        for raw in leases:
            lease = self._decode_lease(raw)
            if lease.expires_at <= at:
                continue
            source = self._map.nodes.get(lease.source_node_id)
            current = self._map.nodes.get(lease.current_node_id)
            target = self._map.nodes.get(lease.target_node_id)
            if (
                source is None
                or current is None
                or target is None
                or lease.current_node_id not in source.adjacent
                or lease.target_node_id not in current.adjacent
                or target.occupancy_zone != lease.target_zone
            ):
                raise ValueError("Prediction lease is map-incompatible")
            key = (
                lease.source_node_id,
                lease.current_node_id,
                lease.target_node_id,
                lease.source_episode_id,
            )
            if key in restored:
                raise ValueError("Prediction lease snapshot is duplicated")
            restored[key] = lease
        if len(restored) > LEASE_LIMIT:
            raise ValueError("Prediction lease bound exceeded")
        self.chain = candidate
        self._leases = restored

    def _validate_counts(self, counts: dict[object, object]) -> None:
        expected_sources = set(self._map.nodes)
        if set(counts) != expected_sources:
            raise ValueError("Prediction route counts are map-incompatible")
        for source_id, raw_targets in counts.items():
            if not isinstance(source_id, str) or not isinstance(raw_targets, dict):
                raise ValueError("Prediction route counts are invalid")
            expected_targets = set(self._map.nodes[source_id].adjacent)
            if set(raw_targets) != expected_targets:
                raise ValueError("Prediction route counts are map-incompatible")
            if any(
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0.0 <= value <= MARKOV_COUNT_LIMIT
                for value in raw_targets.values()
            ):
                raise ValueError("Prediction route counts are invalid")

    @classmethod
    def restored(
        cls,
        predictive_map: PredictiveMap,
        payload: object,
        at: datetime,
    ) -> TargetPredictionManager:
        """Build a validated manager without mutating an existing instance."""

        candidate = cls(predictive_map)
        candidate.restore(payload, at)
        return candidate

    def _create_leases(
        self,
        authorization: TraversalAuthorization,
        state_by_node: dict[str, EpisodeState],
    ) -> tuple[PredictionLease, ...]:
        edge = self._confirmed_edge(authorization)
        if edge is None:
            return ()
        source_id, current_id = edge
        current_state = state_by_node.get(current_id)
        if current_state is None or self._health_blocked(current_state):
            return ()
        candidates = tuple(
            node_id
            for node_id in sorted(self._map.nodes[current_id].adjacent)
            if node_id != source_id
            and not self._health_blocked(state_by_node.get(node_id))
        )
        if not candidates:
            return ()
        raw = self.chain.probabilities(current_id)
        probabilities = {node_id: raw.get(node_id, 0.0) for node_id in candidates}
        created: list[PredictionLease] = []
        for target_id, probability in probabilities.items():
            support = self.chain.counts[current_id][target_id]
            mature = (
                probability >= MATURITY_PROBABILITY and support >= MATURITY_SUPPORT
            )
            lease = PredictionLease(
                source_id,
                current_id,
                target_id,
                self._map.nodes[target_id].occupancy_zone,
                probability,
                support,
                authorization.target_episode_id,
                authorization.authorized_at,
                authorization.authorized_at + LEASE_DURATION,
                mature,
                "confirmed-track prediction",
            )
            self._leases[
                (source_id, current_id, target_id, authorization.target_episode_id)
            ] = lease
            created.append(lease)
        return tuple(created)

    def _confirmed_edge(
        self, authorization: TraversalAuthorization
    ) -> tuple[str, str] | None:
        if (
            not authorization.authorized
            or authorization.track_confidence != "confirmed"
            or authorization.provenance_kind != "adjacent"
            or len(authorization.path_node_ids) < 2
        ):
            return None
        current_id = authorization.target_node_id
        path = authorization.path_node_ids
        if path[-1] != current_id:
            return None
        source_id = path[-2]
        source = self._map.nodes.get(source_id)
        if source is None or current_id not in source.adjacent:
            return None
        return source_id, current_id

    @staticmethod
    def _health_blocked(state: EpisodeState | None) -> bool:
        return bool(
            state is not None
            and (
                state.health_warning
                or state.cadence_warning
                or state.status in {"degraded", "unavailable"}
            )
        )

    def _cancel_on_target_evidence(
        self, episode_states: tuple[EpisodeState, ...]
    ) -> None:
        states = {state.node_id: state for state in episode_states}
        self._leases = {
            key: lease
            for key, lease in self._leases.items()
            if (state := states.get(lease.target_node_id)) is None
            or state.last_event_at is None
            or state.last_event_at <= lease.created_at
        }

    def _cancel_on_source_health(
        self,
        state_by_node: dict[str, EpisodeState],
    ) -> None:
        self._leases = {
            key: lease
            for key, lease in self._leases.items()
            if not self._health_blocked(state_by_node.get(lease.current_node_id))
        }

    def _cancel_on_confirmed_departures(
        self,
        authorizations: tuple[TraversalAuthorization, ...],
    ) -> None:
        departed = {
            source_id
            for authorization in authorizations
            if (edge := self._confirmed_edge(authorization)) is not None
            for source_id in (edge[0],)
        }
        if departed:
            self._leases = {
                key: lease
                for key, lease in self._leases.items()
                if lease.current_node_id not in departed
            }

    def _enforce_bound(self) -> None:
        if len(self._leases) <= LEASE_LIMIT:
            return
        retained = sorted(
            self._leases.items(),
            key=lambda item: (item[1].created_at, item[0]),
        )[-LEASE_LIMIT:]
        self._leases = dict(retained)

    @staticmethod
    def _decode_lease(raw: object) -> PredictionLease:
        if not isinstance(raw, dict):
            raise ValueError("Prediction lease must be a mapping")
        expected_fields = {
            "source_node_id",
            "current_node_id",
            "target_node_id",
            "target_zone",
            "probability",
            "support",
            "source_episode_id",
            "created_at",
            "expires_at",
            "mature",
            "reason",
        }
        if set(raw) != expected_fields:
            raise ValueError("Prediction lease shape is invalid")
        try:
            mature = raw["mature"]
            if not isinstance(mature, bool):
                raise ValueError("Prediction lease maturity must be boolean")
            created_at = datetime.fromisoformat(str(raw["created_at"]))
            expires_at = datetime.fromisoformat(str(raw["expires_at"]))
            probability = float(raw["probability"])
            support = float(raw["support"])
            lease = PredictionLease(
                str(raw["source_node_id"]),
                str(raw["current_node_id"]),
                str(raw["target_node_id"]),
                str(raw["target_zone"]),
                probability,
                support,
                str(raw["source_episode_id"]),
                created_at,
                expires_at,
                mature,
                str(raw["reason"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Prediction lease is invalid") from exc
        require_utc(lease.created_at, "Prediction lease creation")
        require_utc(lease.expires_at, "Prediction lease expiry")
        if (
            not math.isfinite(lease.probability)
            or not 0.0 <= lease.probability <= 1.0
            or not math.isfinite(lease.support)
            or lease.support < 0.0
            or lease.mature
            != (
                lease.probability >= MATURITY_PROBABILITY
                and lease.support >= MATURITY_SUPPORT
            )
            or lease.expires_at <= lease.created_at
            or lease.expires_at - lease.created_at != LEASE_DURATION
            or lease.reason != "confirmed-track prediction"
            or not all(
                (
                    lease.source_node_id,
                    lease.current_node_id,
                    lease.target_node_id,
                    lease.target_zone,
                    lease.source_episode_id,
                    lease.reason,
                )
            )
        ):
            raise ValueError("Prediction lease is invalid")
        return lease


__all__ = [
    "LEASE_DURATION",
    "MATURITY_PROBABILITY",
    "MATURITY_SUPPORT",
    "PredictionLease",
    "TargetPredictionManager",
]
