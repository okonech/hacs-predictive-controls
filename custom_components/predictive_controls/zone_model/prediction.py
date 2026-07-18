"""Downstream-only prediction leases derived from accepted target traversal."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ..markov import MarkovChain
from ..model import PredictiveMap
from .types import TraversalAuthorization, ZoneModelResult, require_utc

LEASE_DURATION = timedelta(seconds=30)
LEASE_LIMIT = 64
LEARNING_REASONS = frozenset(
    {"adjacent_current", "adjacent_recent", "same_zone_other_node"}
)


@dataclass(frozen=True)
class PredictionLease:
    """One finite graph-adjacent prelight projection."""

    source_node_id: str
    current_node_id: str
    target_node_id: str
    target_zone: str
    probability: float
    created_at: datetime
    expires_at: datetime
    reason: str


class TargetPredictionManager:
    """Learn and project only from accepted graph-local traversal results."""

    def __init__(self, predictive_map: PredictiveMap) -> None:
        self._map = predictive_map
        self.chain = MarkovChain(predictive_map)
        self._leases: dict[tuple[str, str, str], PredictionLease] = {}

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

    def apply(self, result: ZoneModelResult) -> None:
        at = result.snapshot.updated_at
        self.expire(at)
        if result.snapshot.count_state.expected_count == 0:
            self.clear()
            return
        self._cancel_on_target_evidence(result)
        for authorization in result.authorizations:
            self._apply_authorization(authorization)

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
        candidate = MarkovChain(self._map)
        candidate.restore_counts(counts)
        restored: dict[tuple[str, str, str], PredictionLease] = {}
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
            restored[
                (lease.source_node_id, lease.current_node_id, lease.target_node_id)
            ] = lease
        if len(restored) > LEASE_LIMIT:
            raise ValueError("Prediction lease bound exceeded")
        self.chain = candidate
        self._leases = restored

    def _apply_authorization(self, authorization: TraversalAuthorization) -> None:
        if not authorization.authorized or authorization.reason not in LEARNING_REASONS:
            return
        current = self._map.nodes.get(authorization.target_node_id)
        if current is None:
            return
        compatible_sources = tuple(
            token
            for token in authorization.source_tokens
            if token.node_id in self._map.nodes
            and authorization.target_node_id in self._map.nodes[token.node_id].adjacent
        )
        source_ids = tuple(sorted({token.node_id for token in compatible_sources}))
        if len(source_ids) != 1:
            return
        source_id = source_ids[0]
        current_id = authorization.target_node_id
        self.chain.observe(source_id, current_id)
        self._leases = {
            key: lease
            for key, lease in self._leases.items()
            if lease.current_node_id != source_id
        }
        candidates = tuple(
            node_id
            for node_id in sorted(self._map.nodes[current_id].adjacent)
            if node_id != source_id
        )
        if not candidates:
            return
        raw = self.chain.probabilities(current_id)
        total = sum(raw.get(node_id, 0.0) for node_id in candidates)
        probabilities = (
            {node_id: 1.0 / len(candidates) for node_id in candidates}
            if total <= 0.0
            else {node_id: raw.get(node_id, 0.0) / total for node_id in candidates}
        )
        for target_id, probability in probabilities.items():
            target_zone = self._map.nodes[target_id].occupancy_zone
            key = (source_id, current_id, target_id)
            self._leases[key] = PredictionLease(
                source_id,
                current_id,
                target_id,
                target_zone,
                probability,
                authorization.authorized_at,
                authorization.authorized_at + LEASE_DURATION,
                "accepted graph traversal",
            )
        if len(self._leases) > LEASE_LIMIT:
            retained = sorted(
                self._leases.items(),
                key=lambda item: (item[1].created_at, item[0]),
            )[-LEASE_LIMIT:]
            self._leases = dict(retained)

    def _cancel_on_target_evidence(self, result: ZoneModelResult) -> None:
        """Cancel projections contradicted or resolved by newer physical evidence."""

        states = {state.node_id: state for state in result.snapshot.episode_states}
        self._leases = {
            key: lease
            for key, lease in self._leases.items()
            if (state := states.get(lease.target_node_id)) is None
            or state.last_event_at is None
            or state.last_event_at <= lease.created_at
        }

    @staticmethod
    def _decode_lease(raw: object) -> PredictionLease:
        if not isinstance(raw, dict):
            raise ValueError("Prediction lease must be a mapping")
        try:
            created_at = datetime.fromisoformat(str(raw["created_at"]))
            expires_at = datetime.fromisoformat(str(raw["expires_at"]))
            lease = PredictionLease(
                str(raw["source_node_id"]),
                str(raw["current_node_id"]),
                str(raw["target_node_id"]),
                str(raw["target_zone"]),
                float(raw["probability"]),
                created_at,
                expires_at,
                str(raw["reason"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Prediction lease is invalid") from exc
        require_utc(lease.created_at, "Prediction lease creation")
        require_utc(lease.expires_at, "Prediction lease expiry")
        if (
            not 0.0 <= lease.probability <= 1.0
            or lease.expires_at <= lease.created_at
            or not all(
                (
                    lease.source_node_id,
                    lease.current_node_id,
                    lease.target_node_id,
                    lease.target_zone,
                    lease.reason,
                )
            )
        ):
            raise ValueError("Prediction lease is invalid")
        return lease


__all__ = ["PredictionLease", "TargetPredictionManager"]
