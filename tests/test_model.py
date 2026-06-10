from __future__ import annotations

import pytest

from custom_components.predictive_controls.model import (
    EntityBinding,
    PredictiveMap,
    PredictiveMapError,
    default_occupancy_behavior,
)


def test_predictive_map_parses_nodes_and_entities() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "zones": {
                "entry_hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                }
            },
            "nodes": {
                "entry": {
                    "label": "Entry",
                    "floor": "first_floor",
                    "zone": "entry_hall",
                    "role": "transition_gate",
                    "entities": {"motion": "binary_sensor.entry"},
                    "adjacent": ["hall"],
                    "initial_weight": 2,
                    "review_required": True,
                },
                "hall": {"adjacent": ["entry"]},
            }
        }
    )

    assert predictive_map.nodes["entry"].label == "Entry"
    assert predictive_map.nodes["entry"].floor == "first_floor"
    assert predictive_map.nodes["entry"].occupancy_zone == "entry_hall"
    assert predictive_map.nodes["entry"].role == "transition_gate"
    assert predictive_map.zone_configs["entry_hall"].occupancy_behavior == "transient"
    assert predictive_map.occupancy_behavior_for_node(
        predictive_map.nodes["entry"]
    ) == "transient"
    assert predictive_map.zone_occupancy_behavior("entry_hall") == "transient"
    assert predictive_map.zone_occupancy_behavior("missing") == "sustained"
    assert predictive_map.nodes["entry"].initial_weight == 2.0
    assert predictive_map.nodes["entry"].review_required
    assert predictive_map.node_for_entity("binary_sensor.entry") == "entry"
    assert predictive_map.entity_binding_for_entity(
        "binary_sensor.entry"
    ) == EntityBinding(node_id="entry", signal_type="motion")
    assert predictive_map.node_for_entity("binary_sensor.missing") is None
    assert predictive_map.entity_binding_for_entity("binary_sensor.missing") is None
    assert predictive_map.entity_ids() == ("binary_sensor.entry",)
    assert predictive_map.neighbors("entry") == ("hall",)
    assert predictive_map.neighbors("missing") == ()
    assert predictive_map.zones() == ("entry_hall", "hall")


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
        ({"nodes": {"entry": {"floor": 1}}}, "floor must be"),
        ({"nodes": {"entry": {"zone": 1}}}, "zone must be"),
        ({"nodes": {"entry": {"role": ""}}}, "role must be"),
        (
            {"nodes": {"entry": {"occupancy_behavior": "forever"}}},
            "occupancy_behavior must be one of",
        ),
        ({"zones": [], "nodes": {"entry": {}}}, "zones must be"),
        (
            {"zones": {"entry": []}, "nodes": {"entry": {}}},
            "Zone 'entry' must be a mapping",
        ),
        (
            {"zones": {"entry": {"role": ""}}, "nodes": {"entry": {}}},
            "Zone 'entry' role must be a string",
        ),
        (
            {
                "zones": {"entry": {"occupancy_behavior": "forever"}},
                "nodes": {"entry": {}},
            },
            "Zone 'entry' occupancy_behavior must be one of",
        ),
        (
            {"nodes": {"entry": {"review_required": "yes"}}},
            "review_required must be",
        ),
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


def test_empty_zone_metadata_is_supported() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {"zones": None, "nodes": {"entry": {}}}
    )

    assert predictive_map.zones() == ("entry",)


def test_default_occupancy_behavior_follows_role() -> None:
    assert default_occupancy_behavior("transition_gate") == "transient"
    assert default_occupancy_behavior("ambiguous_open_plan") == "ambiguous"
    assert default_occupancy_behavior("anchor_sensor") == "sticky"
    assert default_occupancy_behavior("room_occupancy") == "sustained"


def test_node_occupancy_behavior_can_override_zone() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "zones": {
                "office": {"role": "room_occupancy", "occupancy_behavior": "sustained"},
                "hall": {"role": "transition_gate"},
            },
            "nodes": {
                "office_motion": {
                    "zone": "office",
                    "occupancy_behavior": "sticky",
                },
                "hall_motion": {"zone": "hall"},
            },
        }
    )

    assert predictive_map.occupancy_behavior_for_node(
        predictive_map.nodes["office_motion"]
    ) == "sticky"
    assert predictive_map.zone_occupancy_behavior("office") == "sustained"
    assert predictive_map.zone_occupancy_behavior("hall") == "transient"


def test_zone_neighbors_follow_node_adjacency() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_motion": {
                    "zone": "office",
                    "adjacent": ["hall_motion", "desk_motion"],
                },
                "desk_motion": {"zone": "office", "adjacent": ["office_motion"]},
                "hall_motion": {
                    "zone": "hall",
                    "adjacent": ["office_motion", "bath_motion"],
                },
                "bath_motion": {
                    "zone": "bathroom",
                    "adjacent": ["hall_motion"],
                },
            }
        }
    )

    assert predictive_map.zone_neighbors("office") == ("hall",)
    assert predictive_map.zone_neighbors("hall") == ("bathroom", "office")
    assert predictive_map.zone_neighbors("missing") == ()
