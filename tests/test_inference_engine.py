from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import custom_components.predictive_controls.inference.engine as engine_module
from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference.association import EndpointFactor
from custom_components.predictive_controls.inference.engine import (
    ExactInferenceEngine,
)
from custom_components.predictive_controls.inference.factor_chain import (
    ExactFactorChain,
)
from custom_components.predictive_controls.inference.legacy_adapter import (
    LegacyInferenceEngine,
)
from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
)
from custom_components.predictive_controls.inference.policy import (
    PosteriorEventPolicy,
)
from custom_components.predictive_controls.inference.port import (
    InferenceEngine,
)
from custom_components.predictive_controls.inference.reducer import (
    FactorChainReplayState,
)
from custom_components.predictive_controls.inference.replay import (
    RetainedReplayCoordinator,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.support import (
    injective_support_probability,
)
from custom_components.predictive_controls.inference.types import (
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.occupancy_graph import ZoneGraph
from custom_components.predictive_controls.occupancy_persistence import (
    restore_occupancy_state,
)
from custom_components.predictive_controls.occupancy_state import ZonePolicyState
from custom_components.predictive_controls.occupancy_tracker import (
    OccupancyTracker,
    TrackerConfig,
)
from custom_components.predictive_controls.policy_audit import (
    MAX_UNCOMPRESSED_CONTEXT_BYTES,
    pack_policy_audit_payload,
    policy_audit_context_payload,
    validate_target_policy_audit_context,
)
from custom_components.predictive_controls.status import tracker_diagnostics_payload
from custom_components.predictive_controls.yaml_config import load_predictive_map
from tests.differential_runner import DifferentialRunner

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office"],
                },
            }
        }
    )


def make_behavior_map(behavior: str) -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "occupancy_behavior": behavior,
                },
                "hall": {
                    "entities": {"motion": "binary_sensor.hall"},
                },
            }
        }
    )


def make_event() -> OccupancyEvent:
    return OccupancyEvent(
        "binary_sensor.office",
        "office",
        "office",
        "first_floor",
        "room_occupancy",
        "sustained",
        "motion",
        "on",
        NOW,
        0.8,
    )


def make_corroboration_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "source": {
                    "zone": "source",
                    "entities": {"motion": "binary_sensor.source"},
                    "adjacent": [],
                },
                "target_a": {
                    "zone": "target",
                    "entities": {
                        "motion": "binary_sensor.target_a",
                        "presence": "binary_sensor.target_a_alias",
                    },
                    "adjacent": [],
                },
                "target_b": {
                    "zone": "target",
                    "entities": {"motion": "binary_sensor.target_b"},
                    "adjacent": [],
                },
                "other": {
                    "zone": "other",
                    "entities": {"motion": "binary_sensor.other"},
                    "adjacent": [],
                },
            }
        }
    )


def make_prediction_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
                "living": {
                    "entities": {"motion": "binary_sensor.living"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def mapped_event(
    node_id: str,
    zone: str,
    seconds: int,
    *,
    entity_id: str | None = None,
) -> OccupancyEvent:
    return OccupancyEvent(
        entity_id or f"binary_sensor.{node_id}",
        node_id,
        zone,
        "first_floor",
        "room_occupancy",
        "sustained",
        "motion",
        "on",
        NOW + timedelta(seconds=seconds),
        1.0,
    )


def direct_arrival_probability(
    engine: ExactInferenceEngine,
    zone: str,
) -> float:
    factor = max(
        (
            step
            for step in engine._chain.steps  # noqa: SLF001
            if isinstance(step, EndpointFactor) and step.target_zone == zone
        ),
        key=lambda step: (step.endpoint.event_at, step.endpoint.token_id),
    )
    return engine._chain.assignment_and_terminal_probability(  # noqa: SLF001
        factor.endpoint.token_id,
        lambda atom: atom.disposition
        in {"graph_valid", "censored_graph_path", "unlocated"},
        lambda configuration: configuration[factor.target_index] > 0,
    )


def test_exact_engine_applies_physical_node_episode_evidence() -> None:
    engine = ExactInferenceEngine(make_map(), 2)

    assert isinstance(engine, InferenceEngine)
    diagnostics = engine.observe(make_event(), emit_activation=True)

    assert diagnostics.expected_occupants == 2
    assert diagnostics.occupied_marginals["office"] > 0.0
    assert diagnostics.occupied_marginals["hall"] == 0.0
    assert diagnostics.normalization == pytest.approx(1.0, abs=1e-12)
    assert diagnostics.pruned_probability == 0.0
    assert diagnostics.event_disposition == "accepted_positive"
    assert diagnostics.episode_states
    assert diagnostics.unresolved_assignment_count == 1
    assert diagnostics.factor_step_count == 1
    assert diagnostics.retained_input_count == 1
    assert diagnostics.consumed_endpoint_count == 0
    assert not diagnostics.overloaded
    assert engine.finalize(NOW + timedelta(minutes=1))
    assert engine.diagnostics.updated_at == NOW


def test_unrelated_fresh_target_does_not_republish_historical_arrival() -> None:
    predictive_map = make_map()
    policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.0,
        release_threshold=1.0,
    )
    engine = ExactInferenceEngine(predictive_map, 1, policy=policy)

    office = engine.observe(
        mapped_event("office", "office", 0),
        emit_activation=True,
    )
    hall = engine.observe(
        mapped_event("hall", "hall", 1),
        emit_activation=True,
    )

    assert office.policy_states["office"].keep_on
    assert set(office.arrival_supported_probabilities) == {"office"}
    assert set(hall.arrival_supported_probabilities) == {"hall"}
    assert not any(
        decision.action == "activate" and decision.zone == "office"
        for decision in hall.policy_decisions
    )


def test_target_policy_audit_exposes_reconstructable_public_context() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )

    tracker.observe(make_event())

    audit = tracker.diagnostics.joint_target_policy_audit
    assert audit
    assert all(entry.context is not None for entry in audit)
    context = audit[-1].context
    assert context is not None
    assert len(context.compressed_json) <= MAX_UNCOMPRESSED_CONTEXT_BYTES
    expanded = validate_target_policy_audit_context(context)
    assert expanded["occupants"] == 1
    assert expanded["normalization"] == pytest.approx(1.0, abs=1e-12)
    assert expanded["pruned_probability"] == 0.0

    audit = tracker_diagnostics_payload(tracker.diagnostics)["joint"]["policy_audit"]
    accepted = next(
        entry
        for entry in audit
        if entry["decision"]["accepted"]
        and entry["decision"]["reason_code"] == "arrival_supported"
    )
    context = accepted["context"]
    assert context["encoding"] == "zlib-json-v1"
    assert context["data"]


def test_target_policy_audit_context_round_trips_complete_exact_state() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    entry = tracker.diagnostics.joint_target_policy_audit[-1]
    assert entry.context is not None

    context = validate_target_policy_audit_context(entry.context)
    assert context["schema"] == "exact-policy-audit-v2"
    assert context["zones"] == ["hall", "office"]
    assert context["occupants"] == 1
    assert context["message"]
    assert context["chain"]
    assert context["episodes"]
    assert context["replay"]
    arrival_supported = cast(dict[str, object], context["arrival_supported"])
    probabilities = cast(dict[str, float], arrival_supported["probabilities"])
    targets = cast(dict[str, str], arrival_supported["targets"])
    performance = cast(dict[str, object], context["performance"])
    assert probabilities["office"] == pytest.approx(
        entry.decision.gate_values["probability"],
        abs=1e-12,
    )
    assert targets == {
        "office": f"office@{NOW.isoformat()}"
    }
    assert performance["prediction_used_for_policy"] is False

    payload = tracker.occupancy_store_data(NOW, {})
    restored = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    restored.restore_joint_state(payload)
    restored_entry = restored.diagnostics.joint_target_policy_audit[-1]
    assert restored_entry.context == entry.context
    assert policy_audit_context_payload(restored_entry.context)


def test_tracker_zone_projection_defaults_for_unknown_zone() -> None:
    tracker = OccupancyTracker(make_map(), TrackerConfig(expected_occupants=1))

    state = tracker._zone_state_from_diagnostics(  # noqa: SLF001
        "unknown",
        tracker._engine_diagnostics,  # noqa: SLF001
    )

    assert state.zone == "unknown"


def _expanded_target_audit_context() -> dict[str, object]:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    packed = tracker.diagnostics.joint_target_policy_audit[-1].context
    assert packed is not None
    return validate_target_policy_audit_context(packed)


def test_target_policy_audit_semantics_reuses_operator_cache() -> None:
    context = _expanded_target_audit_context()
    cache: dict[tuple[tuple[str, ...], int], object] = {}

    engine_module._validate_target_policy_audit_semantics(context, cache)  # type: ignore[arg-type]  # noqa: SLF001
    engine_module._validate_target_policy_audit_semantics(context, cache)  # type: ignore[arg-type]  # noqa: SLF001

    assert cache


@pytest.mark.parametrize(
    "mutate",
    (
        lambda context: context.update(zones=[]),
        lambda context: context.update(normalization=0.9),
        lambda context: context.update(pruned_probability=0.1),
    ),
)
def test_target_policy_audit_rejects_invalid_top_level_semantics(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    context = _expanded_target_audit_context()
    mutate(context)

    with pytest.raises(ValueError, match="context semantics"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001


def test_target_policy_audit_rejects_invalid_arrival_semantics() -> None:
    context = _expanded_target_audit_context()
    arrivals = cast(dict[str, object], context["arrival_supported"])

    arrivals["targets"] = {}
    with pytest.raises(ValueError, match="arrival-supported evidence"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001

    context = _expanded_target_audit_context()
    arrivals = cast(dict[str, object], context["arrival_supported"])
    targets = cast(dict[str, object], arrivals["targets"])
    targets["office"] = ""
    with pytest.raises(ValueError, match="arrival-supported evidence"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001

    context = _expanded_target_audit_context()
    context["schema"] = "exact-policy-audit-v1"
    arrivals = cast(dict[str, object], context["arrival_supported"])
    arrivals["probabilities"] = {}
    with pytest.raises(ValueError, match="arrival-supported evidence"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001

    context = _expanded_target_audit_context()
    arrivals = cast(dict[str, object], context["arrival_supported"])
    probabilities = cast(dict[str, object], arrivals["probabilities"])
    probabilities["office"] = 0.0
    with pytest.raises(ValueError, match="arrival-supported evidence"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001


def _release_context(
    probability: object,
    zone_result: object,
) -> dict[str, object]:
    context = _expanded_target_audit_context()
    context["release_safe"] = {
        "probabilities": {"office": probability},
        "evidence": {"zones": {"office": zone_result}},
    }
    return context


@pytest.mark.parametrize(
    "context",
    (
        {"probabilities": [], "evidence": {}},
        {"probabilities": {}, "evidence": {"zones": []}},
    ),
)
def test_target_policy_audit_rejects_invalid_release_containers(
    context: dict[str, object],
) -> None:
    payload = _expanded_target_audit_context()
    payload["release_safe"] = context

    with pytest.raises(ValueError, match="release-safe evidence"):
        engine_module._validate_target_policy_audit_semantics(payload)  # noqa: SLF001


@pytest.mark.parametrize(
    "context",
    (
        _release_context(2.0, {}),
        _release_context(
            0.5,
            {"veto": "sustained_positive", "strata": []},
        ),
        _release_context(0.0, {"probability": "bad", "strata": []}),
        _release_context(0.0, {"probability": 0.0, "strata": ["bad"]}),
        _release_context(
            0.0,
            {
                "probability": 0.0,
                "strata": [
                    {
                        "occupancy_rank": True,
                        "probability": 0.0,
                        "qualifies": False,
                        "matching": [],
                        "reasons": ["insufficient_support"],
                    }
                ],
            },
        ),
        _release_context(
            0.0,
            {
                "probability": 0.0,
                "strata": [
                    {
                        "occupancy_rank": 0,
                        "probability": 0.0,
                        "qualifies": True,
                        "matching": [],
                        "reasons": ["unexpected"],
                    }
                ],
            },
        ),
        _release_context(
            0.0,
            {
                "probability": 0.0,
                "strata": [
                    {
                        "occupancy_rank": 0,
                        "probability": 0.0,
                        "qualifies": False,
                        "matching": [],
                        "reasons": [],
                    }
                ],
            },
        ),
        _release_context(0.5, {"probability": 0.0, "strata": []}),
    ),
)
def test_target_policy_audit_rejects_invalid_release_strata(
    context: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="release-safe evidence"):
        engine_module._validate_target_policy_audit_semantics(context)  # noqa: SLF001


def test_target_policy_audit_validates_episode_and_support_shapes() -> None:
    with pytest.raises(ValueError, match="episode evidence"):
        engine_module._decode_audit_corroborations({})  # noqa: SLF001
    with pytest.raises(ValueError, match="episode evidence"):
        engine_module._decode_audit_corroborations(["bad"])  # noqa: SLF001
    with pytest.raises(ValueError, match="episode evidence"):
        engine_module._decode_audit_corroborations(  # noqa: SLF001
            [{"zone": 3, "node_id": "node", "current_positive": False}]
        )

    space = StateSpace(("office", "hall"), 1)
    office_rank = space.rank((1, 0, 0))
    with pytest.raises(ValueError, match="release-safe evidence"):
        engine_module._validate_support_matching(space, office_rank, ["bad"])  # noqa: SLF001
    with pytest.raises(ValueError, match="release-safe evidence"):
        engine_module._validate_support_matching(  # noqa: SLF001
            space,
            office_rank,
            [{"destination_zone": "office", "support_event_id": "support"}],
        )
    with pytest.raises(ValueError, match="release-safe evidence"):
        engine_module._validate_support_matching(  # noqa: SLF001
            space,
            office_rank,
            [
                {
                    "destination_zone": "hall",
                    "support_event_id": "support",
                    "endpoint_ids": ["endpoint"],
                    "episode_ids": ["episode"],
                }
            ],
        )


def test_exact_engine_defensive_codec_and_audit_helpers() -> None:
    payload = cast(
        dict[str, object],
        ExactInferenceEngine(make_map(), 1).serialize(NOW, {}),
    )
    payload["occupants"] = 3
    with pytest.raises(ValueError, match="between zero and two"):
        ExactInferenceEngine(make_map(), 1).restore(payload)

    engine = ExactInferenceEngine(make_map(), 1)
    with pytest.raises(RuntimeError, match="policy is unavailable"):
        engine._target_policy_audit_context(  # noqa: SLF001
            NOW,
            {},
            True,
            {},
            {},
        )

    predicate = engine_module._assignment_alternative_predicate("match")  # noqa: SLF001
    factor = EndpointAlternative(
        "match",
        "stay",
        None,
        None,
        (),
        0.0,
        NOW,
        (),
    )
    atom = EndpointAssignmentAtom(
        "endpoint",
        "match",
        "stay",
        0,
        0,
        None,
        1,
        None,
        "target-node",
        (),
        NOW,
        (),
    )
    assert predicate(atom)
    assert engine_module._terminal_alternative_predicate("match")(factor)  # noqa: SLF001

    space = StateSpace(("office", "hall"), 1)
    operators = CompleteMoveOperators(space)
    with pytest.raises(ValueError, match="factor-chain state"):
        engine_module._decode_chain(  # noqa: SLF001
            {"occupants": 1, "steps": {}},
            space,
            operators,
        )
    with pytest.raises(ValueError, match="sparse log vector"):
        engine_module._decode_log_vector(  # noqa: SLF001
            {
                "encoding": "sparse-log-vector-v1",
                "length": len(space),
                "default": -math.inf,
                "entries": {},
            },
            space,
        )


def test_exact_policy_audit_entry_context_validation_cache() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = cast(dict[str, object], payload["policy"])
    entry = deepcopy(cast(list[dict[str, object]], policy["audit"])[-1])
    cache: set[bytes] = set()
    operators: dict[
        tuple[tuple[str, ...], int],
        tuple[StateSpace, CompleteMoveOperators],
    ] = {}

    decoded = engine_module._decode_policy_audit_entry(  # noqa: SLF001
        entry,
        cache,
        operators,
    )
    assert decoded.context is not None
    assert cache
    assert engine_module._decode_policy_audit_entry(  # noqa: SLF001
        entry,
        cache,
        operators,
    ).context == decoded.context
    assert engine_module._decode_policy_audit_entry(entry).context == decoded.context  # noqa: SLF001

    entry["context"] = None
    assert engine_module._decode_policy_audit_entry(entry).context is None  # noqa: SLF001
    entry["context"] = []
    with pytest.raises(ValueError, match="context is invalid"):
        engine_module._decode_policy_audit_entry(entry)  # noqa: SLF001


def test_exact_engine_uses_adjacent_insertion_checkpoint() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    first = replace(
        make_event(),
        event_at=NOW + timedelta(seconds=2, milliseconds=100),
    )
    last = replace(make_event(), event_at=NOW + timedelta(seconds=3))
    inserted = replace(
        make_event(),
        entity_id="binary_sensor.hall",
        node_id="hall",
        zone="hall",
        event_at=NOW + timedelta(seconds=2, milliseconds=600),
    )

    engine.observe_received(
        first,
        receive_at=NOW + timedelta(seconds=2, milliseconds=100),
        emit_activation=False,
    )
    engine.observe_received(
        last,
        receive_at=NOW + timedelta(seconds=3),
        emit_activation=False,
    )
    diagnostics = engine.observe_received(
        inserted,
        receive_at=NOW + timedelta(seconds=3, milliseconds=500),
        emit_activation=False,
    )

    assert diagnostics.event_disposition == "accepted_positive"
    assert diagnostics.normalization == pytest.approx(1.0, abs=1e-12)


def test_exact_engine_rejects_positive_without_endpoint_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ExactInferenceEngine._apply_replay_state

    def remove_endpoint(
        engine: ExactInferenceEngine,
        state: FactorChainReplayState,
        watermark: datetime,
    ) -> None:
        original(engine, state, watermark)
        engine._chain = ExactFactorChain(engine._posterior)  # noqa: SLF001

    monkeypatch.setattr(ExactInferenceEngine, "_apply_replay_state", remove_endpoint)
    engine = ExactInferenceEngine(make_map(), 1)

    with pytest.raises(ValueError, match="resolve to one endpoint factor"):
        engine.observe(make_event(), emit_activation=False)


@pytest.mark.parametrize("occupants", range(6))
def test_target_policy_audit_sparse_chain_is_hermetic_and_audit_only(
    occupants: int,
) -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=occupants,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    entry = tracker.diagnostics.joint_target_policy_audit[-1]
    assert entry.context is not None
    context = validate_target_policy_audit_context(entry.context)
    chain = cast(dict[str, object], context["chain"])
    assert cast(dict[str, object], chain["base"])["encoding"] == (
        "sparse-log-vector-v1"
    )
    assert cast(dict[str, object], chain["posterior"])["encoding"] == (
        "sparse-log-vector-v1"
    )

    payload = tracker.occupancy_store_data(NOW, {})
    persisted_chain = cast(dict[str, object], payload["chain"])
    assert isinstance(persisted_chain["base"], list)
    assert isinstance(persisted_chain["posterior"], list)
    restored = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=occupants,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    restored.restore_joint_state(payload)
    assert restored.diagnostics.joint_target_policy_audit[-1].context == entry.context


def test_policy_audit_sample_frontier_advances_only_after_successful_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_policy = PosteriorEventPolicy(
        make_map().zones(),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    engine = ExactInferenceEngine(make_map(), 1, policy=target_policy)

    def reject_context(*_args: object) -> object:
        raise ValueError("context packing failed")

    monkeypatch.setattr(engine, "_target_policy_audit_context", reject_context)

    with pytest.raises(ValueError, match="context packing failed"):
        engine._apply_policy(NOW, emit_activation=False)  # noqa: SLF001

    assert engine._last_policy_audit_context_at is None  # noqa: SLF001
    assert target_policy.audit == ()


def test_policy_audit_sample_frontier_never_moves_backward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_policy = PosteriorEventPolicy(
        make_map().zones(),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    engine = ExactInferenceEngine(make_map(), 1, policy=target_policy)
    sampled_at: list[datetime] = []

    def context_at(now: datetime, *_args: object) -> object:
        sampled_at.append(now)
        return pack_policy_audit_payload({"schema": "test-audit-context"})

    monkeypatch.setattr(engine, "_target_policy_audit_context", context_at)

    engine._apply_policy(NOW, emit_activation=False)  # noqa: SLF001
    engine._apply_policy(  # noqa: SLF001
        NOW - timedelta(seconds=1), emit_activation=False
    )
    engine._apply_policy(  # noqa: SLF001
        NOW + timedelta(seconds=29), emit_activation=False
    )
    engine._apply_policy(  # noqa: SLF001
        NOW + timedelta(seconds=30), emit_activation=False
    )

    assert sampled_at == [NOW, NOW + timedelta(seconds=30)]
    assert engine._last_policy_audit_context_at == NOW + timedelta(  # noqa: SLF001
        seconds=30
    )


def test_policy_audit_sample_frontier_restores_newest_complete_context() -> None:
    target_policy = PosteriorEventPolicy(
        make_map().zones(),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    context = pack_policy_audit_payload({"schema": "test-audit-context"})
    target_policy.apply(
        NOW,
        1,
        {"office": 0.1},
        False,
        {},
        emit_activation=False,
        audit_context=context,
    )
    target_policy.apply(
        NOW + timedelta(seconds=1),
        1,
        {"office": 0.2},
        False,
        {},
        emit_activation=False,
    )

    engine = ExactInferenceEngine(make_map(), 1, policy=target_policy)

    assert engine._last_policy_audit_context_at == NOW  # noqa: SLF001


@pytest.mark.parametrize(
    "mutate",
    (
        lambda vector: vector.__setitem__("encoding", "unknown"),
        lambda vector: vector.__setitem__("length", 1_000_000),
        lambda vector: vector.__setitem__("default", 0.0),
        lambda vector: vector.__setitem__("entries", [[True, 0.0]]),
        lambda vector: vector.__setitem__("entries", [[-1, 0.0]]),
        lambda vector: vector.__setitem__("entries", [[0, 0.0], [0, 0.0]]),
        lambda vector: vector.__setitem__("entries", [[1, 0.0], [0, 0.0]]),
        lambda vector: vector.__setitem__("entries", [[0, "invalid"]]),
    ),
)
def test_target_policy_audit_rejects_malformed_sparse_vectors(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = cast(dict[str, object], payload["policy"])
    audit = cast(list[dict[str, object]], policy["audit"])
    envelope = cast(dict[str, object], audit[-1]["context"])
    packed = tracker.diagnostics.joint_target_policy_audit[-1].context
    assert packed is not None
    context = validate_target_policy_audit_context(packed)
    chain = cast(dict[str, object], context["chain"])
    mutate(cast(dict[str, object], chain["base"]))
    malformed = pack_policy_audit_payload(context)
    envelope["data"] = base64.b64encode(malformed.compressed_json).decode()

    with pytest.raises(ValueError, match="sparse log vector"):
        OccupancyTracker(
            make_map(),
            TrackerConfig(
                expected_occupants=1,
                activation_risk_threshold=0.0,
                release_risk_threshold=0.95,
            ),
        ).restore_joint_state(payload)


def test_target_policy_audit_context_corruption_rejects_restore_atomically() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = payload["policy"]
    assert isinstance(policy, dict)
    audit = policy["audit"]
    assert isinstance(audit, list)
    context = audit[-1]["context"]
    assert isinstance(context, dict)
    compressed = bytearray(base64.b64decode(context["data"]))
    compressed[-1] ^= 0x01
    context["data"] = base64.b64encode(compressed).decode()

    target = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    before = target.occupancy_store_data(NOW, {})
    with pytest.raises(ValueError, match="context data|context hash"):
        target.restore_joint_state(payload)
    assert target.occupancy_store_data(NOW, {}) == before


def test_target_policy_audit_semantic_corruption_rejects_restore_atomically() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = payload["policy"]
    assert isinstance(policy, dict)
    audit = policy["audit"]
    assert isinstance(audit, list)
    envelope = audit[-1]["context"]
    assert isinstance(envelope, dict)
    context = json.loads(zlib.decompress(base64.b64decode(envelope["data"])))
    context["release_safe"]["probabilities"]["office"] = 0.5
    context.pop("sha256")
    encoded_body = json.dumps(
        context,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    context["sha256"] = hashlib.sha256(encoded_body).hexdigest()
    encoded = json.dumps(
        context,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    envelope["data"] = base64.b64encode(zlib.compress(encoded, level=6)).decode()

    target = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    before = target.occupancy_store_data(NOW, {})
    with pytest.raises(ValueError, match="release-safe evidence"):
        target.restore_joint_state(payload)
    assert target.occupancy_store_data(NOW, {}) == before


def test_target_policy_audit_v2_target_corruption_rejects_restore() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = payload["policy"]
    assert isinstance(policy, dict)
    audit = policy["audit"]
    assert isinstance(audit, list)
    envelope = audit[-1]["context"]
    assert isinstance(envelope, dict)
    context = json.loads(zlib.decompress(base64.b64decode(envelope["data"])))
    context["arrival_supported"]["targets"]["office"] = "missing-endpoint"
    context.pop("sha256")
    encoded_body = json.dumps(
        context,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    context["sha256"] = hashlib.sha256(encoded_body).hexdigest()
    envelope["data"] = base64.b64encode(
        zlib.compress(
            json.dumps(
                context,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            level=6,
        )
    ).decode()

    with pytest.raises(ValueError, match="arrival-supported evidence"):
        OccupancyTracker(
            make_map(),
            TrackerConfig(
                expected_occupants=1,
                activation_risk_threshold=0.0,
                release_risk_threshold=0.95,
            ),
        ).restore_joint_state(payload)


def test_target_policy_audit_v1_context_remains_restorable() -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    tracker.observe(make_event())
    payload = tracker.occupancy_store_data(NOW, {})
    policy = payload["policy"]
    assert isinstance(policy, dict)
    audit = policy["audit"]
    assert isinstance(audit, list)
    envelope = audit[-1]["context"]
    assert isinstance(envelope, dict)
    context = json.loads(zlib.decompress(base64.b64decode(envelope["data"])))
    context["schema"] = "exact-policy-audit-v1"
    context["arrival_supported"].pop("targets")
    context.pop("sha256")
    encoded_body = json.dumps(
        context,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    context["sha256"] = hashlib.sha256(encoded_body).hexdigest()
    envelope["data"] = base64.b64encode(
        zlib.compress(
            json.dumps(
                context,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            level=6,
        )
    ).decode()

    restored = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=1,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )
    restored.restore_joint_state(payload)
    restored_context = restored.diagnostics.joint_target_policy_audit[-1].context
    assert restored_context is not None
    assert validate_target_policy_audit_context(restored_context)["schema"] == (
        "exact-policy-audit-v1"
    )


@pytest.mark.parametrize("occupants", range(3))
def test_target_policy_audit_context_covers_all_authoritative_counts(
    occupants: int,
) -> None:
    tracker = OccupancyTracker(
        make_map(),
        TrackerConfig(
            expected_occupants=occupants,
            activation_risk_threshold=0.0,
            release_risk_threshold=0.95,
        ),
    )

    tracker.observe(make_event())


def test_n5_accepted_positive_produces_reconstructable_audit_context() -> None:
    predictive_map = load_predictive_map(
        (
            Path(__file__).parents[1] / "benchmarks" / "reference-map.yaml"
        ).read_text()
    )
    entity_id = predictive_map.entity_ids()[0]
    binding = predictive_map.entity_binding_for_entity(entity_id)
    assert binding is not None
    node = predictive_map.nodes[binding.node_id]
    policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.0,
        release_threshold=0.95,
    )
    engine = ExactInferenceEngine(predictive_map, 5, policy=policy)

    diagnostics = engine.observe(
        OccupancyEvent(
            entity_id,
            node.node_id,
            node.occupancy_zone,
                node.floor,
                node.role,
            predictive_map.occupancy_behavior_for_node(node),
                binding.signal_type,
            "on",
            NOW,
                node.initial_weight,
        ),
        emit_activation=True,
    )

    assert diagnostics.normalization == pytest.approx(1.0, abs=1e-12)
    assert diagnostics.pruned_probability == 0.0
    assert len(engine._posterior.space) == 20_349  # noqa: SLF001
    context = diagnostics.policy_audit[-1].context
    assert context is not None
    assert validate_target_policy_audit_context(context)["schema"] == (
        "exact-policy-audit-v2"
    )


@pytest.mark.parametrize("occupants", range(6))
def test_exact_reports_exact_unlocated_arrival_support(occupants: int) -> None:
    engine = ExactInferenceEngine(make_map(), occupants)

    diagnostics = engine.observe(make_event(), emit_activation=False)

    assert (
        diagnostics.arrival_supported_probabilities["office"] > 0.0
    ) is (occupants > 0)


@pytest.mark.parametrize("occupants", range(6))
def test_release_safe_distinguishes_finalized_zero_and_unlocated_counts(
    occupants: int,
) -> None:
    diagnostics = ExactInferenceEngine(make_map(), occupants).diagnostics

    assert diagnostics.release_safe_available
    assert diagnostics.release_safe_probabilities == {
        "hall": 1.0 if occupants == 0 else 0.0,
        "office": 1.0 if occupants == 0 else 0.0,
    }


def test_release_safe_is_unavailable_while_assignment_is_unresolved() -> None:
    engine = ExactInferenceEngine(make_map(), 1)

    diagnostics = engine.observe(make_event(), emit_activation=False)

    assert not diagnostics.release_safe_available
    assert diagnostics.release_safe_probabilities == {}


def test_release_safe_is_unavailable_when_overloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.predictive_controls.inference.engine."
        "MAX_COHERENT_ENDPOINTS",
        0,
    )
    engine = ExactInferenceEngine(make_map(), 1)

    diagnostics = engine.observe(make_event(), emit_activation=False)

    assert diagnostics.overloaded
    assert not diagnostics.release_safe_available
    assert diagnostics.release_safe_probabilities == {}


@pytest.mark.parametrize("behavior", ["sustained", "sticky"])
def test_current_sustained_class_evidence_vetoes_release_safe(
    behavior: str,
) -> None:
    engine = ExactInferenceEngine(make_behavior_map(behavior), 0)
    engine.bootstrap((make_event(),), cold_start=True)

    diagnostics = engine.diagnostics

    assert diagnostics.release_safe_available
    assert diagnostics.release_safe_probabilities["office"] == 0.0
    assert diagnostics.release_safe_probabilities["hall"] == 1.0


def test_current_transient_evidence_does_not_veto_release_safe() -> None:
    engine = ExactInferenceEngine(make_behavior_map("transient"), 0)
    engine.bootstrap((make_event(),), cold_start=True)

    diagnostics = engine.diagnostics

    assert diagnostics.release_safe_available
    assert diagnostics.release_safe_probabilities["office"] == 1.0


def test_finalized_release_safe_matches_exact_support_query() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    engine.observe(mapped_event("office", "office", 0), emit_activation=False)
    engine.observe(mapped_event("hall", "hall", 1), emit_activation=False)
    engine.observe(
        replace(mapped_event("office", "office", 2), state="off"),
        emit_activation=False,
    )

    assert engine.finalize(NOW + timedelta(seconds=70))
    message = engine._chain.finalized_support_message()  # noqa: SLF001
    expected = injective_support_probability(
        message,
        "office",
        lambda support: support.disposition
        in {"stay", "graph_valid", "censored_graph_path", "missed_movement"},
    )

    assert engine.diagnostics.release_safe_available
    assert engine.diagnostics.release_safe_probabilities["office"] == pytest.approx(
        expected,
        abs=1e-12,
    )
    assert expected > 0.0


def test_finalized_graph_support_drives_prediction_and_learning_once() -> None:
    engine = ExactInferenceEngine(make_prediction_map(), 1)
    engine.observe(mapped_event("office", "office", 0), emit_activation=False)
    engine.observe(mapped_event("hall", "hall", 1), emit_activation=False)
    engine.observe(
        replace(mapped_event("office", "office", 2), state="off"),
        emit_activation=False,
    )

    assert engine.finalize(NOW + timedelta(seconds=70))
    diagnostics = engine.diagnostics
    first_counts = diagnostics.route_transition_counts

    assert set(diagnostics.prediction_probabilities) == {"kitchen", "living"}
    assert diagnostics.prediction_probabilities["kitchen"] == pytest.approx(
        diagnostics.prediction_probabilities["living"],
        abs=1e-12,
    )
    assert diagnostics.prediction_leases
    assert first_counts["office"]["hall"] > 0.8

    repeated = engine.diagnostics

    assert repeated.route_transition_counts == first_counts


def test_finalized_prediction_state_round_trips_without_relearning() -> None:
    predictive_map = make_prediction_map()
    original = ExactInferenceEngine(predictive_map, 1)
    original.observe(mapped_event("office", "office", 0), emit_activation=False)
    original.observe(mapped_event("hall", "hall", 1), emit_activation=False)
    original.observe(
        replace(mapped_event("office", "office", 2), state="off"),
        emit_activation=False,
    )
    assert original.finalize(NOW + timedelta(seconds=70))
    before = original.diagnostics
    payload = original.serialize(NOW + timedelta(seconds=70), {})

    restored = ExactInferenceEngine(predictive_map, 1)
    after = restored.restore(payload)

    assert after.prediction_leases == before.prediction_leases
    assert after.prediction_probabilities == before.prediction_probabilities
    assert after.route_transition_counts == before.route_transition_counts
    assert after.route_statistics == before.route_statistics
    assert restored.serialize(NOW + timedelta(seconds=70), {}) == payload


def test_injected_posterior_event_policy_drives_active_edges() -> None:
    predictive_map = make_map()
    policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.8,
        release_threshold=0.9,
    )
    engine = ExactInferenceEngine(predictive_map, 1, policy=policy)

    acquired = engine.observe(
        mapped_event("office", "office", 0),
        emit_activation=True,
    )

    assert acquired.policy_states["office"].keep_on
    engine.observe(mapped_event("hall", "hall", 1), emit_activation=False)
    engine.observe(
        replace(mapped_event("office", "office", 2), state="off"),
        emit_activation=False,
    )
    assert engine.finalize(NOW + timedelta(seconds=70))

    assert not engine.diagnostics.policy_states["office"].keep_on
    assert engine.diagnostics.policy_decisions

    payload = engine.serialize(NOW + timedelta(seconds=70), {})
    restored_policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.8,
        release_threshold=0.9,
    )
    restored = ExactInferenceEngine(
        predictive_map,
        1,
        policy=restored_policy,
    )

    assert restored.restore(payload).policy_states == engine.diagnostics.policy_states


def test_distinct_target_node_adds_strict_relocation_support() -> None:
    engine = ExactInferenceEngine(make_corroboration_map(), 1)
    engine.observe(mapped_event("source", "source", 0), emit_activation=False)
    isolated = engine.observe(
        mapped_event("target_a", "target", 1),
        emit_activation=False,
    )

    assert isolated.arrival_supported_probabilities["target"] == pytest.approx(
        direct_arrival_probability(engine, "target"),
        abs=1e-12,
    )

    corroborated = engine.observe(
        mapped_event("target_b", "target", 2),
        emit_activation=False,
    )
    direct = direct_arrival_probability(engine, "target")

    assert corroborated.arrival_supported_probabilities["target"] > direct


def test_same_node_alias_and_other_zone_do_not_corroborate_arrival() -> None:
    engine = ExactInferenceEngine(make_corroboration_map(), 1)
    engine.observe(mapped_event("source", "source", 0), emit_activation=False)
    engine.observe(mapped_event("target_a", "target", 1), emit_activation=False)
    alias = engine.observe(
        mapped_event(
            "target_a",
            "target",
            2,
            entity_id="binary_sensor.target_a_alias",
        ),
        emit_activation=False,
    )

    assert alias.arrival_supported_probabilities == {}

    other_zone = engine.observe(
        mapped_event("other", "other", 3),
        emit_activation=False,
    )

    assert set(other_zone.arrival_supported_probabilities) == {"other"}


def test_exact_replays_in_lag_events_and_rejects_watermark_boundary() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    later = replace(make_event(), event_at=NOW + timedelta(seconds=5))
    earlier = replace(
        make_event(),
        entity_id="binary_sensor.hall",
        node_id="hall",
        zone="hall",
        event_at=NOW + timedelta(seconds=4),
    )

    engine.observe_received(
        later,
        receive_at=NOW + timedelta(seconds=5),
        emit_activation=False,
    )
    accepted = engine.observe_received(
        earlier,
        receive_at=NOW + timedelta(seconds=5),
        emit_activation=False,
    )
    before = accepted.occupied_marginals
    stale = engine.observe_received(
        replace(earlier, event_at=NOW + timedelta(seconds=3), state="off"),
        receive_at=NOW + timedelta(seconds=5),
        emit_activation=False,
    )

    assert accepted.event_disposition == "accepted_positive"
    assert accepted.updated_at == NOW + timedelta(seconds=5)
    assert stale.event_disposition == "stale"
    assert stale.occupied_marginals == before


def test_exact_duplicate_observation_is_posterior_neutral() -> None:
    engine = ExactInferenceEngine(make_map(), 2)
    engine.observe(make_event(), emit_activation=True)
    before = engine.diagnostics

    duplicate = engine.observe(make_event(), emit_activation=True)

    assert duplicate.event_disposition == "duplicate"
    assert duplicate.occupied_marginals == before.occupied_marginals
    assert duplicate.count_marginals == before.count_marginals
    assert duplicate.updated_at == before.updated_at


def test_exact_count_control_and_persistence_round_trip_exactly() -> None:
    predictive_map = make_map()
    engine = ExactInferenceEngine(predictive_map, 1)
    engine.reconcile_count(2, NOW, "count-2", reconcile_policy=True)
    payload = engine.serialize(NOW, {})
    assert isinstance(payload, dict)
    chain = payload["chain"]
    assert isinstance(chain, dict)
    assert "base_message" in chain

    restored = ExactInferenceEngine(predictive_map, 0)
    diagnostics = restored.restore(payload)

    assert diagnostics == engine.diagnostics
    assert diagnostics.expected_occupants == 2
    assert diagnostics.normalization == pytest.approx(1.0, abs=1e-12)
    assert diagnostics.pruned_probability == 0.0


def test_exact_restore_rejects_support_base_corruption_atomically() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    before = engine.serialize(NOW, {})
    assert isinstance(before, dict)
    chain = before["chain"]
    assert isinstance(chain, dict)
    base_message = chain["base_message"]
    assert isinstance(base_message, dict)
    entries = base_message["entries"]
    assert isinstance(entries, list)
    assert entries
    first = entries[0]
    assert isinstance(first, dict)
    first["occupancy_rank"] = 1

    with pytest.raises(ValueError, match="does not project"):
        engine.restore(before)

    after = ExactInferenceEngine(make_map(), 1).serialize(NOW, {})
    assert engine.serialize(NOW, {}) == after


def test_exact_restore_accepts_sub_tolerance_projection_drift() -> None:
    engine = ExactInferenceEngine(make_map(), 2)
    engine.observe(make_event(), emit_activation=False)
    payload = engine.serialize(NOW, {})
    assert isinstance(payload, dict)
    message = payload["message"]
    assert isinstance(message, dict)
    entries = message["entries"]
    assert isinstance(entries, list)
    first = entries[0]
    assert isinstance(first, dict)
    log_mass = first["log_mass"]
    assert isinstance(log_mass, float)
    first["log_mass"] = log_mass + 5e-13

    restored = ExactInferenceEngine(make_map(), 0)
    restored.restore(payload)
    round_trip = restored.serialize(NOW, {})
    assert isinstance(round_trip, dict)

    assert round_trip["log_probabilities"] == payload["log_probabilities"]


def test_exact_count_controls_are_ordered_duplicate_safe_and_persistent() -> None:
    predictive_map = make_map()
    engine = ExactInferenceEngine(predictive_map, 1)
    accepted = engine.reconcile_count(2, NOW, "count-2", reconcile_policy=True)
    duplicate = engine.reconcile_count(
        3,
        NOW + timedelta(seconds=2),
        "count-2",
        reconcile_policy=True,
    )
    stale = engine.reconcile_count(
        3,
        NOW,
        "count-3-stale",
        reconcile_policy=True,
    )

    assert accepted.expected_occupants == 2
    assert duplicate.expected_occupants == 2
    assert duplicate.event_disposition == "duplicate_count_control"
    assert duplicate.updated_at == NOW
    assert stale.expected_occupants == 2
    assert stale.event_disposition == "stale_count_control"
    assert stale.updated_at == NOW

    payload = engine.serialize(NOW + timedelta(seconds=2), {})
    restored = ExactInferenceEngine(predictive_map, 0)
    restored.restore(payload)
    restored_duplicate = restored.reconcile_count(
        4,
        NOW + timedelta(seconds=3),
        "count-2",
        reconcile_policy=True,
    )
    fresh = restored.reconcile_count(
        3,
        NOW + timedelta(seconds=3),
        "count-3",
        reconcile_policy=True,
    )

    assert restored_duplicate.expected_occupants == 2
    assert restored_duplicate.event_disposition == "duplicate_count_control"
    assert fresh.expected_occupants == 3
    assert fresh.event_disposition == "accepted_count_control"


def test_exact_persists_unresolved_replay_and_continues_exactly() -> None:
    predictive_map = make_map()
    original = ExactInferenceEngine(predictive_map, 1)
    original.observe_received(
        make_event(),
        receive_at=NOW,
        emit_activation=False,
    )
    payload = original.serialize(NOW, {})
    assert isinstance(payload, dict)
    chain = payload["chain"]
    assert isinstance(chain, dict)
    steps = chain["steps"]
    assert isinstance(steps, list)
    endpoint_steps = [step for step in steps if step.get("kind") == "endpoint"]
    assert endpoint_steps
    assert all("reserved_source_indexes" in step for step in endpoint_steps)
    restored = ExactInferenceEngine(predictive_map, 0)

    restored.restore(payload)
    assert restored.serialize(NOW, {}) == payload

    next_event = replace(
        make_event(),
        entity_id="binary_sensor.hall",
        node_id="hall",
        zone="hall",
        event_at=NOW + timedelta(seconds=1),
    )
    expected = original.observe_received(
        next_event,
        receive_at=NOW + timedelta(seconds=1),
        emit_activation=False,
    )
    actual = restored.observe_received(
        next_event,
        receive_at=NOW + timedelta(seconds=1),
        emit_activation=False,
    )

    assert actual == expected
    assert restored.serialize(NOW + timedelta(seconds=1), {}) == original.serialize(
        NOW + timedelta(seconds=1), {}
    )


def test_exact_endpoint_reservation_metadata_is_backward_compatible() -> None:
    endpoint_factor = EndpointFactor(
        EndpointToken("endpoint", "hall", NOW),
        1,
        "hall",
        (
            EndpointAlternative(
                "stay",
                "stay",
                None,
                None,
                ("hall",),
                0.0,
                NOW,
                (),
            ),
        ),
        math.log(0.2),
        math.log(0.9),
        frozenset({0}),
    )

    payload = engine_module._encode_factor_step(endpoint_factor)  # noqa: SLF001
    assert isinstance(payload, dict)
    assert engine_module._decode_factor_step(payload) == endpoint_factor  # noqa: SLF001

    payload.pop("reserved_source_indexes")
    restored = engine_module._decode_factor_step(payload)  # noqa: SLF001
    assert isinstance(restored, EndpointFactor)
    assert restored.reserved_source_indexes == frozenset()


def test_exact_finalization_compacts_raw_input_and_consumes_endpoint() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    engine.observe_received(
        make_event(),
        receive_at=NOW,
        emit_activation=False,
    )
    assert engine.finalize(NOW + timedelta(seconds=3, microseconds=1))
    payload = engine.serialize(NOW + timedelta(seconds=3, microseconds=1), {})
    assert isinstance(payload, dict)
    replay = payload["replay"]
    assert isinstance(replay, dict)

    assert replay["retained"] == []
    assert replay["consumed_endpoint_ids"] == [f"office@{NOW.isoformat()}"]
    assert engine.diagnostics.arrival_supported_probabilities == {}
    assert engine.diagnostics.normalization == pytest.approx(1.0, abs=1e-12)
    assert engine.diagnostics.pruned_probability == 0.0


def test_exact_bootstrap_and_restore_validate_inputs() -> None:
    predictive_map = make_map()
    engine = ExactInferenceEngine(predictive_map, 1)
    engine.bootstrap((make_event(),), cold_start=True)

    with pytest.raises(ValueError, match="not in the predictive map"):
        engine.observe(
            OccupancyEvent(
                **{**make_event().__dict__, "zone": "unknown"},
            ),
            emit_activation=False,
        )
    with pytest.raises(TypeError, match="mapping"):
        engine.restore([])
    with pytest.raises(ValueError, match="schema"):
        engine.restore({})
    valid = engine.serialize(NOW, {})
    assert isinstance(valid, dict)
    with pytest.raises(ValueError, match="zones"):
        engine.restore(
            {
                **valid,
                "zones": ["elsewhere"],
            }
        )
    invalid_posterior = {**valid, "occupants": None}
    with pytest.raises(ValueError, match="posterior"):
        engine.restore(invalid_posterior)
    with pytest.raises(ValueError, match="disposition"):
        engine.restore(
            {
                **valid,
                "event_disposition": 1,
            }
        )
    with pytest.raises(ValueError, match="update time"):
        engine.restore(
            {
                **valid,
                "updated_at": 1,
            }
        )


def test_exact_restore_rejects_map_time_and_episode_corruption_atomically() -> None:
    predictive_map = make_map()
    engine = ExactInferenceEngine(predictive_map, 1)
    engine.observe(make_event(), emit_activation=False)
    before = engine.serialize(NOW, {})
    assert isinstance(before, dict)

    corruptions = (
        ({**before, "map_fingerprint": "wrong"}, "fingerprint"),
        ({**before, "updated_at": "2026-07-16T00:00:00"}, "UTC"),
        ({**before, "updated_at": "not-a-datetime"}, "update time"),
        ({**before, "episodes": []}, "incomplete"),
    )
    for corrupted, message in corruptions:
        with pytest.raises(ValueError, match=message):
            engine.restore(corrupted)
        after = engine.serialize(NOW, {})
        assert after == before
        assert engine.diagnostics.restore_rejection is not None

    assert engine.restore(before).restore_rejection is None


PayloadMutation = Callable[[dict[str, Any]], None]


def _complete_exact_payload() -> dict[str, Any]:
    predictive_map = make_map()
    policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    engine = ExactInferenceEngine(predictive_map, 1, policy=policy)
    engine.reconcile_count(
        1,
        NOW - timedelta(seconds=1),
        "count-1",
        reconcile_policy=True,
    )
    engine.observe(make_event(), emit_activation=True)
    payload = engine.serialize(NOW + timedelta(seconds=1), {})
    assert isinstance(payload, dict)
    payload["prediction_leases"] = [
        {
            "path_key": ["office", None, "hall"],
            "target_zone": "hall",
            "probability": 0.5,
            "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            "reason": "coverage",
        }
    ]
    payload["route_transition_counts"] = {"office": {"hall": 1.0}}
    payload["route_counts"] = [
        {"prefix": ["office"], "targets": {"hall": 1.0}}
    ]
    payload["route_contexts"] = [["office", "hall"]]
    payload["processed_prediction_support_ids"] = ["support-1"]
    return payload


def _set_payload(path: tuple[str | int, ...], value: object) -> PayloadMutation:
    def mutate(payload: dict[str, Any]) -> None:
        target: Any = payload
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = value

    return mutate


def _append_payload(path: tuple[str | int, ...], value: object) -> PayloadMutation:
    def mutate(payload: dict[str, Any]) -> None:
        target: Any = payload
        for component in path:
            target = target[component]
        target.append(value)

    return mutate


def _valid_assignment() -> dict[str, object]:
    return {
        "endpoint_id": "endpoint-1",
        "alternative_id": "alternative-1",
        "disposition": "unlocated",
        "predecessor_rank": 0,
        "successor_rank": 0,
        "source_index": None,
        "target_index": 0,
        "source_node_id": None,
        "target_node_id": "office",
        "route_nodes": [],
        "deadline": (NOW + timedelta(seconds=30)).isoformat(),
        "evidence_ids": ["evidence-1"],
    }


def _valid_support() -> dict[str, object]:
    return {
        "support_event_id": "support-1",
        "disposition": "graph_valid",
        "origin_zone": "office",
        "destination_zone": "hall",
        "route_nodes": ["office", "hall"],
        "endpoint_ids": ["endpoint-1"],
        "episode_ids": ["episode-1"],
        "valid_from": NOW.isoformat(),
        "valid_until": (NOW + timedelta(seconds=30)).isoformat(),
        "learning_eligible": True,
    }


def _duplicate_route_prefix(payload: dict[str, Any]) -> None:
    payload["route_counts"].append(deepcopy(payload["route_counts"][0]))


def _invalid_assignment_field(field: str, value: object) -> PayloadMutation:
    def mutate(payload: dict[str, Any]) -> None:
        assignment = _valid_assignment()
        assignment[field] = value
        payload["message"]["entries"][0]["contexts"] = [assignment]

    return mutate


def _invalid_support_field(field: str, value: object) -> PayloadMutation:
    def mutate(payload: dict[str, Any]) -> None:
        support = _valid_support()
        support[field] = value
        payload["message"]["entries"][0]["supports"] = [support]

    return mutate


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (_set_payload(("message",), []), "augmented message must be a mapping"),
        (_set_payload(("message", "occupants"), 2), "message occupant count"),
        (_set_payload(("message", "entries"), {}), "entries must be a list"),
        (_set_payload(("message", "entries", 0), None), "entry must be a mapping"),
        (
            _set_payload(("message", "entries", 0, "occupancy_rank"), True),
            "augmented entry is invalid",
        ),
        (
            _set_payload(("message", "entries", 0, "log_mass"), math.nan),
            "log mass must be finite",
        ),
        (_set_payload(("chain",), []), "factor chain must be a mapping"),
        (_set_payload(("chain", "occupants"), 2), "occupant count is invalid"),
        (_set_payload(("chain", "base"), None), "factor-chain state is invalid"),
        (_set_payload(("chain", "steps", 0), None), "factor step must be a mapping"),
        (_set_payload(("chain", "steps", 0, "kind"), "wrong"), "step kind"),
        (
            _set_payload(("chain", "steps", 0, "alternatives"), None),
            "endpoint alternatives",
        ),
        (
            _set_payload(("chain", "steps", 0, "reserved_source_indexes"), {}),
            "reserved sources",
        ),
        (
            _set_payload(("chain", "steps", 0, "alternatives", 0), None),
            "alternative must be a mapping",
        ),
        (
            _set_payload(
                ("chain", "steps", 0, "alternatives", 0, "disposition"),
                "wrong",
            ),
            "movement disposition",
        ),
        (
            _set_payload(
                ("chain", "steps", 0, "alternatives", 0, "source_index"),
                True,
            ),
            "alternative source is invalid",
        ),
        (
            _set_payload(("message", "entries", 0, "contexts"), [None]),
            "assignment atom must be a mapping",
        ),
        (
            _invalid_assignment_field("target_index", True),
            "assignment target is invalid",
        ),
        (
            _invalid_assignment_field("route_nodes", [""]),
            "assignment route nodes are invalid",
        ),
        (
            _set_payload(("message", "entries", 0, "supports"), [None]),
            "support atom must be a mapping",
        ),
        (
            _invalid_support_field("learning_eligible", None),
            "support eligibility",
        ),
        (
            _invalid_support_field("disposition", "wrong"),
            "movement disposition",
        ),
        (_set_payload(("count_evidence_ids",), None), "count evidence IDs"),
        (
            _set_payload(("count_evidence_ids",), ["count-1", "count-1"]),
            "count evidence IDs are not canonical",
        ),
        (
            _set_payload(("latest_count_control_at",), None),
            "count control frontier is missing",
        ),
        (_set_payload(("prediction_leases",), None), "prediction leases"),
        (
            _set_payload(("prediction_leases", 0), None),
            "prediction lease must be a mapping",
        ),
        (
            _set_payload(("prediction_leases", 0, "path_key"), ["office"]),
            "prediction path key",
        ),
        (
            _set_payload(("prediction_leases", 0, "probability"), 2.0),
            "prediction probability",
        ),
        (
            _set_payload(("route_transition_counts",), []),
            "route transition counts",
        ),
        (
            _set_payload(("route_transition_counts",), {"": {}}),
            "route transition counts",
        ),
        (
            _set_payload(("route_transition_counts",), {"office": {"": 1.0}}),
            "route transition target",
        ),
        (
            _set_payload(
                ("route_transition_counts",),
                {"office": {"hall": -1.0}},
            ),
            "route transition count is invalid",
        ),
        (_set_payload(("route_counts",), {}), "route counts are invalid"),
        (_set_payload(("route_counts", 0), None), "route count must be a mapping"),
        (
            _set_payload(("route_counts", 0, "targets"), []),
            "route count targets",
        ),
        (_duplicate_route_prefix, "route prefixes must be unique"),
        (
            _set_payload(("route_counts", 0, "targets"), {"": 1.0}),
            "route count target",
        ),
        (
            _set_payload(("route_counts", 0, "targets", "hall"), 0.0),
            "route count is invalid",
        ),
        (_set_payload(("route_contexts",), None), "route contexts"),
        (
            _set_payload(("route_contexts", 0), [""]),
            "route context are invalid",
        ),
        (
            _set_payload(("processed_prediction_support_ids",), None),
            "processed prediction support IDs",
        ),
        (
            _set_payload(
                ("processed_prediction_support_ids",),
                ["support-1", "support-1"],
            ),
            "processed prediction support IDs are not canonical",
        ),
        (
            _set_payload(("migration_bootstrap_pending",), 1),
            "migration bootstrap state",
        ),
        (_set_payload(("policy",), None), "policy state is missing"),
        (_set_payload(("policy",), []), "policy state is invalid"),
        (
            _set_payload(("policy", "activation_threshold"), 0.7),
            "policy configuration is incompatible",
        ),
        (_set_payload(("policy", "states"), {}), "policy zones do not match"),
        (
            _set_payload(("policy", "states", "office"), None),
            "policy zone state",
        ),
        (
            _set_payload(("policy", "states", "office", "keep_on"), 1),
            "policy zone flags",
        ),
        (
            _set_payload(
                ("policy", "states", "office", "last_release_cause"),
                "wrong",
            ),
            "policy release cause",
        ),
        (
            _set_payload(
                ("policy", "states", "office", "last_release_cause"),
                1,
            ),
            "policy release cause",
        ),
        (_set_payload(("policy", "audit"), None), "policy audit is invalid"),
        (
            _set_payload(("policy", "audit", 0), None),
            "policy audit entry",
        ),
        (
            _set_payload(("policy", "audit", 0, "accepted"), 1),
            "policy audit flags",
        ),
        (
            _set_payload(("policy", "audit", 0, "gate_values"), {1: 1.0}),
            "policy audit gates",
        ),
        (
            _set_payload(
                ("policy", "audit", 0, "gate_values"),
                {"probability": math.inf},
            ),
            "policy audit gates",
        ),
        (
            _set_payload(
                ("policy", "audit", 0, "decision_at"),
                (NOW - timedelta(hours=13)).isoformat(),
            ),
            "policy audit exceeds retention bounds",
        ),
    ),
)
def test_exact_restore_rejects_all_schema_corruption_atomically(
    mutate: PayloadMutation,
    message: str,
) -> None:
    payload = _complete_exact_payload()
    mutate(payload)
    predictive_map = make_map()
    target = ExactInferenceEngine(
        predictive_map,
        1,
        policy=PosteriorEventPolicy(
            predictive_map.zones(),
            activation_threshold=0.8,
            release_threshold=0.95,
        ),
    )
    before = target.serialize(NOW, {})

    with pytest.raises((TypeError, ValueError), match=message):
        target.restore(payload)

    assert target.diagnostics.restore_rejection is not None
    assert target.serialize(NOW, {}) == before


def test_stale_snapshot_does_not_advance_shadow_model_time() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    engine.observe(make_event(), emit_activation=False)
    before = engine.diagnostics
    stale = replace(make_event(), state="off", event_at=NOW - timedelta(seconds=1))

    diagnostics = engine.bootstrap((stale,), cold_start=False)

    assert diagnostics.event_disposition == "stale"
    assert diagnostics.updated_at == before.updated_at
    assert diagnostics.episode_states == before.episode_states


def test_exact_empty_bootstrap_finalize_and_unsupported_count() -> None:
    engine = ExactInferenceEngine(make_map(), 2)

    assert engine.bootstrap((), cold_start=False).updated_at is None
    assert not engine.finalize(NOW)
    assert engine.diagnostics.updated_at is None
    payload = engine.serialize(NOW, {})
    assert isinstance(payload, dict)
    payload["updated_at"] = None
    assert engine.restore(payload).updated_at is None
    diagnostics = engine.enter_unsupported_count(3, NOW, "unsupported")
    assert diagnostics.expected_occupants == 0
    assert diagnostics.event_disposition == "unsupported_count"


def test_exact_properties_and_conservative_legacy_migration() -> None:
    predictive_map = make_map()
    without_policy = ExactInferenceEngine(predictive_map, 1)
    assert without_policy.policy is None
    assert without_policy.predictions.leases == ()
    with pytest.raises(ValueError, match="policy is unavailable"):
        without_policy.migrate_legacy_state({}, {}, {})

    policy = PosteriorEventPolicy(
        predictive_map.zones(),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    engine = ExactInferenceEngine(predictive_map, 1, policy=policy)
    migrated = engine.migrate_legacy_state(
        {
            "office": ZonePolicyState(keep_on=True),
            "unknown": ZonePolicyState(keep_on=True),
        },
        {"office": {"hall": 3.0}},
        {("hall", "office"): {"hall": 2.0}},
    )

    assert migrated.policy_states["office"].keep_on
    assert migrated.policy_states["office"].reason == "migrated legacy ownership"
    assert not migrated.policy_states["hall"].keep_on
    assert migrated.route_transition_counts["office"]["hall"] == 3.0
    assert migrated.route_statistics[("hall", "office")]["hall"] == 2.0
    assert migrated.event_disposition == "legacy_v5_migrated"

    bootstrapped = engine.bootstrap((make_event(),), cold_start=False)
    assert bootstrapped.event_disposition == "snapshot_reconciled"
    assert bootstrapped.policy_decisions == ()
    engine.bootstrap((), cold_start=False)


def test_exact_rejects_invalid_and_duplicate_unsupported_count_controls() -> None:
    engine = ExactInferenceEngine(make_map(), 1)
    with pytest.raises(ValueError, match="must be non-empty"):
        engine.reconcile_count(1, NOW, "", reconcile_policy=False)

    accepted = engine.enter_unsupported_count(6, NOW, "unsupported")
    duplicate = engine.enter_unsupported_count(
        6,
        NOW + timedelta(seconds=1),
        "unsupported",
    )

    assert accepted.expected_occupants == 0
    assert duplicate.expected_occupants == 0
    assert duplicate.event_disposition == "duplicate_count_control"


def test_exact_restore_rejects_projection_and_chain_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _complete_exact_payload()
    probabilities = payload["log_probabilities"]
    probabilities[0], probabilities[1] = probabilities[1], probabilities[0]
    with pytest.raises(ValueError, match="projected posterior"):
        ExactInferenceEngine(make_map(), 1).restore(payload)

    payload = _complete_exact_payload()
    payload["replay"] = None
    def different_chain(
        _payload: object,
        space: Any,
        operators: Any,
    ) -> Any:
        posterior = CompactLogPosterior.certain(
            space,
            (0, 1, 0),
        )
        return ExactFactorChain(
            posterior,
            operators=operators,
        )

    monkeypatch.setattr(
        engine_module,
        "_decode_chain",
        different_chain,
    )
    with pytest.raises(ValueError, match="current chain"):
        ExactInferenceEngine(make_map(), 1).restore(payload)


@pytest.mark.parametrize(
    "invariant",
    ("lateness", "chain", "posterior", "episodes"),
)
def test_exact_restore_checks_replay_consistency_defensively(
    monkeypatch: pytest.MonkeyPatch,
    invariant: str,
) -> None:
    payload = _complete_exact_payload()
    original_restore = RetainedReplayCoordinator.restore

    def corrupt_after_restore(
        replay: RetainedReplayCoordinator[Any, Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_restore(replay, *args, **kwargs)
        if invariant == "lateness":
            replay.max_lateness = timedelta(seconds=3)
            return
        current = replay.replay_result or replay.finalized_base
        if invariant in {"chain", "posterior"}:
            replay._replay_result = replace(  # noqa: SLF001
                current,
                chain=replay.finalized_base.chain,
            )
            return
        replay._replay_result = replace(  # noqa: SLF001
            current,
            episode_states=replay.finalized_base.episode_states,
        )

    monkeypatch.setattr(RetainedReplayCoordinator, "restore", corrupt_after_restore)
    if invariant == "posterior":
        monkeypatch.setattr(engine_module, "_encode_chain", lambda _chain: {})
    expected = {
        "lateness": "replay lateness",
        "chain": "replay result does not match current chain",
        "posterior": "replay result does not match message",
        "episodes": "replay episodes do not match current state",
    }[invariant]

    with pytest.raises(ValueError, match=expected):
        ExactInferenceEngine(make_map(), 1).restore(payload)


def test_exact_restore_rejects_replay_and_scalar_helper_corruption() -> None:
    corruptions: tuple[tuple[PayloadMutation, str], ...] = (
        (
            _set_payload(("replay", "finalized_base"), None),
            "replay fold state must be a mapping",
        ),
        (
            _set_payload(("replay", "finalized_base", "dispositions"), None),
            "replay dispositions must be a list",
        ),
        (
            _set_payload(("replay", "finalized_base", "dispositions"), [None]),
            "replay disposition is invalid",
        ),
        (
            _set_payload(("prediction_leases", 0, "target_zone"), ""),
            "prediction target is invalid",
        ),
        (
            _set_payload(("prediction_leases", 0, "probability"), True),
            "prediction probability is invalid",
        ),
        (
            _set_payload(("prediction_leases", 0, "expires_at"), None),
            "prediction expiry is invalid",
        ),
        (
            _set_payload(("prediction_leases", 0, "expires_at"), "wrong"),
            "prediction expiry is invalid",
        ),
    )
    for mutate, message in corruptions:
        payload = _complete_exact_payload()
        mutate(payload)
        with pytest.raises((TypeError, ValueError), match=message):
            ExactInferenceEngine(make_map(), 1).restore(payload)


def test_exact_private_probability_and_replay_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _complete_exact_payload()
    engine = ExactInferenceEngine(make_map(), 1)
    stay = EndpointAlternative(
        "stay",
        "stay",
        None,
        None,
        (),
        0.0,
        NOW + timedelta(seconds=10),
        ("evidence",),
    )

    def factor(token_id: str, zone: str, event_at: datetime) -> EndpointFactor:
        return EndpointFactor(
            EndpointToken(token_id, zone, event_at),
            engine._message.space.location_index(zone),  # noqa: SLF001
            zone,
            (stay,),
            0.0,
            0.0,
        )

    older = factor("older", "office", NOW)
    newer = factor("newer", "office", NOW + timedelta(seconds=1))
    hall = factor("hall", "hall", NOW)
    engine._chain = SimpleNamespace(steps=(object(), newer, older, hall))  # type: ignore[assignment]  # noqa: SLF001
    assert engine._latest_arrival_factors() == {  # noqa: SLF001
        "office": newer,
        "hall": hall,
    }

    engine._chain = SimpleNamespace(  # type: ignore[assignment]  # noqa: SLF001
            steps=(),
        assignment_and_terminal_probabilities=lambda *_args: (1.1,),
    )
    engine._current_arrival_factors = (("office", older),)  # noqa: SLF001
    with pytest.raises(ValueError, match="probability is out of range"):
        engine._arrival_supported_probabilities()  # noqa: SLF001

    replay_engine = ExactInferenceEngine(make_map(), 1)
    replay_engine._process_finalized_prediction_support(NOW)  # noqa: SLF001
    initial = FactorChainReplayState(
        replay_engine._chain,  # noqa: SLF001
        replay_engine._episodes.states,  # noqa: SLF001
    )
    replay_engine._apply_replay_state(initial, NOW)  # noqa: SLF001
    replay = replay_engine._ensure_replay(NOW)  # noqa: SLF001
    current = replay.finalized_base
    assert replay_engine._compact_replay(replay, current) is current  # noqa: SLF001
    replay.posterior_event_at = replay.watermark
    assert replay_engine._compact_replay(replay, current) is current  # noqa: SLF001

    decoded = engine_module._decode_message(  # noqa: SLF001
        payload["message"],
        ExactInferenceEngine(make_map(), 1)._message.space,  # noqa: SLF001
    )
    assert decoded.occupancy_posterior().space.occupants == 1
    assignment_payload = _valid_assignment()
    assignment_payload["disposition"] = "stay"
    assignment = engine_module._decode_assignment(assignment_payload)  # noqa: SLF001
    assert engine_module._encode_assignment(assignment)["endpoint_id"] == "endpoint-1"  # noqa: SLF001


def test_differential_runner_replays_controls_and_restart_without_mismatch() -> None:
    predictive_map = make_map()
    first = ExactInferenceEngine(predictive_map, 1)
    second = ExactInferenceEngine(predictive_map, 1)
    runner = DifferentialRunner(first, second, {})

    assert not runner.bootstrap((make_event(),), cold_start=True).mismatches
    assert not runner.observe(make_event()).mismatches
    assert not runner.reconcile_count(2, NOW, "count-2").mismatches
    assert not runner.finalize(NOW + timedelta(seconds=1)).mismatches

    first_payload = first.serialize(NOW, {})
    second_payload = second.serialize(NOW, {})
    restarted_first = ExactInferenceEngine(predictive_map, 0)
    restarted_second = ExactInferenceEngine(predictive_map, 0)
    restarted_first.restore(first_payload)
    restarted_second.restore(second_payload)
    restarted = DifferentialRunner(restarted_first, restarted_second, {})
    assert not restarted.compare_restart().mismatches


def test_differential_runner_requires_requirement_for_every_mismatch() -> None:
    predictive_map = make_map()
    first = ExactInferenceEngine(predictive_map, 1)
    second = ExactInferenceEngine(predictive_map, 2)

    with pytest.raises(ValueError, match="expected_occupants"):
        DifferentialRunner(first, second, {}).compare_restart()

    frame = DifferentialRunner(
        first,
        second,
        {
            "expected_occupants": "MODEL-017",
            "count_marginals": "MODEL-017",
        },
    ).compare_restart()
    assert {mismatch.requirement_id for mismatch in frame.mismatches} == {"MODEL-017"}


def test_differential_runner_compares_public_projection() -> None:
    predictive_map = make_map()
    first = ExactInferenceEngine(predictive_map, 1)
    second = ExactInferenceEngine(predictive_map, 1)
    runner = DifferentialRunner(
        first,
        second,
        {},
        legacy_projection=lambda _engine: {"office": True},
        replacement_projection=lambda _engine: {"office": True},
    )

    assert not runner.compare_restart().mismatches

    incomplete = DifferentialRunner(
        first,
        second,
        {},
        legacy_projection=lambda _engine: {},
    )
    with pytest.raises(ValueError, match="Both public projections"):
        incomplete.compare_restart()


def test_legacy_adapter_and_tracker_project_engine_specific_contracts() -> None:
    predictive_map = make_map()
    legacy = LegacyInferenceEngine(
        predictive_map,
        ZoneGraph.from_map(predictive_map),
        1,
        None,
    )
    assert isinstance(legacy, InferenceEngine)
    with pytest.raises(TypeError, match="RestoredOccupancyState"):
        legacy.restore({})

    tracker = OccupancyTracker(predictive_map, TrackerConfig(expected_occupants=1))
    tracker._engine = ExactInferenceEngine(predictive_map, 1)  # noqa: SLF001
    assert set(tracker.states) == set(predictive_map.zones())

    tracker._engine.serialize = lambda _now, _counts: ()  # type: ignore[assignment]  # noqa: SLF001
    with pytest.raises(TypeError, match="persistence must be a mapping"):
        tracker.occupancy_store_data(NOW, {})


def test_legacy_and_shadow_complete_replay_has_classified_differences() -> None:
    predictive_map = make_map()
    legacy = LegacyInferenceEngine(
        predictive_map,
        ZoneGraph.from_map(predictive_map),
        1,
        None,
    )
    replacement = ExactInferenceEngine(predictive_map, 1)
    requirement_ids = {
        "bootstrap.occupied_marginals": "STATE-003",
        "bootstrap.count_marginals": "STATE-003",
        "occupied_marginals": "EVID-016",
        "count_marginals": "EVID-016",
        "event_disposition": "EVID-018",
        "public_timeline": "POL-007",
    }
    runner = DifferentialRunner(
        legacy,
        replacement,
        requirement_ids,
        legacy_projection=lambda _engine: {
            zone: state.keep_on for zone, state in legacy.policy.states.items()
        },
        replacement_projection=lambda _engine: dict.fromkeys(
            predictive_map.zones(),
            False,
        ),
    )

    frames = [
        runner.bootstrap((), cold_start=True),
        runner.observe(make_event()),
        runner.reconcile_count(2, NOW + timedelta(seconds=1), "count-2"),
        runner.finalize(NOW + timedelta(seconds=2)),
    ]
    assert {mismatch.requirement_id for mismatch in frames[0].mismatches} == {
        "STATE-003"
    }
    assert frames[1].mismatches
    assert all(
        mismatch.requirement_id for frame in frames for mismatch in frame.mismatches
    )

    legacy_payload = legacy.serialize(NOW + timedelta(seconds=2), {})
    replacement_payload = replacement.serialize(NOW + timedelta(seconds=2), {})
    assert isinstance(legacy_payload, dict)
    restarted_legacy = LegacyInferenceEngine(
        predictive_map,
        ZoneGraph.from_map(predictive_map),
        2,
        None,
    )
    restarted_legacy.restore(
        restore_occupancy_state(
            legacy_payload,
            predictive_map,
            2,
            NOW + timedelta(seconds=3),
        )
    )
    restarted_replacement = ExactInferenceEngine(predictive_map, 0)
    restarted_replacement.restore(replacement_payload)
    restarted = DifferentialRunner(
        restarted_legacy,
        restarted_replacement,
        requirement_ids,
        legacy_projection=lambda _engine: {
            zone: state.keep_on
            for zone, state in restarted_legacy.policy.states.items()
        },
        replacement_projection=lambda _engine: dict.fromkeys(
            predictive_map.zones(),
            False,
        ),
    )
    restart_frame = restarted.compare_restart()
    assert restart_frame.legacy.normalization == pytest.approx(1.0, abs=1e-12)
    assert restart_frame.replacement.normalization == pytest.approx(
        1.0,
        abs=1e-12,
    )
    assert all(mismatch.requirement_id for mismatch in restart_frame.mismatches)
    continued_event = OccupancyEvent(
        **{
            **make_event().__dict__,
            "state": "off",
            "event_at": NOW + timedelta(seconds=4),
        }
    )
    continuation_frames = (
        restarted.observe(continued_event),
        restarted.finalize(NOW + timedelta(seconds=5)),
    )
    assert all(
        mismatch.requirement_id
        for frame in continuation_frames
        for mismatch in frame.mismatches
    )
