from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PredictiveMapError(ValueError):
    """Raised when a predictive map is invalid."""


@dataclass(frozen=True)
class NodeConfig:
    """Configuration for one predictive node."""

    node_id: str
    label: str
    entities: dict[str, str] = field(default_factory=dict)
    adjacent: tuple[str, ...] = ()
    initial_weight: float = 1.0

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

        return cls(
            node_id=node_id,
            label=label,
            entities=parsed_entities,
            adjacent=parsed_adjacent,
            initial_weight=parsed_weight,
        )


@dataclass(frozen=True)
class PredictiveMap:
    """Validated graph and entity mapping for predictive controls."""

    nodes: dict[str, NodeConfig]

    @classmethod
    def from_mapping(cls, raw: Any) -> PredictiveMap:
        if not isinstance(raw, dict):
            raise PredictiveMapError("Predictive map must be a mapping")

        raw_nodes = raw.get("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            raise PredictiveMapError("Predictive map must define at least one node")

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

        return cls(nodes=nodes)

    def node_for_entity(self, entity_id: str) -> str | None:
        for node in self.nodes.values():
            if entity_id in node.entities.values():
                return node.node_id
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
