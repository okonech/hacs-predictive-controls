"""Deterministic retained-input replay for bounded exact inference."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ..events import OccupancyEvent
from .types import require_utc

ReplayDisposition = Literal["accepted", "duplicate", "stale"]

_SCHEMA = "retained-replay-v1"
_MICROSECONDS_PER_DAY = 86_400_000_000


@dataclass(frozen=True)
class RetainedObservation:
    """One accepted raw input with its deterministic replay tie-breaker."""

    event: OccupancyEvent
    evidence_id: str
    receive_sequence: int

    def __post_init__(self) -> None:
        _validate_event(self.event)
        if not self.evidence_id:
            raise ValueError("Retained evidence ID must be non-empty")
        if self.receive_sequence <= 0:
            raise ValueError("Retained receive sequence must be positive")


class RetainedReplayCoordinator[BaseState, ReplayState]:
    """Own bounded raw inputs and replay them from an exact finalized base."""

    __slots__ = (
        "_checkpoint_prefix",
        "_checkpoint_result",
        "_consumed_endpoint_ids",
        "_finalized_base",
        "_replay_result",
        "_retained",
        "finalized_base_through",
        "latest_accepted_event_at",
        "max_lateness",
        "next_receive_sequence",
        "posterior_event_at",
        "watermark",
    )

    def __init__(
        self,
        max_lateness: timedelta,
        watermark: datetime,
        finalized_base_through: datetime,
        finalized_base: BaseState,
    ) -> None:
        if max_lateness < timedelta(0):
            raise ValueError("Maximum lateness must be non-negative")
        require_utc(watermark, "Initial replay watermark")
        require_utc(finalized_base_through, "Initial finalized-base frontier")
        if finalized_base_through > watermark:
            raise ValueError("Finalized-base frontier cannot exceed watermark")
        self.max_lateness = max_lateness
        self.watermark = watermark
        self.latest_accepted_event_at: datetime | None = None
        self.posterior_event_at: datetime | None = None
        self.finalized_base_through = finalized_base_through
        self.next_receive_sequence = 1
        self._finalized_base = finalized_base
        self._replay_result: ReplayState | None = None
        self._checkpoint_prefix: tuple[RetainedObservation, ...] = ()
        self._checkpoint_result: ReplayState | None = None
        self._retained: tuple[RetainedObservation, ...] = ()
        self._consumed_endpoint_ids: frozenset[str] = frozenset()

    @property
    def retained(self) -> tuple[RetainedObservation, ...]:
        return self._retained

    @property
    def finalized_base(self) -> BaseState:
        return self._finalized_base

    @property
    def replay_result(self) -> ReplayState | None:
        return self._replay_result

    @property
    def consumed_endpoint_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._consumed_endpoint_ids))

    def accept(
        self,
        event: OccupancyEvent,
        evidence_id: str,
        receive_at: datetime,
        endpoint_id: str | None = None,
    ) -> ReplayDisposition:
        _validate_event(event)
        if not evidence_id:
            raise ValueError("Evidence ID must be non-empty")
        require_utc(receive_at, "Observation receive time")
        proposed_watermark = max(
            self.watermark,
            receive_at - self.max_lateness,
        )
        if event.event_at <= proposed_watermark:
            self.watermark = proposed_watermark
            return "stale"
        if any(item.evidence_id == evidence_id for item in self._retained):
            self.watermark = proposed_watermark
            return "duplicate"
        if endpoint_id is not None:
            self.assert_endpoint_available(endpoint_id)

        retained = RetainedObservation(
            event,
            evidence_id,
            self.next_receive_sequence,
        )
        self._retained = tuple(sorted((*self._retained, retained), key=_record_key))
        self.watermark = proposed_watermark
        self.next_receive_sequence += 1
        self.latest_accepted_event_at = (
            event.event_at
            if self.latest_accepted_event_at is None
            else max(self.latest_accepted_event_at, event.event_at)
        )
        return "accepted"

    def advance_watermark(self, receive_at: datetime) -> bool:
        require_utc(receive_at, "Replay watermark receive time")
        next_watermark = max(
            self.watermark,
            receive_at - self.max_lateness,
        )
        if next_watermark == self.watermark:
            return False
        self.watermark = next_watermark
        return True

    def replay(
        self,
        reducer: Callable[
            [BaseState, tuple[RetainedObservation, ...]],
            ReplayState,
        ],
    ) -> ReplayState:
        """Run a deterministic, side-effect-free reducer and commit on success."""

        result = reducer(self._finalized_base, self._retained)
        posterior_event_at = max(
            (item.event.event_at for item in self._retained),
            default=self.finalized_base_through,
        )
        self._replay_result = result
        self._checkpoint_prefix = ()
        self._checkpoint_result = None
        self.posterior_event_at = posterior_event_at
        return result

    def replay_incremental(
        self,
        retained: tuple[RetainedObservation, ...],
        reducer: Callable[
            [ReplayState, tuple[RetainedObservation, ...]],
            ReplayState,
        ],
    ) -> ReplayState:
        if self._replay_result is None:
            raise ValueError("Incremental replay requires an existing result")
        if not retained or self._retained[-len(retained) :] != retained:
            raise ValueError("Incremental replay records must be a canonical suffix")
        previous_result = self._replay_result
        result = reducer(previous_result, retained)
        if len(retained) == 1:
            self._checkpoint_prefix = self._retained[:-1]
            self._checkpoint_result = previous_result
        else:
            self._checkpoint_prefix = ()
            self._checkpoint_result = None
        self._replay_result = result
        self.posterior_event_at = max(
            self.posterior_event_at or self.finalized_base_through,
            *(item.event.event_at for item in retained),
        )
        return result

    def replay_adjacent_insertion(
        self,
        accepted: RetainedObservation,
        reducer: Callable[
            [ReplayState, tuple[RetainedObservation, ...]],
            ReplayState,
        ],
    ) -> tuple[ReplayState, ReplayState] | None:
        if (
            self._checkpoint_result is None
            or len(self._retained) < 2
            or self._retained[-2] != accepted
            or self._checkpoint_prefix != self._retained[:-2]
        ):
            return None
        checkpoint = reducer(self._checkpoint_result, (accepted,))
        result = reducer(checkpoint, self._retained[-1:])
        self._checkpoint_prefix = self._retained[:-1]
        self._checkpoint_result = checkpoint
        self._replay_result = result
        self.posterior_event_at = max(
            self.posterior_event_at or self.finalized_base_through,
            accepted.event.event_at,
            self._retained[-1].event.event_at,
        )
        return result, checkpoint

    def replace_replay_result(self, result: ReplayState) -> None:
        if self._replay_result is None:
            raise ValueError("Cannot replace a missing replay result")
        self._replay_result = result

    def commit_finalized_base(
        self,
        finalized_base: BaseState,
        through: datetime,
        consumed_endpoint_ids: tuple[str, ...] = (),
        *,
        preserve_checkpoint: bool = False,
    ) -> None:
        require_utc(through, "Finalized-base commit frontier")
        if through < self.finalized_base_through:
            raise ValueError("Finalized-base frontier cannot move backward")
        if through > self.watermark:
            raise ValueError("Finalized-base frontier cannot exceed watermark")
        if self.posterior_event_at is not None and through > self.posterior_event_at:
            raise ValueError("Finalized-base frontier cannot exceed posterior time")
        if any(not endpoint_id for endpoint_id in consumed_endpoint_ids):
            raise ValueError("Consumed endpoint IDs must be non-empty")

        previous_retained = self._retained
        self._finalized_base = finalized_base
        self._retained = tuple(
            item for item in self._retained if item.event.event_at > through
        )
        if not preserve_checkpoint or self._retained != previous_retained:
            self._checkpoint_prefix = ()
            self._checkpoint_result = None
        self._consumed_endpoint_ids = self._consumed_endpoint_ids.union(
            consumed_endpoint_ids
        )
        self.finalized_base_through = through

    def endpoint_consumed(self, endpoint_id: str) -> bool:
        if not endpoint_id:
            raise ValueError("Endpoint ID must be non-empty")
        return endpoint_id in self._consumed_endpoint_ids

    def register_consumed_endpoints(self, endpoint_ids: tuple[str, ...]) -> None:
        if any(not endpoint_id for endpoint_id in endpoint_ids):
            raise ValueError("Consumed endpoint IDs must be non-empty")
        self._consumed_endpoint_ids = self._consumed_endpoint_ids.union(endpoint_ids)

    def assert_endpoint_available(self, endpoint_id: str) -> None:
        if self.endpoint_consumed(endpoint_id):
            raise ValueError("Endpoint token was already consumed")

    def serialize(
        self,
        encode_base: Callable[[BaseState], object],
        encode_result: Callable[[ReplayState], object],
    ) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "max_lateness_microseconds": _timedelta_microseconds(
                self.max_lateness
            ),
            "watermark": self.watermark.isoformat(),
            "latest_accepted_event_at": _datetime_payload(
                self.latest_accepted_event_at
            ),
            "posterior_event_at": _datetime_payload(self.posterior_event_at),
            "finalized_base_through": self.finalized_base_through.isoformat(),
            "next_receive_sequence": self.next_receive_sequence,
            "retained": [_serialize_record(item) for item in self._retained],
            "consumed_endpoint_ids": list(self.consumed_endpoint_ids),
            "finalized_base": encode_base(self._finalized_base),
            "replay_result": (
                None
                if self._replay_result is None
                else encode_result(self._replay_result)
            ),
        }

    def restore(
        self,
        payload: object,
        decode_base: Callable[[object], BaseState],
        decode_result: Callable[[object], ReplayState],
    ) -> None:
        restored = self._decode(payload, decode_base, decode_result)
        self.max_lateness = restored.max_lateness
        self.watermark = restored.watermark
        self.latest_accepted_event_at = restored.latest_accepted_event_at
        self.posterior_event_at = restored.posterior_event_at
        self.finalized_base_through = restored.finalized_base_through
        self.next_receive_sequence = restored.next_receive_sequence
        self._finalized_base = restored._finalized_base
        self._replay_result = restored._replay_result
        self._retained = restored._retained
        self._consumed_endpoint_ids = restored._consumed_endpoint_ids
        self._checkpoint_prefix = ()
        self._checkpoint_result = None

    @classmethod
    def _decode(
        cls,
        payload: object,
        decode_base: Callable[[object], BaseState],
        decode_result: Callable[[object], ReplayState],
    ) -> RetainedReplayCoordinator[BaseState, ReplayState]:
        if not isinstance(payload, Mapping):
            raise TypeError("Retained replay state must be a mapping")
        if payload.get("schema") != _SCHEMA:
            raise ValueError("Unsupported retained replay schema")
        raw_lateness = payload.get("max_lateness_microseconds")
        if (
            not isinstance(raw_lateness, int)
            or isinstance(raw_lateness, bool)
            or raw_lateness < 0
        ):
            raise ValueError("Stored maximum lateness is invalid")
        watermark = _restore_datetime(payload.get("watermark"), "watermark")
        base_through = _restore_datetime(
            payload.get("finalized_base_through"),
            "finalized-base frontier",
        )
        base = decode_base(payload.get("finalized_base"))
        restored = cls(
            timedelta(microseconds=raw_lateness),
            watermark,
            base_through,
            base,
        )
        latest = _restore_optional_datetime(
            payload.get("latest_accepted_event_at"),
            "latest accepted event time",
        )
        posterior = _restore_optional_datetime(
            payload.get("posterior_event_at"),
            "posterior event time",
        )
        if posterior is not None and posterior < base_through:
            raise ValueError("Stored posterior time precedes finalized base")

        raw_records = payload.get("retained")
        if not isinstance(raw_records, list):
            raise ValueError("Stored retained observations must be a list")
        records = tuple(_restore_record(item) for item in raw_records)
        if records != tuple(sorted(records, key=_record_key)):
            raise ValueError("Stored retained observations are not canonical")
        evidence_ids = tuple(item.evidence_id for item in records)
        sequences = tuple(item.receive_sequence for item in records)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Stored retained evidence IDs must be unique")
        if len(set(sequences)) != len(sequences):
            raise ValueError("Stored receive sequences must be unique")
        if any(item.event.event_at <= base_through for item in records):
            raise ValueError("Stored retained observation is behind finalized base")
        if records and (latest is None or latest < max(
            item.event.event_at for item in records
        )):
            raise ValueError("Stored latest accepted event time is invalid")

        next_sequence = payload.get("next_receive_sequence")
        if (
            not isinstance(next_sequence, int)
            or isinstance(next_sequence, bool)
            or next_sequence <= max(sequences, default=0)
        ):
            raise ValueError("Stored next receive sequence is invalid")
        raw_consumed = payload.get("consumed_endpoint_ids")
        if not isinstance(raw_consumed, list) or any(
            not isinstance(endpoint_id, str) or not endpoint_id
            for endpoint_id in raw_consumed
        ):
            raise ValueError("Stored consumed endpoint IDs are invalid")
        if raw_consumed != sorted(set(raw_consumed)):
            raise ValueError("Stored consumed endpoint IDs are not canonical")

        raw_result = payload.get("replay_result")
        result = None if raw_result is None else decode_result(raw_result)
        restored.latest_accepted_event_at = latest
        restored.posterior_event_at = posterior
        restored.next_receive_sequence = next_sequence
        restored._retained = records
        restored._consumed_endpoint_ids = frozenset(raw_consumed)
        restored._replay_result = result
        return restored


def _record_key(item: RetainedObservation) -> tuple[datetime, str, int]:
    return item.event.event_at, item.evidence_id, item.receive_sequence


def _validate_event(event: OccupancyEvent) -> None:
    require_utc(event.event_at, "Retained observation event time")
    if isinstance(event.reliability, bool) or not isinstance(
        event.reliability,
        int | float,
    ):
        raise ValueError("Observation reliability must be finite")
    if not math.isfinite(float(event.reliability)):
        raise ValueError("Observation reliability must be finite")


def _timedelta_microseconds(value: timedelta) -> int:
    return (
        value.days * _MICROSECONDS_PER_DAY
        + value.seconds * 1_000_000
        + value.microseconds
    )


def _datetime_payload(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _restore_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Stored {label} is invalid")
    try:
        restored = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Stored {label} is invalid") from exc
    require_utc(restored, f"Stored {label}")
    return restored


def _restore_optional_datetime(value: object, label: str) -> datetime | None:
    return None if value is None else _restore_datetime(value, label)


def _serialize_record(item: RetainedObservation) -> dict[str, object]:
    event = item.event
    return {
        "evidence_id": item.evidence_id,
        "receive_sequence": item.receive_sequence,
        "event": {
            "entity_id": event.entity_id,
            "node_id": event.node_id,
            "zone": event.zone,
            "floor": event.floor,
            "role": event.role,
            "occupancy_behavior": event.occupancy_behavior,
            "signal_type": event.signal_type,
            "state": event.state,
            "event_at": event.event_at.isoformat(),
            "reliability": event.reliability,
        },
    }


def _restore_record(payload: object) -> RetainedObservation:
    if not isinstance(payload, Mapping):
        raise ValueError("Stored retained observation must be a mapping")
    evidence_id = payload.get("evidence_id")
    sequence = payload.get("receive_sequence")
    raw_event = payload.get("event")
    if not isinstance(evidence_id, str) or not isinstance(raw_event, Mapping):
        raise ValueError("Stored retained observation is invalid")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise ValueError("Stored receive sequence is invalid")
    string_fields = {
        field: raw_event.get(field)
        for field in (
            "entity_id",
            "node_id",
            "zone",
            "role",
            "occupancy_behavior",
            "signal_type",
            "state",
        )
    }
    if any(not isinstance(value, str) for value in string_fields.values()):
        raise ValueError("Stored observation fields are invalid")
    floor = raw_event.get("floor")
    if floor is not None and not isinstance(floor, str):
        raise ValueError("Stored observation floor is invalid")
    reliability = raw_event.get("reliability")
    if (
        not isinstance(reliability, int | float)
        or isinstance(reliability, bool)
        or not math.isfinite(float(reliability))
    ):
        raise ValueError("Stored observation reliability is invalid")
    event = OccupancyEvent(
        entity_id=str(string_fields["entity_id"]),
        node_id=str(string_fields["node_id"]),
        zone=str(string_fields["zone"]),
        floor=floor,
        role=str(string_fields["role"]),
        occupancy_behavior=str(string_fields["occupancy_behavior"]),
        signal_type=str(string_fields["signal_type"]),
        state=str(string_fields["state"]),
        event_at=_restore_datetime(raw_event.get("event_at"), "event time"),
        reliability=float(reliability),
    )
    return RetainedObservation(event, evidence_id, sequence)
