from __future__ import annotations

import copy
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.automation_policy import (
    AutomationPolicy,
    PendingDeparture,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.joint_filter import JointOccupancyFilter
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.observation_model import EntityEvidence
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_persistence import (
    map_fingerprint,
    restore_occupancy_state,
    serialize_occupancy_state,
)
from custom_components.predictive_controls.occupancy_state import (
    PredictionLease,
    ReleaseCause,
)
from custom_components.predictive_controls.prediction import PredictionManager

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def make_map(include_office: bool = True) -> PredictiveMap:
    nodes = {
        "hall": {
            "zone": "hall",
            "entities": {"motion": "binary_sensor.hall"},
            "adjacent": ["kitchen"],
        },
        "kitchen": {
            "zone": "kitchen",
            "entities": {"motion": "binary_sensor.kitchen"},
            "adjacent": ["hall"],
        },
    }
    if include_office:
        nodes["office"] = {
            "zone": "office",
            "entities": {"motion": "binary_sensor.office"},
            "adjacent": ["hall"],
        }
        nodes["hall"]["adjacent"] = ["office", "kitchen"]
    return PredictiveMap.from_mapping({"nodes": nodes})


def event(zone: str, at: datetime) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor=None,
        role="room_occupancy",
        occupancy_behavior="sustained",
        signal_type="motion",
        state="on",
        event_at=at,
        reliability=0.9,
    )


@pytest.mark.scenario
def test_restart_scenario_round_trips_complete_inference_state() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    predictions = PredictionManager(predictive_map)
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    movement_update = occupancy_filter.observe(
        event("hall", NOW + timedelta(seconds=2))
    )
    policy.apply(movement_update)
    office_state = policy.states["office"]
    policy.restore_states(
        {
            **policy.states,
            "office": replace(
                office_state,
                keep_on=False,
                last_release_cause=ReleaseCause.PROVISIONAL_FALSE_OFF,
                recovery_eligible=True,
                reason="provisional false-off",
            ),
        }
    )
    predictions.restore_leases(
        (
            PredictionLease(
                ("hall", "office", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(minutes=1),
                "test lease",
            ),
        ),
        NOW,
    )
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        predictions.leases,
        occupancy_filter.observations.entity_states,
        {"office": {"hall": 2.5}},
        directional_contexts=occupancy_filter.directional_contexts,
        pending_departures=policy.pending_departures,
        update_sequence=occupancy_filter.update_sequence,
    )

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert [item.key for item in restored.posterior.hypotheses] == [
        item.key for item in occupancy_filter.posterior.hypotheses
    ]
    assert [item.log_probability for item in restored.posterior.hypotheses] == (
        pytest.approx(
            [item.log_probability for item in occupancy_filter.posterior.hypotheses]
        )
    )
    assert restored.policy_states == policy.states
    assert restored.pending_departures == policy.pending_departures
    assert set(restored.directional_contexts) == set(
        occupancy_filter.directional_contexts
    )
    for key, contexts in restored.directional_contexts.items():
        expected = occupancy_filter.directional_contexts[key]
        assert [replace(context, log_probability=0.0) for context in contexts] == [
            replace(context, log_probability=0.0) for context in expected
        ]
        assert [context.log_probability for context in contexts] == pytest.approx(
            [context.log_probability for context in expected]
        )
    assert restored.prediction_leases == predictions.leases
    assert restored.entity_states == occupancy_filter.observations.entity_states
    assert restored.transition_counts == {"office": {"hall": 2.5}}
    assert restored.map_compatible
    assert restored.restore_status == "restored"
    assert restored.update_sequence == 2
    assert payload["map_fingerprint"] == map_fingerprint(predictive_map)


@pytest.mark.scenario
def test_restart_scenario_expires_leases_and_reconciles_removed_zones() -> None:
    old_map = make_map()
    occupancy_filter = JointOccupancyFilter(old_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(old_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        old_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("office", "hall", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(seconds=2),
                "expires",
            ),
        ),
        occupancy_filter.observations.entity_states,
        {},
    )
    policy_payload = cast(dict[str, dict[str, object]], payload["policy"])
    posterior_payload = cast(list[dict[str, object]], payload["posterior"])
    first_positions = cast(list[dict[str, object]], posterior_payload[0]["positions"])
    last_positions = cast(list[dict[str, object]], posterior_payload[-1]["positions"])
    leases_payload = cast(list[dict[str, object]], payload["prediction_leases"])
    policy_payload["removed_zone"] = copy.deepcopy(policy_payload["office"])
    policy_payload["hall"]["activation_expires_at"] = (
        NOW + timedelta(seconds=2)
    ).isoformat()
    first_positions[0].update(
        zone="hall",
        incoming_zone="office",
    )
    last_positions[0].update(
        zone="office",
        incoming_zone=None,
    )
    leases_payload.append(
        {
            "path_key": ["hall", None, "office"],
            "target_zone": "office",
            "probability": 0.7,
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
            "reason": "removed path",
        }
    )

    restored = restore_occupancy_state(
        payload,
        make_map(include_office=False),
        1,
        NOW + timedelta(seconds=10),
    )

    assert not restored.map_compatible
    assert restored.restore_status == "map_changed_rebuilt"
    assert restored.prediction_leases == ()
    assert set(restored.policy_states) == {"hall", "kitchen"}
    assert restored.policy_states["hall"].activation_expires_at is None
    assert len(restored.posterior.hypotheses) == 3
    assert restored.posterior.hypotheses[0].key.positions[0].zone is None
    assert all(
        position.zone is None or position.zone in {"hall", "kitchen"}
        for hypothesis in restored.posterior.hypotheses
        for position in hypothesis.key.positions
    )


@pytest.mark.scenario
def test_schema_two_migrates_policy_and_valid_counts_only() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("hall", "office", "kitchen"),
                "kitchen",
                0.8,
                NOW + timedelta(minutes=1),
                "discarded lease",
            ),
        ),
        occupancy_filter.observations.entity_states,
        {"office": {"hall": 2.5, "missing": 9.0}},
    )
    payload["schema_version"] = 2
    for state in cast(dict[str, dict[str, object]], payload["policy"]).values():
        state.pop("last_release_cause")
        state.pop("recovery_eligible")

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.restore_status == "migrated_policy_only"
    assert restored.policy_states["office"].keep_on
    assert restored.transition_counts == {"office": {"hall": 2.5}}
    assert restored.prediction_leases == ()
    assert restored.entity_states == {}
    assert restored.pending_departures == {}
    assert restored.update_sequence == 0
    assert restored.posterior.hypotheses[0].key.positions[0].zone is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update(schema_version=99),
        lambda payload: payload.update(expected_occupants=2),
        lambda payload: payload.update(zone_index=[]),
        lambda payload: payload.update(update_sequence=-1),
        lambda payload: payload.update(updated_at="not-a-date"),
        lambda payload: payload.update(updated_at=None),
        lambda payload: payload.update(posterior=[]),
        lambda payload: payload["posterior"].append("bad"),
        lambda payload: payload["posterior"][0].update(probability=math.nan),
        lambda payload: payload["posterior"][0].update(positions=[]),
        lambda payload: payload["posterior"][0]["positions"].__setitem__(0, "bad"),
        lambda payload: payload["posterior"][0]["positions"][0].update(zone=3),
        lambda payload: payload["posterior"][0]["positions"][0].update(incoming_zone=3),
        lambda payload: payload["posterior"][0]["positions"][0].update(zone="attic"),
        lambda payload: payload["posterior"][0]["positions"][0].update(
            incoming_zone="attic"
        ),
        lambda payload: payload["posterior"][0].update(probability=0.5),
        lambda payload: payload.update(policy=[]),
        lambda payload: payload["policy"].update(office=[]),
        lambda payload: payload["policy"]["office"].update(keep_on="yes"),
        lambda payload: payload["policy"]["office"].update(evidence_ids=[3]),
        lambda payload: payload["policy"]["office"].update(blocked_episode_ids=[3]),
        lambda payload: payload["policy"]["office"].update(last_release_cause=3),
        lambda payload: payload["policy"]["office"].update(
            last_release_cause="not-a-cause"
        ),
        lambda payload: payload["policy"]["office"].update(recovery_eligible="yes"),
        lambda payload: payload["policy"]["office"].update(
            recovery_eligible=True,
            last_release_cause=None,
        ),
        lambda payload: payload.update(prediction_leases={}),
        lambda payload: payload["prediction_leases"].append("bad"),
        lambda payload: payload["prediction_leases"].append({}),
        lambda payload: payload["prediction_leases"].append(
            {
                "path_key": [None, None, "kitchen"],
                "target_zone": "kitchen",
                "probability": 0.8,
                "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
                "reason": "bad path",
            }
        ),
        lambda payload: payload.update(entity_states=[]),
        lambda payload: payload["entity_states"].update(bad=[]),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            state=3
        ),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            log_likelihood_by_count=[0.0]
        ),
        lambda payload: payload["entity_states"]["binary_sensor.office"].update(
            binding_signature={}
        ),
        lambda payload: payload.update(directional_contexts={}),
        lambda payload: payload["directional_contexts"].append("bad"),
        lambda payload: payload["directional_contexts"][0].update(contexts=[]),
        lambda payload: payload["directional_contexts"][0]["contexts"].__setitem__(
            0, "bad"
        ),
        lambda payload: payload["directional_contexts"][0]["contexts"][0].update(
            origin_zone="attic"
        ),
        lambda payload: payload["directional_contexts"].pop(),
        lambda payload: payload["directional_contexts"][0]["contexts"][0].update(
            probability=0.5
        ),
        lambda payload: payload.update(pending_departures=[]),
        lambda payload: payload["pending_departures"].update(attic={}),
        lambda payload: payload["pending_departures"].update(
            office={
                "current": "attic",
                "probability": 0.5,
                "nonadjacent": False,
                "evidence_ids": [],
            }
        ),
        lambda payload: payload.update(transition_counts=[]),
        lambda payload: payload["transition_counts"].update(bad=[]),
        lambda payload: payload["transition_counts"].update(bad={"target": -1}),
    ),
)
def test_corrupt_restart_state_is_rejected_atomically(mutate: object) -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    update = occupancy_filter.observe(event("office", NOW + timedelta(seconds=1)))
    policy.apply(update)
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        occupancy_filter.observations.entity_states,
        {},
    )
    corrupt = copy.deepcopy(payload)
    mutate(corrupt)  # type: ignore[operator]

    with pytest.raises(ValueError):
        restore_occupancy_state(corrupt, predictive_map, 1, NOW)


@pytest.mark.scenario
def test_restart_reconciles_stale_leases_departures_and_unmapped_evidence() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (
            PredictionLease(
                ("office", None, "attic"),
                "attic",
                0.8,
                NOW + timedelta(minutes=1),
                "stale zone",
            ),
            PredictionLease(
                ("office", "hall", "kitchen"),
                "kitchen",
                0.7,
                NOW,
                "expired",
            ),
        ),
        {
            "binary_sensor.unmapped": EntityEvidence(
                "on",
                (0.0, 0.0),
                NOW,
                NOW,
            )
        },
        {},
        pending_departures={
            "office": PendingDeparture(
                "office",
                "hall",
                0.6,
                False,
                ("office-hall",),
                "graph_valid",
            ),
            "kitchen": PendingDeparture(
                "kitchen",
                "hall",
                0.5,
                True,
                ("kitchen-hall",),
                "missed_movement",
            ),
        },
    )
    departures_payload = cast(
        dict[str, dict[str, object]],
        payload["pending_departures"],
    )
    for departure in departures_payload.values():
        departure.pop("disposition")

    restored = restore_occupancy_state(payload, predictive_map, 1, NOW)

    assert restored.prediction_leases == ()
    assert restored.entity_states["binary_sensor.unmapped"].state == "on"
    assert restored.pending_departures["office"].disposition == "graph_valid"
    assert restored.pending_departures["kitchen"].disposition == "missed_movement"


def test_restart_parser_requires_timezone_and_accepts_z_suffix() -> None:
    predictive_map = make_map()
    occupancy_filter = JointOccupancyFilter(predictive_map, 1, NOW)
    policy = AutomationPolicy(ZoneGraph.from_map(predictive_map))
    payload = serialize_occupancy_state(
        predictive_map,
        occupancy_filter.posterior,
        policy.states,
        (),
        {},
        {},
    )
    payload["updated_at"] = "2026-07-12T12:00:00Z"
    assert (
        restore_occupancy_state(payload, predictive_map, 1, NOW).posterior.updated_at
        == NOW
    )
    payload["updated_at"] = "2026-07-12T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        restore_occupancy_state(payload, predictive_map, 1, NOW)
