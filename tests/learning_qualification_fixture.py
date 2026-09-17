"""Synthetic input-only qualification for independent adjacent learning.

After original c36, three distinct witnessed steps from z fill recent history.
Original e37 then evicts current c from selected overlap; its independently
produced component token can qualify original t38. No inference state is edited.
Never add these synthetic observations to a captured incident or same-row donor.
"""

from dataclasses import replace
from datetime import datetime

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput

LEARNING_STEPS = ("learning_step_1", "learning_step_2", "learning_step_3")


def learning_qualification_map(model: PredictiveMap) -> PredictiveMap:
    """Add a real reciprocal branch without changing original edges/profiles."""
    assert not set(LEARNING_STEPS) & model.nodes.keys()
    nodes = dict(model.nodes)
    path = ("z", *LEARNING_STEPS)
    nodes["z"] = replace(nodes["z"], adjacent=(*nodes["z"].adjacent, path[1]))
    for index, node in enumerate(LEARNING_STEPS, 1):
        nodes[node] = replace(
            nodes["x"], node_id=node, zone=node,
            entities={"motion": f"binary_sensor.{node}"},
            adjacent=path[index - 1:index] + path[index + 1:index + 2],
        )
    return replace(model, nodes=nodes)


def learning_qualification_inputs(at: datetime) -> tuple[SensorInput, ...]:
    """Preserve c36, restore36 and e37/t38/u39; order these after c36."""
    return tuple(SensorInput(f"binary_sensor.{node}", "on", at)
                 for node in LEARNING_STEPS)
