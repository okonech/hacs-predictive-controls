from __future__ import annotations

from custom_components.predictive_controls.panel import panel_js_url


def test_panel_js_url_is_versioned() -> None:
    assert panel_js_url() == "/predictive_controls/static/panel-v0.1.16.js"
