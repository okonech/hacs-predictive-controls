"""Disconnected shared-profile calibration grid and scoring tools."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, replace
from datetime import timedelta
from itertools import product

from .types import BeliefProfile, DecayCalibration


@dataclass(frozen=True)
class CalibrationCandidate:
    """One shared profile and policy calibration candidate."""

    candidate_id: str
    profile: BeliefProfile
    on_threshold: float
    off_threshold: float
    release_dwell: timedelta

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Calibration candidate ID must be non-empty")
        if not 0.0 < self.off_threshold < self.on_threshold < 1.0:
            raise ValueError("Calibration thresholds must satisfy 0 < off < on < 1")
        if self.release_dwell <= timedelta(0) or not math.isfinite(
            self.release_dwell.total_seconds()
        ):
            raise ValueError("Calibration release dwell must be finite and positive")


@dataclass(frozen=True)
class CalibrationTrace:
    """One retained trace's explicit Phase 3 calibration disposition."""

    trace_id: str
    disposition: str
    reason: str

    def __post_init__(self) -> None:
        if not self.trace_id or not self.reason:
            raise ValueError("Calibration trace identity and reason must be non-empty")
        if self.disposition not in {"deferred", "replay"}:
            raise ValueError("Calibration trace disposition must be deferred or replay")


@dataclass(frozen=True)
class CalibrationMetrics:
    """Raw public-outcome metrics for one candidate replay."""

    missed_activation_count: int = 0
    activation_latency_seconds: float = 0.0
    false_release_count: int = 0
    darkness_seconds: float = 0.0
    unsupported_activation_count: int = 0
    stale_active_seconds: float = 0.0
    edge_chatter_count: int = 0
    stuck_recovery_seconds: float = 0.0

    def __post_init__(self) -> None:
        values = tuple(getattr(self, field.name) for field in fields(self))
        if any(
            not isinstance(value, int | float) or not math.isfinite(value) or value < 0
            for value in values
        ):
            raise ValueError("Calibration metrics must be finite and non-negative")

    def __add__(self, other: CalibrationMetrics) -> CalibrationMetrics:
        return CalibrationMetrics(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )


@dataclass(frozen=True)
class CalibrationWeights:
    """Declared aggregate-score weights; raw metrics remain available."""

    missed_activation_count: float = 2.0
    activation_latency_seconds: float = 0.01
    false_release_count: float = 5.0
    darkness_seconds: float = 0.02
    unsupported_activation_count: float = 2.0
    stale_active_seconds: float = 0.005
    edge_chatter_count: float = 1.0
    stuck_recovery_seconds: float = 0.002

    def __post_init__(self) -> None:
        values = tuple(getattr(self, field.name) for field in fields(self))
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("Calibration weights must be finite and non-negative")
        if self.false_release_count <= self.missed_activation_count:
            raise ValueError(
                "Calibration false release weight must exceed missed activation"
            )


@dataclass(frozen=True)
class CandidateScore:
    candidate: CalibrationCandidate
    raw_metrics: CalibrationMetrics
    score: float


@dataclass(frozen=True)
class CalibrationReport:
    scores: tuple[CandidateScore, ...]

    @property
    def best(self) -> CandidateScore:
        return min(
            self.scores,
            key=lambda item: (item.score, item.candidate.candidate_id),
        )


def build_candidate_grid(
    profile_name: str,
    template: BeliefProfile,
    *,
    positive_likelihoods: Sequence[tuple[float, float]],
    clear_likelihoods: Sequence[tuple[float, float]],
    prior_probabilities: Sequence[float],
    asserted: Sequence[DecayCalibration],
    cleared_without_outward: Sequence[DecayCalibration],
    cleared_with_outward: Sequence[DecayCalibration],
    degraded_asserted: Sequence[DecayCalibration],
    unavailable: Sequence[DecayCalibration],
    thresholds: Sequence[tuple[float, float]],
    release_dwells: Sequence[timedelta],
) -> tuple[CalibrationCandidate, ...]:
    if profile_name != template.profile_id:
        raise ValueError("Calibration profile name must match the template")
    dimensions = (
        positive_likelihoods,
        clear_likelihoods,
        prior_probabilities,
        asserted,
        cleared_without_outward,
        cleared_with_outward,
        degraded_asserted,
        unavailable,
        thresholds,
        release_dwells,
    )
    if any(not dimension for dimension in dimensions):
        raise ValueError("Calibration grid dimensions must be non-empty")
    candidates: list[CalibrationCandidate] = []
    for index, values in enumerate(product(*dimensions)):
        (
            positive,
            clear,
            prior,
            asserted_value,
            clear_without,
            clear_with,
            degraded,
            unavailable_value,
            threshold,
            dwell,
        ) = values
        profile = replace(
            template,
            prior_probability=prior,
            positive_empty_likelihood=positive[0],
            positive_occupied_likelihood=positive[1],
            clear_empty_likelihood=clear[0],
            clear_occupied_likelihood=clear[1],
            asserted=asserted_value,
            cleared_without_outward=clear_without,
            cleared_with_outward=clear_with,
            degraded_asserted=degraded,
            unavailable=unavailable_value,
        )
        candidates.append(
            CalibrationCandidate(
                f"{profile_name}-{index:04d}",
                profile,
                threshold[0],
                threshold[1],
                dwell,
            )
        )
    return tuple(candidates)


def evaluate_candidates(
    candidates: Sequence[CalibrationCandidate],
    traces: Sequence[CalibrationTrace],
    replay: Callable[[CalibrationCandidate, CalibrationTrace], CalibrationMetrics],
    weights: CalibrationWeights | None = None,
) -> CalibrationReport:
    if not candidates:
        raise ValueError("At least one calibration candidate is required")
    replay_traces = tuple(trace for trace in traces if trace.disposition == "replay")
    if not replay_traces:
        raise ValueError("At least one calibration replay trace is required")
    effective_weights = CalibrationWeights() if weights is None else weights
    scores: list[CandidateScore] = []
    for candidate in candidates:
        metrics = CalibrationMetrics()
        for trace in replay_traces:
            metrics += replay(candidate, trace)
        score = math.fsum(
            getattr(metrics, field.name) * getattr(effective_weights, field.name)
            for field in fields(metrics)
        )
        scores.append(CandidateScore(candidate, metrics, score))
    return CalibrationReport(tuple(scores))
