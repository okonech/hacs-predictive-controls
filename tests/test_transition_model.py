from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_state import (
    PositionState,
    canonical_hypothesis,
    initial_posterior,
    normalize_hypotheses,
)
from custom_components.predictive_controls.transition_model import TransitionModel

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"zone": "office", "adjacent": ["hall"]},
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "adjacent": ["office", "kitchen"],
                },
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
                "garage": {"zone": "garage", "adjacent": []},
            }
        }
    )


def test_transition_scenario_enumerates_unlocated_adjacent_and_missed_paths() -> None:
    model = TransitionModel(make_map())
    unlocated = model.propagate(initial_posterior(1, NOW), NOW, "office")
    assert {path.key.positions[0].zone for path in unlocated} == {None, "office"}
    assert sum(math.exp(path.log_probability) for path in unlocated) == pytest.approx(
        1.0
    )

    located = normalize_hypotheses(
        {canonical_hypothesis((PositionState("office"),)): 0.0},
        NOW,
    )
    paths = model.propagate(located, NOW, "kitchen")
    by_zone = {path.key.positions[0].zone: path for path in paths}

    assert set(by_zone) == {None, "office", "hall", "kitchen"}
    assert by_zone["hall"].movements == (("office", "hall"),)
    assert by_zone["kitchen"].movements == (("office", "kitchen"),)
    assert by_zone["hall"].key.positions[0].incoming_zone == "office"
    assert sum(math.exp(path.log_probability) for path in paths) == pytest.approx(1.0)


def test_transition_scenario_conserves_two_exchangeable_occupants() -> None:
    model = TransitionModel(make_map())
    posterior = normalize_hypotheses(
        {canonical_hypothesis((PositionState("office"), PositionState("hall"))): 0.0},
        NOW,
    )

    paths = model.propagate(posterior, NOW, "hall")

    assert paths
    assert all(len(path.key.positions) == 2 for path in paths)
    assert all(len(path.movements) <= 1 for path in paths)
    assert all(
        tuple(path.key.positions)
        == tuple(
            sorted(
                path.key.positions,
                key=lambda item: (
                    item.zone is None,
                    item.zone or "",
                    item.incoming_zone or "",
                    item.entered_at.isoformat() if item.entered_at else "",
                ),
            )
        )
        for path in paths
    )
    assert sum(math.exp(path.log_probability) for path in paths) == pytest.approx(1.0)
    assert any(
        [position.zone for position in path.key.positions] == ["hall", "hall"]
        for path in paths
    )


def test_transition_handles_empty_configuration_isolated_zone_and_validation() -> None:
    model = TransitionModel(make_map(), missed_movement_probability=0.0)
    empty = model.propagate(initial_posterior(0, NOW), NOW, "office")
    assert len(empty) == 1
    assert empty[0].key.positions == ()
    assert empty[0].log_probability == 0.0

    isolated = normalize_hypotheses(
        {canonical_hypothesis((PositionState("garage"),)): 0.0},
        NOW,
    )
    paths = model.propagate(isolated, NOW, "garage")
    assert {path.key.positions[0].zone for path in paths} == {None, "garage"}
    assert sum(math.exp(path.log_probability) for path in paths) == pytest.approx(1.0)

    for invalid in (-0.1, 1.0):
        with pytest.raises(ValueError, match=r"\[0, 1\)"):
            TransitionModel(make_map(), missed_movement_probability=invalid)
