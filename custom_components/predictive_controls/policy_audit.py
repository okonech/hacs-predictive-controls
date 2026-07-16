from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import zlib
from collections.abc import Mapping
from typing import cast

from .occupancy_state import PackedPolicyAuditContext, PolicyAuditContext

PACKED_CONTEXT_ENCODING = "zlib-json-v1"
MAX_UNCOMPRESSED_CONTEXT_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_CONTEXT_BYTES = 50 * 1024 * 1024
MAX_CONTEXT_EXPANSION_RATIO = 10
MIN_SHARED_LIST_BYTES = 10 * 1024
_SHARED_LISTS_KEY = "__exact_shared_lists__"
_SHARED_LIST_REF_KEY = "__exact_shared_list_ref__"


def pack_policy_audit_payload(
    payload: Mapping[str, object],
) -> PackedPolicyAuditContext:
    """Pack one deterministic target-policy audit payload."""

    body = cast(dict[str, object], _encode_exact_numbers(dict(payload)))
    if body.get("schema") == "exact-policy-audit-v2":
        body = _compact_shared_lists(body)
    return _pack_policy_audit_body(body)


def pack_preencoded_policy_audit_payload(
    payload: Mapping[str, object],
) -> PackedPolicyAuditContext:
    """Pack an internal payload that already uses exact-number sentinels."""

    body = dict(payload)
    if body.get("schema") == "exact-policy-audit-v2":
        body = _compact_shared_lists(body)
    return _pack_policy_audit_body(body)


def _pack_policy_audit_body(
    body: dict[str, object],
) -> PackedPolicyAuditContext:
    encoded_body = json.dumps(
        body,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    body["sha256"] = hashlib.sha256(encoded_body).hexdigest()
    encoded = json.dumps(
        body,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > MAX_UNCOMPRESSED_CONTEXT_BYTES:
        raise ValueError("policy audit context exceeds the uncompressed bound")
    return PackedPolicyAuditContext(zlib.compress(encoded, level=1))


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


def validate_target_policy_audit_context(
    context: PackedPolicyAuditContext,
) -> dict[str, object]:
    """Validate and expand one complete target-policy audit context."""

    payload = _decode_context(context.compressed_json)
    if payload.get("schema") not in {
        "exact-policy-audit-v1",
        "exact-policy-audit-v2",
    }:
        raise ValueError("target policy audit context schema is invalid")
    digest = payload.pop("sha256", None)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if not isinstance(digest, str) or not hmac.compare_digest(
        digest,
        hashlib.sha256(encoded).hexdigest(),
    ):
        raise ValueError("target policy audit context hash is invalid")
    if payload.get("schema") == "exact-policy-audit-v2":
        payload = _expand_shared_lists(payload, len(encoded))
    return cast(dict[str, object], _decode_exact_numbers(payload))


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


def _encode_exact_numbers(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        if value == -math.inf:
            return {"__exact_float__": "negative_infinity"}
        raise ValueError("target policy audit context contains an invalid number")
    if isinstance(value, Mapping):
        return {
            str(key): _encode_exact_numbers(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_encode_exact_numbers(item) for item in value]
    return value


def _decode_exact_numbers(value: object) -> object:
    if value == {"__exact_float__": "negative_infinity"}:
        return -math.inf
    if isinstance(value, dict):
        return {key: _decode_exact_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_exact_numbers(item) for item in value]
    return value


def _compact_shared_lists(body: dict[str, object]) -> dict[str, object]:
    occurrences: dict[bytes, int] = {}
    first_occurrence: list[bytes] = []
    canonical_lists: dict[int, bytes] = {}

    def canonical_list(value: list[object]) -> bytes:
        identity = id(value)
        encoded = canonical_lists.get(identity)
        if encoded is None:
            encoded = _canonical_json(value)
            canonical_lists[identity] = encoded
        return encoded

    def collect(value: object) -> None:
        if isinstance(value, list):
            encoded = canonical_list(value)
            if len(encoded) >= MIN_SHARED_LIST_BYTES:
                if any(isinstance(item, list | dict) for item in value):
                    _reject_reserved_keys(value)
                if encoded not in occurrences:
                    first_occurrence.append(encoded)
                    occurrences[encoded] = 0
                occurrences[encoded] += 1
                return
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            if _SHARED_LISTS_KEY in value or _SHARED_LIST_REF_KEY in value:
                raise ValueError("target policy audit shared lists are invalid")
            for item in value.values():
                collect(item)

    collect(body)
    shared_ids = {
        encoded: f"list_{index:06d}"
        for index, encoded in enumerate(
            item for item in first_occurrence if occurrences[item] > 1
        )
    }
    if not shared_ids:
        return body

    shared_lists: dict[str, object] = {}

    def replace(value: object) -> object:
        if isinstance(value, list):
            encoded = canonical_list(value)
            shared_id = shared_ids.get(encoded)
            if shared_id is not None:
                shared_lists.setdefault(shared_id, value)
                return {_SHARED_LIST_REF_KEY: shared_id}
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    compact = cast(dict[str, object], replace(body))
    compact[_SHARED_LISTS_KEY] = shared_lists
    return compact


def _expand_shared_lists(
    body: dict[str, object],
    compact_size: int,
) -> dict[str, object]:
    raw_shared = body.get(_SHARED_LISTS_KEY)
    if raw_shared is None:
        _reject_reserved_keys(body)
        return body
    if not isinstance(raw_shared, dict) or not raw_shared:
        raise ValueError("target policy audit shared lists are invalid")
    expected_ids = [f"list_{index:06d}" for index in range(len(raw_shared))]
    if sorted(raw_shared) != expected_ids:
        raise ValueError("target policy audit shared lists are invalid")
    for value in raw_shared.values():
        if not isinstance(value, list):
            raise ValueError("target policy audit shared lists are invalid")
        _reject_reserved_keys(value)
        if len(_canonical_json(value)) < MIN_SHARED_LIST_BYTES:
            raise ValueError("target policy audit shared lists are invalid")

    references: dict[str, int] = dict.fromkeys(expected_ids, 0)

    def validate(value: object, *, root: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                validate(item)
            return
        if not isinstance(value, dict):
            return
        if _SHARED_LISTS_KEY in value and not root:
            raise ValueError("target policy audit shared lists are invalid")
        if _SHARED_LIST_REF_KEY in value:
            if set(value) != {_SHARED_LIST_REF_KEY}:
                raise ValueError("target policy audit shared lists are invalid")
            shared_id = value[_SHARED_LIST_REF_KEY]
            if not isinstance(shared_id, str) or shared_id not in raw_shared:
                raise ValueError("target policy audit shared lists are invalid")
            references[shared_id] += 1
            return
        for key, item in value.items():
            if key != _SHARED_LISTS_KEY:
                validate(item)

    validate(body, root=True)
    if any(count < 2 for count in references.values()):
        raise ValueError("target policy audit shared lists are invalid")

    expanded_body = {
        key: value for key, value in body.items() if key != _SHARED_LISTS_KEY
    }

    def expand(value: object) -> object:
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            shared_id = value.get(_SHARED_LIST_REF_KEY)
            if shared_id is not None:
                return raw_shared[cast(str, shared_id)]
            return {key: expand(item) for key, item in value.items()}
        return value

    expanded_size = _expanded_json_size(expanded_body, raw_shared)
    expansion_limit = min(
        compact_size * MAX_CONTEXT_EXPANSION_RATIO,
        MAX_EXPANDED_CONTEXT_BYTES,
    )
    if expanded_size > expansion_limit:
        raise ValueError("target policy audit shared lists are invalid")
    return cast(dict[str, object], expand(expanded_body))


def _expanded_json_size(
    value: object,
    shared_lists: Mapping[str, object],
) -> int:
    if isinstance(value, list):
        return 2 + max(0, len(value) - 1) + sum(
            _expanded_json_size(item, shared_lists) for item in value
        )
    if isinstance(value, dict):
        shared_id = value.get(_SHARED_LIST_REF_KEY)
        if shared_id is not None:
            return _expanded_json_size(
                shared_lists[cast(str, shared_id)],
                shared_lists,
            )
        return 2 + max(0, len(value) - 1) + sum(
            len(_canonical_json(key))
            + 1
            + _expanded_json_size(item, shared_lists)
            for key, item in value.items()
        )
    return len(_canonical_json(value))


def _reject_reserved_keys(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _reject_reserved_keys(item)
        return
    if not isinstance(value, dict):
        return
    if _SHARED_LISTS_KEY in value or _SHARED_LIST_REF_KEY in value:
        raise ValueError("target policy audit shared lists are invalid")
    for item in value.values():
        _reject_reserved_keys(item)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


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
                "via_zone": evidence.via_zone,
                "via_node_id": evidence.via_node_id,
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
                "segment_probability": departure.segment_probability,
                "destination_movement_probability": (
                    departure.destination_movement_probability
                ),
                "source_episode_ids": list(departure.source_episode_ids),
            }
            for departure in context.pending_departures
        },
    }


def _stored_probability(value: float) -> float:
    return min(1.0, max(0.0, value))
