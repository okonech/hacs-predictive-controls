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
    reason_for_clear_transition_decay,
    reason_for_conflict_decay,
    reason_for_departure_decay,
    reason_for_event,
    reason_for_inactive_decay,
    reason_for_sustained_event,
    status_for_confidence,
    sustained_confidence_for_duration,
)

NON_ADJACENT_EVENT_CONFIDENCE_CAP = 0.34


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
    join_transition_window: timedelta = timedelta(minutes=3)
    join_slot_retention: timedelta = timedelta(minutes=5)
    join_destination_min_confidence: float = 0.35
    departure_transition_window: timedelta = timedelta(minutes=3)
    departure_retention: timedelta = timedelta(minutes=5)
    departure_source_min_confidence: float = 0.35
    entry_plausibility_window: timedelta = timedelta(seconds=30)

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
class InferredJoinSlot:
    """Temporary extra occupant slot for someone joining an occupied zone."""

    zone: str
    source_zone: str
    source_node_id: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class InferredDeparture:
    """Temporary record that a person likely left one zone for another."""

    zone: str
    via_zone: str
    via_node_id: str
    destination_zone: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class EntryPlausibility:
    """Short-lived evidence that adjacent entry into one zone is plausible."""

    zone: str
    source_zone: str
    source_node_id: str
    event_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TrackerDiagnostics:
    """Structured diagnostics for panel and status payloads."""

    expected_occupants: int
    tracks: tuple[AnonymousTrack, ...]
    protected_tracks: tuple[str, ...]
    protected_corridor: tuple[str, ...]
    inferred_join_slots: tuple[InferredJoinSlot, ...]
    inferred_departures: tuple[InferredDeparture, ...]
    prediction_hints: dict[str, float]
    dwell_seconds: dict[str, dict[str, float | int]]
    entry_plausibilities: tuple[EntryPlausibility, ...] = ()


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
        self._join_slots: dict[str, InferredJoinSlot] = {}
        self._departures: dict[str, InferredDeparture] = {}
        self._entry_plausibilities: dict[str, EntryPlausibility] = {}
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
            inferred_join_slots=tuple(self._join_slots.values()),
            inferred_departures=tuple(self._departures.values()),
            prediction_hints=self._prediction_hints.copy(),
            dwell_seconds=self.dwell.payload(),
            entry_plausibilities=tuple(
                self._entry_plausibilities[zone]
                for zone in sorted(self._entry_plausibilities)
            ),
        )

    def state_for_zone(self, zone: str) -> ZoneState:
        return self._states.get(zone, ZoneState(zone=zone))

    def observe(self, event: OccupancyEvent) -> ZoneUpdate:
        previous = self.state_for_zone(event.zone)
        self._expire_inferences(event.event_at)
        self._track_active_event(event)
        self._learn_dwell_if_clear_finished(previous, event)
        join_slot = self._infer_join_slot(previous, event)
        if join_slot is not None:
            self._join_slots[event.zone] = join_slot
        confidence = event_confidence(previous.confidence, event)
        reason = reason_for_event(event, confidence)
        explanation: dict[str, Any] = {
            "type": "event",
            "state": event.state,
            "signal_type": event.signal_type,
            "node_id": event.node_id,
            "active_signal_count": len(self._active_events.get(event.zone, {})),
        }
        clear_departure = self._infer_clear_transition_departure(
            previous,
            event,
            confidence,
        )
        if clear_departure is not None:
            confidence = min(confidence, conflict_confidence(previous.confidence))
            reason = reason_for_clear_transition_decay(
                previous,
                confidence,
                clear_departure.via_zone,
                clear_departure.destination_zone,
            )
            explanation = {
                "type": "clear_transition_decay",
                "departure": departure_payload(clear_departure),
                "trigger_zone": event.zone,
                "active_signal_count": len(self._active_events.get(event.zone, {})),
            }
        nonadjacent_tracks = self._nonadjacent_saturated_track_zones(event)
        if nonadjacent_tracks:
            confidence = min(confidence, NON_ADJACENT_EVENT_CONFIDENCE_CAP)
            track_list = ", ".join(nonadjacent_tracks)
            reason = (
                f"{reason}; non-adjacent to active track(s) "
                f"({track_list}); capped as suspect"
            )
            explanation["nonadjacent_saturated_tracks"] = list(nonadjacent_tracks)
        elif event.state == "on":
            self._mark_entry_plausibilities(event)
        if join_slot is not None:
            reason = (
                f"{reason}; inferred additional occupant from "
                f"{join_slot.source_zone}"
            )
            explanation["join_transition"] = join_slot_payload(join_slot)
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
            reason=reason,
            explanation=explanation,
        )
        self._states[event.zone] = current
        if clear_departure is not None:
            self._departures[event.zone] = clear_departure
        self._recent_events = [*self._recent_events[-24:], event]
        if event.state == "on":
            self._apply_departures(event)
            self._reconcile_competing_zones(event)
        self._update_tracks(event)
        return ZoneUpdate(event=event, previous=previous, current=current)

    def apply_node_predictions(
        self,
        probabilities: Mapping[str, float],
        source_node_id: str | None = None,
    ) -> None:
        """Project node-level next-step predictions into zone-level hints."""

        source_zone = self._zone_for_node(source_node_id)
        allowed_zones = self._allowed_prediction_zones(source_zone)
        hints: dict[str, float] = {}
        for node_id, probability in probabilities.items():
            node = self._map.nodes.get(node_id)
            if node is None or probability <= 0:
                continue
            zone = node.occupancy_zone
            if allowed_zones is not None and zone not in allowed_zones:
                continue
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

    def expire_transient_state(self, now: datetime) -> bool:
        """Expire short-lived automation hints without changing zone confidence."""

        return self._expire_inferences(now)

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
        if self._join_slots.get(state.zone) is not None:
            slots += 1
        return tuple(TrackCandidate(zone=state.zone, score=score) for _ in range(slots))

    def _track_score(
        self,
        state: ZoneState,
        event: OccupancyEvent,
        active_zones: set[str],
    ) -> float:
        if state.zone == event.zone and self._nonadjacent_saturated_track_zones(event):
            return min(state.confidence, NON_ADJACENT_EVENT_CONFIDENCE_CAP)

        score = state.confidence
        score += self._prediction_hints.get(state.zone, 0.0) * 0.5
        if event.state == "on" and state.zone == event.zone:
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

    def _infer_join_slot(
        self, previous: ZoneState, event: OccupancyEvent
    ) -> InferredJoinSlot | None:
        if event.state != "on":
            return None
        if event.occupancy_behavior == "transient" or event.role == "transition_gate":
            return None
        if previous.confidence < self.config.join_destination_min_confidence:
            return None
        if previous.last_evidence_at is None:
            return None

        source = self._recent_adjacent_transition(
            event,
            self.config.join_transition_window,
        )
        if source is None:
            return None
        return InferredJoinSlot(
            zone=event.zone,
            source_zone=source.zone,
            source_node_id=source.node_id,
            event_at=event.event_at,
            expires_at=event.event_at + self.config.join_slot_retention,
        )

    def _recent_adjacent_transition(
        self, event: OccupancyEvent, default_window: timedelta
    ) -> OccupancyEvent | None:
        for recent in reversed(self._recent_events):
            elapsed = event.event_at - recent.event_at
            if elapsed < timedelta(0):
                continue
            if elapsed > self._transition_window_for_events(
                recent,
                event,
                default_window,
            ):
                break
            if recent.zone == event.zone:
                continue
            if (
                recent.occupancy_behavior != "transient"
                and recent.role != "transition_gate"
            ):
                continue
            if self.graph.distance(recent.zone, event.zone, max_depth=1) is None:
                continue
            return recent
        return None

    def _apply_departures(self, event: OccupancyEvent) -> None:
        for departure in self._infer_departures(event):
            previous = self.state_for_zone(departure.zone)
            confidence = conflict_confidence(previous.confidence)
            current = replace(
                previous,
                confidence=confidence,
                status=status_for_confidence(confidence),
                updated_at=event.event_at,
                reason=reason_for_departure_decay(
                    previous,
                    confidence,
                    departure.via_zone,
                    departure.destination_zone,
                ),
                explanation={
                    "type": "departure_decay",
                    "departure": departure_payload(departure),
                    "trigger_zone": event.zone,
                },
            )
            self._states[departure.zone] = current
            self._departures[departure.zone] = departure

    def _infer_departures(
        self, event: OccupancyEvent
    ) -> tuple[InferredDeparture, ...]:
        if event.state != "on":
            return ()
        if event.occupancy_behavior == "transient" or event.role == "transition_gate":
            return ()

        transition = self._recent_adjacent_transition(
            event,
            self.config.departure_transition_window,
        )
        if transition is None:
            return ()

        candidates: list[tuple[float, ZoneState]] = []
        for zone in self.graph.neighbors(transition.zone):
            if zone == event.zone or self._active_events.get(zone):
                continue
            state = self.state_for_zone(zone)
            if state.confidence < self.config.departure_source_min_confidence:
                continue
            if state.last_evidence_at is None:
                continue
            age = event.event_at - state.last_evidence_at
            if age < timedelta(0):
                continue
            if age > self.config.recent_evidence_window:
                continue
            recency = 1.0 - age / self.config.recent_evidence_window
            candidates.append((state.confidence + recency, state))

        if not candidates:
            return ()
        _, source = max(candidates, key=lambda item: item[0])
        return (
            InferredDeparture(
                zone=source.zone,
                via_zone=transition.zone,
                via_node_id=transition.node_id,
                destination_zone=event.zone,
                event_at=event.event_at,
                expires_at=event.event_at + self.config.departure_retention,
            ),
        )

    def _infer_clear_transition_departure(
        self,
        previous: ZoneState,
        event: OccupancyEvent,
        cleared_confidence: float,
    ) -> InferredDeparture | None:
        if event.state != "off":
            return None
        if self._active_events.get(event.zone):
            return None
        if previous.confidence < self.config.departure_source_min_confidence:
            return None
        if previous.last_evidence_at is None:
            return None

        transition = self._recent_adjacent_transition(
            event,
            self.config.departure_transition_window,
        )
        if transition is None:
            return None

        candidates: list[tuple[float, ZoneState]] = []
        for zone in self.graph.neighbors(transition.zone):
            if zone == event.zone or not self._active_events.get(zone):
                continue
            state = self.state_for_zone(zone)
            if state.confidence <= cleared_confidence:
                continue
            candidates.append((state.confidence, state))

        if not candidates:
            return None
        _, destination = max(candidates, key=lambda item: item[0])
        return InferredDeparture(
            zone=event.zone,
            via_zone=transition.zone,
            via_node_id=transition.node_id,
            destination_zone=destination.zone,
            event_at=event.event_at,
            expires_at=event.event_at + self.config.departure_retention,
        )

    def _transition_window_for_events(
        self,
        source: OccupancyEvent,
        target: OccupancyEvent,
        default_window: timedelta,
    ) -> timedelta:
        configured_seconds = self._map.transition_seconds_between_nodes(
            source.node_id,
            target.node_id,
        )
        if configured_seconds is None:
            return default_window
        return timedelta(seconds=configured_seconds)

    def _mark_entry_plausibilities(self, event: OccupancyEvent) -> None:
        for target_zone in self.graph.neighbors(event.zone):
            window = self._entry_plausibility_window_for_zone(event, target_zone)
            self._entry_plausibilities[target_zone] = EntryPlausibility(
                zone=target_zone,
                source_zone=event.zone,
                source_node_id=event.node_id,
                event_at=event.event_at,
                expires_at=event.event_at + window,
            )

    def _entry_plausibility_window_for_zone(
        self,
        event: OccupancyEvent,
        target_zone: str,
    ) -> timedelta:
        configured_seconds = [
            seconds
            for node in self._map.nodes.values()
            if node.occupancy_zone == target_zone
            if (
                seconds := self._map.transition_seconds_between_nodes(
                    event.node_id,
                    node.node_id,
                )
            )
            is not None
        ]
        if not configured_seconds:
            return self.config.entry_plausibility_window
        return timedelta(seconds=max(configured_seconds))

    def _nonadjacent_saturated_track_zones(
        self, event: OccupancyEvent
    ) -> tuple[str, ...]:
        if event.state != "on":
            return ()
        track_zones = self._saturated_active_track_zones()
        if not track_zones:
            return ()
        corridor = self.graph.movement_corridor(
            track_zones,
            radius=self.config.corridor_radius,
        )
        return () if event.zone in corridor else track_zones

    def _allowed_prediction_zones(
        self, source_zone: str | None
    ) -> frozenset[str] | None:
        if source_zone is None:
            return None
        track_zones = self._saturated_active_track_zones()
        if not track_zones:
            return None
        saturated_corridor = self.graph.movement_corridor(
            track_zones,
            radius=self.config.corridor_radius,
        )
        if source_zone not in saturated_corridor:
            return frozenset()
        return self.graph.movement_corridor((source_zone,), radius=1)

    def _saturated_active_track_zones(self) -> tuple[str, ...]:
        occupant_limit = self.config.occupant_limit
        active_tracks = tuple(track for track in self._tracks if track.active)
        if occupant_limit is None or len(active_tracks) < occupant_limit:
            return ()
        return tuple(track.zone for track in active_tracks[:occupant_limit])

    def _zone_for_node(self, node_id: str | None) -> str | None:
        if node_id is None:
            return None
        node = self._map.nodes.get(node_id)
        return None if node is None else node.occupancy_zone

    def _expire_inferences(self, now: datetime) -> bool:
        previous_join_slots = self._join_slots
        previous_departures = self._departures
        previous_entry_plausibilities = self._entry_plausibilities
        self._join_slots = {
            zone: slot
            for zone, slot in self._join_slots.items()
            if slot.expires_at >= now
        }
        self._departures = {
            zone: departure
            for zone, departure in self._departures.items()
            if departure.expires_at >= now
        }
        self._entry_plausibilities = {
            zone: plausibility
            for zone, plausibility in self._entry_plausibilities.items()
            if plausibility.expires_at >= now
        }
        return (
            previous_join_slots != self._join_slots
            or previous_departures != self._departures
            or previous_entry_plausibilities != self._entry_plausibilities
        )

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
        self._update_protected_corridor()

    def _update_protected_corridor(self) -> None:
        track_zones = self._saturated_active_track_zones()
        self._protected_tracks = track_zones
        self._protected_corridor = tuple(
            sorted(
                self.graph.movement_corridor(
                    track_zones,
                    radius=self.config.corridor_radius,
                )
            )
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


def join_slot_payload(slot: InferredJoinSlot) -> dict[str, str]:
    return {
        "zone": slot.zone,
        "source_zone": slot.source_zone,
        "source_node_id": slot.source_node_id,
        "event_at": slot.event_at.isoformat(),
        "expires_at": slot.expires_at.isoformat(),
    }


def departure_payload(departure: InferredDeparture) -> dict[str, str]:
    return {
        "zone": departure.zone,
        "via_zone": departure.via_zone,
        "via_node_id": departure.via_node_id,
        "destination_zone": departure.destination_zone,
        "event_at": departure.event_at.isoformat(),
        "expires_at": departure.expires_at.isoformat(),
    }
