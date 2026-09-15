"""Synthetic current-wire and retained-wrapper qualification, not runtime gap use.

Source: 2026-09-14 parent completion's two frozen missing-helper failures and
independent ready-plan probes. The wrapper must remain callable without runtime
use; a missing current displacement field must reject without losing live state.
No captured physical incident, altered scenario oracle, or new reader behavior.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.predictive_controls.events import event_from_entity
from custom_components.predictive_controls.occupancy_tracker import OccupancyTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput
from tests.gap_lifecycle_fixture import before_component_gap, prepare_gap_target
from tests.test_zone_model_engine import target_map
from tests.test_zone_model_persistence import (
    NOW,
    specimen_rows,
    specimen_snapshot,
    structural_payload,
)
from tests.test_zone_model_supported_gap_acquisition import gap_map

pytestmark = pytest.mark.target_model


def _at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _input(seconds: float, node: str, state: str) -> SensorInput:
    return SensorInput(f"binary_sensor.{node}", state, _at(seconds))


def _belief(payload: dict[str, object], zone: str) -> dict[str, object]:
    return next(row for row in specimen_rows(
        specimen_snapshot(payload)["belief_states"],
    ) if row["zone"] == zone)


def test_missing_path_displacement_preserves_populated_receiver() -> None:
    predictive_map = target_map()
    valid = structural_payload(predictive_map, (
        _input(0, "hall", "on"), _input(2, "room", "on"),
    ), outward=True)
    original = deepcopy(valid)
    hall = _belief(valid, "hall")
    outward = hall["outward_context"]
    assert isinstance(outward, dict)
    assert outward["source_episode_id"] is not None
    assert outward["valid_until"] == _at(92).isoformat()
    assert outward["qualified_until"] is None
    assert hall["qualified_departure_at"] is None
    assert hall["path_displaced_at"] is None
    accepted = restore_target_state(predictive_map, valid, _at(2))
    assert serialize_target_state(predictive_map, accepted) == valid

    malformed = deepcopy(valid)
    del _belief(malformed, "hall")["path_displaced_at"]
    repaired = deepcopy(malformed)
    _belief(repaired, "hall")["path_displaced_at"] = hall["path_displaced_at"]
    assert repaired == valid  # Exactly one deletion; all other records survive.
    incoming = deepcopy(malformed)
    message = "Target belief path displacement field is missing"
    with pytest.raises(ValueError, match=f"^{message}$"):
        restore_target_state(predictive_map, malformed, _at(4))

    donor = ZoneModelEngine(predictive_map, 2, NOW)
    donor.observe(_input(3, "room", "on"))
    donor.observe(_input(4, "hall", "on"))
    live_wire = serialize_target_state(predictive_map, donor)
    receiver, control = (
        OccupancyTracker(predictive_map), OccupancyTracker(predictive_map),
    )
    for tracker in (receiver, control):
        assert tracker.restore_state(live_wire, _at(4))
        assert tracker.policy_states["hall"].active
        assert tracker.config.expected_occupants == 2
    owner = receiver._engine
    assert owner is not None
    before = deepcopy(receiver.occupancy_store_data())
    states, config = receiver.states, receiver.config
    assert before != valid
    assert not receiver.restore_state(malformed, _at(4))
    assert receiver.diagnostics.restore_reason == message
    assert receiver._engine is owner
    assert receiver.config == config
    assert receiver.states == states
    assert receiver.occupancy_store_data() == before == control.occupancy_store_data()

    for seconds, node, state in (
        (5, "hall", "off"), (6, "room", "off"), (40, "room", "on"),
    ):
        event = event_from_entity(
            predictive_map, f"binary_sensor.{node}", state, _at(seconds),
        )
        assert event is not None
        assert receiver.observe(event) == control.observe(event)
    assert receiver.refresh_active(_at(45)) == control.refresh_active(_at(45))
    continued = receiver.occupancy_store_data()
    assert continued != before
    assert continued == control.occupancy_store_data()
    assert receiver.states == control.states
    restored = restore_target_state(predictive_map, continued, _at(45))
    assert serialize_target_state(predictive_map, restored) == continued
    assert malformed == incoming and valid == original


def test_retained_gap_wrapper_uses_real_owner_and_rejects_inverse() -> None:
    predictive_map = gap_map()
    inputs = tuple(_input(seconds, node, state) for seconds, node, state in (
        (0, "seed", "on"), (1, "bridge", "on"), (2, "stay", "on"),
        (10, "seed", "off"), (11, "bridge", "off"),
        (200, "source", "on"), (212, "target", "on"),
    ))
    components = before_component_gap(predictive_map, NOW)
    _, target, effect, authorization = prepare_gap_target(components, inputs[-1])
    assert authorization.reason == "supported_gap_acquisition"
    payload = structural_payload(predictive_map, inputs, count=2)
    owner = restore_target_state(predictive_map, payload, _at(212))
    source, = owner.snapshot.traversal_tokens
    assert source.path_node_ids == ("stay", "source")
    assert source.provenance_kind == "settled_adjacent_transfer"
    assert source.valid_until == _at(245)
    assert owner.snapshot.traversal_tokens == components.frontier.tokens
    assert owner.snapshot.anonymous_supports == components.supports.supports
    assert owner.snapshot.support_token_bindings == components.supports.bindings
    assert target == next(s for s in owner.snapshot.episode_states
                          if s.node_id == "target")
    assert owner._supported_gap_source(target, effect) == source
    assert owner._supported_gap_source(
        target, replace(effect, episode_id="mismatched-target-generation"),
    ) is None
    assert serialize_target_state(predictive_map, owner) == payload

    current = ZoneModelEngine(predictive_map, 2, NOW)
    for input_ in inputs[:-1]:
        current.observe(input_)
    result = current.observe(inputs[-1])
    assert not result.authorizations[0].authorized
    assert not next(p for p in current.snapshot.policy_states
                    if p.zone == "target").active
    current_wire = serialize_target_state(predictive_map, current)
    expected = deepcopy(current_wire)
    for field in (
        "traversal_tokens", "retained_traversal_tokens", "current_token_ids",
        "authorization_uses", "anonymous_supports", "support_token_bindings",
    ):
        specimen_snapshot(expected)[field] = specimen_snapshot(payload)[field]
    assert expected == payload  # Every non-donated current field remains exact.
    current = restore_target_state(predictive_map, current_wire, _at(212))
    assert not current.snapshot.traversal_tokens
    assert not current.snapshot.anonymous_supports
    assert target == next(s for s in current.snapshot.episode_states
                          if s.node_id == "target")
    assert current._supported_gap_source(target, effect) is None
    assert serialize_target_state(predictive_map, current) == current_wire
