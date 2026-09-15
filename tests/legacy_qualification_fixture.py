"""Named component probes for relocated scalar and donor qualifications.

Not an engine, replacement reader, or historical-capture reconstruction. The
selected runtime is tested separately. All validation and inference arithmetic
below belongs to existing production components; the independent prediction
payload is preserved rather than deleting grants to make restore succeed.
"""

from __future__ import annotations

from dataclasses import asdict

from custom_components.predictive_controls.zone_model.persistence import _json_value
from custom_components.predictive_controls.zone_model.types import (
    SensorInput,
    ZoneModelResult,
    ZoneModelSnapshot,
)
from tests.persistence_component_fixture import (
    PersistenceComponents,
    component_wire,
    restore_components,
)


def restore_qualification(
    components: PersistenceComponents,
    snapshot: ZoneModelSnapshot | None = None,
) -> PersistenceComponents:
    """Real field codecs/cross-links; explicitly NOT current-engine acceptance."""
    components.commit_prediction_learning()
    payload = component_wire(components.predictive_map, components)
    if snapshot is not None:
        payload["snapshot"] = _json_value(asdict(snapshot))
    return restore_components(
        components.predictive_map, payload, components.updated_at,
    )


def correlated_policy_probe(
    components: PersistenceComponents, event: SensorInput,
) -> ZoneModelResult:
    """TRAV014's unbound target-only filter/frontier/policy transaction.

    This probe deliberately has no support-backed continuation to issue, and
    never submits correlated evidence as a prediction source. Independent
    diagnostic leases remain intact; this is not selected lease confirmation.
    """
    components.advance(event.event_at, emit_events=False)
    update = components.episodes.observe(event)
    effect, = update.effects
    assert effect.kind == "correlated_positive"
    belief = components.filters[effect.zone]
    belief.apply_correlated_positive(
        effect.episode_id, effect.at, effect.reliability,
    )
    authorization = components.frontier.authorize_correlated_target(
        update.state, effect.at,
    )
    assert authorization.authorized
    assert not components.supports.has_transfer_authority(authorization)
    assert authorization.settled_handoff is None
    belief.apply_arrival_transition(effect.episode_id, effect.at)
    components.frontier.sync(update.state, effect.at)
    decisions, events = components._policies(
        effect.at, state=update.state, effect=effect, authorization=authorization,
    )
    return ZoneModelResult(
        update.disposition, components.snapshot, events, decisions, (authorization,),
    )
