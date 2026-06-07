"""Billing + subscription enforcement (M7).

The load-bearing fix: ``tenants.subscription_status`` was READ but never ENFORCED on
the app paths — a 'canceled' tenant kept using the product. ``require_active_subscription``
(main.py) now gates the agent on it. Stripe webhooks keep the status in sync; the enforce
works off the column even before Stripe keys are configured.

Pure helpers (``subscription_active`` / ``map_stripe_event`` / ``_norm_status``) are
unit-tested; ``resolve_subscription_status`` / ``apply_stripe_event`` hit the DB.
"""
from __future__ import annotations

from typing import Optional

from src.infra.db import get_system_client

ACTIVE_STATES = frozenset({"active", "trialing"})

# Feature flags by plan tier (extends the rate-limit tiers). What each plan unlocks.
TIER_FEATURES = {
    "free": {"forecast", "proposals"},
    "pro": {"forecast", "proposals", "automation_rules", "anomalies", "what_if", "notifications"},
    "enterprise": {"forecast", "proposals", "automation_rules", "anomalies", "what_if",
                   "notifications", "multi_store", "sso"},
}


def subscription_active(status: Optional[str]) -> bool:
    """Pure: may a tenant with this subscription status use the product?"""
    return (status or "").strip().lower() in ACTIVE_STATES


def tier_allows(tier: Optional[str], feature: str) -> bool:
    """Pure: does this plan tier include the feature?"""
    return feature in TIER_FEATURES.get((tier or "free").strip().lower(), TIER_FEATURES["free"])


def _norm_status(s: Optional[str]) -> str:
    """Map any Stripe/raw status onto our three canonical states."""
    s = (s or "").strip().lower()
    if s in ("active", "trialing"):
        return "active"
    if s in ("past_due", "unpaid", "incomplete"):
        return "past_due"
    if s in ("canceled", "cancelled", "incomplete_expired"):
        return "canceled"
    return s or "active"


_EVENT_STATUS = {
    "customer.subscription.created": "active",
    "customer.subscription.updated": None,   # use the subscription object's own status
    "customer.subscription.deleted": "canceled",
    "invoice.payment_failed": "past_due",
    "invoice.paid": "active",
}


def map_stripe_event(event: dict) -> Optional[dict]:
    """Pure: a Stripe webhook event → {stripe_customer_id, status, stripe_subscription_id}
    or None if it doesn't affect a subscription."""
    etype = event.get("type")
    if etype not in _EVENT_STATUS:
        return None
    obj = (event.get("data") or {}).get("object") or {}
    status = _EVENT_STATUS[etype]
    if status is None:
        status = obj.get("status")
    sub = obj.get("id") if str(etype).startswith("customer.subscription") else obj.get("subscription")
    return {
        "stripe_customer_id": obj.get("customer"),
        "status": _norm_status(status),
        "stripe_subscription_id": sub,
    }


async def resolve_subscription_status(tenant_id: str) -> str:
    """Read the tenant's current subscription status (defaults to 'active')."""
    client = get_system_client()
    res = (await client.table("tenants").select("subscription_status")
           .eq("id", tenant_id).limit(1).execute())
    return (res.data[0].get("subscription_status") if res.data else None) or "active"


async def apply_stripe_event(event: dict) -> dict:
    """Idempotently update a tenant's subscription from a Stripe webhook event."""
    mapped = map_stripe_event(event)
    if not mapped or not mapped.get("stripe_customer_id"):
        return {"status": "ignored"}
    client = get_system_client()
    t = (await client.table("tenants").select("id")
         .eq("stripe_customer_id", mapped["stripe_customer_id"]).limit(1).execute())
    if not t.data:
        return {"status": "no_tenant"}
    tid = t.data[0]["id"]
    update = {"subscription_status": mapped["status"]}
    if mapped.get("stripe_subscription_id"):
        update["stripe_subscription_id"] = mapped["stripe_subscription_id"]
    await client.table("tenants").update(update).eq("id", tid).execute()
    return {"status": "applied", "tenant_id": tid, "subscription_status": mapped["status"]}
