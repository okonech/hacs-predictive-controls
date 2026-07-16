from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.count_transition import (
    LogCountTransitionKernel,
)
from custom_components.predictive_controls.inference.episodes import (
    EpisodeEmission,
    ObservationEpisodes,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.model import PredictiveMap
from tests.oracle.exact_inference import (
    DecimalPosterior,
    decrease_count_decimal,
    enumerate_configurations,
    increase_count_decimal,
    observe_decimal,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
ZONES = ("alpha", "beta")
ALIASES = {
    "alpha": ("binary_sensor.alpha_motion", "binary_sensor.alpha_presence"),
    "beta": ("binary_sensor.beta_motion",),
}


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "alpha": {
                    "zone": "alpha",
                    "occupancy_behavior": "sustained",
                    "entities": {
                        "motion": ALIASES["alpha"][0],
                        "presence": ALIASES["alpha"][1],
                    },
                },
                "beta": {
                    "zone": "beta",
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": ALIASES["beta"][0]},
                },
            }
        }
    )


def make_event(
    node_id: str,
    entity_id: str,
    state: str,
    event_at: datetime,
    reliability: float,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id,
        node_id,
        node_id,
        "first_floor",
        "room_occupancy",
        "sustained" if node_id == "alpha" else "ambiguous",
        "motion",
        state,
        event_at,
        reliability,
    )


def full_support_posterior(
    occupants: int,
    random_source: random.Random,
) -> tuple[CompactLogPosterior, DecimalPosterior]:
    configurations = enumerate_configurations(len(ZONES) + 1, occupants)
    weights = {
        configuration: Decimal(str(random_source.uniform(0.01, 1.0)))
        for configuration in configurations
    }
    total = sum(weights.values(), Decimal(0))
    oracle = {
        configuration: weight / total for configuration, weight in weights.items()
    }
    space = StateSpace(ZONES, occupants)
    optimized = CompactLogPosterior(
        space,
        (
            math.log(float(oracle[configuration]))
            for configuration in space.configurations
        ),
    )
    return optimized, oracle


def apply_emissions(
    optimized: CompactLogPosterior,
    oracle: DecimalPosterior,
    emissions: tuple[EpisodeEmission, ...],
) -> tuple[CompactLogPosterior, DecimalPosterior]:
    for emission in emissions:
        zone_index = ZONES.index(emission.zone)
        optimized = optimized.apply_zone_likelihood(
            zone_index,
            empty_log_likelihood=emission.empty_log_likelihood,
            occupied_log_likelihood=emission.occupied_log_likelihood,
        )
        oracle = observe_decimal(
            oracle,
            zone_index,
            emission.empty_log_likelihood,
            emission.occupied_log_likelihood,
        )
    return optimized, oracle


def assert_parity(
    optimized: CompactLogPosterior,
    oracle: DecimalPosterior,
) -> None:
    actual = {
        configuration: math.exp(optimized[index])
        for index, configuration in enumerate(optimized.space.configurations)
    }
    assert actual.keys() == oracle.keys()
    assert tuple(actual.values()) == pytest.approx(
        tuple(float(oracle[configuration]) for configuration in actual),
        abs=2e-12,
    )
    assert optimized.normalization == pytest.approx(1.0, abs=1e-12)
    assert all(value != -math.inf for value in optimized)


@pytest.mark.parametrize("initial_occupants", range(6))
def test_randomized_episode_and_count_trace_matches_decimal_oracle(
    initial_occupants: int,
) -> None:
    random_source = random.Random(74_000 + initial_occupants)
    episodes = ObservationEpisodes(make_map())
    with localcontext() as context:
        context.prec = 80
        optimized, oracle = full_support_posterior(
            initial_occupants,
            random_source,
        )
        event_at = NOW
        for operation_index in range(240):
            action = operation_index % 12
            if action in {0, 1, 2, 3, 4, 5, 6}:
                event_at += timedelta(milliseconds=random_source.randint(1, 4_000))
                node_id = random_source.choice(tuple(ALIASES))
                entity_id = random_source.choice(ALIASES[node_id])
                state = random_source.choice(("on", "off", "unknown", "unavailable"))
                update = episodes.observe(
                    make_event(
                        node_id,
                        entity_id,
                        state,
                        event_at,
                        random_source.random(),
                    )
                )
                optimized, oracle = apply_emissions(
                    optimized,
                    oracle,
                    update.emissions,
                )
            elif action == 7:
                event_at += timedelta(seconds=random_source.randint(1, 12))
                for update in episodes.advance(event_at):
                    optimized, oracle = apply_emissions(
                        optimized,
                        oracle,
                        update.emissions,
                    )
            elif action == 8:
                event_at += timedelta(milliseconds=1)
                snapshot = tuple(
                    make_event(
                        node_id,
                        entity_id,
                        random_source.choice(("on", "off", "unknown", "unavailable")),
                        event_at,
                        random_source.random(),
                    )
                    for node_id, aliases in ALIASES.items()
                    for entity_id in aliases
                )
                for update in episodes.bootstrap(snapshot, cold_start=False):
                    optimized, oracle = apply_emissions(
                        optimized,
                        oracle,
                        update.emissions,
                    )
            elif action == 9:
                restored = ObservationEpisodes(make_map())
                restored.restore(episodes.serialize())
                assert restored.states == episodes.states
                episodes = restored
                optimized = CompactLogPosterior(
                    optimized.space,
                    tuple(optimized),
                )
            else:
                target_count = random_source.randrange(6)
                arrival_prior = tuple(
                    random_source.uniform(0.1, 1.0) for _ in range(len(ZONES) + 1)
                )
                exit_weights = tuple(
                    random_source.uniform(0.1, 1.0) for _ in range(len(ZONES) + 1)
                )
                while optimized.space.occupants < target_count:
                    optimized = LogCountTransitionKernel.increase(
                        optimized,
                        arrival_prior,
                    )
                    oracle = increase_count_decimal(
                        oracle,
                        tuple(Decimal(str(value)) for value in arrival_prior),
                    )
                while optimized.space.occupants > target_count:
                    optimized = LogCountTransitionKernel.decrease(
                        optimized,
                        exit_weights,
                    )
                    oracle = decrease_count_decimal(
                        oracle,
                        tuple(Decimal(str(value)) for value in exit_weights),
                    )
            assert_parity(optimized, oracle)


def test_same_zone_multiplicity_receives_one_binary_zone_factor() -> None:
    space = StateSpace(ZONES, 5)
    optimized = CompactLogPosterior.uniform(space).apply_zone_likelihood(
        0,
        empty_log_likelihood=math.log(0.1),
        occupied_log_likelihood=math.log(0.9),
    )

    one = math.exp(optimized[space.rank((1, 4, 0))])
    five = math.exp(optimized[space.rank((5, 0, 0))])
    empty = math.exp(optimized[space.rank((0, 5, 0))])

    assert one == pytest.approx(five, abs=1e-12)
    assert one / empty == pytest.approx(9.0, abs=1e-12)


def test_n5_extreme_inverse_trace_recovers_decimal_oracle_without_zeroing() -> None:
    random_source = random.Random(75_005)
    with localcontext() as context:
        context.prec = 120
        optimized, oracle = full_support_posterior(5, random_source)
        original = dict(oracle)
        forward = (math.log(1e-6), math.log1p(-1e-6))
        inverse = (forward[1], forward[0])
        for _ in range(250):
            optimized = optimized.apply_zone_likelihood(
                0,
                empty_log_likelihood=forward[0],
                occupied_log_likelihood=forward[1],
            )
            oracle = observe_decimal(oracle, 0, *forward)
        assert all(value != -math.inf for value in optimized)
        for _ in range(250):
            optimized = optimized.apply_zone_likelihood(
                0,
                empty_log_likelihood=inverse[0],
                occupied_log_likelihood=inverse[1],
            )
            oracle = observe_decimal(oracle, 0, *inverse)

        assert_parity(optimized, oracle)
        assert tuple(float(value) for value in oracle.values()) == pytest.approx(
            tuple(float(value) for value in original.values()),
            abs=2e-12,
        )
