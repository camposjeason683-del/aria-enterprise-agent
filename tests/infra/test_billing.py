"""Unit tests for the billing pure helpers (enforcement + Stripe event mapping)."""
from src.infra.billing import (
    map_stripe_event, subscription_active, tier_allows, _norm_status,
)


def test_subscription_active():
    assert subscription_active("active") is True
    assert subscription_active("trialing") is True
    assert subscription_active("canceled") is False
    assert subscription_active("past_due") is False
    assert subscription_active(None) is False
    assert subscription_active("") is False


def test_tier_allows_gates_features():
    assert tier_allows("free", "forecast") is True
    assert tier_allows("free", "automation_rules") is False   # gated to pro+
    assert tier_allows("pro", "automation_rules") is True
    assert tier_allows("enterprise", "multi_store") is True
    assert tier_allows(None, "what_if") is False              # defaults to free


def test_norm_status_maps_to_canonical():
    assert _norm_status("trialing") == "active"
    assert _norm_status("unpaid") == "past_due"
    assert _norm_status("incomplete_expired") == "canceled"
    assert _norm_status(None) == "active"


def test_map_stripe_event():
    deleted = map_stripe_event({"type": "customer.subscription.deleted",
                                "data": {"object": {"id": "sub_1", "customer": "cus_1"}}})
    assert deleted == {"stripe_customer_id": "cus_1", "status": "canceled",
                       "stripe_subscription_id": "sub_1"}

    failed = map_stripe_event({"type": "invoice.payment_failed",
                               "data": {"object": {"customer": "cus_2", "subscription": "sub_2"}}})
    assert failed["status"] == "past_due" and failed["stripe_customer_id"] == "cus_2"

    updated = map_stripe_event({"type": "customer.subscription.updated",
                                "data": {"object": {"id": "sub_3", "customer": "cus_3", "status": "past_due"}}})
    assert updated["status"] == "past_due"  # uses the object's own status

    assert map_stripe_event({"type": "ping"}) is None  # unrelated event
