from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .automation_policy import PendingDeparture
from .const import STORAGE_VERSION
from .model import PredictiveMap
from .observation_model import EntityEvidence
from .occupancy_state import (
    DirectionalContext,
    HypothesisKey,
    PositionState,
    Posterior,
    PredictionLease,
    ReleaseCause,
    WeightedHypothesis,
    ZonePolicyState,
    canonical_hypothesis,
    cold_start_posterior,
    hypothesis_sort_key,
    log_sum_exp,
    normalize_hypotheses,
)

OCCUPANCY_STORAGE_VERSION = STORAGE_VERSION


@dataclass(frozen=True)
class RestoredOccupancyState:
    posterior: Posterior
    directional_contexts: dict[HypothesisKey, tuple[DirectionalContext, ...]]
    policy_states: dict[str, ZonePolicyState]
    pending_departures: dict[str, PendingDeparture]
    prediction_leases: tuple[PredictionLease, ...]
    entity_states: dict[str, EntityEvidence]
    transition_counts: dict[str, dict[str, float]]
    update_sequence: int
    map_compatible: bool
    restore_status: str


def map_fingerprint(predictive_map: PredictiveMap) -> str:
    """Return a stable fingerprint for inference-relevant map structure."""

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


def serialize_occupancy_state(
    predictive_map: PredictiveMap,
    posterior: Posterior,
    policy_states: Mapping[str, ZonePolicyState],
    prediction_leases: tuple[PredictionLease, ...],
    entity_states: Mapping[str, EntityEvidence],
    transition_counts: Mapping[str, Mapping[str, float]],
    *,
    directional_contexts: Mapping[
        HypothesisKey,
        tuple[DirectionalContext, ...],
    ]
    | None = None,
    pending_departures: Mapping[str, PendingDeparture] | None = None,
    update_sequence: int = 0,
) -> dict[str, object]:
    """Serialize the complete restart-safe inference state."""

    return {
        "schema_version": OCCUPANCY_STORAGE_VERSION,
        "map_fingerprint": map_fingerprint(predictive_map),
        "zone_index": list(predictive_map.zones()),
        "directed_edges": [
            [source.node_id, target]
            for source in sorted(
                predictive_map.nodes.values(),
                key=lambda node: node.node_id,
            )
            for target in sorted(source.adjacent)
        ],
        "expected_occupants": len(posterior.hypotheses[0].key.positions),
        "updated_at": posterior.updated_at.isoformat(),
        "update_sequence": update_sequence,
        "posterior": [
            {
                "probability": math.exp(hypothesis.log_probability),
                "positions": [
                    {
                        "zone": position.zone,
                        "incoming_zone": position.incoming_zone,
                        "entered_at": _datetime_payload(position.entered_at),
                    }
                    for position in hypothesis.key.positions
                ],
            }
            for hypothesis in posterior.hypotheses
        ],
        "directional_contexts": [
            {
                "configuration_index": index,
                "contexts": [
                    {
                        "origin_zone": context.origin_zone,
                        "previous_node_id": context.previous_node_id,
                        "current_node_id": context.current_node_id,
                        "started_at": _datetime_payload(context.started_at),
                        "last_event_at": _datetime_payload(context.last_event_at),
                        "evidence_ids": list(context.evidence_ids),
                        "probability": math.exp(context.log_probability),
                        "disposition": context.disposition,
                    }
                    for context in (directional_contexts or {}).get(
                        hypothesis.key,
                        (
                            DirectionalContext(
                                None,
                                None,
                                None,
                                None,
                                None,
                                (),
                                hypothesis.log_probability,
                            ),
                        ),
                    )
                ],
            }
            for index, hypothesis in enumerate(posterior.hypotheses)
        ],
        "policy": {
            zone: {
                "keep_on": state.keep_on,
                "activation_expires_at": _datetime_payload(state.activation_expires_at),
                "last_trusted_at": _datetime_payload(state.last_trusted_at),
                "last_release_cause": (
                    None
                    if state.last_release_cause is None
                    else state.last_release_cause.value
                ),
                "recovery_eligible": state.recovery_eligible,
                "reason": state.reason,
                "evidence_ids": list(state.evidence_ids),
                "blocked_episode_ids": list(state.blocked_episode_ids),
            }
            for zone, state in sorted(policy_states.items())
        },
        "pending_departures": {
            origin: {
                "current": departure.current,
                "probability": departure.probability,
                "nonadjacent": departure.nonadjacent,
                "evidence_ids": list(departure.evidence_ids),
                "disposition": departure.disposition,
            }
            for origin, departure in sorted((pending_departures or {}).items())
        },
        "prediction_leases": [
            {
                "path_key": list(lease.path_key),
                "target_zone": lease.target_zone,
                "probability": lease.probability,
                "expires_at": lease.expires_at.isoformat(),
                "reason": lease.reason,
            }
            for lease in prediction_leases
        ],
        "entity_states": {
            entity_id: {
                "state": state.state,
                "log_likelihood_by_count": list(state.log_likelihood_by_count),
                "changed_at": state.changed_at.isoformat(),
                "episode_started_at": state.episode_started_at.isoformat(),
                "binding_signature": _binding_signature(
                    predictive_map,
                    entity_id,
                ),
            }
            for entity_id, state in sorted(entity_states.items())
        },
        "transition_counts": {
            source: dict(sorted(targets.items()))
            for source, targets in sorted(transition_counts.items())
        },
    }


def restore_occupancy_state(
    payload: Mapping[str, Any],
    predictive_map: PredictiveMap,
    expected_occupants: int,
    now: datetime,
) -> RestoredOccupancyState:
    """Validate and atomically reconstruct restart-safe inference state."""

    schema_version = payload.get("schema_version")
    if schema_version not in {2, OCCUPANCY_STORAGE_VERSION}:
        raise ValueError("unsupported occupancy storage schema")
    valid_zones = set(predictive_map.zones())
    policy_states = _restore_policy(
        payload.get("policy"),
        valid_zones,
        now,
        schema_version,
    )
    transition_counts = _filter_transition_counts(
        _restore_transition_counts(payload.get("transition_counts")),
        predictive_map,
    )
    map_compatible = schema_version == OCCUPANCY_STORAGE_VERSION and payload.get(
        "map_fingerprint"
    ) == map_fingerprint(predictive_map)
    if not map_compatible:
        posterior = cold_start_posterior(
            predictive_map.zones(),
            expected_occupants,
            now,
        )
        return RestoredOccupancyState(
            posterior=posterior,
            directional_contexts={
                hypothesis.key: (
                    DirectionalContext(
                        None,
                        None,
                        None,
                        None,
                        None,
                        (),
                        hypothesis.log_probability,
                    ),
                )
                for hypothesis in posterior.hypotheses
            },
            policy_states=policy_states,
            pending_departures={},
            prediction_leases=(),
            entity_states={},
            transition_counts=transition_counts,
            update_sequence=0,
            map_compatible=False,
            restore_status=(
                "migrated_policy_only" if schema_version == 2 else "map_changed_rebuilt"
            ),
        )

    if payload.get("expected_occupants") != expected_occupants:
        raise ValueError("stored occupant count does not match configuration")
    if payload.get("zone_index") != list(predictive_map.zones()):
        raise ValueError("stored zone index does not match the map")
    update_sequence = payload.get("update_sequence")
    if not isinstance(update_sequence, int) or update_sequence < 0:
        raise ValueError("stored update sequence is invalid")
    updated_at = _parse_datetime(payload.get("updated_at"), "updated_at")
    raw_posterior = payload.get("posterior")
    if not isinstance(raw_posterior, list) or not raw_posterior:
        raise ValueError("stored posterior must be a non-empty list")

    merged: dict[HypothesisKey, list[float]] = defaultdict(list)
    probability_total = 0.0
    for raw_hypothesis in raw_posterior:
        if not isinstance(raw_hypothesis, Mapping):
            raise ValueError("stored hypothesis must be a mapping")
        probability = _finite_probability(
            raw_hypothesis.get("probability"),
            allow_zero=True,
        )
        probability_total += probability
        raw_positions = raw_hypothesis.get("positions")
        if (
            not isinstance(raw_positions, list)
            or len(raw_positions) != expected_occupants
        ):
            raise ValueError("stored hypothesis occupant count is invalid")
        positions: list[PositionState] = []
        for raw_position in raw_positions:
            if not isinstance(raw_position, Mapping):
                raise ValueError("stored position must be a mapping")
            zone = raw_position.get("zone")
            incoming_zone = raw_position.get("incoming_zone")
            if zone is not None and not isinstance(zone, str):
                raise ValueError("stored position zone must be a string or null")
            if incoming_zone is not None and not isinstance(incoming_zone, str):
                raise ValueError("stored incoming zone must be a string or null")
            entered_at = _parse_optional_datetime(raw_position.get("entered_at"))
            if zone is not None and zone not in valid_zones:
                raise ValueError("stored posterior contains an unknown zone")
            elif incoming_zone is not None and incoming_zone not in valid_zones:
                raise ValueError("stored posterior contains an unknown incoming zone")
            positions.append(PositionState(zone, incoming_zone, entered_at))
        merged[canonical_hypothesis(positions)].append(
            -math.inf if probability == 0.0 else math.log(probability)
        )
    if not math.isclose(probability_total, 1.0, abs_tol=1e-12):
        raise ValueError("stored posterior probabilities must sum to one")
    normalized = normalize_hypotheses(
        {key: log_sum_exp(values) for key, values in merged.items()},
        updated_at,
    )
    normalized_weights = {
        hypothesis.key: hypothesis.log_probability
        for hypothesis in normalized.hypotheses
    }
    posterior = Posterior(
        tuple(
            sorted(
                (
                    WeightedHypothesis(
                        key,
                        normalized_weights.get(key, -math.inf),
                    )
                    for key in merged
                ),
                key=lambda item: (
                    -item.log_probability,
                    hypothesis_sort_key(item.key),
                ),
            )
        ),
        updated_at,
    )

    directional_contexts = _restore_directional_contexts(
        payload.get("directional_contexts"),
        posterior,
        predictive_map,
    )
    pending_departures = _restore_pending_departures(
        payload.get("pending_departures"),
        valid_zones,
    )
    prediction_leases = _restore_leases(
        payload.get("prediction_leases"),
        valid_zones,
        now,
    )
    entity_states = _restore_entity_states(
        payload.get("entity_states"),
        expected_occupants,
        predictive_map,
    )
    return RestoredOccupancyState(
        posterior=posterior,
        directional_contexts=directional_contexts,
        policy_states=policy_states,
        pending_departures=pending_departures,
        prediction_leases=prediction_leases,
        entity_states=entity_states,
        transition_counts=transition_counts,
        update_sequence=update_sequence,
        map_compatible=map_compatible,
        restore_status="restored",
    )


def _restore_policy(
    raw_policy: object,
    valid_zones: set[str],
    now: datetime,
    schema_version: int,
) -> dict[str, ZonePolicyState]:
    if not isinstance(raw_policy, Mapping):
        raise ValueError("stored policy must be a mapping")
    states = {zone: ZonePolicyState() for zone in valid_zones}
    for zone, raw_state in raw_policy.items():
        if zone not in valid_zones:
            continue
        if not isinstance(raw_state, Mapping):
            raise ValueError("stored zone policy must be a mapping")
        keep_on = raw_state.get("keep_on")
        reason = raw_state.get("reason")
        evidence_ids = raw_state.get("evidence_ids")
        blocked_episode_ids = raw_state.get("blocked_episode_ids", [])
        if not isinstance(keep_on, bool) or not isinstance(reason, str):
            raise ValueError("stored zone policy fields are invalid")
        if not isinstance(evidence_ids, list) or not all(
            isinstance(item, str) for item in evidence_ids
        ):
            raise ValueError("stored policy evidence IDs are invalid")
        if not isinstance(blocked_episode_ids, list) or not all(
            isinstance(item, str) for item in blocked_episode_ids
        ):
            raise ValueError("stored blocked episode IDs are invalid")
        release_cause: ReleaseCause | None = None
        recovery_eligible = False
        if schema_version >= 3:
            raw_release_cause = raw_state.get("last_release_cause")
            raw_recovery_eligible = raw_state.get("recovery_eligible")
            if raw_release_cause is not None and not isinstance(
                raw_release_cause,
                str,
            ):
                raise ValueError("stored policy release cause is invalid")
            try:
                release_cause = (
                    None
                    if raw_release_cause is None
                    else ReleaseCause(raw_release_cause)
                )
            except ValueError as exc:
                raise ValueError("stored policy release cause is invalid") from exc
            if not isinstance(raw_recovery_eligible, bool):
                raise ValueError("stored policy recovery eligibility is invalid")
            recovery_eligible = raw_recovery_eligible
            if (
                recovery_eligible
                and release_cause != ReleaseCause.PROVISIONAL_FALSE_OFF
            ):
                raise ValueError("stored recovery eligibility has an invalid cause")
        activation_expires_at = _parse_optional_datetime(
            raw_state.get("activation_expires_at")
        )
        if activation_expires_at is not None and activation_expires_at <= now:
            activation_expires_at = None
        states[str(zone)] = ZonePolicyState(
            keep_on=keep_on,
            activation_expires_at=activation_expires_at,
            last_trusted_at=_parse_optional_datetime(raw_state.get("last_trusted_at")),
            last_release_cause=release_cause,
            recovery_eligible=recovery_eligible,
            reason=reason,
            evidence_ids=tuple(evidence_ids),
            blocked_episode_ids=tuple(blocked_episode_ids),
        )
    return states


def _restore_leases(
    raw_leases: object,
    valid_zones: set[str],
    now: datetime,
) -> tuple[PredictionLease, ...]:
    if not isinstance(raw_leases, list):
        raise ValueError("stored prediction leases must be a list")
    leases: list[PredictionLease] = []
    for raw_lease in raw_leases:
        if not isinstance(raw_lease, Mapping):
            raise ValueError("stored prediction lease must be a mapping")
        path_key = raw_lease.get("path_key")
        target_zone = raw_lease.get("target_zone")
        reason = raw_lease.get("reason")
        if (
            not isinstance(path_key, list)
            or len(path_key) != 3
            or not isinstance(path_key[0], str)
            or not isinstance(path_key[2], str)
            or not (path_key[1] is None or isinstance(path_key[1], str))
            or not isinstance(target_zone, str)
            or not isinstance(reason, str)
        ):
            raise ValueError("stored prediction lease fields are invalid")
        probability = _finite_probability(raw_lease.get("probability"))
        expires_at = _parse_datetime(raw_lease.get("expires_at"), "lease expiry")
        if expires_at <= now:
            continue
        if target_zone not in valid_zones or any(
            zone is not None and zone not in valid_zones for zone in path_key
        ):
            continue
        leases.append(
            PredictionLease(
                (path_key[0], path_key[1], path_key[2]),
                target_zone,
                probability,
                expires_at,
                reason,
            )
        )
    return tuple(sorted(leases, key=lambda lease: lease.path_key))


def _restore_entity_states(
    raw_states: object,
    expected_occupants: int,
    predictive_map: PredictiveMap,
) -> dict[str, EntityEvidence]:
    if not isinstance(raw_states, Mapping):
        raise ValueError("stored entity states must be a mapping")
    states: dict[str, EntityEvidence] = {}
    for entity_id, raw_state in raw_states.items():
        if not isinstance(entity_id, str) or not isinstance(raw_state, Mapping):
            raise ValueError("stored entity evidence entry is invalid")
        state = raw_state.get("state")
        values = raw_state.get("log_likelihood_by_count")
        if not isinstance(state, str) or not isinstance(values, list):
            raise ValueError("stored entity evidence fields are invalid")
        if raw_state.get("binding_signature") != _binding_signature(
            predictive_map,
            entity_id,
        ):
            raise ValueError("stored entity binding signature is invalid")
        if len(values) != expected_occupants + 1 or not all(
            isinstance(value, int | float) and math.isfinite(value) for value in values
        ):
            raise ValueError("stored likelihood vector is invalid")
        states[entity_id] = EntityEvidence(
            state=state,
            log_likelihood_by_count=tuple(float(value) for value in values),
            changed_at=_parse_datetime(raw_state.get("changed_at"), "changed_at"),
            episode_started_at=_parse_datetime(
                raw_state.get("episode_started_at"),
                "episode_started_at",
            ),
        )
    return states


def _restore_directional_contexts(
    raw_contexts: object,
    posterior: Posterior,
    predictive_map: PredictiveMap,
) -> dict[HypothesisKey, tuple[DirectionalContext, ...]]:
    if not isinstance(raw_contexts, list):
        raise ValueError("stored directional contexts must be a list")
    by_index: dict[int, tuple[DirectionalContext, ...]] = {}
    valid_zones = set(predictive_map.zones())
    valid_nodes = set(predictive_map.nodes)
    for raw_entry in raw_contexts:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("stored directional context entry must be a mapping")
        index = raw_entry.get("configuration_index")
        variants = raw_entry.get("contexts")
        if (
            not isinstance(index, int)
            or index in by_index
            or not isinstance(variants, list)
            or not 1 <= len(variants) <= 4
        ):
            raise ValueError("stored directional context entry is invalid")
        contexts: list[DirectionalContext] = []
        for raw_context in variants:
            if not isinstance(raw_context, Mapping):
                raise ValueError("stored directional context must be a mapping")
            origin = raw_context.get("origin_zone")
            previous_node = raw_context.get("previous_node_id")
            current_node = raw_context.get("current_node_id")
            evidence_ids = raw_context.get("evidence_ids")
            disposition = raw_context.get("disposition", "contextless")
            if (
                not (origin is None or origin in valid_zones)
                or not (previous_node is None or previous_node in valid_nodes)
                or not (current_node is None or current_node in valid_nodes)
                or not isinstance(evidence_ids, list)
                or not all(isinstance(item, str) for item in evidence_ids)
                or disposition
                not in {
                    "contextless",
                    "graph_valid",
                    "missed_movement",
                    "missed_timing",
                }
            ):
                raise ValueError("stored directional context fields are invalid")
            contexts.append(
                DirectionalContext(
                    origin_zone=origin,
                    previous_node_id=previous_node,
                    current_node_id=current_node,
                    started_at=_parse_optional_datetime(raw_context.get("started_at")),
                    last_event_at=_parse_optional_datetime(
                        raw_context.get("last_event_at")
                    ),
                    evidence_ids=tuple(evidence_ids),
                    log_probability=(
                        -math.inf
                        if (
                            probability := _finite_probability(
                                raw_context.get("probability"),
                                allow_zero=True,
                            )
                        )
                        == 0.0
                        else math.log(probability)
                    ),
                    disposition=disposition,
                )
            )
        by_index[index] = tuple(contexts)
    if set(by_index) != set(range(len(posterior.hypotheses))):
        raise ValueError("stored directional contexts do not cover the posterior")
    restored = {
        hypothesis.key: by_index[index]
        for index, hypothesis in enumerate(posterior.hypotheses)
    }
    for hypothesis in posterior.hypotheses:
        if not math.isclose(
            log_sum_exp(
                context.log_probability for context in restored[hypothesis.key]
            ),
            hypothesis.log_probability,
            abs_tol=1e-12,
        ):
            raise ValueError("stored directional context mass is invalid")
    return restored


def _restore_pending_departures(
    raw_departures: object,
    valid_zones: set[str],
) -> dict[str, PendingDeparture]:
    if not isinstance(raw_departures, Mapping):
        raise ValueError("stored pending departures must be a mapping")
    departures: dict[str, PendingDeparture] = {}
    for origin, raw_departure in raw_departures.items():
        if (
            not isinstance(origin, str)
            or origin not in valid_zones
            or not isinstance(raw_departure, Mapping)
        ):
            raise ValueError("stored pending departure entry is invalid")
        current = raw_departure.get("current")
        nonadjacent = raw_departure.get("nonadjacent")
        evidence_ids = raw_departure.get("evidence_ids")
        disposition = raw_departure.get(
            "disposition",
            "missed_movement" if nonadjacent else "graph_valid",
        )
        if (
            not isinstance(current, str)
            or current not in valid_zones
            or not isinstance(nonadjacent, bool)
            or not isinstance(evidence_ids, list)
            or not all(isinstance(item, str) for item in evidence_ids)
            or disposition not in {"graph_valid", "missed_movement", "missed_timing"}
        ):
            raise ValueError("stored pending departure fields are invalid")
        departures[origin] = PendingDeparture(
            origin=origin,
            current=current,
            probability=_finite_probability(raw_departure.get("probability")),
            nonadjacent=nonadjacent,
            evidence_ids=tuple(evidence_ids),
            disposition=disposition,
        )
    return departures


def _restore_transition_counts(raw_counts: object) -> dict[str, dict[str, float]]:
    if not isinstance(raw_counts, Mapping):
        raise ValueError("stored transition counts must be a mapping")
    counts: dict[str, dict[str, float]] = {}
    for source, raw_targets in raw_counts.items():
        if not isinstance(source, str) or not isinstance(raw_targets, Mapping):
            raise ValueError("stored transition count entry is invalid")
        targets: dict[str, float] = {}
        for target, value in raw_targets.items():
            if (
                not isinstance(target, str)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("stored transition count is invalid")
            targets[target] = float(value)
        counts[source] = targets
    return counts


def _filter_transition_counts(
    counts: dict[str, dict[str, float]],
    predictive_map: PredictiveMap,
) -> dict[str, dict[str, float]]:
    return {
        source: {
            target: value
            for target, value in targets.items()
            if source in predictive_map.nodes
            and target in predictive_map.nodes[source].adjacent
        }
        for source, targets in counts.items()
        if source in predictive_map.nodes
        and any(target in predictive_map.nodes[source].adjacent for target in targets)
    }


def _binding_signature(
    predictive_map: PredictiveMap,
    entity_id: str,
) -> dict[str, object]:
    binding = predictive_map.entity_binding_for_entity(entity_id)
    if binding is None:
        return {}
    node = predictive_map.nodes[binding.node_id]
    return {
        "entity_id": entity_id,
        "node_id": node.node_id,
        "zone": node.occupancy_zone,
        "signal_type": binding.signal_type,
        "role": node.role,
        "occupancy_behavior": predictive_map.occupancy_behavior_for_node(node),
        "reliability_profile": "observation_profiles_v1",
        "graph_version": map_fingerprint(predictive_map),
    }


def _finite_probability(value: object, *, allow_zero: bool = False) -> float:
    if (
        not isinstance(value, int | float)
        or not math.isfinite(value)
        or not (0.0 <= value <= 1.0 if allow_zero else 0.0 < value <= 1.0)
    ):
        raise ValueError("stored probability is invalid")
    return float(value)


def _parse_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"stored {field} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"stored {field} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"stored {field} must include a timezone")
    return parsed


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, "optional datetime")


def _datetime_payload(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
