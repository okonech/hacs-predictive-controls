from __future__ import annotations

from decimal import Decimal, InvalidOperation


def authoritative_occupants_from_state_value(value: object) -> int | None:
    """Parse an authoritative occupant count without coercing invalid input."""

    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"home", "on", "true", "yes"}:
        return 1
    if text in {"not_home", "off", "false", "no", "away"}:
        return 0
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return None
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        return None
    count = int(numeric)
    return count if 0 <= count <= 5 else None


def expected_occupants_from_state_value(value: object, fallback: int) -> int:
    """Resolve an expected occupant count from a Home Assistant state value."""

    fallback_count = max(0, int(fallback))
    if value is None:
        return fallback_count

    text = str(value).strip().lower()
    if not text or text in {"unknown", "unavailable", "none"}:
        return fallback_count
    if text in {"home", "on", "true", "yes"}:
        return 1
    if text in {"not_home", "off", "false", "no", "away"}:
        return 0

    try:
        count = int(float(text))
    except ValueError:
        return fallback_count
    return max(0, count)


def tracked_entity_ids(
    map_entity_ids: tuple[str, ...], expected_occupants_entity: str | None
) -> tuple[str, ...]:
    """Return map entities plus the optional expected-occupants helper entity."""

    entity_ids = {*map_entity_ids}
    helper_entity = (expected_occupants_entity or "").strip()
    if helper_entity:
        entity_ids.add(helper_entity)
    return tuple(sorted(entity_ids))
