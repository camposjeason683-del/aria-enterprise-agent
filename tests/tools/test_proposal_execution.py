"""Unit tests for the proposal-execution dispatcher's pure helpers + category routing."""
from src.tools.proposal_execution import _LIQUID, _PRICE, _REORDER, _item_name, _item_value


def test_item_name_and_value():
    assert _item_name({"product_name": "A"}) == "A"
    assert _item_name({"product": "B"}) == "B"
    assert _item_value({"new_price": 5, "price": 9}, "new_price", "price") == 5
    assert _item_value({"price": 9}, "new_price", "price") == 9
    assert _item_value({}, "new_price", "price") is None


def test_category_sets_are_disjoint_and_cover_intents():
    assert "reabastecimiento" in _REORDER
    assert "ajuste de precios" in _PRICE
    assert "liquidación" in _LIQUID
    # no overlap between the three intent buckets
    assert not (_REORDER & _PRICE) and not (_PRICE & _LIQUID) and not (_REORDER & _LIQUID)
