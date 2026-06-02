"""Live smoke of S4 (persistent session) + S5 (rate limit) against aria-os."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client  # noqa: E402
from src.infra.rate_limiter import _utc_day_key, check_rate_limit  # noqa: E402
from src.infra.session_insforge import InsForgeSessionService  # noqa: E402


async def main():
    admin = get_admin_client()
    t = (await admin.table("tenants").select("id").eq("slug", "iso-a").limit(1).execute()).data[0]["id"]

    # S4 — persist then hydrate from a fresh instance
    svc = InsForgeSessionService()
    await svc.create_session(
        app_name="agents", user_id="smoke", state={"tenant_id": t}, session_id="smoke-1"
    )
    row = await admin.table("agent_sessions").select("id").eq("id", "agents:smoke:smoke-1").execute()
    assert row.data, "session not persisted"
    loaded = await InsForgeSessionService().get_session(
        app_name="agents", user_id="smoke", session_id="smoke-1"
    )
    assert loaded is not None, "session not hydrated by a fresh instance"
    print("✓ S4 session: persisted to agent_sessions + hydrated by a fresh instance")

    # S5 — shared counter increments across calls
    wk = _utc_day_key()
    await admin.table("rate_limit_counters").delete().eq("tenant_id", t).eq("user_id", "smoke").eq("window_key", wk).execute()
    r1 = await check_rate_limit(t, "smoke", "free")
    r2 = await check_rate_limit(t, "smoke", "free")
    assert r1.allowed and r2.allowed and r2.remaining == r1.remaining - 1, f"{r1} {r2}"
    print(f"✓ S5 rate limit: remaining {r1.remaining} → {r2.remaining} (shared rate_limit_counters)")

    await svc.delete_session(app_name="agents", user_id="smoke", session_id="smoke-1")
    print("\n✅ S4 + S5 verified live against aria-os")


asyncio.run(main())
