from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.predictive_controls.zone_model.calibration import (
    CalibrationCandidate,
    CalibrationMetrics,
    CalibrationTrace,
    CalibrationWeights,
    build_candidate_grid,
    evaluate_candidates,
)
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    SHARED_PROFILES,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "zone_model"
NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
TRACE_DISPOSITIONS = (
    CalibrationTrace("T01-open-hallway-backtracking", "replay", "belief_departure"),
    CalibrationTrace("T02-direct-arrival-quiet-stay", "replay", "quiet_stay"),
    CalibrationTrace(
        "T03-two-occupants-open-transition", "deferred", "phase_4_traversal"
    ),
    CalibrationTrace(
        "T04-probability-release-without-global-support",
        "replay",
        "probability_release",
    ),
    CalibrationTrace("T05-stuck-transition-degrades", "replay", "stuck_transition"),
    CalibrationTrace("T06-held-stay-remains-active", "replay", "held_stay"),
    CalibrationTrace("T07-manual-off-refresh", "deferred", "phase_5_refresh"),
)


def test_all_retained_traces_have_explicit_calibration_dispositions() -> None:
    fixture_ids = {
        __import__("json").loads(path.read_text())["scenario_id"]
        for path in FIXTURE_DIR.glob("*.json")
    }
    assert {trace.trace_id for trace in TRACE_DISPOSITIONS} == fixture_ids
    assert {trace.disposition for trace in TRACE_DISPOSITIONS} == {
        "deferred",
        "replay",
    }


def test_belief_calibration_is_shared_and_has_no_zone_dimension() -> None:
    assert set(BELIEF_PROFILES) == set(SHARED_PROFILES)
    assert all(profile.profile_id == name for name, profile in BELIEF_PROFILES.items())
    candidate_field_names = {
        field.name
        for field in fields(
            build_candidate_grid(
                "stay_pir",
                BELIEF_PROFILES["stay_pir"],
                positive_likelihoods=((0.05, 0.95),),
                clear_likelihoods=((0.8, 0.6),),
                prior_probabilities=(0.05,),
                asserted=(BELIEF_PROFILES["stay_pir"].asserted,),
                cleared_without_outward=(
                    BELIEF_PROFILES["stay_pir"].cleared_without_outward,
                ),
                cleared_with_outward=(
                    BELIEF_PROFILES["stay_pir"].cleared_with_outward,
                ),
                degraded_asserted=(BELIEF_PROFILES["stay_pir"].degraded_asserted,),
                unavailable=(BELIEF_PROFILES["stay_pir"].unavailable,),
                thresholds=((0.7, 0.3),),
                release_dwells=(timedelta(seconds=30),),
            )[0]
        )
    }
    assert "zone" not in candidate_field_names


def test_phase5_first_positive_posteriors_select_provisional_threshold() -> None:
    expected = {
        "entry_boundary": 0.625,
        "transition_fast": 0.7142857142857143,
        "stay_pir": 0.7205882352941176,
        "stay_presence": 0.8396624472573839,
    }
    observed: dict[str, float] = {}
    for profile_name, profile in BELIEF_PROFILES.items():
        filter_ = ZoneBeliefFilter("zone", profile, NOW)
        observed[profile_name] = filter_.apply_positive(
            f"{profile_name}:1", NOW
        ).probability
    assert observed == pytest.approx(expected)
    required_acquisition_profiles = (
        "transition_fast",
        "stay_pir",
        "stay_presence",
    )
    assert all(observed[name] >= 0.65 for name in required_acquisition_profiles)
    assert all(observed[name] >= 0.70 for name in required_acquisition_profiles)
    assert observed["transition_fast"] < 0.75
    assert observed["stay_pir"] < 0.75


def test_candidate_grid_is_complete_and_deterministic() -> None:
    profile = BELIEF_PROFILES["transition_fast"]

    def build() -> tuple[CalibrationCandidate, ...]:
        return build_candidate_grid(
            "transition_fast",
            profile,
            positive_likelihoods=((0.1, 0.9), (0.2, 0.8)),
            clear_likelihoods=((0.8, 0.6),),
            prior_probabilities=(0.05,),
            asserted=(profile.asserted,),
            cleared_without_outward=(profile.cleared_without_outward,),
            cleared_with_outward=(profile.cleared_with_outward,),
            degraded_asserted=(profile.degraded_asserted,),
            unavailable=(profile.unavailable,),
            thresholds=((0.7, 0.3), (0.8, 0.2)),
            release_dwells=(timedelta(seconds=30), timedelta(seconds=60)),
        )

    first = build()
    second = build()

    assert first == second
    assert len(first) == 8
    assert tuple(candidate.candidate_id for candidate in first) == tuple(
        f"transition_fast-{index:04d}" for index in range(8)
    )


def test_calibration_scoring_retains_raw_metrics_and_weights_false_release() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    candidates = build_candidate_grid(
        "stay_pir",
        profile,
        positive_likelihoods=((0.05, 0.95), (0.1, 0.9)),
        clear_likelihoods=((0.8, 0.6),),
        prior_probabilities=(profile.prior_probability,),
        asserted=(profile.asserted,),
        cleared_without_outward=(profile.cleared_without_outward,),
        cleared_with_outward=(profile.cleared_with_outward,),
        degraded_asserted=(profile.degraded_asserted,),
        unavailable=(profile.unavailable,),
        thresholds=((0.7, 0.3),),
        release_dwells=(timedelta(seconds=30),),
    )

    def replay(
        candidate: CalibrationCandidate,
        trace: CalibrationTrace,
    ) -> CalibrationMetrics:
        assert trace.disposition == "replay"
        if candidate.candidate_id.endswith("0000"):
            return CalibrationMetrics(false_release_count=1)
        return CalibrationMetrics(missed_activation_count=1)

    report = evaluate_candidates(
        candidates,
        TRACE_DISPOSITIONS,
        replay,
        CalibrationWeights(false_release_count=5.0, missed_activation_count=1.0),
    )

    assert report.best.candidate.candidate_id == "stay_pir-0001"
    assert report.best.raw_metrics.missed_activation_count == 5
    assert report.scores[0].raw_metrics.false_release_count == 5
    assert report.scores[0].score > report.scores[1].score


def test_calibration_ties_use_candidate_id_and_invalid_inputs_are_rejected() -> None:
    profile = BELIEF_PROFILES["entry_boundary"]
    candidates = build_candidate_grid(
        "entry_boundary",
        profile,
        positive_likelihoods=((0.1, 0.9), (0.2, 0.8)),
        clear_likelihoods=((0.8, 0.6),),
        prior_probabilities=(profile.prior_probability,),
        asserted=(profile.asserted,),
        cleared_without_outward=(profile.cleared_without_outward,),
        cleared_with_outward=(profile.cleared_with_outward,),
        degraded_asserted=(profile.degraded_asserted,),
        unavailable=(profile.unavailable,),
        thresholds=((0.7, 0.3),),
        release_dwells=(timedelta(seconds=30),),
    )
    report = evaluate_candidates(
        tuple(reversed(candidates)),
        TRACE_DISPOSITIONS,
        lambda _candidate, _trace: CalibrationMetrics(),
    )
    assert report.best.candidate.candidate_id == "entry_boundary-0000"

    with pytest.raises(ValueError, match="candidate"):
        evaluate_candidates(
            (),
            TRACE_DISPOSITIONS,
            lambda _candidate, _trace: CalibrationMetrics(),
        )
    with pytest.raises(ValueError, match="replay trace"):
        evaluate_candidates(
            candidates,
            (),
            lambda _candidate, _trace: CalibrationMetrics(),
        )
    with pytest.raises(ValueError, match="false release"):
        CalibrationWeights(false_release_count=0.5, missed_activation_count=1.0)


def test_calibration_types_and_grid_reject_invalid_values() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    candidate = build_candidate_grid(
        "stay_pir",
        profile,
        positive_likelihoods=((0.02, 0.98),),
        clear_likelihoods=((0.75, 0.55),),
        prior_probabilities=(0.05,),
        asserted=(profile.asserted,),
        cleared_without_outward=(profile.cleared_without_outward,),
        cleared_with_outward=(profile.cleared_with_outward,),
        degraded_asserted=(profile.degraded_asserted,),
        unavailable=(profile.unavailable,),
        thresholds=((0.7, 0.3),),
        release_dwells=(timedelta(seconds=30),),
    )[0]
    invalid_candidates: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: replace(candidate, candidate_id=""), "candidate ID"),
        (lambda: replace(candidate, on_threshold=0.2), "thresholds"),
        (lambda: replace(candidate, release_dwell=timedelta(0)), "dwell"),
    )
    for factory, message in invalid_candidates:
        with pytest.raises(ValueError, match=message):
            factory()

    with pytest.raises(ValueError, match="identity"):
        CalibrationTrace("", "replay", "reason")
    with pytest.raises(ValueError, match="disposition"):
        CalibrationTrace("trace", "ignored", "reason")
    with pytest.raises(ValueError, match="metrics"):
        CalibrationMetrics(darkness_seconds=math.nan)
    with pytest.raises(ValueError, match="weights"):
        CalibrationWeights(darkness_seconds=-1.0)
    with pytest.raises(ValueError, match="match the template"):
        build_candidate_grid(
            "transition_fast",
            profile,
            positive_likelihoods=((0.02, 0.98),),
            clear_likelihoods=((0.75, 0.55),),
            prior_probabilities=(0.05,),
            asserted=(profile.asserted,),
            cleared_without_outward=(profile.cleared_without_outward,),
            cleared_with_outward=(profile.cleared_with_outward,),
            degraded_asserted=(profile.degraded_asserted,),
            unavailable=(profile.unavailable,),
            thresholds=((0.7, 0.3),),
            release_dwells=(timedelta(seconds=30),),
        )
    with pytest.raises(ValueError, match="dimensions"):
        build_candidate_grid(
            "stay_pir",
            profile,
            positive_likelihoods=(),
            clear_likelihoods=((0.75, 0.55),),
            prior_probabilities=(0.05,),
            asserted=(profile.asserted,),
            cleared_without_outward=(profile.cleared_without_outward,),
            cleared_with_outward=(profile.cleared_with_outward,),
            degraded_asserted=(profile.degraded_asserted,),
            unavailable=(profile.unavailable,),
            thresholds=((0.7, 0.3),),
            release_dwells=(timedelta(seconds=30),),
        )


def test_provisional_profiles_meet_retained_filter_timeline_bounds() -> None:
    quiet_stay = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_pir"], NOW)
    quiet_stay.apply_positive("quiet", NOW + timedelta(seconds=2))
    quiet_stay.apply_stable_clear("quiet", NOW + timedelta(seconds=37))
    quiet_stay.advance(NOW + timedelta(minutes=5))

    outward_departure = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_pir"], NOW)
    outward_departure.apply_positive("outward", NOW + timedelta(seconds=2))
    outward_departure.register_outward(
        "outward",
        NOW + timedelta(seconds=92),
        NOW + timedelta(seconds=25),
    )
    outward_departure.apply_stable_clear("outward", NOW + timedelta(seconds=25))
    outward_departure.advance(NOW + timedelta(minutes=2))

    probability_release = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_pir"], NOW)
    probability_release.apply_positive("release", NOW + timedelta(seconds=2))
    probability_release.apply_stable_clear("release", NOW + timedelta(seconds=35))
    probability_release.advance(NOW + timedelta(minutes=10))

    stuck_transition = ZoneBeliefFilter("zone", BELIEF_PROFILES["transition_fast"], NOW)
    stuck_transition.apply_positive("transition", NOW + timedelta(seconds=2))
    stuck_transition.apply_health_degraded("transition", NOW + timedelta(seconds=62))
    stuck_transition.advance(NOW + timedelta(minutes=10))

    held_presence = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_presence"], NOW)
    held_presence.apply_positive("presence", NOW + timedelta(seconds=2))
    held_presence.advance(NOW + timedelta(hours=2))

    assert quiet_stay.state.probability > 0.3
    assert outward_departure.state.probability < 0.3
    assert probability_release.state.probability < 0.3
    assert stuck_transition.state.probability < 0.3
    assert held_presence.state.probability > 0.9
