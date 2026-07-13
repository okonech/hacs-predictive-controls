from __future__ import annotations

import itertools
import math
from collections import defaultdict, deque
from datetime import datetime, timedelta
from time import perf_counter_ns

from .events import OccupancyEvent
from .model import PredictiveMap
from .observation_model import ObservationModel
from .occupancy_graph import ZoneGraph
from .occupancy_state import (
    DirectionalContext,
    FilterUpdate,
    HypothesisKey,
    MovementEvidence,
    ObservationProvenance,
    PositionState,
    PositiveEvidence,
    Posterior,
    WeightedHypothesis,
    canonical_hypothesis,
    cold_start_posterior,
    hypothesis_sort_key,
    initial_posterior,
    log_sum_exp,
    normalize_hypotheses,
    probability_sum,
    zone_marginals,
)
from .transition_model import TransitionPath

STAY_WEIGHT = 0.39
ADJACENT_MOVEMENT_WEIGHT = 0.60
MISSED_MOVEMENT_WEIGHT = 0.01
MISSED_TIMING_WEIGHT = 0.01
DEFAULT_TRANSITION_SECONDS = 30.0
MOTION_CORROBORATION_WINDOW = timedelta(minutes=2)
TRANSITION_CORROBORATION_WINDOW = timedelta(seconds=30)


class JointOccupancyFilter:
    """Exact/top-K Bayesian filter over exchangeable joint occupancy states."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        expected_occupants: int,
        started_at: datetime,
        *,
        exact_limit: int = 512,
        hard_limit: int = 4096,
    ) -> None:
        if not 0 <= expected_occupants <= 2:
            raise ValueError("expected_occupants must be between zero and two")
        self.map = predictive_map
        self.expected_occupants = expected_occupants
        self.exact_limit = exact_limit
        self.hard_limit = hard_limit
        self.graph = ZoneGraph.from_map(predictive_map)
        self.observations = ObservationModel(expected_occupants)
        self._configuration_keys: tuple[HypothesisKey, ...] = ()
        self._configuration_index: dict[HypothesisKey, int] = {}
        self._move_indexes: dict[tuple[int, str | None, str], int] = {}
        self._set_configuration_space(expected_occupants)
        self._active_positive_entities = {
            zone: set[str]() for zone in predictive_map.zones()
        }
        self.posterior = _densify_posterior(
            initial_posterior(expected_occupants, started_at),
            self._configuration_keys,
        )
        self._directional_contexts: dict[
            HypothesisKey,
            tuple[DirectionalContext, ...],
        ] = {
            hypothesis.key: (_contextless(hypothesis.log_probability),)
            for hypothesis in self.posterior.hypotheses
        }
        self._restored_context_keys: set[HypothesisKey] | None = None
        self._update_sequence = 0
        self._latency_samples_ms: deque[float] = deque(maxlen=256)
        self._last_operation_count = 0
        self._last_context_compaction_count = 0
        self.last_update: FilterUpdate | None = None

    @property
    def configuration_count(self) -> int:
        """Return the fixed anonymous occupancy state-space size."""

        return len(self._configuration_keys)

    @property
    def occupied_marginals(self) -> dict[str, float]:
        if self.last_update is not None and self.last_update.current is self.posterior:
            return dict(self.last_update.occupied_marginals)
        return zone_marginals(self.posterior, self.map.zones())[0]

    @property
    def count_marginals(self) -> dict[str, tuple[float, ...]]:
        if self.last_update is not None and self.last_update.current is self.posterior:
            return dict(self.last_update.count_marginals)
        return zone_marginals(self.posterior, self.map.zones())[1]

    def active_positive_evidence(
        self,
        now: datetime,
    ) -> dict[str, tuple[PositiveEvidence, ...]]:
        """Return currently asserted evidence after signal freshness filtering."""

        return self._current_positive_evidence(now)

    @property
    def directional_contexts(
        self,
    ) -> dict[HypothesisKey, tuple[DirectionalContext, ...]]:
        return self._directional_contexts.copy()

    @property
    def context_count(self) -> int:
        return sum(len(contexts) for contexts in self._directional_contexts.values())

    @property
    def update_sequence(self) -> int:
        return self._update_sequence

    @property
    def performance_metrics(self) -> dict[str, float | int]:
        samples = tuple(self._latency_samples_ms)
        return {
            "sample_count": len(samples),
            "last_ms": samples[-1] if samples else 0.0,
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "p99_ms": _percentile(samples, 0.99),
            "max_ms": max(samples, default=0.0),
            "last_operation_count": self._last_operation_count,
            "last_candidate_expansions": self._last_operation_count,
            "last_context_compactions": self._last_context_compaction_count,
            "configuration_count": self.configuration_count,
            "context_count": self.context_count,
        }

    def observe(self, event: OccupancyEvent) -> FilterUpdate:
        """Apply one sensor event synchronously and return immutable evidence."""

        started_ns = perf_counter_ns()
        try:
            return self._observe(event)
        finally:
            self._latency_samples_ms.append(
                (perf_counter_ns() - started_ns) / 1_000_000
            )

    def _observe(self, event: OccupancyEvent) -> FilterUpdate:
        """Apply one event without the latency instrumentation wrapper."""

        self._update_sequence += 1
        self._last_operation_count = 0
        self._last_context_compaction_count = 0
        previous = self.posterior
        if event.event_at < previous.updated_at:
            update = self._unchanged_update(event, "out_of_order")
            self.last_update = update
            return update

        provenance = self.observations.prepare_delta(event)
        if provenance.disposition in {"duplicate", "ignored"}:
            update = self._update_for(previous, previous, provenance, {})
            self.last_update = update
            return update

        self._update_active_positive_entities(event)

        paths = self._paths_for_event(previous, event)
        self._last_operation_count = len(paths)
        predecessor_weights = {
            hypothesis.key: hypothesis.log_probability
            for hypothesis in previous.hypotheses
        }
        merged: dict[HypothesisKey, float] = {}
        movement_scores: dict[tuple[str, str], float] = {}
        context_scores: dict[
            HypothesisKey,
            dict[tuple[object, ...], float],
        ] = defaultdict(dict)
        evidence_scores: dict[tuple[object, ...], float] = {}
        context_advances: dict[
            tuple[tuple[object, ...], str, str],
            tuple[
                DirectionalContext,
                tuple[object, ...],
                tuple[object, ...],
            ],
        ] = {}
        for path in paths:
            score = (
                path.log_probability
                + provenance.log_likelihood_by_count[_zone_count(path.key, event.zone)]
            )
            predecessor_key = path.predecessor_key or path.key
            predecessor_weight = predecessor_weights[predecessor_key]
            contexts = self._directional_contexts.get(
                predecessor_key,
                (_contextless(predecessor_weight),),
            )
            for context in contexts:
                source_context_key = _context_key(context)
                context_score = score + context.log_probability - predecessor_weight
                if not path.movements:
                    located_here = event.state == "on" and _zone_count(
                        path.key, event.zone
                    ) > _zone_count(predecessor_key, event.zone)
                    contribution_context = (
                        _started_context(event, provenance.event_id)
                        if located_here
                        else context
                    )
                    contribution_context_key = (
                        _context_key(contribution_context)
                        if located_here
                        else source_context_key
                    )
                    evidence_key = None
                else:
                    source, target = path.movements[0]
                    advance_key = (source_context_key, source, target)
                    cached_advance = context_advances.get(advance_key)
                    if cached_advance is None:
                        contribution_context, evidence_key = self._advance_context(
                            context,
                            source,
                            target,
                            event,
                            provenance.event_id,
                        )
                        contribution_context_key = _context_key(contribution_context)
                        context_advances[advance_key] = (
                            contribution_context,
                            evidence_key,
                            contribution_context_key,
                        )
                    else:
                        (
                            contribution_context,
                            evidence_key,
                            contribution_context_key,
                        ) = cached_advance
                    if contribution_context.disposition == "missed_timing":
                        context_score += math.log(MISSED_TIMING_WEIGHT)
                _merge_log_score(merged, path.key, context_score)
                for movement in path.movements:
                    _merge_log_score(movement_scores, movement, context_score)
                _merge_log_score(
                    context_scores[path.key],
                    contribution_context_key,
                    context_score,
                )
                if evidence_key is not None:
                    _merge_log_score(evidence_scores, evidence_key, context_score)

        total = log_sum_exp(merged.values())
        if total == -math.inf:
            update = self._update_for(
                previous,
                previous,
                _with_disposition(provenance, "impossible_observation"),
                {},
            )
            self.last_update = update
            return update

        normalized = _normalize_dense_weights(
            merged,
            self._configuration_keys,
            event.event_at,
        )
        current = normalized
        self.posterior = current
        compacted_contexts = _normalize_and_compact_contexts(
            context_scores,
            total,
        )
        self._last_context_compaction_count = max(
            0,
            sum(len(contexts) for contexts in context_scores.values())
            - sum(len(contexts) for contexts in compacted_contexts.values()),
        )
        self._directional_contexts = {
            hypothesis.key: compacted_contexts.get(
                hypothesis.key,
                (_contextless(hypothesis.log_probability),),
            )
            for hypothesis in current.hypotheses
        }
        movement_mass = {
            movement: math.exp(score - total)
            for movement, score in movement_scores.items()
        }
        movement_evidence = _movement_evidence(evidence_scores, total)
        update = self._update_for(
            previous,
            current,
            provenance,
            movement_mass,
            movement_evidence,
        )
        self.last_update = update
        return update

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool = False,
    ) -> tuple[FilterUpdate, ...]:
        """Reconcile a complete entity snapshot with one posterior normalization."""

        started_ns = perf_counter_ns()
        try:
            return self._bootstrap(events, cold_start=cold_start)
        finally:
            self._latency_samples_ms.append(
                (perf_counter_ns() - started_ns) / 1_000_000
            )

    def _bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> tuple[FilterUpdate, ...]:
        """Apply one snapshot without the latency instrumentation wrapper."""

        ordered = tuple(sorted(events, key=lambda event: event.entity_id))
        if len({event.entity_id for event in ordered}) != len(ordered):
            raise ValueError("bootstrap snapshot contains duplicate entities")
        if cold_start:
            self.posterior = cold_start_posterior(
                self.map.zones(),
                self.expected_occupants,
                self.posterior.updated_at,
            )
            self._directional_contexts = {
                hypothesis.key: (_contextless(hypothesis.log_probability),)
                for hypothesis in self.posterior.hypotheses
            }
            self.observations.restore_entity_states({})

        previous = self.posterior
        self._update_sequence += 1
        self._last_operation_count = len(previous.hypotheses) * len(ordered)
        self._last_context_compaction_count = 0
        for entities in self._active_positive_entities.values():
            entities.clear()
        provenances = tuple(
            self.observations.prepare_snapshot_delta(event) for event in ordered
        )
        for event in ordered:
            if event.state == "on":
                self._active_positive_entities[event.zone].add(event.entity_id)

        likelihood_by_key = {
            hypothesis.key: sum(
                provenance.log_likelihood_by_count[
                    _zone_count(hypothesis.key, event.zone)
                ]
                for event, provenance in zip(ordered, provenances, strict=True)
            )
            for hypothesis in previous.hypotheses
        }
        total = log_sum_exp(
            hypothesis.log_probability + likelihood_by_key[hypothesis.key]
            for hypothesis in previous.hypotheses
        )
        if total == -math.inf:
            updates = tuple(
                self._update_for(
                    previous,
                    previous,
                    _with_disposition(provenance, "impossible_observation"),
                    {},
                )
                for provenance in provenances
            )
            self.last_update = updates[-1] if updates else None
            return updates

        self.posterior = _normalize_dense_weights(
            {
                hypothesis.key: (
                    hypothesis.log_probability + likelihood_by_key[hypothesis.key]
                )
                for hypothesis in previous.hypotheses
            },
            self._configuration_keys,
            max((event.event_at for event in ordered), default=previous.updated_at),
        )
        self._directional_contexts = {
            hypothesis.key: tuple(
                DirectionalContext(
                    context.origin_zone,
                    context.previous_node_id,
                    context.current_node_id,
                    context.started_at,
                    context.last_event_at,
                    context.evidence_ids,
                    context.log_probability + likelihood_by_key[hypothesis.key] - total,
                )
                for context in self._directional_contexts.get(
                    hypothesis.key,
                    (_contextless(hypothesis.log_probability),),
                )
            )
            for hypothesis in previous.hypotheses
        }
        updates = tuple(
            self._update_for(previous, self.posterior, provenance, {})
            for provenance in provenances
        )
        self.last_update = updates[-1] if updates else None
        return updates

    def set_expected_occupants(
        self,
        expected_occupants: int,
        now: datetime,
    ) -> Posterior:
        """Deterministically reconcile every hypothesis to an exact new count."""

        if not 0 <= expected_occupants <= 2:
            raise ValueError("expected_occupants must be between zero and two")
        if expected_occupants == self.expected_occupants:
            return self.posterior

        reconciled: dict[HypothesisKey, list[float]] = defaultdict(list)
        for hypothesis in self.posterior.hypotheses:
            positions = hypothesis.key.positions
            if expected_occupants > len(positions):
                key = canonical_hypothesis(
                    (
                        *positions,
                        *(
                            PositionState(None)
                            for _ in range(expected_occupants - len(positions))
                        ),
                    )
                )
                reconciled[key].append(hypothesis.log_probability)
                continue

            candidates = {
                canonical_hypothesis(positions[index] for index in indexes)
                for indexes in itertools.combinations(
                    range(len(positions)),
                    expected_occupants,
                )
            }
            share = math.log(len(candidates))
            for key in candidates:
                reconciled[key].append(hypothesis.log_probability - share)

        self._set_configuration_space(expected_occupants)
        self.posterior = _densify_posterior(
            normalize_hypotheses(
                {key: log_sum_exp(values) for key, values in reconciled.items()},
                now,
            ),
            self._configuration_keys,
        )
        self.expected_occupants = expected_occupants
        self.observations.set_expected_occupants(expected_occupants)
        self._directional_contexts = {
            hypothesis.key: (_contextless(hypothesis.log_probability),)
            for hypothesis in self.posterior.hypotheses
        }
        for entities in self._active_positive_entities.values():
            entities.clear()
        self.last_update = None
        return self.posterior

    def _paths_for_event(
        self,
        posterior: Posterior,
        event: OccupancyEvent,
    ) -> tuple[TransitionPath, ...]:
        if event.state != "on":
            return tuple(
                TransitionPath(
                    hypothesis.key,
                    hypothesis.log_probability,
                    (),
                    hypothesis.key,
                )
                for hypothesis in posterior.hypotheses
                if hypothesis.log_probability != -math.inf
            )

        paths: list[TransitionPath] = []
        for hypothesis in posterior.hypotheses:
            if hypothesis.log_probability == -math.inf:
                continue
            key = hypothesis.key
            source_counts: dict[str | None, int] = defaultdict(int)
            for position in key.positions:
                source_counts[position.zone] += 1

            candidates: list[
                tuple[HypothesisKey, float, tuple[tuple[str, str], ...]]
            ] = [(key, 0.35 if source_counts.get(None, 0) else STAY_WEIGHT, ())]
            for source, count in sorted(
                source_counts.items(),
                key=lambda item: (item[0] is None, item[0] or ""),
            ):
                if source == event.zone:
                    continue
                source_index = self._configuration_index[key]
                successor = self._configuration_keys[
                    self._move_indexes[(source_index, source, event.zone)]
                ]
                if source is None:
                    weight = 0.65 * count
                    movements: tuple[tuple[str, str], ...] = ()
                elif event.zone in self.graph.neighbors(source):
                    weight = (
                        ADJACENT_MOVEMENT_WEIGHT
                        * count
                        / max(1, len(self.graph.neighbors(source)))
                    )
                    movements = ((source, event.zone),)
                else:
                    weight = MISSED_MOVEMENT_WEIGHT * count
                    movements = ((source, event.zone),)
                candidates.append((successor, weight, movements))

            total_weight = sum(weight for _, weight, _ in candidates)
            paths.extend(
                TransitionPath(
                    key=candidate,
                    log_probability=(
                        hypothesis.log_probability + math.log(weight / total_weight)
                    ),
                    movements=movements,
                    predecessor_key=key,
                )
                for candidate, weight, movements in candidates
            )
        return tuple(paths)

    def _update_active_positive_entities(self, event: OccupancyEvent) -> None:
        for entities in self._active_positive_entities.values():
            entities.discard(event.entity_id)
        if event.state == "on":
            self._active_positive_entities[event.zone].add(event.entity_id)

    def _advance_context(
        self,
        context: DirectionalContext,
        source: str,
        target: str,
        event: OccupancyEvent,
        event_id: str,
    ) -> tuple[DirectionalContext, tuple[object, ...]]:
        source_node_id = context.current_node_id
        source_node = self.map.nodes.get(source_node_id or "")
        coherent = (
            not context.is_contextless
            and source_node is not None
            and source_node.occupancy_zone == source
        )
        origin = context.origin_zone if coherent else source
        previous_node_id = source_node_id if coherent else None
        started_at = context.started_at if coherent else event.event_at
        evidence_ids = _append_evidence(
            context.evidence_ids if coherent else (),
            event_id,
        )
        graph_valid = target in self.graph.neighbors(source)
        disposition = "graph_valid" if graph_valid else "missed_movement"
        if coherent and context.disposition in {"missed_movement", "missed_timing"}:
            disposition = context.disposition
        elif coherent and graph_valid and context.last_event_at is not None:
            transition_seconds = self.map.transition_seconds_between_nodes(
                source_node_id or "",
                event.node_id,
            )
            allowed_seconds = (
                DEFAULT_TRANSITION_SECONDS
                if transition_seconds is None
                else transition_seconds
            )
            if (
                event.event_at - context.last_event_at
            ).total_seconds() > allowed_seconds:
                disposition = "missed_timing"
        advanced = DirectionalContext(
            origin_zone=origin,
            previous_node_id=previous_node_id,
            current_node_id=event.node_id,
            started_at=started_at,
            last_event_at=event.event_at,
            evidence_ids=evidence_ids,
            log_probability=0.0,
            disposition=disposition,
        )
        evidence_key: tuple[object, ...] = (
            origin,
            source,
            target,
            previous_node_id,
            event.node_id,
            evidence_ids,
            disposition,
        )
        return advanced, evidence_key

    def restore_posterior(self, posterior: Posterior) -> None:
        """Restore a validated normalized posterior for the configured map/count."""

        if any(
            len(hypothesis.key.positions) != self.expected_occupants
            for hypothesis in posterior.hypotheses
        ):
            raise ValueError("posterior occupant count does not match configuration")
        if not math.isclose(probability_sum(posterior), 1.0, abs_tol=1e-12):
            raise ValueError("posterior probabilities must be normalized")
        valid_zones = set(self.map.zones())
        if any(
            position.zone is not None and position.zone not in valid_zones
            for hypothesis in posterior.hypotheses
            for position in hypothesis.key.positions
        ):
            raise ValueError("posterior contains an unknown zone")
        self._restored_context_keys = {
            hypothesis.key for hypothesis in posterior.hypotheses
        }
        self.posterior = _densify_posterior(
            posterior,
            self._configuration_keys,
        )
        self._directional_contexts = {
            hypothesis.key: (_contextless(hypothesis.log_probability),)
            for hypothesis in self.posterior.hypotheses
        }
        self.last_update = None

    def restore_directional_contexts(
        self,
        contexts: dict[HypothesisKey, tuple[DirectionalContext, ...]],
        update_sequence: int,
    ) -> None:
        """Restore bounded contexts only when they exactly preserve posterior mass."""

        if not isinstance(update_sequence, int) or update_sequence < 0:
            raise ValueError("update sequence must be a non-negative integer")
        posterior_weights = {
            hypothesis.key: hypothesis.log_probability
            for hypothesis in self.posterior.hypotheses
        }
        required_keys = self._restored_context_keys or set(posterior_weights)
        if set(contexts) != required_keys:
            raise ValueError("directional contexts do not match posterior keys")
        for key, variants in contexts.items():
            if not variants or len(variants) > 4:
                raise ValueError("each posterior key requires one to four contexts")
            if not math.isclose(
                log_sum_exp(context.log_probability for context in variants),
                posterior_weights[key],
                abs_tol=1e-12,
            ):
                raise ValueError("directional context mass does not match posterior")
        self._directional_contexts = {
            key: contexts.get(key, (_contextless(log_probability),))
            for key, log_probability in posterior_weights.items()
        }
        self._restored_context_keys = None
        self._update_sequence = update_sequence

    def _set_configuration_space(self, expected_occupants: int) -> None:
        self._configuration_keys = _configuration_space(
            self.map.zones(),
            expected_occupants,
        )
        self._configuration_index = {
            key: index for index, key in enumerate(self._configuration_keys)
        }
        self._move_indexes = {}
        for source_index, key in enumerate(self._configuration_keys):
            sources = {position.zone for position in key.positions}
            for source in sources:
                for target in self.map.zones():
                    if source == target:
                        continue
                    successor = _move_one(key, source, target)
                    self._move_indexes[(source_index, source, target)] = (
                        self._configuration_index[successor]
                    )

    def _unchanged_update(
        self,
        event: OccupancyEvent,
        disposition: str,
    ) -> FilterUpdate:
        event_id = f"{event.entity_id}@{event.event_at.isoformat()}:{event.state}"
        provenance = ObservationProvenance(
            event_id=event_id,
            evidence_episode_id=event_id,
            entity_id=event.entity_id,
            node_id=event.node_id,
            zone=event.zone,
            state=event.state,
            signal_type=event.signal_type,
            reliability=event.reliability,
            log_likelihood_by_count=(0.0,) * (self.expected_occupants + 1),
            disposition=disposition,
        )
        return self._update_for(self.posterior, self.posterior, provenance, {})

    def _update_for(
        self,
        previous: Posterior,
        current: Posterior,
        provenance: ObservationProvenance,
        movement_mass: dict[tuple[str, str], float],
        movement_evidence: tuple[MovementEvidence, ...] = (),
    ) -> FilterUpdate:
        previous_occupied = (
            self.last_update.occupied_marginals
            if self.last_update is not None and self.last_update.current is previous
            else zone_marginals(previous, self.map.zones())[0]
        )
        occupied, counts = zone_marginals(current, self.map.zones())
        positive_evidence = self._current_positive_evidence(current.updated_at)
        return FilterUpdate(
            previous=previous,
            current=current,
            occupied_marginals=occupied,
            count_marginals=counts,
            movement_mass=dict(sorted(movement_mass.items())),
            provenance=provenance,
            active_positive_entities={
                zone: tuple(item.entity_id for item in evidence)
                for zone, evidence in positive_evidence.items()
            },
            active_positive_evidence=positive_evidence,
            movement_evidence=movement_evidence,
            previous_occupied_marginals=previous_occupied,
        )

    def _current_positive_evidence(
        self,
        now: datetime,
    ) -> dict[str, tuple[PositiveEvidence, ...]]:
        entity_states = self.observations.entity_states
        result: dict[str, tuple[PositiveEvidence, ...]] = {}
        for zone, entity_ids in self._active_positive_entities.items():
            candidates: list[tuple[PositiveEvidence, datetime]] = []
            for entity_id in entity_ids:
                state = entity_states.get(entity_id)
                binding = self.map.entity_binding_for_entity(entity_id)
                if state is None or state.state != "on" or binding is None:
                    continue
                node = self.map.nodes[binding.node_id]
                behavior = self.map.occupancy_behavior_for_node(node)
                sustained = behavior == "sticky" or binding.signal_type in {
                    "still_target",
                    "target",
                    "zone_occupancy",
                    "presence",
                    "occupancy",
                }
                freshness = (
                    TRANSITION_CORROBORATION_WINDOW
                    if behavior == "transient" or node.role == "transition_gate"
                    else MOTION_CORROBORATION_WINDOW
                )
                if not sustained and now - state.changed_at > freshness:
                    continue
                candidates.append(
                    (
                        PositiveEvidence(
                            entity_id,
                            f"{entity_id}@{state.episode_started_at.isoformat()}",
                            state.changed_at,
                            binding.signal_type,
                        ),
                        state.episode_started_at,
                    )
                )
            latest_episode = max(
                (started_at for _, started_at in candidates),
                default=None,
            )
            result[zone] = tuple(
                sorted(
                    (
                        evidence
                        for evidence, started_at in candidates
                        if latest_episode is not None
                        and latest_episode - started_at
                        <= self.observations.correlation_window
                    ),
                    key=lambda evidence: evidence.entity_id,
                )
            )
        return result


def _context_key(context: DirectionalContext) -> tuple[object, ...]:
    return (
        context.origin_zone,
        context.previous_node_id,
        context.current_node_id,
        context.started_at,
        context.last_event_at,
        context.evidence_ids,
        context.disposition,
    )


def _context_from_key(
    key: tuple[object, ...],
    log_probability: float,
) -> DirectionalContext:
    return DirectionalContext(
        origin_zone=key[0] if isinstance(key[0], str) else None,
        previous_node_id=key[1] if isinstance(key[1], str) else None,
        current_node_id=key[2] if isinstance(key[2], str) else None,
        started_at=key[3] if isinstance(key[3], datetime) else None,
        last_event_at=key[4] if isinstance(key[4], datetime) else None,
        evidence_ids=key[5] if isinstance(key[5], tuple) else (),
        log_probability=log_probability,
        disposition=key[6] if isinstance(key[6], str) else "contextless",
    )


def _context_sort_key(context: DirectionalContext) -> tuple[object, ...]:
    return (
        -context.log_probability,
        context.is_contextless,
        context.origin_zone or "",
        context.previous_node_id or "",
        context.current_node_id or "",
        context.started_at is not None,
        context.started_at,
        context.last_event_at is not None,
        context.last_event_at,
        context.evidence_ids,
        context.disposition,
    )


def _context_score_sort_key(
    item: tuple[tuple[object, ...], float],
) -> tuple[object, ...]:
    key, score = item
    return (
        -score,
        key[0] is None or key[2] is None,
        key[0] or "",
        key[1] or "",
        key[2] or "",
        key[3] is not None,
        key[3],
        key[4] is not None,
        key[4],
        key[5],
        key[6],
    )


def _normalize_and_compact_contexts(
    scores: dict[HypothesisKey, dict[tuple[object, ...], float]],
    total: float,
) -> dict[HypothesisKey, tuple[DirectionalContext, ...]]:
    result: dict[HypothesisKey, tuple[DirectionalContext, ...]] = {}
    for key, variants in scores.items():
        ranked = sorted(
            ((context_key, score - total) for context_key, score in variants.items()),
            key=_context_score_sort_key,
        )
        if len(ranked) > 4:
            retained = [
                item
                for item in ranked
                if item[0][0] is not None and item[0][2] is not None
            ][:3]
            retained_keys = {item[0] for item in retained}
            compacted_mass = log_sum_exp(
                score
                for context_key, score in ranked
                if context_key not in retained_keys
            )
            contexts = [
                *(
                    _context_from_key(context_key, score)
                    for context_key, score in retained
                ),
                _contextless(compacted_mass),
            ]
            contexts.sort(key=_context_sort_key)
        else:
            contexts = [
                _context_from_key(context_key, score) for context_key, score in ranked
            ]
        result[key] = tuple(contexts)
    return result


def _movement_evidence(
    scores: dict[tuple[object, ...], float],
    total: float,
) -> tuple[MovementEvidence, ...]:
    evidence = tuple(
        MovementEvidence(
            path_key=(
                str(key[0]),
                key[3] if isinstance(key[3], str) else None,
                str(key[4]),
            ),
            origin_zone=str(key[0]),
            source_zone=str(key[1]),
            target_zone=str(key[2]),
            coherent_probability=math.exp(score - total),
            source_node_id=key[3] if isinstance(key[3], str) else None,
            target_node_id=str(key[4]),
            evidence_ids=key[5] if isinstance(key[5], tuple) else (),
            disposition=str(key[6]),
        )
        for key, score in scores.items()
    )
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                -item.coherent_probability,
                item.path_key,
                item.source_zone,
                item.target_zone,
                item.evidence_ids,
            ),
        )
    )


def _contextless(log_probability: float) -> DirectionalContext:
    return DirectionalContext(
        None,
        None,
        None,
        None,
        None,
        (),
        log_probability,
        "contextless",
    )


def _started_context(
    event: OccupancyEvent,
    event_id: str,
) -> DirectionalContext:
    return DirectionalContext(
        event.zone,
        None,
        event.node_id,
        event.event_at,
        event.event_at,
        (event_id,),
        0.0,
        "graph_valid",
    )


def _append_evidence(existing: tuple[str, ...], item: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, item)))[-8:]


def _merge_log_score[KeyT](
    scores: dict[KeyT, float],
    key: KeyT,
    score: float,
) -> None:
    previous = scores.get(key)
    if previous is None:
        scores[key] = score
        return
    maximum = max(previous, score)
    scores[key] = maximum + math.log1p(math.exp(-abs(previous - score)))


def _percentile(samples: tuple[float, ...], quantile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def _zone_count(key: HypothesisKey, zone: str) -> int:
    return sum(position.zone == zone for position in key.positions)


def _move_one(
    key: HypothesisKey,
    source: str | None,
    target: str,
) -> HypothesisKey:
    positions = list(key.positions)
    source_index = next(
        index for index, position in enumerate(positions) if position.zone == source
    )
    positions[source_index] = PositionState(target)
    return canonical_hypothesis(positions)


def _configuration_space(
    zones: tuple[str, ...],
    expected_occupants: int,
) -> tuple[HypothesisKey, ...]:
    locations: tuple[str | None, ...] = (*zones, None)
    keys = {
        canonical_hypothesis(PositionState(location) for location in positions)
        for positions in itertools.combinations_with_replacement(
            locations,
            expected_occupants,
        )
    }
    return tuple(sorted(keys, key=hypothesis_sort_key))


def _densify_posterior(
    posterior: Posterior,
    configuration_keys: tuple[HypothesisKey, ...],
) -> Posterior:
    weights = {
        hypothesis.key: hypothesis.log_probability
        for hypothesis in posterior.hypotheses
    }
    if set(weights) != set(configuration_keys):
        unknown = set(weights) - set(configuration_keys)
        if unknown:
            raise ValueError("posterior configurations do not match fixed state space")
    return Posterior(
        tuple(
            sorted(
                (
                    WeightedHypothesis(key, weights.get(key, -math.inf))
                    for key in configuration_keys
                ),
                key=lambda item: (
                    -item.log_probability,
                    hypothesis_sort_key(item.key),
                ),
            )
        ),
        posterior.updated_at,
        posterior.pruned_probability,
    )


def _normalize_dense_weights(
    weights: dict[HypothesisKey, float],
    configuration_keys: tuple[HypothesisKey, ...],
    now: datetime,
) -> Posterior:
    normalized = normalize_hypotheses(weights, now)
    return _densify_posterior(normalized, configuration_keys)


def _with_disposition(
    provenance: ObservationProvenance,
    disposition: str,
) -> ObservationProvenance:
    return ObservationProvenance(
        event_id=provenance.event_id,
        evidence_episode_id=provenance.evidence_episode_id,
        entity_id=provenance.entity_id,
        node_id=provenance.node_id,
        zone=provenance.zone,
        state=provenance.state,
        signal_type=provenance.signal_type,
        reliability=provenance.reliability,
        log_likelihood_by_count=provenance.log_likelihood_by_count,
        disposition=disposition,
    )
