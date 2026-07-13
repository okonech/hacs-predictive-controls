from __future__ import annotations

import copy
import math
from datetime import UTC, datetime, timedelta
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
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert all(
        sum(position.zone is None for position in hypothesis.key.positions) >= 1
        for hypothesis in tracker.diagnostics.joint_posterior
        if hypothesis.log_probability > -math.inf
    )
    assert_count_conserved(tracker, 2)
    assert_normalized(tracker)


def test_s17_count_decrease_keeps_strongest_supported_room() -> None:
    predictive_map = make_map()
    tracker = ZoneConfidenceEngine(predictive_map, expected_occupants=2)
    office = event("office", 1)
    tracker.observe(office)
    tracker.observe(event("kitchen", 2))
    tracker.observe(event("office", 3, entity_id="binary_sensor.office_presence"))
    tracker.expire_transient_state(NOW + timedelta(seconds=10))

    tracker.reconcile_expected_occupants(1, NOW + timedelta(seconds=11), "count-down")
    snapshot = public_snapshot(tracker, predictive_map, office)
    strongest = max(
        tracker.diagnostics.joint_occupied_marginals,
        key=lambda zone: (tracker.diagnostics.joint_occupied_marginals[zone], zone),
    )

    assert snapshot.zones[strongest].keep_on
    assert sum(zone.keep_on for zone in snapshot.zones.values()) == 1
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
    assert tracker.diagnostics.joint_posterior[0].key.positions == ()
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
    restart_at = NOW + timedelta(minutes=5)
    restored = restore_occupancy_state(payload, predictive_map, 1, restart_at)
    after = ZoneConfidenceEngine(predictive_map, expected_occupants=1)
    after.restore_joint_state(restored)

    before_bootstrap = public_snapshot(after, predictive_map, office_on)
    office_clear = event("office", 301, state="off")
    after.observe(office_clear, emit_activation=False)
    after_bootstrap = public_snapshot(after, predictive_map, office_clear)

    assert before_bootstrap.zones["office"].keep_on
    assert after_bootstrap.zones["office"].keep_on
    assert not after_bootstrap.zones["office"].activation_plausible
    assert not any(zone.prelight_plausible for zone in after_bootstrap.zones.values())
    assert after.diagnostics.joint_restore_status == "restored"
    assert after.diagnostics.joint_last_provenance is not None
    assert after.diagnostics.joint_last_provenance.disposition == "replacement"
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
    cast(list[dict[str, object]], payload["prediction_leases"]).append(
        {
            "path_key": ["hall", "office", "kitchen"],
            "target_zone": "kitchen",
            "probability": 0.8,
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
            "reason": "removed incoming zone",
        }
    )
    new_map = make_map(include_office=False)
    restored = restore_occupancy_state(payload, new_map, 1, NOW + timedelta(seconds=3))
    after = ZoneConfidenceEngine(new_map, expected_occupants=1)
    after.restore_joint_state(restored)
    snapshot = public_snapshot(after, new_map, event("hall", 3, state="off"))

    assert "office" not in snapshot.zones
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert not any(zone.keep_on for zone in snapshot.zones.values())
    assert not any(zone.prelight_plausible for zone in snapshot.zones.values())
    assert any(
        position.zone is None
        for hypothesis in after.diagnostics.joint_posterior
        for position in hypothesis.key.positions
    )
    assert after.diagnostics.joint_restore_status == "map_changed_rebuilt"


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
    restored = restore_occupancy_state(payload, predictive_map, 0, NOW)
    after = ZoneConfidenceEngine(predictive_map, expected_occupants=0)
    after.restore_joint_state(restored)
    posterior_before = copy.deepcopy(after.diagnostics.joint_posterior)

    snapshot = public_snapshot(after, predictive_map, event("hall", 0))

    assert snapshot.zones["kitchen"].prelight_plausible
    assert after.joint_prediction_probabilities == {"kitchen": 0.8}
    assert not any(zone.activation_plausible for zone in snapshot.zones.values())
    assert not any(zone.keep_on for zone in snapshot.zones.values())
    assert after.diagnostics.joint_posterior == posterior_before
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
        for suffix in ("activation_plausible", "keep_on", "prelight_plausible")
    } <= unique_ids
    assert tuple(summary.zones) == predictive_map.zones()
    assert diagnostics_payload["joint"]["restore"] == {
        "status": "not_attempted",
        "reason": None,
    }
    assert diagnostics_payload["joint"]["hypotheses"]
    assert all(
        isinstance(zone.activation_plausible, bool)
        and isinstance(zone.keep_on, bool)
        and isinstance(zone.prelight_plausible, bool)
        for zone in summary.zones.values()
    )


def test_s29_provisional_release_clears_public_keep_on_edge() -> None:
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
    before = public_snapshot(tracker, predictive_map, hall_motion)

    assert tracker.expire_transient_state(NOW)

    after = public_snapshot(tracker, predictive_map, hall_motion)
    assert before.zones["office"].keep_on
    assert not after.zones["office"].keep_on
    state = tracker.diagnostics.joint_policy_states["office"]
    assert state.last_release_cause == "provisional_false_off"
    assert state.recovery_eligible
