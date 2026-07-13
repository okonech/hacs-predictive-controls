from __future__ import annotations

from typing import Any, cast

import pytest

from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.route_model import RouteModel


def make_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "office": {"adjacent": ["hall"]},
                "hall": {"adjacent": ["office", "kitchen", "living"]},
                "kitchen": {"adjacent": ["hall"]},
                "living": {"adjacent": ["hall"]},
            }
        }
    )


def test_route_model_promotes_longest_prefix_and_backs_off() -> None:
    model = RouteModel(make_map(), minimum_support=2.0, decay=1.0)
    history = ("kitchen", "hall", "office", "hall")
    for _ in range(3):
        assert model.observe(history, "kitchen", weight=1.0)

    longest = model.match(history, ("kitchen", "living"))
    shorter = model.match(("office", "hall"), ("kitchen", "living"))
    fallback = model.match(("living", "hall"), ("kitchen", "living"))

    assert longest.matched_prefix == history
    assert longest.support == 3.0
    assert longest.backoff_level == 0
    assert longest.probabilities == {"kitchen": 1.0}
    assert shorter.matched_prefix == ("office", "hall")
    assert fallback.matched_prefix == ()
    assert fallback.backoff_level == 1


def test_route_model_requires_support_and_bounds_restored_statistics() -> None:
    model = RouteModel(
        make_map(),
        minimum_support=2.0,
        max_prefixes=1,
        max_count=4.0,
        decay=1.0,
    )

    assert model.observe(("office", "hall"), "kitchen", weight=1.0)
    assert model.match(("office", "hall"), ("kitchen", "living")).matched_prefix == ()
    assert model.observe(("office", "hall"), "kitchen", weight=5.0)
    assert model.counts[("office", "hall")]["kitchen"] == 4.0
    assert model.observe(("kitchen", "hall"), "living", weight=3.0)
    assert len(model.counts) == 1

    model.restore_counts(
        {
            ("office", "hall"): {"kitchen": 8.0, "missing": 2.0},
            ("office", "living"): {"hall": 2.0},
        }
    )
    assert model.counts == {("office", "hall"): {"kitchen": 4.0}}
    model.restore_counts({("office", "hall"): {"missing": 2.0}})
    assert model.counts == {}


def test_route_model_rejects_invalid_edges_and_skips_invalid_longer_prefix() -> None:
    model = RouteModel(make_map(), decay=1.0)

    with pytest.raises(ValueError, match="weight"):
        model.observe(("office", "hall"), "kitchen", weight=0.0)
    assert not model.observe((), "hall", weight=1.0)
    assert not model.observe(("missing",), "hall", weight=1.0)
    assert not model.observe(("office",), "living", weight=1.0)
    assert model.observe(
        ("office", "living", "hall"),
        "kitchen",
        weight=1.0,
    )
    assert ("office", "living", "hall") not in model.counts


def test_route_model_discount_can_expire_obsolete_prefix() -> None:
    model = RouteModel(make_map(), decay=0.5)
    model.restore_counts({("office", "hall"): {"kitchen": 1e-6}})

    assert not model.observe(("office",), "hall", weight=1.0)
    assert model.counts == {}


@pytest.mark.parametrize(
    ("keyword", "value"),
    (
        ("max_order", 1),
        ("minimum_support", 0.0),
        ("max_prefixes", 0),
        ("max_count", 0.0),
        ("decay", 0.0),
        ("decay", 1.1),
        ("maximum_boost", -0.1),
        ("maximum_boost", 1.1),
    ),
)
def test_route_model_rejects_invalid_configuration(keyword: str, value: float) -> None:
    with pytest.raises(ValueError):
        RouteModel(
            make_map(),
            **cast(dict[str, Any], {keyword: value}),
        )
