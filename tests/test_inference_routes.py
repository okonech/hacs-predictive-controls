from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.inference.routes import (
    RouteCandidateBuilder,
)
from custom_components.predictive_controls.inference.state_space import StateSpace
from custom_components.predictive_controls.inference.types import (
    EndpointToken,
    RouteEpisodeInterval,
)
from custom_components.predictive_controls.model import PredictiveMap

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "zone": "alpha",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": ["gate"],
                    "transition_seconds": {"gate": 3},
                },
                "gate": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.gate"},
                    "adjacent": ["source", "target", "direct"],
                    "transition_seconds": {"target": 5},
                },
                "direct": {
                    "zone": "hall",
                    "entities": {"motion": "binary_sensor.direct"},
                    "adjacent": ["gate", "target"],
                    "transition_seconds": {"target": 4},
                },
                "target": {
                    "zone": "omega",
                    "entities": {"motion": "binary_sensor.target"},
                    "adjacent": ["gate", "direct"],
                },
            }
        }
    )


def episode(
    node_id: str,
    zone: str,
    start: int,
    end: int,
    *,
    current_positive: bool = False,
    blocked_until: int | None = None,
) -> RouteEpisodeInterval:
    return RouteEpisodeInterval(
        node_id,
        zone,
        f"{node_id}-episode",
        NOW + timedelta(seconds=start),
        NOW + timedelta(seconds=end),
        (f"{node_id}-evidence",),
        current_positive,
        None if blocked_until is None else NOW + timedelta(seconds=blocked_until),
    )


def builder() -> RouteCandidateBuilder:
    predictive_map = make_map()
    return RouteCandidateBuilder(
        predictive_map,
        StateSpace(predictive_map.zones(), 2),
        direct_log_weight=0.0,
        censored_log_weight=-1.0,
    )


def test_builds_all_direct_and_censored_routes_with_exact_deadlines() -> None:
    alternatives = builder().build(
        EndpointToken("target-endpoint", "target", NOW + timedelta(seconds=4)),
        "omega",
        (
            episode("source", "alpha", 0, 2),
            episode("direct", "hall", 0, 2),
        ),
        (episode("gate", "hall", 1, 6, current_positive=True, blocked_until=20),),
    )

    assert tuple(alternative.disposition for alternative in alternatives) == (
        "censored_graph_path",
        "censored_graph_path",
        "graph_valid",
    )
    same_zone_censored, censored, direct = alternatives
    assert same_zone_censored.route_nodes == ("direct", "gate", "target")
    assert same_zone_censored.deadline == NOW + timedelta(seconds=11)
    assert censored.route_nodes == ("source", "gate", "target")
    assert censored.deadline == NOW + timedelta(seconds=10)
    assert censored.evidence_ids == (
        "gate-evidence",
        "source-evidence",
        "target-endpoint",
    )
    assert direct.route_nodes == ("direct", "target")
    assert direct.deadline == NOW + timedelta(seconds=6)


def test_one_microsecond_overflow_removes_direct_and_censored_candidates() -> None:
    source = episode("source", "alpha", 0, 0)
    gate = episode("gate", "hall", 3, 3, current_positive=True, blocked_until=20)
    direct = episode("direct", "hall", 0, 0)

    alternatives = builder().build(
        EndpointToken(
            "late-target",
            "target",
            NOW + timedelta(seconds=8, microseconds=1),
        ),
        "omega",
        (source, direct),
        (gate,),
    )

    assert alternatives == ()


@pytest.mark.parametrize(
    "gate",
    (
        episode("gate", "hall", 1, 6, blocked_until=20),
        episode("gate", "hall", 1, 6, current_positive=True),
        episode("gate", "hall", 1, 6, current_positive=True, blocked_until=3),
    ),
)
def test_censored_route_requires_open_endpoint_blocking_gate(
    gate: RouteEpisodeInterval,
) -> None:
    alternatives = builder().build(
        EndpointToken("target", "target", NOW + timedelta(seconds=4)),
        "omega",
        (episode("source", "alpha", 0, 2),),
        (gate,),
    )

    assert alternatives == ()


def test_route_episode_and_builder_validate_inputs() -> None:
    valid = episode("source", "alpha", 0, 2)
    with pytest.raises(ValueError, match="IDs are required"):
        replace(valid, node_id="")
    with pytest.raises(ValueError, match="must not exceed"):
        replace(valid, valid_from=valid.valid_until + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="evidence IDs"):
        replace(valid, evidence_ids=("",))
    with pytest.raises(ValueError, match="cannot precede"):
        replace(valid, endpoint_blocked_until=NOW - timedelta(microseconds=1))

    predictive_map = make_map()
    with pytest.raises(ValueError, match="zones must match"):
        RouteCandidateBuilder(
            predictive_map,
            StateSpace(("wrong",), 1),
            direct_log_weight=0.0,
            censored_log_weight=0.0,
        )
    with pytest.raises(ValueError, match="positive"):
        RouteCandidateBuilder(
            predictive_map,
            StateSpace(predictive_map.zones(), 1),
            direct_log_weight=0.0,
            censored_log_weight=0.0,
            default_edge_duration=timedelta(0),
        )
    with pytest.raises(ValueError, match="log weights"):
        RouteCandidateBuilder(
            predictive_map,
            StateSpace(predictive_map.zones(), 1),
            direct_log_weight=float("inf"),
            censored_log_weight=0.0,
        )

    route_builder = builder()
    target = EndpointToken("target", "target", NOW + timedelta(seconds=4))
    with pytest.raises(ValueError, match="target zone"):
        route_builder.build(target, "missing", ())
    with pytest.raises(ValueError, match="Route target"):
        route_builder.build(replace(target, node_id="missing"), "omega", ())
    with pytest.raises(ValueError, match="Route target"):
        route_builder.build(replace(target, node_id="source"), "omega", ())
    with pytest.raises(ValueError, match="source episode IDs"):
        route_builder.build(target, "omega", (valid, valid))
    gate = episode("gate", "hall", 1, 6, current_positive=True, blocked_until=20)
    with pytest.raises(ValueError, match="gate episode IDs"):
        route_builder.build(target, "omega", (valid,), (gate, gate))
    with pytest.raises(ValueError, match="Route source"):
        route_builder.build(target, "omega", (replace(valid, node_id="missing"),))
    with pytest.raises(ValueError, match="Route source"):
        route_builder.build(target, "omega", (replace(valid, zone="hall"),))
    with pytest.raises(ValueError, match="Route gate"):
        route_builder.build(
            target,
            "omega",
            (valid,),
            (replace(gate, node_id="missing"),),
        )
    assert route_builder.build(
        target,
        "omega",
        (episode("target", "omega", 0, 2),),
    ) == ()


def test_default_edge_duration_is_used_when_timing_is_absent() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "zone": "alpha",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": ["target"],
                },
                "target": {
                    "zone": "omega",
                    "entities": {"motion": "binary_sensor.target"},
                    "adjacent": ["source"],
                },
            }
        }
    )
    route_builder = RouteCandidateBuilder(
        predictive_map,
        StateSpace(predictive_map.zones(), 1),
        direct_log_weight=0.0,
        censored_log_weight=0.0,
    )
    alternatives = route_builder.build(
        EndpointToken("target-endpoint", "target", NOW + timedelta(seconds=10)),
        "omega",
        (episode("source", "alpha", 0, 1),),
    )

    assert len(alternatives) == 1
    assert alternatives[0].deadline == NOW + timedelta(seconds=31)
