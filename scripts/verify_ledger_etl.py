"""Live gate for the M1 keystone ETL (compile_ledger_for_tenant).

Provisions two throwaway tenants in the linked InsForge project, seeds each with
orders (line_items), then runs the REAL cron code path (run_for_tenant → headless
compile_ledger_for_tenant) and verifies three things:

  1. CORRECTNESS — compiled sales_velocity == summed order quantities per (product, day).
  2. IDEMPOTENCY — compiling twice leaves the SAME ledger row count (no duplicates).
     This only holds if migration 0010's UNIQUE(tenant_id,date,product_id) is live and
     the upsert on_conflict resolves — so this assertion DOUBLES as the 0010 gate.
  3. ISOLATION  — tenant A's compile only writes A's ledger; a tenant-scoped (RLS)
     client for A sees only A's rows, never B's.

Targets INSFORGE_URL (aria-os or a branch DB via env override). Idempotent: resets
the two test tenants' business tables at start and cleans them at the end.

Run: PYTHONPATH=. python3 scripts/verify_ledger_etl.py
"""
import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.cron_runner import run_for_tenant  # noqa: E402
from src.infra.insforge import get_admin_client, get_tenant_client  # noqa: E402
from src.tools.ledger_etl import compile_ledger_for_tenant  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")
APIKEY = os.environ["INSFORGE_API_KEY"]
PW = "AriaTest1234!"
ADMIN_H = {"Authorization": f"Bearer {APIKEY}", "Content-Type": "application/json"}

A_ORDERS = [  # (date, [(name, qty, price)], status)
    ("2026-03-01", [("Tomate", 3, 2.0), ("Queso", 1, 5.0)], "completed"),
    ("2026-03-01", [("Tomate", 2, 2.0)], "processing"),
    ("2026-03-02", [("Tomate", 4, 2.5)], "completed"),
    ("2026-03-02", [("Tomate", 99, 2.0)], "cancelled"),   # excluded (not a sold status)
]
B_ORDERS = [
    ("2026-03-01", [("Pan", 7, 1.0)], "completed"),
]


async def get_user_token(http, email):
    r = await http.post(f"{URL}/api/auth/users?client_type=server",
                        json={"email": email, "password": PW, "name": email})
    if r.status_code == 409:
        r = await http.post(f"{URL}/api/auth/sessions?client_type=server",
                            json={"email": email, "password": PW})
    r.raise_for_status()
    d = r.json()
    return d["user"]["id"], d["accessToken"]


async def ensure_tenant(admin, slug, name):
    res = await admin.table("tenants").select("id").eq("slug", slug).limit(1).execute()
    if res.data:
        return res.data[0]["id"]
    res = await admin.table("tenants").insert({"name": name, "slug": slug}).execute()
    return res.data[0]["id"]


async def ensure_membership(admin, tenant_id, user_id):
    res = (await admin.table("tenant_users").select("id")
           .eq("tenant_id", tenant_id).eq("user_id", user_id).limit(1).execute())
    if not res.data:
        await admin.table("tenant_users").insert(
            {"tenant_id": tenant_id, "user_id": user_id, "role": "admin"}).execute()


async def reset_business(admin, tenant_id):
    for tbl in ("daily_inventory_ledger", "wc_orders_cache", "products"):
        await admin.table(tbl).delete().eq("tenant_id", tenant_id).execute()


async def seed_orders(admin, tenant_id, specs):
    rows = [{
        "tenant_id": tenant_id, "order_id": 2000 + i, "status": status,
        "date_created": f"{date}T10:00:00Z",
        "line_items": [{"product_name": n, "qty": q, "price": p} for (n, q, p) in items],
    } for i, (date, items, status) in enumerate(specs)]
    await admin.table("wc_orders_cache").insert(rows).execute()


async def ledger_rows(admin, tenant_id):
    r = (await admin.table("daily_inventory_ledger")
         .select("product_name, date, sales_velocity, product_id")
         .eq("tenant_id", tenant_id).execute())
    return r.data or []


async def main():
    failures = []
    async with httpx.AsyncClient(timeout=60) as http:
        uid_a, tok_a = await get_user_token(http, "aria-etl-a@example.com")
        uid_b, _ = await get_user_token(http, "aria-etl-b@example.com")

    admin = get_admin_client()
    ta = await ensure_tenant(admin, "etl-a", "ETL Tenant A")
    tb = await ensure_tenant(admin, "etl-b", "ETL Tenant B")
    await ensure_membership(admin, ta, uid_a)
    await ensure_membership(admin, tb, uid_b)
    await reset_business(admin, ta)
    await reset_business(admin, tb)
    await seed_orders(admin, ta, A_ORDERS)
    await seed_orders(admin, tb, B_ORDERS)
    print(f"· seeded A({ta[:8]}) {len(A_ORDERS)} orders, B({tb[:8]}) {len(B_ORDERS)} orders")

    # Run the REAL cron path: headless per-tenant compile.
    r1 = await run_for_tenant(ta, lambda: compile_ledger_for_tenant())
    await run_for_tenant(tb, lambda: compile_ledger_for_tenant())
    print(f"· compile A → {r1}")

    # 1. CORRECTNESS
    rows_a = await ledger_rows(admin, ta)
    vel = {(r["product_name"], r["date"]): r["sales_velocity"] for r in rows_a}
    expected = {("Tomate", "2026-03-01"): 5.0, ("Queso", "2026-03-01"): 1.0,
                ("Tomate", "2026-03-02"): 4.0}
    if {k: float(v) for k, v in vel.items()} != expected:
        failures.append(f"(1) correctness: got {vel}, expected {expected}")
    else:
        print("✓ (1) correctness: velocity = summed qty per (product, day); cancelled excluded")

    # 2. IDEMPOTENCY (== the 0010 UNIQUE gate)
    n_before = len(rows_a)
    await run_for_tenant(ta, lambda: compile_ledger_for_tenant())
    n_after = len(await ledger_rows(admin, ta))
    if n_after != n_before:
        failures.append(f"(2) idempotency: rows {n_before} → {n_after} on re-run (0010 UNIQUE not enforcing?)")
    else:
        print(f"✓ (2) idempotency: re-compile kept {n_after} rows (0010 UNIQUE + upsert on_conflict live)")

    # 3. ISOLATION — admin view + tenant-scoped RLS view
    names_a = {r["product_name"] for r in await ledger_rows(admin, ta)}
    names_b = {r["product_name"] for r in await ledger_rows(admin, tb)}
    if "Pan" in names_a or names_b != {"Pan"}:
        failures.append(f"(3a) cross-tenant bleed: A={names_a}, B={names_b}")
    ca = get_tenant_client(tok_a)
    rls = await ca.table("daily_inventory_ledger").select("product_name, tenant_id").execute()
    if any(r["tenant_id"] != ta for r in (rls.data or [])) or not rls.data:
        failures.append(f"(3b) RLS: A's client saw {len(rls.data or [])} rows incl. foreign tenants")
    else:
        print(f"✓ (3) isolation: A={names_a} / B={names_b}; A's RLS client sees only its own {len(rls.data)} rows")

    # cleanup
    await reset_business(admin, ta)
    await reset_business(admin, tb)

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("✗", f)
        raise SystemExit("LEDGER ETL GATE FAILED")
    print("🔒 LEDGER ETL GATE PASSED (correctness + idempotency/0010 + 2-tenant isolation)")


asyncio.run(main())
