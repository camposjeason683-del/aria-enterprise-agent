"""Unit tests for the WooCommerce write-back helpers (payloads + product resolution)."""
import asyncio

from src.tools.writeback import _find_product_id, _price_payload, _sale_payload

_CREDS = {"woo_url": "https://shop.example", "woo_consumer_key": "k", "woo_consumer_secret": "s"}


def test_payloads():
    assert _price_payload(12.5) == {"regular_price": "12.5"}
    assert _sale_payload(9) == {"sale_price": "9"}


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _Http:
    def __init__(self, data):
        self._data = data

    async def get(self, *a, **k):
        return _Resp(self._data)


def test_find_product_id_prefers_exact_match():
    http = _Http([{"id": 1, "name": "Tomate Cherry"}, {"id": 2, "name": "Tomate"}])
    assert asyncio.run(_find_product_id(http, _CREDS, "Tomate")) == 2


def test_find_product_id_falls_back_to_first():
    http = _Http([{"id": 7, "name": "Tomate Cherry"}])
    assert asyncio.run(_find_product_id(http, _CREDS, "Tomate")) == 7


def test_find_product_id_none_when_empty():
    assert asyncio.run(_find_product_id(_Http([]), _CREDS, "X")) is None
