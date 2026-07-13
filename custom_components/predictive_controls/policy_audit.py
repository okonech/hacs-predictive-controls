from __future__ import annotations

import base64
import binascii
import json
import zlib
from collections.abc import Mapping
from typing import cast

from .occupancy_state import PackedPolicyAuditContext, PolicyAuditContext

PACKED_CONTEXT_ENCODING = "zlib-json-v1"
MAX_UNCOMPRESSED_CONTEXT_BYTES = 2 * 1024 * 1024


def pack_policy_audit_context(
    context: PolicyAuditContext,
) -> PackedPolicyAuditContext:
    """Pack one complete context into deterministic compressed JSON."""

    encoded = json.dumps(
        _expanded_context_payload(context),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return PackedPolicyAuditContext(zlib.compress(encoded, level=6))


def policy_audit_context_payload(
    context: PolicyAuditContext | PackedPolicyAuditContext | None,
) -> dict[str, object] | None:
    """Expand a retained context for diagnostics or validation."""

    if context is None:
        return None
    if isinstance(context, PackedPolicyAuditContext):
        return _decode_context(context.compressed_json)
    return _expanded_context_payload(context)


def stored_policy_audit_context_payload(
    context: PolicyAuditContext | PackedPolicyAuditContext | None,
) -> dict[str, object] | None:
    """Render one context in its compact restart-safe representation."""

    if context is None:
        return None
    packed = (
        context
        if isinstance(context, PackedPolicyAuditContext)
        else pack_policy_audit_context(context)
    )
    return {
        "encoding": PACKED_CONTEXT_ENCODING,
        "data": base64.b64encode(packed.compressed_json).decode("ascii"),
    }


def packed_policy_audit_context_from_storage(
    payload: Mapping[str, object],
) -> PackedPolicyAuditContext:
    """Decode and validate one compact stored context envelope."""

    if payload.get("encoding") != PACKED_CONTEXT_ENCODING:
        raise ValueError("stored policy audit context encoding is invalid")
    data = payload.get("data")
    if not isinstance(data, str):
        raise ValueError("stored policy audit context data is invalid")
    try:
        compressed = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("stored policy audit context data is invalid") from exc
    packed = PackedPolicyAuditContext(compressed)
    _decode_context(packed.compressed_json)
    return packed


def packed_policy_audit_context_size(
    context: PolicyAuditContext | PackedPolicyAuditContext | None,
) -> int:
    if context is None:
        return 0
    if isinstance(context, PackedPolicyAuditContext):
        return len(context.compressed_json)
    return len(pack_policy_audit_context(context).compressed_json)


def _decode_context(compressed: bytes) -> dict[str, object]:
    decompressor = zlib.decompressobj()
    try:
        encoded = decompressor.decompress(
            compressed,
            MAX_UNCOMPRESSED_CONTEXT_BYTES + 1,
        )
    except zlib.error as exc:
        raise ValueError("stored policy audit context data is invalid") from exc
    if (
        len(encoded) > MAX_UNCOMPRESSED_CONTEXT_BYTES
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise ValueError("stored policy audit context data is invalid")
    try:
        payload = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("stored policy audit context data is invalid") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        raise ValueError("stored policy audit context data is invalid")
    return cast(dict[str, object], payload)


def _expanded_context_payload(context: PolicyAuditContext) -> dict[str, object]:
    return {
        "observation": {
            "event_id": context.provenance.event_id,
            "evidence_episode_id": context.provenance.evidence_episode_id,
            "entity_id": context.provenance.entity_id,
            "node_id": context.provenance.node_id,
            "zone": context.provenance.zone,
            "state": context.provenance.state,
            "signal_type": context.provenance.signal_type,
            "reliability": _stored_probability(context.provenance.reliability),
            "log_likelihood_by_count": list(
                context.provenance.log_likelihood_by_count
            ),
            "disposition": context.provenance.disposition,
        },
        "previous_occupied_marginals": {
            zone: _stored_probability(probability)
            for zone, probability in sorted(
                context.previous_occupied_marginals.items()
            )
        },
        "occupied_marginals": {
            zone: _stored_probability(probability)
            for zone, probability in sorted(context.occupied_marginals.items())
        },
        "count_marginals": {
            zone: [_stored_probability(probability) for probability in probabilities]
            for zone, probabilities in sorted(context.count_marginals.items())
        },
        "active_positive_evidence": {
            zone: [
                {
                    "entity_id": evidence.entity_id,
                    "evidence_episode_id": evidence.evidence_episode_id,
                    "changed_at": evidence.changed_at.isoformat(),
                    "signal_type": evidence.signal_type,
                    "node_id": evidence.node_id,
                }
                for evidence in evidence_items
            ]
            for zone, evidence_items in sorted(
                context.active_positive_evidence.items()
            )
        },
        "movement_evidence": [
            {
                "path_key": list(evidence.path_key),
                "origin_zone": evidence.origin_zone,
                "source_zone": evidence.source_zone,
                "target_zone": evidence.target_zone,
                "coherent_probability": _stored_probability(
                    evidence.coherent_probability
                ),
                "source_node_id": evidence.source_node_id,
                "target_node_id": evidence.target_node_id,
                "evidence_ids": list(evidence.evidence_ids),
                "disposition": evidence.disposition,
            }
            for evidence in context.movement_evidence
        ],
        "pending_departures": {
            departure.origin: {
                "current": departure.current,
                "probability": _stored_probability(departure.probability),
                "nonadjacent": departure.nonadjacent,
                "evidence_ids": list(departure.evidence_ids),
                "disposition": departure.disposition,
            }
            for departure in context.pending_departures
        },
    }


def _stored_probability(value: float) -> float:
    return min(1.0, max(0.0, value))
