from __future__ import annotations

from typing import Any

from homeassistant.helpers.storage import Store

_DEVELOPMENT_EXACT_SCHEMA = "prototype-augmented-v5"
_LEGACY_EXACT_SCHEMA = "exact-augmented-v6"


class PredictiveControlsStore(Store):
    """Persist zone-belief state across schema-6, v2, and v3 cutovers."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        del old_minor_version
        if old_major_version not in {1, 2, 3, 4, 5, 6}:
            raise NotImplementedError
        if (
            old_major_version == 5
            and old_data.get("schema") == _DEVELOPMENT_EXACT_SCHEMA
        ):
            return {**old_data, "schema": _LEGACY_EXACT_SCHEMA}
        return old_data
