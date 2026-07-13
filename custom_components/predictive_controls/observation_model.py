from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .events import OccupancyEvent
from .model import PredictiveMap
from .occupancy_state import ObservationProvenance


@dataclass(frozen=True)
class ObservationProfile:
    """Calibrated binary sensor likelihoods before reliability interpolation."""

    on_occupied: float
    on_empty: float
    off_occupied: float
    off_empty: float


SUSTAINED_PROFILE = ObservationProfile(0.97, 0.02, 0.30, 0.95)
ORDINARY_PROFILE = ObservationProfile(0.90, 0.04, 0.45, 0.90)
TRANSITION_PROFILE = ObservationProfile(0.85, 0.05, 0.55, 0.85)


@dataclass(frozen=True)
class EntityEvidence:
    """Latest likelihood contribution retained for one physical entity."""

    state: str
    log_likelihood_by_count: tuple[float, ...]
    changed_at: datetime
    episode_started_at: datetime
    duration_log_odds: float = 0.0
    departure_observed: bool = False


class ObservationModel:
    """Convert sensor edges into bounded per-count log-likelihood deltas."""

    def __init__(
        self,
        expected_occupants: int,
        correlation_window: timedelta = timedelta(minutes=15),
        predictive_map: PredictiveMap | None = None,
    ) -> None:
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        self.expected_occupants = expected_occupants
        self.correlation_window = correlation_window
        self._evidence: dict[str, EntityEvidence] = {}
        self._entity_nodes = (
            {}
            if predictive_map is None
            else {
                entity_id: binding.node_id
                for entity_id in predictive_map.entity_ids()
                if (binding := predictive_map.entity_binding_for_entity(entity_id))
                is not None
            }
        )

    @property
    def entity_states(self) -> dict[str, EntityEvidence]:
        return self._evidence.copy()

    @property
    def asserted_node_likelihoods(self) -> dict[str, tuple[float, ...]]:
        return {
            node_id: self._effective_node_likelihood(node_id)
            for node_id in set(self._entity_nodes.values())
            if any(
                self._entity_nodes.get(entity_id) == node_id
                and state.state == "on"
                and not state.departure_observed
                for entity_id, state in self._evidence.items()
            )
        }

    def set_expected_occupants(self, expected_occupants: int) -> None:
        """Resize future likelihood vectors and clear incompatible evidence."""

        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        if expected_occupants != self.expected_occupants:
            self.expected_occupants = expected_occupants
            self._evidence.clear()

    def prepare_delta(self, event: OccupancyEvent) -> ObservationProvenance:
        """Return the replacement delta for one changed entity state."""

        event_id = _event_id(event)
        if event.state not in {"on", "off"}:
            return self._provenance(
                event, event_id, event_id, "ignored", self._neutral()
            )

        self._entity_nodes[event.entity_id] = event.node_id
        previous = self._evidence.get(event.entity_id)
        if previous is not None and previous.state == event.state:
            episode_id = _episode_id(event.entity_id, previous.episode_started_at)
            return self._provenance(
                event,
                event_id,
                episode_id,
                "duplicate",
                self._neutral(),
            )

        node_already_asserted = any(
            entity_id != event.entity_id
            and self._entity_nodes.get(entity_id) == event.node_id
            and state.state == "on"
            and not state.departure_observed
            for entity_id, state in self._evidence.items()
        )
        previous_node_likelihood = self._effective_node_likelihood(event.node_id)
        current_likelihood = self._likelihood(event)
        if previous is None:
            episode_started_at = event.event_at
            disposition = "accepted"
        else:
            quiet_time = event.event_at - previous.changed_at
            episode_started_at = (
                event.event_at
                if quiet_time > self.correlation_window
                else previous.episode_started_at
            )
            disposition = "replacement"

        self._evidence[event.entity_id] = EntityEvidence(
            state=event.state,
            log_likelihood_by_count=current_likelihood,
            changed_at=event.event_at,
            episode_started_at=episode_started_at,
        )
        current_node_likelihood = self._effective_node_likelihood(event.node_id)
        delta = tuple(
            current - previous
            for current, previous in zip(
                current_node_likelihood,
                previous_node_likelihood,
                strict=True,
            )
        )
        if event.state == "on" and node_already_asserted:
            disposition = "correlated_alias"
        return self._provenance(
            event,
            event_id,
            _episode_id(event.entity_id, episode_started_at),
            disposition,
            delta,
        )

    def prepare_snapshot_delta(self, event: OccupancyEvent) -> ObservationProvenance:
        """Replace one stored factor from a complete startup snapshot."""

        if event.state in {"on", "off"}:
            return self.prepare_delta(event)
        self._entity_nodes[event.entity_id] = event.node_id
        previous_node_likelihood = self._effective_node_likelihood(event.node_id)
        previous = self._evidence.pop(event.entity_id, None)
        if previous is None:
            return self._provenance(
                event,
                _event_id(event),
                _event_id(event),
                "ignored",
                self._neutral(),
            )
        current_node_likelihood = self._effective_node_likelihood(event.node_id)
        return self._provenance(
            event,
            _event_id(event),
            _episode_id(event.entity_id, previous.episode_started_at),
            "replacement",
            tuple(
                current - old
                for current, old in zip(
                    current_node_likelihood,
                    previous_node_likelihood,
                    strict=True,
                )
            ),
        )

    def restore_entity_states(self, states: dict[str, EntityEvidence]) -> None:
        """Restore already-validated entity evidence for bootstrap deduplication."""

        expected_length = self.expected_occupants + 1
        if any(
            len(state.log_likelihood_by_count) != expected_length
            for state in states.values()
        ):
            raise ValueError("restored likelihood vector length does not match count")
        self._evidence = states.copy()

    def apply_duration_log_odds(self, entity_id: str, target: float) -> float:
        """Advance one asserted episode to an absolute bounded duration factor."""

        state = self._evidence.get(entity_id)
        if state is None or state.state != "on" or state.departure_observed:
            return 0.0
        node_id = self._entity_nodes.get(entity_id)
        if node_id is None:
            return 0.0
        previous = self._effective_node_likelihood(node_id)
        self._evidence[entity_id] = replace(
            state,
            duration_log_odds=max(state.duration_log_odds, target),
        )
        current = self._effective_node_likelihood(node_id)
        return 0.0 if self.expected_occupants == 0 else current[1] - previous[1]

    def invalidate_asserted_episode(self, entity_id: str) -> tuple[float, ...]:
        """Remove one asserted episode after confirmed path-specific departure."""

        state = self._evidence.get(entity_id)
        if state is None or state.state != "on" or state.departure_observed:
            return self._neutral()
        node_id = self._entity_nodes.get(entity_id)
        if node_id is None:
            return self._neutral()
        previous = self._effective_node_likelihood(node_id)
        self._evidence[entity_id] = replace(
            state,
            log_likelihood_by_count=self._neutral(),
            duration_log_odds=0.0,
            departure_observed=True,
        )
        current = self._effective_node_likelihood(node_id)
        return tuple(
            new - old for new, old in zip(current, previous, strict=True)
        )

    def _effective_node_likelihood(self, node_id: str) -> tuple[float, ...]:
        candidates = tuple(
            (entity_id, state)
            for entity_id, state in self._evidence.items()
            if self._entity_nodes.get(entity_id) == node_id
            and not state.departure_observed
        )
        asserted = tuple(item for item in candidates if item[1].state == "on")
        if asserted:
            _, selected = max(
                asserted,
                key=lambda item: (
                    _occupied_log_odds(item[1]),
                    item[0],
                ),
            )
        elif candidates:
            _, selected = max(
                candidates,
                key=lambda item: (
                    -_occupied_log_odds(item[1]),
                    item[0],
                ),
            )
        else:
            return self._neutral()
        duration_log_odds = max(
            (
                state.duration_log_odds
                for _, state in asserted
            ),
            default=0.0,
        )
        return tuple(
            value + (duration_log_odds if count > 0 else 0.0)
            for count, value in enumerate(selected.log_likelihood_by_count)
        )

    def _neutral(self) -> tuple[float, ...]:
        return (0.0,) * (self.expected_occupants + 1)

    def _likelihood(self, event: OccupancyEvent) -> tuple[float, ...]:
        profile = _profile_for_event(event)
        if event.state == "on":
            empty, occupied = profile.on_empty, profile.on_occupied
        else:
            empty, occupied = profile.off_empty, profile.off_occupied
        calibrated_empty = _calibrated(empty, event.reliability)
        calibrated_occupied = _calibrated(occupied, event.reliability)
        return (
            math.log(calibrated_empty),
            *(math.log(calibrated_occupied) for _ in range(self.expected_occupants)),
        )

    @staticmethod
    def _provenance(
        event: OccupancyEvent,
        event_id: str,
        episode_id: str,
        disposition: str,
        delta: tuple[float, ...],
    ) -> ObservationProvenance:
        return ObservationProvenance(
            event_id=event_id,
            evidence_episode_id=episode_id,
            entity_id=event.entity_id,
            node_id=event.node_id,
            zone=event.zone,
            state=event.state,
            signal_type=event.signal_type,
            reliability=event.reliability,
            log_likelihood_by_count=delta,
            disposition=disposition,
        )


def _profile_for_event(event: OccupancyEvent) -> ObservationProfile:
    if event.occupancy_behavior == "transient" or event.role == "transition_gate":
        return TRANSITION_PROFILE
    if event.signal_type == "still_target" or event.occupancy_behavior in {
        "sticky",
        "sustained",
    }:
        return SUSTAINED_PROFILE
    return ORDINARY_PROFILE


def _occupied_log_odds(state: EntityEvidence) -> float:
    if len(state.log_likelihood_by_count) < 2:
        return 0.0
    return state.log_likelihood_by_count[1] - state.log_likelihood_by_count[0]


def _calibrated(base: float, reliability: float) -> float:
    bounded_reliability = min(1.0, max(0.0, reliability))
    return 0.5 + bounded_reliability * (base - 0.5)


def _event_id(event: OccupancyEvent) -> str:
    return f"{event.entity_id}@{event.event_at.isoformat()}:{event.state}"


def _episode_id(entity_id: str, started_at: datetime) -> str:
    return f"{entity_id}@{started_at.isoformat()}"
