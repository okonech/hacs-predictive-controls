from __future__ import annotations

from datetime import timedelta

from custom_components.predictive_controls.occupancy_dwell import (
    DwellStats,
    DwellTimeModel,
)


def test_dwell_stats_learns_running_average() -> None:
    stats = DwellStats()

    first = stats.learn(timedelta(minutes=10))
    second = first.learn(timedelta(minutes=20))

    assert first.samples == 1
    assert first.average_seconds == 600
    assert second.samples == 2
    assert second.average_seconds == 900
    assert second.learn(timedelta(seconds=0)) == second


def test_dwell_model_uses_default_until_enough_samples() -> None:
    model = DwellTimeModel(minimum_samples=2)

    model.learn("office", timedelta(minutes=60))

    assert model.stats == {"office": DwellStats(samples=1, average_seconds=3600)}
    assert model.average_seconds("office") is None
    assert model.average_seconds("missing") is None
    assert model.passive_half_life_seconds("office", "sustained") == 300


def test_dwell_model_extends_passive_half_life_for_long_stays() -> None:
    model = DwellTimeModel(minimum_samples=2)

    model.learn("office", timedelta(minutes=60))
    model.learn("office", timedelta(minutes=120))

    assert model.average_seconds("office") == 5400
    assert model.passive_half_life_seconds("office", "sustained") == 2700
    assert model.payload() == {"office": {"samples": 2, "average_seconds": 5400.0}}
