"""DIAG007 presentation amendment: labels cannot change diagnostic authority."""

from copy import deepcopy

import pytest

from custom_components.predictive_controls.status import reliability_warning_summary


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize(
    ("kind", "reasons", "label"),
    [
        ("suspected_stuck", ["assertion_timeout"],
         "Continuous presence detected; path unverified"),
        ("suspected_stuck", ["assertion_timeout", "count_conflict"],
         "suspected stuck"),
        ("suspected_stuck", ["count_conflict"], "suspected stuck"),
        ("flapping", ["impossible_cadence"], "flapping"),
        ("unsupported_jump", ["missing_intermediate"], "unsupported jump"),
    ],
)
def test_warning_description_preserves_diagnostic_rows(
    active: bool, kind: str, reasons: list[str], label: str,
) -> None:
    rows: list[dict[str, object]] = [
        {"zone": "room", "kind": kind, "reasons": reasons, "active": active},
    ]
    before = deepcopy(rows)
    suffix = " (active)" if active else ""
    assert reliability_warning_summary(rows) == (
        f"room: {label} [{', '.join(reasons)}]{suffix}"
    )
    assert rows == before
