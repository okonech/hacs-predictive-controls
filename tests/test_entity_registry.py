from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from custom_components.predictive_controls.entity_registry import (
    async_cleanup_stale_entities,
    expected_entity_unique_ids,
    stale_entity_registry_entries,
)
from custom_components.predictive_controls.model import PredictiveMap


@dataclass(frozen=True)
class FakeRegistryEntry:
    entity_id: str
    unique_id: str | None
    platform: str = "predictive_controls"
    config_entry_id: str = "entry123"
    name: str | None = None
    original_name: str | None = None


class FakeRegistry:
    def __init__(self, entries: list[FakeRegistryEntry]) -> None:
        self.entities = {entry.entity_id: entry for entry in entries}
        self.removed: list[str] = []

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "living_motion": {
                    "zone": "living_room",
                    "adjacent": ["kitchen_motion"],
                },
                "kitchen_motion": {
                    "zone": "kitchen",
                    "adjacent": ["living_motion"],
                },
            }
        }
    )


def test_expected_entity_unique_ids_cover_automation_facing_entities() -> None:
    unique_ids = expected_entity_unique_ids("entry123", make_map())

    assert "entry123_predicted_next_zone" in unique_ids
    assert "entry123_probable_inside_count" in unique_ids
    assert "entry123_possible_inside_count" in unique_ids
    assert "entry123_probable_occupied_zones" in unique_ids
    assert "entry123_possible_occupied_zones" in unique_ids
    assert "entry123_home_probable_occupancy" in unique_ids
    assert "entry123_living_room_confidence" in unique_ids
    assert "entry123_living_room_probable_occupancy" in unique_ids
    assert "entry123_living_room_possible_occupancy" in unique_ids
    assert "entry123_living_room_zone_predicted_next" in unique_ids
    assert "entry123_living_motion_probability" not in unique_ids
    assert "entry123_living_motion_predicted" not in unique_ids
    assert "entry123_living_room_status" not in unique_ids
    assert "entry123_living_room_motion_plausible" not in unique_ids
    assert "entry123_living_room_zone_prediction_probability" not in unique_ids


def test_stale_entries_only_include_this_integration_and_config_entry() -> None:
    expected = expected_entity_unique_ids("entry123", make_map())

    entries = [
        FakeRegistryEntry(
            entity_id="sensor.living_room_confidence",
            unique_id="entry123_living_room_confidence",
        ),
        FakeRegistryEntry(
            entity_id="sensor.entry_prediction_probability",
            unique_id="entry123_entry_probability",
        ),
        FakeRegistryEntry(
            entity_id="sensor.living_room_status",
            unique_id="entry123_living_room_status",
        ),
        FakeRegistryEntry(
            entity_id="binary_sensor.living_room_motion_plausible",
            unique_id="entry123_living_room_motion_plausible",
        ),
        FakeRegistryEntry(
            entity_id="binary_sensor.living_motion_predicted",
            unique_id="entry123_living_motion_predicted",
        ),
        FakeRegistryEntry(
            entity_id="sensor.foreign_stale",
            unique_id="other_entry_entry_probability",
            config_entry_id="other_entry",
        ),
        FakeRegistryEntry(
            entity_id="sensor.other_integration",
            unique_id="entry123_entry_probability",
            platform="other",
        ),
    ]

    stale_entries = stale_entity_registry_entries(entries, "entry123", expected)

    assert [entry.entity_id for entry in stale_entries] == [
        "sensor.entry_prediction_probability",
        "sensor.living_room_status",
        "binary_sensor.living_room_motion_plausible",
        "binary_sensor.living_motion_predicted",
    ]


def test_async_cleanup_stale_entities_removes_only_obsolete_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(
        [
            FakeRegistryEntry(
                entity_id="sensor.living_room_confidence",
                unique_id="entry123_living_room_confidence",
            ),
            FakeRegistryEntry(
                entity_id="sensor.entry_prediction_probability",
                unique_id="entry123_entry_probability",
                name="Entry Prediction Probability",
                original_name="Entry Prediction Probability",
            ),
        ]
    )
    install_fake_entity_registry(monkeypatch, registry)

    result = asyncio.run(
        async_cleanup_stale_entities(object(), "entry123", make_map())
    )

    assert registry.removed == ["sensor.entry_prediction_probability"]
    assert result == {
        "removed_count": 1,
        "removed_entities": [
            {
                "entity_id": "sensor.entry_prediction_probability",
                "unique_id": "entry123_entry_probability",
                "name": "Entry Prediction Probability",
                "original_name": "Entry Prediction Probability",
            }
        ],
        "stale_count": 1,
        "stale_entities": [
            {
                "entity_id": "sensor.entry_prediction_probability",
                "unique_id": "entry123_entry_probability",
                "name": "Entry Prediction Probability",
                "original_name": "Entry Prediction Probability",
            }
        ],
        "expected_count": len(expected_entity_unique_ids("entry123", make_map())),
        "dry_run": False,
    }


def test_async_cleanup_stale_entities_can_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(
        [
            FakeRegistryEntry(
                entity_id="sensor.entry_prediction_probability",
                unique_id="entry123_entry_probability",
            ),
        ]
    )
    install_fake_entity_registry(monkeypatch, registry)

    result = asyncio.run(
        async_cleanup_stale_entities(
            object(),
            "entry123",
            make_map(),
            dry_run=True,
        )
    )

    assert registry.removed == []
    assert result["removed_count"] == 0
    assert result["removed_entities"] == []
    assert result["stale_count"] == 1
    assert result["dry_run"] is True


def install_fake_entity_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry: FakeRegistry,
) -> None:
    def async_get(hass: object) -> FakeRegistry:
        return registry

    fake_entity_registry = SimpleNamespace(async_get=async_get)
    fake_helpers = SimpleNamespace(entity_registry=fake_entity_registry)
    fake_homeassistant = SimpleNamespace(helpers=fake_helpers)
    monkeypatch.setitem(sys.modules, "homeassistant", fake_homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", fake_helpers)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        fake_entity_registry,
    )
