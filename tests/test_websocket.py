from __future__ import annotations

import pytest

from custom_components.predictive_controls.yaml_config import map_yaml_from_payload


def test_map_yaml_from_message_prefers_raw_yaml() -> None:
    raw_yaml = "nodes:\n  entry:\n    adjacent: []\n"

    assert map_yaml_from_payload(
        {"map": {"nodes": {}}, "map_yaml": raw_yaml}
    ) == raw_yaml


def test_map_yaml_from_message_dumps_map_when_raw_yaml_missing() -> None:
    map_yaml = map_yaml_from_payload(
        {"map": {"nodes": {"entry": {"adjacent": []}}}}
    )

    assert map_yaml.startswith("nodes:\n")
    assert "entry:" in map_yaml


def test_map_yaml_from_message_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="Either map or map_yaml is required"):
        map_yaml_from_payload({})
