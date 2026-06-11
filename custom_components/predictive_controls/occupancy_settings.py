from __future__ import annotations


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
