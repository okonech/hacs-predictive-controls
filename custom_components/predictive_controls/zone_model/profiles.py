"""Shared target sensor profiles and legacy-map compatibility mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType

from ..model import PredictiveMap
from .types import BeliefProfile, DecayCalibration, PhysicalNode, SensorProfile

TRANSITION_FAST = SensorProfile(
    "transition_fast",
    "transition",
    burst_correlation_window=timedelta(seconds=3),
    stable_clear_window=timedelta(seconds=5),
    hardware_hold_interval=timedelta(seconds=15),
    assertion_trust_horizon=timedelta(seconds=60),
    post_clear_residual=0.1,
    traversal_context_window=timedelta(seconds=45),
    single_node_reacquisition=False,
)
STAY_PIR = SensorProfile(
    "stay_pir",
    "stay",
    burst_correlation_window=timedelta(seconds=3),
    stable_clear_window=timedelta(seconds=5),
    hardware_hold_interval=timedelta(seconds=30),
    assertion_trust_horizon=timedelta(seconds=900),
    post_clear_residual=0.65,
    traversal_context_window=timedelta(seconds=90),
    single_node_reacquisition=False,
)
STAY_PRESENCE = SensorProfile(
    "stay_presence",
    "stay",
    burst_correlation_window=timedelta(seconds=3),
    stable_clear_window=timedelta(seconds=10),
    hardware_hold_interval=timedelta(seconds=5),
    assertion_trust_horizon=timedelta(seconds=1800),
    post_clear_residual=0.8,
    traversal_context_window=timedelta(seconds=120),
    single_node_reacquisition=False,
)
ENTRY_BOUNDARY = SensorProfile(
    "entry_boundary",
    "entry",
    burst_correlation_window=timedelta(seconds=3),
    stable_clear_window=timedelta(seconds=5),
    hardware_hold_interval=timedelta(seconds=10),
    assertion_trust_horizon=timedelta(seconds=45),
    post_clear_residual=0.05,
    traversal_context_window=timedelta(seconds=30),
    single_node_reacquisition=False,
)
SHARED_PROFILES: Mapping[str, SensorProfile] = MappingProxyType(
    {
        profile.profile_id: profile
        for profile in (ENTRY_BOUNDARY, STAY_PIR, STAY_PRESENCE, TRANSITION_FAST)
    }
)

BELIEF_PROFILES: Mapping[str, BeliefProfile] = MappingProxyType(
    {
        "transition_fast": BeliefProfile(
            "transition_fast",
            prior_probability=0.05,
            positive_empty_likelihood=0.02,
            positive_occupied_likelihood=0.95,
            clear_empty_likelihood=0.8,
            clear_occupied_likelihood=0.4,
            asserted=DecayCalibration(0.15, timedelta(seconds=20)),
            cleared_without_outward=DecayCalibration(0.05, timedelta(seconds=30)),
            cleared_with_outward=DecayCalibration(0.05, timedelta(seconds=10)),
            degraded_asserted=DecayCalibration(0.05, timedelta(seconds=45)),
            unavailable=DecayCalibration(0.05, timedelta(seconds=30)),
        ),
        "stay_pir": BeliefProfile(
            "stay_pir",
            prior_probability=0.05,
            positive_empty_likelihood=0.02,
            positive_occupied_likelihood=0.98,
            clear_empty_likelihood=0.75,
            clear_occupied_likelihood=0.55,
            asserted=DecayCalibration(0.7, timedelta(minutes=10)),
            cleared_without_outward=DecayCalibration(0.05, timedelta(minutes=10)),
            cleared_with_outward=DecayCalibration(0.05, timedelta(seconds=30)),
            degraded_asserted=DecayCalibration(0.05, timedelta(minutes=2)),
            unavailable=DecayCalibration(0.05, timedelta(minutes=5)),
        ),
        "stay_presence": BeliefProfile(
            "stay_presence",
            prior_probability=0.05,
            positive_empty_likelihood=0.01,
            positive_occupied_likelihood=0.995,
            clear_empty_likelihood=0.7,
            clear_occupied_likelihood=0.58,
            asserted=DecayCalibration(0.8, timedelta(minutes=20)),
            cleared_without_outward=DecayCalibration(0.05, timedelta(minutes=45)),
            cleared_with_outward=DecayCalibration(0.05, timedelta(minutes=3)),
            degraded_asserted=DecayCalibration(0.05, timedelta(minutes=5)),
            unavailable=DecayCalibration(0.05, timedelta(minutes=10)),
        ),
        "entry_boundary": BeliefProfile(
            "entry_boundary",
            prior_probability=0.05,
            positive_empty_likelihood=0.03,
            positive_occupied_likelihood=0.95,
            clear_empty_likelihood=0.85,
            clear_occupied_likelihood=0.35,
            asserted=DecayCalibration(0.1, timedelta(seconds=15)),
            cleared_without_outward=DecayCalibration(0.03, timedelta(seconds=20)),
            cleared_with_outward=DecayCalibration(0.03, timedelta(seconds=8)),
            degraded_asserted=DecayCalibration(0.03, timedelta(seconds=30)),
            unavailable=DecayCalibration(0.03, timedelta(seconds=20)),
        ),
    }
)


@dataclass(frozen=True)
class ProfileAssignment:
    """Target profile resolution or a blocking configuration error."""

    node_id: str
    profile_name: str | None
    error: str | None


@dataclass(frozen=True)
class PhysicalNodeBuild:
    """Resolved target nodes and blocking configuration errors."""

    nodes: tuple[PhysicalNode, ...]
    errors: tuple[str, ...]


def profile_assignment_for_node(
    predictive_map: PredictiveMap,
    node_id: str,
) -> ProfileAssignment:
    node = predictive_map.nodes[node_id]
    behavior = predictive_map.occupancy_behavior_for_node(node)
    zone_config = predictive_map.zone_configs.get(node.occupancy_zone)
    role = (
        zone_config.role if zone_config is not None and zone_config.role else node.role
    ).lower()
    signal_types = {signal_type.lower() for signal_type in node.entities}
    entry_roles = {"boundary", "entry", "entry_boundary", "household_boundary"}
    stay_roles = {"room_occupancy", "stay", "subzone", "subzone_occupancy"}

    if node.review_required or behavior == "ambiguous":
        profile_name = None
    elif role in entry_roles and behavior in {"sustained", "transient"}:
        profile_name = "entry_boundary"
    elif role == "transition_gate" and behavior == "transient":
        profile_name = "transition_fast"
    elif role == "anchor_sensor" and behavior == "sticky":
        profile_name = "stay_presence"
    elif role in stay_roles and (
        behavior == "sticky" or signal_types & {"mmwave", "occupancy", "presence"}
    ):
        profile_name = "stay_presence"
    elif (
        role in stay_roles
        and behavior == "sustained"
        and signal_types & {"motion", "pir"}
    ):
        profile_name = "stay_pir"
    elif role not in entry_roles | stay_roles | {"anchor_sensor", "transition_gate"}:
        if behavior == "transient":
            profile_name = "transition_fast"
        elif behavior == "sticky" or signal_types & {
            "mmwave",
            "occupancy",
            "presence",
        }:
            profile_name = "stay_presence"
        else:
            profile_name = None
    else:
        profile_name = None

    if profile_name is not None:
        return ProfileAssignment(node_id, profile_name, None)
    return ProfileAssignment(
        node_id,
        None,
        f"Node {node_id!r} has ambiguous occupancy metadata; target profile required",
    )


def build_physical_nodes(predictive_map: PredictiveMap) -> PhysicalNodeBuild:
    nodes: list[PhysicalNode] = []
    errors: list[str] = []
    for node_id in sorted(predictive_map.nodes):
        node = predictive_map.nodes[node_id]
        assignment = profile_assignment_for_node(predictive_map, node_id)
        if assignment.profile_name is None:
            assert assignment.error is not None
            errors.append(assignment.error)
            continue
        aliases = tuple(sorted(node.entities.values()))
        if not aliases:
            errors.append(
                f"Node {node_id!r} has no physical entity aliases; "
                "target profile required"
            )
            continue
        nodes.append(
            PhysicalNode(
                node_id,
                node.occupancy_zone,
                aliases,
                assignment.profile_name,
            )
        )
    return PhysicalNodeBuild(tuple(nodes), tuple(errors))
