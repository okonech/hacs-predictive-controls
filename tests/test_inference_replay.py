from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.replay import (
    RetainedObservation,
    RetainedReplayCoordinator,
)

NOW = datetime(2026, 7, 15, tzinfo=UTC)


def event(
    seconds: int | float,
    entity_id: str = "binary_sensor.office",
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id,
        "office",
        "office",
        "first_floor",
        "room_occupancy",
        "sustained",
        "motion",
        "on",
        NOW + timedelta(seconds=seconds),
        0.8,
    )


def coordinator() -> RetainedReplayCoordinator[tuple[str, ...], tuple[str, ...]]:
    return RetainedReplayCoordinator(
        timedelta(seconds=2),
        NOW,
        NOW,
        ("base",),
    )


def reduce_ids(
    base: tuple[str, ...],
    retained: tuple[RetainedObservation, ...],
) -> tuple[str, ...]:
    return (*base, *(item.evidence_id for item in retained))


def decode_strings(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list | tuple) or any(
        not isinstance(item, str) for item in payload
    ):
        raise ValueError("Expected a string sequence")
    return tuple(payload)


def populated_coordinator() -> RetainedReplayCoordinator[
    tuple[str, ...], tuple[str, ...]
]:
    replay = coordinator()
    replay.accept(event(3), "first", NOW + timedelta(seconds=3))
    replay.accept(
        event(4, "binary_sensor.hall"),
        "second",
        NOW + timedelta(seconds=4),
    )
    replay.replay(reduce_ids)
    replay.commit_finalized_base(("base",), NOW, ("used-endpoint",))
    return replay


def corrupt(payload: dict[str, object], key: str, value: object) -> dict[str, object]:
    changed = deepcopy(payload)
    changed[key] = value
    return changed


def corrupt_record(
    payload: dict[str, object],
    key: str,
    value: object,
    *,
    event_field: bool = False,
) -> dict[str, object]:
    changed = deepcopy(payload)
    retained = changed["retained"]
    assert isinstance(retained, list)
    record = retained[0]
    assert isinstance(record, dict)
    target: dict[str, Any]
    if event_field:
        event_payload = record["event"]
        assert isinstance(event_payload, dict)
        target = event_payload
    else:
        target = record
    target[key] = value
    return changed


def test_accept_uses_proposed_watermark_and_canonical_event_order() -> None:
    replay = coordinator()

    assert replay.accept(event(2), "equal", NOW + timedelta(seconds=4)) == "stale"
    assert replay.next_receive_sequence == 1
    assert replay.accept(
        replace(
            event(2, "binary_sensor.hall"),
            event_at=NOW + timedelta(seconds=2, microseconds=1),
        ),
        "plus-one",
        NOW + timedelta(seconds=3, microseconds=999_999),
    ) == "accepted"
    assert replay.accept(event(4), "later", NOW + timedelta(seconds=4)) == "accepted"
    assert replay.accept(event(3), "middle", NOW + timedelta(seconds=4)) == "accepted"

    assert tuple(item.evidence_id for item in replay.retained) == (
        "plus-one",
        "middle",
        "later",
    )
    assert replay.latest_accepted_event_at == NOW + timedelta(seconds=4)
    assert replay.replay(reduce_ids) == ("base", "plus-one", "middle", "later")
    assert replay.posterior_event_at == NOW + timedelta(seconds=4)


def test_duplicate_and_wall_clock_advance_do_not_replay_or_allocate() -> None:
    replay = coordinator()
    replay.accept(event(3), "endpoint", NOW + timedelta(seconds=3))
    before = replay.replay(reduce_ids)

    assert replay.accept(event(4), "endpoint", NOW + timedelta(seconds=4)) == (
        "duplicate"
    )
    assert replay.next_receive_sequence == 2
    assert replay.replay_result == before
    assert replay.advance_watermark(NOW + timedelta(seconds=5))
    assert not replay.advance_watermark(NOW + timedelta(seconds=4))
    assert replay.replay_result == before


def test_incremental_replay_accepts_only_canonical_suffix_atomically() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    replay.accept(event(2), "two", NOW + timedelta(seconds=2))
    latest = replay.retained[-1:]

    assert replay.replay_incremental(latest, reduce_ids) == ("base", "one", "two")

    multi = coordinator()
    multi.accept(event(1), "one", NOW + timedelta(seconds=1))
    multi.accept(event(2), "two", NOW + timedelta(seconds=2))
    multi.replay(reduce_ids)
    multi.accept(event(3), "three", NOW + timedelta(seconds=3))
    multi.accept(event(4), "four", NOW + timedelta(seconds=4))
    assert multi.replay_incremental(multi.retained[-2:], reduce_ids)[-2:] == (
        "three",
        "four",
    )

    replay.replace_replay_result(("replacement",))
    assert replay.replay_result == ("replacement",)
    with pytest.raises(ValueError, match="canonical suffix"):
        replay.replay_incremental(replay.retained[:1], reduce_ids)

    empty = coordinator()
    with pytest.raises(ValueError, match="existing result"):
        empty.replay_incremental(
            (RetainedObservation(event(1), "one", 1),),
            reduce_ids,
        )
    with pytest.raises(ValueError, match="missing replay result"):
        empty.replace_replay_result(())


def test_adjacent_insertion_replays_exact_suffix_and_updates_checkpoint() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    replay.accept(event(3), "three", NOW + timedelta(seconds=3))
    replay.replay_incremental(replay.retained[-1:], reduce_ids)
    replay.accept(event(2), "two", NOW + timedelta(seconds=3))
    accepted = next(item for item in replay.retained if item.evidence_id == "two")

    adjacent = replay.replay_adjacent_insertion(accepted, reduce_ids)

    assert adjacent == (
        ("base", "one", "two", "three"),
        ("base", "one", "two"),
    )
    assert replay.replay_result == reduce_ids(replay.finalized_base, replay.retained)

    replay.accept(event(4), "four", NOW + timedelta(seconds=4))
    assert replay.replay_incremental(replay.retained[-1:], reduce_ids) == (
        "base",
        "one",
        "two",
        "three",
        "four",
    )


def test_adjacent_checkpoint_falls_back_for_deeper_insertion() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    for seconds, evidence_id in ((3, "three"), (4, "four")):
        replay.accept(event(seconds), evidence_id, NOW + timedelta(seconds=seconds))
        replay.replay_incremental(replay.retained[-1:], reduce_ids)
    replay.accept(event(2.5), "two", NOW + timedelta(seconds=4))
    accepted = next(item for item in replay.retained if item.evidence_id == "two")

    assert replay.replay_adjacent_insertion(accepted, reduce_ids) is None
    assert replay.replay(reduce_ids) == (
        "base",
        "one",
        "two",
        "three",
        "four",
    )


def test_adjacent_reducer_failure_does_not_commit_partial_state() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    replay.accept(event(3), "three", NOW + timedelta(seconds=3))
    replay.replay_incremental(replay.retained[-1:], reduce_ids)
    replay.accept(event(2), "two", NOW + timedelta(seconds=3))
    accepted = next(item for item in replay.retained if item.evidence_id == "two")
    before = replay.replay_result

    def fail_on_tail(
        base: tuple[str, ...],
        retained: tuple[RetainedObservation, ...],
    ) -> tuple[str, ...]:
        if retained[0].evidence_id == "three":
            raise RuntimeError("tail failed")
        return reduce_ids(base, retained)

    with pytest.raises(RuntimeError, match="tail failed"):
        replay.replay_adjacent_insertion(accepted, fail_on_tail)
    assert replay.replay_result == before
    assert replay.replay_adjacent_insertion(accepted, reduce_ids) is not None


def test_checkpoint_compaction_and_restore_are_correctness_neutral() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    replay.accept(event(3), "three", NOW + timedelta(seconds=3))
    replay.replay_incremental(replay.retained[-1:], reduce_ids)

    replay.commit_finalized_base(
        replay.finalized_base,
        NOW,
        preserve_checkpoint=True,
    )
    replay.accept(event(2), "two", NOW + timedelta(seconds=3))
    accepted = next(item for item in replay.retained if item.evidence_id == "two")
    assert replay.replay_adjacent_insertion(accepted, reduce_ids) is not None

    payload = replay.serialize(tuple, tuple)
    restored = coordinator()
    restored.restore(payload, decode_strings, decode_strings)
    restored.accept(
        event(2, "binary_sensor.hall"),
        "other-two",
        NOW + timedelta(seconds=3),
    )
    restored_accepted = next(
        item for item in restored.retained if item.evidence_id == "other-two"
    )
    assert restored.replay_adjacent_insertion(restored_accepted, reduce_ids) is None
    assert restored.replay(reduce_ids) == reduce_ids(
        restored.finalized_base,
        restored.retained,
    )


def test_checkpoint_invalidates_when_compaction_removes_records() -> None:
    replay = coordinator()
    replay.accept(event(1), "one", NOW + timedelta(seconds=1))
    replay.replay(reduce_ids)
    replay.accept(event(3), "three", NOW + timedelta(seconds=3))
    replay.replay_incremental(replay.retained[-1:], reduce_ids)
    replay.advance_watermark(NOW + timedelta(seconds=4))
    replay.commit_finalized_base(
        ("base", "one"),
        NOW + timedelta(seconds=1),
        preserve_checkpoint=True,
    )
    replay.accept(event(2.5), "two", NOW + timedelta(seconds=4))
    accepted = next(item for item in replay.retained if item.evidence_id == "two")

    assert replay.replay_adjacent_insertion(accepted, reduce_ids) is None


def test_reducer_failure_and_commit_validation_are_atomic() -> None:
    replay = coordinator()
    replay.accept(event(3), "endpoint", NOW + timedelta(seconds=3))

    def fail(
        base: tuple[str, ...],
        retained: tuple[RetainedObservation, ...],
    ) -> tuple[str, ...]:
        del base, retained
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        replay.replay(fail)
    assert replay.replay_result is None
    assert replay.posterior_event_at is None

    replay.replay(reduce_ids)
    replay.advance_watermark(NOW + timedelta(seconds=7))
    before = replay.serialize(tuple, tuple)
    with pytest.raises(ValueError, match="posterior time"):
        replay.commit_finalized_base(
            ("invalid",),
            NOW + timedelta(seconds=4),
        )
    assert replay.serialize(tuple, tuple) == before

    replay.commit_finalized_base(("committed",), NOW, ("endpoint-token",))
    assert replay.endpoint_consumed("endpoint-token")
    with pytest.raises(ValueError, match="already consumed"):
        replay.assert_endpoint_available("endpoint-token")


def test_round_trip_retains_input_behind_later_watermark_and_endpoint_ids() -> None:
    replay = coordinator()
    replay.accept(event(3), "endpoint", NOW + timedelta(seconds=3))
    replay.replay(reduce_ids)
    replay.commit_finalized_base(("committed",), NOW, ("used-endpoint",))
    replay.advance_watermark(NOW + timedelta(seconds=6))
    payload = replay.serialize(tuple, tuple)

    restored = coordinator()
    restored.restore(payload, decode_strings, decode_strings)

    assert restored.serialize(tuple, tuple) == payload
    assert restored.retained[0].event.event_at < restored.watermark
    assert restored.endpoint_consumed("used-endpoint")
    assert restored.replay(reduce_ids) == ("committed", "endpoint")


def test_record_and_constructor_validation() -> None:
    with pytest.raises(ValueError, match="evidence ID"):
        RetainedObservation(event(1), "", 1)
    with pytest.raises(ValueError, match="positive"):
        RetainedObservation(event(1), "evidence", 0)
    with pytest.raises(ValueError, match="non-negative"):
        RetainedReplayCoordinator(timedelta(microseconds=-1), NOW, NOW, ())
    with pytest.raises(ValueError, match="frontier"):
        RetainedReplayCoordinator(
            timedelta(0),
            NOW,
            NOW + timedelta(microseconds=1),
            (),
        )
    with pytest.raises(ValueError, match="finite"):
        coordinator().accept(
            replace(event(1), reliability=float("nan")),
            "nan",
            NOW,
        )
    with pytest.raises(ValueError, match="finite"):
        coordinator().accept(
            replace(event(1), reliability=True),
            "boolean",
            NOW,
        )


def test_clock_endpoint_and_commit_boundaries() -> None:
    replay = coordinator()
    assert not replay.advance_watermark(replay.watermark)
    with pytest.raises(ValueError, match="Evidence ID"):
        replay.accept(event(1), "", NOW)
    with pytest.raises(ValueError, match="UTC"):
        replay.accept(event(1), "event", datetime(2026, 7, 15))
    with pytest.raises(ValueError, match="UTC"):
        replay.advance_watermark(datetime(2026, 7, 15))
    with pytest.raises(ValueError, match="Endpoint ID"):
        replay.endpoint_consumed("")
    assert not replay.endpoint_consumed("available")
    replay.assert_endpoint_available("available")
    replay.register_consumed_endpoints(("registered",))
    with pytest.raises(ValueError, match="already consumed"):
        replay.assert_endpoint_available("registered")
    with pytest.raises(ValueError, match="non-empty"):
        replay.register_consumed_endpoints(("",))

    replay.accept(event(3), "three", NOW + timedelta(seconds=3))
    replay.accept(event(4), "four", NOW + timedelta(seconds=4))
    replay.replay(reduce_ids)
    replay.advance_watermark(NOW + timedelta(seconds=7))

    before = replay.serialize(tuple, tuple)
    invalid_commits = (
        (NOW - timedelta(microseconds=1), (), "backward"),
        (NOW + timedelta(seconds=6), (), "watermark"),
        (NOW + timedelta(seconds=4, microseconds=1), (), "posterior"),
        (NOW, ("",), "non-empty"),
    )
    for through, endpoint_ids, message in invalid_commits:
        with pytest.raises(ValueError, match=message):
            replay.commit_finalized_base(("invalid",), through, endpoint_ids)
        assert replay.serialize(tuple, tuple) == before

    replay.commit_finalized_base(
        ("through-three",),
        NOW + timedelta(seconds=3),
        ("endpoint-3",),
    )
    assert replay.finalized_base == ("through-three",)
    assert tuple(item.evidence_id for item in replay.retained) == ("four",)
    assert replay.consumed_endpoint_ids == ("endpoint-3", "registered")


def test_empty_replay_and_permutation_determinism_for_all_counts() -> None:
    empty = coordinator()
    assert empty.replay(reduce_ids) == ("base",)
    assert empty.posterior_event_at == NOW

    events = (
        (event(3, "binary_sensor.c"), "c"),
        (event(3, "binary_sensor.a"), "a"),
        (event(3, "binary_sensor.b"), "b"),
    )
    expected: tuple[str, ...] | None = None
    for ordering in (
        events,
        tuple(reversed(events)),
        (events[1], events[2], events[0]),
    ):
        replay = coordinator()
        for observation, evidence_id in ordering:
            assert replay.accept(observation, evidence_id, NOW) == "accepted"
        result = replay.replay(reduce_ids)
        assert replay.replay(reduce_ids) == result
        if expected is None:
            expected = result
        assert result == expected

    for occupants in range(6):
        base: tuple[tuple[str, ...], ...] = (("same-zone",) * occupants,)
        count_replay: RetainedReplayCoordinator[
            tuple[tuple[str, ...], ...],
            tuple[tuple[tuple[str, ...], ...], tuple[str, ...]],
        ] = RetainedReplayCoordinator(
            timedelta(seconds=2),
            NOW,
            NOW,
            base,
        )
        count_replay.accept(event(1), f"count-{occupants}", NOW)
        assert count_replay.replay(
            lambda current, retained: (
                current,
                tuple(item.evidence_id for item in retained),
            )
        ) == (base, (f"count-{occupants}",))


def test_restore_rejects_corruption_atomically() -> None:
    source = populated_coordinator()
    valid = source.serialize(tuple, tuple)
    raw_retained = deepcopy(valid["retained"])
    assert isinstance(raw_retained, list)
    reversed_retained = list(reversed(raw_retained))
    duplicate_evidence = deepcopy(raw_retained)
    duplicate_sequence = deepcopy(raw_retained)
    assert isinstance(duplicate_evidence[1], dict)
    assert isinstance(duplicate_sequence[1], dict)
    duplicate_evidence[1]["evidence_id"] = "first"
    duplicate_sequence[1]["receive_sequence"] = 1

    corruptions: tuple[tuple[object, str], ...] = (
        ([], "mapping"),
        (corrupt(valid, "schema", "wrong"), "schema"),
        (corrupt(valid, "max_lateness_microseconds", True), "lateness"),
        (corrupt(valid, "max_lateness_microseconds", -1), "lateness"),
        (corrupt(valid, "watermark", 1), "watermark"),
        (corrupt(valid, "watermark", "not-a-time"), "watermark"),
        (corrupt(valid, "watermark", "2026-07-15T00:00:00"), "UTC"),
        (
            corrupt(
                valid,
                "finalized_base_through",
                (NOW + timedelta(seconds=3)).isoformat(),
            ),
            "frontier",
        ),
        (
            corrupt(
                valid,
                "posterior_event_at",
                (NOW - timedelta(microseconds=1)).isoformat(),
            ),
            "posterior",
        ),
        (corrupt(valid, "retained", {}), "observations"),
        (corrupt(valid, "retained", reversed_retained), "canonical"),
        (corrupt(valid, "retained", duplicate_evidence), "evidence IDs"),
        (corrupt(valid, "retained", duplicate_sequence), "sequences"),
        (
            corrupt_record(
                valid,
                "event_at",
                NOW.isoformat(),
                event_field=True,
            ),
            "behind finalized base",
        ),
        (corrupt(valid, "latest_accepted_event_at", None), "latest accepted"),
        (corrupt(valid, "next_receive_sequence", True), "next receive"),
        (corrupt(valid, "next_receive_sequence", 2), "next receive"),
        (corrupt(valid, "consumed_endpoint_ids", {}), "endpoint IDs"),
        (corrupt(valid, "consumed_endpoint_ids", [""]), "endpoint IDs"),
        (
            corrupt(valid, "consumed_endpoint_ids", ["z", "a"]),
            "canonical",
        ),
        (
            corrupt(valid, "consumed_endpoint_ids", ["used-endpoint"] * 2),
            "canonical",
        ),
        (corrupt(valid, "retained", [1]), "mapping"),
        (corrupt_record(valid, "evidence_id", 1), "invalid"),
        (corrupt_record(valid, "event", 1), "invalid"),
        (corrupt_record(valid, "receive_sequence", True), "sequence"),
        (corrupt_record(valid, "receive_sequence", 0), "positive"),
        (
            corrupt_record(valid, "entity_id", 1, event_field=True),
            "fields",
        ),
        (corrupt_record(valid, "floor", 1, event_field=True), "floor"),
        (
            corrupt_record(valid, "reliability", True, event_field=True),
            "reliability",
        ),
        (
            corrupt_record(valid, "reliability", float("inf"), event_field=True),
            "reliability",
        ),
        (
            corrupt_record(valid, "event_at", 1, event_field=True),
            "event time",
        ),
    )

    target = coordinator()
    target.accept(event(2), "target", NOW)
    before = target.serialize(tuple, tuple)
    for corrupted, message in corruptions:
        with pytest.raises((TypeError, ValueError), match=message):
            target.restore(corrupted, decode_strings, decode_strings)
        assert target.serialize(tuple, tuple) == before


def test_restore_codec_failures_and_extreme_utc_round_trip_are_atomic() -> None:
    source = populated_coordinator()
    valid = source.serialize(tuple, tuple)
    target = coordinator()
    before = target.serialize(tuple, tuple)

    def fail_decode(payload: object) -> tuple[str, ...]:
        del payload
        raise ValueError("codec failed")

    with pytest.raises(ValueError, match="codec failed"):
        target.restore(valid, fail_decode, decode_strings)
    assert target.serialize(tuple, tuple) == before
    with pytest.raises(ValueError, match="codec failed"):
        target.restore(valid, decode_strings, fail_decode)
    assert target.serialize(tuple, tuple) == before

    for origin in (
        datetime(1900, 1, 1, tzinfo=UTC),
        datetime(3000, 1, 1, tzinfo=UTC),
    ):
        extreme: RetainedReplayCoordinator[
            tuple[str, ...], tuple[str, ...]
        ] = RetainedReplayCoordinator(
            timedelta(microseconds=1),
            origin,
            origin,
            ("base",),
        )
        observation = replace(event(1), event_at=origin + timedelta(seconds=1))
        extreme.accept(observation, "extreme", origin)
        extreme.replay(reduce_ids)
        payload = extreme.serialize(tuple, tuple)
        restored = coordinator()
        restored.restore(payload, decode_strings, decode_strings)
        assert restored.serialize(tuple, tuple) == payload
