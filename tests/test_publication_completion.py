"""Synthetic completion regressions, not new physical-light incident reports.

Source: selected-path-completion, 2026-09-13 publication diagnoses. Protect real
entity metadata before the first dispatch, retry/acknowledgment, scoped immutable
summaries and facade mutation isolation. No learning or actuation is fabricated.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.automation_summary import (
    ZoneAutomationState,
    runtime_automation_summary,
)
from custom_components.predictive_controls.const import DISPATCH_UPDATE
from custom_components.predictive_controls.events import event_from_entity
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_tracker import OccupancyTracker
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    PolicyEvent,
    SensorInput,
    TraversalAuthorization,
    ZoneModelResult,
)
from tests.runtime_replay import RuntimeReplay, RuntimeScenario

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def model() -> PredictiveMap:
    adjacent = {"a": ["b"], "b": ["a", "c"], "c": ["b", "t"], "t": ["c"]}
    return PredictiveMap.from_mapping({"nodes": {
        node: {"zone": node, "entities": {"motion": f"binary_sensor.{node}"},
               "adjacent": neighbors}
        for node, neighbors in adjacent.items()
    }})


def prepared(scenario: RuntimeScenario) -> RuntimeReplay:
    live = scenario.create(model(), 2)
    for _ in range(5):
        assert live.runtime.chain.observe("c", "t")
    live.send("binary_sensor.a", "on", NOW)
    live.send("binary_sensor.b", "on", NOW + timedelta(seconds=1))
    return live


def test_attributes_use_one_zone_not_all_map_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PERF005: a real entity read must not construct every ZoneState."""
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        calls: list[str] = []
        original = OccupancyTracker._zone_state

        def projected(self: OccupancyTracker, zone: str, *args: Any) -> Any:
            calls.append(zone)
            return original(self, zone, *args)

        monkeypatch.setattr(OccupancyTracker, "_zone_state", projected)
        attributes = live.entities["b"].extra_state_attributes
        assert attributes["reason"] == "acquired"
        assert calls == ["b"]


@pytest.mark.parametrize("failure_index", (None, 0, 1))
def test_complete_metadata_before_first_dispatch_and_after_subscriber_failure(
    failure_index: int | None,
) -> None:
    """PERF005/PRED008: every entity sees the complete committed operation."""
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        tracker = live.runtime.confidence
        counts = deepcopy(live.runtime.chain.counts)
        captured: list[tuple[dict[str, object], tuple[PolicyDecision, ...]]] = []
        first_write = len(live.writes_for("t"))
        listeners = live.hass.dispatchers[DISPATCH_UPDATE]

        def inspect() -> None:
            attributes = deepcopy(live.entities["t"].extra_state_attributes)
            captured.append((attributes, tracker.policy_decisions))
            assert live.runtime.chain.counts == counts
            assert not tracker._engine._pending_prediction_learning
            if len(captured) - 1 == failure_index:
                raise RuntimeError("subscriber failed")

        listeners.insert(0, inspect)
        try:
            if failure_index is None:
                live.send("binary_sensor.c", "on", NOW + timedelta(seconds=2))
            else:
                with pytest.raises(RuntimeError, match="subscriber failed"):
                    live.send("binary_sensor.c", "on", NOW + timedelta(seconds=2))
        finally:
            listeners.remove(inspect)
        assert captured
        assert live.runtime._automation_summary_cache == {}
        final = live.entities["t"].extra_state_attributes
        assert final["evidence_ids"]
        assert final["phase"] == "predicted"
        for attributes, decisions in captured:
            assert attributes == final
            assert {d.zone for d in decisions} == set(model().zones())
        assert tracker.policy_decisions == captured[0][1]
        assert tracker._publishing_snapshot is None
        assert live.runtime.chain.counts == counts
        # A failed subscriber may prevent the first write; explicit publication
        # must recover using committed metadata, not rely on _record_result return.
        live.runtime._publish_update()
        writes = live.writes_for("t")[first_write:]
        assert len(writes) == 1
        assert writes[0].active and writes[0].attributes == final


def test_later_operation_removes_old_evidence_without_suppressing_updates() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        live.send("binary_sensor.c", "on", NOW + timedelta(seconds=2))
        original = live.writes_for("t")[-1].attributes
        assert original["evidence_ids"]
        count = len(live.writes_for("t"))
        live.send("binary_sensor.a", "on", NOW + timedelta(seconds=3))
        assert live.entities["t"].extra_state_attributes["evidence_ids"] == []
        assert len(live.writes_for("t")) == count + 1
        assert original["evidence_ids"]
        live.runtime._publish_update()
        assert len(live.writes_for("t")) == count + 1


def test_failed_entity_write_retries_identical_signature() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        entity = live.entities["t"]
        original = entity.async_write_ha_state
        attempts = 0

        def fail_once() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("write failed")
            original()

        scenario.patch.setattr(entity, "async_write_ha_state", fail_once)
        with pytest.raises(RuntimeError, match="write failed"):
            live.send("binary_sensor.c", "on", NOW + timedelta(seconds=2))
        live.runtime._publish_update()
        assert attempts == 2
        assert live.view().active("t")
        live.runtime._publish_update()
        assert attempts == 2


@pytest.mark.parametrize("outer_fails", (False, True))
def test_reentrant_successful_newer_acknowledgment_is_not_overwritten(
    outer_fails: bool,
) -> None:
    """Successful nested HA writes win even if the older write then fails."""
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        entity = live.entities["b"]
        original = entity.async_write_ha_state
        old = entity._state_signature()
        entity._published_signature = None
        calls = 0

        def reenter() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                # Transport-only signature input, not a model/evidence mutation.
                scenario.patch.setattr(entity, "_state_signature", lambda: ("new",))
                entity._handle_update()
                if outer_fails:
                    raise RuntimeError("older write failed")
            original()

        scenario.patch.setattr(entity, "async_write_ha_state", reenter)
        if outer_fails:
            with pytest.raises(RuntimeError, match="older write failed"):
                entity._handle_update()
        else:
            entity._handle_update()
        assert old != ("new",)
        assert entity._published_signature == ("new",)
        entity._handle_update()
        assert calls == 2


@pytest.mark.parametrize("inner_fails", (False, True))
def test_nested_dispatch_restores_outer_view_and_discards_root_cache(
    inner_fails: bool,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = scenario.create(model(), 2)
        tracker = live.runtime.confidence
        earlier = tracker._current_snapshot()
        live.send("binary_sensor.a", "on", NOW)
        live.send("binary_sensor.b", "on", NOW + timedelta(seconds=1))
        outer_attributes: dict[str, object] = {}
        depth = 0

        def subscriber() -> None:
            nonlocal depth, outer_attributes
            summary = runtime_automation_summary(live.runtime)
            if depth:
                assert not summary.zones["b"].keep_on
                if inner_fails:
                    raise RuntimeError("inner failed")
                return
            assert summary.zones["b"].keep_on
            outer_attributes = live.entities["b"].extra_state_attributes
            depth += 1
            try:
                def invoke() -> None:
                    tracker._publish_with_snapshot(
                        earlier, live.runtime._dispatch_update,
                    )

                if inner_fails:
                    with pytest.raises(RuntimeError, match="inner failed"):
                        invoke()
                else:
                    invoke()
            finally:
                depth -= 1
            assert runtime_automation_summary(live.runtime) is summary
            assert live.entities["b"].extra_state_attributes == outer_attributes

        scenario.patch.setattr(scenario.runtime_module, "async_dispatcher_send",
                               lambda *_: subscriber())
        live.runtime._publish_update()
        assert tracker._publishing_snapshot is None
        assert live.runtime._automation_summary_cache == {}
        assert outer_attributes["reason"] == "acquired"


def test_summary_zone_map_and_attribute_containers_are_isolated() -> None:
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        summary = runtime_automation_summary(live.runtime)
        with pytest.raises(TypeError):
            cast(MutableMapping[str, ZoneAutomationState], summary.zones)["b"] = (
                summary.zones["a"]
            )
        first = live.entities["b"].extra_state_attributes
        evidence = first["evidence_ids"]
        assert isinstance(evidence, list) and evidence
        evidence.clear()
        assert live.entities["b"].extra_state_attributes["evidence_ids"]


@pytest.mark.parametrize("operation", (
    "count", "unsupported", "restore", "bootstrap", "observe", "advance", "expire",
))
@pytest.mark.parametrize("fast", (False, True))
def test_facade_mutations_reject_before_any_change_during_publication(
    operation: str, fast: bool,
) -> None:
    with RuntimeScenario(NOW) as scenario:
        live = prepared(scenario)
        tracker = live.runtime.confidence
        payload = live.checkpoint()
        at = NOW + timedelta(seconds=2)
        event = event_from_entity(live.map, "binary_sensor.t", "on", at)
        assert event is not None
        operations: dict[str, Callable[[], object]] = {
            "count": lambda: tracker.reconcile_expected_occupants(0, at),
            "unsupported": lambda: tracker.reject_unsupported_count(3, at),
            "restore": lambda: tracker.restore_state(payload, at),
            "bootstrap": lambda: tracker.bootstrap_state((), cold_start=True),
            "observe": lambda: tracker.observe(event),
            "advance": lambda: tracker.refresh_active(at),
            "expire": lambda: tracker.expire_transient_state(at),
        }
        calls = 0

        def subscriber() -> None:
            nonlocal calls
            calls += 1
            engine = tracker._engine
            before = tracker._current_snapshot()
            config = tracker.config
            requested = tracker.requested_expected_occupants
            with pytest.raises(ValueError, match="publication|callback"):
                operations[operation]()
            assert tracker._engine is engine and tracker.config == config
            assert tracker.requested_expected_occupants == requested
            assert tracker._current_snapshot() == before

        scenario.patch.setattr(scenario.runtime_module, "async_dispatcher_send",
                               lambda *_: subscriber())
        if fast:
            live.send("binary_sensor.c", "on", at)
        else:
            live.runtime._publish_update()
        assert calls


@pytest.mark.parametrize("fail_result", (False, True))
def test_optional_result_callback_is_complete_guarded_and_edge_compatible(
    fail_result: bool,
) -> None:
    engine = ZoneModelEngine(model(), 2, NOW)
    engine.observe(SensorInput("binary_sensor.a", "on", NOW))
    result_seen: list[ZoneModelResult] = []
    edges: list[PolicyEvent] = []

    def complete(result: ZoneModelResult) -> None:
        result_seen.append(result)
        assert result.snapshot == engine.snapshot
        with pytest.raises(ValueError, match="callback"):
            engine.advance(result.snapshot.updated_at)
        if fail_result:
            raise RuntimeError("result failed")

    def edge(event: PolicyEvent, decision: PolicyDecision,
             authorization: TraversalAuthorization | None) -> None:
        assert result_seen and event in result_seen[0].policy_events
        assert decision in result_seen[0].policy_decisions
        assert authorization in result_seen[0].authorizations
        edges.append(event)

    if fail_result:
        with pytest.raises(RuntimeError, match="result failed"):
            engine.observe(SensorInput("binary_sensor.b", "on", NOW),
                           result_callback=complete, decision_callback=edge)
        assert edges == []
    else:
        result = engine.observe(SensorInput("binary_sensor.b", "on", NOW),
                                result_callback=complete, decision_callback=edge)
        assert result_seen == [result] and edges == list(result.policy_events)
    assert engine.snapshot.policy_states[1].active
    assert not engine._in_decision_callback


@pytest.mark.parametrize("operation", ("deadline", "duplicate", "stale", "zero"))
def test_result_only_callback_includes_no_edge_and_deadline_results(
    operation: str,
) -> None:
    """Full-result consumers are independent of the optional legacy edge API."""
    engine = ZoneModelEngine(model(), 0 if operation == "zero" else 2, NOW)
    for _ in range(5):
        engine.prediction_manager.chain.observe("c", "t")
    for seconds, node in enumerate(("a", "b", "c")):
        engine.observe(SensorInput(f"binary_sensor.{node}", "on",
                                   NOW + timedelta(seconds=seconds)))
    counts = deepcopy(engine.prediction_manager.chain.counts)
    at = NOW + timedelta(seconds={"deadline": 12, "duplicate": 3,
                                 "stale": 1, "zero": 3}[operation])
    results: list[ZoneModelResult] = []
    result = engine.observe(SensorInput("binary_sensor.c", "on", at),
                            result_callback=results.append)
    assert results == [result]
    assert result.snapshot == engine.snapshot
    if operation == "deadline":
        assert any(e.zone == "t" and e.kind == "released" and e.event_at == at
                   for e in result.policy_events)
        assert any(d.zone == "t" and d.event_kind == "released"
                   for d in result.policy_decisions)
    else:
        assert result.policy_events == ()
    assert engine.prediction_manager.chain.counts == counts


def test_legacy_edge_only_callback_retains_complete_state_and_guard() -> None:
    engine = ZoneModelEngine(model(), 2, NOW)
    engine.observe(SensorInput("binary_sensor.a", "on", NOW))
    edges: list[PolicyEvent] = []

    def edge(event: PolicyEvent, decision: PolicyDecision,
             authorization: TraversalAuthorization | None) -> None:
        assert engine.snapshot.policy_states[1].active
        assert decision.event_kind == event.kind == "acquired"
        assert authorization is not None and authorization.authorized
        with pytest.raises(ValueError, match="callback"):
            engine.commit_prediction_learning()
        edges.append(event)

    result = engine.observe(SensorInput("binary_sensor.b", "on", NOW),
                            decision_callback=edge)
    assert edges == list(result.policy_events)
