from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class PositionState:
    """One anonymous occupant position within a joint hypothesis."""

    zone: str | None
    incoming_zone: str | None = None
    entered_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HypothesisKey:
    """Canonical exchangeable joint occupancy configuration."""

    positions: tuple[PositionState, ...]
    _hash: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_hash", hash(self.positions))

    def __hash__(self) -> int:
        return self._hash


@dataclass(frozen=True)
class WeightedHypothesis:
    """One normalized hypothesis represented in log space."""

    key: HypothesisKey
    log_probability: float


@dataclass(frozen=True)
class Posterior:
    """Normalized deterministic posterior over joint configurations."""

    hypotheses: tuple[WeightedHypothesis, ...]
    updated_at: datetime
    pruned_probability: float = 0.0


@dataclass(frozen=True)
class EntityEvidence:
    """Latest likelihood contribution retained for one physical entity."""

    state: str
    log_likelihood_by_count: tuple[float, ...]
    changed_at: datetime
    episode_started_at: datetime
    duration_log_odds: float = 0.0
    departure_observed: bool = False


@dataclass(frozen=True)
class PendingDeparture:
    """Accumulated path evidence carrying occupancy away from one origin."""

    origin: str
    current: str
    probability: float
    nonadjacent: bool
    evidence_ids: tuple[str, ...]
    disposition: str = "graph_valid"
    segment_probability: float | None = None
    destination_movement_probability: float | None = None
    source_episode_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservationProvenance:
    """Machine-readable evidence contribution for one sensor update."""

    event_id: str
    evidence_episode_id: str
    entity_id: str
    node_id: str
    zone: str
    state: str
    signal_type: str
    reliability: float
    log_likelihood_by_count: tuple[float, ...]
    disposition: str


@dataclass(frozen=True)
class PositiveEvidence:
    """One fresh, currently asserted entity episode eligible for corroboration."""

    entity_id: str
    evidence_episode_id: str
    changed_at: datetime
    signal_type: str
    node_id: str | None = None


@dataclass(frozen=True)
class DirectionalContext:
    """Bounded path metadata associated with occupancy probability mass."""

    origin_zone: str | None
    previous_node_id: str | None
    current_node_id: str | None
    started_at: datetime | None
    last_event_at: datetime | None
    evidence_ids: tuple[str, ...]
    log_probability: float
    disposition: str = "contextless"
    assertion_valid_until: datetime | None = None

    @property
    def is_contextless(self) -> bool:
        return self.origin_zone is None or self.current_node_id is None


@dataclass(frozen=True)
class MovementEvidence:
    """One coherent predecessor-specific movement contribution."""

    path_key: tuple[str, str | None, str]
    origin_zone: str
    source_zone: str
    target_zone: str
    coherent_probability: float
    source_node_id: str | None
    target_node_id: str
    evidence_ids: tuple[str, ...]
    disposition: str
    via_zone: str | None = None
    via_node_id: str | None = None


def competing_current_update_source_nodes(
    movement_evidence: tuple[MovementEvidence, ...],
    active_positive_evidence: Mapping[str, tuple[PositiveEvidence, ...]],
    *,
    origin_source_zone: str,
    target_zone: str,
    target_node_id: str,
    target_event_id: str,
) -> tuple[str, ...]:
    competing_nodes: set[str] = set()
    for evidence in movement_evidence:
        if (
            evidence.disposition != "graph_valid"
            or evidence.source_zone == origin_source_zone
            or evidence.target_zone != target_zone
            or evidence.target_node_id != target_node_id
            or target_event_id not in evidence.evidence_ids
        ):
            continue
        for positive in active_positive_evidence.get(evidence.source_zone, ()):
            source_edge_id = (
                f"{positive.entity_id}@{positive.changed_at.isoformat()}:on"
            )
            if source_edge_id not in evidence.evidence_ids:
                continue
            if (
                positive.node_id is not None
                and evidence.source_node_id != positive.node_id
            ):
                continue
            competing_nodes.add(positive.node_id or positive.entity_id)
    return tuple(sorted(competing_nodes))


@dataclass(frozen=True)
class FilterUpdate:
    """One immutable posterior update and its derived evidence."""

    previous: Posterior
    current: Posterior
    occupied_marginals: Mapping[str, float]
    count_marginals: Mapping[str, tuple[float, ...]]
    movement_mass: Mapping[tuple[str, str], float]
    provenance: ObservationProvenance
    active_positive_entities: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    active_positive_evidence: Mapping[str, tuple[PositiveEvidence, ...]] = field(
        default_factory=dict
    )
    movement_evidence: tuple[MovementEvidence, ...] = ()
    previous_occupied_marginals: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ZonePolicyState:
    """Automation-facing latched policy for one zone."""

    keep_on: bool = False
    activation_expires_at: datetime | None = None
    last_trusted_at: datetime | None = None
    last_release_cause: ReleaseCause | None = None
    recovery_eligible: bool = False
    reason: str = "no trusted occupancy"
    evidence_ids: tuple[str, ...] = ()
    blocked_episode_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    """One accepted or rejected automation-policy gate evaluation."""

    zone: str
    action: str
    accepted: bool
    reason_code: str
    gate_values: Mapping[str, float | bool | str]
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingDepartureAudit:
    """One pending departure snapshot retained with an observation audit."""

    origin: str
    current: str
    probability: float
    nonadjacent: bool
    evidence_ids: tuple[str, ...]
    disposition: str
    segment_probability: float | None = None
    destination_movement_probability: float | None = None
    source_episode_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyAuditContext:
    """Filter evidence needed to reconstruct one policy evaluation."""

    provenance: ObservationProvenance
    previous_occupied_marginals: Mapping[str, float]
    occupied_marginals: Mapping[str, float]
    count_marginals: Mapping[str, tuple[float, ...]]
    active_positive_evidence: Mapping[str, tuple[PositiveEvidence, ...]]
    movement_evidence: tuple[MovementEvidence, ...]
    pending_departures: tuple[PendingDepartureAudit, ...]


@dataclass(frozen=True)
class PackedPolicyAuditContext:
    """Losslessly compressed complete context retained outside the event path."""

    compressed_json: bytes


@dataclass(frozen=True)
class PolicyAuditEntry:
    """One timestamped policy decision retained for post-incident diagnosis."""

    decision_at: datetime
    source: str
    trigger_event_id: str
    trigger_entity_id: str | None
    trigger_zone: str | None
    trigger_state: str | None
    trigger_disposition: str | None
    decision: PolicyDecision
    previous_keep_on: bool
    current_keep_on: bool
    previous_reason: str
    current_reason: str
    previous_release_cause: ReleaseCause | None
    current_release_cause: ReleaseCause | None
    context: PolicyAuditContext | PackedPolicyAuditContext | None = None


class ReleaseCause(StrEnum):
    """Machine-readable cause for a keep-on release."""

    GRAPH_DEPARTURE = "graph_departure"
    CONFIRMED_RELOCATION = "confirmed_relocation"
    COUNT_REDUCTION = "count_reduction"
    AUTHORITATIVE_AWAY = "authoritative_away"
    EXPLICIT_RESET = "explicit_reset"
    PROVISIONAL_FALSE_OFF = "provisional_false_off"
    RELEASE_SAFE = "release_safe"


@dataclass(frozen=True)
class PredictionLease:
    """One time-bounded prediction from a directional movement path."""

    path_key: tuple[str, str | None, str]
    target_zone: str
    probability: float
    expires_at: datetime
    reason: str


def position_sort_key(position: PositionState) -> tuple[bool, str, str, str]:
    """Return a total ordering that never compares optional values directly."""

    return (
        position.zone is None,
        position.zone or "",
        position.incoming_zone or "",
        position.entered_at.isoformat() if position.entered_at else "",
    )


def hypothesis_sort_key(key: HypothesisKey) -> tuple[tuple[bool, str, str, str], ...]:
    """Return the deterministic ordering key for a joint configuration."""

    return tuple(position_sort_key(position) for position in key.positions)


def canonical_hypothesis(positions: Iterable[PositionState]) -> HypothesisKey:
    """Canonicalize exchangeable positions without dropping multiplicity."""

    return HypothesisKey(tuple(sorted(positions, key=position_sort_key)))


def initial_posterior(expected_occupants: int, now: datetime) -> Posterior:
    """Create a certain all-unlocated posterior for an authoritative count."""

    if expected_occupants < 0:
        raise ValueError("expected_occupants must be non-negative")
    key = canonical_hypothesis(
        PositionState(zone=None) for _ in range(expected_occupants)
    )
    return Posterior((WeightedHypothesis(key, 0.0),), now)


def cold_start_posterior(
    zones: Iterable[str],
    expected_occupants: int,
    now: datetime,
    *,
    unlocated_weight: float = 4.0,
) -> Posterior:
    """Create a full anonymous prior with extra weight on unlocated positions."""

    if expected_occupants < 0:
        raise ValueError("expected_occupants must be non-negative")
    if not math.isfinite(unlocated_weight) or unlocated_weight <= 0.0:
        raise ValueError("unlocated_weight must be finite and positive")
    locations: tuple[str | None, ...] = (None, *sorted(set(zones)))
    weights: dict[HypothesisKey, float] = {}
    for positions in itertools.combinations_with_replacement(
        locations,
        expected_occupants,
    ):
        counts = {location: positions.count(location) for location in set(positions)}
        multiplicity = math.factorial(expected_occupants)
        for count in counts.values():
            multiplicity //= math.factorial(count)
        log_weight = math.log(multiplicity)
        log_weight += sum(
            math.log(unlocated_weight) if location is None else 0.0
            for location in positions
        )
        weights[
            canonical_hypothesis(PositionState(location) for location in positions)
        ] = log_weight
    return normalize_hypotheses(weights, now)


def log_sum_exp(values: Iterable[float]) -> float:
    """Stably add log-space values, including all-impossible alternatives."""

    items = tuple(values)
    if not items:
        return -math.inf
    if len(items) == 1:
        return items[0]
    maximum = max(items)
    if maximum == -math.inf:
        return -math.inf
    return maximum + math.log(sum(math.exp(value - maximum) for value in items))


def normalize_hypotheses(
    log_weights: Mapping[HypothesisKey, float],
    now: datetime,
) -> Posterior:
    """Normalize and deterministically order finite joint log weights."""

    if not log_weights:
        raise ValueError("at least one hypothesis is required")
    if any(math.isnan(value) or value == math.inf for value in log_weights.values()):
        raise ValueError("hypothesis log weights must not contain NaN or +infinity")
    total = log_sum_exp(log_weights.values())
    if total == -math.inf:
        raise ValueError("at least one hypothesis must be possible")
    hypotheses = tuple(
        sorted(
            (
                WeightedHypothesis(key, value - total)
                for key, value in log_weights.items()
                if value != -math.inf
            ),
            key=lambda item: (-item.log_probability, hypothesis_sort_key(item.key)),
        )
    )
    return Posterior(hypotheses, now)


def deterministic_prune(
    posterior: Posterior,
    *,
    exact_limit: int = 512,
    retained_probability: float = 0.999999,
    hard_limit: int = 4096,
) -> Posterior:
    """Retain deterministic top mass while reporting the discarded probability."""

    if len(posterior.hypotheses) <= exact_limit:
        return posterior
    retained: list[WeightedHypothesis] = []
    retained_mass = 0.0
    for hypothesis in posterior.hypotheses:
        if len(retained) >= hard_limit:
            break
        retained.append(hypothesis)
        retained_mass += math.exp(hypothesis.log_probability)
        if retained_mass >= retained_probability:
            break
    renormalized = normalize_hypotheses(
        {item.key: item.log_probability for item in retained},
        posterior.updated_at,
    )
    return Posterior(
        renormalized.hypotheses,
        posterior.updated_at,
        max(0.0, 1.0 - retained_mass),
    )


def zone_marginals(
    posterior: Posterior,
    zones: Iterable[str],
) -> tuple[dict[str, float], dict[str, tuple[float, ...]]]:
    """Return occupied and exact-count marginals for every configured zone."""

    zone_ids = tuple(sorted(set(zones)))
    occupant_count = max(
        (len(item.key.positions) for item in posterior.hypotheses),
        default=0,
    )
    counts = {zone: [0.0] * (occupant_count + 1) for zone in zone_ids}
    probabilities: list[float] = []
    for hypothesis in posterior.hypotheses:
        probability = math.exp(hypothesis.log_probability)
        probabilities.append(probability)
        represented: dict[str, int] = {}
        for position in hypothesis.key.positions:
            if position.zone in counts:
                represented[position.zone] = represented.get(position.zone, 0) + 1
        for zone, count in represented.items():
            counts[zone][count] += probability
    total_probability = math.fsum(probabilities)
    for values in counts.values():
        values[0] = max(0.0, total_probability - math.fsum(values[1:]))
    count_marginals = {zone: tuple(values) for zone, values in counts.items()}
    occupied = {zone: sum(values[1:]) for zone, values in count_marginals.items()}
    return occupied, count_marginals


def probability_sum(posterior: Posterior) -> float:
    """Return the linear-space normalization sum for invariant checks."""

    return sum(math.exp(item.log_probability) for item in posterior.hypotheses)
