"""Test-only replay runner for legacy/replacement engine comparison."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.port import (
    EngineDiagnostics,
    InferenceEngine,
)

Projection = Callable[[InferenceEngine], Mapping[str, object]]


@dataclass(frozen=True)
class DifferentialMismatch:
    field: str
    legacy: object
    replacement: object
    requirement_id: str


@dataclass(frozen=True)
class DifferentialFrame:
    operation: str
    legacy: EngineDiagnostics
    replacement: EngineDiagnostics
    mismatches: tuple[DifferentialMismatch, ...]


class DifferentialRunner:
    """Feed identical controls to two engines and classify every difference."""

    def __init__(
        self,
        legacy: InferenceEngine,
        replacement: InferenceEngine,
        requirement_ids: Mapping[str, str],
        *,
        legacy_projection: Projection | None = None,
        replacement_projection: Projection | None = None,
    ) -> None:
        self.legacy = legacy
        self.replacement = replacement
        self._requirement_ids = requirement_ids
        self._legacy_projection = legacy_projection
        self._replacement_projection = replacement_projection

    def bootstrap(
        self,
        events: tuple[OccupancyEvent, ...],
        *,
        cold_start: bool,
    ) -> DifferentialFrame:
        self.legacy.bootstrap(events, cold_start=cold_start)
        self.replacement.bootstrap(events, cold_start=cold_start)
        return self._frame("bootstrap")

    def observe(self, event: OccupancyEvent) -> DifferentialFrame:
        self.legacy.observe(event, emit_activation=True)
        self.replacement.observe(event, emit_activation=True)
        return self._frame(f"observe:{event.entity_id}:{event.state}")

    def reconcile_count(
        self,
        expected_occupants: int,
        now: datetime,
        evidence_id: str,
    ) -> DifferentialFrame:
        self.legacy.reconcile_count(
            expected_occupants,
            now,
            evidence_id,
            reconcile_policy=True,
        )
        self.replacement.reconcile_count(
            expected_occupants,
            now,
            evidence_id,
            reconcile_policy=True,
        )
        return self._frame(f"count:{expected_occupants}")

    def finalize(self, now: datetime) -> DifferentialFrame:
        self.legacy.finalize(now)
        self.replacement.finalize(now)
        return self._frame("finalize")

    def compare_restart(self) -> DifferentialFrame:
        return self._frame("restart")

    def _frame(self, operation: str) -> DifferentialFrame:
        legacy = self.legacy.diagnostics
        replacement = self.replacement.diagnostics
        compared: dict[str, tuple[object, object]] = {
            "expected_occupants": (
                legacy.expected_occupants,
                replacement.expected_occupants,
            ),
            "occupied_marginals": (
                legacy.occupied_marginals,
                replacement.occupied_marginals,
            ),
            "count_marginals": (
                legacy.count_marginals,
                replacement.count_marginals,
            ),
            "normalization": (legacy.normalization, replacement.normalization),
            "pruned_probability": (
                legacy.pruned_probability,
                replacement.pruned_probability,
            ),
            "event_disposition": (
                legacy.event_disposition,
                replacement.event_disposition,
            ),
        }
        if self._legacy_projection is not None:
            if self._replacement_projection is None:
                raise ValueError("Both public projections must be configured")
            compared["public_timeline"] = (
                self._legacy_projection(self.legacy),
                self._replacement_projection(self.replacement),
            )
        mismatches = tuple(
            self._mismatch(operation, field, legacy_value, replacement_value)
            for field, (legacy_value, replacement_value) in compared.items()
            if not _equivalent(legacy_value, replacement_value)
        )
        return DifferentialFrame(operation, legacy, replacement, mismatches)

    def _mismatch(
        self,
        operation: str,
        field: str,
        legacy: object,
        replacement: object,
    ) -> DifferentialMismatch:
        requirement_id = self._requirement_ids.get(
            f"{operation}.{field}",
            self._requirement_ids.get(field),
        )
        if requirement_id is None:
            raise ValueError(
                f"Differential mismatch lacks requirement classification: {field}"
            )
        return DifferentialMismatch(field, legacy, replacement, requirement_id)


def _equivalent(left: object, right: object) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if left.keys() != right.keys():
            return False
        return all(_equivalent(left[key], right[key]) for key in left)
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _equivalent(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right

