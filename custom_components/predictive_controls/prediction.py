from __future__ import annotations

from datetime import datetime, timedelta

from .markov import MarkovChain
from .model import PredictiveMap
from .occupancy_graph import ZoneGraph
from .occupancy_state import FilterUpdate, PredictionLease
from .route_model import RouteMatch, RouteModel


class PredictionManager:
    """Maintain independent direction-aware leases without creating evidence."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        chain: MarkovChain | None = None,
        route_model: RouteModel | None = None,
        *,
        movement_threshold: float = 0.50,
        learning_threshold: float = 0.80,
        lease_duration: timedelta = timedelta(seconds=30),
    ) -> None:
        self.map = predictive_map
        self.graph = ZoneGraph.from_map(predictive_map)
        self.chain = chain or MarkovChain(predictive_map)
        self.route_model = route_model or RouteModel(predictive_map)
        self.movement_threshold = movement_threshold
        self.learning_threshold = learning_threshold
        self.lease_duration = lease_duration
        self._leases: dict[tuple[str, str | None, str], PredictionLease] = {}
        self._route_contexts: tuple[tuple[str, ...], ...] = ()
        self._last_route_match: RouteMatch | None = None
        self._last_route_probabilities: dict[str, float] = {}

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

    @property
    def route_counts(self) -> dict[tuple[str, ...], dict[str, float]]:
        return self.route_model.counts

    @property
    def route_contexts(self) -> tuple[tuple[str, ...], ...]:
        return self._route_contexts

    @property
    def route_diagnostics(self) -> dict[str, object]:
        match = self._last_route_match
        return {
            "matched_prefix": [] if match is None else list(match.matched_prefix),
            "support": 0.0 if match is None else match.support,
            "backoff_level": 0 if match is None else match.backoff_level,
            "minimum_support": self.route_model.minimum_support,
            "resulting_probabilities": dict(self._last_route_probabilities),
        }

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
                    self._route_history_for_edge(evidence),
                )
                reason = (
                    "learned route-prefix branch probability"
                    if self._last_route_match is not None
                    and self._last_route_match.matched_prefix
                    else "learned forward branch probability"
                )
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
        if len(qualifying) != 1:
            return ()
        evidence = qualifying[0]
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
        compatible = self._compatible_route_contexts(source_node.node_id)
        if len(compatible) == 1:
            self.route_model.observe(
                compatible[0],
                target_node.node_id,
                weight=evidence.coherent_probability,
            )
        self._advance_route_contexts(
            source_node.node_id,
            target_node.node_id,
            compatible,
        )
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
            self._route_contexts = ()

    def reset(self) -> None:
        self._leases.clear()
        self._route_contexts = ()

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

    def restore_route_state(
        self,
        counts: dict[tuple[str, ...], dict[str, float]],
        contexts: tuple[tuple[str, ...], ...],
    ) -> None:
        self.route_model.restore_counts(counts)
        self._route_contexts = tuple(
            sorted(
                {
                    history
                    for history in contexts
                    if 2 <= len(history) <= self.route_model.max_order
                    and all(node_id in self.map.nodes for node_id in history)
                    and all(
                        target in self.map.nodes[source].adjacent
                        for source, target in zip(history, history[1:], strict=False)
                    )
                }
            )[:4]
        )

    def _cancel_from(self, source: str) -> None:
        for key in tuple(self._leases):
            if key[0] == source:
                del self._leases[key]

    def _branch_probabilities(
        self,
        node_id: str,
        current_zone: str,
        candidates: tuple[str, ...],
        route_history: tuple[str, ...] = (),
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
            base = dict.fromkeys(candidates, equal)
        else:
            base = {zone: probability / total for zone, probability in totals.items()}

        current_node = self.map.nodes.get(node_id)
        target_nodes = (
            tuple(
                sorted(
                    target
                    for target in current_node.adjacent
                    if self.map.nodes[target].occupancy_zone in candidates
                )
            )
            if current_node is not None
            and current_node.occupancy_zone == current_zone
            else ()
        )
        match = self.route_model.match(route_history, target_nodes)
        self._last_route_match = match
        if not match.matched_prefix:
            self._last_route_probabilities = dict(base)
            return base
        route_by_zone = dict.fromkeys(candidates, 0.0)
        for target, probability in match.probabilities.items():
            route_by_zone[self.map.nodes[target].occupancy_zone] += probability
        influence = self.route_model.maximum_boost * min(
            1.0,
            match.support / (2.0 * self.route_model.minimum_support),
        )
        blended = {
            zone: (1.0 - influence) * base[zone]
            + influence * route_by_zone[zone]
            for zone in candidates
        }
        self._last_route_probabilities = dict(blended)
        return blended

    def _compatible_route_contexts(
        self,
        source_node_id: str,
    ) -> tuple[tuple[str, ...], ...]:
        return tuple(
            history
            for history in self._route_contexts
            if history[-1] == source_node_id
        )

    def _route_history_for_edge(
        self,
        evidence: object,
    ) -> tuple[str, ...]:
        source = getattr(evidence, "source_node_id", None)
        target = getattr(evidence, "target_node_id", None)
        if not isinstance(source, str) or not isinstance(target, str):
            return ()
        compatible = self._compatible_route_contexts(source)
        if len(compatible) > 1:
            return ()
        history = compatible[0] if compatible else (source,)
        return (*history, target)[-self.route_model.max_order :]

    def _advance_route_contexts(
        self,
        source: str,
        target: str,
        compatible: tuple[tuple[str, ...], ...],
    ) -> None:
        retained = {
            history for history in self._route_contexts if history[-1] != source
        }
        history = compatible[0] if len(compatible) == 1 else (source,)
        retained.add((*history, target)[-self.route_model.max_order :])
        self._route_contexts = tuple(
            sorted(retained, key=lambda item: (-len(item), item))[:4]
        )
