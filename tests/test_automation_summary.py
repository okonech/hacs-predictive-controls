from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.predictive_controls.automation_summary import (
    _active_plausibility_zones,
    runtime_automation_summary,
)
from custom_components.predictive_controls.confidence import ZoneState
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import (
    ActivationPlausibility,
    AnonymousTrack,
    EntryPlausibility,
    InferredDeparture,
    TrackerDiagnostics,
)


@dataclass(frozen=True)
class FakeRuntime:
    map: PredictiveMap
    zone_states: dict[str, ZoneState]
    expected_occupants: int
    confidence: object


@dataclass(frozen=True)
class FakeConfidence:
    diagnostics: TrackerDiagnostics


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "living_motion": {
                    "zone": "living_room",
                    "adjacent": ["foyer_motion"],
                },
                "foyer_motion": {
                    "zone": "foyer",
                    "adjacent": ["living_motion", "kitchen_motion"],
                },
                "kitchen_motion": {
                    "zone": "kitchen",
                    "adjacent": ["foyer_motion"],
                },
                "office_motion": {"zone": "office", "adjacent": []},
            }
        }
    )


def make_diagnostics() -> TrackerDiagnostics:
    return TrackerDiagnostics(
        expected_occupants=2,
        tracks=(
            AnonymousTrack(
                track_id="track_1",
                zone="living_room",
                confidence=0.88,
                active=True,
                last_evidence_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
                source_entities=("binary_sensor.living_still",),
            ),
            AnonymousTrack(
                track_id="track_2",
                zone="kitchen",
                confidence=0.42,
                active=False,
                last_evidence_at=datetime(2026, 6, 7, 11, 58, tzinfo=UTC),
                source_entities=(),
            ),
        ),
        protected_tracks=("living_room",),
        protected_corridor=("foyer", "living_room"),
        inferred_join_slots=(),
        inferred_departures=(
            InferredDeparture(
                zone="kitchen",
                via_zone="foyer",
                via_node_id="foyer_motion",
                destination_zone="living_room",
                event_at=datetime(2026, 6, 7, 12, 1, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 6, tzinfo=UTC),
            ),
        ),
        prediction_hints={"kitchen": 0.72, "office": 0.31},
        dwell_seconds={},
        entry_plausibilities=(
            EntryPlausibility(
                zone="foyer",
                source_zone="living_room",
                source_node_id="living_motion",
                event_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 1, tzinfo=UTC),
            ),
        ),
        activation_plausibilities=(
            ActivationPlausibility(
                zone="foyer",
                reason="fresh adjacent entry path before local detection",
                source_zone="living_room",
                source_node_id="living_motion",
                event_at=datetime(2026, 6, 7, 12, tzinfo=UTC),
                expires_at=datetime(2026, 6, 7, 12, 1, tzinfo=UTC),
            ),
        ),
    )


def make_runtime() -> FakeRuntime:
    return FakeRuntime(
        map=make_map(),
        zone_states={
            "living_room": ZoneState(
                zone="living_room",
                confidence=0.91,
                status="confirmed",
            ),
            "kitchen": ZoneState(
                zone="kitchen",
                confidence=0.48,
                status="possible",
            ),
            "office": ZoneState(
                zone="office",
                confidence=0.12,
                status="suspect",
            ),
        },
        expected_occupants=2,
        confidence=FakeConfidence(make_diagnostics()),
    )


def test_summary_exposes_probable_and_possible_zone_contracts() -> None:
    summary = runtime_automation_summary(make_runtime())

    assert summary.expected_inside_count == 2
    assert summary.probable_inside_count == 1
    assert summary.possible_inside_count == 2
    assert summary.probable_occupied_zones == ("living_room",)
    assert summary.possible_occupied_zones == ("kitchen", "living_room")
    assert summary.zones["living_room"].probable_occupancy
    assert summary.zones["kitchen"].possible_occupancy
    assert not summary.zones["office"].possible_occupancy


def test_summary_exposes_activation_and_keep_on_contracts() -> None:
    summary = runtime_automation_summary(make_runtime())

    assert summary.activation_plausible_zones == ("foyer",)
    assert summary.keep_on_zones == ("living_room",)
    assert summary.diagnostic_entry_path_plausible_zones == ("foyer",)
    assert summary.zones["foyer"].activation_plausible
    assert summary.zones["foyer"].diagnostic_entry_path_plausible
    assert not summary.zones["kitchen"].activation_plausible
    assert not summary.zones["office"].activation_plausible
    assert not summary.zones["kitchen"].keep_on


def test_summary_exposes_zone_predictions_for_prelighting() -> None:
    summary = runtime_automation_summary(make_runtime())

    assert summary.diagnostic_predicted_next_zone == "kitchen"
    assert summary.diagnostic_predicted_next_probability == 0.72
    assert summary.prelight_plausible_zones == ("kitchen",)
    assert summary.zones["kitchen"].prelight_plausible
    assert summary.zones["kitchen"].prediction_probability == 0.72
    assert not summary.zones["office"].prelight_plausible


def test_prediction_threshold_can_be_tuned_for_zone_predictions() -> None:
    summary = runtime_automation_summary(make_runtime(), prediction_threshold=0.3)

    assert summary.prelight_plausible_zones == ("kitchen", "office")
    assert not summary.zones["office"].activation_plausible


def test_expired_entry_path_plausibility_is_ignored_after_last_event() -> None:
    runtime = make_runtime()
    object.__setattr__(
        runtime,
        "last_occupancy_event",
        SimpleNamespace(event_at=datetime(2026, 6, 7, 12, 2, tzinfo=UTC)),
    )

    summary = runtime_automation_summary(runtime)

    assert summary.diagnostic_entry_path_plausible_zones == ()
    assert summary.prelight_plausible_zones == ("kitchen",)


def test_plausibility_filter_keeps_unexpired_valid_zones() -> None:
    now = datetime(2026, 6, 7, 12, tzinfo=UTC)
    diagnostics = SimpleNamespace(
        entry_plausibilities=(
            SimpleNamespace(
                zone="foyer",
                expires_at=now + timedelta(seconds=30),
            ),
            SimpleNamespace(
                zone=None,
                expires_at=now + timedelta(seconds=30),
            ),
        )
    )

    zones = _active_plausibility_zones(
        diagnostics,
        SimpleNamespace(event_at=now),
        "entry_plausibilities",
    )

    assert zones == {"foyer"}


def test_summary_explanation_is_short_and_human_readable() -> None:
    summary = runtime_automation_summary(make_runtime())

    assert summary.explanation == (
        "Probably occupied: Living Room. Next likely zone: Kitchen (72%)."
    )


def test_summary_handles_no_occupancy_or_predictions() -> None:
    runtime = FakeRuntime(
        map=make_map(),
        zone_states={},
        expected_occupants=0,
        confidence=FakeConfidence(
            TrackerDiagnostics(
                expected_occupants=0,
                tracks=(),
                protected_tracks=(),
                protected_corridor=(),
                inferred_join_slots=(),
                inferred_departures=(),
                prediction_hints={},
                dwell_seconds={},
            )
        ),
    )

    summary = runtime_automation_summary(runtime)

    assert summary.expected_inside_count == 0
    assert summary.probable_inside_count == 0
    assert summary.possible_inside_count == 0
    assert summary.probable_occupied_zones == ()
    assert summary.diagnostic_predicted_next_zone is None
    assert summary.diagnostic_predicted_next_probability is None
    assert summary.explanation == "No zones are probably occupied."


def test_summary_explanation_limits_long_zone_lists() -> None:
    runtime = FakeRuntime(
        map=PredictiveMap.from_mapping(
            {
                "nodes": {
                    "a_motion": {"zone": "alpha"},
                    "b_motion": {"zone": "bravo"},
                    "c_motion": {"zone": "charlie"},
                    "d_motion": {"zone": "delta"},
                }
            }
        ),
        zone_states={
            zone: ZoneState(zone=zone, confidence=0.7, status="probable")
            for zone in ("alpha", "bravo", "charlie", "delta")
        },
        expected_occupants=0,
        confidence=FakeConfidence(
            TrackerDiagnostics(
                expected_occupants=0,
                tracks=(),
                protected_tracks=(),
                protected_corridor=(),
                inferred_join_slots=(),
                inferred_departures=(),
                prediction_hints={},
                dwell_seconds={},
            )
        ),
    )

    summary = runtime_automation_summary(runtime)

    assert summary.explanation == "Probably occupied: Alpha, Bravo, Charlie +1 more."
