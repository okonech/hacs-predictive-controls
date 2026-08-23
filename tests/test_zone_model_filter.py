from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.zone_model.filter import (
    ARRIVAL_FROM_EMPTY_PROBABILITY,
    ARRIVAL_FROM_OCCUPIED_PROBABILITY,
    ZoneBeliefFilter,
    probability_to_log_odds,
)
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.types import (
    BeliefContribution,
    BeliefProfile,
    DecayCalibration,
    OutwardContext,
    ZoneBeliefState,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("profile_name", sorted(BELIEF_PROFILES))
@pytest.mark.parametrize("reliability", (0.0001, 0.5, 1.0))
def test_supported_arrival_crosses_on_threshold_at_reliability_boundaries(
    profile_name: str,
    reliability: float,
) -> None:
    filter_ = ZoneBeliefFilter("zone", BELIEF_PROFILES[profile_name], NOW)
    filter_.apply_positive("episode", NOW, reliability)

    supported = filter_.apply_arrival_transition("episode", NOW)
    duplicate = filter_.apply_arrival_transition("episode", NOW)

    assert supported.probability >= ARRIVAL_FROM_EMPTY_PROBABILITY
    assert supported.probability <= ARRIVAL_FROM_OCCUPIED_PROBABILITY
    assert duplicate == supported


def test_supported_arrival_bounds_high_prior_without_entering_release_region() -> None:
    filter_ = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_presence"], NOW)
    filter_.apply_positive("episode", NOW)
    high_prior = filter_.state.probability

    supported = filter_.apply_arrival_transition("episode", NOW)

    assert high_prior > ARRIVAL_FROM_OCCUPIED_PROBABILITY
    assert supported.probability == pytest.approx(
        ARRIVAL_FROM_EMPTY_PROBABILITY * (1.0 - high_prior)
        + ARRIVAL_FROM_OCCUPIED_PROBABILITY * high_prior
    )
    assert supported.probability > 0.7


def test_interaction_applies_the_finite_ceiling_once_per_episode() -> None:
    filter_ = belief_filter()

    applied = filter_.apply_interaction("interaction", NOW)
    duplicate = filter_.apply_interaction("interaction", NOW)

    assert applied.log_odds == 30.0
    assert duplicate == applied
    assert contribution_count(filter_, "local_interaction") == 1


def test_interaction_idempotency_uses_generation_after_restore() -> None:
    filter_ = belief_filter(contribution_limit=1)
    filter_.apply_interaction("interaction", NOW)
    evicted = filter_.advance(NOW + timedelta(seconds=1))
    assert contribution_count(filter_, "local_interaction") == 0

    restored = ZoneBeliefFilter.restore(
        BELIEF_PROFILES["stay_pir"],
        evicted,
        contribution_limit=1,
    )
    duplicate = restored.apply_interaction(
        "interaction", NOW + timedelta(seconds=1)
    )

    assert duplicate == evicted
    assert duplicate.log_odds < 30.0


def test_arrival_transition_and_observation_reliability_reject_invalid_inputs() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode", NOW)

    with pytest.raises(ValueError, match="probabilities"):
        filter_.apply_arrival_transition(
            "episode",
            NOW,
            empty_to_occupied=0.9,
            occupied_to_occupied=0.8,
        )
    with pytest.raises(ValueError, match="current episode"):
        filter_.apply_arrival_transition("other", NOW)
    with pytest.raises(ValueError, match="Observation reliability"):
        filter_.apply_positive("next", NOW, reliability=0.0)


def belief_filter(
    profile_name: str = "stay_pir",
    *,
    contribution_limit: int = 32,
) -> ZoneBeliefFilter:
    return ZoneBeliefFilter(
        "zone",
        BELIEF_PROFILES[profile_name],
        NOW,
        contribution_limit=contribution_limit,
    )


def contribution_count(filter_: ZoneBeliefFilter, kind: str) -> int:
    return sum(item.kind == kind for item in filter_.state.contributions)


def test_positive_and_stable_clear_are_one_time_bayes_updates() -> None:
    filter_ = belief_filter()
    bootstrap = filter_.state.probability

    positive = filter_.apply_positive("episode-1", NOW + timedelta(seconds=1))
    assert positive.probability > bootstrap
    assert positive.context == "asserted"
    assert positive.generation_episode_id == "episode-1"
    assert positive.asserted_episode_id == "episode-1"
    assert contribution_count(filter_, "local_positive") == 1

    duplicate = filter_.apply_positive("episode-1", NOW + timedelta(seconds=2))
    assert positive.probability < duplicate.probability < 0.9
    assert contribution_count(filter_, "local_positive") == 1

    cleared = filter_.apply_stable_clear("episode-1", NOW + timedelta(seconds=3))
    assert cleared.probability < duplicate.probability
    assert cleared.context == "cleared_without_outward"
    assert cleared.asserted_episode_id is None
    assert contribution_count(filter_, "stable_clear") == 1

    filter_.apply_stable_clear("episode-1", NOW + timedelta(seconds=4))
    assert contribution_count(filter_, "stable_clear") == 1


def test_correlated_positive_cancels_paired_stable_clear_likelihood() -> None:
    filter_ = belief_filter("stay_presence")
    reliability = 0.75
    filter_.apply_positive("episode-1", NOW, reliability)
    filter_.apply_stable_clear("episode-1", NOW, reliability)
    clear_contribution = filter_.state.contributions[-1]

    correlated = filter_.apply_correlated_positive(
        "episode-2",
        NOW,
        reliability,
    )
    correlated_contribution = correlated.contributions[-1]
    profile = BELIEF_PROFILES["stay_presence"]
    expected_scale = math.log(
        profile.clear_empty_likelihood / profile.clear_occupied_likelihood
    ) / math.log(
        profile.positive_occupied_likelihood / profile.positive_empty_likelihood
    )

    assert expected_scale == pytest.approx(0.040879518931593604)
    assert abs(
        clear_contribution.log_odds_delta
        + correlated_contribution.log_odds_delta
    ) <= 1e-12
    assert correlated_contribution.kind == "correlated_positive"
    assert correlated.generation_episode_id == "episode-2"
    assert correlated.asserted_episode_id == "episode-2"
    assert correlated.context == "asserted"
    assert filter_.apply_correlated_positive("episode-2", NOW) == correlated


def test_correlated_positive_rejects_invalid_likelihood_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filter_ = belief_filter("stay_presence")
    monkeypatch.setattr(math, "isfinite", lambda _value: False)

    with pytest.raises(ValueError, match="likelihood scale"):
        filter_.apply_correlated_positive("episode", NOW)


def test_outward_context_is_or_composed_strict_and_generation_scoped() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW + timedelta(seconds=1))
    first_expiry = NOW + timedelta(seconds=30)
    latest_expiry = NOW + timedelta(seconds=45)

    retained = filter_.register_outward(
        "episode-1", first_expiry, NOW + timedelta(seconds=2)
    )
    assert retained.context == "asserted"
    assert retained.outward_context == OutwardContext("episode-1", first_expiry)

    filter_.register_outward("episode-1", latest_expiry, NOW + timedelta(seconds=3))
    cleared = filter_.apply_stable_clear("episode-1", NOW + timedelta(seconds=4))
    assert cleared.context == "cleared_with_outward"
    assert cleared.outward_context == OutwardContext("episode-1", latest_expiry)

    before_expiry = filter_.advance(latest_expiry - timedelta(microseconds=1))
    assert before_expiry.context == "cleared_with_outward"
    expired = filter_.advance(latest_expiry)
    assert expired.context == "cleared_without_outward"
    assert expired.outward_context is None

    renewed = filter_.register_outward(
        "episode-1",
        latest_expiry + timedelta(minutes=1),
        latest_expiry,
    )
    assert renewed.context == "cleared_with_outward"

    with pytest.raises(ValueError, match="current source episode"):
        filter_.register_outward(
            "other-episode", latest_expiry + timedelta(minutes=1), latest_expiry
        )

    filter_.apply_positive("episode-2", latest_expiry)
    assert filter_.state.outward_context is None
    assert filter_.state.generation_episode_id == "episode-2"


def test_callback_cadence_does_not_change_decay_across_outward_expiry() -> None:
    coarse = belief_filter()
    fine = belief_filter()
    expiry = NOW + timedelta(seconds=30)
    frontier = NOW + timedelta(seconds=90)

    for filter_ in (coarse, fine):
        filter_.apply_positive("episode-1", NOW)
        filter_.register_outward("episode-1", expiry, NOW)
        filter_.apply_stable_clear("episode-1", NOW)

    coarse.advance(frontier)
    for seconds in range(10, 91, 10):
        fine.advance(NOW + timedelta(seconds=seconds))

    assert coarse.state.context == fine.state.context == "cleared_without_outward"
    assert coarse.state.probability == pytest.approx(fine.state.probability, abs=1e-12)


def test_quiet_stay_persists_and_outward_departure_accelerates_decay() -> None:
    quiet = belief_filter()
    departed = belief_filter()
    clear_at = NOW + timedelta(seconds=10)
    frontier = NOW + timedelta(minutes=5)

    for filter_ in (quiet, departed):
        filter_.apply_positive("episode-1", NOW)
    departed.register_outward(
        "episode-1", frontier + timedelta(minutes=1), NOW + timedelta(seconds=5)
    )
    quiet.apply_stable_clear("episode-1", clear_at)
    departed.apply_stable_clear("episode-1", clear_at)
    quiet.advance(frontier)
    departed.advance(frontier)

    assert quiet.state.probability > departed.state.probability
    assert quiet.state.context == "cleared_without_outward"
    assert departed.state.context == "cleared_with_outward"


def test_transition_profile_assertion_decays_faster_than_stay_profile() -> None:
    transition = belief_filter("transition_fast")
    stay = belief_filter("stay_pir")
    frontier = NOW + timedelta(seconds=30)

    transition_start = transition.apply_positive("transition-1", NOW).probability
    stay_start = stay.apply_positive("stay-1", NOW).probability
    transition.advance(frontier)
    stay.advance(frontier)

    transition_baseline = BELIEF_PROFILES[
        "transition_fast"
    ].asserted.baseline_probability
    stay_baseline = BELIEF_PROFILES["stay_pir"].asserted.baseline_probability
    transition_fraction = (transition.state.probability - transition_baseline) / (
        transition_start - transition_baseline
    )
    stay_fraction = (stay.state.probability - stay_baseline) / (
        stay_start - stay_baseline
    )
    assert transition_fraction < stay_fraction


def test_health_unavailable_and_recovery_are_neutral_context_changes() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW)
    degraded = filter_.apply_health_degraded("episode-1", NOW + timedelta(minutes=15))
    assert degraded.context == "degraded_asserted"
    assert degraded.health_warning is True
    assert contribution_count(filter_, "health_degraded") == 1

    unavailable_probability = filter_.apply_unavailable(
        NOW + timedelta(minutes=16)
    ).probability
    assert filter_.state.context == "unavailable"
    assert filter_.state.asserted_episode_id is None
    assert filter_.state.outward_context is None

    recovered = filter_.apply_health_recovered("episode-2", NOW + timedelta(minutes=16))
    assert recovered.probability == unavailable_probability
    assert recovered.health_warning is False
    asserted = filter_.apply_positive("episode-2", NOW + timedelta(minutes=16))
    assert asserted.context == "asserted"
    assert asserted.probability > recovered.probability


def test_stable_clear_recovers_unavailable_without_reopening_outward() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW)
    filter_.apply_unavailable(NOW + timedelta(seconds=1))

    unavailable = filter_.register_outward(
        "episode-1",
        NOW + timedelta(minutes=1),
        NOW + timedelta(seconds=2),
    )
    assert unavailable.context == "unavailable"
    assert unavailable.outward_context is None
    cleared = filter_.apply_stable_clear("episode-1", NOW + timedelta(seconds=3))
    assert cleared.context == "cleared_without_outward"
    assert contribution_count(filter_, "stable_clear") == 1


def test_accepted_clear_recovers_bootstrap_unavailable_to_prior() -> None:
    filter_ = ZoneBeliefFilter("zone", BELIEF_PROFILES["stay_pir"], NOW)
    filter_.apply_unavailable(NOW)

    recovered = filter_.apply_availability_clear(
        None,
        NOW + timedelta(seconds=1),
    )

    assert recovered.context == "cleared_without_outward"
    assert recovered.probability == pytest.approx(
        BELIEF_PROFILES["stay_pir"].prior_probability
    )
    assert recovered.contributions == ()
    assert filter_.apply_availability_clear(None, NOW + timedelta(seconds=1)) == (
        recovered
    )


def test_accepted_clear_recovers_existing_episode_without_absence_evidence() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW)
    filter_.apply_unavailable(NOW + timedelta(seconds=1))
    advanced = filter_.advance(NOW + timedelta(seconds=2))

    recovered = filter_.apply_availability_clear(
        "episode-1",
        NOW + timedelta(seconds=2),
    )

    assert recovered.context == "cleared_without_outward"
    assert recovered.probability == advanced.probability
    assert recovered.contributions[-1].kind == "availability_clear"
    assert recovered.contributions[-1].log_odds_delta == 0.0
    filter_.apply_unavailable(NOW + timedelta(seconds=3))
    with pytest.raises(ValueError, match="current episode"):
        filter_.apply_availability_clear(
            "other",
            NOW + timedelta(seconds=3),
        )


def test_stale_time_is_rejected_and_equal_time_operations_are_ordered() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW + timedelta(seconds=1))

    with pytest.raises(ValueError, match="earlier than"):
        filter_.advance(NOW)

    filter_.apply_health_degraded("episode-1", NOW + timedelta(seconds=1))
    filter_.apply_unavailable(NOW + timedelta(seconds=1))
    assert filter_.state.context == "unavailable"
    assert filter_.state.last_updated_at == NOW + timedelta(seconds=1)


def test_duplicate_health_unavailable_and_outward_operations_are_idempotent() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW)
    filter_.apply_health_degraded("episode-1", NOW + timedelta(seconds=1))
    assert (
        filter_.apply_health_degraded("episode-1", NOW + timedelta(seconds=1))
        == filter_.state
    )
    filter_.apply_unavailable(NOW + timedelta(seconds=2))
    assert filter_.apply_unavailable(NOW + timedelta(seconds=2)) == filter_.state
    assert (
        filter_.apply_health_recovered(
            "episode-2", NOW + timedelta(seconds=2)
        ).health_warning
        is False
    )
    assert (
        filter_.apply_health_recovered("episode-2", NOW + timedelta(seconds=2))
        == filter_.state
    )

    filter_.apply_positive("episode-2", NOW + timedelta(seconds=2))
    expiry = NOW + timedelta(minutes=1)
    filter_.register_outward("episode-2", expiry, NOW + timedelta(seconds=2))
    assert (
        filter_.register_outward(
            "episode-2", expiry - timedelta(seconds=1), NOW + timedelta(seconds=2)
        )
        == filter_.state
    )
    assert (
        filter_.register_outward(
            "episode-2", NOW + timedelta(seconds=2), NOW + timedelta(seconds=2)
        )
        == filter_.state
    )


def test_outward_expiry_while_asserted_preserves_asserted_context() -> None:
    filter_ = belief_filter()
    expiry = NOW + timedelta(seconds=10)
    filter_.apply_positive("episode-1", NOW)
    filter_.register_outward("episode-1", expiry, NOW)
    expired = filter_.advance(expiry)

    assert expired.context == "asserted"
    assert expired.outward_context is None
    assert contribution_count(filter_, "context_expired") == 1


def test_confirmed_return_supersedes_outward_without_changing_belief() -> None:
    filter_ = belief_filter()
    filter_.apply_positive("episode-1", NOW)
    filter_.register_outward(
        "episode-1",
        NOW + timedelta(minutes=1),
        NOW + timedelta(seconds=1),
    )
    filter_.advance(NOW + timedelta(seconds=2))
    before = filter_.state.probability

    returned = filter_.supersede_outward("episode-1", NOW + timedelta(seconds=2))

    assert returned.outward_context is None
    assert returned.probability == pytest.approx(before)
    assert contribution_count(filter_, "outward_superseded") == 1
    assert (
        filter_.supersede_outward("episode-1", NOW + timedelta(seconds=2))
        == returned
    )
    with pytest.raises(ValueError, match="match current episode"):
        filter_.supersede_outward("other", NOW + timedelta(seconds=2))

    cleared_filter = belief_filter()
    cleared_filter.apply_positive("episode-1", NOW)
    cleared_filter.register_outward(
        "episode-1",
        NOW + timedelta(minutes=1),
        NOW + timedelta(seconds=1),
    )
    cleared_filter.apply_stable_clear("episode-1", NOW + timedelta(seconds=2))
    cleared = cleared_filter.supersede_outward(
        "episode-1",
        NOW + timedelta(seconds=3),
    )
    assert cleared.context == "cleared_without_outward"


def test_beliefs_remain_finite_and_contributions_are_bounded_fifo() -> None:
    filter_ = belief_filter(contribution_limit=4)
    for generation in range(40):
        filter_.apply_positive(f"episode-{generation}", NOW)

    assert math.isfinite(filter_.state.log_odds)
    assert 0.0 <= filter_.state.probability <= 1.0
    assert len(filter_.state.contributions) == 4
    assert filter_.state.contributions[-1].episode_id == "episode-39"


def test_test_only_restore_validates_state_and_advances_once() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    original = belief_filter()
    original.apply_positive("episode-1", NOW)
    original.apply_stable_clear("episode-1", NOW + timedelta(seconds=10))
    snapshot = original.state
    restore_at = NOW + timedelta(minutes=5)

    restored = ZoneBeliefFilter.restore(profile, snapshot, restore_at=restore_at)
    direct = belief_filter()
    direct.apply_positive("episode-1", NOW)
    direct.apply_stable_clear("episode-1", NOW + timedelta(seconds=10))
    direct.advance(restore_at)
    assert restored.state == direct.state
    assert restored.advance(restore_at) == restored.state

    with pytest.raises(ValueError, match="profile"):
        ZoneBeliefFilter.restore(
            profile, replace(snapshot, profile_name="transition_fast")
        )
    with pytest.raises(ValueError, match="asserted context"):
        ZoneBeliefFilter.restore(
            profile,
            replace(
                snapshot,
                context="asserted",
                asserted_episode_id=None,
            ),
        )


def test_threshold_query_validation_and_long_refinement() -> None:
    filter_ = belief_filter()
    asserted = filter_.apply_positive("episode-1", NOW)
    incompatible = replace(asserted, profile_name="transition_fast")
    with pytest.raises(ValueError, match="profile"):
        filter_.threshold_crossed_at(incompatible, 0.5, NOW)
    with pytest.raises(ValueError, match="invalid"):
        filter_.threshold_crossed_at(asserted, -1.0, NOW)
    assert (
        filter_.threshold_crossed_at(asserted, 0.71, NOW + timedelta(days=36_500))
        is None
    )
    cleared = filter_.apply_stable_clear("episode-1", NOW)
    crossed = filter_.threshold_crossed_at(cleared, 0.3, NOW + timedelta(days=36_500))
    assert crossed is not None


def test_restore_rejects_every_invalid_cross_field_state() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    asserted_filter = belief_filter()
    asserted = asserted_filter.apply_positive("episode-1", NOW)
    clear_filter = belief_filter()
    clear_filter.apply_positive("episode-1", NOW)
    cleared = clear_filter.apply_stable_clear("episode-1", NOW)
    contribution = BeliefContribution(
        NOW,
        "local_positive",
        "cleared_without_outward",
        "asserted",
        1.0,
        "episode-1",
    )

    invalid_states = (
        (replace(asserted, log_odds=31.0), "numerical bound"),
        (
            replace(asserted, contributions=(contribution,) * 33),
            "configured bound",
        ),
        (
            replace(
                asserted,
                contributions=(replace(contribution, at=NOW + timedelta(seconds=1)),),
            ),
            "newer than",
        ),
        (replace(asserted, asserted_episode_id=None), "asserted context"),
        (
            replace(asserted, asserted_episode_id="other"),
            "asserted context",
        ),
        (replace(asserted, health_warning=True), "asserted context"),
        (
            replace(asserted, context="degraded_asserted", health_warning=False),
            "degraded context",
        ),
        (
            replace(
                asserted,
                context="degraded_asserted",
                asserted_episode_id="other",
                health_warning=True,
            ),
            "degraded context",
        ),
        (
            replace(cleared, asserted_episode_id="episode-1"),
            "retains an assertion",
        ),
        (replace(cleared, context="cleared_with_outward"), "context is missing"),
        (
            replace(
                asserted,
                outward_context=OutwardContext("other", NOW + timedelta(seconds=10)),
            ),
            "outward context",
        ),
        (
            replace(
                asserted,
                outward_context=OutwardContext("episode-1", NOW),
            ),
            "outward context",
        ),
        (
            replace(
                cleared,
                outward_context=OutwardContext(
                    "episode-1", NOW + timedelta(seconds=10)
                ),
            ),
            "outward context",
        ),
        (
            replace(
                cleared,
                context="unavailable",
                outward_context=OutwardContext(
                    "episode-1", NOW + timedelta(seconds=10)
                ),
            ),
            "outward context",
        ),
        (
            replace(cleared, generation_episode_id=None),
            "bootstrap belief",
        ),
    )
    for state, message in invalid_states:
        with pytest.raises(ValueError, match=message):
            ZoneBeliefFilter.restore(profile, state)

    restored_bootstrap = ZoneBeliefFilter.restore(profile, belief_filter().state)
    assert restored_bootstrap.state.generation_episode_id is None


def test_filter_rejects_invalid_inputs_and_impossible_operations() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    with pytest.raises(ValueError, match="Probability"):
        probability_to_log_odds(0.0)
    with pytest.raises(ValueError, match="Zone"):
        ZoneBeliefFilter("", profile, NOW)
    with pytest.raises(ValueError, match="Contribution limit"):
        ZoneBeliefFilter("zone", profile, NOW, contribution_limit=0)

    filter_ = belief_filter()
    with pytest.raises(ValueError, match="Episode ID"):
        filter_.apply_positive("", NOW)
    filter_.apply_positive("episode-1", NOW)
    with pytest.raises(ValueError, match="current source episode"):
        filter_.apply_stable_clear("episode-2", NOW)
    with pytest.raises(ValueError, match="asserted episode"):
        filter_.apply_health_degraded("episode-2", NOW)
    with pytest.raises(ValueError, match="finite"):
        ZoneBeliefFilter._bounded_log_odds(math.inf)  # noqa: SLF001


def test_belief_profile_and_contribution_validation() -> None:
    profile = BELIEF_PROFILES["stay_pir"]
    invalid_profiles: tuple[tuple[Callable[[], BeliefProfile], str], ...] = (
        (lambda: replace(profile, profile_id="unknown"), "Unknown belief profile"),
        (lambda: replace(profile, prior_probability=math.nan), "prior probability"),
        (
            lambda: replace(profile, positive_empty_likelihood=0.0),
            "likelihoods",
        ),
        (
            lambda: replace(
                profile,
                positive_occupied_likelihood=profile.positive_empty_likelihood,
            ),
            "favor occupied",
        ),
        (
            lambda: replace(
                profile,
                clear_occupied_likelihood=profile.clear_empty_likelihood,
            ),
            "favor empty",
        ),
    )
    for factory, message in invalid_profiles:
        with pytest.raises(ValueError, match=message):
            factory()

    with pytest.raises(ValueError, match="Unknown belief context"):
        profile.decay_for("transition")
    with pytest.raises(ValueError, match="contribution kind"):
        BeliefContribution(
            NOW,
            "unknown",
            "asserted",
            "asserted",
            0.0,
        )
    with pytest.raises(ValueError, match="context"):
        BeliefContribution(
            NOW,
            "elapsed_decay",
            "transition",
            "asserted",
            0.0,
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: DecayCalibration(0.0, timedelta(seconds=1)),
            "baseline probability",
        ),
        (
            lambda: DecayCalibration(0.5, timedelta(0)),
            "time constant",
        ),
        (
            lambda: OutwardContext("", NOW),
            "episode ID",
        ),
        (
            lambda: BeliefContribution(
                NOW,
                "elapsed_decay",
                "cleared_without_outward",
                "cleared_without_outward",
                math.inf,
            ),
            "finite",
        ),
    ],
)
def test_belief_types_reject_invalid_calibration_and_state(
    factory: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        assert callable(factory)
        factory()


def test_zone_belief_state_rejects_non_utc_and_unknown_context() -> None:
    base = belief_filter().state
    with pytest.raises(ValueError, match="UTC"):
        ZoneBeliefState(
            base.zone,
            base.profile_name,
            base.log_odds,
            base.last_updated_at.replace(tzinfo=None),
            base.context,
        )
    with pytest.raises(ValueError, match="context"):
        replace(base, context="transition")
    with pytest.raises(ValueError, match="zone"):
        replace(base, zone="")
    with pytest.raises(ValueError, match="profile"):
        replace(base, profile_name="unknown")
    with pytest.raises(ValueError, match="finite"):
        replace(base, log_odds=math.inf)
