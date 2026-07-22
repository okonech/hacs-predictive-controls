from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from custom_components.predictive_controls.zone_model.policy import PolicyAuditLog
from custom_components.predictive_controls.zone_model.types import (
    PolicyDecision,
    PolicyEvent,
)

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def decision(
    at: datetime,
    *,
    episode_id: str = "room:1",
    evidence_ids: tuple[str, ...] = ("room:1",),
) -> PolicyDecision:
    return PolicyDecision(
        at,
        at,
        "room",
        "room_motion",
        episode_id,
        "stay_pir",
        0.6,
        0.8,
        False,
        True,
        "positive",
        True,
        True,
        "adjacent_current",
        evidence_ids,
        False,
        False,
        0.7,
        0.3,
        timedelta(seconds=60),
        None,
        "acquired",
        "acquired",
    )


def test_audit_defaults_and_canonical_size_are_deterministic() -> None:
    first = PolicyAuditLog()
    second = PolicyAuditLog()
    row = decision(NOW)
    assert first.append(row) is True
    assert second.append(row) is True
    assert first.rows == second.rows == (row,)
    assert first.encoded_bytes == second.encoded_bytes
    assert first.retention == (timedelta(hours=12), 2048, 2 * 1024 * 1024, 4096)


def test_audit_time_and_entry_bounds_evict_fifo() -> None:
    audit = PolicyAuditLog(max_age=timedelta(hours=1), entry_limit=2)
    first = decision(NOW, episode_id="one")
    second = decision(NOW + timedelta(minutes=1), episode_id="two")
    third = decision(NOW + timedelta(minutes=2), episode_id="three")
    for row in (first, second, third):
        assert audit.append(row) is True
    assert audit.rows == (second, third)

    at_expiry = NOW + timedelta(hours=1, minutes=2)
    fourth = decision(at_expiry, episode_id="four")
    audit.append(fourth)
    assert len(audit.rows) == 1
    assert audit.rows[0] == fourth


def test_audit_byte_bound_and_oversized_rows_are_observable() -> None:
    sample_size = PolicyAuditLog.encoded_size(decision(NOW))
    audit = PolicyAuditLog(byte_limit=sample_size + 20, max_row_bytes=4096)
    first = decision(NOW, episode_id="one")
    second = decision(NOW + timedelta(seconds=1), episode_id="two")
    assert audit.append(first) is True
    assert audit.append(second) is True
    assert audit.rows == (second,)
    assert audit.encoded_bytes <= sample_size + 20

    oversized = replace(
        second,
        event_at=NOW + timedelta(seconds=2),
        processing_at=NOW + timedelta(seconds=2),
        evidence_ids=("x" * 5000,),
    )
    before = audit.rows
    assert audit.append(oversized) is False
    assert audit.rows == before
    assert audit.rejected_rows == 1


def test_audit_rejects_non_monotonic_time_and_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        PolicyAuditLog(entry_limit=0)
    audit = PolicyAuditLog()
    audit.append(decision(NOW))
    with pytest.raises(ValueError, match="backward"):
        audit.append(decision(NOW - timedelta(seconds=1)))


def test_audit_deferral_materializes_only_after_flush_and_aborts_cleanly() -> None:
    audit = PolicyAuditLog()
    with pytest.raises(RuntimeError, match="not active"):
        audit.flush_deferred()
    audit.begin_defer()
    with pytest.raises(RuntimeError, match="already active"):
        audit.begin_defer()
    first = decision(NOW, episode_id="one")
    second = decision(NOW + timedelta(seconds=1), episode_id="two")
    assert audit.append(first)
    assert audit.append(second)
    assert len(audit.rows) == 0
    assert audit.encoded_bytes == 0
    with pytest.raises(ValueError, match="backward"):
        audit.append(decision(NOW - timedelta(seconds=1)))

    audit.flush_deferred()

    flushed = cast(tuple[PolicyDecision, ...], audit.rows)
    assert flushed == (first, second)
    assert audit.encoded_bytes > 0
    audit.begin_defer()
    audit.append(decision(NOW + timedelta(seconds=2), episode_id="discarded"))
    audit.discard_deferred()
    retained = cast(tuple[PolicyDecision, ...], audit.rows)
    assert retained == (first, second)


def test_policy_event_validates_public_edge_contract() -> None:
    valid = PolicyEvent(
        "acquired",
        NOW,
        "room",
        "room:1",
        0.7,
        "adjacent_current",
        "acquired",
    )
    assert replace(valid, kind="released", episode_id=None).episode_id is None
    for changes, message in (
        ({"kind": "unknown"}, "Unknown policy event"),
        ({"zone": ""}, "identifiers"),
        ({"episode_id": ""}, "identifiers"),
        ({"episode_id": None}, "require an episode"),
        ({"belief": float("nan")}, "finite"),
        ({"belief": 1.1}, "finite"),
        ({"authorization_reason": ""}, "reasons"),
        ({"policy_reason": ""}, "reasons"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(valid, **changes)


def test_policy_decision_validates_compact_audit_contract() -> None:
    valid = decision(NOW)
    invalid_cases = (
        ({"processing_at": NOW - timedelta(microseconds=1)}, "processing"),
        ({"zone": ""}, "zone and profile"),
        ({"profile_name": "unknown"}, "zone and profile"),
        ({"node_id": ""}, "identifiers"),
        ({"episode_id": ""}, "identifiers"),
        ({"belief_before": float("nan")}, "beliefs"),
        ({"belief_after": 1.1}, "beliefs"),
        ({"active_before": 0}, "flags"),
        ({"local_evidence_kind": "unknown"}, "evidence kind"),
        ({"traversal_reason": ""}, "traversal reason"),
        ({"evidence_ids": ("room:1", "room:1")}, "evidence IDs"),
        ({"evidence_ids": ("",)}, "evidence IDs"),
        ({"off_threshold": 0.7}, "thresholds"),
        ({"release_dwell": timedelta(0)}, "release dwell"),
        ({"release_dwell": timedelta(seconds=-1)}, "release dwell"),
        (
            {
                "pending_release_since": NOW,
                "active_after": False,
                "event_kind": None,
            },
            "pending release",
        ),
        (
            {"pending_release_since": NOW + timedelta(microseconds=1)},
            "pending release",
        ),
        ({"event_kind": "unknown"}, "event kind"),
        ({"active_before": True}, "contradicts"),
        ({"reason": ""}, "reason"),
    )
    for changes, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            replace(valid, **changes)
