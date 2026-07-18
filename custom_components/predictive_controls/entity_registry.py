from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .model import PredictiveMap

AGGREGATE_SENSOR_SUFFIXES = (
    "authoritative_occupant_count",
    "diagnostic_predicted_next_zone",
    "diagnostic_entry_path_plausible_zones",
)

AGGREGATE_BINARY_SENSOR_SUFFIXES = (
    "home_active",
    "predictive_controls_problem",
)

ZONE_SENSOR_SUFFIXES = (
    "authorization_reason",
    "diagnostic_confidence",
    "occupancy_probability",
    "release_dwell",
)

ZONE_BINARY_SENSOR_SUFFIXES = (
    "active",
    "prelight",
    "diagnostic_entry_path_plausible",
)

ZONE_EVENT_SUFFIXES = ("arrival",)

LEGACY_AGGREGATE_SUFFIXES = (
    "activation_plausible_zones",
    "keep_on_zones",
    "home_keep_on",
)

LEGACY_ZONE_SUFFIXES = (
    "activation_plausible",
    "arrival_supported_probability",
    "keep_on",
    "prelight_plausible",
    "release_safe_probability",
)


def expected_entity_unique_ids(
    entry_id: str,
    predictive_map: PredictiveMap,
) -> set[str]:
    """Return unique IDs currently provided by one config entry."""

    unique_ids = {f"{entry_id}_{suffix}" for suffix in AGGREGATE_SENSOR_SUFFIXES}
    unique_ids.update(
        f"{entry_id}_{suffix}" for suffix in AGGREGATE_BINARY_SENSOR_SUFFIXES
    )
    for zone in predictive_map.zones():
        unique_ids.update(
            f"{entry_id}_{zone}_{suffix}" for suffix in ZONE_SENSOR_SUFFIXES
        )
        unique_ids.update(
            f"{entry_id}_{zone}_{suffix}" for suffix in ZONE_BINARY_SENSOR_SUFFIXES
        )
        unique_ids.update(
            f"{entry_id}_{zone}_{suffix}" for suffix in ZONE_EVENT_SUFFIXES
        )
    return unique_ids


def stale_entity_registry_entries(
    entries: list[Any],
    config_entry_id: str,
    expected_unique_ids: set[str],
) -> list[Any]:
    """Return stale Predictive Controls entity-registry rows."""

    return [
        entry
        for entry in entries
        if getattr(entry, "platform", None) == DOMAIN
        and getattr(entry, "config_entry_id", None) == config_entry_id
        and getattr(entry, "unique_id", None) not in expected_unique_ids
    ]


async def async_remove_legacy_entities(
    hass: Any,
    entry_id: str,
    predictive_map: PredictiveMap,
) -> int:
    """Remove compatibility projections retired at the target cutover."""

    from homeassistant.helpers import entity_registry as er

    legacy_unique_ids = {f"{entry_id}_{suffix}" for suffix in LEGACY_AGGREGATE_SUFFIXES}
    for zone in predictive_map.zones():
        legacy_unique_ids.update(
            f"{entry_id}_{zone}_{suffix}" for suffix in LEGACY_ZONE_SUFFIXES
        )

    registry = er.async_get(hass)
    legacy_entries = [
        registry_entry
        for registry_entry in list(registry.entities.values())
        if getattr(registry_entry, "platform", None) == DOMAIN
        and getattr(registry_entry, "config_entry_id", None) == entry_id
        and getattr(registry_entry, "unique_id", None) in legacy_unique_ids
    ]
    for registry_entry in legacy_entries:
        registry.async_remove(registry_entry.entity_id)
    return len(legacy_entries)


async def async_cleanup_stale_entities(
    hass: Any,
    entry_id: str,
    predictive_map: PredictiveMap,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Remove stale registry rows for one Predictive Controls config entry."""

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    expected = expected_entity_unique_ids(entry_id, predictive_map)
    stale_entries = stale_entity_registry_entries(
        list(registry.entities.values()),
        entry_id,
        expected,
    )
    stale_payload = [entity_registry_entry_payload(entry) for entry in stale_entries]
    if not dry_run:
        for entry in stale_entries:
            registry.async_remove(entry.entity_id)
    return {
        "removed_count": 0 if dry_run else len(stale_entries),
        "removed_entities": [] if dry_run else stale_payload,
        "stale_count": len(stale_entries),
        "stale_entities": stale_payload,
        "expected_count": len(expected),
        "dry_run": dry_run,
    }


def entity_registry_entry_payload(entry: Any) -> dict[str, object]:
    return {
        "entity_id": getattr(entry, "entity_id", None),
        "unique_id": getattr(entry, "unique_id", None),
        "name": getattr(entry, "name", None),
        "original_name": getattr(entry, "original_name", None),
    }
