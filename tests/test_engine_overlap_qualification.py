"""Synthetic overlap qualification; no captured incident inputs are changed.

September 17 repair: X4 retains correlated T3 until genuine history eviction.
Keep the original held-ON nonrearm stream alongside the cleared membership
specimens, and observe real fallback support preparation without replacing it.
Authority: PATH007/008, TRAV014, PRED007/008/009, STATE001/002.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from custom_components.predictive_controls.zone_model.persistence import (
    restore_target_state,
)
from custom_components.predictive_controls.zone_model.supports import (
    PreparedSupportUpdate,
)
from custom_components.predictive_controls.zone_model.types import (
    EpisodeEffect,
    EpisodeState,
    SupportTransition,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
)
from tests.engine_completion_fixture import (
    at,
    correlated_ready,
    event,
    graph,
    roundtrip,
)
from tests.test_zone_model_persistence import structural_payload

pytestmark = pytest.mark.target_model


@pytest.mark.parametrize("count", (1, 2))
def test_held_correlated_history_eviction_does_not_rearm(count: int) -> None:
    """Original direct T3/X4/Y6/Z7/W8/ON9, without instant-retirement fiction."""
    predictive_map = graph({
        "a": ("b",), "b": ("a", "c"), "c": ("b", "t", "x"),
        "t": ("c",), "u": ("v",), "v": ("u",),
        "x": ("c", "y"), "y": ("x", "z"), "z": ("y", "w"), "w": ("z",),
    }, presence=frozenset({"t"}))
    inputs = (event("t", "on", -40), event("t", "off", -20),
              event("a", "on", 0), event("b", "on", 1), event("c", "on", 2))
    payload = structural_payload(predictive_map, inputs, count=count)
    engine = restore_target_state(predictive_map, payload, at(2))
    counts = engine.prediction_manager.chain.counts
    debt = engine.prediction_state["deferred_counts"]
    result = engine.observe(event("t", "on", 3))
    assert result.disposition == "accepted_correlated_positive"
    assert result.authorizations[0].reason == "selected_path"
    assert not any(t.node_id in {"c", "t"} for t in result.snapshot.traversal_tokens)
    engine.observe(event("x", "on", 4))
    physical = next(s for s in engine.snapshot.episode_states if s.node_id == "t")
    source = next(s for s in engine.snapshot.selected_sources if s.node_id == "t")
    assert physical.status == "asserted" and physical.cadence_correlated
    assert source.origin == "correlated" and source.consumed
    assert source.episode_id == physical.episode_id
    assert any(witness[-1].episode_id == physical.episode_id
               and witness[-1].branch_active
               for path in engine.snapshot.selected_paths if path is not None
               for witness in path.branch_routes)
    roundtrip(predictive_map, engine)
    for node, seconds in (("y", 6), ("z", 7), ("w", 8)):
        engine.observe(event(node, "on", seconds))
        roundtrip(predictive_map, engine)
    assert all(v.episode_id != physical.episode_id
               for path in engine.snapshot.selected_paths if path is not None
               for v in path.occurrences)
    assert "t" not in engine._selected_paths.covered_nodes
    selected = engine.snapshot.selected_paths
    restored = roundtrip(predictive_map, engine)
    results = []
    for item in (engine, restored):
        results.append(item.observe(event("t", "on", 9)))
        current = next(s for s in item.snapshot.episode_states if s.node_id == "t")
        assert current.status == "asserted" and current.cadence_correlated
        assert current.episode_id == physical.episode_id
        assert item.snapshot.selected_paths == selected
        assert source == next(s for s in item.snapshot.selected_sources
                              if s.node_id == "t")
        assert not any(t.episode_id == physical.episode_id for t in (
            *item.snapshot.traversal_tokens, *item.snapshot.retained_traversal_tokens,
        ))
        assert item.prediction_manager.chain.counts == counts
        assert item.prediction_state["deferred_counts"] == debt
        assert not item._pending_prediction_learning
        roundtrip(predictive_map, item)
    assert results[0] == results[1]
    assert not results[0].authorizations and not results[0].policy_events


def test_correlated_token_survives_real_support_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe the actual preparation boundary; never inject a prepared result."""
    predictive_map, engine = correlated_ready()
    original_prepare = engine._supports.prepare
    calls: list[TraversalToken] = []

    def checked_prepare(
        observed_at: datetime,
        effect: EpisodeEffect | None,
        authorization: TraversalAuthorization | None,
        issued_target_token: TraversalToken | None,
        episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState],
        active_tokens: Sequence[TraversalToken],
        retained_tokens: Sequence[TraversalToken],
        *,
        prepared_handoff: SupportTransition | None = None,
    ) -> PreparedSupportUpdate:
        assert observed_at == at(38)
        assert effect is not None and effect.kind == "correlated_positive"
        assert authorization is not None
        assert authorization.reason == "adjacent_authorized"
        assert issued_target_token is not None
        token = issued_target_token
        assert token.node_id == "t" and token in active_tokens
        physical = next(s for s in episodes if s.node_id == "t")
        source = next(s for s in engine.snapshot.selected_sources if s.node_id == "t")
        assert source.origin == "correlated" and source.consumed
        assert physical.cadence_correlated
        assert source.episode_id == physical.episode_id == token.episode_id
        assert source.at == physical.started_at == token.accepted_at == at(38)
        assert all(v.episode_id != token.episode_id
                   for path in engine.snapshot.selected_paths if path is not None
                   for v in path.occurrences)
        calls.append(token)
        return original_prepare(
            observed_at, effect, authorization, token, episodes, beliefs,
            active_tokens, retained_tokens, prepared_handoff=prepared_handoff,
        )

    monkeypatch.setattr(engine._supports, "prepare", checked_prepare)
    result = engine.observe(event("t", "on", 38))
    token, = calls
    assert token in result.snapshot.traversal_tokens
    assert any(s.current_node_id == "t" for s in result.snapshot.anonymous_supports)
    assert [(p.zone, p.kind) for p in result.policy_events] == [("t", "acquired")]
    assert not engine._pending_prediction_learning
    roundtrip(predictive_map, engine)
