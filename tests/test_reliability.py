from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.predictive_controls.occupancy_state import (
    PolicyAuditEntry,
    PolicyDecision,
)
from custom_components.predictive_controls.reliability import (
    RELIABILITY_FLAP_WINDOW,
    summarize_policy_reliability,
)

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


def audit_entry(
    event_id: str,
    at: datetime,
    state: str,
    *,
    action: str = "activate",
    accepted: bool = False,
    reason_code: str = "occupied_gate_failed",
    occupied_marginal: float | None = 0.2,
    entity_id: str | None = "binary_sensor.office_motion",
    zone: str | None = "office",
    previous_keep_on: bool = False,
    current_keep_on: bool = False,
) -> PolicyAuditEntry:
    gate_values: dict[str, float | bool | str] = {}
    if occupied_marginal is not None:
        gate_values["occupied_marginal"] = occupied_marginal
    return PolicyAuditEntry(
        decision_at=at,
        source="observation",
        trigger_event_id=event_id,
        trigger_entity_id=entity_id,
        trigger_zone=zone,
        trigger_state=state,
        trigger_disposition="accepted",
        decision=PolicyDecision(
            zone=zone or "office",
            action=action,
            accepted=accepted,
            reason_code=reason_code,
            gate_values=gate_values,
            evidence_ids=(event_id,),
        ),
        previous_keep_on=previous_keep_on,
        current_keep_on=current_keep_on,
        previous_reason="previous",
        current_reason="current",
        previous_release_cause=None,
        current_release_cause=None,
    )


def test_reliability_summary_flags_repeated_rejected_motion_and_flaps() -> None:
    audit = (
        audit_entry(
            "office-on-1",
            NOW,
            "on",
            action="release",
            reason_code="graph_departure_gate_failed",
            occupied_marginal=None,
        ),
        audit_entry("office-on-1", NOW, "on", occupied_marginal=0.2),
        audit_entry(
            "office-off-1",
            NOW + timedelta(seconds=5),
            "off",
            reason_code="non_positive_observation",
            occupied_marginal=None,
        ),
        audit_entry(
            "office-on-2",
            NOW + timedelta(seconds=10),
            "on",
            occupied_marginal=0.3,
        ),
        audit_entry(
            "office-off-2",
            NOW + timedelta(seconds=14),
            "off",
            reason_code="non_positive_observation",
            occupied_marginal=None,
        ),
        audit_entry(
            "held-on",
            NOW + timedelta(seconds=20),
            "on",
            reason_code="increase_gate_failed",
            occupied_marginal=0.9,
            previous_keep_on=True,
            current_keep_on=True,
        ),
        audit_entry(
            "accepted-on",
            NOW + timedelta(seconds=25),
            "on",
            accepted=True,
            reason_code="graph_supported_arrival",
            occupied_marginal=0.8,
            current_keep_on=True,
        ),
        audit_entry(
            "single-duplicate",
            NOW + timedelta(seconds=30),
            "on",
            action="observe",
            reason_code="observation_duplicate",
            occupied_marginal=None,
            entity_id="binary_sensor.hall_motion",
            zone="hall",
        ),
        audit_entry(
            "no-trigger",
            NOW + timedelta(seconds=35),
            "on",
            entity_id=None,
            zone=None,
        ),
    )

    summary = summarize_policy_reliability(audit)

    assert summary.observed_event_count == 7
    assert summary.oldest_event_at == NOW
    assert summary.newest_event_at == NOW + timedelta(seconds=30)
    assert len(summary.rejected_motion_captures) == 1
    captures = summary.rejected_motion_captures[0]
    assert captures.entity_id == "binary_sensor.office_motion"
    assert captures.zone == "office"
    assert captures.capture_count == 2
    assert captures.last_capture_at == NOW + timedelta(seconds=10)
    assert captures.reason_counts == (("occupied_gate_failed", 2),)
    assert captures.max_occupied_marginal == 0.3

    assert len(summary.low_confidence_flaps) == 1
    flaps = summary.low_confidence_flaps[0]
    assert flaps.entity_id == "binary_sensor.office_motion"
    assert flaps.zone == "office"
    assert flaps.pulse_count == 2
    assert flaps.last_flap_at == NOW + timedelta(seconds=14)
    assert flaps.shortest_pulse_seconds == 4.0
    assert flaps.max_occupied_marginal == 0.3


def test_reliability_summary_handles_empty_and_long_pulses() -> None:
    assert RELIABILITY_FLAP_WINDOW == timedelta(seconds=30)
    empty = summarize_policy_reliability(())
    assert empty.observed_event_count == 0
    assert empty.oldest_event_at is None
    assert empty.newest_event_at is None
    assert empty.rejected_motion_captures == ()
    assert empty.low_confidence_flaps == ()

    long_pulses = (
        audit_entry("on-1", NOW, "on"),
        audit_entry("off-1", NOW + timedelta(seconds=31), "off"),
        audit_entry("on-2", NOW + timedelta(seconds=40), "on"),
        audit_entry("off-2", NOW + timedelta(seconds=71), "off"),
    )
    summary = summarize_policy_reliability(long_pulses)
    assert len(summary.rejected_motion_captures) == 1
    assert summary.low_confidence_flaps == ()



def test_reliability_summary_deduplicates_context_free_observations() -> None:
    first = audit_entry(
        "duplicate-1",
        NOW,
        "on",
        action="observe",
        reason_code="observation_duplicate",
        occupied_marginal=None,
    )
    audit = (
        first,
        first,
        audit_entry(
            "duplicate-2",
            NOW + timedelta(seconds=1),
            "on",
            action="observe",
            reason_code="observation_duplicate",
            occupied_marginal=None,
        ),
        audit_entry(
            "orphan-off",
            NOW + timedelta(seconds=2),
            "off",
            reason_code="non_positive_observation",
            occupied_marginal=None,
        ),
    )

    summary = summarize_policy_reliability(audit)

    assert summary.observed_event_count == 3
    assert len(summary.rejected_motion_captures) == 1
    captures = summary.rejected_motion_captures[0]
    assert captures.capture_count == 2
    assert captures.reason_counts == (("observation_duplicate", 2),)
    assert captures.max_occupied_marginal is None
    assert summary.low_confidence_flaps == ()
