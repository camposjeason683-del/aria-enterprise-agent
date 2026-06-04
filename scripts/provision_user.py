"""Admin-only: provision a user into a tenant (create the user + add membership).

Now that self-serve signup is disabled (it created tenant-less orphan users the
multi-tenant backend rejects — see F6), this is the canonical "invite" path: an
admin runs it with the new user's email, the target tenant, a role and a temporary
password. The user then signs in at /login and can change their password.

Targets INSFORGE_URL explicitly (the aria-os project) — never the MCP/Cinco backend.
Idempotent: re-running updates the role instead of duplicating the membership.

Usage:
  PYTHONPATH=. python3 scripts/provision_user.py <email> <tenant_slug> <admin|employee> <temp_password>
"""
import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.infra.insforge import get_admin_client  # noqa: E402

URL = os.environ["INSFORGE_URL"].rstrip("/")


async def main() -> None:
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    email, slug, role, password = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    if role not in ("admin", "employee"):
        print("✗ role must be 'admin' or 'employee'")
        sys.exit(2)

    admin = get_admin_client()

    # 1. Resolve the tenant (must already exist).
    t = await admin.table("tenants").select("id, name").eq("slug", slug).limit(1).execute()
    if not t.data:
        print(f"✗ tenant '{slug}' not found — create it first")
        sys.exit(1)
    tenant_id = t.data[0]["id"]

    # 2. Create the auth user (or sign in if it already exists with this password).
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(
            f"{URL}/api/auth/users?client_type=server",
            json={"email": email, "password": password, "name": email},
        )
        if r.status_code == 409:  # already exists → need the password to get the id
            r = await http.post(
                f"{URL}/api/auth/sessions?client_type=server",
                json={"email": email, "password": password},
            )
            if r.status_code >= 300:
                print(f"✗ user '{email}' already exists but the password didn't match. "
                      "Reset it in InsForge or pass the user's current password.")
                sys.exit(1)
        r.raise_for_status()
        user_id = r.json()["user"]["id"]

    # 3. Upsert the membership (idempotent).
    m = (
        await admin.table("tenant_users")
        .select("id, role").eq("tenant_id", tenant_id).eq("user_id", user_id).limit(1).execute()
    )
    if m.data:
        if m.data[0]["role"] != role:
            await admin.table("tenant_users").update({"role": role}).eq("id", m.data[0]["id"]).execute()
            print(f"✓ {email} role updated → {role} in tenant '{slug}'")
        else:
            print(f"✓ {email} already provisioned as {role} in tenant '{slug}' (no change)")
    else:
        await admin.table("tenant_users").insert(
            {"tenant_id": tenant_id, "user_id": user_id, "role": role}
        ).execute()
        print(f"✓ provisioned {email} → tenant '{slug}' ({t.data[0]['name']}) as {role}")
    print(f"  user can now sign in at /login with email '{email}' and the temp password.")


asyncio.run(main())
