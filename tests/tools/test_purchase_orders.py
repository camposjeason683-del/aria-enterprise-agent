"""Unit tests for the pure PO state-machine helpers."""
from src.tools.purchase_orders import _item_name, _item_qty, _next_state


def test_next_state_valid_chain():
    assert _next_state("pending_audit", "confirm") == "confirmed"
    assert _next_state("confirmed", "dispatch") == "dispatched"
    assert _next_state("dispatched", "deliver") == "delivered"


def test_next_state_invalid_transitions():
    assert _next_state("pending_audit", "deliver") is None       # skip
    assert _next_state("delivered", "confirm") is None           # terminal
    assert _next_state("confirmed", "confirm") is None           # repeat → handled as no-op upstream
    assert _next_state("draft", "dispatch") is None


def test_item_qty_aliases_and_guards():
    assert _item_qty({"quantity": 5}) == 5.0
    assert _item_qty({"qty": "3"}) == 3.0
    assert _item_qty({"cantidad": 2}) == 2.0
    assert _item_qty({"qty": "abc"}) == 0.0
    assert _item_qty({}) == 0.0


def test_item_name_aliases():
    assert _item_name({"product_name": "A"}) == "A"
    assert _item_name({"product": "B"}) == "B"
    assert _item_name({"name": "C"}) == "C"
    assert _item_name({}) is None
