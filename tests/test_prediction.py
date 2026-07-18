from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.prediction import (
    PredictionLease,
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
    TraversalToken,
    ZoneModelResult,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "entities": {"motion": "binary_sensor.office"},
                    "adjacent": ["hall"],
                },
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall"},
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {
                    "zone": "kitchen",
                    "entities": {"motion": "binary_sensor.kitchen"},
                    "adjacent": ["hall"],
                },
                "living": {
                    "zone": "living",
                    "entities": {"motion": "binary_sensor.living"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def accepted_traversal() -> tuple[ZoneModelEngine, ZoneModelResult]:
    engine = ZoneModelEngine(make_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.office", "on", NOW))
    result = engine.observe(
        SensorInput("binary_sensor.hall", "on", NOW + timedelta(seconds=1))
    )
    return engine, result


def test_prediction_uses_only_accepted_graph_traversal() -> None:
    _, result = accepted_traversal()
    manager = TargetPredictionManager(make_map())

    manager.apply(result)

    assert manager.probabilities == pytest.approx({"kitchen": 0.5, "living": 0.5})
    assert manager.chain.counts["office"]["hall"] == 1.0
    assert all(lease.target_zone != "office" for lease in manager.leases)


def test_prediction_rejects_source_free_and_ambiguous_sources() -> None:
    engine, result = accepted_traversal()
    target = result.authorizations[0]
    manager = TargetPredictionManager(make_map())
    source_free = replace(target, reason="source_free_corroborated", source_tokens=())
    second = TraversalToken(
        "kitchen:kitchen:1",
        "kitchen",
        "kitchen",
        "stay",
        "stay_pir",
        "kitchen:1",
        NOW,
        NOW + timedelta(seconds=30),
    )
    ambiguous = replace(target, source_tokens=(*target.source_tokens, second))

    manager.apply(
        ZoneModelResult("accepted", engine.snapshot, authorizations=(source_free,))
    )
    manager.apply(
        ZoneModelResult("accepted", engine.snapshot, authorizations=(ambiguous,))
    )

    assert manager.probabilities == {}
    assert all(
        count == 0.0
        for targets in manager.chain.counts.values()
        for count in targets.values()
    )


def test_prediction_expiry_count_zero_and_restore_are_isolated() -> None:
    engine, result = accepted_traversal()
    manager = TargetPredictionManager(make_map())
    manager.apply(result)
    payload = manager.serialize()

    restored = TargetPredictionManager(make_map())
    restored.restore(payload, NOW + timedelta(seconds=2))
    assert restored.probabilities == manager.probabilities
    assert restored.expire(NOW + timedelta(minutes=1))
    assert restored.probabilities == {}

    restored.apply(result)
    count_zero = replace(
        engine.snapshot,
        count_state=replace(engine.snapshot.count_state, expected_count=0),
    )
    restored.apply(ZoneModelResult("accepted", count_zero))
    assert restored.probabilities == {}


def test_prediction_cancels_on_new_target_sensor_evidence() -> None:
    engine, result = accepted_traversal()
    manager = TargetPredictionManager(make_map())
    manager.apply(result)

    contradictory = engine.observe(
        SensorInput("binary_sensor.kitchen", "off", NOW + timedelta(seconds=2))
    )
    manager.apply(contradictory)

    assert manager.probabilities == {"living": 0.5}


def test_prediction_manager_cannot_change_authoritative_snapshot() -> None:
    engine, result = accepted_traversal()
    before = engine.snapshot

    TargetPredictionManager(make_map()).apply(result)

    assert engine.snapshot == before


def test_prediction_restore_rejects_map_incompatible_lease_atomically() -> None:
    _, result = accepted_traversal()
    manager = TargetPredictionManager(make_map())
    manager.apply(result)
    payload = manager.serialize()
    leases = payload["leases"]
    assert isinstance(leases, list)
    leases[0]["target_node_id"] = "missing"

    restored = TargetPredictionManager(make_map())
    with pytest.raises(ValueError, match="map-incompatible"):
        restored.restore(payload, NOW + timedelta(seconds=2))
    assert restored.probabilities == {}


def test_prediction_restore_and_decoder_boundaries() -> None:
    manager = TargetPredictionManager(make_map())
    with pytest.raises(ValueError, match="invalid"):
        manager.restore({"counts": [], "leases": []}, NOW)
    with pytest.raises(ValueError, match="mapping"):
        manager._decode_lease([])  # noqa: SLF001
    with pytest.raises(ValueError, match="invalid"):
        manager._decode_lease({})  # noqa: SLF001

    _, result = accepted_traversal()
    authorization = result.authorizations[0]
    manager._apply_authorization(  # noqa: SLF001
        replace(authorization, target_node_id="missing")
    )
    manager.apply(result)
    payload = manager.serialize()
    leases = payload["leases"]
    assert isinstance(leases, list)
    expired = replace(
        manager.leases[0], expires_at=NOW + timedelta(seconds=1, milliseconds=500)
    )
    payload["leases"] = [
        {
            **expired.__dict__,
            "created_at": expired.created_at.isoformat(),
            "expires_at": expired.expires_at.isoformat(),
        }
    ]
    restored = TargetPredictionManager(make_map())
    restored.restore(payload, NOW + timedelta(seconds=2))
    assert restored.leases == ()


@pytest.mark.parametrize(
    "update",
    (
        {"probability": 2.0},
        {"expires_at": NOW.isoformat()},
        {"source_node_id": ""},
    ),
)
def test_prediction_decoder_rejects_invalid_lease_values(
    update: dict[str, object],
) -> None:
    raw: dict[str, object] = {
        "source_node_id": "office",
        "current_node_id": "hall",
        "target_node_id": "kitchen",
        "target_zone": "kitchen",
        "probability": 0.5,
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        "reason": "accepted graph traversal",
    }
    raw.update(update)
    with pytest.raises(ValueError, match="invalid"):
        TargetPredictionManager(make_map())._decode_lease(raw)  # noqa: SLF001


def test_prediction_enforces_live_and_restored_lease_bounds() -> None:
    _, result = accepted_traversal()
    authorization = result.authorizations[0]
    manager = TargetPredictionManager(make_map())
    for index in range(64):
        lease = PredictionLease(
            f"source-{index}",
            f"current-{index}",
            f"target-{index}",
            f"zone-{index}",
            0.5,
            NOW,
            NOW + timedelta(seconds=30),
            "test seed",
        )
        manager._leases[
            (lease.source_node_id, lease.current_node_id, lease.target_node_id)
        ] = lease  # noqa: SLF001
    manager._apply_authorization(authorization)  # noqa: SLF001
    assert len(manager.leases) == 64

    target_ids = [f"target_{index}" for index in range(65)]
    nodes: dict[str, object] = {
        "source": {"adjacent": ["hub"]},
        "hub": {"adjacent": ["source", *target_ids]},
    }
    nodes.update({target: {"adjacent": ["hub"]} for target in target_ids})
    large_map = PredictiveMap.from_mapping({"nodes": nodes})
    leases = [
        {
            "source_node_id": "source",
            "current_node_id": "hub",
            "target_node_id": target,
            "target_zone": target,
            "probability": 1 / 65,
            "created_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            "reason": "accepted graph traversal",
        }
        for target in target_ids
    ]
    with pytest.raises(ValueError, match="bound exceeded"):
        TargetPredictionManager(large_map).restore(
            {"counts": {}, "leases": leases}, NOW
        )
