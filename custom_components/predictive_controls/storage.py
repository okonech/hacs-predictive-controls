from __future__ import annotations

from typing import Any

from homeassistant.helpers.storage import Store


class PredictiveControlsStore(Store):
    """Persist inference state across supported Predictive Controls schemas."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        del old_minor_version
        if old_major_version not in {1, 2, 3, 4}:
            raise NotImplementedError
        return old_data
