"""User request: complete restart-safe, bounded postpublication learning.

Expected: accepted adjacent observations survive saves/failures without changing
live lease statistics; selected/correlated/predicted outcomes never teach routes.
Observed: retained synthetic c->t learning is early or lost across callbacks/save.
Source: 2026-09-14 completion-learning-mapping and explicit durable repair request.
Scope: real observed pending work after strictly accepted structural restoration;
not a new physical incident. Component-only numerical calibration is labeled.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest

from custom_components.predictive_controls.const import DISPATCH_UPDATE
from custom_components.predictive_controls.events import event_from_entity
from custom_components.predictive_controls.markov import MARKOV_COUNT_LIMIT, MarkovChain
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model import persistence as persistence
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.prediction import (
    TargetPredictionManager,
)
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    ZoneModelResult,
)
from tests.runtime_replay import RuntimeScenario
from tests.test_learning_publication_completion import (
    _at,
    _input,
    _map,
    _pending,
    _restored,
    _round_trip,
)
from tests.test_prediction import _legacy_confirmation, make_map

pytestmark = pytest.mark.target_model


def test_raw_accepted_learning_survives_save_before_drain() -> None:
    """Real queue qualification precedes the old writer's observable lost count."""
    model, engine, queued, _ = _pending()
    original_raw = tuple(engine._pending_prediction_learning)
    payload = serialize_target_state(model, engine)
    unchanged = deepcopy(payload)
    restarted = restore_target_state(model, payload, engine.snapshot.updated_at)
    assert engine._pending_prediction_learning == [queued]
    assert tuple(engine._pending_prediction_learning) == original_raw
    assert not restarted._pending_prediction_learning
    restarted.commit_prediction_learning()
    assert restarted.prediction_manager.chain.counts["c"]["t"] == 1
    restarted.commit_prediction_learning()
    assert restarted.prediction_manager.chain.counts["c"]["t"] == 1
    assert payload == unchanged


@pytest.mark.parametrize("fail", (False, True))
def test_callback_saved_learning_survives_subscriber_failure(fail: bool) -> None:
    model = _map()
    engine = _restored(model)
    engine.observe(_input("e", "on", 37))
    saved: list[dict[str, object]] = []

    def publish(result: ZoneModelResult) -> None:
        assert result.snapshot == engine.snapshot
        queued, = engine._pending_prediction_learning
        assert queued in result.authorizations
        assert engine.prediction_manager.chain.counts["c"]["t"] == 0
        saved.append(serialize_target_state(model, engine))
        if fail:
            raise RuntimeError("saved subscriber failed")

    if fail:
        with pytest.raises(RuntimeError, match="saved subscriber failed"):
            engine.observe(_input("t", "on", 38), result_callback=publish)
    else:
        engine.observe(_input("t", "on", 38), result_callback=publish)
    assert len(saved) == 1
    restarted = restore_target_state(model, saved[0], _at(38))
    for candidate in (restarted, engine):
        candidate.commit_prediction_learning()
        assert candidate.prediction_manager.chain.counts["c"]["t"] == 1
        candidate.commit_prediction_learning()
        assert candidate.prediction_manager.chain.counts["c"]["t"] == 1


@pytest.mark.parametrize("boundary", ("minute", "transient", "count"))
@pytest.mark.parametrize("fail", (False, True))
def test_runtime_timer_count_publish_before_learning(
    boundary: str, fail: bool,
) -> None:
    """Real runtime callbacks publish current metadata before prior raw learning.

    Engine-level real e37/t38 observations intentionally stop before the consumer's
    drain, representing accepted work left at a publication/save boundary. No
    queue, lease or authorization is injected into the runtime engine.
    """
    model = _map()
    prefix = serialize_target_state(model, _restored(model))
    with RuntimeScenario(_at(36)) as scenario:
        replay = scenario.create(model, 2)
        runtime = replay.runtime
        assert runtime.confidence.restore_state(prefix, _at(36))
        engine = cast(ZoneModelEngine, runtime.confidence._engine)
        if boundary == "transient":
            # Actual stable-clear deadline guarantees a transient publication;
            # diagnostic-only lease expiry is not itself a public update.
            engine.observe(_input("b", "off", 36))
        engine.observe(_input("e", "on", 37))
        result = engine.observe(_input("t", "on", 38))
        queued, = engine._pending_prediction_learning
        assert queued in result.authorizations
        assert queued.path_node_ids == ("z", "c", "t")
        assert engine.prediction_manager.chain.counts["c"]["t"] == 0
        seen: list[tuple[float, str | None]] = []
        saves: list[dict[str, object]] = []
        scenario.patch.setattr(
            runtime, "schedule_transition_count_save",
            lambda: saves.append(runtime.transition_store_data()),
        )
        frontier = _at(41 if boundary == "transient" else 39)

        def published() -> None:
            seen.append((runtime.chain.counts["c"]["t"],
                         runtime.confidence.diagnostics.event_disposition))
            assert runtime.confidence.policy_decisions
            assert all(row.event_at == frontier
                       for row in runtime.confidence.policy_decisions)
            before = runtime.transition_store_data()
            for mutate in (
                runtime.confidence.commit_prediction_learning,
                lambda: runtime.confidence.refresh_active(frontier),
                lambda: runtime.observe_node("c", frontier),
            ):
                with pytest.raises(ValueError, match="Model mutation is forbidden"):
                    mutate()
                assert runtime.transition_store_data() == before
            saved = runtime.transition_store_data()
            restored = restore_target_state(model, saved, frontier)
            assert serialize_target_state(model, restored) == saved
            if fail:
                raise RuntimeError("runtime subscriber failed")

        replay.hass.dispatchers[DISPATCH_UPDATE].append(published)

        def run() -> None:
            if boundary == "count":
                replay.send("sensor.replay_people", "0", frontier)
            else:
                scenario.clock.now = frontier
                if boundary == "minute":
                    runtime._async_refresh_active_confidence(frontier)
                else:
                    runtime._async_expire_transient_state(frontier)

        if fail:
            with pytest.raises(RuntimeError, match="runtime subscriber failed"):
                run()
        else:
            run()
        assert seen == [(0, "accepted" if boundary == "count" else "advanced")]
        assert runtime.chain.counts["c"]["t"] == 1
        assert saves
        restored = restore_target_state(model, saves[-1], frontier)
        restored.commit_prediction_learning()
        assert restored.prediction_manager.chain.counts["c"]["t"] == 1
        assert not engine._pending_prediction_learning
        assert frontier > _at(38) + timedelta(microseconds=1)


def _debt(manager: TargetPredictionManager) -> dict[str, dict[str, float | None]]:
    return cast(
        dict[str, dict[str, float | None]], manager.serialize()["deferred_counts"],
    )


def test_bootstrap_advance_does_not_drain_before_publication() -> None:
    model, engine, _, _ = _pending()
    saved = serialize_target_state(model, engine)
    with RuntimeScenario(_at(39)) as scenario:
        replay = scenario.create(model, 2)
        tracker = replay.runtime.confidence
        assert tracker.restore_state(saved, _at(38))
        # Real known states, not inferred authorizations, drive bootstrap.
        event = event_from_entity(model, "binary_sensor.t", "on", _at(39))
        assert event is not None
        tracker.bootstrap_state((event,), cold_start=False)
        assert tracker.prediction_chain.counts["c"]["t"] == 0

        def published() -> None:
            assert tracker.prediction_chain.counts["c"]["t"] == 0

        tracker.publish_current_projection(published)
        assert tracker.commit_prediction_learning()
        assert tracker.prediction_chain.counts["c"]["t"] == 1


def test_blocked_runtime_subscriber_failure_still_saves() -> None:
    model, engine, _, event = _pending(same_row=True, support=30)
    engine.observe(event)
    assert not engine.commit_prediction_learning()
    assert _debt(engine.prediction_manager)["c"]["t"] == 1
    payload = serialize_target_state(model, engine)
    with RuntimeScenario(_at(71)) as scenario:
        replay = scenario.create(model, 2)
        runtime = replay.runtime
        assert runtime.confidence.restore_state(payload, _at(71))
        saves: list[dict[str, object]] = []
        scenario.patch.setattr(runtime, "schedule_transition_count_save",
                               lambda: saves.append(runtime.transition_store_data()))

        def fail() -> None:
            assert runtime.chain.counts["c"]["t"] == 0
            raise RuntimeError("blocked subscriber")

        replay.hass.dispatchers[DISPATCH_UPDATE].append(fail)
        with pytest.raises(RuntimeError, match="blocked subscriber"):
            runtime.observe_node("c", _at(71))
        assert len(saves) == 1
        restored = restore_target_state(model, saves[0], _at(71))
        assert not restored.commit_prediction_learning()
        assert _debt(restored.prediction_manager)["c"]["t"] == 1


@pytest.mark.parametrize("callbacks", (False, True))
def test_preparation_failure_preserves_prior_raw_and_no_new_work(
    callbacks: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, engine, queued, event = _pending()
    before = engine.prediction_state
    prepare = engine._prepare_predictions
    calls: list[ZoneModelResult] = []

    def fail(*args: Any, **kwargs: Any) -> None:
        prepare(*args, **kwargs)
        raise RuntimeError("preparation failure")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_prepare_predictions", fail)
        with pytest.raises(RuntimeError, match="preparation failure"):
            engine.observe(event, result_callback=calls.append if callbacks else None)
    assert calls == []
    assert engine._pending_prediction_learning == [queued]
    assert engine.prediction_state["deferred_counts"] == before["deferred_counts"]
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    assert engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1


@pytest.mark.parametrize("stage", ("fold", "apply"))
def test_failed_drain_transfer_is_retryable_exactly_once(
    stage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, engine, queued, _ = _pending()
    before = engine.prediction_state
    original_chain = engine.prediction_manager.chain

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("drain failed")

    with monkeypatch.context() as patch:
        if stage == "fold":
            patch.setattr(engine.prediction_manager, "_project_deferred", fail)
        else:
            patch.setattr(MarkovChain, "restore_counts", fail)
        with pytest.raises(RuntimeError, match="drain failed"):
            engine.commit_prediction_learning()
    assert engine.prediction_manager.chain is original_chain
    assert engine._pending_prediction_learning == ([queued] if stage == "fold" else [])
    assert engine.prediction_state == before
    _round_trip(model, engine)
    assert engine.commit_prediction_learning()
    assert engine.prediction_manager.chain.counts["c"]["t"] == 1
    assert not engine.commit_prediction_learning()


@pytest.mark.parametrize("initial", (0.125, 999_998.25, MARKOV_COUNT_LIMIT))
def test_component_fractional_capped_observation_algebra(initial: float) -> None:
    """Component numerical calibration, not a fabricated engine input history."""
    _, _, result = _legacy_confirmation()
    auth, = result.authorizations
    manager = TargetPredictionManager(make_map())
    reference = MarkovChain(make_map())
    seed = manager.chain.counts
    seed["hall"]["kitchen"] = initial
    manager.chain.restore_counts(seed)
    reference.restore_counts(seed)
    for _ in range(7):
        manager.defer((auth,))
        reference.observe("hall", "kitchen")
        assert manager.chain.counts["hall"]["kitchen"] == initial
        expected = reference.counts["hall"]["kitchen"]
        assert _debt(manager)["hall"]["kitchen"] == (
            expected if expected > initial else None
        )
    assert manager.commit(()) == (initial < MARKOV_COUNT_LIMIT)
    assert manager.chain.counts == reference.counts
    assert all(value is None for row in _debt(manager).values()
               for value in row.values())
    chain = manager.chain
    assert not manager.commit(()) and manager.chain is chain


def test_component_competing_edges_block_whole_row_not_unrelated_row() -> None:
    """Explicit statistical component batches use real frozen row-C leases."""
    model, engine, queued, event = _pending(same_row=True, support=30)
    engine.observe(event)
    manager = engine.prediction_manager
    leases, grants, snapshot = manager.leases, manager.grants, engine.snapshot
    assert any(lease.current_node_id == "c" for lease in leases)
    # These are numerical component observations, not new physical engine facts.
    competing = replace(queued, target_node_id="v", target_zone="v",
                        path_node_ids=("z", "c", "v"))
    separate = replace(queued, target_node_id="w", target_zone="w",
                       path_node_ids=("y", "z", "w"))
    assert manager.commit((competing, separate))
    assert manager.chain.counts["z"]["w"] == 1
    assert manager.chain.counts["c"]["t"] == 0
    assert manager.chain.counts["c"]["v"] == 30
    assert _debt(manager)["c"]["t"] == 1
    assert _debt(manager)["c"]["v"] == 31
    assert (manager.leases, manager.grants, engine.snapshot) == (
        leases, grants, snapshot,
    )
    _round_trip(model, engine)
    engine.advance(_at(81))
    assert engine.commit_prediction_learning()
    assert manager.chain.counts["c"]["t"] == 1
    assert manager.chain.counts["c"]["v"] == 31
    assert not engine.commit_prediction_learning()
    _round_trip(model, engine)


@pytest.mark.parametrize("boundary", ("zero", "health", "expiry"))
def test_qualified_debt_outlives_inference_revocation(boundary: str) -> None:
    model, engine, _, event = _pending(same_row=True, support=30)
    engine.observe(event)
    engine.commit_prediction_learning()
    old_episode = next(s.episode_id for s in engine.snapshot.episode_states
                       if s.node_id == "c")
    if boundary == "zero":
        engine.observe_count(CountInput("zero", 0, True, _at(72)))
        engine.observe(_input("c", "off", 73))
        assert not engine.snapshot.traversal_tokens
        assert not any(engine.snapshot.selected_paths)
        assert not engine.prediction_manager.leases
    elif boundary == "health":
        engine.observe(_input("c", "unavailable", 72))
        assert not any(lease.current_node_id == "c"
                       for lease in engine.prediction_manager.leases)
    else:
        engine.advance(_at(81))
    assert engine.prediction_manager.chain.counts["c"]["t"] == 0
    saved = serialize_target_state(model, engine)
    restarted = restore_target_state(model, saved, engine.snapshot.updated_at)
    assert _debt(restarted.prediction_manager)["c"]["t"] == 1
    for candidate in (engine, restarted):
        assert candidate.commit_prediction_learning()
        assert candidate.prediction_manager.chain.counts["c"]["t"] == 1
        assert not candidate.commit_prediction_learning()
    if boundary == "zero":
        # Zero clears inference, not the independently observed physical episode.
        assert next(s.episode_id for s in engine.snapshot.episode_states
                    if s.node_id == "c") == old_episode


@pytest.mark.parametrize("mutation", (
    "missing", "container", "missing_row", "extra_row", "row_type",
    "missing_edge", "extra_edge", "boolean", "text", "nan", "infinity",
    "negative", "equal", "over_cap", "saturated",
))
def test_required_matrix_rejects_atomically_and_continues(mutation: str) -> None:
    model, engine, queued, _ = _pending()
    valid = engine.prediction_state
    bad = deepcopy(valid)
    debt = cast(dict[str, dict[str, object]], bad["deferred_counts"])
    if mutation == "missing":
        del bad["deferred_counts"]
    elif mutation == "container":
        bad["deferred_counts"] = []
    elif mutation == "missing_row":
        del debt["c"]
    elif mutation == "extra_row":
        debt["missing"] = {}
    elif mutation == "row_type":
        cast(dict[str, object], debt)["c"] = []
    elif mutation == "missing_edge":
        del debt["c"]["t"]
    elif mutation == "extra_edge":
        debt["c"]["missing"] = None
    else:
        invalid: dict[str, object] = {
            "boolean": True, "text": "1", "nan": float("nan"),
            "infinity": float("inf"), "negative": -1, "equal": 0,
            "over_cap": MARKOV_COUNT_LIMIT + 1, "saturated": MARKOV_COUNT_LIMIT,
        }
        debt["c"]["t"] = invalid[mutation]
        if mutation == "saturated":
            cast(dict[str, dict[str, float]], bad["counts"])["c"]["t"] = (
                MARKOV_COUNT_LIMIT
            )
    original = deepcopy(bad)
    receiver = engine.prediction_manager
    before = receiver.serialize()
    assert receiver.leases and engine._pending_prediction_learning == [queued]
    # Component restore would prune expired leases at100; malformed debt must
    # reject before pruning/installation, not become invisible during expiry.
    with pytest.raises(ValueError, match="deferred count"):
        receiver.restore(bad, _at(100))
    assert receiver.serialize() == before
    assert repr(bad) == repr(original)  # NaN does not compare equal numerically.
    with pytest.raises(ValueError, match="deferred count"):
        engine.restore_prediction_state(bad, _at(38))
    assert engine._pending_prediction_learning == [queued]
    assert receiver.serialize() == before
    assert engine.prediction_state == valid
    _round_trip(model, engine)
    assert engine.commit_prediction_learning()
    assert receiver.chain.counts["c"]["t"] == 1


def test_empty_rows_and_detached_projection_are_required() -> None:
    model = PredictiveMap.from_mapping({"nodes": {"isolated": {}}})
    manager = TargetPredictionManager(model)
    assert _debt(manager) == {"isolated": {}}
    saved = manager.serialize()
    restored = TargetPredictionManager.restored(model, saved, _at(0))
    assert restored.serialize() == saved
    cast(dict[str, object], saved["deferred_counts"]).clear()
    assert _debt(manager) == {"isolated": {}}
    assert _debt(restored) == {"isolated": {}}
    with pytest.raises(ValueError, match="deferred count"):
        restored.restore(saved, _at(0))


def test_current_fingerprint_rejects_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import json

    model, engine, _, _ = _pending()
    recipe = persistence._target_map_fingerprint_payload(model)
    assert type(recipe["deferred_prediction_learning_version"]) is int
    assert recipe.pop("deferred_prediction_learning_version") == 1
    old = hashlib.sha256(json.dumps(recipe, sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()
    saved = serialize_target_state(model, engine)
    assert saved["map_fingerprint"] != old
    saved["map_fingerprint"] = old

    def forbidden(*_args: object) -> None:
        pytest.fail("old fingerprint reached nested decoder")

    monkeypatch.setattr(persistence, "_decode_snapshot", forbidden)
    with pytest.raises(ValueError, match="map fingerprint"):
        restore_target_state(model, saved, _at(38))


@pytest.mark.parametrize("kind", ("ordinary", "correlated", "predicted"))
def test_selected_and_prediction_confirmation_never_create_debt(kind: str) -> None:
    model = _map()
    engine = ZoneModelEngine(model, 2, _at(0))
    if kind == "predicted":
        for _ in range(30):
            engine.prediction_manager.chain.observe("c", "t")
    counts = engine.prediction_manager.chain.counts
    for at, node in enumerate(("a", "b", "c")):
        result = engine.observe(_input(node, "on", at))
    assert result.authorizations[-1].provenance_kind == "selected_path"
    if kind == "predicted":
        policy = next(p for p in engine.snapshot.policy_states if p.zone == "t")
        assert policy.phase == "predicted"
        engine.observe(_input("t", "on", 3))
        policy = next(p for p in engine.snapshot.policy_states if p.zone == "t")
        assert policy.phase != "predicted"
    elif kind == "correlated":
        engine.observe(_input("c", "off", 3))
        result = engine.observe(_input("c", "on", 4))
        assert result.disposition == "correlated_reassertion"
    assert not engine.commit_prediction_learning()
    assert not engine._pending_prediction_learning
    assert engine.prediction_manager.chain.counts == counts
    assert all(value is None for row in _debt(engine.prediction_manager).values()
               for value in row.values())
    _round_trip(model, engine)
