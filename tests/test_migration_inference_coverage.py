from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.predictive_controls.events import OccupancyEvent
from custom_components.predictive_controls.inference import count_transition
from custom_components.predictive_controls.inference import policy as policy_module
from custom_components.predictive_controls.inference.association import (
    AugmentedLogMessage,
    EndpointFactor,
)
from custom_components.predictive_controls.inference.episodes import (
    EpisodeEmission,
    ObservationEpisodes,
)
from custom_components.predictive_controls.inference.factor_chain import (
    ExactFactorChain,
    ZoneLikelihoodStep,
)
from custom_components.predictive_controls.inference.operators import (
    CompleteMoveOperators,
)
from custom_components.predictive_controls.inference.policy import (
    PosteriorEventPolicy,
    PosteriorPolicyAuditEntry,
)
from custom_components.predictive_controls.inference.reducer import (
    AugmentedEventReducer,
    FactorChainEventReducer,
    FactorChainReplayState,
    InferenceReplayState,
)
from custom_components.predictive_controls.inference.state_space import (
    CompactLogPosterior,
    StateSpace,
)
from custom_components.predictive_controls.inference.support import (
    injective_support_probability,
)
from custom_components.predictive_controls.inference.types import (
    AugmentedStateKey,
    EndpointAlternative,
    EndpointAssignmentAtom,
    EndpointToken,
    MovementDisposition,
    SupportEventAtom,
)
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.observation_model import ObservationModel
from custom_components.predictive_controls.occupancy_state import (
    PolicyDecision,
    ReleaseCause,
    ZonePolicyState,
)
from custom_components.predictive_controls.prediction import PredictionManager

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {
                    "zone": "office",
                    "entities": {
                        "motion": "binary_sensor.office_motion",
                        "presence": "binary_sensor.office_presence",
                    },
                    "adjacent": ["hall"],
                },
                "hall": {
                    "zone": "hall",
                    "role": "transition_gate",
                    "occupancy_behavior": "transient",
                    "entities": {"motion": "binary_sensor.hall_motion"},
                    "adjacent": ["office", "kitchen", "living"],
                },
                "kitchen": {
                    "zone": "kitchen",
                    "entities": {"motion": "binary_sensor.kitchen_motion"},
                    "adjacent": ["hall"],
                },
                "living": {
                    "zone": "living",
                    "entities": {"motion": "binary_sensor.living_motion"},
                    "adjacent": ["hall"],
                },
            }
        }
    )


def make_event(
    node_id: str = "office",
    *,
    state: str = "on",
    seconds: int = 0,
) -> OccupancyEvent:
    return OccupancyEvent(
        f"binary_sensor.{node_id}_motion",
        node_id,
        node_id,
        "first_floor",
        "transition_gate" if node_id == "hall" else "room_occupancy",
        "transient" if node_id == "hall" else "sustained",
        "motion",
        state,
        NOW + timedelta(seconds=seconds),
        1.0,
    )


def make_factor(
    endpoint_id: str = "hall-endpoint",
    *,
    target_index: int = 1,
    source_index: int | None = 0,
) -> EndpointFactor:
    deadline = NOW + timedelta(seconds=30)
    return EndpointFactor(
        EndpointToken(endpoint_id, "hall", NOW),
        target_index,
        "hall",
        (
            EndpointAlternative(
                f"stay:{endpoint_id}",
                "stay",
                None,
                None,
                (),
                math.log(0.4),
                deadline,
                (endpoint_id,),
            ),
            EndpointAlternative(
                f"move:{endpoint_id}",
                "graph_valid",
                source_index,
                None if source_index is None else "office",
                ("office", "hall") if source_index is not None else (),
                math.log(0.6),
                deadline,
                (endpoint_id,),
            ),
        ),
        math.log(0.2),
        math.log(0.9),
    )


def make_support(
    source: str = "office",
    target: str = "hall",
    *,
    support_id: str = "support-1",
    endpoint_id: str = "endpoint-1",
    route_nodes: tuple[str, ...] | None = None,
    disposition: MovementDisposition = "graph_valid",
    learning_eligible: bool = True,
) -> SupportEventAtom:
    return SupportEventAtom(
        support_id,
        disposition,
        source,
        target,
        (source, target) if route_nodes is None else route_nodes,
        (endpoint_id,),
        (),
        NOW,
        NOW + timedelta(minutes=1),
        learning_eligible,
    )


def test_augmented_likelihood_rejects_invalid_zone_and_nonfinite_evidence() -> None:
    space = StateSpace(("office", "hall"), 1)
    message = AugmentedLogMessage.from_posterior(
        CompactLogPosterior.certain(space, (1, 0, 0))
    )

    for zone_index in (-1, len(space.zones)):
        with pytest.raises(IndexError, match="zone index"):
            message.apply_zone_likelihood(
                zone_index,
                empty_log_likelihood=0.0,
                occupied_log_likelihood=0.0,
            )
    for empty, occupied in ((math.nan, 0.0), (0.0, math.inf)):
        with pytest.raises(ValueError, match="must be finite"):
            message.apply_zone_likelihood(
                0,
                empty_log_likelihood=empty,
                occupied_log_likelihood=occupied,
            )

    assert message.occupancy_posterior().normalization == pytest.approx(1.0)


def test_logsumexp_preserves_normalized_mass_and_empty_identity() -> None:
    assert count_transition._logsumexp(()) == -math.inf  # noqa: SLF001
    assert count_transition._logsumexp((math.log(0.25), math.log(0.75))) == (  # noqa: SLF001
        pytest.approx(0.0, abs=1e-12)
    )


def test_episode_restore_rejects_duplicate_nodes_and_alias_drift_atomically() -> None:
    episodes = ObservationEpisodes(make_map())
    original = episodes.states
    office = next(state for state in original if state.node_id == "office")

    with pytest.raises(ValueError, match="nodes are invalid"):
        episodes.restore_snapshot((*original, office))
    assert episodes.states == original

    incompatible = replace(
        office,
        raw_alias_states=(("binary_sensor.unmapped", "off"),),
    )
    with pytest.raises(ValueError, match="incompatible with the map"):
        episodes.restore_snapshot(
            tuple(
                incompatible if state.node_id == "office" else state
                for state in original
            )
        )
    assert episodes.states == original


@pytest.mark.parametrize(
    ("zone_index", "empty", "occupied", "message"),
    (
        (-1, 0.0, 0.0, "non-negative"),
        (0, math.nan, 0.0, "must be finite"),
        (0, 0.0, math.inf, "must be finite"),
    ),
)
def test_zone_likelihood_step_validates_model_inputs(
    zone_index: int,
    empty: float,
    occupied: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ZoneLikelihoodStep(zone_index, empty, occupied, NOW)


def test_factor_chain_rejects_incompatible_operators_and_duplicate_endpoints() -> None:
    space = StateSpace(("office", "hall"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    other_space = StateSpace(("office", "hall"), 1)
    factor = make_factor()

    with pytest.raises(ValueError, match="share a state space"):
        ExactFactorChain(
            posterior,
            operators=CompleteMoveOperators(other_space),
        )
    with pytest.raises(ValueError, match="duplicated"):
        ExactFactorChain(posterior, (factor, factor))

    chain = ExactFactorChain(posterior).apply_endpoint(factor)
    with pytest.raises(ValueError, match="already present"):
        chain.apply_endpoint(factor)
    assert chain.posterior.normalization == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("corrupt_probability", (-0.01, 1.01))
def test_factor_chain_joint_probability_guard_rejects_corrupt_numeric_result(
    monkeypatch: pytest.MonkeyPatch,
    corrupt_probability: float,
) -> None:
    space = StateSpace(("office", "hall"), 1)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (1, 0, 0))
    ).apply_endpoint(make_factor())
    real_exp = math.exp
    real_log = math.log

    def stable_logaddexp(first: float, second: float) -> float:
        if first == -math.inf:
            return second
        if second == -math.inf:
            return first
        maximum = max(first, second)
        return maximum + real_log(
            real_exp(first - maximum) + real_exp(second - maximum)
        )

    monkeypatch.setattr(
        "custom_components.predictive_controls.inference.factor_chain._logaddexp",
        stable_logaddexp,
    )
    monkeypatch.setattr(
        "custom_components.predictive_controls.inference.factor_chain.math.exp",
        lambda _value: corrupt_probability,
    )
    with pytest.raises(ValueError, match="probability is out of range"):
        chain.assignment_probability("hall-endpoint", lambda _atom: True)


def test_factor_chain_joint_probability_rejects_missing_total_mass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = StateSpace(("office", "hall"), 1)
    chain = ExactFactorChain(
        CompactLogPosterior.certain(space, (1, 0, 0))
    ).apply_endpoint(make_factor())
    monkeypatch.setattr(
        ExactFactorChain,
        "_factor_transitions",
        lambda _chain, _factor, _rank: (),
    )

    with pytest.raises(ValueError, match="no finite total mass"):
        chain.assignment_probability("hall-endpoint", lambda _atom: True)


def test_factor_chain_compaction_handles_noop_likelihood_and_endpoint_steps() -> None:
    space = StateSpace(("office", "hall"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    empty = ExactFactorChain(posterior)

    unchanged, consumed = empty.compact(NOW)
    assert unchanged is empty
    assert consumed == ()

    chain = empty.apply_zone_likelihood(
        0,
        empty_log_likelihood=math.log(0.2),
        occupied_log_likelihood=math.log(0.9),
        event_at=NOW,
    ).apply_endpoint(make_factor())
    compacted, consumed = chain.compact(NOW + timedelta(seconds=31))

    assert consumed == ("hall-endpoint",)
    assert compacted.steps == ()
    assert compacted.posterior.normalization == pytest.approx(1.0, abs=1e-12)
    assert tuple(compacted.posterior) == pytest.approx(
        tuple(chain.posterior),
        abs=1e-12,
    )


def test_factor_chain_compaction_rejects_context_and_projection_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = StateSpace(("office", "hall"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    chain = ExactFactorChain(posterior).apply_endpoint(make_factor())
    watermark = NOW + timedelta(seconds=31)

    with monkeypatch.context() as context:
        context.setattr(
            AugmentedLogMessage,
            "finalize",
            lambda message, _watermark, _declarations=(): message,
        )
        with pytest.raises(ValueError, match="retained assignment context"):
            chain.compact(watermark)

    with monkeypatch.context() as context:
        context.setattr(
            EndpointFactor,
            "apply",
            lambda _factor, message, _operators: message,
        )
        with pytest.raises(ValueError, match="changed the factor-chain posterior"):
            chain.compact(watermark)


def test_factor_chain_rejects_persisted_and_support_base_drift() -> None:
    space = StateSpace(("office", "hall"), 1)
    base = CompactLogPosterior.certain(space, (1, 0, 0))
    chain = ExactFactorChain(base)
    other_space = StateSpace(("office", "hall"), 1)

    with pytest.raises(ValueError, match="factor-chain space"):
        chain.with_persisted_posterior(
            CompactLogPosterior.certain(other_space, (1, 0, 0))
        )
    with pytest.raises(ValueError, match="does not reconstruct"):
        chain.with_persisted_posterior(
            CompactLogPosterior.certain(space, (0, 1, 0))
        )
    with pytest.raises(ValueError, match="support base must use"):
        ExactFactorChain(
            base,
            base_message=AugmentedLogMessage.from_posterior(
                CompactLogPosterior.certain(other_space, (1, 0, 0))
            ),
        )
    with pytest.raises(ValueError, match="does not project"):
        ExactFactorChain(
            base,
            base_message=AugmentedLogMessage.from_posterior(
                CompactLogPosterior.certain(space, (0, 1, 0))
            ),
        )


def test_factor_chain_endpoint_validates_target_and_preserves_stay() -> None:
    space = StateSpace(("office", "hall"), 1)
    posterior = CompactLogPosterior.certain(space, (1, 0, 0))
    chain = ExactFactorChain(posterior)

    with pytest.raises(ValueError, match="valid target"):
        make_factor(target_index=-1)
    with pytest.raises(IndexError, match="target zone index"):
        chain.apply_endpoint(make_factor(target_index=len(space.zones)))

    updated = chain.apply_endpoint(make_factor())
    stay_probability = updated.assignment_probability(
        "hall-endpoint",
        lambda atom: atom.source_index is None,
    )
    assert 0.0 < stay_probability < 1.0
    assert updated.posterior.normalization == pytest.approx(1.0, abs=1e-12)


def test_factor_transition_validation_preserves_only_feasible_alternatives() -> None:
    space = StateSpace(("office", "hall"), 1)
    chain = ExactFactorChain(CompactLogPosterior.certain(space, (1, 0, 0)))

    with pytest.raises(IndexError, match="target zone index"):
        chain._factor_transitions(  # noqa: SLF001
            make_factor(target_index=len(space.zones)),
            space.rank((1, 0, 0)),
        )

    deadline = NOW + timedelta(seconds=30)

    def factor_with(alternative: EndpointAlternative) -> EndpointFactor:
        stay = EndpointAlternative(
            "stay:validation",
            "stay",
            None,
            None,
            (),
            math.log(0.4),
            deadline,
            (),
        )
        return EndpointFactor(
            EndpointToken("validation", "hall", NOW),
            1,
            "hall",
            (stay, alternative),
            math.log(0.2),
            math.log(0.9),
        )

    disabled = EndpointAlternative(
        "disabled",
        "graph_valid",
        0,
        "office",
        ("office", "hall"),
        -math.inf,
        deadline,
        (),
    )
    disabled_transitions = chain._factor_transitions(  # noqa: SLF001
        factor_with(disabled),
        space.rank((1, 0, 0)),
    )
    assert [
        alternative.alternative_id
        for alternative, _, _ in disabled_transitions
    ] == ["stay:validation"]

    invalid_source = EndpointAlternative(
        "invalid-source",
        "graph_valid",
        len(space.locations),
        "outside",
        ("outside", "hall"),
        0.0,
        deadline,
        (),
    )
    with pytest.raises(IndexError, match="source location index"):
        chain._factor_transitions(  # noqa: SLF001
            factor_with(invalid_source),
            space.rank((1, 0, 0)),
        )

    self_move = replace(
        invalid_source,
        alternative_id="self-move",
        source_index=1,
        source_node_id="hall",
        route_nodes=("hall", "hall"),
    )
    with pytest.raises(ValueError, match="source and target must differ"):
        chain._factor_transitions(  # noqa: SLF001
            factor_with(self_move),
            space.rank((1, 0, 0)),
        )

    empty_source = replace(
        invalid_source,
        alternative_id="empty-source",
        source_index=1,
        source_node_id="hall-source",
        route_nodes=("hall-source", "office"),
    )
    office_factor = replace(
        factor_with(empty_source),
        target_index=0,
        target_zone="office",
    )
    empty_source_transitions = chain._factor_transitions(  # noqa: SLF001
        office_factor,
        space.rank((1, 0, 0)),
    )
    assert [
        alternative.alternative_id
        for alternative, _, _ in empty_source_transitions
    ] == ["stay:validation"]


@pytest.mark.parametrize(
    ("activation", "release", "message"),
    (
        (-0.01, 0.95, "activation threshold"),
        (1.01, 0.95, "activation threshold"),
        (0.8, -0.01, "release threshold"),
        (0.8, 1.01, "release threshold"),
    ),
)
def test_policy_rejects_thresholds_outside_probability_domain(
    activation: float,
    release: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PosteriorEventPolicy(
            ("office",),
            activation_threshold=activation,
            release_threshold=release,
        )

    with pytest.raises(ValueError, match="activation window"):
        PosteriorEventPolicy(
            ("office",),
            activation_threshold=0.8,
            release_threshold=0.95,
            activation_window=timedelta(microseconds=-1),
        )


def test_policy_orders_release_before_arrival_without_reacquisition() -> None:
    policy = PosteriorEventPolicy(
        ("hall", "office"),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    policy.restore_states(
        {"hall": ZonePolicyState(), "office": ZonePolicyState(keep_on=True)}
    )

    retained = policy.apply(
        NOW,
        1,
        {"hall": 0.79, "unknown": 1.0},
        True,
        {"office": 0.949},
        emit_activation=False,
    )
    assert retained["office"].keep_on
    assert not retained["hall"].keep_on
    assert {decision.reason_code for decision in policy.last_decisions} == {
        "release_safe_not_met",
        "arrival_supported_not_met",
    }

    released = policy.apply(
        NOW + timedelta(seconds=1),
        1,
        {"office": 1.0},
        True,
        {"office": 0.95},
        emit_activation=True,
    )
    assert not released["office"].keep_on
    assert released["office"].last_release_cause is ReleaseCause.RELEASE_SAFE
    assert [decision.action for decision in policy.last_decisions] == ["release"]


def test_policy_restore_rejects_invalid_states_and_unordered_audit_atomically() -> None:
    policy = PosteriorEventPolicy(
        ("office", "hall"),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    original = policy.states

    with pytest.raises(ValueError, match="zones do not match"):
        policy.restore_states({"office": ZonePolicyState()})
    assert policy.states == original

    invalid_states: dict[str, Any] = {
        "office": ZonePolicyState(),
        "hall": object(),
    }
    with pytest.raises(ValueError, match="states are invalid"):
        policy.restore_states(invalid_states)
    assert policy.states == original

    decision = PolicyDecision("office", "activate", True, "test", {})
    later = PosteriorPolicyAuditEntry(NOW + timedelta(seconds=1), decision, False, True)
    earlier = PosteriorPolicyAuditEntry(NOW, decision, False, True)
    unknown = PosteriorPolicyAuditEntry(
        NOW,
        replace(decision, zone="unknown"),
        False,
        True,
    )
    with pytest.raises(ValueError, match="unknown zone"):
        policy.restore_audit((unknown,), NOW)
    with pytest.raises(ValueError, match="not ordered"):
        policy.restore_audit((later, earlier), NOW + timedelta(seconds=2))
    assert policy.audit == ()


def test_policy_reset_and_audit_bounds_clear_ownership_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = PosteriorEventPolicy(
        ("office", "hall"),
        activation_threshold=0.8,
        release_threshold=0.95,
    )
    policy.restore_states(
        {
            "office": ZonePolicyState(keep_on=True),
            "hall": ZonePolicyState(keep_on=True),
        }
    )
    monkeypatch.setattr(policy_module, "POLICY_AUDIT_MAX_ENTRIES", 1)

    states = policy.reset(NOW)

    assert all(not state.keep_on for state in states.values())
    assert all(
        state.last_release_cause is ReleaseCause.EXPLICIT_RESET
        for state in states.values()
    )
    assert len(policy.audit) == 1
    assert policy.audit[0].decision.reason_code == "explicit_reset"


def test_reducers_validate_space_identity_and_apply_both_emission_kinds() -> None:
    predictive_map = make_map()
    space = StateSpace(predictive_map.zones(), 1)
    other_space = StateSpace(predictive_map.zones(), 1)

    with pytest.raises(ValueError, match="zones must match"):
        AugmentedEventReducer(predictive_map, StateSpace(("wrong",), 1))
    with pytest.raises(ValueError, match="share a state space"):
        AugmentedEventReducer(
            predictive_map,
            space,
            CompleteMoveOperators(other_space),
        )

    explicit = AugmentedEventReducer(predictive_map, space)
    compact = FactorChainEventReducer(predictive_map, space)
    posterior = CompactLogPosterior.certain(space, (0, 0, 0, 0, 1))
    other_posterior = CompactLogPosterior.certain(other_space, (0, 0, 0, 0, 1))
    message = AugmentedLogMessage.from_posterior(posterior)
    episodes = ObservationEpisodes(predictive_map).states
    positive = EpisodeEmission(
        "office",
        "office",
        "office-episode",
        "office-evidence",
        "positive",
        math.log(0.02),
        math.log(0.97),
    )
    clear = replace(
        positive,
        kind="clear",
        empty_log_likelihood=math.log(0.95),
        occupied_log_likelihood=math.log(0.30),
    )

    endpoint_message = explicit._apply_emission(message, positive, NOW, episodes)  # noqa: SLF001
    cleared_message = explicit._apply_emission(message, clear, NOW, episodes)  # noqa: SLF001
    assert endpoint_message.has_endpoint("office-episode")
    assert not cleared_message.has_endpoint("office-episode")
    assert endpoint_message.normalization == pytest.approx(1.0)
    assert cleared_message.normalization == pytest.approx(1.0)

    with pytest.raises(ValueError, match="exact state space"):
        explicit.initial_state(other_posterior)
    wrong_explicit = InferenceReplayState(
        AugmentedLogMessage.from_posterior(other_posterior),
        episodes,
    )
    with pytest.raises(ValueError, match="reducer state space"):
        explicit.reduce(wrong_explicit, ())
    with pytest.raises(ValueError, match="reducer state space"):
        explicit.advance(wrong_explicit, NOW)

    with pytest.raises(ValueError, match="exact state space"):
        compact.initial_state(other_posterior)
    wrong_compact = FactorChainReplayState(ExactFactorChain(other_posterior), episodes)
    with pytest.raises(ValueError, match="reducer state space"):
        compact.reduce(wrong_compact, ())
    with pytest.raises(ValueError, match="reducer state space"):
        compact.advance(wrong_compact, NOW)

    compact_chain = ExactFactorChain(posterior)
    positive_chain = compact._apply_chain_emission(  # noqa: SLF001
        compact_chain,
        positive,
        NOW,
        episodes,
    )
    clear_chain = compact._apply_chain_emission(  # noqa: SLF001
        compact_chain,
        clear,
        NOW,
        episodes,
    )
    assert positive_chain.unresolved_endpoint_count == 1
    assert isinstance(clear_chain.steps[-1], ZoneLikelihoodStep)
    assert positive_chain.posterior.normalization == pytest.approx(1.0)
    assert clear_chain.posterior.normalization == pytest.approx(1.0)

    factor = compact._endpoint_builder._endpoint_factor(  # noqa: SLF001
        positive,
        NOW,
        episodes,
    )
    unlocated_assignment = EndpointAssignmentAtom(
        factor.endpoint.token_id,
        "unlocated:test",
        "graph_valid",
        space.rank((0, 0, 0, 0, 1)),
        space.rank((1, 0, 0, 0, 0)),
        space.unlocated_index,
        space.location_index("office"),
        "unlocated",
        "office",
        ("unlocated", "office"),
        NOW,
        ("office-evidence",),
    )
    assert compact._finalization_support(  # noqa: SLF001
        factor,
        unlocated_assignment,
        NOW,
        episodes,
    ) is None


def test_persisted_log_posterior_rejects_shape_finitude_and_mass_drift() -> None:
    space = StateSpace(("office",), 1)

    with pytest.raises(ValueError, match="dimension"):
        CompactLogPosterior.from_normalized(space, (0.0,))
    with pytest.raises(ValueError, match="finite or negative infinity"):
        CompactLogPosterior.from_normalized(space, (math.nan, -math.inf))
    with pytest.raises(ValueError, match="must be normalized"):
        CompactLogPosterior.from_normalized(
            space,
            (math.log(0.6), math.log(0.3)),
        )


@pytest.mark.parametrize("corrupt_probability", (-0.01, 1.01))
def test_injective_support_requires_distinct_evidence_and_guards_probability(
    monkeypatch: pytest.MonkeyPatch,
    corrupt_probability: float,
) -> None:
    space = StateSpace(("office", "hall"), 1)
    support = make_support()
    supported = AugmentedLogMessage(
        space,
        ((AugmentedStateKey(space.rank((0, 1, 0)), supports=(support,)), 0.0),),
    )
    unsupported = AugmentedLogMessage.from_posterior(
        CompactLogPosterior.certain(space, (0, 1, 0))
    )

    assert injective_support_probability(supported, "office", lambda _item: True) == 1.0
    assert (
        injective_support_probability(
            unsupported,
            "office",
            lambda _item: True,
        )
        == 0.0
    )

    monkeypatch.setattr(
        math,
        "fsum",
        lambda _values: corrupt_probability,
    )
    with pytest.raises(ValueError, match="probability is out of range"):
        injective_support_probability(supported, "office", lambda _item: True)


def test_snapshot_neutral_without_previous_evidence_is_idempotent() -> None:
    model = ObservationModel(1)
    event = make_event(state="unavailable")

    ignored = model.prepare_snapshot_delta(event)

    assert ignored.disposition == "ignored"
    assert ignored.log_likelihood_by_count == (0.0, 0.0)
    assert model.entity_states == {}


def test_prediction_finalized_support_paths_are_separate_from_invalid_learning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PredictionManager(make_map())
    valid = make_support()
    invalid = make_support(
        support_id="invalid",
        endpoint_id="invalid-endpoint",
        route_nodes=("office",),
    )

    leases = manager.apply_finalized_supports(
        ((invalid, 1.0), (valid, 0.8)),
        NOW,
    )
    assert {lease.target_zone: lease.probability for lease in leases} == {
        "kitchen": 0.4,
        "living": 0.4,
    }

    original_observe = manager.chain.observe
    monkeypatch.setattr(manager.chain, "observe", lambda *_args, **_kwargs: False)
    assert manager.learn_finalized_supports(((valid, 0.9),)) == ()
    monkeypatch.setattr(manager.chain, "observe", original_observe)

    assert manager.learn_finalized_supports(((invalid, 0.9),)) == ()
    assert manager.learn_finalized_supports(((valid, 0.9),)) == (("office", "hall"),)
    assert manager.chain.counts["office"]["hall"] == pytest.approx(0.9)


def test_prediction_single_continuation_and_route_context_learning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"zone": "office", "adjacent": ["hall"]},
                "hall": {"zone": "hall", "adjacent": ["office", "kitchen"]},
                "kitchen": {"zone": "kitchen", "adjacent": ["hall"]},
            }
        }
    )
    manager = PredictionManager(predictive_map)
    support = make_support()

    leases = manager.apply_finalized_supports(((support, 0.8),), NOW)

    assert len(leases) == 1
    assert leases[0].target_zone == "kitchen"
    assert leases[0].probability == pytest.approx(0.8)
    assert leases[0].reason == "only graph-valid forward continuation"

    invalid_edge = replace(
        support,
        support_event_id="invalid-edge",
        endpoint_ids=("invalid-edge",),
        route_nodes=("unknown", "hall"),
    )
    assert manager.learn_finalized_supports(((invalid_edge, 0.9),)) == ()

    monkeypatch.setattr(
        PredictionManager,
        "_compatible_route_contexts",
        lambda _manager, _source: (("kitchen", "hall", "office"),),
    )
    learned = manager.learn_finalized_supports(((support, 0.9),))

    assert learned == (("office", "hall"),)
    assert manager.route_counts
