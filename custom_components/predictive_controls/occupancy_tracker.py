from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from .events import OccupancyEvent
from .model import PredictiveMap
from .occupancy_dwell import DwellTimeModel
from .occupancy_graph import ZoneGraph
from .occupancy_scoring import (
    conflict_confidence,
    event_confidence,
    passive_confidence_for_duration,
    reason_for_conflict_decay,
    reason_for_event,
    reason_for_inactive_decay,
    reason_for_sustained_event,
    status_for_confidence,
    sustained_confidence_for_duration,
)


@dataclass(frozen=True)
class ZoneState:
    """Current inferred occupancy confidence for one zone."""

    zone: str
    confidence: float = 0.0
    status: str = "rejected"
    occupancy_behavior: str = "sustained"
    active_since: datetime | None = None
    last_evidence_at: datetime | None = None
    last_clear_at: datetime | None = None
    updated_at: datetime | None = None
    last_node_id: str | None = None
    reason: str = "no evidence"
    explanation: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ZoneUpdate:
    """Result of applying one occupancy inference update."""

    event: OccupancyEvent
    previous: ZoneState
    current: ZoneState


@dataclass(frozen=True)
class TrackerConfig:
    """Configuration for anonymous multi-occupant occupancy inference."""

    expected_occupants: int = 0
    corridor_radius: int = 1
    recent_evidence_window: timedelta = timedelta(minutes=15)

    @property
    def occupant_limit(self) -> int | None:
        return self.expected_occupants if self.expected_occupants > 0 else None


@dataclass(frozen=True)
class TrackCandidate:
    """One zone that may explain an anonymous occupant track."""

    zone: str
    score: float


@dataclass(frozen=True)
class AnonymousTrack:
    """One anonymous occupant explanation projected from zone evidence."""

    track_id: str
    zone: str
    confidence: float
    active: bool
    last_evidence_at: datetime | None
    source_entities: tuple[str, ...]


@dataclass(frozen=True)
class TrackerDiagnostics:
    """Structured diagnostics for panel and status payloads."""

    expected_occupants: int
    tracks: tuple[AnonymousTrack, ...]
    protected_tracks: tuple[str, ...]
    protected_corridor: tuple[str, ...]
    prediction_hints: dict[str, float]
    dwell_seconds: dict[str, dict[str, float | int]]


class OccupancyTracker:
    """Anonymous multi-occupant tracker over the configured zone graph."""

    def __init__(
        self,
        predictive_map: PredictiveMap,
        config: TrackerConfig | None = None,
    ) -> None:
        self.config = config or TrackerConfig()
        self._map = predictive_map
        self.graph = ZoneGraph.from_map(predictive_map)
        self.dwell = DwellTimeModel()
        self._states = {
            zone: ZoneState(
                zone=zone,
                occupancy_behavior=predictive_map.zone_occupancy_behavior(zone),
            )
            for zone in predictive_map.zones()
        }
        self._active_events: dict[str, dict[str, OccupancyEvent]] = {}
        self._recent_events: list[OccupancyEvent] = []
        self._tracks: tuple[AnonymousTrack, ...] = ()
        self._protected_tracks: tuple[str, ...] = ()
        self._protected_corridor: tuple[str, ...] = ()
        self._prediction_hints: dict[str, float] = {}

    @property
    def states(self) -> dict[str, ZoneState]:
        return self._states.copy()

    @property
    def recent_events(self) -> tuple[OccupancyEvent, ...]:
        return tuple(self._recent_events)

    @property
    def tracks(self) -> tuple[AnonymousTrack, ...]:
        return self._tracks

    @property
    def diagnostics(self) -> TrackerDiagnostics:
        return TrackerDiagnostics(
            expected_occupants=self.config.expected_occupants,
            tracks=self._tracks,
            protected_tracks=self._protected_tracks,
            protected_corridor=self._protected_corridor,
            prediction_hints=self._prediction_hints.copy(),
            dwell_seconds=self.dwell.payload(),
        )

    def state_for_zone(self, zone: str) -> ZoneState:
        return self._states.get(zone, ZoneState(zone=zone))

    def observe(self, event: OccupancyEvent) -> ZoneUpdate:
        previous = self.state_for_zone(event.zone)
        self._track_active_event(event)
        self._learn_dwell_if_clear_finished(previous, event)
        confidence = event_confidence(previous.confidence, event)
        current = replace(
            previous,
            confidence=confidence,
            status=status_for_confidence(confidence),
            occupancy_behavior=event.occupancy_behavior,
            active_since=self._active_since(event.zone),
            last_evidence_at=event.event_at
            if event.state == "on"
            else previous.last_evidence_at,
            last_clear_at=event.event_at
            if event.state == "off"
            else previous.last_clear_at,
            updated_at=event.event_at,
            last_node_id=event.node_id,
            reason=reason_for_event(event, confidence),
            explanation={
                "type": "event",
                "state": event.state,
                "signal_type": event.signal_type,
                "node_id": event.node_id,
                "active_signal_count": len(self._active_events.get(event.zone, {})),
            },
        )
        self._states[event.zone] = current
        self._recent_events = [*self._recent_events[-24:], event]
        if event.state == "on":
            self._reconcile_competing_zones(event)
        self._update_tracks(event)
        return ZoneUpdate(event=event, previous=previous, current=current)

    def apply_node_predictions(self, probabilities: Mapping[str, float]) -> None:
        """Project node-level next-step predictions into zone-level hints."""

        hints: dict[str, float] = {}
        for node_id, probability in probabilities.items():
            node = self._map.nodes.get(node_id)
            if node is None or probability <= 0:
                continue
            zone = node.occupancy_zone
            hints[zone] = max(hints.get(zone, 0.0), float(probability))
        self._prediction_hints = hints

    def refresh_active(self, now: datetime) -> tuple[ZoneUpdate, ...]:
        updates: list[ZoneUpdate] = []
        for zone, active_events in self._active_events.items():
            if not active_events:
                continue
            active_event = min(active_events.values(), key=lambda event: event.event_at)
            update = self._refresh_active_zone(zone, active_event, now)
            if update is not None:
                updates.append(update)

        for zone in self._states:
            if self._active_events.get(zone):
                continue
            update = self._decay_inactive_zone(zone, now)
            if update is not None:
                updates.append(update)
        return tuple(updates)

    def _refresh_active_zone(
        self, zone: str, active_event: OccupancyEvent, now: datetime
    ) -> ZoneUpdate | None:
        previous = self.state_for_zone(zone)
        confidence = sustained_confidence_for_duration(
            active_event,
            max(timedelta(0), now - active_event.event_at),
            previous.confidence,
        )
        if confidence <= previous.confidence:
            return None

        current = replace(
            previous,
            confidence=confidence,
            status=status_for_confidence(confidence),
            occupancy_behavior=active_event.occupancy_behavior,
            active_since=active_event.event_at,
            updated_at=now,
            last_node_id=active_event.node_id,
            reason=reason_for_sustained_event(active_event, confidence, now),
            explanation={
                "type": "sustained",
                "active_minutes": max(
                    0,
                    int((now - active_event.event_at).total_seconds() // 60),
                ),
                "active_signal_count": len(self._active_events.get(zone, {})),
            },
        )
        self._states[zone] = current
        return ZoneUpdate(active_event, previous, current)

    def _decay_inactive_zone(
        self, zone: str, now: datetime
    ) -> ZoneUpdate | None:
        previous = self.state_for_zone(zone)
        if previous.confidence <= 0:
            return None
        decay_from = (
            previous.updated_at
            or previous.last_clear_at
            or previous.last_evidence_at
        )
        if decay_from is None:
            return None

        elapsed = now - decay_from
        if elapsed <= timedelta(0):
            return None

        confidence = passive_confidence_for_duration(
            previous.occupancy_behavior,
            elapsed,
            previous.confidence,
            self.dwell.passive_half_life_seconds(
                previous.zone,
                previous.occupancy_behavior,
            ),
        )
        if confidence >= previous.confidence:
            return None

        current = replace(
            previous,
            confidence=confidence,
            status=status_for_confidence(confidence),
            updated_at=now,
            reason=reason_for_inactive_decay(previous, confidence, elapsed),
            explanation={
                "type": "passive_decay",
                "inactive_seconds": elapsed.total_seconds(),
                "dwell_average_seconds": self.dwell.average_seconds(previous.zone),
            },
        )
        self._states[zone] = current
        return ZoneUpdate(
            self._inference_event(previous, now),
            previous,
            current,
        )

    def _reconcile_competing_zones(self, event: OccupancyEvent) -> None:
        occupant_limit = self.config.occupant_limit
        if occupant_limit is None:
            return

        protected_tracks = self._protected_track_zones(event, occupant_limit)
        if len(protected_tracks) < occupant_limit:
            return

        protected_zones = self.graph.movement_corridor(
            protected_tracks,
            radius=self.config.corridor_radius,
        )
        self._protected_tracks = protected_tracks
        self._protected_corridor = tuple(sorted(protected_zones))
        for zone, previous in tuple(self._states.items()):
            if zone in protected_zones or self._active_events.get(zone):
                continue
            if previous.confidence < 0.05:
                continue
            confidence = conflict_confidence(previous.confidence)
            current = replace(
                previous,
                confidence=confidence,
                status=status_for_confidence(confidence),
                updated_at=event.event_at,
                reason=reason_for_conflict_decay(
                    previous, confidence, protected_tracks
                ),
                explanation={
                    "type": "conflict_decay",
                    "protected_tracks": list(protected_tracks),
                    "protected_corridor": sorted(protected_zones),
                    "trigger_zone": event.zone,
                    "active_signal_count": len(self._active_events.get(zone, {})),
                },
            )
            self._states[zone] = current

    def _protected_track_zones(
        self, event: OccupancyEvent, occupant_limit: int
    ) -> tuple[str, ...]:
        active_zones = {
            zone for zone, active_events in self._active_events.items() if active_events
        }
        candidates = [
            candidate
            for state in self._states.values()
            if state.confidence >= 0.05
            for candidate in self._track_candidates(state, event, active_zones)
        ]
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return tuple(candidate.zone for candidate in candidates[:occupant_limit])

    def _track_candidates(
        self,
        state: ZoneState,
        event: OccupancyEvent,
        active_zones: set[str],
    ) -> tuple[TrackCandidate, ...]:
        score = self._track_score(state, event, active_zones)
        slots = max(1, len(self._active_events.get(state.zone, {})))
        return tuple(TrackCandidate(zone=state.zone, score=score) for _ in range(slots))

    def _track_score(
        self,
        state: ZoneState,
        event: OccupancyEvent,
        active_zones: set[str],
    ) -> float:
        score = state.confidence
        score += self._prediction_hints.get(state.zone, 0.0) * 0.5
        if state.zone == event.zone:
            score += 3.0
        if state.zone in active_zones:
            score += 2.0
        elif state.last_evidence_at is not None:
            age = max(0.0, (event.event_at - state.last_evidence_at).total_seconds())
            if age <= self.config.recent_evidence_window.total_seconds():
                progress = age / self.config.recent_evidence_window.total_seconds()
                score += 1.0 - progress
        return score

    def _track_active_event(self, event: OccupancyEvent) -> None:
        zone_events = self._active_events.setdefault(event.zone, {})
        if event.state == "on":
            zone_events[event.entity_id] = event
        else:
            zone_events.pop(event.entity_id, None)

    def _learn_dwell_if_clear_finished(
        self, previous: ZoneState, event: OccupancyEvent
    ) -> None:
        if event.state != "off" or previous.active_since is None:
            return
        if self._active_events.get(event.zone):
            return
        self.dwell.learn(event.zone, event.event_at - previous.active_since)

    def _update_tracks(self, event: OccupancyEvent) -> None:
        occupant_limit = self.config.occupant_limit
        if occupant_limit is None:
            zones = tuple(
                state.zone
                for state in sorted(
                    self._states.values(),
                    key=lambda item: item.confidence,
                    reverse=True,
                )
                if state.confidence >= 0.05
            )
        else:
            zones = self._protected_track_zones(event, occupant_limit)
        self._tracks = tuple(
            self._track_from_zone(index + 1, zone)
            for index, zone in enumerate(zones)
        )

    def _track_from_zone(self, index: int, zone: str) -> AnonymousTrack:
        state = self.state_for_zone(zone)
        active_events = self._active_events.get(zone, {})
        return AnonymousTrack(
            track_id=f"track_{index}",
            zone=zone,
            confidence=state.confidence,
            active=bool(active_events),
            last_evidence_at=state.last_evidence_at,
            source_entities=tuple(sorted(active_events)),
        )

    def _active_since(self, zone: str) -> datetime | None:
        active_events = self._active_events.get(zone, {})
        if not active_events:
            return None
        return min(event.event_at for event in active_events.values())

    @staticmethod
    def _inference_event(previous: ZoneState, now: datetime) -> OccupancyEvent:
        return OccupancyEvent(
            entity_id="",
            node_id=previous.last_node_id or previous.zone,
            zone=previous.zone,
            floor=None,
            role="inference",
            occupancy_behavior=previous.occupancy_behavior,
            signal_type="time_decay",
            state="off",
            event_at=now,
            reliability=1.0,
        )
