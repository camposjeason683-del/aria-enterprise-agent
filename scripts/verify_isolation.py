"""
Live 2-tenant isolation gate (spec: tenancy/tenant-isolation).

Provisions two users + two tenants in the aria-os InsForge project, seeds 3 vs 5
orders, then verifies — with each user's JWT — that no path returns the other
tenant's rows, INCLUDING the raw LLM-SQL path (exec_safe_read). Idempotent.
"""
import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client, get_tenant_client  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")
APIKEY = os.environ["INSFORGE_API_KEY"]
PW = "AriaTest1234!"
ADMIN_H = {"Authorization": f"Bearer {APIKEY}", "Content-Type": "application/json"}


async def ensure_no_verification(http):
    cfg = (await http.get(f"{URL}/api/auth/public-config")).json()
    if cfg.get("requireEmailVerification"):
        await http.put(
            f"{URL}/api/auth/config", headers=ADMIN_H, json={"requireEmailVerification": False}
        )
        print("· disabled email verification (test project)")


async def get_user_token(http, email):
    r = await http.post(
        f"{URL}/api/auth/users?client_type=server",
        json={"email": email, "password": PW, "name": email},
    )
    if r.status_code == 409:  # already exists → sign in
        r = await http.post(
            f"{URL}/api/auth/sessions?client_type=server",
            json={"email": email, "password": PW},
        )
    r.raise_for_status()
    d = r.json()
    assert d.get("accessToken"), f"no accessToken for {email}: {d}"
    return d["user"]["id"], d["accessToken"]


async def ensure_tenant(admin, slug, name):
    res = await admin.table("tenants").select("id").eq("slug", slug).limit(1).execute()
    if res.data:
        return res.data[0]["id"]
    res = await admin.table("tenants").insert({"name": name, "slug": slug}).execute()
    return res.data[0]["id"]


async def ensure_membership(admin, tenant_id, user_id):
    res = (
        await admin.table("tenant_users")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        await admin.table("tenant_users").insert(
            {"tenant_id": tenant_id, "user_id": user_id, "role": "admin"}
        ).execute()


async def reseed_orders(admin, tenant_id, n):
    await admin.table("wc_orders_cache").delete().eq("tenant_id", tenant_id).execute()
    rows = [
        {
            "tenant_id": tenant_id,
            "order_id": 1000 + i,
            "customer_name": f"cust{i}",
            "total": 10.0 + i,
            "status": "processing",
        }
        for i in range(n)
    ]
    await admin.table("wc_orders_cache").insert(rows).execute()


async def main():
    async with httpx.AsyncClient(timeout=60) as http:
        await ensure_no_verification(http)
        uid_a, tok_a = await get_user_token(http, "aria-iso-a@example.com")
        uid_b, tok_b = await get_user_token(http, "aria-iso-b@example.com")

    admin = get_admin_client()
    ta = await ensure_tenant(admin, "iso-a", "Tenant A")
    tb = await ensure_tenant(admin, "iso-b", "Tenant B")
    await ensure_membership(admin, ta, uid_a)
    await ensure_membership(admin, tb, uid_b)
    await reseed_orders(admin, ta, 3)
    await reseed_orders(admin, tb, 5)
    print(f"· seeded: tenant A({ta[:8]})=3 orders, tenant B({tb[:8]})=5 orders")

    ca, cb = get_tenant_client(tok_a), get_tenant_client(tok_b)
    failures = []

    # (i) normal tool query
    ra = await ca.table("wc_orders_cache").select("tenant_id").execute()
    if len(ra.data) != 3 or any(r["tenant_id"] != ta for r in ra.data):
        failures.append(f"(i) A tool query saw {len(ra.data)} rows / {{{ {r['tenant_id'] for r in ra.data} }}}")
    rb = await cb.table("wc_orders_cache").select("tenant_id").execute()
    if len(rb.data) != 5 or any(r["tenant_id"] != tb for r in rb.data):
        failures.append(f"(i) B tool query saw {len(rb.data)} rows")

    # (ii) raw LLM SQL with NO tenant filter
    rawa = await ca.rpc("exec_safe_read", {"q": "SELECT tenant_id FROM wc_orders_cache"})
    ta_seen = {r["tenant_id"] for r in (rawa.data or [])}
    if ta_seen != {ta}:
        failures.append(f"(ii) A raw SQL leaked tenants: {ta_seen}")

    # (iii) unfiltered aggregate
    agg = await ca.rpc("exec_safe_read", {"q": "SELECT count(*) AS n FROM wc_orders_cache"})
    if (agg.data or [{}])[0].get("n") != 3:
        failures.append(f"(iii) A unfiltered count = {agg.data} (expected 3)")

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("✗", f)
        raise SystemExit("ISOLATION GATE FAILED")
    print("✓ (i)   tool query: A sees 3 (only A), B sees 5 (only B)")
    print("✓ (ii)  raw LLM SQL with no filter: A sees only tenant A")
    print("✓ (iii) unfiltered COUNT(*): A counts only its own 3")
    print("\n🔒 2-TENANT ISOLATION GATE PASSED")


asyncio.run(main())
