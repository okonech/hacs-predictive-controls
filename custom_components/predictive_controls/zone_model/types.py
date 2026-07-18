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
        "count_zero",
        "context_expired",
        "elapsed_decay",
        "health_degraded",
        "health_recovered",
        "local_positive",
        "stable_clear",
        "unavailable",
    }
)


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
    single_node_reacquisition: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id or not self.role:
            raise ValueError("Profile identifiers must be non-empty")
        durations = (
            self.burst_correlation_window,
            self.stable_clear_window,
            self.hardware_hold_interval,
            self.assertion_trust_horizon,
            self.traversal_context_window,
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
        if not isinstance(self.single_node_reacquisition, bool):
            raise ValueError("Single-node reacquisition capability must be boolean")


@dataclass(frozen=True)
class PhysicalNode:
    """One target physical sensor process and all of its entity aliases."""

    node_id: str
    zone: str
    aliases: tuple[str, ...]
    profile_name: str

    def __post_init__(self) -> None:
        if not self.node_id or not self.zone:
            raise ValueError("Physical-node identifiers must be non-empty")
        if not self.aliases or len(self.aliases) != len(set(self.aliases)):
            raise ValueError("Physical node must define at least one unique alias")
        if any(not alias for alias in self.aliases):
            raise ValueError("Physical-node aliases must be non-empty")
        if self.profile_name not in PROFILE_NAMES:
            raise ValueError(f"Unknown sensor profile: {self.profile_name}")


@dataclass(frozen=True)
class SensorInput:
    """One normalized physical alias state input."""

    entity_id: str
    state: str
    event_at: datetime

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("Sensor entity ID must be non-empty")
        if self.state not in SENSOR_STATES:
            raise ValueError("Sensor state must be on, off, unknown, or unavailable")
        require_utc(self.event_at, "Sensor event time")


@dataclass(frozen=True)
class EpisodeEffect:
    """One deduplicated episode fact for a later target-model phase."""

    node_id: str
    zone: str
    episode_id: str
    kind: str
    at: datetime

    def __post_init__(self) -> None:
        if self.kind not in {
            "health_degraded",
            "health_recovered",
            "positive",
            "stable_clear",
        }:
            raise ValueError(f"Unknown episode effect: {self.kind}")
        require_utc(self.at, "Episode effect time")


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
    clear_emitted: bool = False
    health_warning: bool = False

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
        if self.valid_until <= self.accepted_at:
            raise ValueError("Traversal token expiry must follow acceptance")


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

    def __post_init__(self) -> None:
        if not (self.target_node_id and self.target_zone and self.target_episode_id):
            raise ValueError("Traversal target identifiers must be non-empty")
        require_utc(self.authorized_at, "Traversal authorization frontier")
        if not isinstance(self.authorized, bool) or not self.reason:
            raise ValueError("Traversal authorization result is invalid")


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

    def __post_init__(self) -> None:
        if not self.zone or self.profile_name not in PROFILE_NAMES:
            raise ValueError("Policy state zone and profile must be valid")
        if not isinstance(self.active, bool):
            raise ValueError("Policy active state must be boolean")
        require_utc(self.last_evaluated_at, "Policy evaluation time")
        if self.pending_release_since is not None:
            require_utc(self.pending_release_since, "Pending release time")
            if not self.active or self.pending_release_since > self.last_evaluated_at:
                raise ValueError("Pending release requires current active state")
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
            "health_degraded",
            "health_recovered",
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


@dataclass(frozen=True)
class ZoneModelResult:
    """One ordered target operation result without public side effects."""

    disposition: str
    snapshot: ZoneModelSnapshot
    policy_events: tuple[PolicyEvent, ...] = ()
    policy_decisions: tuple[PolicyDecision, ...] = ()
    authorizations: tuple[TraversalAuthorization, ...] = ()
