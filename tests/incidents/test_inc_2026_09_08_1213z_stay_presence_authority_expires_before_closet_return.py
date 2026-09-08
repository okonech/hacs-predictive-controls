from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
    serialize_target_state,
)
from custom_components.predictive_controls.zone_model.types import SensorInput


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _incident_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "top": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.top"},
                    "adjacent": ["entrance"],
                    "initial_weight": 0.85,
                },
                "entrance": {
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.entrance"},
                    "adjacent": ["top", "closet"],
                    "initial_weight": 0.8,
                },
                "closet": {
                    "role": "subzone_occupancy",
                    "occupancy_behavior": "sustained",
                    "entities": {"mmwave": "binary_sensor.closet"},
                    "adjacent": ["entrance", "bathroom"],
                    "initial_weight": 0.8,
                },
                "bathroom": {
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {"mmwave": "binary_sensor.bathroom"},
                    "adjacent": ["closet"],
                    "initial_weight": 0.7,
                },
            }
        }
    )


def _engine_with_settled_bathroom_support(
    predictive_map: PredictiveMap,
    authoritative_count: int,
) -> ZoneModelEngine:
    route_at = _at("2026-09-08T10:00:00Z")
    engine = ZoneModelEngine(
        predictive_map,
        authoritative_count,
        route_at - timedelta(seconds=1),
    )
    for offset, entity_id in enumerate(
        (
            "binary_sensor.top",
            "binary_sensor.entrance",
            "binary_sensor.closet",
            "binary_sensor.bathroom",
        )
    ):
        engine.observe(
            SensorInput(entity_id, "on", route_at + timedelta(seconds=offset))
        )
    for offset, entity_id in enumerate(
        (
            "binary_sensor.top",
            "binary_sensor.entrance",
            "binary_sensor.closet",
            "binary_sensor.bathroom",
        ),
        start=10,
    ):
        engine.observe(
            SensorInput(entity_id, "off", route_at + timedelta(seconds=offset))
        )
    engine.advance(_at("2026-09-08T11:00:00Z"))

    assert [
        (support.current_node_id, support.current_zone, support.state)
        for support in engine.snapshot.anonymous_supports
    ] == [("bathroom", "bathroom", "settled")]
    assert engine.snapshot.traversal_tokens == ()
    return engine


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_inc_2026_09_08_1213z_stay_presence_authority_expires_before_closet_return(
    authoritative_count: int,
) -> None:
    predictive_map = _incident_map()
    engine = _engine_with_settled_bathroom_support(
        predictive_map,
        authoritative_count,
    )
    closet_at = _at("2026-09-08T12:13:34.142281Z")
    bathroom_at = _at("2026-09-08T12:14:24.044050Z")
    closet_clear_at = _at("2026-09-08T12:14:52.365745Z")
    target_at = _at("2026-09-08T12:16:24.972720Z")
    restore_at = target_at - timedelta(microseconds=1)
    sleep_off_at = _at("2026-09-08T12:16:56.291116Z")

    first_closet = engine.observe(
        SensorInput("binary_sensor.closet", "on", closet_at)
    )
    bathroom = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", bathroom_at)
    )
    engine.observe(SensorInput("binary_sensor.closet", "off", closet_clear_at))
    engine.advance(restore_at)

    first_closet_authorization = first_closet.authorizations[0]
    bathroom_authorization = bathroom.authorizations[0]
    bathroom_episode = next(
        state
        for state in bathroom.snapshot.episode_states
        if state.node_id == "bathroom"
    )
    bathroom_token = next(
        token
        for token in bathroom.snapshot.traversal_tokens
        if token.episode_id == bathroom_episode.episode_id
    )
    assert not first_closet_authorization.authorized
    assert first_closet_authorization.reason == "track_bootstrap_pending"
    assert bathroom_authorization.authorized
    assert bathroom_authorization.reason == "settled_endpoint_reacquired"
    assert target_at - bathroom_at == timedelta(seconds=120, microseconds=928670)

    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        restore_at,
    )
    target = engine.observe(
        SensorInput("binary_sensor.closet", "on", target_at)
    )
    restored_target = restored.observe(
        SensorInput("binary_sensor.closet", "on", target_at)
    )
    target_authorization = target.authorizations[0]
    closet_policy = next(
        state for state in target.snapshot.policy_states if state.zone == "closet"
    )

    assert closet_policy.active, (
        target_authorization.authorized,
        target_authorization.reason,
    )
    assert target_authorization.authorized
    assert target_authorization.reason == "adjacent_authorized"
    public_events = [
        (event.zone, event.kind, event.event_at)
        for event in target.policy_events
    ]
    assert public_events == [("closet", "acquired", target_at)]
    assert bathroom_token.valid_until == bathroom_at + timedelta(seconds=180)
    assert restored_target.snapshot == target.snapshot
    assert restored_target.policy_events == target.policy_events
    assert restored_target.authorizations == target.authorizations

    for entity_id, event_at in (
        ("binary_sensor.entrance", _at("2026-09-08T12:16:30.116610Z")),
        ("binary_sensor.top", _at("2026-09-08T12:16:31.748532Z")),
    ):
        result = engine.observe(SensorInput(entity_id, "on", event_at))
        restored_result = restored.observe(SensorInput(entity_id, "on", event_at))
        assert restored_result.snapshot == result.snapshot
    sleep_off = engine.advance(sleep_off_at)
    restored_sleep_off = restored.advance(sleep_off_at)
    sleep_off_closet = next(
        state
        for state in sleep_off.snapshot.policy_states
        if state.zone == "closet"
    )
    assert sleep_off_closet.active
    assert restored_sleep_off.snapshot == sleep_off.snapshot
    assert all(
        "interaction" not in state.node_id
        for state in sleep_off.snapshot.episode_states
    )


@pytest.mark.target_model
def test_inc_2026_09_08_settled_correlated_reacquisition_issues_no_token() -> None:
    predictive_map = _incident_map()
    engine = _engine_with_settled_bathroom_support(predictive_map, 1)
    asserted_at = _at("2026-09-08T12:14:24.044050Z")
    clear_at = asserted_at + timedelta(seconds=10)
    stable_clear_at = clear_at + timedelta(seconds=10)
    correlated_at = stable_clear_at + timedelta(seconds=10)

    asserted = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", asserted_at)
    )
    engine.observe(SensorInput("binary_sensor.bathroom", "off", clear_at))
    engine.advance(stable_clear_at)
    token_ids_before = tuple(
        token.token_id for token in engine.snapshot.traversal_tokens
    )
    correlated = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", correlated_at)
    )

    assert asserted.authorizations[0].reason == "settled_endpoint_reacquired"
    assert correlated.disposition == "accepted_correlated_positive"
    assert correlated.authorizations[0].reason == "settled_endpoint_reacquired"
    assert tuple(
        token.token_id for token in correlated.snapshot.traversal_tokens
    ) == token_ids_before


# Synthetic extensions of the reopened 1213Z report, NOT new live observations.
# Everything above this marker is the immutable original file (SHA-256 in spec).
# Imports remain here deliberately to preserve that entire byte-for-byte prefix.
from dataclasses import replace  # noqa: E402
from importlib import import_module  # noqa: E402
from types import MappingProxyType  # noqa: E402

from custom_components.predictive_controls.zone_model import (  # noqa: E402
    types as zone_types,
)
from custom_components.predictive_controls.zone_model.persistence import (  # noqa: E402
    target_map_fingerprint,
)
from custom_components.predictive_controls.zone_model.policy import (  # noqa: E402
    POLICY_CALIBRATIONS,
)
from custom_components.predictive_controls.zone_model.profiles import (  # noqa: E402
    build_physical_nodes,
)


def _strict_round_trip(
    predictive_map: PredictiveMap,
    engine: ZoneModelEngine,
) -> ZoneModelEngine:
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)
    assert restored.snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, restored) == payload
    return restored


def _synthetic_long_stay_engine(
    predictive_map: PredictiveMap,
    authoritative_count: int,
    source_age: int,
    target_kind: str,
) -> tuple[ZoneModelEngine, datetime]:
    """Event-only ordinary history; correlated history is an explicit composite."""
    engine = _engine_with_settled_bathroom_support(
        predictive_map, authoritative_count
    )
    # Drain historical route learning before the tested event, including live mode.
    engine.commit_prediction_learning()
    original_support = engine.snapshot.anonymous_supports[0]
    source_at = _at("2026-09-08T12:00:00Z")
    acquired = engine.observe(SensorInput("binary_sensor.bathroom", "on", source_at))
    assert acquired.authorizations[0].reason == "settled_endpoint_reacquired"
    target_at = source_at + timedelta(seconds=source_age)
    frontier = target_at - timedelta(microseconds=1)
    engine.advance(frontier)
    assert (
        engine.snapshot.anonymous_supports[0].support_id == original_support.support_id
    )

    if target_kind == "correlated":
        # Independently generated target history: never prime beside an eligible
        # source (which would consume it on the proposed implementation). The old
        # isolated cycle preserves generation ordering for historical references.
        donor = ZoneModelEngine(
            predictive_map, authoritative_count, _at("2026-09-08T09:59:59Z")
        )
        for event_at, state in (
            (_at("2026-09-08T10:00:02Z"), "on"),
            (_at("2026-09-08T10:00:12Z"), "off"),
            (target_at - timedelta(seconds=40), "on"),
            (target_at - timedelta(seconds=30), "off"),
        ):
            donor.observe(SensorInput("binary_sensor.closet", state, event_at))
        donor.advance(target_at - timedelta(seconds=20))
        donor.advance(frontier)
        isolated = donor.snapshot
        assert not isolated.traversal_tokens
        assert not isolated.retained_traversal_tokens
        assert not isolated.anonymous_supports
        assert not isolated.authorization_uses
        donor_target = next(s for s in isolated.episode_states if s.node_id == "closet")
        assert donor_target.status == "clear" and donor_target.clear_emitted
        assert donor_target.cadence_run_started_at == target_at - timedelta(seconds=40)
        assert donor_target.cadence_last_transition_at == target_at - timedelta(
            seconds=30
        )
        # The counter increments on the completing reassertion at T, not clear.
        assert donor_target.cadence_cycle_count == 0
        assert not donor_target.cadence_warning
        assert not next(s for s in isolated.policy_states if s.zone == "closet").active
        _strict_round_trip(predictive_map, donor)

        original = engine.snapshot
        composite = replace(
            original,
            episode_states=tuple(
                donor_target if s.node_id == "closet" else s
                for s in original.episode_states
            ),
            belief_states=tuple(
                next(d for d in isolated.belief_states if d.zone == "closet")
                if s.zone == "closet" else s
                for s in original.belief_states
            ),
            policy_states=tuple(
                next(d for d in isolated.policy_states if d.zone == "closet")
                if s.zone == "closet" else s
                for s in original.policy_states
            ),
            pending_candidates=isolated.pending_candidates,
            reliability_warning_occurrences=tuple(sorted(
                (
                    *(w for w in original.reliability_warning_occurrences
                      if w.node_id != "closet"),
                    *(w for w in isolated.reliability_warning_occurrences
                      if w.node_id == "closet"),
                ),
                key=lambda w: (w.node_id, w.reason),
            )),
        )
        # Strict existing validators, no fabricated support/token or inherited
        # audit claim. Preserve independently learned route data, not a fake route.
        prediction = engine.prediction_manager.serialize()
        engine = ZoneModelEngine.restore(predictive_map, composite, (), frontier)
        engine.restore_prediction_state(prediction, frontier)
        assert engine.snapshot == composite
    _strict_round_trip(predictive_map, engine)
    return engine, target_at


def _assert_eligible_source(
    predictive_map: PredictiveMap,
    snapshot: zone_types.ZoneModelSnapshot,
    target_at: datetime,
    source_age: timedelta,
) -> zone_types.AnonymousOccupancySupport:
    """Literal proposal predicates, not the weaker settled-retention predicate."""
    profiles = import_module(
        "custom_components.predictive_controls.zone_model.profiles"
    ).SHARED_PROFILES
    nodes = {n.node_id: n for n in build_physical_nodes(predictive_map).nodes}
    assert snapshot.count_state.expected_count in (1, 2)
    assert len(snapshot.anonymous_supports) == 1
    support = snapshot.anonymous_supports[0]
    source = next(s for s in snapshot.episode_states if s.node_id == "bathroom")
    belief = next(s for s in snapshot.belief_states if s.zone == "bathroom")
    physical = nodes[source.node_id]
    target = nodes["closet"]
    assert support.state == "settled" and support.valid_until is None
    assert support.current_node_id == physical.node_id == source.node_id
    assert support.current_zone == physical.zone == source.zone == belief.zone
    assert support.current_episode_id == source.episode_id
    assert support.created_at <= support.updated_at <= target_at
    assert source.started_at is not None and source.started_at <= target_at
    assert target_at - source.started_at == source_age
    assert profiles[physical.profile_name].role == "stay"
    assert not physical.interaction_aliases
    assert source.status == "asserted" and source.known_on
    assert source.episode_id is not None
    assert source.health_warning is False and source.cadence_warning is False
    assert belief.health_warning is False and belief.context == "asserted"
    assert (
        belief.generation_episode_id == belief.asserted_episode_id == source.episode_id
    )
    assert belief.outward_context is None
    assert belief.probability >= POLICY_CALIBRATIONS[belief.profile_name].on_threshold
    assert physical.node_id != target.node_id and physical.zone != target.zone
    assert target.node_id in predictive_map.neighbors(physical.node_id)
    assert not target.interaction_aliases and 0 < target.reliability <= 1
    assert source.traversal_valid_until is not None
    assert source.traversal_valid_until <= target_at
    # At exactly 180s the source token may exist at T-1us, but is expired at T.
    assert all(t.valid_until <= target_at for t in snapshot.traversal_tokens)
    assert all(p.node_id == "closet" for p in snapshot.pending_candidates)
    assert not next(p for p in snapshot.policy_states if p.zone == "closet").active
    return support


@pytest.mark.target_model
@pytest.mark.parametrize("source_age", (180, 300, 1800, 7200, 86400))
@pytest.mark.parametrize("authoritative_count", (1, 2))
@pytest.mark.parametrize("target_kind", ("ordinary", "correlated"))
@pytest.mark.parametrize("restored", (False, True), ids=("uninterrupted", "restored"))
def test_long_stay_settled_adjacent_transfer(
    source_age: int,
    authoritative_count: int,
    target_kind: str,
    restored: bool,
) -> None:
    """Synthetic 5 ages × 2 counts × 2 kinds × 2 restart modes = 40 cases."""
    predictive_map = _incident_map()
    engine, target_at = _synthetic_long_stay_engine(
        predictive_map, authoritative_count, source_age, target_kind
    )
    if restored:
        engine = _strict_round_trip(predictive_map, engine)
    before = engine.snapshot
    support = _assert_eligible_source(
        predictive_map, before, target_at, timedelta(seconds=source_age)
    )
    # Independently advance only stored deadlines to establish the event-frontier
    # source projection (especially expiry equality); do not retime physical input.
    elapsed = _strict_round_trip(predictive_map, engine)
    elapsed.advance(target_at, emit_events=False)
    _assert_eligible_source(
        predictive_map, elapsed.snapshot, target_at, timedelta(seconds=source_age)
    )
    assert not elapsed.snapshot.traversal_tokens
    source_belief = next(
        s for s in elapsed.snapshot.belief_states if s.zone == "bathroom"
    )
    source_episode = next(
        s for s in elapsed.snapshot.episode_states if s.node_id == "bathroom"
    )
    created_before = engine.diagnostic_counters["support_created"]
    transferred_before = engine.diagnostic_counters["support_transferred"]
    prediction_before = engine.prediction_manager.serialize()
    assert not engine._pending_prediction_learning
    result = engine.observe(SensorInput("binary_sensor.closet", "on", target_at))
    assert result.disposition == (
        "accepted_correlated_positive"
        if target_kind == "correlated" else "accepted_positive"
    )
    target = next(s for s in result.snapshot.episode_states if s.node_id == "closet")
    previous_target = next(s for s in before.episode_states if s.node_id == "closet")
    assert target.started_at == target_at
    assert target.generation == previous_target.generation + 1
    assert target.episode_id and target.episode_id != previous_target.episode_id
    assert target.status == "asserted" and target.known_on
    assert not target.health_warning and not target.cadence_warning
    assert target.traversal_valid_until is not None
    assert target_at < target.traversal_valid_until
    authorization, = result.authorizations
    policy = next(s for s in result.snapshot.policy_states if s.zone == "closet")
    # First proposed-contract assertion is PUBLIC active; baseline must fail here,
    # not on constructing a future enum/token or a private implementation detail.
    assert policy.active, (authorization.authorized, authorization.reason)
    assert authorization.authorized
    assert authorization.reason == "settled_adjacent_transfer"
    assert [(e.zone, e.kind, e.event_at) for e in result.policy_events] == [
        ("closet", "acquired", target_at)
    ]
    assert not authorization.source_tokens and not authorization.new_uses
    assert policy.activation_source_episode_ids == (source_episode.episode_id,)
    assert policy.activation_path_node_ids == ("bathroom", "closet")
    moved, = result.snapshot.anonymous_supports
    assert moved.support_id == support.support_id
    assert moved.created_at == support.created_at
    assert moved.updated_at == target_at
    assert moved.current_episode_id == target.episode_id
    assert (moved.current_node_id, moved.current_zone, moved.state) == (
        "closet", "closet", "settled"
    )
    assert moved.provenance_kind == "settled_adjacent_transfer"
    assert moved.path_node_ids == ("bathroom", "closet") and moved.valid_until is None
    assert engine.diagnostic_counters["support_created"] == created_before
    assert engine.diagnostic_counters["support_transferred"] == transferred_before + 1
    token, = result.snapshot.traversal_tokens
    assert token.token_id == f"closet:{target.episode_id}"
    assert token.accepted_at == target_at
    assert token.valid_until == target.traversal_valid_until
    assert token.valid_until == target_at + timedelta(seconds=180)
    assert token.track_confidence == "provisional"
    assert token.equivalent_confirmed_strength
    assert token.path_node_ids == ("bathroom", "closet")
    assert token.provenance_kind == "settled_adjacent_transfer"
    assert result.snapshot.support_token_bindings == (
        zone_types.SupportTokenBinding(token.token_id, support.support_id),
    )
    assert (
        result.snapshot.retained_traversal_tokens
        == elapsed.snapshot.retained_traversal_tokens
    )
    assert result.snapshot.authorization_uses == elapsed.snapshot.authorization_uses
    assert next(
        s for s in result.snapshot.belief_states if s.zone == "bathroom"
    ) == source_belief
    assert next(
        s for s in result.snapshot.episode_states if s.node_id == "bathroom"
    ) == source_episode
    assert not result.snapshot.pending_candidates
    assert not engine._pending_prediction_learning
    assert engine.prediction_manager.serialize() == prediction_before
    engine.commit_prediction_learning()
    assert engine.prediction_manager.serialize() == prediction_before
    recovered = _strict_round_trip(predictive_map, engine)
    for current in (engine, recovered):
        repeated = current.observe(
            SensorInput("binary_sensor.closet", "on", target_at)
        )
        assert not repeated.policy_events and not repeated.authorizations
        assert repeated.snapshot == result.snapshot


def _run_exact_120_probe(
    predictive_map: PredictiveMap,
    authoritative_count: int,
) -> tuple[zone_types.ZoneModelResult, zone_types.ZoneModelResult]:
    """Independent exact replay: never calls or retimes the frozen primary."""
    engine = _engine_with_settled_bathroom_support(predictive_map, authoritative_count)
    engine.commit_prediction_learning()
    closet_at = _at("2026-09-08T12:13:34.142281Z")
    bathroom_at = _at("2026-09-08T12:14:24.044050Z")
    target_at = _at("2026-09-08T12:16:24.972720Z")
    first = engine.observe(SensorInput("binary_sensor.closet", "on", closet_at))
    bathroom = engine.observe(SensorInput("binary_sensor.bathroom", "on", bathroom_at))
    assert first.authorizations[0].reason == "track_bootstrap_pending"
    assert not first.authorizations[0].authorized
    assert bathroom.authorizations[0].reason == "settled_endpoint_reacquired"
    source_token = next(
        t for t in bathroom.snapshot.traversal_tokens if t.node_id == "bathroom"
    )
    assert source_token.valid_until == bathroom_at + timedelta(seconds=120)
    assert target_at - bathroom_at == timedelta(seconds=120, microseconds=928670)
    engine.observe(SensorInput(
        "binary_sensor.closet", "off", _at("2026-09-08T12:14:52.365745Z")
    ))
    engine.advance(target_at - timedelta(microseconds=1))
    _assert_eligible_source(
        predictive_map, engine.snapshot, target_at, target_at - bathroom_at
    )
    restored = _strict_round_trip(predictive_map, engine)
    target = engine.observe(SensorInput("binary_sensor.closet", "on", target_at))
    restored_target = restored.observe(
        SensorInput("binary_sensor.closet", "on", target_at)
    )
    assert restored_target == target
    for entity_id, event_at in (
        ("binary_sensor.entrance", _at("2026-09-08T12:16:30.116610Z")),
        ("binary_sensor.top", _at("2026-09-08T12:16:31.748532Z")),
    ):
        result = engine.observe(SensorInput(entity_id, "on", event_at))
        assert restored.observe(SensorInput(entity_id, "on", event_at)) == result
    sleep_off = engine.advance(_at("2026-09-08T12:16:56.291116Z"))
    assert restored.advance(_at("2026-09-08T12:16:56.291116Z")) == sleep_off
    return target, sleep_off


@pytest.mark.target_model
@pytest.mark.parametrize("authoritative_count", (1, 2))
def test_long_stay_original_120_calibration_exact_incident_probe(
    authoritative_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Verified by repository-wide SHARED_PROFILES/STAY_PRESENCE source search.
    modules = tuple(
        import_module(f"custom_components.predictive_controls.zone_model.{name}")
        for name in (
            "profiles", "episodes", "traversal", "engine", "supports", "count",
            "persistence",
        )
    )
    originals = tuple(module.SHARED_PROFILES for module in modules)
    registry = originals[0]
    assert all(original is registry for original in originals)
    assert registry["stay_presence"].traversal_context_window == timedelta(seconds=180)
    replacement = MappingProxyType({
        **registry,
        "stay_presence": replace(
            registry["stay_presence"], traversal_context_window=timedelta(seconds=120)
        ),
    })
    assert replacement["stay_presence"].track_bootstrap_window == timedelta(seconds=120)
    assert replacement["stay_presence"].assertion_trust_horizon == timedelta(
        seconds=1800
    )
    assert replace(
        replacement["stay_presence"], traversal_context_window=timedelta(seconds=180)
    ) == registry["stay_presence"]
    predictive_map = _incident_map()
    ordinary_fingerprint = target_map_fingerprint(predictive_map)
    try:
        with monkeypatch.context() as scoped:
            for module in modules:
                scoped.setattr(module, "SHARED_PROFILES", replacement)
            assert all(module.SHARED_PROFILES is replacement for module in modules)
            assert target_map_fingerprint(predictive_map) != ordinary_fingerprint
            target, sleep_off = _run_exact_120_probe(
                predictive_map, authoritative_count
            )
            authorization, = target.authorizations
            policy = next(
                s for s in target.snapshot.policy_states if s.zone == "closet"
            )
            assert policy.active, (authorization.authorized, authorization.reason)
            assert authorization.authorized
            assert authorization.reason == "settled_adjacent_transfer"
            assert [(e.zone, e.kind, e.event_at) for e in target.policy_events] == [
                ("closet", "acquired", _at("2026-09-08T12:16:24.972720Z"))
            ]
            assert next(
                s for s in sleep_off.snapshot.policy_states if s.zone == "closet"
            ).active
            assert all(
                "interaction" not in s.node_id
                for s in sleep_off.snapshot.episode_states
            )
    finally:
        # Executes even on the intended pre-fix public failure. No fixture may
        # leak 120-second calibration into the immutable 180-second primary.
        assert all(
            module.SHARED_PROFILES is original
            for module, original in zip(modules, originals, strict=True)
        )
        assert registry["stay_presence"].traversal_context_window == timedelta(
            seconds=180
        )
        assert target_map_fingerprint(predictive_map) == ordinary_fingerprint
