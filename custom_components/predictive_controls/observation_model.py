from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .events import OccupancyEvent
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
    ) -> None:
        if expected_occupants < 0:
            raise ValueError("expected_occupants must be non-negative")
        self.expected_occupants = expected_occupants
        self.correlation_window = correlation_window
        self._evidence: dict[str, EntityEvidence] = {}

    @property
    def entity_states(self) -> dict[str, EntityEvidence]:
        return self._evidence.copy()

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

        current_likelihood = self._likelihood(event)
        if previous is None:
            episode_started_at = event.event_at
            delta = current_likelihood
            disposition = "accepted"
        else:
            quiet_time = event.event_at - previous.changed_at
            episode_started_at = (
                event.event_at
                if quiet_time > self.correlation_window
                else previous.episode_started_at
            )
            delta = tuple(
                current
                - old
                - (previous.duration_log_odds if count > 0 else 0.0)
                for count, (current, old) in enumerate(
                    zip(
                        current_likelihood,
                        previous.log_likelihood_by_count,
                        strict=True,
                    )
                )
            )
            disposition = "replacement"

        self._evidence[event.entity_id] = EntityEvidence(
            state=event.state,
            log_likelihood_by_count=current_likelihood,
            changed_at=event.event_at,
            episode_started_at=episode_started_at,
        )
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
        previous = self._evidence.pop(event.entity_id, None)
        if previous is None:
            return self._provenance(
                event,
                _event_id(event),
                _event_id(event),
                "ignored",
                self._neutral(),
            )
        return self._provenance(
            event,
            _event_id(event),
            _episode_id(event.entity_id, previous.episode_started_at),
            "replacement",
            tuple(-value for value in previous.log_likelihood_by_count),
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
        increment = max(0.0, target - state.duration_log_odds)
        if increment > 0.0:
            self._evidence[entity_id] = replace(
                state,
                duration_log_odds=target,
            )
        return increment

    def invalidate_asserted_episode(self, entity_id: str) -> tuple[float, ...]:
        """Remove one asserted episode after confirmed path-specific departure."""

        state = self._evidence.get(entity_id)
        if state is None or state.state != "on" or state.departure_observed:
            return self._neutral()
        applied = tuple(
            value + (state.duration_log_odds if count > 0 else 0.0)
            for count, value in enumerate(state.log_likelihood_by_count)
        )
        self._evidence[entity_id] = replace(
            state,
            log_likelihood_by_count=self._neutral(),
            duration_log_odds=0.0,
            departure_observed=True,
        )
        return tuple(-value for value in applied)

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


def _calibrated(base: float, reliability: float) -> float:
    bounded_reliability = min(1.0, max(0.0, reliability))
    return 0.5 + bounded_reliability * (base - 0.5)


def _event_id(event: OccupancyEvent) -> str:
    return f"{event.entity_id}@{event.event_at.isoformat()}:{event.state}"


def _episode_id(entity_id: str, started_at: datetime) -> str:
    return f"{entity_id}@{started_at.isoformat()}"
