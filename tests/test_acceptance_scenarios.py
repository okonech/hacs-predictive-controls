from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from occupancy_test_utils import (
    assert_count_conserved,
    assert_normalized,
    public_snapshot,
)

from custom_components.predictive_controls.automation_summary import (
    runtime_automation_summary,
)
from custom_components.predictive_controls.confidence import ZoneConfidenceEngine
from custom_components.predictive_controls.entity_registry import (
    expected_entity_unique_ids,
)
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_persistence import (
    restore_occupancy_state,
)
from custom_components.predictive_controls.occupancy_state import ZonePolicyState
from custom_components.predictive_controls.status import tracker_diagnostics_payload
from custom_components.predictive_controls.yaml_config import load_predictive_map

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
pytestmark = pytest.mark.scenario


def make_map(*, include_office: bool = True) -> PredictiveMap:
    nodes: dict[str, dict[str, object]] = {
        "hall": {
            "zone": "hall",
            "role": "transition_gate",
            "occupancy_behavior": "transient",
            "entities": {"motion": "binary_sensor.hall"},
            "adjacent": ["kitchen"],
        },
        "kitchen": {
            "zone": "kitchen",
            "entities": {"motion": "binary_sensor.kitchen"},
            "adjacent": ["hall"],
        },
        "garage": {
            "zone": "garage",
            "entities": {"motion": "binary_sensor.garage"},
            "adjacent": [],
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


def event(
    zone: str,
    seconds: int,
    *,
    state: str = "on",
    entity_id: str | None = None,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id=entity_id or f"binary_sensor.{zone}",
        node_id=zone,
        zone=zone,
        floor=None,
        role="transition_gate" if zone == "hall" else "room_occupancy",
        occupancy_behavior="transient" if zone == "hall" else "sustained",
        signal_type="motion",
        state=state,
        event_at=NOW + timedelta(seconds=seconds),
        reliability=0.9,
    )


def test_s16_count_increase_preserves_keep_on_without_activation() -> None:
    predictive_map = make_map()
    cold = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    cold.reconcile_expected_occupants(2, NOW, "cold-count-up")
    assert_count_conserved(cold, 2)
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)
    tracker.expire_transient_state(NOW + timedelta(seconds=10))

    tracker.reconcile_expected_occupants(2, NOW + timedelta(seconds=11), "count-up")
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert snapshot.zones["office"].keep_on
    assert all(
        decision.action != "activate" or not decision.accepted
        for decision in tracker.diagnostics.joint_policy_decisions
    )
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s17_count_decrease_does_not_select_a_room_for_release() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    office = event("office", 1)
    tracker.observe(office)
    tracker.observe(event("kitchen", 2))
    tracker.observe(event("office", 3))
    tracker.expire_transient_state(NOW + timedelta(seconds=10))

    tracker.reconcile_expected_occupants(1, NOW + timedelta(seconds=11), "count-down")
    snapshot = public_snapshot(tracker, predictive_map, office)
    strongest = max(
        tracker.diagnostics.joint_occupied_marginals,
        key=lambda zone: (tracker.diagnostics.joint_occupied_marginals[zone], zone),
    )

    assert snapshot.zones[strongest].keep_on
    assert sum(zone.keep_on for zone in snapshot.zones.values()) == 2
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert_count_conserved(tracker, 1)
    assert_normalized(tracker)


def test_s18_count_zero_clears_all_public_policy_and_predictions() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office = event("office", 1)
    tracker.observe(office)

    tracker.reconcile_expected_occupants(0, NOW + timedelta(seconds=2), "count-zero")
    snapshot = public_snapshot(tracker, predictive_map, office)

    assert all(
        not zone.activation_plausible
        and not zone.keep_on
        and not zone.prelight_plausible
        for zone in snapshot.zones.values()
    )
    assert tracker.diagnostics.expected_occupants == 0
    assert_count_conserved(tracker, 0)
    assert_normalized(tracker)


def test_s19_restart_clear_sensor_preserves_keep_on_without_bootstrap_activation() -> (
    None
):
    predictive_map = make_map()
    before = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office_on = event("office", 1)
    before.observe(office_on)
    payload = before.occupancy_store_data(
        NOW + timedelta(seconds=2),
        {"office": {"hall": 0.75}},
    )
    cast(list[dict[str, object]], payload["prediction_leases"]).append(
        {
            "path_key": ["hall", "office", "kitchen"],
            "target_zone": "kitchen",
            "probability": 0.8,
            "expires_at": (NOW + timedelta(seconds=5)).isoformat(),
            "reason": "expired during downtime",
        }
    )
    after = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    after.restore_joint_state(payload)

    before_bootstrap = public_snapshot(after, predictive_map, office_on)
    office_clear = event("office", 301, state="off")
    after.observe(office_clear, emit_activation=False)
    after_bootstrap = public_snapshot(after, predictive_map, office_clear)

    assert before_bootstrap.zones["office"].keep_on
    assert after_bootstrap.zones["office"].keep_on
    assert not after_bootstrap.zones["office"].activation_plausible
    assert not any(zone.prelight_plausible for zone in after_bootstrap.zones.values())
    assert after.diagnostics.joint_restore_status == "restored"
    assert after.diagnostics.joint_event_disposition == "accepted_clear"
    assert_count_conserved(after, 1)
    assert_normalized(after)


def test_s20_corrupt_restore_is_atomic_and_diagnostic() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    try:
        restore_occupancy_state({"schema_version": 99}, predictive_map, 1, NOW)
    except ValueError as exc:
        tracker.reject_joint_restore(str(exc))
    diagnostics = tracker.diagnostics
    summary = runtime_automation_summary(
        SimpleNamespace(
            map=predictive_map,
            zone_states=tracker.states,
            expected_occupants=1,
            confidence=tracker,
            last_occupancy_event=None,
        )
    )

    assert diagnostics.joint_restore_status == "rejected"
    assert diagnostics.joint_restore_reason == "unsupported occupancy storage schema"
    assert diagnostics.joint_posterior == ()
    assert tracker.joint_states == tracker.states
    assert not summary.keep_on_zones
    assert not summary.activation_plausible_zones


def test_s21_map_change_moves_removed_zone_to_unlocated_without_public_edge() -> None:
    old_map = make_map()
    before = ZoneConfidenceEngine(old_map, expected_occupants=1)
    before.observe(event("office", 1))
    payload = before.occupancy_store_data(NOW + timedelta(seconds=2), {})
    new_map = make_map(include_office=False)
    after = ZoneConfidenceEngine(new_map, expected_occupants=1)
    with pytest.raises(ValueError, match="map fingerprint"):
        after.restore_joint_state(payload)
    after.reject_joint_restore("Exact engine map fingerprint does not match")
    snapshot = public_snapshot(after, new_map, event("hall", 3, state="off"))

    assert "office" not in snapshot.zones
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert not any(zone.keep_on for zone in snapshot.zones.values())
    assert not any(zone.prelight_plausible for zone in snapshot.zones.values())
    assert after.diagnostics.joint_restore_status == "rejected"


def test_s26_prediction_only_restore_does_not_change_occupancy_or_policy() -> None:
    predictive_map = make_map()
    before = ZoneConfidenceEngine(predictive_map, expected_occupants=0)
    payload = before.occupancy_store_data(NOW, {})
    assert all(
        "last_event_id" not in state.explanation
        for state in before.joint_states.values()
    )
    cast(list[dict[str, object]], payload["prediction_leases"]).append(
        {
            "path_key": ["hall", "office", "kitchen"],
            "target_zone": "kitchen",
            "probability": 0.8,
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
            "reason": "restored forced continuation",
        }
    )
    after = ZoneConfidenceEngine(predictive_map, expected_occupants=0)
    after.restore_joint_state(payload)
    posterior_before = copy.deepcopy(after.diagnostics.joint_count_marginals)

    snapshot = public_snapshot(after, predictive_map, event("hall", 0))

    assert snapshot.zones["kitchen"].prelight_plausible
    assert after.joint_prediction_probabilities == {"kitchen": 0.8}
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert not any(zone.keep_on for zone in snapshot.zones.values())
    assert after.diagnostics.joint_count_marginals == posterior_before
    assert_count_conserved(after, 0)
    assert_normalized(after)


def test_s28_entity_contract_is_stable_for_joint_policy_projection() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    tracker.observe(event("office", 1))
    runtime = SimpleNamespace(
        map=predictive_map,
        zone_states=tracker.joint_states,
        expected_occupants=1,
        confidence=tracker,
        last_occupancy_event=event("office", 1),
    )
    summary = runtime_automation_summary(runtime)
    diagnostics_payload = tracker_diagnostics_payload(tracker.diagnostics)
    unique_ids = expected_entity_unique_ids("entry", predictive_map)

    assert {
        f"entry_{zone}_{suffix}"
        for zone in predictive_map.zones()
        for suffix in ("active", "prelight")
    } <= unique_ids
    assert not {
        f"entry_{zone}_{suffix}"
        for zone in predictive_map.zones()
        for suffix in ("activation_plausible", "keep_on", "prelight_plausible")
    } & unique_ids
    assert "entry_home_keep_on" not in unique_ids
    assert "entry_activation_plausible_zones" not in unique_ids
    assert "entry_keep_on_zones" not in unique_ids
    assert tuple(summary.zones) == predictive_map.zones()
    assert diagnostics_payload["joint"]["restore"] == {
        "status": "not_attempted",
        "reason": None,
    }
    assert diagnostics_payload["joint"]["occupied_marginals"]
    assert all(
        isinstance(zone.activation_plausible, bool)
        and isinstance(zone.keep_on, bool)
        and isinstance(zone.prelight_plausible, bool)
        for zone in summary.zones.values()
    )


def test_s29_elapsed_time_and_low_confidence_preserve_public_keep_on() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    hall_motion = event("hall", 0)
    tracker.observe(hall_motion)
    assert tracker.diagnostics.joint_occupied_marginals["office"] <= 0.10
    tracker._joint_policy.restore_states(  # noqa: SLF001
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW - timedelta(minutes=50)
                if zone == "office"
                else None,
            )
            for zone in predictive_map.zones()
        }
    )
    tracker.refresh_active(NOW)
    before = public_snapshot(tracker, predictive_map, hall_motion)

    tracker.expire_transient_state(NOW)

    after = public_snapshot(tracker, predictive_map, hall_motion)
    assert before.zones["office"].keep_on
    assert after.zones["office"].keep_on
    state = tracker.diagnostics.joint_policy_states["office"]
    assert state.last_release_cause is None
    assert not state.recovery_eligible


def test_s30_asserted_local_motion_preserves_keep_on_through_expiry() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    office_motion = event("office", 0)
    tracker.observe(office_motion)
    tracker._joint_policy.restore_states(  # noqa: SLF001
        {
            zone: ZonePolicyState(
                keep_on=zone == "office",
                last_trusted_at=NOW if zone == "office" else None,
            )
            for zone in predictive_map.zones()
        }
    )

    tracker.observe(event("kitchen", 15 * 60 + 1))
    after_observation = public_snapshot(tracker, predictive_map, office_motion)
    assert after_observation.zones["office"].keep_on

    tracker.expire_transient_state(NOW + timedelta(minutes=15, seconds=5))
    after_expiry = public_snapshot(tracker, predictive_map, office_motion)
    assert after_expiry.zones["office"].keep_on


def test_s31_sustained_room_confidence_survives_untracked_flaps() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    tracker.observe(event("hall", 0))
    office_motion = event("office", 14)
    tracker.observe(office_motion)
    arrival_confidence = tracker.diagnostics.joint_occupied_marginals["office"]
    assert arrival_confidence >= 0.60

    tracker.expire_transient_state(NOW + timedelta(minutes=22))
    sustained_confidence = tracker.diagnostics.joint_occupied_marginals["office"]
    assert sustained_confidence > arrival_confidence

    for offset in range(22 * 60 + 1, 22 * 60 + 61, 10):
        tracker.observe(event("garage", offset))
        tracker.observe(event("garage", offset + 1, state="off"))

    snapshot = public_snapshot(tracker, predictive_map, office_motion)
    assert snapshot.zones["office"].keep_on
    assert 0.0 <= tracker.diagnostics.joint_occupied_marginals["office"] <= 1.0


def _replay_sustained_outside_support_incident() -> tuple[
    ZoneConfidenceEngine,
    PredictiveMap,
    OccupancyEvent,
]:
    predictive_map = load_predictive_map(
        (
            Path(__file__).resolve().parents[1] / "benchmarks" / "reference-map.yaml"
        ).read_text()
    )
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)

    def incident_event(
        node_id: str,
        timestamp: str,
        *,
        state: str = "on",
    ) -> OccupancyEvent:
        node = predictive_map.nodes[node_id]
        entity_id = next(iter(node.entities.values()))
        return OccupancyEvent(
            entity_id=entity_id,
            node_id=node_id,
            zone=node.occupancy_zone,
            floor=node.floor,
            role=node.role,
            occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
            signal_type="motion",
            state=state,
            event_at=datetime.fromisoformat(timestamp),
            reliability=node.initial_weight,
        )

    events = (
        incident_event("guest_bedroom_sensor", "2026-07-17T01:05:58.991876+00:00"),
        incident_event("bedroom_entrance_sensor", "2026-07-17T01:59:11.413081+00:00"),
        incident_event(
            "bedroom_entrance_sensor",
            "2026-07-17T01:59:27.783545+00:00",
            state="off",
        ),
        incident_event("foyer_sensor", "2026-07-17T01:59:58.819700+00:00", state="off"),
        incident_event(
            "entrance_sensor", "2026-07-17T02:00:01.581357+00:00", state="off"
        ),
        incident_event(
            "dining_sensor", "2026-07-17T02:00:14.323969+00:00", state="off"
        ),
        incident_event("dining_sensor", "2026-07-17T02:00:20.972178+00:00"),
        incident_event("entrance_sensor", "2026-07-17T02:00:39.207809+00:00"),
        incident_event("foyer_sensor", "2026-07-17T02:00:42.426768+00:00"),
        incident_event("stairs_bottom_sensor", "2026-07-17T02:00:45.806936+00:00"),
        incident_event(
            "entrance_sensor", "2026-07-17T02:00:49.082902+00:00", state="off"
        ),
        incident_event(
            "kitchen_sensor", "2026-07-17T02:00:49.730563+00:00", state="off"
        ),
        incident_event(
            "dining_sensor", "2026-07-17T02:00:54.066688+00:00", state="off"
        ),
        incident_event(
            "stairs_bottom_sensor", "2026-07-17T02:00:56.934759+00:00", state="off"
        ),
        incident_event("foyer_sensor", "2026-07-17T02:00:59.924776+00:00", state="off"),
        incident_event("foyer_sensor", "2026-07-17T02:02:05.211889+00:00"),
        incident_event("stairs_top_sensor", "2026-07-17T02:02:06.584548+00:00"),
        incident_event("office_a_sensor", "2026-07-17T02:02:15.250020+00:00"),
        incident_event("foyer_sensor", "2026-07-17T02:02:17.056236+00:00", state="off"),
        incident_event(
            "stairs_bottom_sensor", "2026-07-17T02:02:19.843601+00:00", state="off"
        ),
        incident_event(
            "stairs_top_sensor", "2026-07-17T02:02:22.353553+00:00", state="off"
        ),
        incident_event("upstairs_bathroom_sensor", "2026-07-17T02:03:58.773865+00:00"),
        incident_event(
            "stairs_top_sensor", "2026-07-17T02:04:02.539437+00:00", state="off"
        ),
        incident_event(
            "office_a_sensor", "2026-07-17T02:04:11.997815+00:00", state="off"
        ),
        incident_event("stairs_top_sensor", "2026-07-17T02:05:07.792692+00:00"),
        incident_event("office_a_sensor", "2026-07-17T02:05:12.150973+00:00"),
        incident_event(
            "stairs_top_sensor",
            "2026-07-17T02:05:19.354734+00:00",
            state="off",
        ),
        incident_event(
            "upstairs_bathroom_sensor", "2026-07-17T02:05:25.355503+00:00", state="off"
        ),
    )
    for occupancy_event in events:
        tracker.observe(occupancy_event)
    tracker.expire_transient_state(
        datetime.fromisoformat("2026-07-17T02:24:50.232884+00:00")
    )
    return tracker, predictive_map, events[-1]


def test_inc_current_sustained_sensor_retains_high_occupancy_probability() -> None:
    tracker, _, _ = _replay_sustained_outside_support_incident()

    assert tracker.diagnostics.joint_occupied_marginals["guest_bedroom"] >= 0.95


def test_inc_two_supported_occupants_release_held_transition_zone() -> None:
    tracker, predictive_map, latest_event = _replay_sustained_outside_support_incident()
    snapshot = public_snapshot(tracker, predictive_map, latest_event)

    assert not snapshot.zones["bedroom_entrance"].keep_on


def test_inc_long_held_source_routes_through_hall_to_activate_target() -> None:
    predictive_map = load_predictive_map(
        (
            Path(__file__).resolve().parents[1] / "benchmarks" / "reference-map.yaml"
        ).read_text()
    )
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)

    def incident_event(
        node_id: str,
        timestamp: str,
    ) -> OccupancyEvent:
        node = predictive_map.nodes[node_id]
        return OccupancyEvent(
            entity_id=next(iter(node.entities.values())),
            node_id=node_id,
            zone=node.occupancy_zone,
            floor=node.floor,
            role=node.role,
            occupancy_behavior=predictive_map.occupancy_behavior_for_node(node),
            signal_type="motion",
            state="on",
            event_at=datetime.fromisoformat(timestamp),
            reliability=node.initial_weight,
        )

    tracker.observe(
        incident_event("office_a_sensor", "2026-07-17T16:19:09.673534+00:00")
    )
    tracker.observe(
        incident_event("living_right_sensor", "2026-07-17T17:08:01.840252+00:00")
    )
    tracker.observe(
        incident_event("stairs_top_sensor", "2026-07-17T17:26:01.623088+00:00")
    )
    tracker.observe(
        incident_event("dining_sensor", "2026-07-17T17:26:04.300759+00:00")
    )
    target_event = incident_event(
        "upstairs_bathroom_sensor",
        "2026-07-17T17:26:07.494721+00:00",
    )
    tracker.observe(target_event)

    snapshot = public_snapshot(tracker, predictive_map, target_event)
    target_decision = next(
        decision
        for decision in tracker.diagnostics.joint_policy_decisions
        if decision.zone == "upstairs_bathroom" and decision.action == "activate"
    )

    assert target_decision.gate_values["threshold"] == pytest.approx(0.8)
    assert snapshot.zones["upstairs_bathroom"].keep_on
