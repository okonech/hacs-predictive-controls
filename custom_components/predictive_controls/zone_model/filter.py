"""Per-zone binary belief updates and deterministic context decay."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta

from .types import (
    BeliefContribution,
    BeliefProfile,
    OutwardContext,
    ZoneBeliefState,
    require_utc,
)

LOG_ODDS_LIMIT = 30.0
DEFAULT_CONTRIBUTION_LIMIT = 32
ARRIVAL_FROM_EMPTY_PROBABILITY = 0.75
ARRIVAL_FROM_OCCUPIED_PROBABILITY = 0.80


def probability_to_log_odds(probability: float) -> float:
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ValueError("Probability must be finite and in (0, 1)")
    return math.log(probability) - math.log1p(-probability)


class ZoneBeliefFilter:
    """Maintain one independently explainable graph-local zone belief."""

    def __init__(
        self,
        zone: str,
        profile: BeliefProfile,
        bootstrap_at: datetime,
        *,
        contribution_limit: int = DEFAULT_CONTRIBUTION_LIMIT,
    ) -> None:
        require_utc(bootstrap_at, "Belief bootstrap time")
        if not zone:
            raise ValueError("Zone must be non-empty")
        if contribution_limit <= 0:
            raise ValueError("Contribution limit must be positive")
        self._profile = profile
        self._contribution_limit = contribution_limit
        self._state = ZoneBeliefState(
            zone,
            profile.profile_id,
            probability_to_log_odds(profile.prior_probability),
            bootstrap_at,
            "cleared_without_outward",
        )

    @property
    def state(self) -> ZoneBeliefState:
        return self._state

    @classmethod
    def restore(
        cls,
        profile: BeliefProfile,
        state: ZoneBeliefState,
        *,
        restore_at: datetime | None = None,
        contribution_limit: int = DEFAULT_CONTRIBUTION_LIMIT,
    ) -> ZoneBeliefFilter:
        filter_ = cls(
            state.zone,
            profile,
            state.last_updated_at,
            contribution_limit=contribution_limit,
        )
        filter_._validate_state(state)
        filter_._state = state
        if restore_at is not None:
            filter_.advance(restore_at)
        return filter_

    def apply_positive(
        self, episode_id: str, at: datetime, reliability: float = 1.0
    ) -> ZoneBeliefState:
        self._require_episode_id(episode_id)
        self._advance_to(at)
        if self._state.generation_episode_id == episode_id:
            return self._state
        before = self._state
        self._state = replace(
            before,
            log_odds=self._apply_likelihood(
                self._profile.positive_empty_likelihood,
                self._profile.positive_occupied_likelihood,
                reliability,
            ),
            context="asserted",
            generation_episode_id=episode_id,
            asserted_episode_id=episode_id,
            outward_context=None,
            health_warning=False,
        )
        self._record("local_positive", before, episode_id)
        return self._state

    def apply_stable_clear(
        self, episode_id: str, at: datetime, reliability: float = 1.0
    ) -> ZoneBeliefState:
        self._require_episode_id(episode_id)
        self._advance_to(at)
        if self._state.generation_episode_id != episode_id:
            raise ValueError("Stable clear does not match the current source episode")
        if self._state.context in {
            "cleared_with_outward",
            "cleared_without_outward",
        }:
            return self._state
        before = self._state
        has_outward = (
            before.outward_context is not None
            and before.outward_context.valid_until > at
        )
        self._state = replace(
            before,
            log_odds=self._apply_likelihood(
                self._profile.clear_empty_likelihood,
                self._profile.clear_occupied_likelihood,
                reliability,
            ),
            context=(
                "cleared_with_outward" if has_outward else "cleared_without_outward"
            ),
            asserted_episode_id=None,
            outward_context=before.outward_context if has_outward else None,
        )
        self._record("stable_clear", before, episode_id)
        return self._state

    def apply_arrival_transition(
        self,
        episode_id: str,
        at: datetime,
        empty_to_occupied: float = ARRIVAL_FROM_EMPTY_PROBABILITY,
        occupied_to_occupied: float = ARRIVAL_FROM_OCCUPIED_PROBABILITY,
    ) -> ZoneBeliefState:
        """Apply one graph-supported occupancy-state transition."""

        self._require_episode_id(episode_id)
        self._advance_to(at)
        if not 0.0 < empty_to_occupied <= occupied_to_occupied < 1.0:
            raise ValueError("Arrival transition probabilities are invalid")
        if self._state.generation_episode_id != episode_id:
            raise ValueError("Arrival transition must match current episode")
        if any(
            item.kind == "arrival_transition"
            and item.episode_id == episode_id
            and item.at == at
            for item in self._state.contributions
        ):
            return self._state
        before = self._state
        probability = empty_to_occupied * (1.0 - before.probability) + (
            occupied_to_occupied * before.probability
        )
        self._state = replace(
            before,
            log_odds=self._bounded_log_odds(probability_to_log_odds(probability)),
        )
        self._record("arrival_transition", before, episode_id)
        return self._state

    def apply_health_degraded(self, episode_id: str, at: datetime) -> ZoneBeliefState:
        self._require_episode_id(episode_id)
        self._advance_to(at)
        if (
            self._state.generation_episode_id != episode_id
            or self._state.asserted_episode_id != episode_id
        ):
            raise ValueError("Health degradation does not match the asserted episode")
        if self._state.health_warning:
            return self._state
        before = self._state
        self._state = replace(
            before,
            context="degraded_asserted",
            health_warning=True,
        )
        self._record("health_degraded", before, episode_id)
        return self._state

    def apply_health_recovered(self, episode_id: str, at: datetime) -> ZoneBeliefState:
        self._require_episode_id(episode_id)
        self._advance_to(at)
        if not self._state.health_warning:
            return self._state
        before = self._state
        context = (
            "asserted"
            if before.asserted_episode_id == episode_id
            else before.context
        )
        self._state = replace(before, context=context, health_warning=False)
        self._record("health_recovered", before, episode_id)
        return self._state

    def apply_unavailable(self, at: datetime) -> ZoneBeliefState:
        self._advance_to(at)
        if self._state.context == "unavailable" and self._state.outward_context is None:
            return self._state
        before = self._state
        self._state = replace(
            before,
            context="unavailable",
            asserted_episode_id=None,
            outward_context=None,
        )
        self._record("unavailable", before, before.generation_episode_id)
        return self._state

    def apply_availability_clear(
        self,
        episode_id: str | None,
        at: datetime,
    ) -> ZoneBeliefState:
        """End unavailable context when an accepted clear state arrives."""

        self._advance_to(at)
        if self._state.context != "unavailable":
            return self._state
        if episode_id is not None:
            self._require_episode_id(episode_id)
            if self._state.generation_episode_id != episode_id:
                raise ValueError(
                    "Availability clear does not match the current episode"
                )
            before = self._state
            self._state = replace(
                before,
                context="cleared_without_outward",
                asserted_episode_id=None,
                outward_context=None,
                health_warning=False,
            )
            self._record("availability_clear", before, episode_id)
            return self._state
        self._state = replace(
            self._state,
            log_odds=probability_to_log_odds(self._profile.prior_probability),
            context="cleared_without_outward",
            asserted_episode_id=None,
            outward_context=None,
            health_warning=False,
            contributions=(),
        )
        return self._state

    def register_outward(
        self,
        source_episode_id: str,
        valid_until: datetime,
        at: datetime,
    ) -> ZoneBeliefState:
        self._require_episode_id(source_episode_id)
        require_utc(valid_until, "Outward context expiry")
        self._advance_to(at)
        if self._state.generation_episode_id != source_episode_id:
            raise ValueError(
                "Outward context does not match the current source episode"
            )
        if self._state.context == "unavailable" or valid_until <= at:
            return self._state
        current = self._state.outward_context
        if current is not None and current.valid_until >= valid_until:
            return self._state
        context = self._state.context
        if context == "cleared_without_outward":
            context = "cleared_with_outward"
        self._state = replace(
            self._state,
            context=context,
            outward_context=OutwardContext(source_episode_id, valid_until),
        )
        return self._state

    def supersede_outward(
        self,
        episode_id: str,
        at: datetime,
    ) -> ZoneBeliefState:
        self._require_episode_id(episode_id)
        self._advance_to(at)
        if self._state.generation_episode_id != episode_id:
            raise ValueError("Superseded outward context must match current episode")
        if self._state.outward_context is None:
            return self._state
        before = self._state
        context = before.context
        if context == "cleared_with_outward":
            context = "cleared_without_outward"
        self._state = replace(before, context=context, outward_context=None)
        self._record("outward_superseded", before, episode_id)
        return self._state

    def advance(self, now: datetime) -> ZoneBeliefState:
        self._advance_to(now)
        return self._state

    def threshold_crossed_at(
        self,
        start: ZoneBeliefState,
        threshold: float,
        end_at: datetime,
    ) -> datetime | None:
        """Return the deterministic first downward crossing in one decay interval."""

        require_utc(end_at, "Belief threshold frontier")
        if start.profile_name != self._profile.profile_id:
            raise ValueError("Belief threshold profile is incompatible")
        if not 0.0 <= threshold <= 1.0 or end_at < start.last_updated_at:
            raise ValueError("Belief threshold query is invalid")
        if start.probability <= threshold:
            return start.last_updated_at
        candidate = ZoneBeliefFilter.restore(self._profile, start)
        candidate.advance(end_at)
        if candidate.state.probability > threshold:
            return None
        low = start.last_updated_at
        high = end_at
        for _ in range(48):  # pragma: no branch - bounded numerical refinement
            if high - low <= timedelta(microseconds=1):
                break
            middle = low + (high - low) / 2
            probe = ZoneBeliefFilter.restore(self._profile, start)
            probe.advance(middle)
            if probe.state.probability <= threshold:
                high = middle
            else:
                low = middle
        return high

    def apply_empty_baseline(self, at: datetime) -> ZoneBeliefState:
        self._advance_to(at)
        self._state = replace(
            self._state,
            log_odds=probability_to_log_odds(self._profile.prior_probability),
            context="cleared_without_outward",
            generation_episode_id=None,
            asserted_episode_id=None,
            outward_context=None,
            health_warning=False,
            contributions=(),
        )
        return self._state

    def _advance_to(self, at: datetime) -> None:
        require_utc(at, "Belief update time")
        if at < self._state.last_updated_at:
            raise ValueError("Belief update time is earlier than the current frontier")
        if at == self._state.last_updated_at:
            return
        outward = self._state.outward_context
        if outward is not None and outward.valid_until <= at:
            self._decay_to(outward.valid_until)
            before = self._state
            context = before.context
            if context == "cleared_with_outward":
                context = "cleared_without_outward"
            self._state = replace(
                before,
                context=context,
                outward_context=None,
            )
            self._record("context_expired", before, outward.source_episode_id)
        if self._state.last_updated_at < at:
            self._decay_to(at)

    def _decay_to(self, at: datetime) -> None:
        before = self._state
        if (
            before.generation_episode_id is None
            and before.context == "cleared_without_outward"
        ):
            self._state = replace(before, last_updated_at=at)
            return
        elapsed = (at - before.last_updated_at).total_seconds()
        calibration = self._profile.decay_for(before.context)
        survival = math.exp(-elapsed / calibration.time_constant.total_seconds())
        probability = (
            calibration.baseline_probability
            + (before.probability - calibration.baseline_probability) * survival
        )
        self._state = replace(
            before,
            log_odds=self._bounded_log_odds(probability_to_log_odds(probability)),
            last_updated_at=at,
        )
        if before.generation_episode_id is None:
            return
        self._record("elapsed_decay", before, before.generation_episode_id)

    def _apply_likelihood(
        self, empty: float, occupied: float, reliability: float
    ) -> float:
        if not math.isfinite(reliability) or not 0 < reliability <= 1:
            raise ValueError("Observation reliability must be finite and in (0, 1]")
        return self._bounded_log_odds(
            self._state.log_odds
            + reliability * (math.log(occupied) - math.log(empty))
        )

    def _record(
        self,
        kind: str,
        before: ZoneBeliefState,
        episode_id: str | None,
    ) -> None:
        contribution = BeliefContribution(
            self._state.last_updated_at,
            kind,
            before.context,
            self._state.context,
            self._state.log_odds - before.log_odds,
            episode_id,
        )
        contributions = (*self._state.contributions, contribution)[
            -self._contribution_limit :
        ]
        self._state = replace(self._state, contributions=contributions)

    def _validate_state(self, state: ZoneBeliefState) -> None:
        if state.profile_name != self._profile.profile_id:
            raise ValueError(
                "Stored belief profile does not match the configured profile"
            )
        if abs(state.log_odds) > LOG_ODDS_LIMIT:
            raise ValueError("Stored belief log odds exceed the numerical bound")
        if len(state.contributions) > self._contribution_limit:
            raise ValueError("Stored belief contributions exceed the configured bound")
        if any(item.at > state.last_updated_at for item in state.contributions):
            raise ValueError("Stored belief contribution is newer than its state")
        if state.context == "asserted" and (
            state.asserted_episode_id is None
            or state.asserted_episode_id != state.generation_episode_id
            or state.health_warning
        ):
            raise ValueError("Stored asserted context is inconsistent")
        if state.context == "degraded_asserted" and (
            state.asserted_episode_id is None
            or state.asserted_episode_id != state.generation_episode_id
            or not state.health_warning
        ):
            raise ValueError("Stored degraded context is inconsistent")
        if (
            state.context
            in {
                "cleared_with_outward",
                "cleared_without_outward",
                "unavailable",
            }
            and state.asserted_episode_id is not None
        ):
            raise ValueError("Stored non-asserted context retains an assertion")
        if state.context == "cleared_with_outward" and state.outward_context is None:
            raise ValueError("Stored outward context is missing")
        if state.outward_context is not None and (
            state.outward_context.source_episode_id != state.generation_episode_id
            or state.outward_context.valid_until <= state.last_updated_at
            or state.context in {"cleared_without_outward", "unavailable"}
        ):
            raise ValueError("Stored outward context is inconsistent")
        if state.generation_episode_id is None:
            prior_log_odds = probability_to_log_odds(
                self._profile.prior_probability
            )
            invalid_reference = bool(
                state.asserted_episode_id is not None
                or state.outward_context is not None
                or state.health_warning
            )
            if state.context == "cleared_without_outward":
                invalid_context = bool(
                    state.contributions
                    or abs(state.log_odds - prior_log_odds) > 1e-12
                )
            elif state.context == "unavailable":
                unavailable = (
                    state.contributions[0]
                    if len(state.contributions) == 1
                    else None
                )
                calibration = self._profile.unavailable
                elapsed = (
                    0.0
                    if unavailable is None
                    else (state.last_updated_at - unavailable.at).total_seconds()
                )
                survival = math.exp(
                    -elapsed / calibration.time_constant.total_seconds()
                )
                expected_probability = calibration.baseline_probability + (
                    self._profile.prior_probability
                    - calibration.baseline_probability
                ) * survival
                expected_log_odds = probability_to_log_odds(expected_probability)
                invalid_context = bool(
                    unavailable is None
                    or unavailable.kind != "unavailable"
                    or unavailable.episode_id is not None
                    or unavailable.context_before != "cleared_without_outward"
                    or unavailable.context_after != "unavailable"
                    or abs(unavailable.log_odds_delta) > 1e-12
                    or abs(state.log_odds - expected_log_odds) > 1e-12
                )
            else:  # pragma: no cover - other contexts are rejected above
                invalid_context = True
            if invalid_reference or invalid_context:
                raise ValueError("Stored bootstrap belief state is inconsistent")

    @staticmethod
    def _bounded_log_odds(value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Belief log odds must remain finite")
        return min(LOG_ODDS_LIMIT, max(-LOG_ODDS_LIMIT, value))

    @staticmethod
    def _require_episode_id(episode_id: str) -> None:
        if not episode_id:
            raise ValueError("Episode ID must be non-empty")
