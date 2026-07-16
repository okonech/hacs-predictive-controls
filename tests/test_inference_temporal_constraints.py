from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.predictive_controls.inference.association import (
    DifferenceBoundMatrix,
)
from custom_components.predictive_controls.inference.types import (
    DifferenceConstraint,
    TemporalInterval,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 7, 20, 12, 0, 0, 123456, tzinfo=UTC)


def test_fixed_intervals_and_transitive_closure_are_exact() -> None:
    matrix = DifferenceBoundMatrix.solve(
        ("target", "source", "gate"),
        (
            TemporalInterval("source", NOW, NOW),
            TemporalInterval(
                "gate",
                NOW + timedelta(seconds=1),
                NOW + timedelta(seconds=4),
            ),
            TemporalInterval(
                "target",
                NOW + timedelta(seconds=2),
                NOW + timedelta(seconds=20),
            ),
        ),
        (
            DifferenceConstraint("gate", "source", timedelta(seconds=3)),
            DifferenceConstraint("target", "gate", timedelta(seconds=5)),
        ),
    )

    assert matrix is not None
    assert matrix.variables == ("gate", "source", "target")
    assert matrix.lower_bound("target") == NOW + timedelta(seconds=2)
    assert matrix.upper_bound("target") == NOW + timedelta(seconds=8)
    assert matrix.maximum_difference("target", "source") == timedelta(seconds=8)


def test_multiple_intervals_and_duplicate_constraints_choose_tightest_bounds() -> None:
    matrix = DifferenceBoundMatrix.solve(
        ("event", "origin"),
        (
            TemporalInterval("origin", NOW, NOW),
            TemporalInterval(
                "event",
                NOW - timedelta(seconds=1),
                NOW + timedelta(seconds=10),
            ),
            TemporalInterval(
                "event",
                NOW + timedelta(seconds=2),
                NOW + timedelta(seconds=8),
            ),
        ),
        (
            DifferenceConstraint("event", "origin", timedelta(seconds=7)),
            DifferenceConstraint("event", "origin", timedelta(seconds=5)),
            DifferenceConstraint("event", "origin", timedelta(seconds=6)),
        ),
    )

    assert matrix is not None
    assert matrix.lower_bound("event") == NOW + timedelta(seconds=2)
    assert matrix.upper_bound("event") == NOW + timedelta(seconds=5)


def test_strict_and_non_strict_order_use_microsecond_precision() -> None:
    equal_intervals = (
        TemporalInterval("earlier", NOW, NOW),
        TemporalInterval("later", NOW, NOW),
    )

    assert DifferenceBoundMatrix.solve(
        ("earlier", "later"),
        equal_intervals,
        (DifferenceConstraint("earlier", "later", timedelta(0)),),
    ) is not None
    assert DifferenceBoundMatrix.solve(
        ("earlier", "later"),
        equal_intervals,
        (
            DifferenceConstraint(
                "earlier",
                "later",
                timedelta(microseconds=-1),
            ),
        ),
    ) is None


def test_negative_cycle_and_disconnected_variable() -> None:
    assert DifferenceBoundMatrix.solve(
        ("alpha", "beta"),
        constraints=(
            DifferenceConstraint("alpha", "beta", timedelta(seconds=-1)),
            DifferenceConstraint("beta", "alpha", timedelta(0)),
        ),
    ) is None

    matrix = DifferenceBoundMatrix.solve(("bounded", "free"), (
        TemporalInterval("bounded", NOW, NOW + timedelta(seconds=1)),
    ))
    assert matrix is not None
    assert matrix.lower_bound("free") is None
    assert matrix.upper_bound("free") is None
    assert matrix.maximum_difference("free", "bounded") is None


def test_solver_is_deterministic_under_input_permutations() -> None:
    intervals = (
        TemporalInterval("alpha", NOW, NOW + timedelta(seconds=10)),
        TemporalInterval("beta", NOW, NOW + timedelta(seconds=10)),
    )
    constraints = (
        DifferenceConstraint("beta", "alpha", timedelta(seconds=4)),
        DifferenceConstraint("alpha", "beta", timedelta(seconds=2)),
    )

    first = DifferenceBoundMatrix.solve(
        ("beta", "alpha"),
        intervals,
        constraints,
    )
    second = DifferenceBoundMatrix.solve(
        ("alpha", "beta"),
        tuple(reversed(intervals)),
        tuple(reversed(constraints)),
    )

    assert first is not None
    assert second is not None
    assert first.variables == second.variables
    for variable in first.variables:
        assert first.lower_bound(variable) == second.lower_bound(variable)
        assert first.upper_bound(variable) == second.upper_bound(variable)
    assert first.maximum_difference("beta", "alpha") == second.maximum_difference(
        "beta",
        "alpha",
    )


@pytest.mark.parametrize(
    "value",
    (
        datetime(1901, 12, 13, 20, 45, 52, 654321, tzinfo=UTC),
        EPOCH,
        datetime(9998, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    ),
)
def test_datetime_bounds_round_trip_exactly(value: datetime) -> None:
    matrix = DifferenceBoundMatrix.solve(
        ("event",),
        (TemporalInterval("event", value, value),),
    )

    assert matrix is not None
    assert matrix.lower_bound("event") == value
    assert matrix.upper_bound("event") == value


def test_temporal_type_validation() -> None:
    naive = datetime(2026, 7, 20)
    non_utc = NOW.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValueError, match="non-empty"):
        TemporalInterval("", NOW, NOW)
    with pytest.raises(ValueError, match="UTC"):
        TemporalInterval("event", naive, NOW)
    with pytest.raises(ValueError, match="UTC"):
        TemporalInterval("event", NOW, non_utc)
    with pytest.raises(ValueError, match="must not exceed"):
        TemporalInterval("event", NOW, NOW - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="non-empty"):
        DifferenceConstraint("", "event", timedelta(0))
    with pytest.raises(ValueError, match="non-empty"):
        DifferenceConstraint("event", "", timedelta(0))


def test_solver_and_query_validation() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        DifferenceBoundMatrix.solve(("",))
    with pytest.raises(ValueError, match="reserved"):
        DifferenceBoundMatrix.solve(("__zero_clock__",))
    with pytest.raises(ValueError, match="unique"):
        DifferenceBoundMatrix.solve(("event", "event"))
    with pytest.raises(ValueError, match="undeclared variable: missing"):
        DifferenceBoundMatrix.solve(
            ("event",),
            (TemporalInterval("missing", NOW, NOW),),
        )
    with pytest.raises(ValueError, match="undeclared variable: missing"):
        DifferenceBoundMatrix.solve(
            ("event",),
            constraints=(
                DifferenceConstraint("event", "missing", timedelta(0)),
            ),
        )

    matrix = DifferenceBoundMatrix.solve(("event",))
    assert matrix is not None
    with pytest.raises(KeyError, match="Undeclared"):
        matrix.upper_bound("missing")
    with pytest.raises(KeyError, match="Undeclared"):
        matrix.lower_bound("missing")
    with pytest.raises(KeyError, match="Undeclared"):
        matrix.maximum_difference("event", "missing")
