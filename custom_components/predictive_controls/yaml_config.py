from __future__ import annotations

from typing import Any

import yaml

from .actions import PredictiveAction, parse_actions
from .model import PredictiveMap

DEFAULT_MAP_YAML = """nodes:
  entry:
    label: Entry
    entities:
      motion: binary_sensor.example_entry_motion
    adjacent:
      - hallway
  hallway:
    label: Hallway
    entities:
      motion: binary_sensor.example_hallway_motion
    adjacent:
      - entry
      - kitchen
  kitchen:
    label: Kitchen
    entities:
      motion: binary_sensor.example_kitchen_motion
    adjacent:
      - hallway
"""

DEFAULT_ACTIONS_YAML = """actions:
  prelight_kitchen:
    when:
      predicted_node: kitchen
      min_probability: 0.6
      cooldown_seconds: 300
    call:
      service: light.turn_on
      target:
        entity_id: light.example_kitchen
      data:
        brightness_pct: 35
"""


def load_yaml_document(text: str) -> Any:
    loaded = yaml.safe_load(text)
    return {} if loaded is None else loaded


def dump_yaml_document(data: Any) -> str:
  return str(yaml.safe_dump(data, sort_keys=False))


def map_yaml_from_payload(payload: dict[str, Any]) -> str:
  if "map_yaml" in payload and payload["map_yaml"].strip():
    return str(payload["map_yaml"])
  if "map" in payload:
    return dump_yaml_document(payload["map"])
  raise ValueError("Either map or map_yaml is required")


def load_predictive_map(text: str) -> PredictiveMap:
    return PredictiveMap.from_mapping(load_yaml_document(text))


def load_predictive_actions(text: str) -> tuple[PredictiveAction, ...]:
    return parse_actions(load_yaml_document(text))
