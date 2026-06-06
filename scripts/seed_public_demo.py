"""Seed the demo tenant with a realistic ~180-day business time series so the agent
has real signal to be autonomous over (forecasting, seasonality, reorder + dead-stock
detection, revenue/customer analytics).

Product NAMES come from a PUBLIC API (TheMealDB ingredient list) with a hardcoded
fallback; the daily sales/stock SERIES is generated with trend + weekly seasonality
+ noise + per-product archetypes so the proactive sweep and forecast_sales produce
meaningful, non-empty output:
  - growth    : rising demand, healthy stock          → forecast shows an uptrend
  - critical  : high velocity, ends with low stock     → triggers reorder proposals
  - deadstock : overstocked, demand collapses          → triggers liquidation proposals
  - stable    : flat demand                            → baseline

Idempotent: wipes + reseeds the demo tenant's business tables. Targets INSFORGE_URL
(aria-os) explicitly — never the MCP/Cinco backend.

Run: PYTHONPATH=. python3 scripts/seed_public_demo.py
"""
import asyncio
import math
import os
import random
import uuid
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")
APIKEY = os.environ["INSFORGE_API_KEY"]
ADMIN_H = {"Authorization": f"Bearer {APIKEY}", "Content-Type": "application/json"}
DEMO_EMAIL, DEMO_PW = "demo@aria.os", "AriaDemo2026!"

RNG = random.Random(20260605)  # fixed seed → reproducible series (no wall-clock randomness)
DAYS = 180

FALLBACK = ["Harina 000", "Aceite de oliva", "Tomate triturado", "Mozzarella", "Levadura",
            "Azúcar", "Café en grano", "Manteca", "Huevos", "Leche entera", "Sal fina",
            "Arroz", "Pollo", "Queso parmesano", "Cebolla", "Pimienta negra"]
SUPPLIERS = ["Distribuidora Andina", "Mayorista del Sur", "Proveeduría Central", "AgroFresh SA"]
CUSTOMERS = ["Bistró Norte", "Café Sur", "Mercado Central", "Hotel Plaza", "Resto Río",
             "Panadería Luna", "Pizzería Vesuvio", "Almacén Don José"]

# 16 products across 4 archetypes: (kind, base_velocity, trend, season_strength).
ARCH = (
    [("growth", 9, 0.7, 0.8)] * 4
    + [("critical", 13, 0.25, 0.7)] * 4
    + [("deadstock", 8, -0.6, 0.5)] * 4
    + [("stable", 7, 0.0, 0.6)] * 4
)


async def fetch_ingredients(n: int) -> list[str]:
    """Public product catalog from TheMealDB; falls back to a hardcoded list."""
    try:
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.get("https://www.themealdb.com/api/json/v1/1/list.php?i=list")
            meals = r.json().get("meals", []) or []
            names = [m["strIngredient"].strip() for m in meals if m.get("strIngredient")]
            RNG.shuffle(names)
            if len(names) >= n:
                print(f"· catálogo: TheMealDB (API pública), {len(names)} ingredientes")
                return names[:n]
    except Exception as e:  # noqa: BLE001 — any network/parse failure → graceful fallback
        print(f"· TheMealDB no disponible ({e}); usando catálogo de respaldo")
    return FALLBACK[:n]


def weekly_factor(dow: int, strength: float) -> float:
    # restaurant supply runs busier Thu–Sat
    base = {0: 0.9, 1: 0.95, 2: 1.0, 3: 1.15, 4: 1.3, 5: 1.35, 6: 0.8}[dow]
    return 1 + (base - 1) * strength


def gen_product_series(arch, dates):
    kind, base, trend, season = arch
    rows = []
    for d, date in enumerate(dates):
        prog = d / DAYS
        # Velocity: realistic series (trend + weekly seasonality + noise) for forecasting.
        decay = 1.0
        if kind == "deadstock" and prog > 0.78:  # demand collapses in the last ~5 weeks
            decay = max(0.05, 1 - (prog - 0.78) / 0.22)
        vel = max(0.0, base * weekly_factor(date.weekday(), season) * (1 + trend * prog) * decay * RNG.gauss(1, 0.13))
        # Stock: per-archetype band, decoupled from depletion so the END state reliably
        # carries the intended signal (critical ≤15, deadstock >50) for the sweep.
        if kind == "critical":
            stock = max(2.0, 24 - 17 * prog + RNG.gauss(0, 2.5))      # ramps down → recent ≤15
        elif kind == "deadstock":
            stock = min(150.0, 65 + 55 * prog + RNG.gauss(0, 6))      # accumulates → >50, idle
        elif kind == "growth":
            stock = 50 + 14 * math.sin(d / 9.0) + RNG.gauss(0, 4)     # healthy
        else:  # stable
            stock = 45 + 10 * math.sin(d / 7.0) + RNG.gauss(0, 3)
        prod = round(max(0.0, RNG.gauss(vel, 2)), 1) if (kind != "deadstock" and d % 9 == 0) else 0.0
        rows.append({"date": date.strftime("%Y-%m-%d"), "vel": round(vel, 1),
                     "stock": round(max(0.0, stock), 1), "prod": prod})
    return rows


async def insert_chunked(admin, table, rows, chunk=400):
    for i in range(0, len(rows), chunk):
        await admin.table(table).insert(rows[i:i + chunk]).execute()


async def main():
    async with httpx.AsyncClient(timeout=60) as http:
        await http.put(f"{URL}/api/auth/config", headers=ADMIN_H, json={"requireEmailVerification": False})
        r = await http.post(f"{URL}/api/auth/users?client_type=server",
                            json={"email": DEMO_EMAIL, "password": DEMO_PW, "name": "Demo Admin"})
        if r.status_code == 409:
            r = await http.post(f"{URL}/api/auth/sessions?client_type=server",
                                json={"email": DEMO_EMAIL, "password": DEMO_PW})
        r.raise_for_status()
        uid = r.json()["user"]["id"]

    admin = get_admin_client()
    res = await admin.table("tenants").select("id").eq("slug", "demo").limit(1).execute()
    t = res.data[0]["id"] if res.data else (
        await admin.table("tenants").insert({"name": "ARIA Demo", "slug": "demo", "subscription_tier": "pro"}).execute()
    ).data[0]["id"]
    m = await admin.table("tenant_users").select("id").eq("tenant_id", t).eq("user_id", uid).limit(1).execute()
    if not m.data:
        await admin.table("tenant_users").insert({"tenant_id": t, "user_id": uid, "role": "admin"}).execute()

    names = await fetch_ingredients(len(ARCH))
    dates = [datetime.now().date() - timedelta(days=DAYS - 1 - d) for d in range(DAYS)]

    products, suppliers, ledger = [], [], []
    prices = {}
    for i, (name, arch) in enumerate(zip(names, ARCH)):
        # ledger.product_id / supplier_catalog.product_id MUST equal products.id —
        # the sweep joins products on `.in_("id", ledger_product_ids)`. A deterministic
        # uuid keeps the seed reproducible.
        pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"aria-demo-product-{i}"))
        price = round(RNG.uniform(2.5, 28.0), 2)
        prices[name] = price
        products.append({"tenant_id": t, "id": pid, "sku": f"SKU-{1000 + i}", "name": name, "price": price})
        suppliers.append({"tenant_id": t, "product_id": pid, "nombre_original": name,
                          "proveedor": SUPPLIERS[i % len(SUPPLIERS)], "marca": "Genérica"})
        for row in gen_product_series(arch, dates):
            ledger.append({"tenant_id": t, "date": row["date"], "product_id": pid, "product_name": name,
                           "stock_end_of_day": row["stock"], "sales_velocity": row["vel"],
                           "production_detected": row["prod"]})

    # Orders coherent with sales: 2–4/day, line_items reference real products, ~12% invalid status.
    orders = []
    oid = 3000
    for date in dates:
        for _ in range(RNG.randint(2, 4)):
            n_items = RNG.randint(1, 3)
            picks = RNG.sample(names, n_items)
            items = [{"product_name": p, "qty": RNG.randint(1, 6), "price": prices[p]} for p in picks]
            total = round(sum(it["qty"] * it["price"] for it in items), 2)
            status = RNG.choices(["completed", "processing", "cancelled", "failed"], weights=[70, 18, 8, 4])[0]
            orders.append({"tenant_id": t, "order_id": oid, "customer_name": RNG.choice(CUSTOMERS),
                           "total": total, "status": status,
                           "date_created": f"{date.strftime('%Y-%m-%d')}T{RNG.randint(9,21):02d}:00:00Z",
                           "line_items": items})
            oid += 1

    print(f"· generando {len(ledger)} filas de ledger, {len(orders)} órdenes, {len(products)} productos…")
    for tbl in ("daily_inventory_ledger", "wc_orders_cache", "products", "supplier_catalog"):
        await admin.table(tbl).delete().eq("tenant_id", t).execute()
    await insert_chunked(admin, "daily_inventory_ledger", ledger)
    await insert_chunked(admin, "wc_orders_cache", orders)
    await insert_chunked(admin, "products", products)
    await insert_chunked(admin, "supplier_catalog", suppliers)

    print(f"\n✅ Demo sembrado en tenant ARIA Demo ({t[:8]}…)")
    print(f"   {DAYS} días · {len(products)} productos · {len(ledger)} filas ledger · {len(orders)} órdenes")
    print(f"   arquetipos: 4 growth / 4 critical-stock / 4 dead-stock / 4 stable")
    print(f"   LOGIN → {DEMO_EMAIL} / {DEMO_PW}")


asyncio.run(main())
