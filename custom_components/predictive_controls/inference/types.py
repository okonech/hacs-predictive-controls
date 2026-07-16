"""Immutable value types shared by exact inference modules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

type MovementDisposition = Literal[
    "stay",
    "graph_valid",
    "unlocated",
    "missed_movement",
    "censored_graph_path",
]
_MOVEMENT_DISPOSITIONS = frozenset(
    {
        "stay",
        "graph_valid",
        "unlocated",
        "missed_movement",
        "censored_graph_path",
    }
)


def require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must be timezone-aware UTC")


@dataclass(frozen=True)
class TemporalInterval:
    """Closed UTC interval for one temporal constraint variable."""

    variable: str
    earliest: datetime
    latest: datetime

    def __post_init__(self) -> None:
        if not self.variable:
            raise ValueError("Temporal interval variable must be non-empty")
        require_utc(self.earliest, "Temporal interval earliest time")
        require_utc(self.latest, "Temporal interval latest time")
        if self.earliest > self.latest:
            raise ValueError("Temporal interval earliest time must not exceed latest")


@dataclass(frozen=True)
class DifferenceConstraint:
    """Upper bound on minuend time minus subtrahend time."""

    minuend: str
    subtrahend: str
    maximum: timedelta

    def __post_init__(self) -> None:
        if not self.minuend or not self.subtrahend:
            raise ValueError("Difference constraint variables must be non-empty")


@dataclass(frozen=True)
class RouteEpisodeInterval:
    """Finite event-time validity for one route-participating episode."""

    node_id: str
    zone: str
    episode_id: str
    valid_from: datetime
    valid_until: datetime
    evidence_ids: tuple[str, ...]
    current_positive: bool = False
    endpoint_blocked_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.node_id or not self.zone or not self.episode_id:
            raise ValueError("Route episode node, zone, and episode IDs are required")
        require_utc(self.valid_from, "Route episode validity start")
        require_utc(self.valid_until, "Route episode validity end")
        if self.valid_from > self.valid_until:
            raise ValueError("Route episode validity start must not exceed end")
        if any(not evidence_id for evidence_id in self.evidence_ids):
            raise ValueError("Route episode evidence IDs must be non-empty")
        if self.endpoint_blocked_until is not None:
            require_utc(
                self.endpoint_blocked_until,
                "Route episode endpoint block end",
            )
            if self.endpoint_blocked_until < self.valid_from:
                raise ValueError("Route episode endpoint block cannot precede start")


@dataclass(frozen=True)
class EndpointAlternative:
    """One declared categorical explanation for a positive endpoint."""

    alternative_id: str
    disposition: MovementDisposition
    source_index: int | None
    source_node_id: str | None
    route_nodes: tuple[str, ...]
    log_weight: float
    deadline: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.alternative_id:
            raise ValueError("Endpoint alternative ID must be non-empty")
        if self.disposition not in _MOVEMENT_DISPOSITIONS:
            raise ValueError("Endpoint alternative disposition is invalid")
        if self.disposition == "stay":
            if self.source_index is not None or self.source_node_id is not None:
                raise ValueError("Stay alternative must not declare a source")
        elif (
            self.source_index is None
            or self.source_index < 0
            or not self.source_node_id
        ):
            raise ValueError("Movement alternative requires a valid source")
        if math.isnan(self.log_weight) or self.log_weight == math.inf:
            raise ValueError(
                "Endpoint alternative log weight must be finite or negative infinity"
            )
        require_utc(self.deadline, "Endpoint alternative deadline")
        if any(not node_id for node_id in self.route_nodes):
            raise ValueError("Endpoint alternative route nodes must be non-empty")
        if any(not evidence_id for evidence_id in self.evidence_ids):
            raise ValueError("Endpoint alternative evidence IDs must be non-empty")


@dataclass(frozen=True)
class EndpointAssignmentAtom:
    """Probability-bearing endpoint ownership retained in augmented state."""

    endpoint_id: str
    alternative_id: str
    disposition: MovementDisposition
    predecessor_rank: int
    successor_rank: int
    source_index: int | None
    target_index: int
    source_node_id: str | None
    target_node_id: str
    route_nodes: tuple[str, ...]
    deadline: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.endpoint_id or not self.alternative_id:
            raise ValueError(
                "Assignment endpoint and alternative IDs must be non-empty"
            )
        if self.disposition not in _MOVEMENT_DISPOSITIONS:
            raise ValueError("Assignment disposition is invalid")
        if min(self.predecessor_rank, self.successor_rank, self.target_index) < 0:
            raise ValueError("Assignment state and target indexes must be non-negative")
        if self.disposition == "stay":
            if self.source_index is not None or self.source_node_id is not None:
                raise ValueError("Stay assignment must not declare a source")
        elif (
            self.source_index is None
            or self.source_index < 0
            or not self.source_node_id
        ):
            raise ValueError("Movement assignment requires a valid source")
        if not self.target_node_id:
            raise ValueError("Assignment target node ID must be non-empty")
        require_utc(self.deadline, "Assignment deadline")


@dataclass(frozen=True)
class SupportEventAtom:
    """Finite probability-bearing support event retained after assignment."""

    support_event_id: str
    disposition: MovementDisposition
    origin_zone: str
    destination_zone: str
    route_nodes: tuple[str, ...]
    endpoint_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    learning_eligible: bool

    def __post_init__(self) -> None:
        if (
            not self.support_event_id
            or not self.origin_zone
            or not self.destination_zone
        ):
            raise ValueError("Support event and zone IDs must be non-empty")
        if self.disposition not in _MOVEMENT_DISPOSITIONS:
            raise ValueError("Support event disposition is invalid")
        if any(not endpoint_id for endpoint_id in self.endpoint_ids):
            raise ValueError("Support endpoint IDs must be non-empty")
        require_utc(self.valid_from, "Support validity start")
        require_utc(self.valid_until, "Support validity end")
        if self.valid_from > self.valid_until:
            raise ValueError("Support validity start must not exceed end")


@dataclass(frozen=True)
class AssignmentIdentity:
    """Complete identity of one categorical endpoint assignment branch."""

    endpoint_id: str
    alternative_id: str
    predecessor_rank: int
    successor_rank: int

    def __post_init__(self) -> None:
        if not self.endpoint_id or not self.alternative_id:
            raise ValueError("Assignment identity IDs must be non-empty")
        if self.predecessor_rank < 0 or self.successor_rank < 0:
            raise ValueError("Assignment identity ranks must be non-negative")


@dataclass(frozen=True)
class FinalizationSupport:
    """Optional bounded support retained for one finalized assignment."""

    identity: AssignmentIdentity
    support: SupportEventAtom | None


@dataclass(frozen=True)
class AugmentedStateKey:
    """One occupancy configuration and its exact latent support context."""

    occupancy_rank: int
    contexts: tuple[EndpointAssignmentAtom, ...] = ()
    supports: tuple[SupportEventAtom, ...] = ()

    def __post_init__(self) -> None:
        if self.occupancy_rank < 0:
            raise ValueError("Augmented occupancy rank must be non-negative")


def assignment_atom_sort_key(atom: EndpointAssignmentAtom) -> tuple[object, ...]:
    return (
        atom.endpoint_id,
        atom.alternative_id,
        atom.predecessor_rank,
        atom.successor_rank,
        -1 if atom.source_index is None else atom.source_index,
        atom.target_index,
        atom.disposition,
        atom.deadline,
    )


def support_atom_sort_key(atom: SupportEventAtom) -> tuple[object, ...]:
    return (
        atom.support_event_id,
        atom.disposition,
        atom.origin_zone,
        atom.destination_zone,
        atom.valid_from,
        atom.valid_until,
    )


@dataclass(frozen=True)
class EndpointToken:
    """One externally observed endpoint that can support one crossing."""

    token_id: str
    node_id: str
    event_at: datetime

    def __post_init__(self) -> None:
        if not self.token_id or not self.node_id:
            raise ValueError("Endpoint token and node IDs must be non-empty")
        require_utc(self.event_at, "Endpoint event time")


@dataclass(frozen=True)
class AssignmentAlternative:
    """One mutually exclusive anonymous source-to-target explanation."""

    source_index: int
    target_index: int
    weight: float

    def __post_init__(self) -> None:
        if self.source_index == self.target_index:
            raise ValueError("Assignment source and target must differ")
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise ValueError("Assignment weight must be finite and non-negative")


@dataclass(frozen=True)
class UnresolvedAssignment:
    """Finite-lag alternatives for one unconsumed external endpoint."""

    candidate_id: str
    endpoint: EndpointToken
    alternatives: tuple[AssignmentAlternative, ...]
    stay_weight: float
    deadline: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Assignment candidate ID must be non-empty")
        if not self.alternatives:
            raise ValueError("Assignment requires at least one movement alternative")
        if not math.isfinite(self.stay_weight) or self.stay_weight < 0.0:
            raise ValueError("Assignment stay weight must be finite and non-negative")
        require_utc(self.deadline, "Assignment deadline")
        if self.deadline < self.endpoint.event_at:
            raise ValueError("Assignment deadline cannot precede its endpoint")


@dataclass(frozen=True)
class FinalizedAssignmentCertificate:
    """Bounded support record retained after exact assignment marginalization."""

    candidate_id: str
    endpoint_id: str
    deadline: datetime
    alternatives: tuple[AssignmentAlternative, ...]
    evidence_ids: tuple[str, ...]
