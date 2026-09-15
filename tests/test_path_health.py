"""Synthetic pure diagnostic proofs for REQ-HEALTH-001..003/PATH-STATE-001.

These are not production incident captures. Raw aliases deliberately disagree
with episode generation/status/legacy health flags: diagnostics must neither use
those inference flags nor mutate episodes, paths, filters or public outputs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.zone_model.path_health import (
    PathHealth,
    PathHealthState,
    decode_health,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeState,
    PhysicalNode,
    ReliabilityWarningOccurrence,
)

pytestmark = pytest.mark.target_model
NOW = datetime(2026, 9, 12, tzinfo=UTC)
EMPTY: frozenset[str] = frozenset()
NODES = (
    PhysicalNode(
        "a", "room_a", ("binary_sensor.a", "binary_sensor.a2"), "stay_presence",
    ),
    PhysicalNode("b", "room_b", ("binary_sensor.b",), "transition_fast"),
)


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


class Scene:
    """Feed immutable physical levels, independently of inference generations."""

    def __init__(self) -> None:
        self.health = PathHealth(NODES)
        self.episodes = tuple(EpisodeState(
            node.node_id, node.zone, node.profile_name,
            tuple((alias, "off") for alias in node.aliases),
        ) for node in NODES)
        self.covered = EMPTY

    def send(
        self, seconds: float, values: tuple[str, str], b: str = "off",
        *, bootstrap: bool = False,
    ) -> None:
        self.episodes = tuple(replace(
            state, alias_states=tuple(zip(
                (alias for alias, _ in state.alias_states),
                values if state.node_id == "a" else (b,), strict=True,
            )),
        ) for state in self.episodes)
        original = self.episodes
        self.health.observe(
            self.episodes, at(seconds), self.covered, bootstrap=bootstrap,
        )
        assert self.episodes == original

    def advance(self, seconds: float) -> tuple[ReliabilityWarningOccurrence, ...]:
        return self.health.advance(at(seconds), self.covered)

    def cycle(self, start: float, duration: float = 10, b: str = "off") -> None:
        self.send(start, ("on", "off"), b)
        self.send(start + duration, ("off", "off"), b)

    def restart(self, seconds: float) -> None:
        ledger = self.advance(seconds)
        states = decode_health(wire(self.health))
        new = PathHealth(NODES)
        new.restore(states, ledger, at(seconds))
        assert new.states == self.health.states
        assert new.advance(at(seconds), self.covered) == ledger
        self.health = new


def wire(health: PathHealth) -> list[dict[str, object]]:
    decoded: object = json.loads(json.dumps(
        [asdict(state) for state in health.states],
        default=lambda value: value.isoformat(),
    ))
    assert isinstance(decoded, list)
    records: list[dict[str, object]] = []
    for raw in decoded:
        assert isinstance(raw, dict)
        record: dict[str, object] = {}
        for key, value in raw.items():
            assert isinstance(key, str)
            record[key] = value
        records.append(record)
    return records


def warning(
    node: str, reason: str, first: float, last: float, cleared: float | None = None,
) -> ReliabilityWarningOccurrence:
    return ReliabilityWarningOccurrence(
        node, f"room_{node}",
        "suspected_stuck" if reason == "assertion_timeout" else "flapping",
        reason, at(first), at(last), None if cleared is None else at(cleared),
    )


@pytest.mark.parametrize("seconds", (599, 600, 601))
@pytest.mark.parametrize("path_count", (1, 2))
def test_continuous_unsupported_on_exact_threshold(
    seconds: int, path_count: int,
) -> None:
    scene = Scene()
    # Multiplicity of selected paths is deliberately absent from the health API.
    selected = tuple(frozenset({"b"}) for _ in range(path_count))
    scene.covered = frozenset().union(*selected)
    scene.send(0, ("on", "off"))
    assert scene.advance(seconds) == (() if seconds < 600 else (
        warning("a", "assertion_timeout", 600, seconds),
    ))


def test_supported_on_then_path_loss_starts_at_current_frontier() -> None:
    scene = Scene()
    scene.covered = frozenset({"a"})
    scene.send(0, ("on", "off"))
    assert scene.advance(7200) == ()
    scene.covered = EMPTY
    assert scene.advance(10000) == ()
    assert scene.health.states[0].unsupported_started_at == at(10000)
    assert scene.advance(10599) == ()
    assert scene.advance(10600) == (warning("a", "assertion_timeout", 10600, 10600),)
    scene.covered = frozenset({"a"})
    assert scene.advance(10601) == (
        warning("a", "assertion_timeout", 10600, 10601, 10601),
    )
    scene.covered = EMPTY
    scene.advance(11000)
    assert scene.advance(11600) == (warning("a", "assertion_timeout", 11600, 11600),)


@pytest.mark.parametrize("phase", ("off", "unknown", "unavailable"))
def test_off_or_unknown_interrupts_unsupported_duration(phase: str) -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    scene.send(599, (phase, phase))
    assert scene.advance(1200) == ()
    scene.send(1201, ("on", "off"))
    assert scene.advance(1800) == ()
    assert scene.advance(1801) == (warning("a", "assertion_timeout", 1801, 1801),)
    scene.send(1802, (phase, phase))
    assert scene.advance(2000) == (warning("a", "assertion_timeout", 1801, 1802, 1802),)


def test_same_update_on_support_loss_and_support_gain_adjust_predicates() -> None:
    scene = Scene()
    scene.covered = frozenset({"a"})
    scene.send(0, ("off", "off"))
    scene.covered = EMPTY
    scene.send(10, ("on", "off"))
    assert scene.health.states[0].unsupported_started_at == at(10)
    scene.covered = frozenset({"a"})
    assert scene.advance(10) == ()
    assert scene.health.states[0].unsupported_started_at is None
    scene.covered = EMPTY
    scene.send(20, ("off", "off"))
    assert scene.advance(7200) == ()


@pytest.mark.parametrize("recovery", ("support", "off"))
def test_deadline_before_same_time_recovery_is_retained(recovery: str) -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    if recovery == "support":
        scene.covered = frozenset({"a"})
    else:
        scene.send(600, ("off", "off"))
    assert scene.advance(600) == (warning("a", "assertion_timeout", 600, 600, 600),)


@pytest.mark.parametrize("duration,qualifies", ((0, True), (60, True), (60.001, False)))
def test_five_six_quick_cycles_and_inclusive_duration(
    duration: float, qualifies: bool,
) -> None:
    scene = Scene()
    for index in range(5):
        scene.cycle(index * 100, duration)
        assert scene.advance(index * 100 + duration) == ()
    scene.cycle(500, duration)
    assert scene.advance(500 + duration) == (() if not qualifies else (
        warning("a", "sustained_flapping", 500 + duration, 500 + duration),
    ))


def test_rolling_hour_is_open_left_and_long_cycles_do_not_evict_completions() -> None:
    scene = Scene()
    for start in range(0, 500, 100):
        scene.cycle(start)
    saved = scene.health.states[0].completed_cycles
    scene.cycle(500, 61)
    assert scene.health.states[0].completed_cycles == saved
    scene.cycle(3500)
    assert scene.advance(3609.999) == (
        warning("a", "sustained_flapping", 3510, 3609.999),
    )
    assert scene.advance(3610) == (
        warning("a", "sustained_flapping", 3510, 3610, 3610),
    )
    assert len(scene.health.states[0].completed_cycles) == 5


def test_sixth_completion_at_oldest_expiry_does_not_qualify() -> None:
    scene = Scene()
    for start in range(0, 500, 100):
        scene.cycle(start)
    scene.cycle(3600)
    assert scene.advance(3610) == ()
    assert len(scene.health.states[0].completed_cycles) == 5


def test_sliding_six_preserves_occurrence_start_and_exact_expiry() -> None:
    scene = Scene()
    for start in range(0, 2000, 100):
        scene.cycle(start)
    assert scene.health.states[0].completed_cycles == tuple(
        at(s) for s in range(1410, 2000, 100)
    )
    assert scene.advance(5009) == (warning("a", "sustained_flapping", 510, 5009),)
    assert scene.advance(20000) == (
        warning("a", "sustained_flapping", 510, 5010, 5010),
    )
    assert scene.health.states[0].completed_cycles == ()


def test_any_on_all_off_and_mixed_unknown_aggregate() -> None:
    scene = Scene()
    scene.send(0, ("on", "unknown"))
    scene.send(5, ("on", "on"))
    scene.send(10, ("off", "on"))
    assert scene.health.states[0].on_started_at == at(0)
    scene.send(20, ("off", "off"))
    assert scene.health.states[0].completed_cycles == (at(20),)
    scene.send(30, ("on", "off"))
    scene.send(40, ("off", "unavailable"))
    assert scene.health.states[0].phase == "unknown"
    scene.send(45, ("off", "off"))
    assert scene.health.states[0].completed_cycles == (at(20),)
    scene.send(50, ("unknown", "on"))
    scene.send(55, ("off", "off"))
    final_state = scene.health.states[0]
    assert final_state.completed_cycles == (at(20), at(55))


def test_duplicates_generations_legacy_flags_and_timers_are_not_edges() -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    for index in range(1, 10):
        scene.episodes = tuple(replace(
            state, generation=index, episode_id=f"{state.node_id}:{index}",
            status="degraded", health_warning=True, degradation_reason="count_conflict",
        ) for state in scene.episodes)
        scene.send(index, ("on", "off"))
        assert scene.advance(index) == ()
    assert scene.health.states[0].on_started_at == at(0)
    scene.send(10, ("off", "off"))
    for _ in range(10):
        scene.send(10, ("off", "off"))
        scene.advance(10)
    assert scene.health.states[0].completed_cycles == (at(10),)
    # Repeated real raw transitions count even when no generation changes.
    for start in range(20, 120, 20):
        scene.cycle(start)
    assert scene.advance(110) == (warning("a", "sustained_flapping", 110, 110),)
    assert scene.advance(7200) == (warning("a", "sustained_flapping", 110, 3610, 3610),)


def test_two_counters_are_independent_and_support_clears_only_stuck() -> None:
    scene = Scene()
    for start in range(0, 120, 20):
        scene.cycle(start)
    scene.send(120, ("on", "off"))
    assert scene.advance(720) == (
        warning("a", "assertion_timeout", 720, 720),
        warning("a", "sustained_flapping", 110, 720),
    )
    scene.covered = frozenset({"a"})
    assert scene.advance(730) == (
        warning("a", "assertion_timeout", 720, 730, 730),
        warning("a", "sustained_flapping", 110, 730),
    )
    scene.send(740, ("off", "off"))
    assert scene.advance(740)[1] == warning("a", "sustained_flapping", 110, 740)


@pytest.mark.parametrize("restart", (False, True))
def test_coarse_fine_advance_have_identical_logical_ledgers(restart: bool) -> None:
    scenes = (Scene(), Scene())
    for scene in scenes:
        for start in range(0, 120, 20):
            scene.cycle(start, b="on")
        if restart:
            scene.restart(110)
    for seconds in range(111, 8001):
        scenes[1].advance(seconds)
    assert scenes[0].advance(8000) == scenes[1].advance(8000) == (
        warning("a", "sustained_flapping", 110, 3610, 3610),
        warning("b", "assertion_timeout", 600, 8000),
    )
    assert scenes[0].health.states == scenes[1].health.states


def test_in_session_roundtrip_preserves_unfinished_cycle_and_unsupported_run() -> None:
    scene = Scene()
    scene.send(0, ("on", "off"), "on")
    scene.restart(30)
    scene.send(60, ("off", "off"), "on")
    assert scene.health.states[0].completed_cycles == (at(60),)
    assert scene.advance(600) == (warning("b", "assertion_timeout", 600, 600),)
    scene.restart(600)
    assert scene.advance(601) == (warning("b", "assertion_timeout", 600, 601),)


def test_bootstrap_on_unknown_start_cannot_complete_cycle_but_can_warn() -> None:
    scene = Scene()
    scene.send(10000, ("on", "off"), bootstrap=True)
    state = scene.health.states[0]
    assert state.on_started_at is None
    assert state.unsupported_started_at == at(10000)
    assert scene.advance(10599) == ()
    assert scene.advance(10600) == (warning("a", "assertion_timeout", 10600, 10600),)
    scene.send(10601, ("off", "off"))
    assert scene.health.states[0].completed_cycles == ()


@pytest.mark.parametrize("phase", (("on", "off"), ("off", "off"), ("unknown", "off")))
def test_bootstrap_breaks_restored_gap_without_crediting_outside_time(
    phase: tuple[str, str],
) -> None:
    scene = Scene()
    scene.cycle(0)
    scene.send(20, ("on", "off"))
    scene.restart(30)
    scene.send(10000, phase, bootstrap=True)
    assert scene.advance(10000) == ()
    assert scene.health.states[0].on_started_at is None
    assert scene.health.states[0].completed_cycles == ()
    if phase[0] == "on":
        scene.send(10030, ("off", "off"))
        assert scene.health.states[0].completed_cycles == ()
    scene.cycle(10040)
    final_state = scene.health.states[0]
    assert final_state.completed_cycles == (at(10050),)


def test_warning_occurrences_are_bounded_latest_rows_and_roundtrip() -> None:
    scene = Scene()
    for offset in range(0, 30000, 10000):
        for start in range(offset, offset + 120, 20):
            scene.cycle(start, b="on")
        scene.send(offset + 120, ("on", "off"), "on")
        scene.advance(offset + 720)
        scene.restart(offset + 720)
        assert len(scene.advance(offset + 720)) == 3
        scene.send(offset + 800, ("off", "off"))
        scene.advance(offset + 5000)
    assert scene.advance(30000) == (
        warning("a", "assertion_timeout", 20720, 20800, 20800),
        warning("a", "sustained_flapping", 20110, 23610, 23610),
        warning("b", "assertion_timeout", 20600, 20800, 20800),
    )
    scene.restart(30000)


@pytest.mark.parametrize("value", (
    None, True, False, 0, "2026-09-12", datetime(2026, 9, 12),
    datetime.fromisoformat("2026-09-12T00:00:00+01:00"),
))
def test_invalid_datetime_arguments_are_rejected_without_mutation(value: Any) -> None:
    scene = Scene()
    original = scene.health.states
    for operation in (
        lambda: scene.health.advance(value, EMPTY),
        lambda: scene.health.observe(scene.episodes, value, EMPTY),
        lambda: scene.health.restore(original, (), value),
    ):
        with pytest.raises(ValueError):
            operation()
        assert scene.health.states == original


@pytest.mark.parametrize("change", (
    {"node_id": True}, {"zone": ""}, {"phase": False}, {"phase": "unavailable"},
    {"on_started_at": True}, {"unsupported_started_at": False},
    {"phase": "off", "on_started_at": NOW},
    {"phase": "on", "on_started_at": at(10), "unsupported_started_at": NOW},
    {"completed_cycles": []}, {"completed_cycles": (True,)},
    {"completed_cycles": (at(10), NOW)},
    {"completed_cycles": tuple(at(i) for i in range(7))},
    {"phase": "on", "on_started_at": NOW, "completed_cycles": (at(1),)},
))
def test_health_state_rejects_malformed_fields(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PathHealthState(**({"node_id": "a", "zone": "room_a"} | change))


@pytest.mark.parametrize("change", (
    {"node_id": True}, {"zone": 1}, {"phase": None}, {"extra": 0},
    {"on_started_at": True}, {"on_started_at": NOW},
    {"on_started_at": "2026-09-12T00:00:00"},
    {"on_started_at": "2026-09-12T00:00:00+01:00"},
    {"on_started_at": "invalid"}, {"unsupported_started_at": 1},
    {"completed_cycles": ()}, {"completed_cycles": [None]},
    {"completed_cycles": [True]}, {"completed_cycles": [NOW.isoformat()] * 7},
))
def test_strict_json_field_decoder(change: dict[str, Any]) -> None:
    record = wire(PathHealth(NODES))[0] | change
    with pytest.raises(ValueError):
        decode_health([record])


def test_strict_json_shape_order_and_required_fields() -> None:
    records = wire(PathHealth(NODES))
    assert decode_health(records) == PathHealth(NODES).states
    value: object
    for value in (None, True, {}, (), [None], [records[0], records[0]], records[::-1]):
        with pytest.raises(ValueError):
            decode_health(value)
    for key in records[0]:
        with pytest.raises(ValueError):
            decode_health([{
                name: value for name, value in records[0].items() if name != key
            }])


@pytest.mark.parametrize("defect", (
    "missing_node", "extra_node", "duplicate_node", "order", "zone", "future",
    "expired_cycle", "state_list", "occurrence_list", "missing_warning",
    "extra_warning",
    "duplicate_warning", "warning_order", "warning_zone", "warning_node", "old_reason",
    "late_first", "stale_last", "future_warning", "cleared_active", "early_flapping",
))
def test_strict_atomic_restore_rejects_malformed_snapshot(defect: str) -> None:
    scene = Scene()
    scene.send(0, ("on", "off"), "on")
    ledger = scene.advance(600)
    original = scene.health.states
    states: Any = original
    occurrences: Any = ledger
    if defect == "missing_node":
        states = states[:1]
    elif defect == "extra_node":
        states = (*states, PathHealthState("c", "room_c"))
    elif defect == "duplicate_node":
        states = (states[0], states[0])
    elif defect == "order":
        states = states[::-1]
    elif defect == "zone":
        states = (replace(states[0], zone="other"), states[1])
    elif defect == "future":
        states = (replace(states[0], unsupported_started_at=at(601)), states[1])
    elif defect == "expired_cycle":
        states = (replace(states[0], completed_cycles=(at(-3000),)), states[1])
    elif defect == "state_list":
        states = list(states)
    elif defect == "occurrence_list":
        occurrences = list(ledger)
    elif defect == "missing_warning":
        occurrences = ()
    elif defect == "extra_warning":
        occurrences = (
            ledger[0], warning("a", "sustained_flapping", 500, 600), ledger[1],
        )
    elif defect == "duplicate_warning":
        occurrences = (ledger[0], ledger[0], ledger[1])
    elif defect == "warning_order":
        occurrences = ledger[::-1]
    elif defect == "warning_zone":
        occurrences = (replace(ledger[0], zone="other"), ledger[1])
    elif defect == "warning_node":
        occurrences = (replace(ledger[0], node_id="c"), ledger[1])
    elif defect == "old_reason":
        occurrences = (replace(ledger[0], reason="count_conflict"), ledger[1])
    elif defect == "late_first":
        occurrences = (warning("a", "assertion_timeout", 599, 600), ledger[1])
    elif defect == "stale_last":
        occurrences = (warning("a", "assertion_timeout", 599, 599), ledger[1])
    elif defect == "future_warning":
        occurrences = (warning("a", "assertion_timeout", 600, 601), ledger[1])
    elif defect == "cleared_active":
        occurrences = (warning("a", "assertion_timeout", 600, 600, 600), ledger[1])
    else:
        states = (replace(
            states[0], on_started_at=at(60), unsupported_started_at=at(60),
            completed_cycles=tuple(at(i * 10) for i in range(6)),
        ), states[1])
        occurrences = (warning("a", "sustained_flapping", 51, 600), ledger[1])
    with pytest.raises(ValueError):
        scene.health.restore(states, occurrences, at(600))
    assert scene.health.states == original
    assert scene.advance(600) == ledger


def test_invalid_observations_coverage_and_backwards_time_are_atomic() -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    original = scene.health.states
    for states in (
        (), scene.episodes[:1], (scene.episodes[0], scene.episodes[0]),
        (replace(scene.episodes[0], zone="other"), scene.episodes[1]),
        (replace(scene.episodes[0], alias_states=(("other", "off"),)),
         scene.episodes[1]),
        (replace(scene.episodes[0], alias_states=(
            ("binary_sensor.a", "pressed"), ("binary_sensor.a2", "off"),
        )), scene.episodes[1]),
    ):
        with pytest.raises(ValueError):
            scene.health.observe(states, at(1000), EMPTY)
        assert scene.health.states == original
    for coverage in ({"a"}, frozenset({"unknown"}), frozenset({True})):
        with pytest.raises(ValueError):
            scene.health.advance(at(1000), coverage)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        scene.health.observe(scene.episodes, at(1000), EMPTY, bootstrap=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        scene.health.advance(at(-1), EMPTY)
    assert scene.health.states == original
    assert scene.advance(599) == ()


def test_empty_nodes_and_duplicate_node_or_alias_rejection() -> None:
    health = PathHealth(())
    health.observe((), NOW, EMPTY)
    assert health.advance(NOW, EMPTY) == ()
    assert health.states == ()
    assert decode_health([]) == ()
    health.restore((), (), NOW)
    for nodes in (
        (NODES[0], NODES[0]),
        (NODES[0], replace(NODES[1], aliases=NODES[0].aliases)),
    ):
        with pytest.raises(ValueError):
            PathHealth(nodes)


def test_equal_time_real_cycles_count_but_duplicate_levels_do_not() -> None:
    scene = Scene()
    for _ in range(6):
        scene.cycle(0, 0)
        scene.send(0, ("off", "off"))
    assert scene.health.states[0].completed_cycles == (NOW,) * 6
    assert scene.advance(0) == (warning("a", "sustained_flapping", 0, 0),)
    scene.restart(0)
    assert scene.advance(3600) == (
        warning("a", "sustained_flapping", 0, 3600, 3600),
    )


def test_unknown_alias_with_other_alias_on_does_not_interrupt_known_on() -> None:
    scene = Scene()
    scene.send(0, ("on", "on"))
    scene.send(599, ("unavailable", "on"))
    assert scene.advance(600) == (warning("a", "assertion_timeout", 600, 600),)


@pytest.mark.parametrize("field", (
    "first_observed_at", "last_observed_at", "cleared_at",
))
@pytest.mark.parametrize("value", (True, 1, "not-a-time", datetime(2026, 9, 12)))
def test_restore_revalidates_even_malformed_frozen_warning_objects(
    field: str, value: Any,
) -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    ledger = scene.advance(600)
    corrupted = replace(ledger[0])
    object.__setattr__(corrupted, field, value)
    with pytest.raises(ValueError):
        scene.health.restore(scene.health.states, (corrupted,), at(600))
    assert scene.advance(600) == ledger


@pytest.mark.parametrize("field", ("first_observed_at", "last_observed_at"))
def test_restore_rejects_null_required_warning_timestamps(field: str) -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    ledger = scene.advance(600)
    corrupted = replace(ledger[0])
    object.__setattr__(corrupted, field, None)
    with pytest.raises(ValueError):
        scene.health.restore(scene.health.states, (corrupted,), at(600))
    assert scene.advance(600) == ledger


def test_restore_rejects_cleared_warning_overlapping_new_unsupported_run() -> None:
    scene = Scene()
    scene.send(0, ("on", "off"))
    state = replace(scene.health.states[0], unsupported_started_at=at(100))
    with pytest.raises(ValueError):
        scene.health.restore(
            (state, scene.health.states[1]),
            (warning("a", "assertion_timeout", 100, 200, 200),), at(200),
        )
