from __future__ import annotations

import asyncio
import builtins
from collections.abc import Mapping, Sequence

import pytest

from custom_components.predictive_controls.panel import (
    async_unregister_panel,
    panel_js_url,
)


def test_panel_js_url_is_versioned() -> None:
    assert panel_js_url() == "/predictive_controls/static/panel-v0.1.19.js"


def test_panel_unregister_supports_home_assistant_without_frontend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def import_without_frontend(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "homeassistant.components.frontend":
            raise ImportError
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_frontend)
    asyncio.run(async_unregister_panel(object()))
