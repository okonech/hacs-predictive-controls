"""Immutable target-model profile and episode types."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

PROFILE_NAMES = frozenset(
    {"entry_boundary", "stay_pir", "stay_presence", "transition_fast"}
)
SENSOR_STATES = frozenset({"off", "on", "unavailable", "unknown"})
EPISODE_STATUSES = frozenset(
    {"asserted", "baseline", "clear", "clearing", "degraded", "unavailable"}
)
BELIEF_CONTEXTS = frozenset(
    {
        "asserted",
        "cleared_with_outward",
        "cleared_without_outward",
        "degraded_asserted",
        "unavailable",
    }
)
BELIEF_CONTRIBUTION_KINDS = frozenset(
    {
        "arrival_transition",
        "availability_clear",
        "count_zero",
        "context_expired",
        "elapsed_decay",
        "health_degraded",
        "health_recovered",
        "local_positive",
        "outward_superseded",
        "stable_clear",
        "unavailable",
    }
)
TRACK_CONFIDENCES = frozenset({"provisional", "confirmed"})
SUPPORT_STATES = frozenset({"moving", "settled"})
SUPPORT_TRANSITIONS = frozenset({"advanced", "coalesced", "created", "settled"})
POLICY_PHASES = frozenset({"inactive", "pending", "predicted", "active"})
ACTIVE_PROVENANCES = frozenset({"evidence", "restored_seed"})
ACTIVE_EVIDENCE_REASONS = frozenset(
    {
        "adjacent_authorized",
        "boundary_authorized",
        "missed_edge_authorized",
        "prediction_confirmed",
        "provisional_track_acquired",
        "same_zone_authorized",
        "track_confirmed",
    }
)
PREDICTION_MATURITY_PROBABILITY = 0.85
PREDICTION_MATURITY_SUPPORT = 5.0


def require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")


def _finite_duration(value: timedelta) -> bool:
    return math.isfinite(value.total_seconds()) and value >= timedelta(0)


@dataclass(frozen=True)
class DecayCalibration:
    """One finite probability baseline and continuous-time constant."""

    baseline_probability: float
    time_constant: timedelta

    def __post_init__(self) -> None:
        if not math.isfinite(self.baseline_probability) or not (
            0.0 < self.baseline_probability < 1.0
        ):
            raise ValueError("Decay baseline probability must be finite and in (0, 1)")
        if not _finite_duration(self.time_constant) or self.time_constant == timedelta(
            0
        ):
            raise ValueError("Decay time constant must be finite and positive")


@dataclass(frozen=True)
class BeliefProfile:
    """Shared binary likelihoods and context decay calibration."""

    profile_id: str
    prior_probability: float
    positive_empty_likelihood: float
    positive_occupied_likelihood: float
    clear_empty_likelihood: float
    clear_occupied_likelihood: float
    asserted: DecayCalibration
    cleared_without_outward: DecayCalibration
    cleared_with_outward: DecayCalibration
    degraded_asserted: DecayCalibration
    unavailable: DecayCalibration

    def __post_init__(self) -> None:
        if self.profile_id not in PROFILE_NAMES:
            raise ValueError(f"Unknown belief profile: {self.profile_id}")
        if not math.isfinite(self.prior_probability) or not (
            0.0 < self.prior_probability < 1.0
        ):
            raise ValueError("Belief prior probability must be finite and in (0, 1)")
        likelihoods = (
            self.positive_empty_likelihood,
            self.positive_occupied_likelihood,
            self.clear_empty_likelihood,
            self.clear_occupied_likelihood,
        )
        if any(
            not math.isfinite(value) or not 0.0 < value <= 1.0 for value in likelihoods
        ):
            raise ValueError("Belief likelihoods must be finite and in (0, 1]")
        if self.positive_occupied_likelihood <= self.positive_empty_likelihood:
            raise ValueError("Positive evidence must favor occupied belief")
        if self.clear_occupied_likelihood >= self.clear_empty_likelihood:
            raise ValueError("Stable clear evidence must favor empty belief")

    def decay_for(self, context: str) -> DecayCalibration:
        match context:
            case "asserted":
                return self.asserted
            case "cleared_without_outward":
                return self.cleared_without_outward
            case "cleared_with_outward":
                return self.cleared_with_outward
            case "degraded_asserted":
                return self.degraded_asserted
            case "unavailable":
                return self.unavailable
            case _:
                raise ValueError(f"Unknown belief context: {context}")


@dataclass(frozen=True)
class OutwardContext:
    """OR-composed outward frontier for one source episode generation."""

    source_episode_id: str
    valid_until: datetime

    def __post_init__(self) -> None:
        if not self.source_episode_id:
            raise ValueError("Outward context episode ID must be non-empty")
        require_utc(self.valid_until, "Outward context expiry")


@dataclass(frozen=True)
class BeliefContribution:
    """One bounded explanation of a local belief or context change."""

    at: datetime
    kind: str
    context_before: str
    context_after: str
    log_odds_delta: float
    episode_id: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.at, "Belief contribution time")
        if self.kind not in BELIEF_CONTRIBUTION_KINDS:
            raise ValueError(f"Unknown belief contribution kind: {self.kind}")
        if (
            self.context_before not in BELIEF_CONTEXTS
            or self.context_after not in BELIEF_CONTEXTS
        ):
            raise ValueError("Belief contribution context is invalid")
        if not math.isfinite(self.log_odds_delta):
            raise ValueError("Belief contribution delta must be finite")


@dataclass(frozen=True)
class ZoneBeliefState:
    """Complete immutable state for one graph-local zone belief."""

    zone: str
    profile_name: str
    log_odds: float
    last_updated_at: datetime
    context: str
    generation_episode_id: str | None = None
    asserted_episode_id: str | None = None
    outward_context: OutwardContext | None = None
    health_warning: bool = False
    contributions: tuple[BeliefContribution, ...] = ()

    def __post_init__(self) -> None:
        if not self.zone:
            raise ValueError("Zone belief zone must be non-empty")
        if self.profile_name not in PROFILE_NAMES:
            raise ValueError(f"Unknown belief profile: {self.profile_name}")
        if not math.isfinite(self.log_odds):
            raise ValueError("Zone belief log odds must be finite")
        require_utc(self.last_updated_at, "Zone belief update time")
        if self.context not in BELIEF_CONTEXTS:
            raise ValueError(f"Unknown belief context: {self.context}")

    @property
    def probability(self) -> float:
        if self.log_odds >= 0.0:
            return 1.0 / (1.0 + math.exp(-self.log_odds))
        exponential = math.exp(self.log_odds)
        return exponential / (1.0 + exponential)


@dataclass(frozen=True)
class SensorProfile:
    """Shared physical timing and residual calibration."""

    profile_id: str
    role: str
    burst_correlation_window: timedelta
    stable_clear_window: timedelta
    hardware_hold_interval: timedelta
    assertion_trust_horizon: timedelta
    post_clear_residual: float
    traversal_context_window: timedelta
    track_bootstrap_window: timedelta

    def __post_init__(self) -> None:
        if not self.profile_id or not self.role:
            raise ValueError("Profile identifiers must be non-empty")
        durations = (
            self.burst_correlation_window,
            self.stable_clear_window,
            self.hardware_hold_interval,
            self.assertion_trust_horizon,
            self.traversal_context_window,
            self.track_bootstrap_window,
        )
        if any(not _finite_duration(value) for value in durations):
            raise ValueError("Profile durations must be finite and non-negative")
        if self.stable_clear_window == timedelta(
            0
        ) or self.assertion_trust_horizon == timedelta(0):
            raise ValueError("Clear and trust durations must be positive")
        if self.burst_correlation_window >= self.stable_clear_window:
            raise ValueError(
                "Burst correlation window must be shorter than stable clear window"
            )
        if not math.isfinite(self.post_clear_residual) or not (
            0.0 <= self.post_clear_residual <= 1.0
        ):
            raise ValueError("Profile post-clear residual must be finite and in [0, 1]")
        if self.track_bootstrap_window == timedelta(0):
            raise ValueError("Track-bootstrap window must be positive")

    @property
    def single_node_reacquisition(self) -> bool:
        """Deprecated v2 behavior retained only until the atomic v3 cutover."""

        return self.role == "stay"


@dataclass(frozen=True)
class PhysicalNode:
    """One target physical sensor process and all of its entity aliases."""

    node_id: str
    zone: str
    aliases: tuple[str, ...]
    profile_name: str
    reliability: float = 1.0
    route_prior_weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.node_id or not self.zone:
            raise ValueError("Physical-node identifiers must be non-empty")
        if not self.aliases or len(self.aliases) != len(set(self.aliases)):
            raise ValueError("Physical node must define at least one unique alias")
        if any(not alias for alias in self.aliases):
            raise ValueError("Physical-node aliases must be non-empty")
        if self.profile_name not in PROFILE_NAMES:
            raise ValueError(f"Unknown sensor profile: {self.profile_name}")
        if not math.isfinite(self.reliability) or not 0 < self.reliability <= 1:
            raise ValueError("Physical-node reliability must be finite and in (0, 1]")
        if not math.isfinite(self.route_prior_weight) or self.route_prior_weight <= 0:
            raise ValueError("Physical-node route prior must be finite and positive")


@dataclass(frozen=True)
class SensorInput:
    """One normalized physical alias state input."""

    entity_id: str
    state: str
    event_at: datetime
    reliability: float = 1.0

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("Sensor entity ID must be non-empty")
        if self.state not in SENSOR_STATES:
            raise ValueError("Sensor state must be on, off, unknown, or unavailable")
        require_utc(self.event_at, "Sensor event time")
        if not math.isfinite(self.reliability) or not 0 < self.reliability <= 1:
            raise ValueError("Sensor reliability must be finite and in (0, 1]")


@dataclass(frozen=True)
class EpisodeEffect:
    """One deduplicated episode fact for a later target-model phase."""

    node_id: str
    zone: str
    episode_id: str
    kind: str
    at: datetime
    reliability: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in {
            "correlated_continuity_authorized",
            "correlated_flap_ignored",
            "impossible_cadence",
            "health_degraded",
            "health_recovered",
            "positive",
            "stable_clear",
        }:
            raise ValueError(f"Unknown episode effect: {self.kind}")
        require_utc(self.at, "Episode effect time")
        if not math.isfinite(self.reliability) or not 0 < self.reliability <= 1:
            raise ValueError("Episode reliability must be finite and in (0, 1]")


@dataclass(frozen=True)
class EpisodeState:
    """Complete immutable state for one physical-node episode process."""

    node_id: str
    zone: str
    profile_name: str
    alias_states: tuple[tuple[str, str], ...]
    generation: int = 0
    episode_id: str | None = None
    status: str = "baseline"
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    advanced_at: datetime | None = None
    clear_started_at: datetime | None = None
    clear_deadline: datetime | None = None
    hold_until: datetime | None = None
    assertion_trust_until: datetime | None = None
    traversal_valid_until: datetime | None = None
    degraded_at: datetime | None = None
    degradation_reason: str | None = None
    clear_emitted: bool = False
    health_warning: bool = False
    cadence_warning: bool = False

    @property
    def known_on(self) -> bool:
        return any(state == "on" for _, state in self.alias_states)


@dataclass(frozen=True)
class EpisodeUpdate:
    """Result of one event or deterministic time-frontier advancement."""

    disposition: str
    state: EpisodeState
    effects: tuple[EpisodeEffect, ...] = ()


@dataclass(frozen=True)
class TraversalToken:
    """One finite anonymous physical-episode traversal frontier."""

    token_id: str
    node_id: str
    zone: str
    role: str
    profile_name: str
    episode_id: str
    accepted_at: datetime
    valid_until: datetime
    track_confidence: str = "provisional"
    path_node_ids: tuple[str, ...] = ()
    provenance_kind: str = "adjacent"
    equivalent_confirmed_strength: bool = False
    continuity_reopened_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.token_id,
                self.node_id,
                self.zone,
                self.role,
                self.profile_name,
                self.episode_id,
            )
        ):
            raise ValueError("Traversal token identifiers must be non-empty")
        require_utc(self.accepted_at, "Traversal token acceptance time")
        require_utc(self.valid_until, "Traversal token expiry")
        if self.continuity_reopened_at is not None:
            require_utc(
                self.continuity_reopened_at,
                "Traversal token continuity reopening",
            )
        if self.valid_until <= self.accepted_at:
            raise ValueError("Traversal token expiry must follow acceptance")
        if self.continuity_reopened_at is not None and not (
            self.accepted_at < self.continuity_reopened_at < self.valid_until
        ):
            raise ValueError("Traversal continuity reopening must be within token time")
        if self.track_confidence not in TRACK_CONFIDENCES:
            raise ValueError("Traversal token track confidence is invalid")
        if not self.path_node_ids or len(self.path_node_ids) > 3:
            raise ValueError("Traversal token path must contain one to three nodes")
        if any(not node_id for node_id in self.path_node_ids):
            raise ValueError("Traversal token path nodes must be non-empty")
        if not self.provenance_kind:
            raise ValueError("Traversal token provenance must be non-empty")
        if not isinstance(self.equivalent_confirmed_strength, bool):
            raise ValueError("Traversal equivalent-strength flag must be boolean")


@dataclass(frozen=True)
class PendingAcquisitionCandidate:
    """One finite unsupported physical episode retained per zone."""

    node_id: str
    zone: str
    profile_name: str
    episode_id: str
    created_at: datetime
    expires_at: datetime
    traversal_valid_until: datetime
    reliability: float

    def __post_init__(self) -> None:
        if not all((self.node_id, self.zone, self.profile_name, self.episode_id)):
            raise ValueError("Pending candidate identifiers must be non-empty")
        if self.profile_name not in PROFILE_NAMES:
            raise ValueError("Pending candidate profile is invalid")
        for value, field in (
            (self.created_at, "Pending candidate creation"),
            (self.expires_at, "Pending candidate expiry"),
            (self.traversal_valid_until, "Pending traversal expiry"),
        ):
            require_utc(value, field)
        if self.expires_at <= self.created_at:
            raise ValueError("Pending candidate expiry must follow creation")
        if self.traversal_valid_until <= self.created_at:
            raise ValueError("Pending traversal expiry must follow creation")
        if not math.isfinite(self.reliability) or not 0 < self.reliability <= 1:
            raise ValueError("Pending candidate reliability must be in (0, 1]")


@dataclass(frozen=True)
class AuthorizationUse:
    """One deduplicated token use by a target episode."""

    token_id: str
    target_episode_id: str
    reason: str
    authorized_at: datetime

    def __post_init__(self) -> None:
        if not self.token_id or not self.target_episode_id or not self.reason:
            raise ValueError("Traversal use identifiers must be non-empty")
        require_utc(self.authorized_at, "Traversal authorization time")


@dataclass(frozen=True)
class TraversalAuthorization:
    """Deterministic graph authorization result for one target episode."""

    target_node_id: str
    target_zone: str
    target_episode_id: str
    authorized_at: datetime
    authorized: bool
    reason: str
    source_tokens: tuple[TraversalToken, ...] = ()
    new_uses: tuple[AuthorizationUse, ...] = ()
    track_confidence: str | None = None
    path_node_ids: tuple[str, ...] = ()
    provenance_kind: str | None = None
    equivalent_confirmed_strength: bool = False

    def __post_init__(self) -> None:
        if not (self.target_node_id and self.target_zone and self.target_episode_id):
            raise ValueError("Traversal target identifiers must be non-empty")
        require_utc(self.authorized_at, "Traversal authorization frontier")
        if not isinstance(self.authorized, bool) or not self.reason:
            raise ValueError("Traversal authorization result is invalid")
        if self.authorized:
            if self.track_confidence not in TRACK_CONFIDENCES:
                raise ValueError("Authorized traversal requires track confidence")
            if not self.path_node_ids or len(self.path_node_ids) > 3:
                raise ValueError("Authorized traversal path is invalid")
            if not self.provenance_kind:
                raise ValueError("Authorized traversal provenance is required")
        elif any(
            (
                self.track_confidence is not None,
                bool(self.path_node_ids),
                self.provenance_kind is not None,
                self.equivalent_confirmed_strength,
            )
        ):
            raise ValueError("Rejected traversal cannot carry track provenance")


@dataclass(frozen=True)
class CountInput:
    """One normalized authoritative occupant-count input."""

    event_id: str
    value: int | None
    available: bool
    event_at: datetime

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("Count event ID must be non-empty")
        if not isinstance(self.available, bool):
            raise ValueError("Count availability must be boolean")
        require_utc(self.event_at, "Count event time")


@dataclass(frozen=True)
class CountState:
    """Last valid count and bounded input diagnostics."""

    expected_count: int
    last_event_at: datetime | None = None
    last_event_id: str | None = None
    positive_transition_at: datetime | None = None
    positive_transition_until: datetime | None = None
    seen_event_ids: tuple[str, ...] = ()
    diagnostics: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.expected_count, int)
            or isinstance(self.expected_count, bool)
            or not 0 <= self.expected_count <= 2
        ):
            raise ValueError("Expected count is outside the supported range")
        for value in (
            self.last_event_at,
            self.positive_transition_at,
            self.positive_transition_until,
        ):
            if value is not None:
                require_utc(value, "Count state time")
        transition_times = (
            self.positive_transition_at,
            self.positive_transition_until,
        )
        if (transition_times[0] is None) != (transition_times[1] is None):
            raise ValueError("Count positive transition must have two frontiers")
        if (
            transition_times[0] is not None
            and transition_times[1] is not None
            and transition_times[1] <= transition_times[0]
        ):
            raise ValueError("Count positive transition expiry must follow its event")
        if len(self.seen_event_ids) != len(set(self.seen_event_ids)) or any(
            not event_id for event_id in self.seen_event_ids
        ):
            raise ValueError("Count event IDs must be unique and non-empty")
        if len(self.diagnostics) != 5 or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.diagnostics
        ):
            raise ValueError(
                "Count diagnostics must contain five non-negative integers"
            )


@dataclass(frozen=True)
class CountUpdate:
    disposition: str
    state: CountState
    categorical_zero: bool = False


@dataclass(frozen=True)
class CountDiagnostics:
    expected_count: int
    evidence_cluster_count: int
    cluster_delta: int


@dataclass(frozen=True)
class AnonymousOccupancySupport:
    """One bounded anonymous count-support lineage and current endpoint."""

    support_id: str
    state: str
    created_at: datetime
    updated_at: datetime
    current_episode_id: str
    current_node_id: str
    current_zone: str
    path_node_ids: tuple[str, ...]
    provenance_kind: str
    valid_until: datetime | None
    last_transition: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.support_id,
                self.current_episode_id,
                self.current_node_id,
                self.current_zone,
                self.provenance_kind,
            )
        ):
            raise ValueError("Anonymous-support identifiers must be non-empty")
        if not self.support_id.startswith("support:"):
            raise ValueError("Anonymous-support ID must derive from a token")
        if self.state not in SUPPORT_STATES:
            raise ValueError("Anonymous-support state is invalid")
        if self.provenance_kind not in {"adjacent", "boundary", "missed_edge"}:
            raise ValueError("Anonymous-support provenance is invalid")
        if self.last_transition not in SUPPORT_TRANSITIONS:
            raise ValueError("Anonymous-support transition is invalid")
        require_utc(self.created_at, "Anonymous-support creation")
        require_utc(self.updated_at, "Anonymous-support update")
        if self.updated_at < self.created_at:
            raise ValueError("Anonymous-support update predates creation")
        if (
            not 1 <= len(self.path_node_ids) <= 3
            or any(not node_id for node_id in self.path_node_ids)
            or self.path_node_ids[-1] != self.current_node_id
        ):
            raise ValueError("Anonymous-support path is inconsistent")
        if self.state == "moving":
            if self.valid_until is None:
                raise ValueError("Moving support requires an expiry")
            require_utc(self.valid_until, "Anonymous-support expiry")
            if self.valid_until <= self.updated_at:
                raise ValueError("Moving-support expiry must follow its update")
        elif self.valid_until is not None:
            raise ValueError("Settled support cannot retain an expiry")


@dataclass(frozen=True)
class SupportTokenBinding:
    """Map one active or retained traversal token to one support."""

    token_id: str
    support_id: str

    def __post_init__(self) -> None:
        if not self.token_id or not self.support_id.startswith("support:"):
            raise ValueError("Support-token binding identifiers are invalid")


@dataclass(frozen=True)
class CountSupport:
    """Immutable support projection consumed by count-conflict evaluation."""

    support_id: str
    endpoint_node_id: str
    endpoint_zone: str
    path_node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((self.support_id, self.endpoint_node_id, self.endpoint_zone)):
            raise ValueError("Count-support identifiers must be non-empty")
        if not self.support_id.startswith("support:"):
            raise ValueError("Count-support ID is invalid")
        if (
            not 1 <= len(self.path_node_ids) <= 3
            or self.path_node_ids[-1] != self.endpoint_node_id
        ):
            raise ValueError("Count-support path is inconsistent")


@dataclass(frozen=True)
class SupportTransitionEvent:
    """Latest bounded support transition diagnostic."""

    support_id: str
    at: datetime
    transition: str
    reason: str
    coalesced_support_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.support_id or not self.reason:
            raise ValueError("Support-transition identifiers must be non-empty")
        require_utc(self.at, "Support-transition time")
        if self.transition not in {*SUPPORT_TRANSITIONS, "removed"}:
            raise ValueError("Support-transition kind is invalid")
        if self.coalesced_support_ids != tuple(
            sorted(set(self.coalesced_support_ids))
        ) or any(not value for value in self.coalesced_support_ids):
            raise ValueError("Coalesced support IDs must be unique and sorted")


@dataclass(frozen=True)
class SupportTransition:
    """Complete atomic next support state returned by the tracker."""

    supports: tuple[AnonymousOccupancySupport, ...]
    bindings: tuple[SupportTokenBinding, ...]
    latest_transition: SupportTransitionEvent | None = None

    def __post_init__(self) -> None:
        support_ids = tuple(item.support_id for item in self.supports)
        if support_ids != tuple(sorted(set(support_ids))):
            raise ValueError("Anonymous supports must be unique and sorted")
        token_ids = tuple(item.token_id for item in self.bindings)
        if token_ids != tuple(sorted(set(token_ids))):
            raise ValueError("Support-token bindings must be unique and sorted")
        known_support_ids = set(support_ids)
        if any(item.support_id not in known_support_ids for item in self.bindings):
            raise ValueError("Support-token binding references an absent support")


@dataclass(frozen=True)
class CountConflictState:
    """One continuous count contradiction for an asserted stay episode."""

    target_node_id: str
    target_zone: str
    target_episode_id: str
    started_at: datetime
    last_evaluated_at: datetime
    deadline: datetime
    support_ids: tuple[str, ...]
    degraded_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all((self.target_node_id, self.target_zone, self.target_episode_id)):
            raise ValueError("Count-conflict identifiers must be non-empty")
        for value, label in (
            (self.started_at, "Count-conflict start"),
            (self.last_evaluated_at, "Count-conflict evaluation"),
            (self.deadline, "Count-conflict deadline"),
        ):
            require_utc(value, label)
        if not self.started_at <= self.last_evaluated_at <= self.deadline:
            if self.degraded_at is None or self.last_evaluated_at < self.started_at:
                raise ValueError("Count-conflict frontiers are inconsistent")
        if self.deadline <= self.started_at:
            raise ValueError("Count-conflict deadline must follow its start")
        if self.support_ids != tuple(sorted(set(self.support_ids))):
            raise ValueError("Count-conflict support IDs must be unique and sorted")
        if not self.support_ids:
            raise ValueError("Count conflict requires anonymous supports")
        if self.degraded_at is not None:
            require_utc(self.degraded_at, "Count-conflict degradation")
            if self.degraded_at < self.deadline:
                raise ValueError("Count-conflict degradation predates its deadline")


@dataclass(frozen=True)
class PolicyCalibration:
    """Shared Schmitt thresholds and release dwell for one profile."""

    profile_name: str
    on_threshold: float
    off_threshold: float
    release_dwell: timedelta

    def __post_init__(self) -> None:
        if self.profile_name not in PROFILE_NAMES:
            raise ValueError(f"Unknown policy profile: {self.profile_name}")
        if not 0.0 < self.off_threshold < self.on_threshold < 1.0:
            raise ValueError("Policy thresholds must satisfy 0 < off < on < 1")
        if not _finite_duration(self.release_dwell) or self.release_dwell == timedelta(
            0
        ):
            raise ValueError("Policy release dwell must be finite and positive")


@dataclass(frozen=True)
class RefreshDedupEntry:
    """One finite acquired or refreshed episode publication guard."""

    episode_id: str
    published_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("Refresh episode ID must be non-empty")
        require_utc(self.published_at, "Refresh publication time")
        require_utc(self.expires_at, "Refresh deduplication expiry")
        if self.expires_at <= self.published_at:
            raise ValueError("Refresh expiry must follow publication")


@dataclass(frozen=True)
class ZonePolicyState:
    """Immutable active projection and pending release state for one zone."""

    zone: str
    profile_name: str
    active: bool
    last_evaluated_at: datetime
    pending_release_since: datetime | None = None
    refresh_dedup: tuple[RefreshDedupEntry, ...] = ()
    phase: str = "inactive"
    activation_provenance: str | None = None
    prediction_expires_at: datetime | None = None
    prediction_source_episode_id: str | None = None
    prediction_probability: float | None = None
    prediction_support: float | None = None
    activation_episode_id: str | None = None
    activation_at: datetime | None = None
    activation_reason: str | None = None
    activation_track_confidence: str | None = None
    activation_path_node_ids: tuple[str, ...] = ()
    activation_provenance_kind: str | None = None
    activation_source_episode_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.zone or self.profile_name not in PROFILE_NAMES:
            raise ValueError("Policy state zone and profile must be valid")
        if not isinstance(self.active, bool):
            raise ValueError("Policy active state must be boolean")
        if self.phase not in POLICY_PHASES:
            raise ValueError("Policy phase is invalid")
        require_utc(self.last_evaluated_at, "Policy evaluation time")
        if self.pending_release_since is not None:
            require_utc(self.pending_release_since, "Pending release time")
            if not self.active or self.pending_release_since > self.last_evaluated_at:
                raise ValueError("Pending release requires current active state")
        if self.prediction_expires_at is not None:
            require_utc(self.prediction_expires_at, "Prediction policy expiry")
        if self.prediction_source_episode_id == "":
            raise ValueError("Prediction source episode ID must be non-empty")
        if self.activation_episode_id == "" or self.activation_reason == "":
            raise ValueError("Policy activation evidence must be non-empty")
        if self.activation_provenance_kind == "":
            raise ValueError("Policy activation provenance must be non-empty")
        if self.activation_track_confidence is not None and (
            self.activation_track_confidence not in TRACK_CONFIDENCES
        ):
            raise ValueError("Policy activation track confidence is invalid")
        if (
            len(self.activation_path_node_ids) > 3
            or any(not node_id for node_id in self.activation_path_node_ids)
            or len(self.activation_source_episode_ids)
            != len(set(self.activation_source_episode_ids))
            or any(not episode_id for episode_id in self.activation_source_episode_ids)
        ):
            raise ValueError("Policy activation evidence references are invalid")
        if self.activation_at is not None:
            require_utc(self.activation_at, "Policy activation time")
        for value in (self.prediction_probability, self.prediction_support):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(
                    "Prediction policy metrics must be finite and non-negative"
                )
        prediction_fields = (
            self.prediction_expires_at,
            self.prediction_source_episode_id,
            self.prediction_probability,
            self.prediction_support,
        )
        if self.phase == "predicted":
            if (
                not self.active
                or self.activation_provenance != "prediction"
                or any(value is None for value in prediction_fields)
                or self.prediction_expires_at is None
                or self.prediction_expires_at <= self.last_evaluated_at
                or self.prediction_probability is None
                or not (
                    PREDICTION_MATURITY_PROBABILITY
                    <= self.prediction_probability
                    <= 1.0
                )
                or self.prediction_support is None
                or self.prediction_support < PREDICTION_MATURITY_SUPPORT
            ):
                raise ValueError("Predicted policy state is inconsistent")
        elif any(value is not None for value in prediction_fields):
            raise ValueError("Non-predicted policy retains prediction state")
        if self.phase in {"inactive", "pending"} and self.active:
            raise ValueError("Inactive policy phase cannot be active")
        if self.phase == "active" and not self.active:
            raise ValueError("Active policy phase must be active")
        if (
            self.phase in {"inactive", "pending"}
            and self.activation_provenance is not None
        ):
            raise ValueError("Inactive policy phase retains activation provenance")
        if (
            self.phase == "active"
            and self.activation_provenance not in ACTIVE_PROVENANCES
        ):
            raise ValueError("Active policy provenance is invalid")
        activation_fields = (
            self.activation_episode_id,
            self.activation_at,
            self.activation_reason,
            self.activation_track_confidence,
            self.activation_provenance_kind,
        )
        if self.phase == "active" and self.activation_provenance == "evidence":
            if (
                any(value is None for value in activation_fields[:3])
                or self.activation_at is None
                or self.activation_at > self.last_evaluated_at
                or self.activation_reason not in ACTIVE_EVIDENCE_REASONS
                or not self.activation_path_node_ids
                or (
                    self.activation_reason == "prediction_confirmed"
                    and (
                        self.activation_track_confidence is not None
                        or self.activation_provenance_kind
                        != "prediction_confirmation"
                        or len(self.activation_path_node_ids) != 1
                        or self.activation_source_episode_ids
                    )
                )
                or (
                    self.activation_reason != "prediction_confirmed"
                    and (
                        self.activation_track_confidence is None
                        or self.activation_provenance_kind is None
                    )
                )
            ):
                raise ValueError("Evidence-active policy lacks acquisition evidence")
        elif (
            any(value is not None for value in activation_fields)
            or self.activation_path_node_ids
            or self.activation_source_episode_ids
        ):
            raise ValueError("Policy retains incompatible activation evidence")
        if len(self.refresh_dedup) > 256:
            raise ValueError("Refresh deduplication state exceeds its bound")
        episode_ids = tuple(item.episode_id for item in self.refresh_dedup)
        if len(episode_ids) != len(set(episode_ids)):
            raise ValueError("Refresh deduplication episode IDs must be unique")
        publication_times = tuple(item.published_at for item in self.refresh_dedup)
        if publication_times != tuple(sorted(publication_times)):
            raise ValueError("Refresh deduplication entries must be time ordered")
        if any(
            item.published_at > self.last_evaluated_at
            or item.expires_at <= self.last_evaluated_at
            for item in self.refresh_dedup
        ):
            raise ValueError(
                "Refresh deduplication entry is outside the state frontier"
            )


@dataclass(frozen=True)
class PolicyEvent:
    """One target active edge or optional arrival publication."""

    kind: str
    event_at: datetime
    zone: str
    episode_id: str | None
    belief: float
    authorization_reason: str | None
    policy_reason: str

    def __post_init__(self) -> None:
        if self.kind not in {"acquired", "refreshed", "released"}:
            raise ValueError(f"Unknown policy event: {self.kind}")
        require_utc(self.event_at, "Policy event time")
        if not self.zone or self.episode_id == "":
            raise ValueError("Policy event identifiers must be non-empty")
        if self.kind in {"acquired", "refreshed"} and self.episode_id is None:
            raise ValueError("Arrival policy events require an episode ID")
        if not math.isfinite(self.belief) or not 0.0 <= self.belief <= 1.0:
            raise ValueError("Policy event belief must be finite and in [0, 1]")
        if self.authorization_reason == "" or not self.policy_reason:
            raise ValueError("Policy event reasons must be non-empty")


@dataclass(frozen=True)
class PolicyDecision:
    """One compact zone-local policy explanation row."""

    event_at: datetime
    processing_at: datetime
    zone: str
    node_id: str | None
    episode_id: str | None
    profile_name: str
    belief_before: float
    belief_after: float
    active_before: bool
    active_after: bool
    local_evidence_kind: str | None
    local_trustworthy: bool
    authorization_authorized: bool
    traversal_reason: str | None
    evidence_ids: tuple[str, ...]
    count_zero: bool
    health_warning: bool
    on_threshold: float
    off_threshold: float
    release_dwell: timedelta
    pending_release_since: datetime | None
    event_kind: str | None
    reason: str
    count_conflict_support_ids: tuple[str, ...] = ()
    reliability_result: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.event_at, "Policy decision event time")
        require_utc(self.processing_at, "Policy decision processing time")
        if self.processing_at < self.event_at:
            raise ValueError("Policy decision processing cannot precede event time")
        if not self.zone or self.profile_name not in PROFILE_NAMES:
            raise ValueError("Policy decision zone and profile must be valid")
        if self.node_id == "" or self.episode_id == "":
            raise ValueError("Policy decision evidence identifiers must be non-empty")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in (self.belief_before, self.belief_after)
        ):
            raise ValueError("Policy decision beliefs must be finite and in [0, 1]")
        if not all(
            isinstance(value, bool)
            for value in (
                self.active_before,
                self.active_after,
                self.local_trustworthy,
                self.authorization_authorized,
                self.count_zero,
                self.health_warning,
            )
        ):
            raise ValueError("Policy decision flags must be boolean")
        if self.local_evidence_kind not in {
            None,
            "correlated_continuity_authorized",
            "correlated_flap_ignored",
            "health_degraded",
            "health_recovered",
            "impossible_cadence",
            "positive",
            "stable_clear",
        }:
            raise ValueError("Policy decision local evidence kind is invalid")
        if self.traversal_reason == "":
            raise ValueError("Policy decision traversal reason must be non-empty")
        if len(self.evidence_ids) != len(set(self.evidence_ids)) or any(
            not evidence_id for evidence_id in self.evidence_ids
        ):
            raise ValueError(
                "Policy decision evidence IDs must be unique and non-empty"
            )
        if not 0.0 < self.off_threshold < self.on_threshold < 1.0:
            raise ValueError("Policy decision thresholds must satisfy 0 < off < on < 1")
        if not _finite_duration(self.release_dwell) or self.release_dwell == timedelta(
            0
        ):
            raise ValueError(
                "Policy decision release dwell must be finite and positive"
            )
        if self.pending_release_since is not None:
            require_utc(self.pending_release_since, "Policy pending release time")
            if not self.active_after or self.pending_release_since > self.event_at:
                raise ValueError("Policy pending release requires current active state")
        if self.event_kind not in {None, "acquired", "refreshed", "released"}:
            raise ValueError("Policy decision event kind is invalid")
        expected_edge = {
            "acquired": (False, True),
            "refreshed": (True, True),
            "released": (True, False),
        }
        if self.event_kind is not None and expected_edge[self.event_kind] != (
            self.active_before,
            self.active_after,
        ):
            raise ValueError("Policy decision event contradicts its active edge")
        if not self.reason:
            raise ValueError("Policy decision reason must be non-empty")
        if self.count_conflict_support_ids != tuple(
            sorted(set(self.count_conflict_support_ids))
        ) or any(not support_id for support_id in self.count_conflict_support_ids):
            raise ValueError(
                "Policy decision count-conflict support IDs must be unique and sorted"
            )
        if self.reliability_result not in {None, "degraded", "recovered"}:
            raise ValueError("Policy decision reliability result is invalid")
        if bool(self.count_conflict_support_ids) != bool(self.reliability_result):
            raise ValueError(
                "Policy decision count-conflict diagnostics must be complete"
            )


@dataclass(frozen=True)
class PolicyUpdate:
    state: ZonePolicyState
    event: PolicyEvent | None
    decision: PolicyDecision


@dataclass(frozen=True)
class ZoneModelSnapshot:
    """Complete bounded target state at one event-time frontier."""

    updated_at: datetime
    episode_states: tuple[EpisodeState, ...]
    belief_states: tuple[ZoneBeliefState, ...]
    traversal_tokens: tuple[TraversalToken, ...]
    current_token_ids: tuple[str, ...]
    authorization_uses: tuple[AuthorizationUse, ...]
    count_state: CountState
    policy_states: tuple[ZonePolicyState, ...]
    pending_candidates: tuple[PendingAcquisitionCandidate, ...] = ()
    count_conflicts: tuple[CountConflictState, ...] = ()
    retained_traversal_tokens: tuple[TraversalToken, ...] = ()
    anonymous_supports: tuple[AnonymousOccupancySupport, ...] = ()
    support_token_bindings: tuple[SupportTokenBinding, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.updated_at, "Zone-model snapshot time")
        for states, label in (
            (self.episode_states, "episode node"),
            (self.belief_states, "belief zone"),
            (self.policy_states, "policy zone"),
        ):
            identifiers = tuple(
                getattr(state, "node_id", getattr(state, "zone", ""))
                for state in states
            )
            if identifiers != tuple(sorted(identifiers)) or len(identifiers) != len(
                set(identifiers)
            ):
                raise ValueError(f"Zone-model {label} state must be unique and sorted")
        if self.current_token_ids != tuple(sorted(set(self.current_token_ids))):
            raise ValueError(
                "Zone-model current traversal tokens must be unique and sorted"
            )
        retained_ids = tuple(item.token_id for item in self.retained_traversal_tokens)
        if retained_ids != tuple(sorted(set(retained_ids))):
            raise ValueError("Retained traversal tokens must be unique and sorted")
        pending_zones = tuple(item.zone for item in self.pending_candidates)
        if pending_zones != tuple(sorted(set(pending_zones))):
            raise ValueError("Pending candidates must be unique and sorted by zone")
        SupportTransition(self.anonymous_supports, self.support_token_bindings)
        conflict_nodes = tuple(item.target_node_id for item in self.count_conflicts)
        if conflict_nodes != tuple(sorted(set(conflict_nodes))):
            raise ValueError("Count conflicts must be unique and sorted")


@dataclass(frozen=True)
class ZoneModelResult:
    """One ordered target operation result without public side effects."""

    disposition: str
    snapshot: ZoneModelSnapshot
    policy_events: tuple[PolicyEvent, ...] = ()
    policy_decisions: tuple[PolicyDecision, ...] = ()
    authorizations: tuple[TraversalAuthorization, ...] = ()
