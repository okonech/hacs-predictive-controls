"""Synthetic history retirement; never add these inputs to recorded replays.

After A0/B1/C2/X3, genuine A/X generation changes fill the four-visit bound.
Equal-time delivery is intentional component qualification: it isolates real
authority retirement at3 without changing C's original calibration frontier,
presence, or likelihood. No sensor state, selection or policy is injected.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from custom_components.predictive_controls.model import NodeConfig, PredictiveMap
from custom_components.predictive_controls.zone_model.types import SensorInput


def retirement_inputs(
    at: datetime, *, pair: tuple[str, str] = ("a", "x"),
) -> tuple[SensorInput, ...]:
    """Keep the pair's endpoint while evicting the other still-ON generations."""
    return tuple(
        SensorInput(f"binary_sensor.{node}", state, at)
        for node in pair * 2
        for state in ("unavailable", "on")
    )


def retire_overlap(observe: Callable[[SensorInput], object], at: datetime) -> None:
    for event in retirement_inputs(at):
        observe(event)


def retired_prefix_map(mapping: PredictiveMap) -> PredictiveMap:
    """Add a two-edge observed branch for strict prefix-only retirement donors."""
    assert not {"retirement_inner", "retirement_tip"} & mapping.nodes.keys()
    return replace(mapping, nodes={
        **mapping.nodes,
        "c": replace(mapping.nodes["c"], adjacent=(
            *mapping.nodes["c"].adjacent, "retirement_inner",
        )),
        "retirement_inner": NodeConfig(
            "retirement_inner", "Retirement inner",
            {"mmwave": "binary_sensor.retirement_inner"},
            ("c", "retirement_tip"), occupancy_behavior="sustained",
        ),
        "retirement_tip": NodeConfig(
            "retirement_tip", "Retirement tip",
            {"mmwave": "binary_sensor.retirement_tip"},
            ("retirement_inner",), occupancy_behavior="sustained",
        ),
    })


def retired_prefix_inputs(start: datetime) -> tuple[SensorInput, ...]:
    """C stays ON: history eviction revokes it while a real prefix remembers it."""
    return tuple(SensorInput(f"binary_sensor.{node}", state,
                             start + timedelta(seconds=seconds))
                 for node, state, seconds in (
                     ("a", "on", 0), ("b", "on", 1), ("c", "on", 2),
                     ("retirement_inner", "on", 2.1),
                     ("retirement_tip", "on", 2.2),
                     ("a", "unavailable", 2.3), ("a", "on", 2.3),
                     ("x", "on", 3), ("retirement_inner", "unavailable", 3),
                 ))
