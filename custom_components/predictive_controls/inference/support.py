"""Exact probability queries over finalized support-event strata."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .association import AugmentedLogMessage
from .types import SupportEventAtom

SupportRejectionReason = Literal[
    "origin_nonempty",
    "unlocated_nonzero",
    "insufficient_support",
    "destination_mismatch",
    "support_event_conflict",
    "endpoint_conflict",
    "episode_conflict",
]


@dataclass(frozen=True)
class SupportMatchingSlot:
    """One deterministic destination-slot to support-event assignment."""

    destination_zone: str
    occurrence: int
    support_event_id: str
    endpoint_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupportStratumResult:
    """Exact matching result for one augmented posterior stratum."""

    occupancy_rank: int
    probability: float
    qualifies: bool
    matching: tuple[SupportMatchingSlot, ...]
    reasons: tuple[SupportRejectionReason, ...]


@dataclass(frozen=True)
class InjectiveSupportResult:
    """Exact probability and deterministic per-stratum support evidence."""

    probability: float
    strata: tuple[SupportStratumResult, ...]


def injective_support_probability(
    message: AugmentedLogMessage,
    origin_zone: str,
    support_predicate: Callable[[SupportEventAtom], bool],
) -> float:
    """Sum exact mass with an empty origin and distinct support per occupant."""

    return injective_support_result(
        message,
        origin_zone,
        support_predicate,
    ).probability


def injective_support_result(
    message: AugmentedLogMessage,
    origin_zone: str,
    support_predicate: Callable[[SupportEventAtom], bool],
) -> InjectiveSupportResult:
    """Return exact mass with deterministic support witnesses and rejections."""

    origin_index = message.space.location_index(origin_zone)
    strata: list[SupportStratumResult] = []
    qualifying_masses: list[float] = []
    for key, log_mass in message.entries:
        configuration = message.space.unrank(key.occupancy_rank)
        slots = tuple(
            zone
            for zone, count in zip(
                message.space.zones,
                configuration[: message.space.unlocated_index],
                strict=True,
            )
            for _ in range(count)
        )
        eligible = tuple(
            support for support in key.supports if support_predicate(support)
        )
        reasons: list[SupportRejectionReason] = []
        if configuration[origin_index] > 0:
            reasons.append("origin_nonempty")
        if configuration[message.space.unlocated_index] > 0:
            reasons.append("unlocated_nonzero")
        matching: tuple[SupportEventAtom, ...] | None = None
        if not reasons:
            matching, matching_reasons = _injective_support_matching(
                slots,
                eligible,
            )
            reasons.extend(matching_reasons)
        qualifies = not reasons and matching is not None
        mass = math.exp(log_mass)
        if qualifies:
            qualifying_masses.append(mass)
        occurrences: dict[str, int] = {}
        rendered_matching: list[SupportMatchingSlot] = []
        if matching is not None:
            for slot, support in zip(slots, matching, strict=True):
                occurrences[slot] = occurrences.get(slot, 0) + 1
                rendered_matching.append(
                    SupportMatchingSlot(
                        slot,
                        occurrences[slot],
                        support.support_event_id,
                        support.endpoint_ids,
                        support.episode_ids,
                    )
                )
        strata.append(
            SupportStratumResult(
                key.occupancy_rank,
                mass,
                qualifies,
                tuple(rendered_matching),
                tuple(reasons),
            )
        )

    probability = math.fsum(qualifying_masses)
    if probability < -1e-12 or probability > 1.0 + 1e-12:
        raise ValueError("Injective support probability is out of range")
    return InjectiveSupportResult(
        min(1.0, max(0.0, probability)),
        tuple(strata),
    )


def _has_injective_support(
    slots: Sequence[str],
    supports: Sequence[SupportEventAtom],
) -> bool:
    matching, _reasons = _injective_support_matching(slots, supports)
    return matching is not None


def _injective_support_matching(
    slots: Sequence[str],
    supports: Sequence[SupportEventAtom],
) -> tuple[
    tuple[SupportEventAtom, ...] | None,
    tuple[SupportRejectionReason, ...],
]:
    if not slots:
        return (), ()
    if len(supports) < len(slots):
        return None, ("insufficient_support",)
    candidates = {
        zone: tuple(
            sorted(
                (
                    support
                    for support in supports
                    if support.destination_zone == zone
                ),
                key=lambda support: support.support_event_id,
            )
        )
        for zone in set(slots)
    }
    if any(len(candidates[zone]) < slots.count(zone) for zone in candidates):
        return None, ("destination_mismatch",)
    indexed_slots = tuple(enumerate(slots))
    ordered_slots = tuple(
        sorted(
            indexed_slots,
            key=lambda item: (len(candidates[item[1]]), item[1], item[0]),
        )
    )

    def search(
        slot_index: int,
        used_support_ids: frozenset[str],
        used_endpoint_ids: frozenset[str],
        used_episode_ids: frozenset[str],
        selected: tuple[tuple[int, SupportEventAtom], ...],
    ) -> tuple[tuple[int, SupportEventAtom], ...] | None:
        if slot_index == len(ordered_slots):
            return selected
        original_index, zone = ordered_slots[slot_index]
        for support in candidates[zone]:
            endpoint_ids = frozenset(support.endpoint_ids)
            episode_ids = frozenset(support.episode_ids)
            if (
                support.support_event_id in used_support_ids
                or not endpoint_ids.isdisjoint(used_endpoint_ids)
                or not episode_ids.isdisjoint(used_episode_ids)
            ):
                continue
            result = search(
                slot_index + 1,
                used_support_ids | {support.support_event_id},
                used_endpoint_ids | endpoint_ids,
                used_episode_ids | episode_ids,
                (*selected, (original_index, support)),
            )
            if result is not None:
                return result
        return None

    selected = search(0, frozenset(), frozenset(), frozenset(), ())
    if selected is not None:
        return tuple(support for _, support in sorted(selected)), ()
    support_ids = [support.support_event_id for support in supports]
    endpoint_ids = [
        endpoint_id for support in supports for endpoint_id in support.endpoint_ids
    ]
    episode_ids = [
        episode_id for support in supports for episode_id in support.episode_ids
    ]
    reasons: list[SupportRejectionReason] = []
    if len(set(support_ids)) != len(support_ids):
        reasons.append("support_event_conflict")
    if len(set(endpoint_ids)) != len(endpoint_ids):
        reasons.append("endpoint_conflict")
    if len(set(episode_ids)) != len(episode_ids):
        reasons.append("episode_conflict")
    return None, tuple(reasons)
