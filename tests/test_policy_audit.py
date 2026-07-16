from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from datetime import UTC, datetime

import pytest

from custom_components.predictive_controls.occupancy_state import (
    MovementEvidence,
    ObservationProvenance,
    PackedPolicyAuditContext,
    PendingDepartureAudit,
    PolicyAuditContext,
    PositiveEvidence,
)
from custom_components.predictive_controls.policy_audit import (
    MAX_UNCOMPRESSED_CONTEXT_BYTES,
    PACKED_CONTEXT_ENCODING,
    pack_policy_audit_context,
    pack_policy_audit_payload,
    pack_preencoded_policy_audit_payload,
    packed_policy_audit_context_from_storage,
    packed_policy_audit_context_size,
    policy_audit_context_payload,
    stored_policy_audit_context_payload,
    validate_target_policy_audit_context,
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


def test_target_policy_v2_shared_lists_are_lossless_and_deterministic() -> None:
    shared = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": list(shared),
    }

    packed = pack_policy_audit_payload(payload)

    assert packed == pack_policy_audit_payload(payload)
    assert validate_target_policy_audit_context(packed) == payload
    compact = json.loads(zlib.decompress(packed.compressed_json))
    assert compact["first"] == {
        "__exact_shared_list_ref__": "list_000000"
    }
    assert compact["second"] == compact["first"]
    assert list(compact["__exact_shared_lists__"]) == ["list_000000"]


@pytest.mark.parametrize("aliased", (False, True))
def test_target_policy_v2_deduplicates_equal_and_aliased_lists(
    aliased: bool,
) -> None:
    shared = list(range(5_000))
    second = shared if aliased else list(shared)
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": second,
    }

    packed = pack_policy_audit_payload(payload)
    compact = json.loads(zlib.decompress(packed.compressed_json))

    assert compact["first"] == {
        "__exact_shared_list_ref__": "list_000000"
    }
    assert compact["second"] == compact["first"]
    assert list(compact["__exact_shared_lists__"]) == ["list_000000"]
    assert validate_target_policy_audit_context(packed) == payload


def test_target_policy_v2_compacts_repeated_nested_large_lists() -> None:
    shared = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": [shared],
        "second": [list(shared)],
    }

    packed = pack_policy_audit_payload(payload)
    compact = json.loads(zlib.decompress(packed.compressed_json))

    assert compact["first"] == {
        "__exact_shared_list_ref__": "list_000000"
    }
    assert compact["second"] == compact["first"]
    assert validate_target_policy_audit_context(packed) == payload


def test_target_policy_v2_repeated_packing_is_byte_deterministic() -> None:
    shared = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": list(shared),
    }

    packed = [pack_policy_audit_payload(payload) for _ in range(5)]

    assert packed == [packed[0]] * 5


def test_target_policy_v1_skips_compaction_and_round_trips_infinity() -> None:
    shared = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v1",
        "first": shared,
        "second": list(shared),
        "impossible": -math.inf,
    }

    packed = pack_policy_audit_payload(payload)
    compact = json.loads(zlib.decompress(packed.compressed_json))

    assert "__exact_shared_lists__" not in compact
    assert validate_target_policy_audit_context(packed) == payload


def test_target_policy_v2_preencoded_packer_compacts_aliased_lists() -> None:
    shared: list[object] = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": shared,
    }

    packed = pack_preencoded_policy_audit_payload(payload)
    compact = json.loads(zlib.decompress(packed.compressed_json))

    assert compact["first"] == {"__exact_shared_list_ref__": "list_000000"}
    assert compact["second"] == compact["first"]
    assert validate_target_policy_audit_context(packed) == payload


def test_target_policy_v2_preencoded_packer_compacts_equal_lists() -> None:
    shared: list[object] = list(range(5_000))
    payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": list(shared),
    }

    packed = pack_preencoded_policy_audit_payload(payload)
    compact = json.loads(zlib.decompress(packed.compressed_json))

    assert compact["first"] == {"__exact_shared_list_ref__": "list_000000"}
    assert compact["second"] == compact["first"]
    assert validate_target_policy_audit_context(packed) == payload


def test_target_policy_v2_packers_preserve_nonshared_nested_values() -> None:
    shared: list[object] = list(range(5_000))
    nested: list[object] = [[1], {"nested": [2]}, 3]
    equality_payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": list(shared),
        "nested": nested,
    }
    identity_payload = {
        "schema": "exact-policy-audit-v2",
        "first": shared,
        "second": shared,
        "nested": nested,
    }

    assert validate_target_policy_audit_context(
        pack_policy_audit_payload(equality_payload)
    ) == equality_payload
    assert validate_target_policy_audit_context(
        pack_preencoded_policy_audit_payload(identity_payload)
    ) == identity_payload


def test_target_policy_pack_rejects_invalid_numbers_and_uncompressed_size() -> None:
    with pytest.raises(ValueError, match="invalid number"):
        pack_policy_audit_payload(
            {"schema": "exact-policy-audit-v1", "value": math.inf}
        )
    with pytest.raises(ValueError, match="uncompressed bound"):
        pack_preencoded_policy_audit_payload(
            {
                "schema": "exact-policy-audit-v1",
                "value": "x" * MAX_UNCOMPRESSED_CONTEXT_BYTES,
            }
        )


def test_target_policy_v2_rejects_reserved_key_inside_large_list() -> None:
    value: list[object] = list(range(5_000))
    value.append({"__exact_shared_list_ref__": "reserved"})

    with pytest.raises(ValueError, match="shared lists are invalid"):
        pack_policy_audit_payload(
            {
                "schema": "exact-policy-audit-v2",
                "first": value,
                "second": list(value),
            }
        )


def _signed_target_context(body: dict[str, object]) -> PackedPolicyAuditContext:
    encoded = json.dumps(
        body,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signed = {**body, "sha256": hashlib.sha256(encoded).hexdigest()}
    return PackedPolicyAuditContext(
        zlib.compress(
            json.dumps(
                signed,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            level=6,
        )
    )


@pytest.mark.parametrize(
    "body",
    (
        {
            "schema": "exact-policy-audit-v2",
            "value": {"__exact_shared_list_ref__": "list_999999"},
            "__exact_shared_lists__": {"list_000000": list(range(5_000))},
        },
        {
            "schema": "exact-policy-audit-v2",
            "value": {
                "__exact_shared_list_ref__": "list_000000",
                "extra": True,
            },
            "__exact_shared_lists__": {"list_000000": list(range(5_000))},
        },
        {
            "schema": "exact-policy-audit-v2",
            "values": [
                {"__exact_shared_list_ref__": "list_000000"},
                {"__exact_shared_list_ref__": "list_000000"},
            ],
            "__exact_shared_lists__": {
                "list_000000": [
                    {"__exact_shared_list_ref__": "list_000000"},
                    *range(5_000),
                ]
            },
        },
        {
            "schema": "exact-policy-audit-v2",
            "__exact_shared_list_ref__": "reserved",
        },
    ),
)
def test_target_policy_v2_rejects_invalid_shared_list_references(
    body: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="shared lists are invalid"):
        validate_target_policy_audit_context(_signed_target_context(body))


def test_target_policy_v2_rejects_shared_list_expansion_bomb() -> None:
    shared = list(range(5_000))
    body: dict[str, object] = {
        "schema": "exact-policy-audit-v2",
        "values": [
            {"__exact_shared_list_ref__": "list_000000"}
            for _ in range(20)
        ],
        "__exact_shared_lists__": {"list_000000": shared},
    }

    with pytest.raises(ValueError, match="shared lists are invalid"):
        validate_target_policy_audit_context(_signed_target_context(body))


def test_target_policy_v2_pack_rejects_reserved_representation_keys() -> None:
    with pytest.raises(ValueError, match="shared lists are invalid"):
        pack_policy_audit_payload(
            {
                "schema": "exact-policy-audit-v2",
                "value": {"__exact_shared_list_ref__": "reserved"},
            }
        )

    shared: list[object] = list(range(5_000))
    shared.append({"__exact_shared_lists__": {}})
    with pytest.raises(ValueError, match="shared lists are invalid"):
        pack_preencoded_policy_audit_payload(
            {
                "schema": "exact-policy-audit-v2",
                "first": shared,
                "second": shared,
            }
        )


@pytest.mark.parametrize(
    "body",
    (
        {"schema": "unsupported"},
        {"schema": "exact-policy-audit-v2", "sha256": "wrong"},
    ),
)
def test_target_policy_context_rejects_schema_and_hash(body: dict[str, object]) -> None:
    packed = PackedPolicyAuditContext(
        zlib.compress(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        )
    )

    with pytest.raises(ValueError, match="schema|hash"):
        validate_target_policy_audit_context(packed)


@pytest.mark.parametrize(
    "body",
    (
        {
            "schema": "exact-policy-audit-v2",
            "values": [
                {"__exact_shared_list_ref__": "list_000000"},
                {"__exact_shared_list_ref__": "list_000000"},
            ],
            "__exact_shared_lists__": [],
        },
        {
            "schema": "exact-policy-audit-v2",
            "values": [
                {"__exact_shared_list_ref__": "list_000000"},
                {"__exact_shared_list_ref__": "list_000000"},
            ],
            "__exact_shared_lists__": {"wrong": list(range(5_000))},
        },
        {
            "schema": "exact-policy-audit-v2",
            "values": [
                {"__exact_shared_list_ref__": "list_000000"},
                {"__exact_shared_list_ref__": "list_000000"},
            ],
            "__exact_shared_lists__": {"list_000000": "not-a-list"},
        },
        {
            "schema": "exact-policy-audit-v2",
            "values": [
                {"__exact_shared_list_ref__": "list_000000"},
                {"__exact_shared_list_ref__": "list_000000"},
            ],
            "__exact_shared_lists__": {"list_000000": [1]},
        },
        {
            "schema": "exact-policy-audit-v2",
            "nested": {"__exact_shared_lists__": {}},
            "__exact_shared_lists__": {"list_000000": list(range(5_000))},
        },
        {
            "schema": "exact-policy-audit-v2",
            "values": [{"__exact_shared_list_ref__": "list_000000"}],
            "__exact_shared_lists__": {"list_000000": list(range(5_000))},
        },
    ),
)
def test_target_policy_v2_rejects_malformed_shared_list_tables(
    body: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="shared lists are invalid"):
        validate_target_policy_audit_context(_signed_target_context(body))


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
