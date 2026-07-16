"""Replaceable internal inference engine protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..events import OccupancyEvent
from ..occupancy_state import PolicyDecision, PredictionLease, ZonePolicyState
from .policy import PosteriorPolicyAuditEntry


@dataclass(frozen=True)
class EngineDiagnostics:
    """Implementation-neutral values used by shadow differential replay."""

    expected_occupants: int
    occupied_marginals: Mapping[str, float]
    count_marginals: Mapping[str, tuple[float, ...]]
    normalization: float
    pruned_probability: float
    event_disposition: str | None
    updated_at: datetime | None
    episode_states: tuple[object, ...] = ()
    restore_rejection: str | None = None
    unresolved_assignment_count: int = 0
    factor_step_count: int = 0
    retained_input_count: int = 0
    consumed_endpoint_count: int = 0
    overloaded: bool = False
    arrival_supported_probabilities: Mapping[str, float] = field(
        default_factory=dict
    )
    release_safe_available: bool = False
    release_safe_probabilities: Mapping[str, float] = field(default_factory=dict)
    prediction_leases: tuple[PredictionLease, ...] = ()
    prediction_probabilities: Mapping[str, float] = field(default_factory=dict)
    route_transition_counts: Mapping[str, Mapping[str, float]] = field(
        default_factory=dict
    )
    route_statistics: Mapping[tuple[str, ...], Mapping[str, float]] = field(
        default_factory=dict
    )
    route_diagnostics: Mapping[str, object] = field(default_factory=dict)
    policy_states: Mapping[str, ZonePolicyState] = field(default_factory=dict)
    policy_decisions: tuple[PolicyDecision, ...] = ()
    most_likely_counts: Mapping[str, int] = field(default_factory=dict)
    policy_audit: tuple[PosteriorPolicyAuditEntry, ...] = ()


@runtime_checkable
class InferenceEngine(Protocol):
    """Internal engine boundary consumed by the stable tracker facade."""

    @property
    def diagnostics(self) -> EngineDiagnostics: ...

    def ensure(self, now: datetime) -> None: ...

    def observe(
        self,
        event: OccupancyEvent,
        *,
        emit_activation: bool,
    ) -> EngineDiagnostics: ...

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> EngineDiagnostics: ...

    def finalize(self, now: datetime) -> bool: ...

    def reconcile_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
        *,
        reconcile_policy: bool,
    ) -> EngineDiagnostics: ...

    def enter_unsupported_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
    ) -> EngineDiagnostics: ...

    def serialize(
        self,
        now: datetime,
        transition_counts: Mapping[str, Mapping[str, float]],
    ) -> object: ...

    def restore(self, restored: object) -> EngineDiagnostics: ...
