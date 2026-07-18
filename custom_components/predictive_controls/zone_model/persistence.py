"""Atomic serialization and schema-6 compatibility for target state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, cast

from ..model import PredictiveMap
from .engine import ZoneModelEngine
from .types import (
    AuthorizationUse,
    BeliefContribution,
    CountState,
    EpisodeState,
    OutwardContext,
    PolicyDecision,
    RefreshDedupEntry,
    SensorInput,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelSnapshot,
    ZonePolicyState,
    require_utc,
)

TARGET_SCHEMA = "zone-belief-v2"
LEGACY_TARGET_SCHEMA = "zone-belief-shadow-v1"
LEGACY_EXACT_SCHEMA = "exact-augmented-v6"


def target_map_fingerprint(predictive_map: PredictiveMap) -> str:
    payload = {
        node_id: {
            "zone": node.occupancy_zone,
            "adjacent": sorted(node.adjacent),
            "transition_seconds": dict(sorted(node.transition_seconds.items())),
            "role": node.role,
            "occupancy_behavior": predictive_map.occupancy_behavior_for_node(node),
            "entities": dict(sorted(node.entities.items())),
        }
        for node_id, node in sorted(predictive_map.nodes.items())
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def serialize_target_state(
    predictive_map: PredictiveMap,
    engine: ZoneModelEngine,
) -> dict[str, object]:
    snapshot = engine.snapshot
    return {
        "schema": TARGET_SCHEMA,
        "map_fingerprint": target_map_fingerprint(predictive_map),
        "snapshot": _json_value(asdict(snapshot)),
        "audit": [_json_value(asdict(row)) for row in engine.audit_rows],
    }


def restore_target_state(
    predictive_map: PredictiveMap,
    payload: object,
    restore_at: datetime,
) -> ZoneModelEngine:
    require_utc(restore_at, "Target restore time")
    root = _mapping(payload, "Target state")
    if root.get("schema") != TARGET_SCHEMA:
        raise ValueError("Target schema is incompatible")
    if root.get("map_fingerprint") != target_map_fingerprint(predictive_map):
        raise ValueError("Target map fingerprint is incompatible")
    snapshot = _decode_snapshot(root.get("snapshot"))
    audit_payload = root.get("audit")
    if not isinstance(audit_payload, list):
        raise ValueError("Target audit must be a list")
    audit = tuple(_decode_policy_decision(item) for item in audit_payload)
    return ZoneModelEngine.restore(predictive_map, snapshot, audit, restore_at)


def migrate_schema6_seed(
    predictive_map: PredictiveMap,
    payload: object,
    sensor_snapshot: Sequence[SensorInput],
    at: datetime,
) -> ZoneModelEngine:
    """Create a finite target seed without importing exact assignments."""

    require_utc(at, "Target migration time")
    root = _mapping(payload, "Schema-6 state")
    if root.get("schema") != LEGACY_EXACT_SCHEMA:
        raise ValueError("Schema-6 migration source is incompatible")
    if root.get("map_fingerprint") != target_map_fingerprint(predictive_map):
        raise ValueError("Schema-6 migration map fingerprint is incompatible")
    occupants = root.get("occupants")
    if not isinstance(occupants, int) or isinstance(occupants, bool):
        raise ValueError("Schema-6 migration occupant count is invalid")
    policy = root.get("policy")
    active_seed: dict[str, bool] = {}
    if policy is not None:
        policy_mapping = _mapping(policy, "Schema-6 policy")
        states = _mapping(policy_mapping.get("states"), "Schema-6 policy states")
        for zone, raw_state in states.items():
            state = _mapping(raw_state, "Schema-6 zone policy")
            keep_on = state.get("keep_on")
            if not isinstance(zone, str) or not isinstance(keep_on, bool):
                raise ValueError("Schema-6 active seed is invalid")
            active_seed[zone] = keep_on
    engine = ZoneModelEngine(
        predictive_map,
        occupants,
        at,
        active_seed=active_seed,
    )
    engine.bootstrap_sensor_snapshot(sensor_snapshot, at)
    return engine


def _decode_snapshot(value: object) -> ZoneModelSnapshot:
    data = _mapping(value, "Target snapshot")
    return ZoneModelSnapshot(
        _datetime(data.get("updated_at"), "snapshot updated_at"),
        tuple(_decode_episode(item) for item in _list(data, "episode_states")),
        tuple(_decode_belief(item) for item in _list(data, "belief_states")),
        tuple(_decode_token(item) for item in _list(data, "traversal_tokens")),
        tuple(_strings(data.get("current_token_ids"), "current token IDs")),
        tuple(_decode_use(item) for item in _list(data, "authorization_uses")),
        _decode_count(data.get("count_state")),
        tuple(_decode_policy_state(item) for item in _list(data, "policy_states")),
    )


def _decode_episode(value: object) -> EpisodeState:
    data = _mapping(value, "Target episode")
    aliases = data.get("alias_states")
    if not isinstance(aliases, list) or any(
        not isinstance(item, list)
        or len(item) != 2
        or not all(isinstance(part, str) for part in item)
        for item in aliases
    ):
        raise ValueError("Target episode aliases are invalid")
    return EpisodeState(
        _string(data, "node_id"),
        _string(data, "zone"),
        _string(data, "profile_name"),
        tuple((cast(str, item[0]), cast(str, item[1])) for item in aliases),
        generation=_integer(data, "generation"),
        episode_id=_optional_string(data.get("episode_id"), "episode ID"),
        status=_string(data, "status"),
        started_at=_optional_datetime(data.get("started_at"), "episode start"),
        last_event_at=_optional_datetime(data.get("last_event_at"), "last event"),
        advanced_at=_optional_datetime(data.get("advanced_at"), "advance time"),
        clear_started_at=_optional_datetime(
            data.get("clear_started_at"), "clear start"
        ),
        clear_deadline=_optional_datetime(data.get("clear_deadline"), "clear deadline"),
        hold_until=_optional_datetime(data.get("hold_until"), "hold expiry"),
        assertion_trust_until=_optional_datetime(
            data.get("assertion_trust_until"), "trust expiry"
        ),
        traversal_valid_until=_optional_datetime(
            data.get("traversal_valid_until"), "traversal expiry"
        ),
        degraded_at=_optional_datetime(data.get("degraded_at"), "degradation time"),
        clear_emitted=_boolean(data, "clear_emitted"),
        health_warning=_boolean(data, "health_warning"),
    )


def _decode_belief(value: object) -> ZoneBeliefState:
    data = _mapping(value, "Target belief")
    outward_raw = data.get("outward_context")
    outward = None
    if outward_raw is not None:
        outward_data = _mapping(outward_raw, "Target outward context")
        outward = OutwardContext(
            _string(outward_data, "source_episode_id"),
            _datetime(outward_data.get("valid_until"), "outward expiry"),
        )
    contributions = tuple(
        _decode_contribution(item) for item in _list(data, "contributions")
    )
    return ZoneBeliefState(
        _string(data, "zone"),
        _string(data, "profile_name"),
        _number(data, "log_odds"),
        _datetime(data.get("last_updated_at"), "belief update"),
        _string(data, "context"),
        _optional_string(data.get("generation_episode_id"), "generation episode"),
        _optional_string(data.get("asserted_episode_id"), "asserted episode"),
        outward,
        _boolean(data, "health_warning"),
        contributions,
    )


def _decode_contribution(value: object) -> BeliefContribution:
    data = _mapping(value, "Target belief contribution")
    return BeliefContribution(
        _datetime(data.get("at"), "contribution time"),
        _string(data, "kind"),
        _string(data, "context_before"),
        _string(data, "context_after"),
        _number(data, "log_odds_delta"),
        _optional_string(data.get("episode_id"), "contribution episode"),
    )


def _decode_token(value: object) -> TraversalToken:
    data = _mapping(value, "Target traversal token")
    return TraversalToken(
        _string(data, "token_id"),
        _string(data, "node_id"),
        _string(data, "zone"),
        _string(data, "role"),
        _string(data, "profile_name"),
        _string(data, "episode_id"),
        _datetime(data.get("accepted_at"), "token acceptance"),
        _datetime(data.get("valid_until"), "token expiry"),
    )


def _decode_use(value: object) -> AuthorizationUse:
    data = _mapping(value, "Target traversal use")
    return AuthorizationUse(
        _string(data, "token_id"),
        _string(data, "target_episode_id"),
        _string(data, "reason"),
        _datetime(data.get("authorized_at"), "authorization time"),
    )


def _decode_count(value: object) -> CountState:
    data = _mapping(value, "Target count")
    diagnostics = data.get("diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != 5:
        raise ValueError("Target count diagnostics are invalid")
    return CountState(
        _integer(data, "expected_count"),
        _optional_datetime(data.get("last_event_at"), "count event time"),
        _optional_string(data.get("last_event_id"), "count event ID"),
        _optional_datetime(data.get("positive_transition_at"), "count transition"),
        _optional_datetime(
            data.get("positive_transition_until"), "count transition expiry"
        ),
        tuple(_strings(data.get("seen_event_ids"), "count event IDs")),
        cast(tuple[int, int, int, int, int], tuple(diagnostics)),
    )


def _decode_policy_state(value: object) -> ZonePolicyState:
    data = _mapping(value, "Target policy state")
    dedup = tuple(_decode_refresh(item) for item in _list(data, "refresh_dedup"))
    return ZonePolicyState(
        _string(data, "zone"),
        _string(data, "profile_name"),
        _boolean(data, "active"),
        _datetime(data.get("last_evaluated_at"), "policy evaluation"),
        _optional_datetime(data.get("pending_release_since"), "pending release"),
        dedup,
    )


def _decode_refresh(value: object) -> RefreshDedupEntry:
    data = _mapping(value, "Target refresh guard")
    return RefreshDedupEntry(
        _string(data, "episode_id"),
        _datetime(data.get("published_at"), "refresh publication"),
        _datetime(data.get("expires_at"), "refresh expiry"),
    )


def _decode_policy_decision(value: object) -> PolicyDecision:
    data = _mapping(value, "Target policy audit row")
    return PolicyDecision(
        _datetime(data.get("event_at"), "audit event time"),
        _datetime(data.get("processing_at"), "audit processing time"),
        _string(data, "zone"),
        _optional_string(data.get("node_id"), "audit node"),
        _optional_string(data.get("episode_id"), "audit episode"),
        _string(data, "profile_name"),
        _number(data, "belief_before"),
        _number(data, "belief_after"),
        _boolean(data, "active_before"),
        _boolean(data, "active_after"),
        _optional_string(data.get("local_evidence_kind"), "local evidence"),
        _boolean(data, "local_trustworthy"),
        _boolean(data, "authorization_authorized"),
        _optional_string(data.get("traversal_reason"), "traversal reason"),
        tuple(_strings(data.get("evidence_ids"), "audit evidence IDs")),
        _boolean(data, "count_zero"),
        _boolean(data, "health_warning"),
        _number(data, "on_threshold"),
        _number(data, "off_threshold"),
        timedelta(seconds=_number(data, "release_dwell")),
        _optional_datetime(data.get("pending_release_since"), "pending release"),
        _optional_string(data.get("event_kind"), "audit event kind"),
        _string(data, "reason"),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _list(data: Mapping[str, object], field: str) -> list[object]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValueError(f"Target {field} must be a list")
    return value


def _string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Target {field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Target {field} must be a string or null")
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Target {field} must be a string list")
    return value


def _boolean(data: Mapping[str, object], field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"Target {field} must be boolean")
    return value


def _integer(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Target {field} must be an integer")
    return value


def _number(data: Mapping[str, object], field: str) -> float:
    value = data.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Target {field} must be numeric")
    return float(value)


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Target {field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Target {field} must be an ISO timestamp") from exc
    require_utc(parsed, f"Target {field}")
    return parsed


def _optional_datetime(value: object, field: str) -> datetime | None:
    return None if value is None else _datetime(value, field)


__all__ = [
    "LEGACY_EXACT_SCHEMA",
    "TARGET_SCHEMA",
    "LEGACY_TARGET_SCHEMA",
    "migrate_schema6_seed",
    "restore_target_state",
    "serialize_target_state",
    "target_map_fingerprint",
]
