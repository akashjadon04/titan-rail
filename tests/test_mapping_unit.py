"""Unit tests for the mapping ladder, exercised without HTTP."""

from __future__ import annotations

from titan_rail.mapping import (
    MethodMapper,
    ShippingMethod,
    load_catalog,
    normalize,
)

from .conftest import FIXTURES

METHODS = (
    ShippingMethod("SM-A", "Standard Ground", "Marlin Post", ("standard", "ground")),
    ShippingMethod("SM-B", "Express Air", "Veltro Express", ("express",)),
)


def test_normalize_lowercases_and_collapses() -> None:
    assert normalize("  Standard   GROUND ") == "standard ground"


def test_normalize_strips_punctuation() -> None:
    assert normalize("Click & Collect!") == "click collect"


def test_exact_id_beats_alias() -> None:
    # "SM-B" is also registered as an alias of SM-A; the id rung must win.
    mapper = MethodMapper(
        (
            ShippingMethod("SM-A", "Standard Ground", "Marlin Post", ("sm b",)),
            ShippingMethod("SM-B", "Express Air", "Veltro Express", ()),
        )
    )
    outcome = mapper.map_value("SM-B")
    assert outcome.decision == "MAPPED_EXACT"
    assert outcome.method is not None and outcome.method.method_id == "SM-B"


def test_alias_beats_fuzzy() -> None:
    outcome = MethodMapper(METHODS).map_value("ground")
    assert outcome.decision == "MAPPED_ALIAS"
    assert outcome.method is not None and outcome.method.method_id == "SM-A"


def test_ambiguous_fuzzy_refuses_to_map() -> None:
    mapper = MethodMapper(
        (
            ShippingMethod("SM-X", "Blue Express", "Carrier X", ()),
            ShippingMethod("SM-Y", "Blu Express", "Carrier Y", ()),
        )
    )
    outcome = mapper.map_value("blue expres")
    assert outcome.decision == "UNMAPPED"
    assert outcome.method is None
    assert any("ambiguous" in detail for _, _, detail in outcome.steps)
    assert {c.method.method_id for c in outcome.candidates} == {"SM-X", "SM-Y"}


def test_fuzzy_threshold_is_respected() -> None:
    strict = MethodMapper(METHODS, fuzzy_threshold=0.99)
    outcome = strict.map_value("Standrd Ground")
    assert outcome.decision == "UNMAPPED"


def test_candidates_are_capped() -> None:
    methods = tuple(
        ShippingMethod(f"SM-{i}", f"Parcel Route {i}", "Marlin Post", ())
        for i in range(6)
    )
    mapper = MethodMapper(methods, max_candidates=3)
    outcome = mapper.map_value("parcel route")
    assert len(outcome.candidates) <= 3


def test_candidates_sorted_descending() -> None:
    mapper = MethodMapper(METHODS, candidate_floor=0.1)
    outcome = mapper.map_value("standart groun")
    scores = [c.score for c in outcome.candidates]
    assert scores == sorted(scores, reverse=True)


def test_empty_catalog_is_graceful() -> None:
    outcome = MethodMapper(()).map_value("anything")
    assert outcome.decision == "UNMAPPED"
    assert outcome.candidates == []


def test_load_catalog_from_fixture() -> None:
    methods = load_catalog(FIXTURES / "shipping_methods.json")
    assert len(methods) == 5
    by_id = {m.method_id: m for m in methods}
    assert by_id["SM-STD-01"].carrier == "Marlin Post"
    assert "click and collect" in by_id["SM-PUP-05"].aliases
