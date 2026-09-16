"""Synthetic physical/record contracts, not incidents or lighting scenarios.

EVID001/002/003/006/011/012, HEALTH001..004 and PATH-STATE001: malformed
records/batches must fail at their owning guard without partial installation;
timers cannot manufacture physical evidence. PATH003/005 and PRED008 bind
authorization/displacement records to canonical observed occurrences.

Pre-edit mapping: docs/spec/completion-physical-records.md. Legacy gap/handoff
builders are read-only standalone component fixtures, not selected-engine state.
No production guard, shared calibration, original test or harness is patched.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.episodes import PhysicalEpisodes
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.path_health import (
    PathHealth,
    PathHealthState,
)
from custom_components.predictive_controls.zone_model.profiles import (
    BELIEF_PROFILES,
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.selected_paths import (
    SelectedPaths,
)
from custom_components.predictive_controls.zone_model.types import (
    AuthorizationUse,
    PhysicalNode,
    ReliabilityWarningOccurrence,
    SelectedPredictionGrant,
    SensorInput,
    TraversalAuthorization,
    ZoneBeliefState,
)
from tests.gap_lifecycle_fixture import before_component_gap, prepare_gap_target
from tests.handoff_component_fixture import handoff_proposal
from tests.persistence_component_fixture import PersistenceComponents
from tests.test_zone_model_supported_gap_acquisition import gap_map

pytestmark = pytest.mark.target_model
ORIGIN = datetime(2026, 9, 14, tzinfo=UTC)
EMPTY: frozenset[str] = frozenset()
NODES = (
    PhysicalNode("a", "a", ("binary_sensor.a", "binary_sensor.a2"), "stay_presence"),
    PhysicalNode("b", "b", ("binary_sensor.b",), "stay_presence"),
    PhysicalNode(
        "press", "press", ("event.press",), "stay_pir",
        interaction_aliases=("event.press",),
    ),
)


def at(seconds: float) -> datetime:
    return ORIGIN + timedelta(seconds=seconds)


def _reconstruct_invalid[T: (
    PathHealthState, ZoneBeliefState, TraversalAuthorization, SelectedPredictionGrant,
)](record: T, changes: dict[str, object]) -> T:
    """Send wrong-type init fields through the actual validating constructor.

    These records have only init fields. Preserve nested objects rather than
    using asdict, and never bypass __post_init__ with frozen-object mutation.
    Normal and type-correct malformed values use explicit replace fields instead.
    """
    values: dict[str, object] = {
        field.name: getattr(record, field.name) for field in fields(record)
    }
    values.update(changes)
    construct: Callable[..., T] = type(record)
    return construct(**values)


def sensor(alias: str, state: str, seconds: float) -> SensorInput:
    return SensorInput(alias, state, at(seconds))


def assert_error(operation: Callable[[], object], message: str) -> None:
    """Do not accept a subclass, incidental setup failure, or broad regex match."""
    with pytest.raises(ValueError) as caught:
        operation()
    assert type(caught.value) is ValueError
    assert str(caught.value) == message


@pytest.mark.parametrize("invalid", (None, 0, 1, "false", (), []))
def test_episode_diagnostic_mode_is_boolean_not_truthiness(invalid: object) -> None:
    nodes = (PhysicalNode("a", "a", ("binary_sensor.a",), "transition_fast"),)
    # Deliberately dynamic malformed constructor input; all outputs remain typed.
    construct: Callable[..., PhysicalEpisodes] = PhysicalEpisodes
    assert_error(
        lambda: construct(nodes, diagnostic_warnings=invalid),
        "Episode diagnostic mode must be boolean",
    )
    enabled = PhysicalEpisodes(nodes, diagnostic_warnings=True)
    disabled = PhysicalEpisodes(nodes, diagnostic_warnings=False)
    observed = sensor("binary_sensor.a", "on", 0)
    assert enabled.observe(observed) == disabled.observe(observed)
    warned, = enabled.advance(at(60))
    neutral, = disabled.advance(at(60))
    assert tuple(effect.kind for effect in warned.effects) == ("health_degraded",)
    assert warned.state.degradation_reason == "assertion_timeout"
    assert neutral.effects == () and not neutral.state.health_warning
    assert neutral.state.episode_id == warned.state.episode_id
    assert enabled.advance(at(60))[0].effects == ()
    assert disabled.advance(at(60))[0].effects == ()


def startup_receiver() -> PhysicalEpisodes:
    receiver = PhysicalEpisodes(NODES, diagnostic_warnings=False)
    receiver.observe(sensor("binary_sensor.a", "on", 10))
    receiver.observe(sensor("binary_sensor.b", "on", 30))
    return receiver


def startup_batch(seconds: float) -> tuple[SensorInput, ...]:
    return (
        sensor("binary_sensor.a", "off", seconds),
        sensor("binary_sensor.a2", "on", seconds),
        sensor("binary_sensor.b", "on", seconds),
        sensor("event.press", "unknown", seconds),
    )


@pytest.mark.parametrize(("mutation", "message"), (
    ("duplicate", "Startup snapshot repeats a physical alias"),
    ("unmapped", "Startup snapshot alias is not mapped"),
    ("frontier", "Startup snapshot must share one frontier"),
    ("press", "Startup levels cannot contain physical presses"),
    ("interaction_on", "Startup interaction levels must be neutral"),
    ("interaction_off", "Startup interaction levels must be neutral"),
    ("backward", "Startup snapshot cannot move backward"),
))
def test_startup_rejects_malformed_batch_atomically(
    mutation: str, message: str,
) -> None:
    receiver, control, accepted = (startup_receiver() for _ in range(3))
    before = receiver.states
    good = startup_batch(40)
    updates = accepted.reconcile_startup_snapshot(good, at(40))
    assert tuple(update.disposition for update in updates) == (
        "startup_continuation", "startup_continuation", "startup_continuation",
    )
    assert all(not update.effects for update in updates)
    assert tuple(state.episode_id for state in accepted.states) == tuple(
        state.episode_id for state in before
    )
    assert accepted.states != before  # The proposed alias swap is not a no-op.

    frontier = at(40)
    bad = good
    if mutation == "duplicate":
        bad = (*good, good[0])
    elif mutation == "unmapped":
        bad = (*good[:-1], replace(good[-1], entity_id="event.not_mapped"))
    elif mutation == "frontier":
        bad = (*good[:-1], replace(good[-1], event_at=at(41)))
    elif mutation == "press":
        bad = (*good[:-1], replace(good[-1], state="pressed"))
    elif mutation in {"interaction_on", "interaction_off"}:
        level = mutation.removeprefix("interaction_")
        bad = (*good[:-1], replace(good[-1], state=level))
    else:
        assert mutation == "backward"
        frontier, bad = at(20), startup_batch(20)
        # A can be processed first, but B's later observation must reject all of it.
        assert before[0].advanced_at == at(10) < frontier < at(30)
        assert before[1].advanced_at == at(30)
    incoming = deepcopy(bad)
    assert_error(lambda: receiver.reconcile_startup_snapshot(bad, frontier), message)
    assert receiver.states == before == control.states
    assert bad == incoming

    assert receiver.reconcile_startup_snapshot(good, at(40)) == (
        control.reconcile_startup_snapshot(good, at(40))
    )
    press = sensor("event.press", "pressed", 41)
    result = receiver.observe(press)
    assert result == control.observe(press)
    assert result.disposition == "accepted_interaction"
    assert tuple(effect.kind for effect in result.effects) == ("interaction",)
    assert receiver.observe(sensor("binary_sensor.b", "off", 50)) == (
        control.observe(sensor("binary_sensor.b", "off", 50))
    )
    assert receiver.advance(at(60)) == control.advance(at(60))
    assert receiver.states == control.states


@pytest.mark.parametrize("diagnostic_warnings", (False, True))
def test_quiet_expiry_cancels_queued_cadence_warning(
    diagnostic_warnings: bool,
) -> None:
    nodes = (PhysicalNode("a", "a", ("binary_sensor.a",), "stay_presence"),)
    sparse = PhysicalEpisodes(nodes, diagnostic_warnings=diagnostic_warnings)
    for seconds, level in ((0, "on"), (20, "off"), (31, "on"), (40, "off")):
        sparse.observe(sensor("binary_sensor.a", level, seconds))
    original, = sparse.states
    assert original.generation == 2 and original.cadence_cycle_count == 1
    assert original.cadence_run_started_at == at(0)
    assert original.cadence_last_transition_at == at(40)
    assert original.clear_deadline == at(50)
    fine = PhysicalEpisodes(nodes, diagnostic_warnings=diagnostic_warnings)
    restored = PhysicalEpisodes(nodes, diagnostic_warnings=diagnostic_warnings)
    fine.restore_snapshot(sparse.states)
    restored.restore_snapshot(sparse.states)
    assert fine.states == restored.states == sparse.states

    sparse_effects = sparse.advance(at(10800))[0].effects
    fine_effects = tuple(
        effect
        for seconds in (50, 639.999999, 640, 10800)
        for update in fine.advance(at(seconds))
        for effect in update.effects
    )
    assert sparse_effects == fine_effects == restored.advance(at(10800))[0].effects
    assert tuple((effect.kind, effect.at) for effect in sparse_effects) == (
        ("stable_clear", at(50)),
    )
    assert sparse.states == fine.states == restored.states
    final, = sparse.states
    assert final.status == "clear" and final.clear_emitted
    assert final.cadence_run_started_at is final.cadence_last_transition_at is None
    assert final.cadence_cycle_count == 0 and not final.cadence_warning
    assert final.cadence_warning_reason is None
    assert sparse.advance(at(10800))[0].effects == ()


def health_snapshot(health: PathHealth) -> tuple[
    tuple[PathHealthState, ...],
    tuple[tuple[tuple[str, str], ReliabilityWarningOccurrence], ...],
    datetime | None,
]:
    """Read all mutable health state without progressing time to inspect it."""
    return health.states, tuple(sorted(health._occurrences.items())), health._at


def health_receiver() -> tuple[PhysicalEpisodes, PathHealth]:
    episodes = PhysicalEpisodes(NODES, diagnostic_warnings=False)
    episodes.reconcile_startup_snapshot(
        (sensor("binary_sensor.a2", "off", 0),), at(0),
    )
    health = PathHealth(NODES)
    episodes.observe(sensor("binary_sensor.a", "on", 0))
    health.observe(episodes.states, at(0), EMPTY)
    return episodes, health


@pytest.mark.parametrize("mutation", ("list", "foreign_record"))
def test_health_requires_physical_node_collection(mutation: str) -> None:
    accepted = PathHealth(NODES)
    assert tuple(state.node_id for state in accepted.states) == ("a", "b", "press")
    invalid: object = list(NODES) if mutation == "list" else accepted.states
    incoming = deepcopy(invalid)
    construct: Callable[..., PathHealth] = PathHealth
    assert_error(lambda: construct(invalid), "Path health requires physical nodes")
    assert invalid == incoming
    assert accepted.advance(at(0), EMPTY) == ()
    assert all(state.phase == "unknown" for state in accepted.states)


@pytest.mark.parametrize("mutation", ("list", "foreign_record"))
def test_health_rejects_non_episode_observations_atomically(mutation: str) -> None:
    episodes, health = health_receiver()
    control_episodes, control = health_receiver()
    ledger = health.advance(at(600), EMPTY)
    assert ledger == control.advance(at(600), EMPTY)
    assert len(ledger) == 1 and ledger[0].first_observed_at == at(600)
    accepted = PathHealth(NODES)
    accepted.restore(health.states, ledger, at(600))
    assert health_snapshot(accepted) == health_snapshot(health)
    accepted.observe(episodes.states, at(610), EMPTY)
    assert accepted._occurrences[("a", "assertion_timeout")].last_observed_at == at(610)
    # A tuple of health records is not a tuple of physical episode observations.
    invalid: object = list(episodes.states) if mutation == "list" else health.states
    incoming = deepcopy(invalid)
    before = health_snapshot(health)
    observe: Callable[..., None] = health.observe
    assert_error(
        lambda: observe(invalid, at(610), EMPTY),
        "Path health observations require episode states",
    )
    assert health_snapshot(health) == before == health_snapshot(control)
    assert invalid == incoming
    assert episodes.states == control_episodes.states
    for seconds, level in ((611, "off"), (620, "on")):
        for physical, diagnostic in ((episodes, health), (control_episodes, control)):
            physical.observe(sensor("binary_sensor.a", level, seconds))
            diagnostic.observe(physical.states, at(seconds), EMPTY)
        assert health_snapshot(health) == health_snapshot(control)
    assert health.advance(at(1220), EMPTY) == control.advance(at(1220), EMPTY)
    assert health._occurrences[("a", "assertion_timeout")].first_observed_at == at(1220)


@pytest.mark.parametrize("intervening", ("timer", "duplicate", "off", "future"))
def test_jump_requires_exact_observed_on_frontier(intervening: str) -> None:
    episodes, health = health_receiver()
    control_episodes, control = health_receiver()
    for physical, diagnostic in ((episodes, health), (control_episodes, control)):
        diagnostic.record_unsupported_jump("a", at(0), EMPTY)
        occurrence = diagnostic._occurrences[("a", "unsupported_jump")]
        assert occurrence.first_observed_at == occurrence.last_observed_at == at(0)
        if intervening == "timer":
            diagnostic.advance(at(1), EMPTY)
        elif intervening == "duplicate":
            physical.observe(sensor("binary_sensor.a", "on", 1))
            diagnostic.observe(physical.states, at(1), EMPTY)
        elif intervening == "off":
            physical.observe(sensor("binary_sensor.a", "off", 1))
            diagnostic.observe(physical.states, at(1), EMPTY)
        else:
            assert intervening == "future"
    before = health_snapshot(health)
    assert_error(
        lambda: health.record_unsupported_jump("a", at(1), EMPTY),
        "Unsupported jump requires the observed ON frontier",
    )
    assert health_snapshot(health) == before == health_snapshot(control)
    for physical, diagnostic in ((episodes, health), (control_episodes, control)):
        physical.observe(sensor("binary_sensor.a", "off", 2))
        diagnostic.observe(physical.states, at(2), EMPTY)
        physical.observe(sensor("binary_sensor.a", "on", 3))
        diagnostic.observe(physical.states, at(3), EMPTY)
        diagnostic.record_unsupported_jump("a", at(3), EMPTY)
    assert health_snapshot(health) == health_snapshot(control)
    occurrence = health._occurrences[("a", "unsupported_jump")]
    assert occurrence == ReliabilityWarningOccurrence(
        "a", "a", "unsupported_jump", "unsupported_jump", at(3), at(3),
    )


def test_covered_fresh_on_does_not_record_jump() -> None:
    episodes = PhysicalEpisodes(NODES, diagnostic_warnings=False)
    episodes.observe(sensor("binary_sensor.a", "on", 0))
    covered, uncovered = PathHealth(NODES), PathHealth(NODES)
    coverage = frozenset({"a"})
    covered.observe(episodes.states, at(0), coverage)
    uncovered.observe(episodes.states, at(0), EMPTY)
    before = health_snapshot(covered)
    covered.record_unsupported_jump("a", at(0), coverage)
    uncovered.record_unsupported_jump("a", at(0), EMPTY)
    assert health_snapshot(covered) == before
    assert covered.states[0].unsupported_started_at is None
    jump, = uncovered.advance(at(100), EMPTY)
    assert jump.first_observed_at == jump.last_observed_at == at(0)
    assert covered.advance(at(100), EMPTY) == ()
    assert covered.states[0].unsupported_started_at == at(100)
    assert covered.advance(at(699.999999), EMPTY) == ()
    timeout, = covered.advance(at(700), EMPTY)
    assert timeout.reason == "assertion_timeout"
    assert timeout.first_observed_at == timeout.last_observed_at == at(700)
    assert ("a", "unsupported_jump") not in covered._occurrences
    assert episodes.states[0].generation == 1


@pytest.mark.parametrize(("mutation", "message"), (
    ("eleventh", "Path health must retain at most ten cycle timestamps"),
    ("list", "Path health must retain at most ten cycle timestamps"),
    ("reversed", "Path health completions must be ordered"),
    ("after_on", "Completed cycle cannot follow the current ON start"),
))
def test_health_record_bound_preserves_real_completions(
    mutation: str, message: str,
) -> None:
    episodes = PhysicalEpisodes(NODES, diagnostic_warnings=False)
    # The unused alias has a real startup OFF; every later OFF is aggregate OFF.
    episodes.reconcile_startup_snapshot((sensor("binary_sensor.a2", "off", 0),), at(0))
    health = PathHealth(NODES)
    covered = frozenset({"a"})
    for start in range(0, 220, 20):
        for seconds, level in ((start, "on"), (start + 10, "off")):
            episodes.observe(sensor("binary_sensor.a", level, seconds))
            health.observe(episodes.states, at(seconds), covered)
    episodes.observe(sensor("binary_sensor.a", "on", 220))
    health.observe(episodes.states, at(220), covered)
    state = health.states[0]
    assert state.completed_cycles == tuple(at(s) for s in range(30, 220, 20))
    assert len(state.completed_cycles) == 10 and state.on_started_at == at(220)
    assert replace(state) == state
    ledger = tuple(item for _, item in health_snapshot(health)[1])
    control = PathHealth(NODES)
    control.restore(health.states, ledger, at(220))
    assert health_snapshot(control) == health_snapshot(health)
    invalid: object
    if mutation == "eleventh":
        invalid = (at(10), *state.completed_cycles)
    elif mutation == "list":
        invalid = list(state.completed_cycles)
    elif mutation == "reversed":
        invalid = tuple(reversed(state.completed_cycles))
    else:
        assert mutation == "after_on"
        invalid = (*state.completed_cycles[:-1], at(220.000001))
    incoming, before = deepcopy(invalid), health_snapshot(health)
    if isinstance(invalid, tuple):
        assert_error(lambda: replace(state, completed_cycles=invalid), message)
    else:
        assert_error(
            lambda: _reconstruct_invalid(state, {"completed_cycles": invalid}), message,
        )
    assert incoming == invalid and health_snapshot(health) == before
    for expiry_seconds, count in ((1229.999999, 10), (1230, 9)):
        assert health.advance(at(expiry_seconds), covered) == (
            control.advance(at(expiry_seconds), covered)
        )
        assert len(health.states[0].completed_cycles) == count
    warning = health._occurrences[("a", "sustained_flapping")]
    assert warning.first_observed_at == at(190) and warning.cleared_at == at(1230)
    assert warning.cleared_at - state.completed_cycles[0] == timedelta(seconds=1200)
    for seconds, level in ((1231, "off"), (1240, "on"), (1250, "off")):
        episodes.observe(sensor("binary_sensor.a", level, seconds))
        for diagnostic in (health, control):
            diagnostic.observe(episodes.states, at(seconds), covered)
        assert health_snapshot(health) == health_snapshot(control)
    assert health.states[0].completed_cycles[-1] == at(1250)


def displaced_filter() -> ZoneBeliefFilter:
    physical = PhysicalEpisodes(NODES, diagnostic_warnings=False)
    observed = physical.observe(sensor("binary_sensor.a", "on", 10))
    positive, = observed.effects
    belief = ZoneBeliefFilter("a", BELIEF_PROFILES["stay_presence"], at(0))
    belief.apply_positive(positive.episode_id, positive.at, positive.reliability)
    belief.displace_path(at(20))
    belief.advance(at(30))
    assert belief.state.path_displaced_at == at(20)
    assert belief.state.generation_episode_id == observed.state.episode_id
    return belief


@pytest.mark.parametrize(("reference", "message"), (
    (1, "Physical episode reference must be a string"),
    (f"a:0:{at(10).isoformat()}", "Physical episode reference is malformed"),
    ("a:1:2026-09-14T00:00:10Z", "Physical episode reference must be canonical"),
))
def test_displacement_requires_canonical_physical_reference(
    reference: object, message: str,
) -> None:
    belief = displaced_filter()
    before = belief.state
    control = ZoneBeliefFilter.restore(BELIEF_PROFILES["stay_presence"], before)
    assert control.state == replace(before) == before
    if isinstance(reference, str):
        assert_error(lambda: replace(before, generation_episode_id=reference), message)
    else:
        assert_error(
            lambda: _reconstruct_invalid(before, {"generation_episode_id": reference}),
            message,
        )
    assert belief.state == before
    assert belief.advance(at(40)) == control.advance(at(40))


@pytest.mark.parametrize(("change", "message"), (
    ({"physical_hold": 0}, "Physical hold must be boolean"),
    ({"physical_hold": 1}, "Physical hold must be boolean"),
    ({"physical_hold": "false"}, "Physical hold must be boolean"),
    (
        {"path_displaced_at": at(20).isoformat()},
        "Path displacement time must be a UTC datetime",
    ),
    ({"generation_episode_id": None}, "Path displacement requires a belief generation"),
    (
        {"path_displaced_at": at(9.999999)},
        "Path displacement is outside its generation",
    ),
    (
        {"path_displaced_at": at(30.000001)},
        "Path displacement is outside its generation",
    ),
))
def test_belief_record_rejects_invalid_physical_fields(
    change: dict[str, object], message: str,
) -> None:
    belief = displaced_filter()
    before = belief.state
    control = ZoneBeliefFilter.restore(BELIEF_PROFILES["stay_presence"], before)
    assert control.state == before
    incoming = deepcopy(change)
    displaced_at = change.get("path_displaced_at")
    if "generation_episode_id" in change:
        assert_error(lambda: replace(before, generation_episode_id=None), message)
    elif isinstance(displaced_at, datetime):
        assert_error(lambda: replace(before, path_displaced_at=displaced_at), message)
    else:
        assert_error(lambda: _reconstruct_invalid(before, change), message)
    assert change == incoming and belief.state == before
    # Both ends are inclusive; presence is a Boolean, not an integer permission.
    for frontier in (at(10), at(30)):
        for held in (False, True):
            boundary = replace(before, path_displaced_at=frontier, physical_hold=held)
            assert boundary.path_displaced_at == frontier
            assert boundary.physical_hold is held
            assert ZoneBeliefFilter.restore(
                BELIEF_PROFILES["stay_presence"], boundary,
            ).state == boundary
    assert belief.advance(at(40)) == control.advance(at(40))


def selected_records() -> tuple[
    PhysicalEpisodes, SelectedPaths, TraversalAuthorization,
]:
    mapping = PredictiveMap.from_mapping({"nodes": {
        name: {
            "role": "anchor_sensor", "occupancy_behavior": "sticky",
            "entities": {"mmwave": f"binary_sensor.{name}"}, "adjacent": neighbors,
        }
        for name, neighbors in (
            ("a", ["b"]), ("b", ["a", "c"]), ("c", ["b", "d"]), ("d", ["c"]),
        )
    }})
    nodes = build_physical_nodes(mapping)
    assert not nodes.errors
    episodes = PhysicalEpisodes(nodes.nodes, diagnostic_warnings=False)
    selected = SelectedPaths(mapping, nodes.nodes, 1)
    authorization: TraversalAuthorization | None = None
    for seconds, node in enumerate(("a", "b", "c")):
        update = episodes.observe(sensor(f"binary_sensor.{node}", "on", seconds))
        effect, = update.effects
        assert effect.kind == "positive"
        authorization = selected.observe(effect, update.state, episodes.states)
    assert authorization is not None and authorization.authorized
    assert authorization.reason == authorization.provenance_kind == "selected_path"
    assert authorization.track_confidence == "confirmed"
    assert authorization.path_node_ids == ("a", "b", "c")
    assert replace(authorization) == authorization
    return episodes, selected, authorization


def continue_selected(
    episodes: PhysicalEpisodes, selected: SelectedPaths,
) -> TraversalAuthorization:
    update = episodes.observe(sensor("binary_sensor.d", "on", 3))
    effect, = update.effects
    authorization = selected.observe(effect, update.state, episodes.states)
    assert authorization is not None and authorization.authorized
    assert authorization.path_node_ids == ("b", "c", "d")
    assert authorization.target_node_id == "d"
    return authorization


@pytest.mark.parametrize("invalid", ([], ("",), (1,), (None,)))
def test_authorization_witness_container_and_owner_are_strict(invalid: object) -> None:
    episodes, selected, authorization = selected_records()
    control_episodes, control, _ = selected_records()
    before = (episodes.states, selected.paths, selected.sources)
    assert_error(
        lambda: _reconstruct_invalid(
            authorization, {"selected_source_episode_ids": invalid},
        ),
        "Selected source episode IDs must be a tuple of identities",
    )
    assert (episodes.states, selected.paths, selected.sources) == before
    assert continue_selected(episodes, selected) == (
        continue_selected(control_episodes, control)
    )
    assert selected.paths == control.paths and selected.sources == control.sources

    tracker, _, handoff, _, _, _, _ = handoff_proposal()
    source = handoff.settled_handoff
    assert source is not None and replace(handoff) == handoff
    saved = (tracker.supports, tracker.bindings, dict(tracker.counters))
    assert_error(
        lambda: replace(
            handoff, selected_source_episode_ids=(source.source_episode_id,),
        ),
        "Selected source witnesses require selected-path authority",
    )
    assert (tracker.supports, tracker.bindings, tracker.counters) == saved
    assert replace(handoff, selected_source_episode_ids=()) == handoff


def component_capture(components: PersistenceComponents) -> dict[str, object]:
    return deepcopy({
        "snapshot": components.snapshot,
        "prediction": components.prediction_manager.serialize(),
        "learning": tuple(components.learning),
        "audit": components.audit_rows,
        "counters": components.diagnostic_counters,
    })


@pytest.mark.parametrize("mutation", (
    "source_role", "source_provenance", "source_accepted", "source_expired",
    "source_reopened", "use_token", "use_target", "use_reason", "use_time",
))
def test_gap_record_rejects_mismatched_source_and_use(mutation: str) -> None:
    mapping = gap_map()
    components = before_component_gap(mapping, ORIGIN)
    control = before_component_gap(mapping, ORIGIN)
    event = sensor("binary_sensor.target", "on", 212)
    _, _, _, authorization = prepare_gap_target(components, event)
    _, _, _, original_control = prepare_gap_target(control, event)
    assert authorization == original_control and replace(authorization) == authorization
    assert authorization.reason == "supported_gap_acquisition"
    source, = authorization.source_tokens
    use = AuthorizationUse(
        source.token_id, authorization.target_episode_id,
        authorization.reason, authorization.authorized_at,
    )
    assert replace(authorization, new_uses=(use,)).new_uses == (use,)
    assert replace(authorization, new_uses=()).new_uses == ()
    before = component_capture(components)
    assert component_capture(control) == before
    # Reconstruct the inner record OUTSIDE raises: only the cross-record guard
    # may reject these otherwise well-formed tokens/uses.
    malformed_source = replace(
        source,
        role="stay" if mutation == "source_role" else source.role,
        provenance_kind=(
            "adjacent" if mutation == "source_provenance" else source.provenance_kind
        ),
        accepted_at=at(212) if mutation == "source_accepted" else source.accepted_at,
        valid_until=at(212) if mutation == "source_expired" else source.valid_until,
        continuity_reopened_at=(
            at(201) if mutation == "source_reopened" else source.continuity_reopened_at
        ),
    )
    malformed_use = replace(
        use,
        token_id=f"{use.token_id}:other" if mutation == "use_token" else use.token_id,
        target_episode_id=(
            source.episode_id if mutation == "use_target" else use.target_episode_id
        ),
        reason="adjacent_authorized" if mutation == "use_reason" else use.reason,
        authorized_at=at(212.000001) if mutation == "use_time" else use.authorized_at,
    )
    assert_error(
        lambda: replace(
            authorization, source_tokens=(malformed_source,), new_uses=(malformed_use,),
        ),
        "Supported-gap source/use is invalid",
    )
    assert component_capture(components) == before
    assert replace(authorization) == original_control
    for model in (components, control):
        model.advance(at(213))
        model.observe(sensor("binary_sensor.target", "off", 214))
        model.advance(at(224))
    assert component_capture(components) == component_capture(control)
    target = next(
        state for state in components.episodes.states if state.node_id == "target"
    )
    assert target.status == "clear" and target.clear_emitted


@pytest.mark.parametrize("change", (
    {"authorized": False}, {"provenance_kind": "adjacent"},
    {"source_tokens": []}, {"new_uses": []}, {"path_node_ids": ("a", "b")},
    {"path_node_ids": ["a", "b", "c"]}, {"equivalent_confirmed_strength": True},
))
def test_selected_authorization_rejects_shape_corruption(
    change: dict[str, object],
) -> None:
    episodes, selected, authorization = selected_records()
    control_episodes, control, _ = selected_records()
    before = (episodes.states, selected.paths, selected.sources)
    incoming = deepcopy(change)

    def operation() -> TraversalAuthorization:
        if "authorized" in change:
            return replace(authorization, authorized=False)
        if "provenance_kind" in change:
            return replace(authorization, provenance_kind="adjacent")
        if "equivalent_confirmed_strength" in change:
            return replace(authorization, equivalent_confirmed_strength=True)
        if change.get("path_node_ids") == ("a", "b"):
            return replace(authorization, path_node_ids=("a", "b"))
        return _reconstruct_invalid(authorization, change)

    assert_error(
        operation,
        "Selected-path authorization shape is invalid",
    )
    source, = authorization.selected_source_episode_ids
    assert_error(
        lambda: replace(authorization, selected_source_episode_ids=(source, source)),
        "Selected-path authorization shape is invalid",
    )
    assert incoming == change
    assert (episodes.states, selected.paths, selected.sources) == before
    assert continue_selected(episodes, selected) == (
        continue_selected(control_episodes, control)
    )
    assert (episodes.states, selected.paths, selected.sources) == (
        control_episodes.states, control.paths, control.sources,
    )


@pytest.mark.parametrize("mutation", ("wrong_node", "future", "same_generation"))
def test_selected_source_must_match_route_and_generation(mutation: str) -> None:
    episodes, selected, authorization = selected_records()
    control_episodes, control, _ = selected_records()
    before = (episodes.states, selected.paths, selected.sources)
    # Independent physical record controls, not self-corroborating engine paths.
    physical = PhysicalEpisodes((
        PhysicalNode("b", "b", ("binary_sensor.b",), "stay_presence"),
        PhysicalNode("c", "c", ("binary_sensor.c",), "stay_presence"),
    ))
    equal_source = physical.observe(sensor("binary_sensor.b", "on", 2)).state
    first_target = physical.observe(sensor("binary_sensor.c", "on", 2)).state
    assert equal_source.episode_id is not None and first_target.episode_id is not None
    equal_time = replace(
        authorization, selected_source_episode_ids=(equal_source.episode_id,),
    )
    assert equal_time.authorized_at == equal_source.started_at
    physical.observe(sensor("binary_sensor.c", "off", 12))
    later_target = physical.observe(sensor("binary_sensor.c", "on", 23)).state
    assert later_target.episode_id is not None and later_target.generation == 2
    older_generation = replace(
        authorization, path_node_ids=("c", "c"),
        target_episode_id=later_target.episode_id, authorized_at=at(23),
        selected_source_episode_ids=(first_target.episode_id,),
    )
    assert older_generation.selected_source_episode_ids == (first_target.episode_id,)

    path_node_ids = authorization.path_node_ids
    if mutation == "wrong_node":
        wrong = next(state for state in episodes.states if state.node_id == "a")
        assert wrong.episode_id is not None
        source_episode_ids = (wrong.episode_id,)
    elif mutation == "future":
        future_physical = PhysicalEpisodes((
            PhysicalNode("b", "b", ("binary_sensor.b",), "stay_presence"),
        ))
        future = future_physical.observe(sensor("binary_sensor.b", "on", 3)).state
        assert future.episode_id is not None
        source_episode_ids = (future.episode_id,)
    else:
        assert mutation == "same_generation"
        path_node_ids = ("c", "c")
        source_episode_ids = (authorization.target_episode_id,)
    assert_error(
        lambda: replace(
            authorization, path_node_ids=path_node_ids,
            selected_source_episode_ids=source_episode_ids,
        ),
        "Selected-path source witness is inconsistent",
    )
    assert (episodes.states, selected.paths, selected.sources) == before
    assert continue_selected(episodes, selected) == (
        continue_selected(control_episodes, control)
    )
    assert selected.paths == control.paths and selected.sources == control.sources


@pytest.mark.parametrize("invalid", (None, "selected_path", {"authorized": True}))
def test_prediction_grant_requires_authorization_record(invalid: object) -> None:
    episodes, selected, authorization = selected_records()
    control_episodes, control, _ = selected_records()
    grant = SelectedPredictionGrant(authorization, "positive", "d", at(12))
    assert replace(grant) == grant
    assert grant.key == ("b", "c", "d", authorization.target_episode_id)
    before = (episodes.states, selected.paths, selected.sources)
    incoming = deepcopy(invalid)
    assert_error(
        lambda: _reconstruct_invalid(grant, {"authorization": invalid}),
        "Selected prediction requires an authorization",
    )
    assert invalid == incoming and grant.authorization == authorization
    assert (episodes.states, selected.paths, selected.sources) == before
    assert continue_selected(episodes, selected) == (
        continue_selected(control_episodes, control)
    )
    assert selected.paths == control.paths and selected.sources == control.sources
