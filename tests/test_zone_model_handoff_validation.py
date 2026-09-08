"""REQ-TRAV-018 immutable projections and prepublication proposal inverses.

Valid support history comes from the event-driven handoff fixture. Deliberately
inconsistent component projections below test validator boundaries, not reachable
sensor histories or persistence acceptance. No frozen incident is reconstructed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.predictive_controls.zone_model.profiles import (
    build_physical_nodes,
)
from custom_components.predictive_controls.zone_model.supports import (
    AnonymousSupportTracker,
)
from custom_components.predictive_controls.zone_model.types import (
    AuthorizationUse,
    EpisodeEffect,
    EpisodeState,
    OutwardContext,
    SettledAdjacentHandoff,
    SupportTokenBinding,
    SupportTransition,
    TraversalAuthorization,
    TraversalToken,
    ZoneBeliefState,
)
from tests.test_zone_model_handoff import (
    EPSILON,
    _at,
    _episode,
    _handoff,
    _input,
    _map,
    _policy,
    _seed,
    _token,
)

pytestmark = pytest.mark.target_model


def _selection() -> SettledAdjacentHandoff:
    return SettledAdjacentHandoff(
        "support:a:origin", "a", "a", "a:source", _at(2),
        "b", "b:target", _at(302),
    )


def _authorization(selection: SettledAdjacentHandoff) -> TraversalAuthorization:
    return TraversalAuthorization(
        selection.target_node_id, "b", selection.target_episode_id,
        selection.authorized_at, True, "settled_adjacent_transfer",
        track_confidence="provisional",
        path_node_ids=(selection.source_node_id, selection.target_node_id),
        provenance_kind="settled_adjacent_transfer",
        equivalent_confirmed_strength=True, settled_handoff=selection,
    )


@pytest.mark.parametrize("field", tuple(SettledAdjacentHandoff.__dataclass_fields__))
def test_handoff_selection_is_frozen_in_every_field(field: str) -> None:
    selection = _selection()
    original = _selection()
    with pytest.raises(FrozenInstanceError):
        setattr(selection, field, getattr(selection, field))
    assert selection == original and hash(selection) == hash(original)


@pytest.mark.parametrize("field", tuple(TraversalAuthorization.__dataclass_fields__))
def test_handoff_authorization_is_frozen_in_every_field(field: str) -> None:
    authorization = _authorization(_selection())
    original = _authorization(_selection())
    with pytest.raises(FrozenInstanceError):
        setattr(authorization, field, getattr(authorization, field))
    assert authorization == original and hash(authorization) == hash(original)


@pytest.mark.parametrize(
    "changes,message",
    [
        *[({field: ""}, "identities are invalid") for field in (
            "support_id", "source_node_id", "source_zone", "source_episode_id",
            "target_node_id", "target_episode_id",
        )],
        ({"support_id": "not-support:a"}, "identities are invalid"),
        ({"source_node_id": "b"}, "source and target are inconsistent"),
        ({"source_episode_id": "b:target"}, "source and target are inconsistent"),
        ({"source_updated_at": _at(302) + EPSILON},
         "source and target are inconsistent"),
        *[({field: at}, "must be timezone-aware UTC")
          for field in ("source_updated_at", "authorized_at")
          for at in (_at(2).replace(tzinfo=None),
                     _at(2).astimezone(timezone(timedelta(hours=1))))],
    ],
)
def test_handoff_selection_rejects_invalid_identity_and_frontiers(
    changes: dict[str, Any], message: str,
) -> None:
    selection = _selection()
    with pytest.raises(ValueError, match=message):
        replace(selection, **changes)
    assert selection == _selection()
    # Timestamp equality is allowed; only future source mutation is rejected.
    equal = replace(selection, source_updated_at=selection.authorized_at)
    assert equal.source_updated_at == equal.authorized_at


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"settled_handoff": None}, "requires its dedicated authorization"),
        ({"reason": "adjacent_authorized"}, "requires its dedicated authorization"),
        *[({field: value}, "authorization is inconsistent") for field, value in (
            ("authorized", False), ("target_node_id", "c"),
            ("target_episode_id", "b:other"), ("target_zone", "a"),
            ("authorized_at", _at(302) + EPSILON),
            ("path_node_ids", ("b",)), ("path_node_ids", ("b", "a")),
            ("path_node_ids", ("x", "a", "b")),
            ("provenance_kind", "adjacent"), ("track_confidence", "confirmed"),
            ("track_confidence", None), ("equivalent_confirmed_strength", False),
            ("new_uses", (AuthorizationUse("a:old", "b:target", "adjacent_authorized",
                                            _at(302)),)),
            ("source_tokens", (TraversalToken(
                "a:a:source", "a", "a", "stay", "stay_presence", "a:source",
                _at(301), _at(481), path_node_ids=("a",),
            ),)),
        )],
    ],
)
def test_handoff_authorization_requires_exact_selection_and_no_token_authority(
    changes: dict[str, Any], message: str,
) -> None:
    authorization = _authorization(_selection())
    with pytest.raises(ValueError, match=message):
        replace(authorization, **changes)
    assert authorization == _authorization(_selection())
    ordinary = replace(
        authorization, reason="adjacent_authorized", settled_handoff=None,
        provenance_kind="adjacent", equivalent_confirmed_strength=False,
    )
    assert ordinary.authorized and ordinary.settled_handoff is None


def _proposal(*, correlated: bool = False) -> tuple[
    AnonymousSupportTracker, EpisodeEffect, TraversalAuthorization, TraversalToken,
    tuple[EpisodeState, ...], tuple[ZoneBeliefState, ...], tuple[TraversalToken, ...],
]:
    """Re-use authentic pre-transfer support with immutable post-arrival inputs."""
    predictive_map = _map()
    engine = _seed(predictive_map, correlated=correlated)
    before = engine.snapshot
    result = _handoff(engine)
    authorization, = result.authorizations
    tracker = AnonymousSupportTracker(
        predictive_map, build_physical_nodes(predictive_map).nodes,
    )
    tracker.restore(
        before.anonymous_supports, before.support_token_bindings, before.updated_at,
    )
    effect = EpisodeEffect(
        "b", "b", authorization.target_episode_id,
        "correlated_positive" if correlated else "positive", _at(302),
    )
    return (
        tracker, effect, authorization, _token(engine, "b"),
        result.snapshot.episode_states, result.snapshot.belief_states,
        result.snapshot.retained_traversal_tokens,
    )


@pytest.mark.parametrize(
    "component,changes",
    [
        ("node", {"missing": True}),
        ("node", {"interaction_aliases": ("binary_sensor.b",)}),
        *[("effect", {"kind": kind}) for kind in (
            "interaction", "stable_clear", "correlated_flap_ignored",
            "correlated_continuity_authorized",
        )],
        ("effect", {"node_id": "c"}), ("effect", {"zone": "c"}),
        ("effect", {"episode_id": "b:wrong"}),
        ("target", {"started_at": None}),
        ("target", {"started_at": _at(302) - EPSILON}),
        ("target", {"started_at": _at(302) + EPSILON}),
        *[("target", {"status": status}) for status in (
            "baseline", "clearing", "clear", "degraded", "unavailable",
        )],
        ("target", {"episode_id": None}),
        ("target", {"alias_states": (("binary_sensor.b", "off"),)}),
        ("target", {"health_warning": True}),
        ("target", {"cadence_warning": True,
                    "cadence_warning_reason": "impossible_cadence"}),
        ("target", {"traversal_valid_until": None}),
        ("target", {"traversal_valid_until": _at(302)}),
        ("target", {"traversal_valid_until": _at(302) - EPSILON}),
    ],
)
def test_ineligible_target_fails_before_reading_any_source_projection(
    component: str, changes: dict[str, Any],
) -> None:
    tracker, effect, authorization, _, episodes, beliefs, _ = _proposal()
    target = next(state for state in episodes if state.node_id == "b")
    before = (tracker.supports, tracker.bindings, tracker.latest_transition,
              tracker.counters)
    assert tracker.settled_adjacent_for(target, effect, episodes, beliefs) == (
        authorization.settled_handoff
    )
    if component == "target":
        target = replace(target, **changes)
    elif component == "effect":
        effect = replace(effect, **changes)
    else:
        nodes = dict(tracker._nodes)
        if changes.get("missing"):
            nodes.pop("b")
        else:
            nodes["b"] = replace(nodes["b"], **changes)
        tracker._nodes = nodes
    # Duplicated inputs would raise if the selector read source projections.
    with patch.object(
        tracker, "_unique_by", side_effect=AssertionError("source lookup"),
    ):
        assert tracker.settled_adjacent_for(
            target, effect, (*episodes, episodes[0]), (*beliefs, beliefs[0]),
        ) is None
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters) == before


@pytest.mark.parametrize(
    "component,changes",
    [
        ("support", {"state": "moving", "valid_until": _at(482)}),
        ("support", {"updated_at": _at(302) + EPSILON}),
        ("support", {"created_at": _at(303), "updated_at": _at(303)}),
        ("support", {"current_episode_id": "a:wrong"}),
        ("node", {"missing": True}), ("node", {"zone": "elsewhere"}),
        ("node", {"interaction_aliases": ("binary_sensor.a",)}),
        ("node", {"profile_name": "transition_fast"}),
        ("node", {"profile_name": "entry_boundary"}),
        ("node", {"zone": "b"}),
        ("source", {"missing": True}), ("source", {"zone": "elsewhere"}),
        ("source", {"episode_id": None}),
        ("source", {"started_at": None}),
        ("source", {"started_at": _at(302) + EPSILON}),
        *[("source", {"status": status}) for status in (
            "baseline", "clearing", "clear", "degraded", "unavailable",
        )],
        ("source", {"alias_states": (("binary_sensor.a", "off"),)}),
        ("source", {"health_warning": True}),
        ("source", {"cadence_warning": True,
                    "cadence_warning_reason": "impossible_cadence"}),
        ("belief", {"missing": True}), ("belief", {"health_warning": True}),
        *[("belief", {"context": context}) for context in (
            "degraded_asserted", "unavailable", "cleared_with_outward",
            "cleared_without_outward",
        )],
        ("belief", {"generation_episode_id": "a:wrong"}),
        ("belief", {"asserted_episode_id": "a:wrong"}),
        ("belief", {"generation_episode_id": None}),
        ("belief", {"asserted_episode_id": None}),
        ("belief", {"outward_context": OutwardContext("a:source", _at(482))}),
        ("belief", {"log_odds": math.log(0.699999 / 0.300001)}),
    ],
)
def test_each_source_trust_predicate_is_required_without_mutating_support(
    component: str, changes: dict[str, Any],
) -> None:
    tracker, effect, authorization, _, episodes, beliefs, _ = _proposal()
    target = next(state for state in episodes if state.node_id == "b")
    assert tracker.settled_adjacent_for(target, effect, episodes, beliefs) == (
        authorization.settled_handoff
    )
    if component == "support":
        tracker._supports = (replace(tracker.supports[0], **changes),)
    elif component == "node":
        nodes = dict(tracker._nodes)
        if changes.get("missing"):
            nodes.pop("a")
        else:
            nodes["a"] = replace(nodes["a"], **changes)
        tracker._nodes = nodes
    elif component == "source":
        episodes = tuple(
            replace(state, **changes) if state.node_id == "a" else state
            for state in episodes
            if not (state.node_id == "a" and changes.get("missing"))
        )
    else:
        beliefs = tuple(
            replace(state, **changes) if state.zone == "a" else state
            for state in beliefs
            if not (state.zone == "a" and changes.get("missing"))
        )
    before = (tracker.supports, tracker.bindings, tracker.latest_transition,
              tracker.counters, episodes, beliefs)
    assert tracker.settled_adjacent_for(target, effect, episodes, beliefs) is None
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters, episodes, beliefs) == before


@pytest.mark.parametrize("target_id", ("a", "y", "c", "d"))
def test_handoff_requires_different_node_zone_and_direct_not_two_hop_adjacency(
    target_id: str,
) -> None:
    tracker, effect, _, _, episodes, beliefs, _ = _proposal()
    target = next(state for state in episodes if state.node_id == "b")
    target = replace(
        target, node_id=target_id, zone="a" if target_id == "y" else target_id,
    )
    effect = replace(effect, node_id=target.node_id, zone=target.zone)
    # Y is adjacent but projected into the source's zone; C is two hops away.
    assert tracker.settled_adjacent_for(target, effect, episodes, beliefs) is None


@pytest.mark.parametrize("correlated", (False, True))
def test_selection_and_proposal_are_read_only_until_single_idempotent_commit(
    correlated: bool,
) -> None:
    tracker, effect, authorization, token, episodes, beliefs, retained = _proposal(
        correlated=correlated,
    )
    original = (tracker.supports, tracker.bindings, tracker.latest_transition,
                tracker.counters)
    support, = tracker.supports
    target = next(state for state in episodes if state.node_id == "b")
    # Selection threshold is inclusive and uses belief calibration, not active.
    beliefs = tuple(
        replace(belief, log_odds=math.log(0.7 / 0.3)) if belief.zone == "a" else belief
        for belief in beliefs
    )
    assert tracker.settled_adjacent_for(target, effect, episodes, beliefs) == (
        authorization.settled_handoff
    )
    prepared = tracker.prepare_handoff(
        effect.at, effect, authorization, token, episodes, beliefs, (token,),
    )
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters) == original
    moved, = prepared.supports
    assert moved.support_id == support.support_id
    assert moved.created_at == support.created_at and moved.updated_at == effect.at
    assert moved.current_node_id == "b" and moved.path_node_ids == ("a", "b")
    assert prepared.bindings == (
        SupportTokenBinding(token.token_id, support.support_id),
    )
    # No supplied proposal: apply must perform real validation/preparation itself.
    applied = tracker.apply(
        effect.at, effect, authorization, token, episodes, beliefs, (token,), retained,
    )
    assert applied == prepared
    counters = tracker.counters
    assert counters["support_transferred"] == original[3]["support_transferred"] + 1
    assert counters["support_created"] == original[3]["support_created"]
    assert tracker.apply(
        effect.at, effect, authorization, token, episodes, beliefs, (token,), retained,
    ) == prepared
    assert tracker.counters == counters
    assert tracker.prepare_handoff(
        effect.at, effect, authorization, token, episodes, beliefs, (token,),
    ) == prepared
    assert tracker.counters == counters


@pytest.mark.parametrize("missing", ("effect", "token", "both"))
def test_unprepared_handoff_requires_effect_and_token_without_committing(
    missing: str,
) -> None:
    tracker, effect, authorization, token, episodes, beliefs, retained = _proposal()
    before = (tracker.supports, tracker.bindings, tracker.latest_transition,
              tracker.counters)
    with pytest.raises(ValueError, match="requires a target effect/token"):
        tracker.apply(
            effect.at, None if missing in {"effect", "both"} else effect,
            authorization, None if missing in {"token", "both"} else token,
            episodes, beliefs, (token,), retained,
        )
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters) == before


@pytest.mark.parametrize("correlated", (False, True))
@pytest.mark.parametrize(
    "fault,message",
    [
        ("no-selection", "requires its selected live target"),
        ("evicted-target", "requires its selected live target"),
        *[(fault, "selection is no longer valid") for fault in (
            "absent-support", "stale-selection", "missing-target",
            "confirmed-token", "no-equivalence", "wrong-expiry", "unhealthy-source",
        )],
        *[(fault, "application inputs are inconsistent") for fault in (
            "effect-time", "token-time", "token-episode", "token-node", "token-zone",
            "token-path", "token-provenance",
        )],
        ("duplicate-episodes", "episode inputs must be unique"),
        ("duplicate-beliefs", "belief inputs must be unique"),
    ],
)
def test_real_malformed_proposal_validation_precedes_policy_and_publication(
    correlated: bool, fault: str, message: str,
) -> None:
    engine = _seed(_map(), correlated=correlated)
    before = engine.snapshot
    counters = engine._supports.counters
    prepare = engine._supports.prepare_handoff

    def malformed(
        at: datetime, effect: EpisodeEffect, authorization: TraversalAuthorization,
        token: TraversalToken, episodes: Sequence[EpisodeState],
        beliefs: Sequence[ZoneBeliefState], active_tokens: Sequence[TraversalToken],
    ) -> SupportTransition:
        selection = authorization.settled_handoff
        assert selection is not None
        if fault == "no-selection":
            authorization = replace(
                authorization, reason="adjacent_authorized", settled_handoff=None,
            )
        elif fault == "evicted-target":
            active_tokens = ()
        elif fault in {"absent-support", "stale-selection"}:
            selection = (
                replace(selection, support_id="support:missing")
                if fault == "absent-support"
                else replace(
                    selection, source_updated_at=selection.source_updated_at + EPSILON,
                )
            )
            authorization = replace(authorization, settled_handoff=selection)
        elif fault == "missing-target":
            episodes = tuple(state for state in episodes if state.node_id != "b")
        elif fault == "unhealthy-source":
            episodes = tuple(
                replace(state, health_warning=True) if state.node_id == "a" else state
                for state in episodes
            )
        elif fault == "duplicate-episodes":
            episodes = (*episodes, episodes[0])
        elif fault == "duplicate-beliefs":
            beliefs = (*beliefs, beliefs[0])
        elif fault == "effect-time":
            effect = replace(effect, at=at - EPSILON)
        else:
            mutations: dict[str, dict[str, Any]] = {
                "confirmed-token": {"track_confidence": "confirmed"},
                "no-equivalence": {"equivalent_confirmed_strength": False},
                "wrong-expiry": {"valid_until": token.valid_until + EPSILON},
                "token-time": {"accepted_at": at - EPSILON},
                "token-episode": {"episode_id": "b:wrong"},
                "token-node": {"node_id": "a"},
                "token-zone": {"zone": "a"},
                "token-path": {"path_node_ids": ("b",)},
                "token-provenance": {"provenance_kind": "adjacent"},
            }
            token = replace(token, **mutations[fault])
            # Keep it present, so deeper proposal checks (not membership) reject.
            active_tokens = (token,)
        return prepare(
            at, effect, authorization, token, episodes, beliefs, active_tokens,
        )

    with (
        patch.object(
            engine._supports, "prepare_handoff", side_effect=malformed,
        ) as checked,
        patch.object(
            engine, "_evaluate_policies", wraps=engine._evaluate_policies,
        ) as policy,
        patch.object(engine._supports, "apply", wraps=engine._supports.apply) as commit,
        patch.object(engine, "_apply_count_conflicts") as count,
    ):
        with pytest.raises(ValueError, match=message):
            engine.observe(
                _input("b", "on", 302),
                decision_callback=lambda *_: pytest.fail("invalid proposal published"),
            )
        assert checked.call_count == 1
        policy.assert_not_called()
        commit.assert_not_called()
        count.assert_not_called()
    assert not _policy(engine, "b").active
    assert engine.snapshot.anonymous_supports == before.anonymous_supports
    assert engine.snapshot.support_token_bindings == before.support_token_bindings
    assert engine._supports.counters == counters
    assert _episode(engine, "a") == next(
        state for state in before.episode_states if state.node_id == "a"
    )
    assert not engine._pending_prediction_learning


@pytest.mark.parametrize("correlated", (False, True))
def test_consumed_selection_cannot_rebind_same_support_to_another_target(
    correlated: bool,
) -> None:
    tracker, effect, authorization, token, episodes, beliefs, retained = _proposal(
        correlated=correlated,
    )
    tracker.apply(
        effect.at, effect, authorization, token, episodes, beliefs, (token,), retained,
    )
    before = (tracker.supports, tracker.bindings, tracker.latest_transition,
              tracker.counters)
    selection = authorization.settled_handoff
    assert selection is not None
    other_selection = replace(selection, target_node_id="y", target_episode_id="y:new")
    other_authorization = replace(
        authorization, target_node_id="y", target_zone="y", target_episode_id="y:new",
        path_node_ids=("a", "y"), settled_handoff=other_selection,
    )
    other_effect = replace(effect, node_id="y", zone="y", episode_id="y:new")
    other_token = replace(
        token, token_id="y:y:new", node_id="y", zone="y", episode_id="y:new",
        path_node_ids=("a", "y"),
    )
    target = next(state for state in episodes if state.node_id == "b")
    episodes = tuple(state for state in episodes if state.node_id != "y") + (
        replace(target, node_id="y", zone="y", episode_id="y:new"),
    )
    with pytest.raises(ValueError, match="selection is no longer valid"):
        tracker.apply(
            effect.at, other_effect, other_authorization, other_token,
            episodes, beliefs, (token, other_token), retained,
        )
    assert (tracker.supports, tracker.bindings, tracker.latest_transition,
            tracker.counters) == before


@pytest.mark.parametrize("correlated", (False, True))
def test_unbound_dedicated_token_never_qualifies_for_generic_support_creation(
    correlated: bool,
) -> None:
    tracker, effect, authorization, token, episodes, beliefs, retained = _proposal(
        correlated=correlated,
    )
    tracker.clear(effect.at)
    assert not tracker.supports and not tracker.bindings
    assert not tracker._confirmed_strength(token)
    # Even a caller attempting generic fallthrough with spare count capacity
    # cannot turn restricted equivalence into new confirmed count support.
    generic = replace(
        authorization, reason="adjacent_authorized", settled_handoff=None,
    )
    result = tracker.apply(
        effect.at, effect, generic, token, episodes, beliefs, (token,), retained,
    )
    assert not result.supports and not result.bindings
    assert tracker.counters["support_created"] == 0
