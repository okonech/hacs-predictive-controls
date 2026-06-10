from __future__ import annotations

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_graph import ZoneGraph


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office_motion": {
                    "zone": "office",
                    "adjacent": ["hall_motion", "desk_motion"],
                },
                "desk_motion": {
                    "zone": "office",
                    "adjacent": ["office_motion"],
                },
                "hall_motion": {
                    "zone": "hall",
                    "adjacent": ["office_motion", "bath_motion"],
                },
                "bath_motion": {
                    "zone": "bathroom",
                    "adjacent": ["hall_motion"],
                },
                "garage_motion": {
                    "zone": "garage",
                    "adjacent": [],
                },
            }
        }
    )


def test_zone_graph_derives_bidirectional_zone_edges() -> None:
    graph = ZoneGraph.from_map(make_map())

    assert graph.zones() == ("bathroom", "garage", "hall", "office")
    assert graph.neighbors("office") == frozenset({"hall"})
    assert graph.neighbors("hall") == frozenset({"bathroom", "office"})
    assert graph.neighbors("missing") == frozenset()


def test_zone_graph_expands_movement_corridors_by_radius() -> None:
    graph = ZoneGraph.from_map(make_map())

    assert graph.movement_corridor(["office"]) == frozenset({"office", "hall"})
    assert graph.movement_corridor(["office"], radius=2) == frozenset(
        {"office", "hall", "bathroom"}
    )
    assert graph.movement_corridor(["missing"]) == frozenset({"missing"})


def test_zone_graph_distance_returns_shortest_known_path() -> None:
    graph = ZoneGraph.from_map(make_map())

    assert graph.distance("office", "office") == 0
    assert graph.distance("office", "bathroom") == 2
    assert graph.distance("office", "bathroom", max_depth=1) is None
    assert graph.distance("office", "garage") is None
    assert graph.distance("office", "missing") is None
