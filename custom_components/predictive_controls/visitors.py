from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from .events import OccupancyEvent

EXIT_GRACE_SECONDS = 30
MOTION_SIGNALS = frozenset({"motion", "pir", "mmwave", "presence", "occupancy"})


class VisitorsMode:
    def __init__(self, zones: tuple[str, ...]) -> None:
        self.enabled = False
        self.held_zones: set[str] = set()
        self.exit_at: datetime | None = None
        self._zones = frozenset(zones)
        self._started_at: datetime | None = None
        self._frontiers: dict[str, datetime] = {}

    def set_enabled(self, enabled: bool, now: datetime) -> None:
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self._frontiers.clear()
        self._started_at = now if enabled else None
        self.exit_at = (
            now + timedelta(seconds=EXIT_GRACE_SECONDS)
            if not enabled and self.held_zones else None
        )

    def sample(self, events: Iterable[OccupancyEvent], now: datetime) -> None:
        if not self.enabled:
            return
        self._started_at = now
        for event in events:
            self.observe(event, now)

    def observe(self, event: OccupancyEvent, processing_at: datetime) -> None:
        if (
            not self.enabled
            or event.signal_type not in MOTION_SIGNALS
            or event.entity_id.startswith("event.")
            or event.event_at > processing_at
            or self._started_at is None
            or event.event_at < self._started_at
            or event.event_at < self._frontiers.get(event.entity_id, event.event_at)
        ):
            return
        self._frontiers[event.entity_id] = event.event_at
        if event.state == "on":
            self.held_zones.add(event.zone)

    def retain_active(self, zones: Iterable[str]) -> bool:
        before = len(self.held_zones)
        if self.enabled:
            self.held_zones.update(zones)
        return len(self.held_zones) != before

    def expire(self, now: datetime) -> bool:
        if self.exit_at is None or now < self.exit_at:
            return False
        self.held_zones.clear()
        self.exit_at = None
        return True

    def store_data(self) -> dict[str, object]:
        return {
            "version": 1,
            "enabled": self.enabled,
            "held_zones": sorted(self.held_zones),
            "exit_at": None if self.exit_at is None else self.exit_at.isoformat(),
        }

    def restore(self, raw: object, now: datetime) -> bool:
        self.enabled = False
        self.held_zones.clear()
        self.exit_at = self._started_at = None
        self._frontiers.clear()
        if raw is None:
            return True
        if not isinstance(raw, dict):
            return False
        version = raw.get("version")
        enabled = raw.get("enabled")
        held = raw.get("held_zones")
        deadline = raw.get("exit_at")
        if (
            type(version) is not int or version != 1
            or not isinstance(enabled, bool)
            or not isinstance(held, list)
            or any(not isinstance(zone, str) or not zone for zone in held)
            or len(set(held)) != len(held)
        ):
            return False
        exit_at = None
        if deadline is not None:
            if not isinstance(deadline, str):
                return False
            try:
                exit_at = datetime.fromisoformat(deadline)
                if exit_at.tzinfo is None or exit_at.utcoffset() is None:
                    return False
                exit_at = exit_at.astimezone(UTC)
            except (ValueError, OverflowError):
                return False
        if (enabled and exit_at is not None) or (
            not enabled and bool(held) != (exit_at is not None)
        ):
            return False
        self.enabled = enabled
        self.held_zones = set(held) & self._zones
        self.exit_at = exit_at
        self._started_at = now if enabled else None
        self.expire(now)
        return True
