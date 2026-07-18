from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DISPATCH_UPDATE, DOMAIN
from .runtime import PredictiveControlsRuntime
from .zone_model.types import PolicyEvent


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ZoneArrivalEvent(runtime, entry.entry_id, zone) for zone in runtime.map.zones()
    )


class ZoneArrivalEvent(EventEntity):
    """Project accepted distinct target arrival episodes."""

    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False
    _attr_event_types = ["acquired", "refreshed"]

    def __init__(
        self,
        runtime: PredictiveControlsRuntime,
        entry_id: str,
        zone: str,
    ) -> None:
        self.runtime = runtime
        self.zone = zone
        self._seen_episode_ids: set[str] = set()
        self._attr_name = f"{zone.replace('_', ' ').title()} Arrival"
        self._attr_unique_id = f"{entry_id}_{zone}_arrival"

    async def async_added_to_hass(self) -> None:
        self._project_decisions(emit=False)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self._project_decisions(emit=True)
        self.async_write_ha_state()

    def _project_decisions(self, *, emit: bool) -> None:
        for event in self.runtime.confidence.diagnostics.policy_events:
            if event.zone != self.zone or event.kind == "released":
                continue
            episode_id = event.episode_id
            if episode_id is None or episode_id in self._seen_episode_ids:
                continue
            self._seen_episode_ids.add(episode_id)
            if emit:
                self._trigger_event(event.kind, self._event_payload(event))

    def _event_payload(self, event: PolicyEvent) -> dict[str, object]:
        return {
            "zone": event.zone,
            "episode_id": event.episode_id,
            "accepted_at": event.event_at.isoformat(),
            "belief": event.belief,
            "authorization_reason": event.authorization_reason,
            "policy_reason": event.policy_reason,
        }
