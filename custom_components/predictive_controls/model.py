from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OCCUPANCY_BEHAVIORS = ("transient", "sustained", "sticky", "ambiguous")


class PredictiveMapError(ValueError):
    """Raised when a predictive map is invalid."""


@dataclass(frozen=True)
class EntityBinding:
    """Resolved entity binding from one predictive node."""

    node_id: str
    signal_type: str


def default_occupancy_behavior(role: str) -> str:
    if role == "transition_gate":
        return "transient"
    if role == "ambiguous_open_plan":
        return "ambiguous"
    if role == "anchor_sensor":
        return "sticky"
    return "sustained"


@dataclass(frozen=True)
class ZoneConfig:
    """Display and inference metadata for one occupancy zone."""

    zone_id: str
    role: str | None = None
    occupancy_behavior: str | None = None

    @classmethod
    def from_mapping(cls, zone_id: str, raw: Any) -> ZoneConfig:
        if not isinstance(raw, dict):
            raise PredictiveMapError(f"Zone {zone_id!r} must be a mapping")

        role = raw.get("role")
        if role is not None and (not isinstance(role, str) or not role):
            raise PredictiveMapError(f"Zone {zone_id!r} role must be a string")

        occupancy_behavior = raw.get("occupancy_behavior")
        if occupancy_behavior is not None:
            if occupancy_behavior not in OCCUPANCY_BEHAVIORS:
                joined = ", ".join(OCCUPANCY_BEHAVIORS)
                raise PredictiveMapError(
                    f"Zone {zone_id!r} occupancy_behavior must be one of: {joined}"
                )

        return cls(
            zone_id=zone_id,
            role=role,
            occupancy_behavior=occupancy_behavior,
        )


@dataclass(frozen=True)
class NodeConfig:
    """Configuration for one predictive node."""

    node_id: str
    label: str
    entities: dict[str, str] = field(default_factory=dict)
    adjacent: tuple[str, ...] = ()
    initial_weight: float = 1.0
    floor: str | None = None
    zone: str | None = None
    role: str = "room_occupancy"
    occupancy_behavior: str | None = None
    review_required: bool = False

    @classmethod
    def from_mapping(cls, node_id: str, raw: Any) -> NodeConfig:
        if not isinstance(raw, dict):
            raise PredictiveMapError(f"Node {node_id!r} must be a mapping")

        label = raw.get("label", node_id)
        if not isinstance(label, str) or not label:
            raise PredictiveMapError(
                f"Node {node_id!r} label must be a non-empty string"
            )

        entities = raw.get("entities", {})
        if not isinstance(entities, dict):
            raise PredictiveMapError(f"Node {node_id!r} entities must be a mapping")
        parsed_entities = {str(key): str(value) for key, value in entities.items()}

        adjacent = raw.get("adjacent", [])
        if not isinstance(adjacent, list):
            raise PredictiveMapError(f"Node {node_id!r} adjacent must be a list")
        parsed_adjacent = tuple(str(target) for target in adjacent)

        initial_weight = raw.get("initial_weight", raw.get("initial_reliability"))
        if initial_weight is None:
            initial_weight = 1.0
        try:
            parsed_weight = float(initial_weight)
        except (TypeError, ValueError) as exc:
            raise PredictiveMapError(
                f"Node {node_id!r} initial_weight must be numeric"
            ) from exc
        if parsed_weight <= 0:
            raise PredictiveMapError(
                f"Node {node_id!r} initial_weight must be positive"
            )

        floor = raw.get("floor")
        if floor is not None and not isinstance(floor, str):
            raise PredictiveMapError(f"Node {node_id!r} floor must be a string")

        zone = raw.get("zone")
        if zone is not None and not isinstance(zone, str):
            raise PredictiveMapError(f"Node {node_id!r} zone must be a string")

        role = raw.get("role", "room_occupancy")
        if not isinstance(role, str) or not role:
            raise PredictiveMapError(f"Node {node_id!r} role must be a string")

        occupancy_behavior = raw.get("occupancy_behavior")
        if occupancy_behavior is not None:
            if occupancy_behavior not in OCCUPANCY_BEHAVIORS:
                joined = ", ".join(OCCUPANCY_BEHAVIORS)
                raise PredictiveMapError(
                    f"Node {node_id!r} occupancy_behavior must be one of: {joined}"
                )

        review_required = raw.get("review_required", False)
        if not isinstance(review_required, bool):
            raise PredictiveMapError(
                f"Node {node_id!r} review_required must be a boolean"
            )

        return cls(
            node_id=node_id,
            label=label,
            entities=parsed_entities,
            adjacent=parsed_adjacent,
            initial_weight=parsed_weight,
            floor=floor,
            zone=zone,
            role=role,
            occupancy_behavior=occupancy_behavior,
            review_required=review_required,
        )

    @property
    def occupancy_zone(self) -> str:
        return self.zone or self.node_id


@dataclass(frozen=True)
class PredictiveMap:
    """Validated graph and entity mapping for predictive controls."""

    nodes: dict[str, NodeConfig]
    zone_configs: dict[str, ZoneConfig] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Any) -> PredictiveMap:
        if not isinstance(raw, dict):
            raise PredictiveMapError("Predictive map must be a mapping")

        raw_nodes = raw.get("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            raise PredictiveMapError("Predictive map must define at least one node")

        raw_zones = raw.get("zones", {})
        if raw_zones is None:
            raw_zones = {}
        if not isinstance(raw_zones, dict):
            raise PredictiveMapError("Predictive map zones must be a mapping")

        zone_configs = {
            str(zone_id): ZoneConfig.from_mapping(str(zone_id), zone_raw)
            for zone_id, zone_raw in raw_zones.items()
        }

        nodes = {
            str(node_id): NodeConfig.from_mapping(str(node_id), node_raw)
            for node_id, node_raw in raw_nodes.items()
        }
        unknown_targets = sorted(
            {
                target
                for node in nodes.values()
                for target in node.adjacent
                if target not in nodes
            }
        )
        if unknown_targets:
            joined = ", ".join(unknown_targets)
            raise PredictiveMapError(f"Adjacent nodes are not defined: {joined}")

        return cls(nodes=nodes, zone_configs=zone_configs)

    def node_for_entity(self, entity_id: str) -> str | None:
        binding = self.entity_binding_for_entity(entity_id)
        return binding.node_id if binding is not None else None

    def entity_binding_for_entity(self, entity_id: str) -> EntityBinding | None:
        for node in self.nodes.values():
            for signal_type, bound_entity_id in node.entities.items():
                if entity_id == bound_entity_id:
                    return EntityBinding(
                        node_id=node.node_id,
                        signal_type=signal_type,
                    )
        return None

    def entity_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                entity_id
                for node in self.nodes.values()
                for entity_id in node.entities.values()
            )
        )

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        node = self.nodes.get(node_id)
        return node.adjacent if node is not None else ()

    def zones(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *self.zone_configs,
                    *(node.occupancy_zone for node in self.nodes.values()),
                }
            )
        )

    def occupancy_behavior_for_node(self, node: NodeConfig) -> str:
        if node.occupancy_behavior is not None:
            return node.occupancy_behavior
        zone_config = self.zone_configs.get(node.occupancy_zone)
        if zone_config is not None and zone_config.occupancy_behavior is not None:
            return zone_config.occupancy_behavior
        role = (
            zone_config.role
            if zone_config is not None and zone_config.role
            else node.role
        )
        return default_occupancy_behavior(role)

    def zone_occupancy_behavior(self, zone: str) -> str:
        zone_config = self.zone_configs.get(zone)
        if zone_config is not None and zone_config.occupancy_behavior is not None:
            return zone_config.occupancy_behavior
        for node in self.nodes.values():
            if node.occupancy_zone == zone:
                return self.occupancy_behavior_for_node(node)
        return "sustained"
