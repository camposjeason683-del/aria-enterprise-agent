"""Live e2e smoke of the main.py cutover through the REAL FastAPI app:
a real user JWT passes require_tenant → tenant resolution → tenant client → RLS
query. Uses /api/v1/proposals (no LLM needed)."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

URL = os.environ["INSFORGE_URL"].rstrip("/")
r = httpx.post(
    f"{URL}/api/auth/sessions?client_type=server",
    json={"email": "aria-iso-a@example.com", "password": "AriaTest1234!"},
    timeout=30,
)
token = r.json()["accessToken"]

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402

with TestClient(app) as c:
    no_auth = c.get("/api/v1/proposals")
    with_jwt = c.get("/api/v1/proposals", headers={"Authorization": f"Bearer {token}"})
    print(f"no-auth → {no_auth.status_code} (expect 401)")
    print(f"with real JWT → {with_jwt.status_code} {with_jwt.text[:120]}")
    assert no_auth.status_code == 401
    assert with_jwt.status_code == 200

print("\n✅ cutover e2e: require_tenant + tenant client + RLS query work through the live app")
