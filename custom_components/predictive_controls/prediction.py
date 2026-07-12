from __future__ import annotations

from datetime import datetime, timedelta

from .markov import MarkovChain
from .model import PredictiveMap
from .occupancy_graph import ZoneGraph
from .occupancy_state import FilterUpdate, PredictionLease


class PredictionManager:
    """Maintain independent direction-aware leases without creating evidence."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        chain: MarkovChain | None = None,
        *,
        movement_threshold: float = 0.50,
        learning_threshold: float = 0.80,
        lease_duration: timedelta = timedelta(seconds=30),
    ) -> None:
        self.map = predictive_map
        self.graph = ZoneGraph.from_map(predictive_map)
        self.chain = chain or MarkovChain(predictive_map)
        self.movement_threshold = movement_threshold
        self.learning_threshold = learning_threshold
        self.lease_duration = lease_duration
        self._leases: dict[tuple[str, str | None, str], PredictionLease] = {}

    @property
    def leases(self) -> tuple[PredictionLease, ...]:
        return tuple(self._leases[key] for key in sorted(self._leases))

    @property
    def probabilities(self) -> dict[str, float]:
        probabilities: dict[str, float] = {}
        for lease in self._leases.values():
            probabilities[lease.target_zone] = max(
                probabilities.get(lease.target_zone, 0.0),
                lease.probability,
            )
        return dict(sorted(probabilities.items()))

    def apply(self, update: FilterUpdate) -> tuple[PredictionLease, ...]:
        """Update leases from posterior movement while leaving occupancy untouched."""

        now = update.current.updated_at
        self.expire(now)
        if update.provenance.disposition not in {"accepted", "replacement"}:
            return self.leases

        for evidence in update.movement_evidence:
            movement_probability = evidence.coherent_probability
            if (
                movement_probability < self.movement_threshold
                or evidence.disposition != "graph_valid"
            ):
                continue
            source = evidence.source_zone
            current = evidence.target_zone
            self._cancel_from(source)
            candidates = tuple(sorted(self.graph.neighbors(current) - {source}))
            if not candidates:
                continue
            if len(candidates) == 1:
                probabilities = {candidates[0]: 1.0}
                reason = "only graph-valid forward continuation"
            else:
                probabilities = self._branch_probabilities(
                    update.provenance.node_id,
                    current,
                    candidates,
                )
                reason = "learned forward branch probability"
            for target, branch_probability in probabilities.items():
                path_key = (current, source, target)
                self._leases[path_key] = PredictionLease(
                    path_key=path_key,
                    target_zone=target,
                    probability=movement_probability * branch_probability,
                    expires_at=now + self.lease_duration,
                    reason=reason,
                )
        return self.leases

    def learn(self, update: FilterUpdate) -> tuple[tuple[str, str], ...]:
        """Learn only the strongest posterior-consistent concrete node edge."""

        if update.provenance.disposition not in {"accepted", "replacement"}:
            return ()
        qualifying = [
            evidence
            for evidence in update.movement_evidence
            if evidence.coherent_probability >= self.learning_threshold
            and evidence.disposition == "graph_valid"
            and evidence.source_node_id is not None
            and evidence.target_node_id == update.provenance.node_id
            and evidence.target_zone == update.provenance.zone
        ]
        if not qualifying:
            return ()
        evidence = max(
            qualifying,
            key=lambda item: (item.coherent_probability, item.path_key),
        )
        source_node = self.map.nodes.get(evidence.source_node_id or "")
        target_node = self.map.nodes.get(evidence.target_node_id)
        if (
            source_node is None
            or target_node is None
            or target_node.node_id not in source_node.adjacent
        ):
            return ()
        if not self.chain.observe(
            source_node.node_id,
            target_node.node_id,
            weight=evidence.coherent_probability,
        ):
            return ()
        return ((source_node.node_id, target_node.node_id),)

    def expire(self, now: datetime) -> bool:
        expired = [
            key for key, lease in self._leases.items() if lease.expires_at <= now
        ]
        for key in expired:
            del self._leases[key]
        return bool(expired)

    def reconcile_count(self, previous: int, current: int) -> None:
        if current < previous:
            self._leases.clear()

    def reset(self) -> None:
        self._leases.clear()

    def restore_leases(
        self,
        leases: tuple[PredictionLease, ...],
        now: datetime,
    ) -> None:
        valid_zones = set(self.graph.zones())
        self._leases = {
            lease.path_key: lease
            for lease in leases
            if lease.expires_at > now
            and lease.target_zone in valid_zones
            and all(zone is None or zone in valid_zones for zone in lease.path_key)
        }

    def _cancel_from(self, source: str) -> None:
        for key in tuple(self._leases):
            if key[0] == source:
                del self._leases[key]

    def _branch_probabilities(
        self,
        node_id: str,
        current_zone: str,
        candidates: tuple[str, ...],
    ) -> dict[str, float]:
        node = self.map.nodes.get(node_id)
        source_nodes = (
            (node,)
            if node is not None and node.occupancy_zone == current_zone
            else tuple(
                candidate
                for candidate in self.map.nodes.values()
                if candidate.occupancy_zone == current_zone
            )
        )
        totals = dict.fromkeys(candidates, 0.0)
        for source_node in source_nodes:
            for target_node, probability in self.chain.probabilities(
                source_node.node_id
            ).items():
                target_zone = self.map.nodes[target_node].occupancy_zone
                if target_zone in totals:
                    totals[target_zone] += probability
        total = sum(totals.values())
        if total == 0.0:
            equal = 1.0 / len(candidates)
            return dict.fromkeys(candidates, equal)
        return {zone: probability / total for zone, probability in totals.items()}
