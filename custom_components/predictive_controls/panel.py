from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .const import DOMAIN, NAME, VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_register_panel(hass: HomeAssistant) -> None:
    from homeassistant.components.frontend import async_register_built_in_panel
    from homeassistant.components.http import StaticPathConfig

    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=f"/{DOMAIN}/static",
                path=str(frontend_dir),
                cache_headers=False,
            )
        ]
    )
    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=NAME,
        sidebar_icon="mdi:transit-connection-variant",
        frontend_url_path=DOMAIN,
        config={
            "_panel_custom": {
                "name": "predictive-controls-panel",
                "embed_iframe": False,
                "trust_external": False,
                "js_url": f"/{DOMAIN}/static/panel.js?v={VERSION}",
            }
        },
        require_admin=True,
    )


async def async_unregister_panel(hass: HomeAssistant) -> None:
    try:
        from homeassistant.components.frontend import async_remove_panel
    except ImportError:
        return
    async_remove_panel(hass, DOMAIN)
