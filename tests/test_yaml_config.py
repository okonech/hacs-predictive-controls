from __future__ import annotations

import pytest

from custom_components.predictive_controls.yaml_config import (
    DEFAULT_ACTIONS_YAML,
    DEFAULT_MAP_YAML,
    dump_yaml_document,
    load_predictive_actions,
    load_predictive_map,
    load_yaml_document,
)


def test_default_yaml_documents_are_valid_and_generic() -> None:
    predictive_map = load_predictive_map(DEFAULT_MAP_YAML)
    actions = load_predictive_actions(DEFAULT_ACTIONS_YAML)

    assert sorted(predictive_map.nodes) == ["entry", "hallway", "kitchen"]
    assert actions[0].call.service == "light.turn_on"


def test_empty_yaml_document_loads_as_mapping() -> None:
    assert load_yaml_document("") == {}


def test_invalid_yaml_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_yaml_document("nodes:\n  entry\n    adjacent: []\n")


def test_dump_yaml_document_preserves_key_order() -> None:
    dumped = dump_yaml_document({"nodes": {"entry": {"adjacent": ["hall"]}}})

    assert dumped.startswith("nodes:\n")
    assert "adjacent:\n    - hall" in dumped

