"""P2 correctness gate — DB-side aggregates must equal the old Python-sum logic.

Seeds a known set of orders for a dedicated tenant, then asserts that the new
exec_safe_read aggregate path (query_revenue_summary / query_top_customers)
returns EXACTLY what the previous "fetch every row + sum in Python" logic would —
run inline here as the reference — over the same live, RLS-scoped data. Idempotent.

Run: PYTHONPATH=. python3 scripts/verify_p2_aggregates.py
"""
import asyncio
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client, get_tenant_client  # noqa: E402
from src.infra.tenant_context import TenantContext, set_current  # noqa: E402
from src.tools import sales  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")
APIKEY = os.environ["INSFORGE_API_KEY"]
PW = "AriaTest1234!"
EMAIL = "aria-p2@example.com"

# Known seed → hand-computable expected (date_created = now, so any window catches it).
# Only completed+processing count toward revenue; top_customers also drops null/empty names.
SEED = [
    {"customer_name": "Ana", "total": 100, "status": "completed"},
    {"customer_name": "Ana", "total": 50, "status": "completed"},
    {"customer_name": "Ana", "total": 25, "status": "processing"},   # Ana = 175
    {"customer_name": "Beto", "total": 200, "status": "completed"},  # Beto = 200
    {"customer_name": "Caro", "total": 75, "status": "processing"},  # Caro = 75
    {"customer_name": "Dani", "total": 999, "status": "cancelled"},  # excluded (status)
    {"customer_name": "", "total": 10, "status": "completed"},       # in revenue, NOT in top
    {"customer_name": None, "total": 20, "status": "completed"},     # in revenue, NOT in top
]
EXPECTED_REVENUE = 480.0          # 100+50+25+200+75+10+20 (cancelled 999 excluded)
EXPECTED_COUNT = 7
EXPECTED_TOP = [                  # sorted by spend desc, empty/null names dropped
    {"name": "Beto", "total_spent": 200.0},
    {"name": "Ana", "total_spent": 175.0},
    {"name": "Caro", "total_spent": 75.0},
]


async def get_user(http):
    r = await http.post(f"{URL}/api/auth/users?client_type=server", json={"email": EMAIL, "password": PW, "name": EMAIL})
    if r.status_code == 409:
        r = await http.post(f"{URL}/api/auth/sessions?client_type=server", json={"email": EMAIL, "password": PW})
    r.raise_for_status()
    d = r.json()
    return d["user"]["id"], d["accessToken"]


# ── Reference: the EXACT pre-P2 Python logic, kept here to prove equivalence ──
async def ref_revenue(client, days):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    res = (
        await client.table("wc_orders_cache").select("total, status")
        .gte("date_created", cutoff).in_("status", ["completed", "processing"]).execute()
    )
    total = sum(float(r["total"]) for r in (res.data or []))
    return {"revenue": round(total, 2), "orders_counted": len(res.data or [])}


async def ref_top(client, days, limit):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    res = (
        await client.table("wc_orders_cache").select("customer_name, total")
        .gte("date_created", cutoff).in_("status", ["completed", "processing"]).execute()
    )
    customers = {}
    for r in (res.data or []):
        name = r.get("customer_name")
        if name:
            customers[name] = customers.get(name, 0) + float(r.get("total") or 0)
    top = sorted(customers.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"name": c[0], "total_spent": round(c[1], 2)} for c in top]


async def main():
    async with httpx.AsyncClient(timeout=60) as http:
        cfg = (await http.get(f"{URL}/api/auth/public-config")).json()
        if cfg.get("requireEmailVerification"):
            await http.put(f"{URL}/api/auth/config",
                           headers={"Authorization": f"Bearer {APIKEY}", "Content-Type": "application/json"},
                           json={"requireEmailVerification": False})
        uid, tok = await get_user(http)

    admin = get_admin_client()
    res = await admin.table("tenants").select("id").eq("slug", "p2-test").limit(1).execute()
    tid = res.data[0]["id"] if res.data else (await admin.table("tenants").insert({"name": "P2 Test", "slug": "p2-test"}).execute()).data[0]["id"]
    mem = await admin.table("tenant_users").select("id").eq("tenant_id", tid).eq("user_id", uid).limit(1).execute()
    if not mem.data:
        await admin.table("tenant_users").insert({"tenant_id": tid, "user_id": uid, "role": "admin"}).execute()

    # idempotent reseed
    now_iso = datetime.now().isoformat()
    await admin.table("wc_orders_cache").delete().eq("tenant_id", tid).execute()
    await admin.table("wc_orders_cache").insert([
        {"tenant_id": tid, "order_id": 5000 + i, "customer_name": o["customer_name"],
         "total": o["total"], "status": o["status"], "date_created": now_iso}
        for i, o in enumerate(SEED)
    ]).execute()
    print(f"· seeded {len(SEED)} orders for tenant p2-test({tid[:8]})")

    # Run the tool functions under the tenant's RLS context (what production does).
    set_current(TenantContext(user_id=uid, tenant_id=tid, role="admin", jwt=tok))
    client = get_tenant_client(tok)

    new_rev = await sales.query_revenue_summary(days=7)
    new_top = await sales.query_top_customers(days=7, limit=5)
    ref_rev = await ref_revenue(client, 7)
    ref_t = await ref_top(client, 7, 5)

    failures = []
    # 1. new == hand-computed expected
    if new_rev["revenue"] != EXPECTED_REVENUE or new_rev["orders_counted"] != EXPECTED_COUNT:
        failures.append(f"revenue: got {new_rev}, expected revenue={EXPECTED_REVENUE} count={EXPECTED_COUNT}")
    if new_top["top_customers"] != EXPECTED_TOP:
        failures.append(f"top: got {new_top['top_customers']}, expected {EXPECTED_TOP}")
    # 2. new == reference Python logic (equivalence over the SAME live data)
    if (new_rev["revenue"], new_rev["orders_counted"]) != (ref_rev["revenue"], ref_rev["orders_counted"]):
        failures.append(f"revenue != python-ref: new={new_rev} ref={ref_rev}")
    if new_top["top_customers"] != ref_t:
        failures.append(f"top != python-ref: new={new_top['top_customers']} ref={ref_t}")

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("✗", f)
        raise SystemExit("P2 AGGREGATE GATE FAILED")
    print(f"✓ revenue: {new_rev['revenue']} over {new_rev['orders_counted']} orders (== expected == python-ref)")
    print(f"✓ top_customers: {[c['name']+':'+str(c['total_spent']) for c in new_top['top_customers']]} (== expected == python-ref)")
    print("\n🔢 P2 DB-AGGREGATE CORRECTNESS GATE PASSED")


asyncio.run(main())
