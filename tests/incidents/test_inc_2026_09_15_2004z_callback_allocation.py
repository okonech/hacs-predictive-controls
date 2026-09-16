"""User-reported issue: "please fix the blocker"; "optimization is awlays good".
User expected: keep callbacks under 5ms p99; 10ms only if genuinely necessary.
Observed: local 100-event runs reached positive 5.634570/rejected 5.984307ms;
the fresh unchanged baseline passed at 4.097385/4.212224ms. Not a HA incident.
Source: September 15 report; intake 2026-09-15T20:04:40.601257Z supplies identity
because the original benchmark event minute is unavailable. Local evidence:
/tmp/callback-perf-20260915/{baseline.json,callbacks-before.prof}. The profile
contained 1200 measured callbacks, 392900 health-state validations and 19400
audit asdict calls. It is not an uninstrumented latency acceptance result.
Test scope: synthetic work-count regression for the verified redundant work,
with public diagnostic rows and canonical audit bytes protected. Not a claim
of reproducing host-dependent wall time. The unchanged standalone 100-event
benchmark remains the public latency oracle; no existing scenario is amended.
2026-09-16: user approved migrating the supplemental synthetic cycle-pruning
boundary to10 cycles/20minutes. The original computational primary is unchanged.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.predictive_controls.zone_model import path_health
from custom_components.predictive_controls.zone_model.path_health import PathHealth
from custom_components.predictive_controls.zone_model.policy import PolicyAuditLog
from custom_components.predictive_controls.zone_model.types import (
    EpisodeState,
    PhysicalNode,
    PolicyDecision,
    ReliabilityWarningOccurrence,
)

NOW = datetime(2026, 9, 15, 20, 4, 40, 601257, tzinfo=UTC)
NODE = PhysicalNode("a", "room", ("binary_sensor.a",), "stay_presence")
EMPTY: frozenset[str] = frozenset()
pytestmark = pytest.mark.target_model


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def episode(phase: str) -> tuple[EpisodeState, ...]:
    return (EpisodeState("a", "room", "stay_presence", (("binary_sensor.a", phase),)),)


def row() -> PolicyDecision:
    return PolicyDecision(
        NOW, NOW, "room", "a", "a:1", "stay_presence", 0.6, 0.8,
        False, True, "positive", True, True, "adjacent_current", ("a:1",),
        False, False, 0.7, 0.3, timedelta(seconds=120), None, "acquired", "acquired",
    )


def legacy_bytes(decision: PolicyDecision) -> bytes:
    """Independent pre-optimization serializer, not the production converter."""
    def default(value: object) -> str | float:
        if isinstance(value, datetime):
            return value.isoformat()
        assert isinstance(value, timedelta)
        return value.total_seconds()

    return json.dumps(
        asdict(decision), default=default, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


@pytest.mark.parametrize("workload", ("health", "audit"))
def test_inc_2026_09_15_2004z_callback_allocation(workload: str) -> None:
    if workload == "health":
        health = PathHealth((NODE,))
        health.observe(episode("on"), NOW, EMPTY)
        before = health.states
        with patch.object(path_health, "replace", wraps=replace) as allocate:
            for _ in range(100):
                assert health.advance(at(599), EMPTY) == ()
                assert health.states == before
        # A work budget, not a sensor/model expectation or flaky elapsed limit.
        assert allocate.call_count == 0, "unchanged health records reconstructed"
    else:
        decision = row()
        expected = legacy_bytes(decision)
        audit = PolicyAuditLog()
        with patch.object(copy, "deepcopy", wraps=copy.deepcopy) as copying:
            for _ in range(100):
                assert audit.append(decision)
                assert audit.encoded_size(decision) == len(expected)
            assert audit.rows == (decision,) * 100
            assert audit.encoded_bytes == len(expected) * 100
        assert copying.call_count == 0, "audit sizing deep-copies immutable fields"


def test_unchanged_health_still_refreshes_and_clears_exact_deadlines() -> None:
    health = PathHealth((NODE,))
    health.observe(episode("on"), NOW, EMPTY)
    original = health.states
    for seconds in (600, 600, 601):
        assert health.advance(at(seconds), EMPTY) == (ReliabilityWarningOccurrence(
            "a", "room", "suspected_stuck", "assertion_timeout", at(600), at(seconds),
        ),)
        assert health.states == original
    assert health.advance(at(602), frozenset({"a"})) == (
        ReliabilityWarningOccurrence(
            "a", "room", "suspected_stuck", "assertion_timeout", at(600), at(602),
            at(602),
        ),
    )
    assert original[0].unsupported_started_at == NOW
    assert health.states[0].unsupported_started_at is None
    health.advance(at(603), EMPTY)
    assert health.states[0].unsupported_started_at == at(603)
    for seconds in (1199, 1200, 1201):
        assert health.advance(at(seconds), EMPTY)[0].cleared_at == at(602)
    assert health.advance(at(1203), EMPTY)[0].first_observed_at == at(1203)
    with pytest.raises(ValueError, match="backwards"):
        health.advance(at(1202), EMPTY)
    with pytest.raises(ValueError, match="mapped"):
        health.advance(at(1203), frozenset({"not_mapped"}))


def test_cycle_pruning_keeps_exact_expiry_and_frozen_prior_state() -> None:
    health = PathHealth((NODE,))
    for start in range(0, 200, 20):
        health.observe(episode("on"), at(start), EMPTY)
        health.observe(episode("off"), at(start + 10), EMPTY)
    before = health.states
    health.advance(at(1209.999999), EMPTY)
    assert health.states == before
    assert health.advance(at(1210), EMPTY) == (ReliabilityWarningOccurrence(
        "a", "room", "flapping", "sustained_flapping", at(190), at(1210), at(1210),
    ),)
    assert health.states[0].completed_cycles == tuple(
        at(i) for i in range(30, 200, 20)
    )
    assert before[0].completed_cycles == tuple(at(i) for i in range(10, 200, 20))
    ledger = health.advance(at(1210), EMPTY)
    restored = PathHealth((NODE,))
    restored.restore(health.states, ledger, at(1210))
    assert restored.advance(at(4000), EMPTY) == health.advance(at(4000), EMPTY)
    assert restored.states == health.states


@pytest.mark.parametrize("populated", (False, True))
def test_audit_bytes_match_legacy_oracle_and_supported_field_schema(
    populated: bool,
) -> None:
    decision = replace(
        row(), node_id="\"é\n" if populated else None,
        episode_id="a:🙂" if populated else None,
        evidence_ids=("é", "🙂") if populated else (),
        count_conflict_support_ids=("x", "y") if populated else (),
        reliability_result="degraded" if populated else None,
        pending_release_since=NOW if populated else None,
        event_kind=None, local_evidence_kind=None, traversal_reason=None,
        release_dwell=timedelta(seconds=120, microseconds=123456),
    )
    for field in fields(decision):
        value = getattr(decision, field.name)
        assert (
            value is None or type(value) in (str, bool, float, datetime, timedelta)
            or (type(value) is tuple and all(type(item) is str for item in value))
        ), f"Expand the byte oracle for new field type: {field.name}"
    expected = legacy_bytes(decision)
    with patch.object(json, "dumps", wraps=json.dumps) as encode:
        assert PolicyAuditLog.encoded_size(decision) == len(expected)
    args, kwargs = encode.call_args
    assert json.dumps(*args, **kwargs).encode("utf-8") == expected
    # Exactly 4096 is accepted; 4097 is rejected without evicting a good row.
    base_size = len(legacy_bytes(replace(decision, reason="x")))
    exact = replace(decision, reason="x" * (4096 - base_size + 1))
    assert len(legacy_bytes(exact)) == 4096
    log = PolicyAuditLog(byte_limit=4096)
    assert log.append(decision)
    assert log.append(exact)
    assert log.rows == (exact,)
    assert log.encoded_bytes == 4096
    assert not log.append(replace(exact, reason=exact.reason + "x"))
    assert log.rows == (exact,)
    assert log.rejected_rows == 1
