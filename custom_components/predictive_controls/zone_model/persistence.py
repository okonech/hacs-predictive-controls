"""Atomic serialization and schema-6 compatibility for target state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from ..const import PRODUCT_MAX_OCCUPANTS
from ..model import PredictiveMap
from .engine import ZoneModelEngine
from .filter import (
    ARRIVAL_FROM_EMPTY_PROBABILITY,
    ARRIVAL_FROM_OCCUPIED_PROBABILITY,
)
from .policy import POLICY_CALIBRATIONS
from .prediction import LEASE_DURATION
from .profiles import (
    BELIEF_PROFILES,
    SHARED_PROFILES,
    build_physical_nodes,
    profile_assignment_for_node,
)
from .types import (
    PREDICTION_MATURITY_PROBABILITY,
    PREDICTION_MATURITY_SUPPORT,
    AuthorizationUse,
    BeliefContribution,
    CountConflictState,
    CountState,
    EpisodeState,
    OutwardContext,
    PendingAcquisitionCandidate,
    PolicyDecision,
    RefreshDedupEntry,
    SensorInput,
    StrongTrackedFront,
    TraversalToken,
    ZoneBeliefState,
    ZoneModelSnapshot,
    ZonePolicyState,
    require_utc,
)

TARGET_SCHEMA = "zone-belief-v3"
LEGACY_V2_SCHEMA = "zone-belief-v2"
LEGACY_TARGET_SCHEMA = "zone-belief-shadow-v1"
LEGACY_EXACT_SCHEMA = "exact-augmented-v6"

V2_ALLOWED_ACTIVE_REASONS = frozenset(
    {
        "adjacent_authorized",
        "adjacent_current",
        "adjacent_recent",
        "boundary_authorized",
        "boundary_count_increase",
        "missed_edge_authorized",
        "same_zone_authorized",
        "same_zone_other_node",
    }
)


@dataclass(frozen=True)
class LegacySchema6Seed:
    """Validated schema-6 compatibility state retained until bootstrap."""

    expected_count: int
    active_seed: dict[str, bool]


@dataclass(frozen=True)
class LegacyV2Seed:
    """Conservative compatibility state retained until raw sensors bootstrap."""

    expected_count: int
    active_seed: dict[str, bool]


def legacy_target_map_fingerprint(predictive_map: PredictiveMap) -> str:
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


def target_map_fingerprint(predictive_map: PredictiveMap) -> str:
    """Fingerprint all map and profile inputs that can change v3 inference."""

    payload = {
        "nodes": {
            node_id: {
                "zone": node.occupancy_zone,
                "adjacent": sorted(node.adjacent),
                "transition_seconds": dict(sorted(node.transition_seconds.items())),
                "role": node.role,
                "occupancy_behavior": predictive_map.occupancy_behavior_for_node(
                    node
                ),
                "profile_name": profile_assignment_for_node(
                    predictive_map, node_id
                ).profile_name,
                "entities": dict(sorted(node.entities.items())),
                "reliability": node.reliability,
                "route_prior_weight": node.route_prior_weight,
            }
            for node_id, node in sorted(predictive_map.nodes.items())
        },
        "profiles": {
            name: _json_value(asdict(profile))
            for name, profile in sorted(SHARED_PROFILES.items())
        },
        "belief_profiles": {
            name: _json_value(asdict(profile))
            for name, profile in sorted(BELIEF_PROFILES.items())
        },
        "policy_calibrations": {
            name: _json_value(asdict(calibration))
            for name, calibration in sorted(POLICY_CALIBRATIONS.items())
        },
        "arrival_calibration": {
            "from_empty": ARRIVAL_FROM_EMPTY_PROBABILITY,
            "from_occupied": ARRIVAL_FROM_OCCUPIED_PROBABILITY,
        },
        "prediction_calibration": {
            "maturity_probability": PREDICTION_MATURITY_PROBABILITY,
            "maturity_support": PREDICTION_MATURITY_SUPPORT,
            "lease_seconds": LEASE_DURATION.total_seconds(),
        },
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
        "prediction": engine.prediction_manager.serialize(),
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
    prediction = root.get("prediction")
    if prediction is None:
        raise ValueError("Target prediction state is missing")
    candidate = ZoneModelEngine.restore(
        predictive_map,
        snapshot,
        audit,
        snapshot.updated_at,
    )
    candidate.restore_prediction_state(prediction, snapshot.updated_at)
    if restore_at > snapshot.updated_at:
        candidate.advance(restore_at, processing_at=restore_at, emit_events=False)
    return candidate


def migrate_schema6_seed(
    predictive_map: PredictiveMap,
    payload: object,
    sensor_snapshot: Sequence[SensorInput],
    at: datetime,
    *,
    expected_count: int | None = None,
) -> ZoneModelEngine:
    """Create a finite target seed without importing exact assignments."""

    require_utc(at, "Target migration time")
    seed = (
        payload
        if isinstance(payload, LegacySchema6Seed)
        else decode_schema6_seed(predictive_map, payload)
    )
    active_seed = _validated_active_seed(
        predictive_map,
        seed.active_seed,
        source="Schema-6",
    )
    resolved_count = _migration_count(seed.expected_count, expected_count)
    engine = ZoneModelEngine(
        predictive_map,
        resolved_count,
        at,
        active_seed=active_seed,
    )
    engine.bootstrap_sensor_snapshot(sensor_snapshot, at)
    return engine


def decode_schema6_seed(
    predictive_map: PredictiveMap,
    payload: object,
) -> LegacySchema6Seed:
    """Validate schema-6 state before retaining a deferred migration seed."""

    root = _mapping(payload, "Schema-6 state")
    if root.get("schema") != LEGACY_EXACT_SCHEMA:
        raise ValueError("Schema-6 migration source is incompatible")
    if root.get("map_fingerprint") != legacy_target_map_fingerprint(predictive_map):
        raise ValueError("Schema-6 migration map fingerprint is incompatible")
    occupants = root.get("occupants")
    if (
        not isinstance(occupants, int)
        or isinstance(occupants, bool)
        or not 0 <= occupants <= PRODUCT_MAX_OCCUPANTS
    ):
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
    return LegacySchema6Seed(
        occupants,
        _validated_active_seed(
            predictive_map,
            active_seed,
            source="Schema-6",
        ),
    )


def decode_v2_seed(
    predictive_map: PredictiveMap,
    payload: object,
) -> LegacyV2Seed:
    """Validate legacy v2 structure and retain only proven public active edges."""

    root = _mapping(payload, "V2 state")
    if root.get("schema") != LEGACY_V2_SCHEMA:
        raise ValueError("V2 migration source is incompatible")
    if root.get("map_fingerprint") != legacy_target_map_fingerprint(predictive_map):
        raise ValueError("V2 map fingerprint is incompatible")
    snapshot = _mapping(root.get("snapshot"), "V2 snapshot")
    _datetime(snapshot.get("updated_at"), "v2 snapshot updated_at")
    for field in (
        "episode_states",
        "belief_states",
        "traversal_tokens",
        "current_token_ids",
        "authorization_uses",
        "policy_states",
    ):
        _list(snapshot, field)
    count = _decode_count(snapshot.get("count_state"))
    audit_payload = root.get("audit")
    if not isinstance(audit_payload, list):
        raise ValueError("V2 audit must be a list")
    audit = tuple(_decode_policy_decision(item) for item in audit_payload)
    latest_edge: dict[str, PolicyDecision] = {}
    for row in sorted(audit, key=lambda item: (item.event_at, item.zone)):
        if row.event_kind in {"acquired", "released"}:
            latest_edge[row.zone] = row
    configured_zones = {
        node.zone for node in build_physical_nodes(predictive_map).nodes
    }
    active_seed: dict[str, bool] = {}
    for raw in _list(snapshot, "policy_states"):
        state = _mapping(raw, "V2 policy state")
        zone = _string(state, "zone")
        active = _boolean(state, "active")
        if zone not in configured_zones:
            raise ValueError("V2 policy zone is incompatible")
        edge = latest_edge.get(zone)
        active_seed[zone] = bool(
            active
            and edge is not None
            and edge.event_kind == "acquired"
            and edge.traversal_reason in V2_ALLOWED_ACTIVE_REASONS
        )
    return LegacyV2Seed(count.expected_count, active_seed)


def migrate_v2_seed(
    predictive_map: PredictiveMap,
    seed: LegacyV2Seed,
    sensor_snapshot: Sequence[SensorInput],
    at: datetime,
    *,
    expected_count: int | None = None,
) -> ZoneModelEngine:
    """Cold-build v3 from raw sensors while preserving only proven v2 active."""

    require_utc(at, "V2 migration time")
    engine = ZoneModelEngine(
        predictive_map,
        _migration_count(seed.expected_count, expected_count),
        at,
        active_seed=seed.active_seed,
    )
    engine.bootstrap_sensor_snapshot(sensor_snapshot, at)
    return engine


def _migration_count(stored: int, authoritative: int | None) -> int:
    """Validate both frontiers and prefer the current authoritative count."""

    for value in (stored, authoritative):
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= PRODUCT_MAX_OCCUPANTS
        ):
            raise ValueError("Migration occupant count is invalid")
    return stored if authoritative is None else authoritative


def _validated_active_seed(
    predictive_map: PredictiveMap,
    active_seed: Mapping[str, bool],
    *,
    source: str,
) -> dict[str, bool]:
    configured_zones = {
        node.zone for node in build_physical_nodes(predictive_map).nodes
    }
    if any(
        not isinstance(zone, str)
        or not isinstance(active, bool)
        or zone not in configured_zones
        for zone, active in active_seed.items()
    ):
        raise ValueError(f"{source} active seed is incompatible")
    return dict(active_seed)


def _decode_snapshot(value: object) -> ZoneModelSnapshot:
    data = _mapping(value, "Target snapshot")
    retained_raw = data.get("retained_traversal_tokens", [])
    if not isinstance(retained_raw, list):
        raise ValueError("Retained traversal tokens must be a list")
    return ZoneModelSnapshot(
        _datetime(data.get("updated_at"), "snapshot updated_at"),
        tuple(_decode_episode(item) for item in _list(data, "episode_states")),
        tuple(_decode_belief(item) for item in _list(data, "belief_states")),
        tuple(_decode_token(item) for item in _list(data, "traversal_tokens")),
        tuple(_strings(data.get("current_token_ids"), "current token IDs")),
        tuple(_decode_use(item) for item in _list(data, "authorization_uses")),
        _decode_count(data.get("count_state")),
        tuple(_decode_policy_state(item) for item in _list(data, "policy_states")),
        tuple(
            _decode_pending_candidate(item)
            for item in _list(data, "pending_candidates")
        ),
        tuple(_decode_strong_front(item) for item in _list(data, "strong_fronts")),
        tuple(
            _decode_count_conflict(item) for item in _list(data, "count_conflicts")
        ),
        tuple(_decode_token(item) for item in retained_raw),
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
        degradation_reason=_optional_string(
            data.get("degradation_reason"), "degradation reason"
        ),
        clear_emitted=_boolean(data, "clear_emitted"),
        health_warning=_boolean(data, "health_warning"),
        cadence_warning=_boolean(data, "cadence_warning"),
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
        _string(data, "track_confidence"),
        tuple(_strings(data.get("path_node_ids"), "token path node IDs")),
        _string(data, "provenance_kind"),
        _boolean(data, "equivalent_confirmed_strength"),
        _optional_datetime(
            data.get("continuity_reopened_at"),
            "token continuity reopening",
        ),
    )


def _decode_pending_candidate(value: object) -> PendingAcquisitionCandidate:
    data = _mapping(value, "Target pending candidate")
    return PendingAcquisitionCandidate(
        _string(data, "node_id"),
        _string(data, "zone"),
        _string(data, "profile_name"),
        _string(data, "episode_id"),
        _datetime(data.get("created_at"), "pending creation"),
        _datetime(data.get("expires_at"), "pending expiry"),
        _datetime(data.get("traversal_valid_until"), "pending traversal expiry"),
        _number(data, "reliability"),
    )


def _decode_strong_front(value: object) -> StrongTrackedFront:
    data = _mapping(value, "Target strong front")
    return StrongTrackedFront(
        _string(data, "front_id"),
        tuple(_strings(data.get("token_ids"), "strong-front token IDs")),
        tuple(_strings(data.get("node_ids"), "strong-front node IDs")),
        tuple(_strings(data.get("zones"), "strong-front zones")),
        tuple(_strings(data.get("episode_ids"), "strong-front episode IDs")),
        _datetime(data.get("valid_until"), "strong-front expiry"),
    )


def _decode_count_conflict(value: object) -> CountConflictState:
    data = _mapping(value, "Target count conflict")
    return CountConflictState(
        _string(data, "target_node_id"),
        _string(data, "target_zone"),
        _string(data, "target_episode_id"),
        _datetime(data.get("started_at"), "count-conflict start"),
        _datetime(data.get("last_evaluated_at"), "count-conflict evaluation"),
        _datetime(data.get("deadline"), "count-conflict deadline"),
        tuple(_strings(data.get("strong_front_ids"), "count-conflict front IDs")),
        _optional_datetime(data.get("degraded_at"), "count-conflict degradation"),
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
        _string(data, "phase"),
        _optional_string(data.get("activation_provenance"), "activation provenance"),
        _optional_datetime(
            data.get("prediction_expires_at"), "prediction policy expiry"
        ),
        _optional_string(
            data.get("prediction_source_episode_id"), "prediction source episode"
        ),
        _optional_number(data.get("prediction_probability"), "prediction probability"),
        _optional_number(data.get("prediction_support"), "prediction support"),
        _optional_string(data.get("activation_episode_id"), "activation episode"),
        _optional_datetime(data.get("activation_at"), "activation time"),
        _optional_string(data.get("activation_reason"), "activation reason"),
        _optional_string(
            data.get("activation_track_confidence"),
            "activation track confidence",
        ),
        tuple(
            _strings(
                data.get("activation_path_node_ids"),
                "activation path node IDs",
            )
        ),
        _optional_string(
            data.get("activation_provenance_kind"),
            "activation provenance kind",
        ),
        tuple(
            _strings(
                data.get("activation_source_episode_ids"),
                "activation source episode IDs",
            )
        ),
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
        tuple(
            _strings(
                data.get("count_conflict_front_ids", []),
                "audit count-conflict front IDs",
            )
        ),
        _optional_string(
            data.get("reliability_result"), "audit reliability result"
        ),
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


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Target {field} must be numeric or null")
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
    "LEGACY_V2_SCHEMA",
    "legacy_target_map_fingerprint",
    "LegacySchema6Seed",
    "LegacyV2Seed",
    "decode_schema6_seed",
    "decode_v2_seed",
    "migrate_schema6_seed",
    "migrate_v2_seed",
    "restore_target_state",
    "serialize_target_state",
    "target_map_fingerprint",
]
