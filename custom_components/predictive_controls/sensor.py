from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .automation_summary import runtime_automation_summary
from .const import DISPATCH_UPDATE, DOMAIN
from .runtime import PredictiveControlsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PredictiveControlsRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        NextNodeSensor(runtime, entry.entry_id),
        PredictedNextZoneSensor(runtime, entry.entry_id),
        ProbableInsideCountSensor(runtime, entry.entry_id),
        PossibleInsideCountSensor(runtime, entry.entry_id),
        ProbableOccupiedZonesSensor(runtime, entry.entry_id),
        PossibleOccupiedZonesSensor(runtime, entry.entry_id),
        MotionPlausibleZonesSensor(runtime, entry.entry_id),
        ActiveMovementCorridorSensor(runtime, entry.entry_id),
        OccupancyExplanationSensor(runtime, entry.entry_id),
    ]
    entities.extend(
        NodeProbabilitySensor(runtime, entry.entry_id, node_id)
        for node_id in runtime.map.nodes
    )
    entities.extend(
        ZoneConfidenceSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZoneStatusSensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    entities.extend(
        ZonePredictionProbabilitySensor(runtime, entry.entry_id, zone)
        for zone in runtime.map.zones()
    )
    async_add_entities(entities)


class RuntimeSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        self.runtime = runtime
        self.entry_id = entry_id

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DISPATCH_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class NextNodeSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="next_node",
        name="Predicted Next Node",
        icon="mdi:graph-outline",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_next_node"

    @property
    def native_value(self) -> str | None:
        prediction = self.runtime.last_prediction
        return prediction.node_id if prediction is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        prediction = self.runtime.last_prediction
        return {
            "probabilities": self.runtime.probabilities,
            "probability": prediction.probability if prediction is not None else None,
            "last_source_node": self.runtime.last_source_node,
        }


class PredictedNextZoneSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="predicted_next_zone",
        name="Predicted Next Zone",
        icon="mdi:map-marker-path",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_predicted_next_zone"

    @property
    def native_value(self) -> str | None:
        return runtime_automation_summary(self.runtime).predicted_next_zone

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "probability": summary.predicted_next_probability,
            "predicted_zones": list(summary.predicted_zones),
            "zone_probabilities": {
                zone: state.prediction_probability
                for zone, state in summary.zones.items()
                if state.prediction_probability > 0
            },
        }


class ProbableInsideCountSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="probable_inside_count",
        name="Probable Inside Count",
        icon="mdi:account-check-outline",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_probable_inside_count"

    @property
    def native_value(self) -> int:
        return runtime_automation_summary(self.runtime).probable_inside_count

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "expected_inside_count": summary.expected_inside_count,
            "probable_occupied_zones": list(summary.probable_occupied_zones),
        }


class PossibleInsideCountSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="possible_inside_count",
        name="Possible Inside Count",
        icon="mdi:account-question-outline",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_possible_inside_count"

    @property
    def native_value(self) -> int:
        return runtime_automation_summary(self.runtime).possible_inside_count

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        summary = runtime_automation_summary(self.runtime)
        return {
            "expected_inside_count": summary.expected_inside_count,
            "possible_occupied_zones": list(summary.possible_occupied_zones),
        }


class ZoneListSensor(RuntimeSensor):
    _attr_icon = "mdi:floor-plan"
    _attr_zone_attribute = "zones"

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_{self.entity_key}"
        self._attr_name = self.entity_name

    @property
    def native_value(self) -> int:
        return len(self.zones)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {self._attr_zone_attribute: list(self.zones)}

    @property
    def zones(self) -> tuple[str, ...]:
        raise NotImplementedError


class ProbableOccupiedZonesSensor(ZoneListSensor):
    entity_key = "probable_occupied_zones"
    entity_name = "Probable Occupied Zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).probable_occupied_zones


class PossibleOccupiedZonesSensor(ZoneListSensor):
    entity_key = "possible_occupied_zones"
    entity_name = "Possible Occupied Zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).possible_occupied_zones


class MotionPlausibleZonesSensor(ZoneListSensor):
    entity_key = "motion_plausible_zones"
    entity_name = "Motion Plausible Zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).motion_plausible_zones


class ActiveMovementCorridorSensor(ZoneListSensor):
    entity_key = "active_movement_corridor"
    entity_name = "Active Movement Corridor"
    _attr_zone_attribute = "corridor_zones"

    @property
    def zones(self) -> tuple[str, ...]:
        return runtime_automation_summary(self.runtime).active_movement_corridor


class OccupancyExplanationSensor(RuntimeSensor):
    entity_description = SensorEntityDescription(
        key="occupancy_explanation",
        name="Occupancy Explanation",
        icon="mdi:text-box-search-outline",
    )

    def __init__(self, runtime: PredictiveControlsRuntime, entry_id: str) -> None:
        super().__init__(runtime, entry_id)
        self._attr_unique_id = f"{entry_id}_occupancy_explanation"

    @property
    def native_value(self) -> str:
        return runtime_automation_summary(self.runtime).explanation


class NodeProbabilitySensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, node_id: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.node_id = node_id
        label = runtime.map.nodes[node_id].label
        self._attr_name = f"{label} Prediction Probability"
        self._attr_unique_id = f"{entry_id}_{node_id}_probability"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float:
        return round(self.runtime.probabilities.get(self.node_id, 0.0) * 100, 1)


class ZoneConfidenceSensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Confidence"
        self._attr_unique_id = f"{entry_id}_{zone}_confidence"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float:
        state = self.runtime.zone_states.get(self.zone)
        confidence = state.confidence if state is not None else 0.0
        return round(confidence * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.runtime.zone_states.get(self.zone)
        if state is None:
            return {"status": "rejected", "reason": "no evidence"}
        return {
            "status": state.status,
            "occupancy_behavior": state.occupancy_behavior,
            "active_since": state.active_since.isoformat()
            if state.active_since is not None
            else None,
            "last_evidence_at": state.last_evidence_at.isoformat()
            if state.last_evidence_at is not None
            else None,
            "last_clear_at": state.last_clear_at.isoformat()
            if state.last_clear_at is not None
            else None,
            "last_node_id": state.last_node_id,
            "reason": state.reason,
        }


class ZoneStatusSensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Status"
        self._attr_unique_id = f"{entry_id}_{zone}_status"

    @property
    def native_value(self) -> str:
        state = self.runtime.zone_states.get(self.zone)
        return state.status if state is not None else "rejected"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.runtime.zone_states.get(self.zone)
        if state is None:
            return {"confidence": 0.0, "reason": "no evidence"}
        return {
            "confidence": state.confidence,
            "occupancy_behavior": state.occupancy_behavior,
            "active_since": state.active_since.isoformat()
            if state.active_since is not None
            else None,
            "reason": state.reason,
            "last_node_id": state.last_node_id,
        }


class ZonePredictionProbabilitySensor(RuntimeSensor):
    def __init__(
        self, runtime: PredictiveControlsRuntime, entry_id: str, zone: str
    ) -> None:
        super().__init__(runtime, entry_id)
        self.zone = zone
        self._attr_name = f"{zone.replace('_', ' ').title()} Prediction Probability"
        self._attr_unique_id = f"{entry_id}_{zone}_zone_prediction_probability"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float:
        state = runtime_automation_summary(self.runtime).zones[self.zone]
        return round(state.prediction_probability * 100, 1)
