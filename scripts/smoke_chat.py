"""Full end-to-end chat smoke against aria-os: auth → rate-limit → session →
agent (Gemini) → response. Uses a real user JWT and a data question that
exercises the SALES analyst + a tenant-scoped (RLS) tool query."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

URL = os.environ["INSFORGE_URL"].rstrip("/")
token = httpx.post(
    f"{URL}/api/auth/sessions?client_type=server",
    json={"email": "aria-iso-a@example.com", "password": "AriaTest1234!"},
    timeout=30,
).json()["accessToken"]

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402

with TestClient(app) as c:
    r = c.post(
        "/api/v1/chat",
        data={"message": "¿Cuántas órdenes de venta tengo registradas en total? Respondé en una frase."},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    print("status:", r.status_code)
    body = r.json()
    print("agent:", body.get("agent"))
    print("remaining:", body.get("remaining_requests"))
    print("response:", (body.get("response") or "")[:400])
    assert r.status_code == 200, body
    assert (body.get("response") or "").strip(), "empty agent response"

print("\n✅ chat e2e: Gemini respondió a través de la app real (auth + sesión + agente)")
