from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.profiles import (
    ENTRY_BOUNDARY,
    SHARED_PROFILES,
    STAY_PIR,
    STAY_PRESENCE,
    TRANSITION_FAST,
    build_physical_nodes,
    profile_assignment_for_node,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    PhysicalNode,
    SensorInput,
)

NOW = datetime(2026, 7, 18, 8, tzinfo=UTC)


def profile_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "hall": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                },
                "room_pir": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.room_motion"},
                },
                "room_presence": {
                    "role": "anchor_sensor",
                    "occupancy_behavior": "sticky",
                    "entities": {"presence": "binary_sensor.room_presence"},
                },
                "entry": {
                    "role": "entry_boundary",
                    "entities": {"contact": "binary_sensor.entry"},
                },
                "review": {
                    "role": "ambiguous_open_plan",
                    "occupancy_behavior": "ambiguous",
                    "entities": {"motion": "binary_sensor.review"},
                },
            }
        }
    )


def test_shared_profiles_have_independent_finite_timing() -> None:
    assert SHARED_PROFILES == {
        "entry_boundary": ENTRY_BOUNDARY,
        "stay_pir": STAY_PIR,
        "stay_presence": STAY_PRESENCE,
        "transition_fast": TRANSITION_FAST,
    }
    assert TRANSITION_FAST.hardware_hold_interval < STAY_PIR.hardware_hold_interval
    assert TRANSITION_FAST.assertion_trust_horizon < STAY_PIR.assertion_trust_horizon
    assert STAY_PIR.post_clear_residual < STAY_PRESENCE.post_clear_residual
    assert ENTRY_BOUNDARY.role == "entry"
    assert STAY_PIR.single_node_reacquisition is True
    assert STAY_PRESENCE.single_node_reacquisition is True
    assert TRANSITION_FAST.single_node_reacquisition is False
    assert ENTRY_BOUNDARY.single_node_reacquisition is False
    with pytest.raises(ValueError, match="must be boolean"):
        replace(STAY_PIR, single_node_reacquisition=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("node_id", "profile_name"),
    [
        ("hall", "transition_fast"),
        ("room_pir", "stay_pir"),
        ("room_presence", "stay_presence"),
        ("entry", "entry_boundary"),
    ],
)
def test_current_map_metadata_resolves_deterministically(
    node_id: str,
    profile_name: str,
) -> None:
    assignment = profile_assignment_for_node(profile_map(), node_id)

    assert assignment.node_id == node_id
    assert assignment.profile_name == profile_name
    assert assignment.error is None


def test_ambiguous_mapping_reports_blocking_error() -> None:
    assignment = profile_assignment_for_node(profile_map(), "review")

    assert assignment.profile_name is None
    assert assignment.error == (
        "Node 'review' has ambiguous occupancy metadata; target profile required"
    )

    result = build_physical_nodes(profile_map())
    assert [node.node_id for node in result.nodes] == [
        "entry",
        "hall",
        "room_pir",
        "room_presence",
    ]
    assert result.errors == (assignment.error,)

    unrecognized_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "contact_only": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"contact": "binary_sensor.contact_only"},
                }
            }
        }
    )
    unrecognized = profile_assignment_for_node(unrecognized_map, "contact_only")
    assert unrecognized.profile_name is None
    assert unrecognized.error is not None

    reviewed_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "review": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sustained",
                    "review_required": True,
                    "entities": {"motion": "binary_sensor.review"},
                }
            }
        }
    )
    reviewed = profile_assignment_for_node(reviewed_map, "review")
    assert reviewed.profile_name == "stay_pir"
    assert reviewed.error is None


def test_profile_validation_is_strict() -> None:
    with pytest.raises(ValueError, match="durations must be finite and non-negative"):
        replace(TRANSITION_FAST, stable_clear_window=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="Clear and trust durations must be positive"):
        replace(TRANSITION_FAST, stable_clear_window=timedelta(0))
    with pytest.raises(ValueError, match="must be shorter than stable clear"):
        replace(
            TRANSITION_FAST,
            burst_correlation_window=TRANSITION_FAST.stable_clear_window,
        )
    with pytest.raises(ValueError, match="post-clear residual must be finite and in"):
        replace(TRANSITION_FAST, post_clear_residual=float("nan"))
    with pytest.raises(ValueError, match="post-clear residual must be finite and in"):
        replace(TRANSITION_FAST, post_clear_residual=1.1)
    with pytest.raises(ValueError, match="identifiers must be non-empty"):
        replace(TRANSITION_FAST, profile_id="")


def test_physical_node_and_input_validation_is_strict() -> None:
    with pytest.raises(ValueError, match="identifiers must be non-empty"):
        PhysicalNode("", "room", ("binary_sensor.room",), "stay_pir")
    with pytest.raises(ValueError, match="at least one unique alias"):
        PhysicalNode(
            "room",
            "room",
            ("binary_sensor.room", "binary_sensor.room"),
            "stay_pir",
        )
    with pytest.raises(ValueError, match="aliases must be non-empty"):
        PhysicalNode("room", "room", ("",), "stay_pir")
    with pytest.raises(ValueError, match="Unknown sensor profile"):
        PhysicalNode("room", "room", ("binary_sensor.room",), "custom")
    with pytest.raises(ValueError, match="state must be"):
        SensorInput("binary_sensor.room", "maybe", NOW)
    with pytest.raises(ValueError, match="entity ID must be non-empty"):
        SensorInput("", "on", NOW)
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        SensorInput("binary_sensor.room", "on", NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="Unknown episode effect"):
        EpisodeEffect("room", "room", "episode", "invented", NOW)
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        EpisodeEffect(
            "room",
            "room",
            "episode",
            "positive",
            NOW.replace(tzinfo=None),
        )


def test_profile_mapping_reports_nodes_without_aliases() -> None:
    result = build_physical_nodes(
        PredictiveMap.from_mapping(
            {
                "nodes": {
                    "room": {
                        "role": "anchor_sensor",
                        "occupancy_behavior": "sticky",
                    }
                }
            }
        )
    )

    assert result.nodes == ()
    assert result.errors == (
        "Node 'room' has no physical entity aliases; target profile required",
    )


def test_contradictory_role_and_behavior_require_review() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "contradictory": {
                    "role": "anchor_sensor",
                    "occupancy_behavior": "transient",
                    "entities": {"presence": "binary_sensor.contradictory"},
                }
            }
        }
    )

    assignment = profile_assignment_for_node(predictive_map, "contradictory")

    assert assignment.profile_name is None
    assert assignment.error is not None


@pytest.mark.parametrize(
    ("behavior", "signal_type", "profile_name"),
    [
        ("sticky", "motion", "stay_pir"),
        ("sustained", "presence", "stay_presence"),
        ("sustained", "mmwave", "stay_presence"),
    ],
)
def test_generic_stay_roles_use_explicit_presence_metadata(
    behavior: str,
    signal_type: str,
    profile_name: str,
) -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "room": {
                    "role": "room_occupancy",
                    "occupancy_behavior": behavior,
                    "entities": {signal_type: f"binary_sensor.room_{signal_type}"},
                }
            }
        }
    )

    assert (
        profile_assignment_for_node(predictive_map, "room").profile_name
        == profile_name
    )


def test_zone_role_is_the_current_map_compatibility_role() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "zones": {"hall": {"role": "transition_gate"}},
            "nodes": {
                "hall_motion": {
                    "zone": "hall",
                    "entities": {"motion": "binary_sensor.hall_motion"},
                }
            },
        }
    )

    assert (
        profile_assignment_for_node(predictive_map, "hall_motion").profile_name
        == "transition_fast"
    )


@pytest.mark.parametrize(
    ("behavior", "signal_type", "profile_name"),
    [
        ("transient", "motion", "transition_fast"),
        ("sticky", "contact", "stay_presence"),
        ("sustained", "presence", "stay_presence"),
        ("sustained", "contact", None),
    ],
)
def test_unknown_roles_require_explicit_behavior_or_presence_signal(
    behavior: str,
    signal_type: str,
    profile_name: str | None,
) -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "legacy": {
                    "role": "legacy_custom",
                    "occupancy_behavior": behavior,
                    "entities": {signal_type: f"binary_sensor.legacy_{signal_type}"},
                }
            }
        }
    )

    assignment = profile_assignment_for_node(predictive_map, "legacy")

    assert assignment.profile_name == profile_name
    assert (assignment.error is None) == (profile_name is not None)
