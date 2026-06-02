"""Seed a ready-to-use demo tenant + user + sample data in aria-os, so you can
log in and immediately use the agent. Idempotent. Prints the demo credentials."""
import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")
APIKEY = os.environ["INSFORGE_API_KEY"]
ADMIN_H = {"Authorization": f"Bearer {APIKEY}", "Content-Type": "application/json"}

DEMO_EMAIL = "demo@aria.os"
DEMO_PW = "AriaDemo2026!"


async def get_or_create_user(http):
    await http.put(f"{URL}/api/auth/config", headers=ADMIN_H, json={"requireEmailVerification": False})
    r = await http.post(
        f"{URL}/api/auth/users?client_type=server",
        json={"email": DEMO_EMAIL, "password": DEMO_PW, "name": "Demo Admin"},
    )
    if r.status_code == 409:
        r = await http.post(
            f"{URL}/api/auth/sessions?client_type=server",
            json={"email": DEMO_EMAIL, "password": DEMO_PW},
        )
    r.raise_for_status()
    return r.json()["user"]["id"]


async def ensure_tenant(admin, slug, name, tier="pro"):
    res = await admin.table("tenants").select("id").eq("slug", slug).limit(1).execute()
    if res.data:
        return res.data[0]["id"]
    res = await admin.table("tenants").insert(
        {"name": name, "slug": slug, "subscription_tier": tier}
    ).execute()
    return res.data[0]["id"]


async def main():
    async with httpx.AsyncClient(timeout=60) as http:
        uid = await get_or_create_user(http)

    admin = get_admin_client()
    t = await ensure_tenant(admin, "demo", "ARIA Demo")

    # membership (admin)
    m = await admin.table("tenant_users").select("id").eq("tenant_id", t).eq("user_id", uid).limit(1).execute()
    if not m.data:
        await admin.table("tenant_users").insert(
            {"tenant_id": t, "user_id": uid, "role": "admin"}
        ).execute()

    # sample orders
    await admin.table("wc_orders_cache").delete().eq("tenant_id", t).execute()
    customers = ["Bistró Norte", "Café Sur", "Mercado Central", "Hotel Plaza", "Resto Río"]
    orders = [
        {
            "tenant_id": t,
            "order_id": 2000 + i,
            "customer_name": customers[i % len(customers)],
            "total": round(120.0 + i * 37.5, 2),
            "status": "completed" if i % 3 else "processing",
            "date_created": f"2026-05-{(i % 27) + 1:02d}T12:00:00Z",
        }
        for i in range(14)
    ]
    await admin.table("wc_orders_cache").insert(orders).execute()

    # sample inventory
    await admin.table("daily_inventory_ledger").delete().eq("tenant_id", t).execute()
    products = [("Harina 000", 8), ("Aceite girasol", 3), ("Tomate triturado", 25), ("Mozzarella", 5), ("Levadura", 40)]
    await admin.table("daily_inventory_ledger").insert(
        [
            {
                "tenant_id": t,
                "date": "2026-05-31",
                "product_id": f"P{i}",
                "product_name": name,
                "stock_end_of_day": stock,
                "sales_velocity": round(2.5 + i, 1),
            }
            for i, (name, stock) in enumerate(products)
        ]
    ).execute()

    # a sample proposal
    await admin.table("aria_proposals").delete().eq("tenant_id", t).execute()
    await admin.table("aria_proposals").insert(
        {
            "tenant_id": t,
            "title": "Reabastecer Aceite girasol",
            "problem": "Stock en 3 unidades con velocidad de venta alta.",
            "proposed_action": "Generar OC de 50 unidades al proveedor habitual.",
            "urgency": "alta",
            "status": "pending",
            "category": "reabastecimiento",
        }
    ).execute()

    print("\n✅ Demo listo.")
    print(f"   tenant: ARIA Demo ({t[:8]}…) · 14 órdenes, 5 productos, 1 propuesta")
    print(f"   LOGIN  →  email: {DEMO_EMAIL}   password: {DEMO_PW}")


asyncio.run(main())
