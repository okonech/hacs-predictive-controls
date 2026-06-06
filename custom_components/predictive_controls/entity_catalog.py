from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MOTION_DEVICE_CLASSES = {"motion", "occupancy", "presence"}
ENTITY_ID_HINTS = (
    "motion",
    "occupancy",
    "presence",
    "mmwave",
    "radar",
    "target",
)


@dataclass(frozen=True)
class EntityCandidate:
    entity_id: str
    name: str
    state: str
    device_class: str | None


def is_motion_candidate(entity_id: str, attributes: dict[str, Any]) -> bool:
    domain = entity_id.split(".", 1)[0]
    if domain != "binary_sensor":
        return False

    device_class = attributes.get("device_class")
    if isinstance(device_class, str) and device_class in MOTION_DEVICE_CLASSES:
        return True

    lowered_entity_id = entity_id.lower()
    return any(hint in lowered_entity_id for hint in ENTITY_ID_HINTS)


def candidate_from_state(state: Any) -> EntityCandidate | None:
    entity_id = str(getattr(state, "entity_id", ""))
    attributes = getattr(state, "attributes", {})
    if not isinstance(attributes, dict) or not is_motion_candidate(
        entity_id, attributes
    ):
        return None

    friendly_name = attributes.get("friendly_name")
    device_class = attributes.get("device_class")
    return EntityCandidate(
        entity_id=entity_id,
        name=friendly_name if isinstance(friendly_name, str) else entity_id,
        state=str(getattr(state, "state", "unknown")),
        device_class=device_class if isinstance(device_class, str) else None,
    )


def serialize_candidates(states: list[Any]) -> list[dict[str, str | None]]:
    candidates = [candidate_from_state(state) for state in states]
    return [
        {
            "entity_id": candidate.entity_id,
            "name": candidate.name,
            "state": candidate.state,
            "device_class": candidate.device_class,
        }
        for candidate in sorted(
            (candidate for candidate in candidates if candidate is not None),
            key=lambda item: item.entity_id,
        )
    ]
