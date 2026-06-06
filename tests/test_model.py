from __future__ import annotations

import pytest

from custom_components.predictive_controls.model import (
    PredictiveMap,
    PredictiveMapError,
)


def test_predictive_map_parses_nodes_and_entities() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "entry": {
                    "label": "Entry",
                    "entities": {"motion": "binary_sensor.entry"},
                    "adjacent": ["hall"],
                    "initial_weight": 2,
                },
                "hall": {"adjacent": ["entry"]},
            }
        }
    )

    assert predictive_map.nodes["entry"].label == "Entry"
    assert predictive_map.nodes["entry"].initial_weight == 2.0
    assert predictive_map.node_for_entity("binary_sensor.entry") == "entry"
    assert predictive_map.node_for_entity("binary_sensor.missing") is None
    assert predictive_map.entity_ids() == ("binary_sensor.entry",)
    assert predictive_map.neighbors("entry") == ("hall",)
    assert predictive_map.neighbors("missing") == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "Predictive map must be a mapping"),
        ({}, "Predictive map must define at least one node"),
        ({"nodes": {"entry": []}}, "Node 'entry' must be a mapping"),
        ({"nodes": {"entry": {"label": ""}}}, "label must be"),
        ({"nodes": {"entry": {"entities": []}}}, "entities must be"),
        ({"nodes": {"entry": {"adjacent": "hall"}}}, "adjacent must be"),
        ({"nodes": {"entry": {"initial_weight": "heavy"}}}, "must be numeric"),
        ({"nodes": {"entry": {"initial_weight": 0}}}, "must be positive"),
        ({"nodes": {"entry": {"adjacent": ["hall"]}}}, "not defined: hall"),
    ],
)
def test_predictive_map_rejects_invalid_config(raw: object, message: str) -> None:
    with pytest.raises(PredictiveMapError, match=message):
        PredictiveMap.from_mapping(raw)


def test_initial_reliability_alias_is_supported() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {"nodes": {"entry": {"initial_reliability": 0.75}}}
    )

    assert predictive_map.nodes["entry"].initial_weight == 0.75
