from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.count import (
    DIAGNOSTIC_LIMIT,
    CountContext,
    CountInput,
    CountState,
    apply_count_update,
)
from custom_components.predictive_controls.zone_model.filter import ZoneBeliefFilter
from custom_components.predictive_controls.zone_model.profiles import BELIEF_PROFILES
from custom_components.predictive_controls.zone_model.traversal import TraversalFrontier

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def test_count_validation_preserves_last_valid_value() -> None:
    context = CountContext(0)
    accepted = context.observe(CountInput("one", 1, True, NOW))
    duplicate = context.observe(CountInput("one", 1, True, NOW))
    stale = context.observe(CountInput("stale", 0, True, NOW - timedelta(seconds=1)))
    invalid = context.observe(
        CountInput("invalid", 3, True, NOW + timedelta(seconds=1))
    )
    unavailable = context.observe(
        CountInput("unavailable", None, False, NOW + timedelta(seconds=2))
    )
    same_value = context.observe(
        CountInput("same-value", 1, True, NOW + timedelta(seconds=3))
    )

    assert accepted.disposition == "accepted"
    assert accepted.state.expected_count == 1
    assert accepted.state.positive_transition_at == NOW
    assert duplicate.disposition == "duplicate"
    assert stale.disposition == "stale"
    assert invalid.disposition == "invalid"
    assert unavailable.disposition == "unavailable"
    assert same_value.disposition == "duplicate"
    assert context.state.expected_count == 1
    assert context.state.diagnostics == (1, 2, 1, 1, 1)


def test_count_zero_resets_filters_and_frontier_but_positive_invents_nothing() -> None:
    context = CountContext(1)
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unused": {
                    "role": "room_occupancy",
                    "entities": {"motion": "binary_sensor.unused"},
                }
            }
        }
    )
    frontier = TraversalFrontier(predictive_map, ())
    filters = {
        "a": ZoneBeliefFilter("a", BELIEF_PROFILES["stay_pir"], NOW),
        "b": ZoneBeliefFilter("b", BELIEF_PROFILES["stay_presence"], NOW),
    }
    filters["a"].apply_positive("a-episode", NOW + timedelta(seconds=1))
    filters["b"].apply_positive("b-episode", NOW + timedelta(seconds=1))

    zero = context.observe(CountInput("zero", 0, True, NOW + timedelta(seconds=2)))
    apply_count_update(zero, filters, frontier)
    for zone, filter_ in filters.items():
        assert filter_.state.generation_episode_id is None
        profile_name = "stay_pir" if zone == "a" else "stay_presence"
        assert filter_.state.probability == pytest.approx(
            BELIEF_PROFILES[profile_name].prior_probability
        )
    assert frontier.tokens == ()

    positive = context.observe(
        CountInput("positive", 2, True, NOW + timedelta(seconds=3))
    )
    before = {zone: filter_.state for zone, filter_ in filters.items()}
    apply_count_update(positive, filters, frontier)
    assert {zone: filter_.state for zone, filter_ in filters.items()} == before
    assert frontier.tokens == ()


def test_count_diagnostics_compare_clusters_without_forcing_zones() -> None:
    context = CountContext(2)
    diagnostics = context.diagnostics(evidence_cluster_count=1)
    assert diagnostics.expected_count == 2
    assert diagnostics.evidence_cluster_count == 1
    assert diagnostics.cluster_delta == -1


@pytest.mark.parametrize("initial_count", [True, 1.5, -1, 3])
def test_count_context_rejects_invalid_initial_count(initial_count: object) -> None:
    with pytest.raises(ValueError):
        CountContext(initial_count)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "event",
    [
        CountInput("none", None, True, NOW),
        CountInput("bool", True, True, NOW),
    ],
)
def test_count_context_rejects_non_integer_values(event: CountInput) -> None:
    assert CountContext(0).observe(event).disposition == "invalid"


def test_count_state_and_input_validate_direct_construction() -> None:
    with pytest.raises(ValueError):
        CountInput("", 0, True, NOW)
    with pytest.raises(ValueError):
        CountInput("event", 0, 1, NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CountInput("event", 0, True, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        CountState(3)
    with pytest.raises(ValueError):
        CountState(1, positive_transition_at=NOW)
    with pytest.raises(ValueError):
        CountState(
            1,
            positive_transition_at=NOW,
            positive_transition_until=NOW,
        )
    with pytest.raises(ValueError):
        CountState(1, seen_event_ids=("same", "same"))
    with pytest.raises(ValueError):
        CountState(1, seen_event_ids=("",))
    with pytest.raises(ValueError):
        CountState(1, diagnostics=(0, 0, 0, 0))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CountState(1, diagnostics=(0, 0, 0, 0, -1))


def test_count_diagnostics_are_bounded_and_validate_cluster_count() -> None:
    assert CountContext._increment((DIAGNOSTIC_LIMIT, 0, 0, 0, 0), 0)[0] == (
        DIAGNOSTIC_LIMIT
    )
    with pytest.raises(ValueError):
        CountContext(0).diagnostics(-1)


def test_count_seen_event_ids_are_bounded() -> None:
    context = CountContext(0)
    for index in range(40):
        context.observe(CountInput(f"event-{index}", None, False, NOW))
    assert len(context.state.seen_event_ids) == 32
    assert context.state.seen_event_ids[0] == "event-8"


def test_count_zero_rejects_stale_filter_or_frontier_atomically() -> None:
    context = CountContext(1)
    zero = context.observe(CountInput("zero", 0, True, NOW))
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "unused": {
                    "entities": {"motion": "binary_sensor.unused"},
                }
            }
        }
    )
    frontier = TraversalFrontier(predictive_map, ())
    future_filter = ZoneBeliefFilter(
        "future", BELIEF_PROFILES["stay_pir"], NOW + timedelta(seconds=1)
    )
    before = future_filter.state
    with pytest.raises(ValueError, match="predates a zone belief"):
        apply_count_update(zero, {"future": future_filter}, frontier)
    assert future_filter.state == before

    frontier.advance(NOW + timedelta(seconds=1))
    current_filter = ZoneBeliefFilter("current", BELIEF_PROFILES["stay_pir"], NOW)
    with pytest.raises(ValueError, match="cannot move backward"):
        apply_count_update(zero, {"current": current_filter}, frontier)
    assert current_filter.state.last_updated_at == NOW
