from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations

import pytest

from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
)
from custom_components.predictive_controls.inference.state_space import StateSpace
from custom_components.predictive_controls.inference.support import (
    _has_injective_support,
    _injective_support_matching,
    injective_support_probability,
    injective_support_result,
)
from custom_components.predictive_controls.inference.types import (
    AugmentedStateKey,
    MovementDisposition,
    SupportEventAtom,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def support(
    support_id: str,
    destination: str,
    *,
    endpoint_ids: tuple[str, ...] | None = None,
    episode_ids: tuple[str, ...] | None = None,
    disposition: MovementDisposition = "graph_valid",
) -> SupportEventAtom:
    return SupportEventAtom(
        support_id,
        disposition,
        "source",
        destination,
        ("source-node", f"{destination}-node"),
        endpoint_ids or (f"endpoint-{support_id}",),
        episode_ids or (f"episode-{support_id}",),
        NOW,
        NOW + timedelta(minutes=1),
        disposition == "graph_valid",
    )


def brute_force_match(
    configuration: tuple[int, ...],
    zones: tuple[str, ...],
    supports: Sequence[SupportEventAtom],
    predicate: Callable[[SupportEventAtom], bool],
) -> bool:
    slots = tuple(
        zone
        for zone, count in zip(zones, configuration, strict=True)
        for _ in range(count)
    )
    eligible = tuple(item for item in supports if predicate(item))
    if len(eligible) < len(slots):
        return False
    for assignment in permutations(eligible, len(slots)):
        if any(
            item.destination_zone != zone
            for item, zone in zip(assignment, slots, strict=True)
        ):
            continue
        if len({item.support_event_id for item in assignment}) != len(assignment):
            continue
        endpoints = tuple(
            endpoint_id for item in assignment for endpoint_id in item.endpoint_ids
        )
        episodes = tuple(
            episode_id for item in assignment for episode_id in item.episode_ids
        )
        if len(set(endpoints)) != len(endpoints):
            continue
        if len(set(episodes)) != len(episodes):
            continue
        return True
    return False


def direct_oracle(
    message: AugmentedLogMessage,
    origin: str,
    predicate: Callable[[SupportEventAtom], bool],
) -> float:
    origin_index = message.space.location_index(origin)
    return math.fsum(
        math.exp(log_mass)
        for key, log_mass in message.entries
        if (
            (configuration := message.space.unrank(key.occupancy_rank))[origin_index]
            == 0
            and configuration[message.space.unlocated_index] == 0
            and brute_force_match(
                configuration[: message.space.unlocated_index],
                message.space.zones,
                key.supports,
                predicate,
            )
        )
    )


def decimal_oracle(
    records: Sequence[
        tuple[tuple[int, ...], tuple[SupportEventAtom, ...], Decimal]
    ],
    zones: tuple[str, ...],
    origin: str,
    predicate: Callable[[SupportEventAtom], bool],
) -> Decimal:
    origin_index = zones.index(origin)
    total = sum((probability for _, _, probability in records), Decimal(0))
    selected = sum(
        (
            probability
            for configuration, supports, probability in records
            if configuration[origin_index] == 0
            and configuration[len(zones)] == 0
            and brute_force_match(
                configuration[: len(zones)],
                zones,
                supports,
                predicate,
            )
        ),
        Decimal(0),
    )
    return selected / total


def message_from_records(
    space: StateSpace,
    records: Sequence[
        tuple[tuple[int, ...], tuple[SupportEventAtom, ...], Decimal]
    ],
) -> AugmentedLogMessage:
    return AugmentedLogMessage(
        space,
        (
            (
                AugmentedStateKey(space.rank(configuration), supports=supports),
                math.log(float(probability)),
            )
            for configuration, supports, probability in records
        ),
    )


@pytest.mark.parametrize("occupants", range(6))
def test_injective_support_probability_covers_all_counts(occupants: int) -> None:
    space = StateSpace(("origin", "target"), occupants)
    matching = tuple(support(str(index), "target") for index in range(occupants))
    message = message_from_records(
        space,
        (((0, occupants, 0), matching, Decimal(1)),),
    )

    assert injective_support_probability(message, "origin", lambda _item: True) == 1.0


def test_injective_support_helpers_accept_empty_slot_set() -> None:
    assert _injective_support_matching((), ()) == ((), ())
    assert _has_injective_support((), ())


def test_injective_support_requires_distinct_resources_for_multiplicity() -> None:
    space = StateSpace(("origin", "target"), 2)
    first = support("first", "target")
    second = support("second", "target")
    duplicate_id = support("first", "target")
    duplicate_endpoint = support(
        "endpoint-copy",
        "target",
        endpoint_ids=first.endpoint_ids,
    )
    duplicate_episode = support(
        "episode-copy",
        "target",
        episode_ids=first.episode_ids,
    )

    for invalid in (
        (first,),
        (first, duplicate_id),
        (first, duplicate_endpoint),
        (first, duplicate_episode),
    ):
        message = message_from_records(
            space,
            (((0, 2, 0), invalid, Decimal(1)),),
        )
        assert injective_support_probability(
            message,
            "origin",
            lambda _item: True,
        ) == 0.0

    valid = message_from_records(
        space,
        (((0, 2, 0), (first, second), Decimal(1)),),
    )
    assert injective_support_probability(valid, "origin", lambda _item: True) == 1.0


def test_injective_support_result_explains_matching_and_rejections() -> None:
    space = StateSpace(("origin", "target"), 2)
    first = support("first", "target")
    second = support("second", "target")
    conflicting = support(
        "conflicting",
        "target",
        endpoint_ids=first.endpoint_ids,
    )
    message = message_from_records(
        space,
        (
            ((0, 2, 0), (first, second), Decimal("0.4")),
            ((1, 1, 0), (first,), Decimal("0.2")),
            ((0, 1, 1), (first,), Decimal("0.1")),
            ((0, 2, 0), (first, conflicting), Decimal("0.3")),
        ),
    )

    result = injective_support_result(message, "origin", lambda _item: True)

    assert result.probability == injective_support_probability(
        message,
        "origin",
        lambda _item: True,
    )
    assert result.probability == pytest.approx(0.4, abs=1e-12)
    qualifying = next(stratum for stratum in result.strata if stratum.qualifies)
    assert [slot.occurrence for slot in qualifying.matching] == [1, 2]
    assert [slot.support_event_id for slot in qualifying.matching] == [
        "first",
        "second",
    ]
    reasons = {
        reason
        for stratum in result.strata
        if not stratum.qualifies
        for reason in stratum.reasons
    }
    assert reasons == {
        "origin_nonempty",
        "unlocated_nonzero",
        "endpoint_conflict",
    }


def test_injective_support_result_reports_duplicate_support_event() -> None:
    space = StateSpace(("origin", "target"), 2)
    first = support("duplicate", "target")
    duplicate = support(
        "duplicate",
        "target",
        endpoint_ids=("other-endpoint",),
        episode_ids=("other-episode",),
    )
    message = message_from_records(
        space,
        (((0, 2, 0), (first, duplicate), Decimal(1)),),
    )

    result = injective_support_result(message, "origin", lambda _item: True)

    assert result.probability == 0.0
    assert result.strata[0].reasons == ("support_event_conflict",)


def test_injective_support_matches_every_destination_slot() -> None:
    space = StateSpace(("origin", "alpha", "beta"), 3)
    matching = (
        support("alpha", "alpha"),
        support("beta-1", "beta"),
        support("beta-2", "beta"),
    )
    mismatched = (*matching[:-1], support("alpha-extra", "alpha"))
    records = (
        ((0, 1, 2, 0), matching, Decimal("0.4")),
        ((0, 1, 2, 0), mismatched, Decimal("0.6")),
    )
    message = message_from_records(space, records)

    actual = injective_support_probability(message, "origin", lambda _item: True)

    assert actual == pytest.approx(0.4, abs=1e-12)
    assert actual == pytest.approx(
        direct_oracle(message, "origin", lambda _item: True),
        abs=1e-12,
    )


def test_injective_support_excludes_origin_unlocated_and_predicate_mass() -> None:
    space = StateSpace(("origin", "target"), 1)
    accepted = support("accepted", "target")
    rejected = support("rejected", "target", disposition="missed_movement")
    records = (
        ((0, 1, 0), (accepted,), Decimal("0.25")),
        ((1, 0, 0), (accepted,), Decimal("0.20")),
        ((0, 0, 1), (accepted,), Decimal("0.15")),
        ((0, 1, 0), (rejected,), Decimal("0.40")),
    )
    message = message_from_records(space, records)
    def graph_only(item: SupportEventAtom) -> bool:
        return item.disposition == "graph_valid"

    assert injective_support_probability(
        message,
        "origin",
        graph_only,
    ) == pytest.approx(0.25, abs=1e-12)
    assert injective_support_probability(
        message,
        "origin",
        lambda _item: False,
    ) == 0.0


def test_injective_support_matches_decimal_oracle_and_is_deterministic() -> None:
    space = StateSpace(("origin", "alpha", "beta"), 2)
    alpha = support("alpha", "alpha")
    beta = support("beta", "beta")
    beta_extra = support("beta-extra", "beta")
    records = (
        ((0, 1, 1, 0), (alpha, beta), Decimal("0.31")),
        ((0, 0, 2, 0), (beta, beta_extra), Decimal("0.23")),
        ((0, 2, 0, 0), (alpha,), Decimal("0.19")),
        ((1, 1, 0, 0), (alpha, beta), Decimal("0.17")),
        ((0, 1, 0, 1), (alpha, beta), Decimal("0.10")),
    )
    message = message_from_records(space, records)
    reversed_message = message_from_records(space, tuple(reversed(records)))
    expected = decimal_oracle(
        records,
        space.zones,
        "origin",
        lambda _item: True,
    )

    actual = injective_support_probability(message, "origin", lambda _item: True)

    assert actual == pytest.approx(float(expected), abs=1e-12)
    assert actual == injective_support_probability(
        reversed_message,
        "origin",
        lambda _item: True,
    )
    assert message.normalization == pytest.approx(1.0, abs=1e-12)


def test_injective_support_rejects_unknown_origin() -> None:
    space = StateSpace(("origin",), 0)
    message = message_from_records(space, (((0, 0), (), Decimal(1)),))

    with pytest.raises(KeyError):
        injective_support_probability(message, "missing", lambda _item: True)
