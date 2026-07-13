from __future__ import annotations

import base64
import zlib
from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.occupancy_state import (
    MovementEvidence,
    ObservationProvenance,
    PendingDepartureAudit,
    PolicyAuditContext,
    PositiveEvidence,
)
from custom_components.predictive_controls.policy_audit import (
    MAX_UNCOMPRESSED_CONTEXT_BYTES,
    PACKED_CONTEXT_ENCODING,
    pack_policy_audit_context,
    packed_policy_audit_context_from_storage,
    packed_policy_audit_context_size,
    policy_audit_context_payload,
    stored_policy_audit_context_payload,
)

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


def make_context() -> PolicyAuditContext:
    provenance = ObservationProvenance(
        event_id="hall-motion",
        evidence_episode_id="hall-motion:1",
        entity_id="binary_sensor.hall",
        node_id="hall",
        zone="hall",
        state="on",
        signal_type="motion",
        reliability=0.9,
        log_likelihood_by_count=(-1.0, 0.5),
        disposition="accepted",
    )
    return PolicyAuditContext(
        provenance=provenance,
        previous_occupied_marginals={"office": 0.8, "hall": 0.2},
        occupied_marginals={"office": 0.3, "hall": 0.7},
        count_marginals={"office": (0.7, 0.3), "hall": (0.3, 0.7)},
        active_positive_evidence={
            "hall": (
                PositiveEvidence(
                    entity_id="binary_sensor.hall",
                    evidence_episode_id="hall-motion:1",
                    changed_at=NOW,
                    signal_type="motion",
                ),
            )
        },
        movement_evidence=(
            MovementEvidence(
                path_key=("hall", "office", "kitchen"),
                origin_zone="office",
                source_zone="office",
                target_zone="hall",
                coherent_probability=0.65,
                source_node_id="office",
                target_node_id="hall",
                evidence_ids=("office-motion", "hall-motion"),
                disposition="graph_valid",
            ),
        ),
        pending_departures=(
            PendingDepartureAudit(
                origin="office",
                current="hall",
                probability=0.65,
                nonadjacent=False,
                evidence_ids=("office-motion", "hall-motion"),
                disposition="graph_valid",
            ),
        ),
    )


def test_policy_audit_context_packing_is_lossless_and_deterministic() -> None:
    context = make_context()
    packed = pack_policy_audit_context(context)
    stored = stored_policy_audit_context_payload(context)

    assert stored is not None
    assert stored["encoding"] == PACKED_CONTEXT_ENCODING
    restored = packed_policy_audit_context_from_storage(stored)
    assert restored == packed
    assert policy_audit_context_payload(restored) == policy_audit_context_payload(
        context
    )
    assert packed_policy_audit_context_size(None) == 0
    assert packed_policy_audit_context_size(context) == len(packed.compressed_json)
    assert packed_policy_audit_context_size(packed) == len(packed.compressed_json)
    assert stored_policy_audit_context_payload(None) is None


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({}, "encoding is invalid"),
        (
            {"encoding": PACKED_CONTEXT_ENCODING, "data": 3},
            "data is invalid",
        ),
        (
            {"encoding": PACKED_CONTEXT_ENCODING, "data": "not-base64"},
            "data is invalid",
        ),
    ),
)
def test_packed_policy_audit_context_rejects_invalid_envelope(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        packed_policy_audit_context_from_storage(payload)


def _stored_compressed(data: bytes) -> dict[str, object]:
    return {
        "encoding": PACKED_CONTEXT_ENCODING,
        "data": base64.b64encode(data).decode("ascii"),
    }


@pytest.mark.parametrize(
    "compressed",
    (
        b"not-zlib",
        zlib.compress(b"[1,2,3]"),
        zlib.compress(b"{"),
        zlib.compress(b"{}")[:-1],
        zlib.compress(b"{}") + b"trailing-data",
        zlib.compress(b"x" * (MAX_UNCOMPRESSED_CONTEXT_BYTES + 1)),
    ),
)
def test_packed_policy_audit_context_rejects_invalid_compressed_data(
    compressed: bytes,
) -> None:
    with pytest.raises(ValueError, match="data is invalid"):
        packed_policy_audit_context_from_storage(_stored_compressed(compressed))
