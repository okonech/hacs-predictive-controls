from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DISPATCH_UPDATE, DOMAIN
from .occupancy_state import PolicyDecision
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ZoneArrivalEvent(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
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
        for decision in self.runtime.confidence.diagnostics.joint_policy_decisions:
            event_type = self._event_type(decision)
            if event_type is None:
                continue
            for episode_id in decision.evidence_ids:
                if episode_id in self._seen_episode_ids:
                    continue
                self._seen_episode_ids.add(episode_id)
                if emit:
                    self._trigger_event(
                        event_type,
                        {
                            "zone": self.zone,
                            "episode_id": episode_id,
                            "arrival_supported_probability": decision.gate_values.get(
                                "probability"
                            ),
                            "accepted_at": (
                                None
                                if self.runtime.last_occupancy_event is None
                                    else (
                                        self.runtime.last_occupancy_event.event_at
                                        .isoformat()
                                    )
                            ),
                            "reason": decision.reason_code,
                        },
                    )

    def _event_type(self, decision: PolicyDecision) -> str | None:
        if decision.zone != self.zone or decision.action != "activate":
            return None
        if decision.accepted and decision.reason_code == "arrival_supported":
            return "acquired"
        if not decision.accepted and decision.reason_code == "already_active":
            return "refreshed"
        return None
