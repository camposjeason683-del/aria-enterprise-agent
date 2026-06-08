"""
ARIA-OS: FastAPI Gateway + ADK Runner
Main entrypoint for the enterprise agentic system.
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

import json

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.genai import types

load_dotenv()

from src.agents.coordinator import build_root_agent  # noqa: E402
from src.config import ALLOWED_AUDIO_TYPES, ALLOWED_IMAGE_TYPES  # noqa: E402
from src.config import APP_NAME, MAX_FILE_SIZE, MAX_MESSAGE_LENGTH  # noqa: E402
from src.infra.auth import require_tenant  # noqa: E402
from src.infra.db import close_supabase, get_supabase, get_system_client  # noqa: E402
from src.infra.logger import log_error, log_info  # noqa: E402
from src.infra.rate_limiter import check_rate_limit, rate_limiter  # noqa: E402
from src.infra.session_insforge import InsForgeSessionService  # noqa: E402
from src.infra.tenant_context import TenantContext  # noqa: E402
from src.infra.tenants import list_active_tenants, resolve_tenant_tier  # noqa: E402
from src.infra.cron_runner import run_for_tenant  # noqa: E402


# ─── Lifecycle ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # No warm-up call here: get_supabase() is now tenant-scoped and there is no
    # tenant context at startup. The shared InsForge HTTP client is created lazily.
    from src.infra.observability import init_observability

    init_observability()  # Sentry if SENTRY_DSN is set; no-op otherwise (M4)
    log_info("🟢 ARIA-OS starting up")
    yield
    log_info("🔴 ARIA-OS shutting down")
    await close_supabase()


# ─── App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="ARIA-OS — Enterprise Agentic Operating System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:3000"
    ).split(","),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


async def _asgi_json(send, status: int, payload: dict) -> None:
    """Send a minimal JSON response directly from pure-ASGI middleware."""
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


class _CopilotKitTenantMiddleware:
    """Pure-ASGI middleware: for the CopilotKit agent path (which is mounted by
    ag_ui_adk and has no FastAPI dependency to run require_tenant), verify the
    forwarded JWT and seed the tenant contextvar in the SAME task as the endpoint
    so the agent's tools stay RLS-scoped. Must be pure-ASGI (not BaseHTTPMiddleware)
    so the contextvar propagates to the handler."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").startswith(
            "/api/v1/copilotkit"
        ):
            auth = ""
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    auth = v.decode()
                    break
            if auth.startswith("Bearer "):
                try:
                    from src.infra.auth import (
                        resolve_tenant_membership,
                        verify_insforge_jwt,
                    )
                    from src.infra.tenant_context import TenantContext, set_current

                    token = auth.removeprefix("Bearer ").strip()
                    claims = verify_insforge_jwt(token)
                    uid = claims.get("sub")
                    if uid:
                        m = await resolve_tenant_membership(uid)
                        set_current(
                            TenantContext(
                                user_id=uid,
                                tenant_id=m["tenant_id"],
                                role=m["role"],
                                jwt=token,
                            )
                        )
                except Exception as exc:
                    log_error("CopilotKit tenant middleware: auth failed", error=str(exc))
            # F1/C3: fail closed when no tenant context got established and the demo
            # fallback is disabled (prod) — reject instead of silently running as the
            # demo tenant. Local dev keeps zero-friction via ARIA_ALLOW_DEMO_FALLBACK.
            from src.infra.db import _ALLOW_DEMO_FALLBACK
            from src.infra.tenant_context import current as _cur_ctx0

            if _cur_ctx0() is None and not _ALLOW_DEMO_FALLBACK:
                return await _asgi_json(send, 401, {"detail": "Autenticación requerida."})
            # C2: enforce the kill switch + rate limit on the agent path too —
            # ag_ui_adk mounts this endpoint outside the FastAPI deps that gate
            # /api/v1/chat, so without this the sandbox runs the agents unthrottled
            # and can't be stopped by the kill switch.
            try:
                _active = await is_ai_active()
            except KillSwitchUnavailable:
                return await _asgi_json(send, 503, {"detail": "Servicio temporalmente no disponible."})
            if not _active:
                return await _asgi_json(send, 503, {"detail": "ARIA está desactivada por el administrador."})
            from src.infra.tenant_context import current as _current_ctx
            _ctx = _current_ctx()
            if _ctx is not None:
                try:
                    _tier = await resolve_tenant_tier(_ctx.tenant_id)
                    _rate = await check_rate_limit(_ctx.tenant_id, _ctx.user_id, _tier)
                    if not _rate.allowed:
                        return await _asgi_json(send, 429, {"detail": "Límite de solicitudes excedido para tu plan."})
                except Exception as exc:
                    log_error("CopilotKit rate-limit check failed", error=str(exc))
        await self.app(scope, receive, send)


app.add_middleware(_CopilotKitTenantMiddleware)

# ─── ADK Runner ──────────────────────────────────────────────────────
root_agent = build_root_agent()
# Durable, multi-instance session storage (write-through to InsForge).
session_service = InsForgeSessionService()
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


# ─── Middleware: Request Timing ──────────────────────────────────────
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 2)
    response.headers["X-Response-Time-Ms"] = str(duration)
    return response


# ─── Health ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """E3: liveness probe (was 404). Used by Render/Cloud Run health checks —
    deliberately unauthenticated and dependency-free so it stays green during a DB
    blip (the kill switch / readiness is a separate concern)."""
    return {"status": "ok"}


# ─── Kill Switch ─────────────────────────────────────────────────────
class KillSwitchUnavailable(Exception):
    """H4: raised when the kill-switch config can't be READ (vs. an actual 'off').
    Lets callers distinguish a transient DB outage (→ 503 'temporarily unavailable')
    from an admin disable (→ 503 'desactivada por el administrador')."""


async def is_ai_active() -> bool:
    """Read the kill switch flag with auto-reconnect retry. Raises
    KillSwitchUnavailable if the config can't be read (so a DB blip is reported as a
    transient outage, not misreported as 'the admin turned ARIA off')."""
    for attempt in range(2):
        try:
            client = get_system_client()
            res = (
                await client.table("system_config")
                .select("value")
                .eq("key", "ai_active")
                .limit(1)
                .execute()
            )
            return bool(res.data and res.data[0]["value"] == "true")
        except Exception as e:
            log_error(f"Kill switch check failed (attempt {attempt+1}): {e}")
            if attempt == 0:
                await close_supabase()
    raise KillSwitchUnavailable("kill switch config unreadable")



# ─── Helper: Session management ─────────────────────────────────────
async def get_or_create_session(
    user_id: str, session_id: str = "", state: dict | None = None
):
    session = None
    if session_id:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    if not session:
        # `state` seeds tenant_id/user_id/role into the ADK session (read by
        # tools and persisted to agent_sessions).
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id or None, state=state
        )
    return session


# ─── Helper: Upload to storage ──────────────────────────────────────
async def save_to_storage(data: bytes, filename: str) -> str:
    # TODO(storage/S6): migrate artifact uploads to InsForge storage. Until then,
    # attachments beyond image/audio are not persisted (the chat text/image/audio
    # path is unaffected).
    raise HTTPException(
        501, "El almacenamiento de archivos se está migrando a InsForge (pendiente)."
    )


async def require_active_subscription(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    """Gate the product on the tenant's subscription (M7). A past_due/canceled tenant
    gets 402 — the load-bearing fix for 'canceled tenant still works'. Billing routes
    stay open so they can reactivate."""
    from src.infra.billing import resolve_subscription_status, subscription_active

    status = await resolve_subscription_status(tenant.tenant_id)
    if not subscription_active(status):
        raise HTTPException(402, "Suscripción inactiva. Reactivá tu plan para seguir usando ARIA.")
    return tenant


# ─── Chat Endpoint (Multimodal) ─────────────────────────────────────
@app.post("/api/v1/chat")
async def chat(
    message: str = Form(""),
    session_id: str = Form(""),
    file: UploadFile | None = File(None),
    files: list[UploadFile] = File(default=[]),
    tenant: TenantContext = Depends(require_active_subscription),
):
    start = time.time()
    # Identity comes from the verified JWT (never a client-supplied form field).
    user_id = tenant.user_id

    # 1. Kill Switch (H4: distinguish 'off' from 'config unreadable')
    try:
        _ai_active = await is_ai_active()
    except KillSwitchUnavailable:
        raise HTTPException(503, "Servicio temporalmente no disponible. Reintentá en unos segundos.")
    if not _ai_active:
        raise HTTPException(503, "ARIA está desactivada por el administrador.")

    # 2. Rate limit (per tenant+user, by subscription tier; shared counter)
    tier = await resolve_tenant_tier(tenant.tenant_id)
    rate = await check_rate_limit(tenant.tenant_id, user_id, tier)
    if not rate.allowed:
        raise HTTPException(429, "Límite de solicitudes excedido para tu plan.")

    # 3. Build multimodal parts
    parts: list[types.Part] = []

    if message.strip():
        if len(message) > MAX_MESSAGE_LENGTH:
            raise HTTPException(400, f"Mensaje demasiado largo (máx {MAX_MESSAGE_LENGTH} chars).")
        parts.append(types.Part(text=message.strip()))

    # Files: image / audio / video / PDF / text are analysed NATIVELY by Gemini
    # (inline, or the Files API when large). Accepts a single `file` or many `files`.
    from src.tools.multimodal import UPLOAD_MAX, build_file_part

    uploads = ([file] if file else []) + [f for f in (files or []) if f]
    had_media = False
    for up in uploads:
        content_bytes = await up.read()
        if len(content_bytes) > UPLOAD_MAX:
            raise HTTPException(413, f"'{up.filename}' excede el máximo permitido ({UPLOAD_MAX // 1024 // 1024}MB).")
        part, note = await build_file_part(content_bytes, up.filename or "", up.content_type)
        if part is not None:
            parts.append(part)
            had_media = True
        else:
            parts.append(types.Part(text=note))  # unsupported → labelled note, never silent
        log_info("chat attachment", agent="chat", tool=note)

    if had_media and not message.strip():
        parts.append(types.Part(text="Analizá el/los archivo(s) adjunto(s) y dame el contexto relevante para mi negocio."))

    if not parts:
        raise HTTPException(400, "Envía un mensaje, imagen o archivo.")

    # 4. Session (seed tenant identity into ADK state for tools + persistence)
    session = await get_or_create_session(
        user_id,
        session_id,
        state={"tenant_id": tenant.tenant_id, "user_id": user_id, "role": tenant.role},
    )

    # 5. Run Agent (with retry-backoff for 429/503)
    response_parts: list[str] = []
    last_agent = "kernel"
    max_retries = 3
    base_delay = 5  # seconds
    last_error = None

    for attempt in range(max_retries):
        response_parts = []
        last_agent = "kernel"
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=types.Content(role="user", parts=parts),
            ):
                if event.author and event.author != last_agent:
                    log_info(
                        f"➡️ [TRANSICIÓN] El flujo pasa al agente/nodo: '{event.author}'",
                        agent=event.author,
                        session_id=session.id,
                        user_id=user_id,
                    )
                    last_agent = event.author

                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call:
                            log_info(
                                f"🛠️ [HERRAMIENTA] Agente '{event.author}' ejecutando tool '{part.function_call.name}'",
                                agent=event.author,
                                tool=part.function_call.name,
                                session_id=session.id,
                                user_id=user_id,
                                args=str(part.function_call.args)[:300]
                            )
                        if part.text:
                            response_parts.append(part.text)
            break  # ── Success: exit retry loop
        except Exception as e:
            err_str = str(e)
            last_error = e
            is_retriable = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "503" in err_str
                or "UNAVAILABLE" in err_str
            )
            if is_retriable and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 5s, 10s, 20s
                log_error(
                    f"Agent hit retriable error (attempt {attempt+1}/{max_retries}), "
                    f"retrying in {delay}s: {err_str[:120]}",
                    user_id=user_id,
                )
                await asyncio.sleep(delay)
            else:
                log_error(f"Agent execution failed: {err_str}", user_id=user_id)
                raise HTTPException(
                    status_code=500,
                    detail=f"Error en la ejecución del agente: {err_str}"
                )

    duration = round((time.time() - start) * 1000, 2)
    log_info(
        "Chat completed",
        user_id=user_id,
        session_id=session.id,
        agent=last_agent,
        duration_ms=duration,
    )

    # 6. Usage log (fire-and-forget; system table, no PII in the payload)
    try:
        client = get_system_client()
        await client.table("aria_usage_log").insert(
            {
                "tenant_id": tenant.tenant_id,
                "user_id": user_id,
                "agent": last_agent,
                "response_time_ms": duration,
            }
        ).execute()
    except Exception:
        pass  # Non-critical

    return {
        "response": "\n".join(response_parts),
        "session_id": session.id,
        "agent": last_agent,
        "response_time_ms": duration,
        "remaining_requests": rate.remaining,
    }


# ─── Admin Endpoints ─────────────────────────────────────────────────
async def require_admin(tenant: TenantContext = Depends(require_tenant)) -> TenantContext:
    """F3: gate privileged actions (proposal approve/reject/execute) to admins.
    Employees are tenant members but must not approve/execute strategic proposals
    (which create real purchase_order_drafts)."""
    if tenant.role != "admin":
        raise HTTPException(403, "Acción permitida solo para administradores.")
    return tenant


@app.post("/api/v1/admin/kill-switch")
async def toggle_kill_switch(
    active: bool, tenant: TenantContext = Depends(require_tenant)
):
    if tenant.role != "admin":
        raise HTTPException(403, "Solo un admin puede usar el kill switch.")
    client = get_system_client()
    await (
        client.table("system_config")
        .upsert({"key": "ai_active", "value": str(active).lower()})
        .execute()
    )
    log_info(f"Kill switch toggled: {active}")
    return {"ai_active": active}


@app.get("/api/v1/proposals")
async def list_proposals(
    status: str = "pending", tenant: TenantContext = Depends(require_tenant)
):
    client = await get_supabase()
    res = (
        await client.table("aria_proposals")
        .select("*")
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
    )
    return {"proposals": res.data}


@app.post("/api/v1/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str, tenant: TenantContext = Depends(require_admin)
):
    client = await get_supabase()
    await (
        client.table("aria_proposals")
        .update(
            {
                "status": "approved",
                "approved_by": tenant.user_id,
                "approved_at": datetime.now().isoformat(),
            }
        )
        .eq("id", proposal_id)
        .execute()
    )
    return {"status": "approved", "proposal_id": proposal_id}


@app.post("/api/v1/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    reason: str = "",
    tenant: TenantContext = Depends(require_admin),
):
    client = await get_supabase()
    await (
        client.table("aria_proposals")
        .update({"status": "rejected", "rejection_reason": reason})
        .eq("id", proposal_id)
        .execute()
    )
    return {"status": "rejected", "proposal_id": proposal_id}


@app.post("/api/v1/proposals/{proposal_id}/execute")
async def execute_proposal(
    proposal_id: str, tenant: TenantContext = Depends(require_admin)
):
    from src.tools.proposal_execution import apply_proposal_effects
    res = await apply_proposal_effects(proposal_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/v1/proposals/{proposal_id}/comment")
async def add_proposal_comment(
    proposal_id: str,
    content: str = Form(...),
    author: str = Form("admin"),
    tenant: TenantContext = Depends(require_tenant),
):
    client = await get_supabase()
    
    # 1. Insert the user's comment
    await client.table("proposal_comments").insert({
        "proposal_id": proposal_id,
        "author": author,
        "content": content
    }).execute()
    
    # 2. Check if AI active (H4: tolerate a transient config-read outage)
    try:
        _comment_ai_active = await is_ai_active()
    except KillSwitchUnavailable:
        _comment_ai_active = False
    if not _comment_ai_active:
        return {
            "status": "success",
            "agent_responded": False,
            "detail": "Kernel ARIA inactivo. No se generó respuesta del agente."
        }

    try:
        # 3. Retrieve the proposal
        prop_res = await client.table("aria_proposals").select("*").eq("id", proposal_id).single().execute()
        if not prop_res.data:
            raise HTTPException(status_code=404, detail="Propuesta no encontrada")
        proposal = prop_res.data

        # 4. Retrieve all comments including the new one
        comments_res = await client.table("proposal_comments").select("*").eq("proposal_id", proposal_id).order("created_at", desc=False).execute()
        comments = comments_res.data or []

        # 5. Format comment history
        history_str = ""
        for c in comments:
            history_str += f"- {c['author']}: {c['content']}\n"

        # 6. Construct prompt
        prompt = f"""
[CONTEXTO DE LA PROPUESTA]
ID: {proposal['id']}
Título: {proposal['title']}
Problema: {proposal['problem']}
Acción Propuesta: {proposal['proposed_action']}
Impacto Estimado: {proposal.get('estimated_impact', 'No especificado')}
Riesgo: {proposal.get('risk', 'No especificado')}
Notas: {proposal.get('notes', 'Ninguna')}
Categoría: {proposal.get('category', 'Reabastecimiento')}

[HISTORIAL DE DEBATE EN EL MURO]
{history_str}

[ÚLTIMO COMENTARIO RECIBIDO]
El usuario ({author}) acaba de comentar en el muro debatiendo tu propuesta:
"{content}"

[INSTRUCCIÓN]
Como StrategicAdvisor (el COO virtual de ARIA-OS) de la empresa, debes responder de forma directa, profesional, y ejecutiva a este último comentario.
- Si el usuario te cuestiona o te debate, justifica tu postura analizando los pros y contras basándote en la información dada.
- Si los argumentos del comprador son sólidos y sugieren un cambio lógico, acéptalo con profesionalismo y dile que puede editar los campos correspondientes de la propuesta arriba.
- Mantén tu respuesta concisa (máximo 2 párrafos). Dirígete directamente al Comprador en español. No uses introducciones redundantes ni rellenos.
"""

        # 7. Invoke StrategicAdvisor directly
        from src.agents.strategic_advisor import strategic_advisor
        from google.adk.runners import Runner

        advisor_runner = Runner(
            agent=strategic_advisor,
            app_name=APP_NAME,
            session_service=session_service,
        )

        response_parts = []
        async for event in advisor_runner.run_async(
            user_id="proposal_debate",
            session_id=f"debate_{proposal_id}",
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_parts.append(part.text)

        agent_reply = "\n".join(response_parts).strip()

        # 8. Save Agent response if non-empty
        if agent_reply:
            await client.table("proposal_comments").insert({
                "proposal_id": proposal_id,
                "author": "StrategicAdvisor",
                "content": agent_reply
            }).execute()

        return {
            "status": "success",
            "agent_responded": True,
            "agent_reply": agent_reply
        }

    except Exception as e:
        log_error(f"Error in proposal debate generation: {e}")
        return {
            "status": "success",
            "agent_responded": False,
            "error": str(e)
        }



# ─── Automation rules (if-this-then-that) ────────────────────────────────────
@app.get("/api/v1/automation-rules")
async def list_automation_rules(tenant: TenantContext = Depends(require_tenant)):
    client = await get_supabase()
    res = (
        await client.table("automation_rules")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return {"rules": res.data}


@app.post("/api/v1/automation-rules")
async def create_automation_rule(
    name: str = Form(...),
    metric: str = Form(...),
    op: str = Form(...),
    threshold: float = Form(...),
    action: str = Form("create_proposal"),
    tenant: TenantContext = Depends(require_admin),
):
    from src.tools.automation import SUPPORTED_METRICS

    if metric not in SUPPORTED_METRICS:
        raise HTTPException(400, f"Métrica no soportada: {metric}. Opciones: {list(SUPPORTED_METRICS)}")
    if op not in (">", "<", ">=", "<=", "=="):
        raise HTTPException(400, "Operador inválido (usá >, <, >=, <=, ==).")
    client = await get_supabase()
    res = (
        await client.table("automation_rules")
        .insert(
            {
                "tenant_id": tenant.tenant_id,
                "name": name,
                "metric": metric,
                "op": op,
                "threshold": threshold,
                "action": action,
                "enabled": True,
            }
        )
        .execute()
    )
    return {"status": "created", "rule": (res.data or [None])[0]}


@app.delete("/api/v1/automation-rules/{rule_id}")
async def delete_automation_rule(
    rule_id: str, tenant: TenantContext = Depends(require_admin)
):
    client = await get_supabase()
    await client.table("automation_rules").delete().eq("id", rule_id).execute()
    return {"status": "deleted", "rule_id": rule_id}


# ── Self-serve signup (M5) ───────────────────────────────────────────────────
@app.post("/api/v1/signup")
async def signup(payload: dict = Body(...)):
    """Public: create the auth user, then a tenant + admin membership ATOMICALLY
    (RPC). Idempotent — re-running for an existing user completes any missing
    tenant/membership (fixes the F6 orphan-tenant bug that disabled signup)."""
    import httpx

    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    company = (payload.get("company_name") or "").strip()
    if not email or not password or not company:
        raise HTTPException(400, "Faltan email, password o company_name.")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres.")

    url = os.environ["INSFORGE_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(f"{url}/api/auth/users?client_type=server",
                            json={"email": email, "password": password, "name": company})
        if r.status_code == 409:  # already registered → sign in (idempotent)
            r = await http.post(f"{url}/api/auth/sessions?client_type=server",
                                json={"email": email, "password": password})
        if r.status_code >= 400:
            raise HTTPException(400, "No se pudo crear/autenticar la cuenta (¿email ya registrado con otra clave?).")
        d = r.json()

    uid = (d.get("user") or {}).get("id")
    if not uid:
        raise HTTPException(500, "Respuesta de autenticación inesperada.")

    admin = get_system_client()
    m = await admin.table("tenant_users").select("tenant_id").eq("user_id", uid).limit(1).execute()
    if m.data:  # existing membership (idempotent re-run / previously orphaned user)
        tid, created = m.data[0]["tenant_id"], False
    else:
        rpc = await admin.rpc("create_tenant_with_admin",
                              {"p_user_id": uid, "p_company_name": company})
        data = rpc.data
        if isinstance(data, str):
            tid = data
        elif isinstance(data, list) and data:
            tid = data[0] if isinstance(data[0], str) else data[0].get("create_tenant_with_admin")
        elif isinstance(data, dict):
            tid = data.get("create_tenant_with_admin") or data.get("id")
        else:
            tid = None
        created = True

    log_info("signup", user_id=uid, tenant_id=tid, agent="auth")
    return {"status": "ok", "user_id": uid, "tenant_id": tid, "tenant_created": created,
            "accessToken": d.get("accessToken"), "refreshToken": d.get("refreshToken")}


# ── Data ingestion: CSV / Google-Sheets import (M2) ──────────────────────────
def _parse_mapping(mapping: str) -> dict | None:
    if not mapping:
        return None
    try:
        m = json.loads(mapping)
        return m if isinstance(m, dict) and m else None
    except Exception:
        raise HTTPException(400, "mapping inválido (debe ser JSON).")


@app.post("/api/v1/import/preview")
async def import_preview(
    file: UploadFile = File(...), mapping: str = Form(""),
    tenant: TenantContext = Depends(require_admin),
):
    """Parse (robust: .xlsx/csv, auto delimiter+encoding) + validate WITHOUT committing —
    detected headers + mapping + sample + rejected rows + possible duplicates."""
    from src.tools.importers import preview_table

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "Archivo demasiado grande (máx 10MB).")
    return preview_table(content, file.filename or "", _parse_mapping(mapping))


@app.post("/api/v1/import/csv")
async def import_csv_route(
    file: UploadFile = File(...), mapping: str = Form(""),
    tenant: TenantContext = Depends(require_admin),
):
    """Parse + validate + ingest a file (.csv/.xlsx) for the caller's tenant (compiles the ledger)."""
    from src.tools.importers import import_table

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "Archivo demasiado grande (máx 10MB).")
    return await import_table(content, file.filename or "", _parse_mapping(mapping))


@app.post("/api/v1/integrations/google-sheet")
async def import_google_sheet(payload: dict = Body(...), tenant: TenantContext = Depends(require_admin)):
    """Fetch a PUBLIC Google Sheet as CSV and ingest it for the caller's tenant."""
    from src.tools.importers import connect_google_sheet

    url = payload.get("url") or ""
    if not url:
        raise HTTPException(400, "Falta 'url' del Google Sheet.")
    return await connect_google_sheet(url, payload.get("mapping"))


# ── WooCommerce connect (M6 onboarding) ──────────────────────────────────────
@app.post("/api/v1/integrations/woocommerce")
async def connect_woocommerce(payload: dict = Body(...), tenant: TenantContext = Depends(require_admin)):
    """Save the tenant's WooCommerce credentials (encrypted at rest). The scheduler's
    sync then pulls orders → ledger. Admin-only (require_admin)."""
    from src.tools.integrations import save_tenant_integration

    url = (payload.get("url") or "").strip()
    key = (payload.get("consumer_key") or "").strip()
    secret = (payload.get("consumer_secret") or "").strip()
    if not all([url, key, secret]):
        raise HTTPException(400, "Faltan url, consumer_key o consumer_secret.")
    await save_tenant_integration(tenant.tenant_id, url, key, secret)
    return {"status": "ok", "connected": "woocommerce"}


# ── Billing (M7) ─────────────────────────────────────────────────────────────
@app.post("/api/v1/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe webhook → update the tenant's subscription (idempotent). NOTE: signature
    verification needs STRIPE_WEBHOOK_SECRET (configure via insforge-cli); until then
    do not expose publicly."""
    from src.infra.billing import apply_stripe_event

    try:
        event = await request.json()
    except Exception:
        raise HTTPException(400, "Payload inválido.")
    return await apply_stripe_event(event)


@app.get("/api/v1/billing/status")
async def billing_status(tenant: TenantContext = Depends(require_tenant)):
    """The caller tenant's plan + subscription status (for the settings/billing UI)."""
    from src.infra.billing import resolve_subscription_status
    from src.infra.tenants import resolve_tenant_tier

    return {
        "subscription_status": await resolve_subscription_status(tenant.tenant_id),
        "tier": await resolve_tenant_tier(tenant.tenant_id),
    }


@app.post("/api/v1/billing/checkout")
async def billing_checkout(payload: dict = Body(...), tenant: TenantContext = Depends(require_admin)):
    """Start a Stripe Checkout for a plan. Requires Stripe configured in InsForge."""
    raise HTTPException(501, "Stripe aún no está configurado (configurá las keys con insforge-cli).")


# ── Owner dashboard + what-if forecast (M8) ──────────────────────────────────
@app.get("/api/v1/dashboard/summary")
async def dashboard_summary(tenant: TenantContext = Depends(require_active_subscription)):
    """Business pulse: pending decisions, recent anomalies, KPIs — one read for the home."""
    from src.tools.ledger_common import latest_ledger_date

    client = await get_supabase()
    props = (await client.table("aria_proposals")
             .select("id, title, category, urgency, status, created_at")
             .eq("status", "pending").order("created_at", desc=True).limit(10).execute()).data or []
    products = (await client.table("products").select("id, name").limit(500).execute()).data or []
    latest = await latest_ledger_date(client)
    anomalies = []
    try:
        from src.tools.anomaly import detect_anomalies
        an = await detect_anomalies(top_n=5)
        anomalies = (an.get("anomalies") or an.get("findings") or [])[:5]
    except Exception as e:  # noqa: BLE001 — dashboard must render even if a sub-query fails
        log_error("dashboard anomalies failed", error=str(e))
    return {
        "pending_proposals": props,
        "pending_count": len(props),
        "product_count": len(products),
        "products": [p.get("name") for p in products][:100],
        "latest_ledger_date": latest,
        "anomalies": anomalies,
    }


@app.get("/api/v1/forecast")
async def forecast_endpoint(
    product: str = "", days: int = 14, price: float = 0.0,
    tenant: TenantContext = Depends(require_active_subscription),
):
    """Forecast a product's demand. Pass ``price`` (> 0) for a what-if re-forecast (XREG)."""
    from src.tools.forecasting import forecast_sales

    return await forecast_sales(product, days, price_override=price)


# ── Purchase-order lifecycle (M3) ────────────────────────────────────────────
@app.post("/api/v1/purchase-orders/{po_id}/{action}")
async def transition_purchase_order(
    po_id: str, action: str, tenant: TenantContext = Depends(require_admin)
):
    """Move a PO forward: confirm → dispatch → deliver. Idempotent / order-checked."""
    if action not in ("confirm", "dispatch", "deliver"):
        raise HTTPException(400, "Acción inválida (confirm|dispatch|deliver).")
    from src.tools.purchase_orders import transition_po

    res = await transition_po(po_id, action)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


# Cron endpoints: an EXTERNAL scheduler (Render Cron / Cloud Scheduler) hits these
# with the shared secret. Each iterates the ACTIVE tenants and runs the job under a
# HEADLESS per-tenant context (run_for_tenant → admin client pinned to tenant_id),
# isolating per-tenant failures so one bad tenant never aborts the loop.
def _require_cron_secret(provided: str | None) -> None:
    expected = os.environ.get("CRON_SECRET", "")
    if not expected or provided != expected:
        raise HTTPException(403, "Cron secret inválido o ausente.")


@app.post("/api/v1/cron/compile-ledger")
async def trigger_compile_ledger(x_cron_secret: str = Header(default="")):
    """KEYSTONE: compile each tenant's cached WooCommerce orders into the daily
    ledger. MUST run before proactive-sweep in the scheduler order — the sweep /
    forecast / anomalies all read the ledger this produces."""
    _require_cron_secret(x_cron_secret)
    from src.tools.ledger_etl import compile_ledger_for_tenant

    tenants = await list_active_tenants()
    results = []
    for t in tenants:
        tid = t["id"]
        try:
            r = await run_for_tenant(tid, lambda: compile_ledger_for_tenant())
            results.append({
                "tenant_id": tid, "status": "ok",
                "rows": r.get("rows", 0), "products_added": r.get("products_added", 0),
            })
        except Exception as e:  # noqa: BLE001 — one tenant must not abort the loop
            log_error("cron compile-ledger failed", tenant_id=tid, error=str(e))
            results.append({"tenant_id": tid, "status": "error"})
    log_info(f"cron compile-ledger ran for {len(tenants)} tenant(s)", agent="cron")
    return {"tenants": len(tenants), "results": results}


@app.post("/api/v1/cron/proactive-sweep")
async def trigger_proactive_sweep(x_cron_secret: str = Header(default="")):
    _require_cron_secret(x_cron_secret)
    from src.tools.strategic import execute_proactive_sweep_auto
    from src.tools.automation import evaluate_rules

    async def _tenant_tick() -> str:
        # Sweep + rule evaluation under ONE headless tenant context; independent so
        # one failing never aborts the other.
        status = "ok"
        try:
            await execute_proactive_sweep_auto()
        except Exception as e:  # noqa: BLE001
            log_error("cron sweep failed", error=str(e))
            status = "error"
        try:
            await evaluate_rules()
        except Exception as e:  # noqa: BLE001
            log_error("cron evaluate_rules failed", error=str(e))
        return status

    tenants = await list_active_tenants()
    results = []
    for t in tenants:
        tid = t["id"]
        try:
            status = await run_for_tenant(tid, _tenant_tick)
            results.append({"tenant_id": tid, "status": status})
        except Exception as e:  # noqa: BLE001 — one tenant must not abort the loop
            log_error("cron proactive-sweep failed", tenant_id=tid, error=str(e))
            results.append({"tenant_id": tid, "status": "error"})
    log_info(f"cron proactive-sweep ran for {len(tenants)} tenant(s)", agent="cron")
    return {"tenants": len(tenants), "results": results}


@app.post("/api/v1/cron/insight-sweep")
async def trigger_insight_sweep(x_cron_secret: str = Header(default="")):
    _require_cron_secret(x_cron_secret)
    from src.tools.anomaly import detect_anomalies

    tenants = await list_active_tenants()
    results = []
    for t in tenants:
        tid = t["id"]
        try:
            r = await run_for_tenant(tid, lambda: detect_anomalies())
            results.append({"tenant_id": tid, "status": "ok", "anomalies": r.get("count", 0)})
        except Exception as e:  # noqa: BLE001 — one tenant must not abort the loop
            log_error("cron insight-sweep failed", tenant_id=tid, error=str(e))
            results.append({"tenant_id": tid, "status": "error"})
    return {"tenants": len(tenants), "results": results}


@app.post("/api/v1/cron/morning-brief")
async def trigger_morning_brief(x_cron_secret: str = Header(default="")):
    _require_cron_secret(x_cron_secret)
    from src.tools.strategic import gather_full_business_snapshot

    tenants = await list_active_tenants()
    results = []
    for t in tenants:
        tid = t["id"]
        try:
            snap = await run_for_tenant(tid, lambda: gather_full_business_snapshot())
            results.append({"tenant_id": tid, "status": "ok", "snapshot": snap})
        except Exception as e:  # noqa: BLE001
            log_error("cron morning-brief failed", tenant_id=tid, error=str(e))
            results.append({"tenant_id": tid, "status": "error"})
    return {"tenants": len(tenants), "results": results}


@app.get("/api/v1/health")
async def health():
    db_ok = False
    try:
        client = get_system_client()
        await client.table("system_config").select("key").limit(1).execute()
        db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "ai_active": await is_ai_active(),
        "agents": 19,
        "version": "1.0.0",
    }


# ─── Identity + Canvas persistence (Fase 2, tenant-scoped) ──────────
@app.get("/api/v1/me")
async def me(tenant: TenantContext = Depends(require_tenant)):
    return {"user_id": tenant.user_id, "tenant_id": tenant.tenant_id, "role": tenant.role}


@app.get("/api/v1/canvas")
async def get_canvas(tenant: TenantContext = Depends(require_tenant)):
    """Load the caller's canvas workspace (RLS-scoped)."""
    client = await get_supabase()
    res = (
        await client.table("canvas_workspaces")
        .select("state")
        .eq("user_id", tenant.user_id)
        .limit(1)
        .execute()
    )
    return {"state": res.data[0]["state"] if res.data else None}


@app.put("/api/v1/canvas")
async def put_canvas(
    state: dict = Body(...), tenant: TenantContext = Depends(require_tenant)
):
    """Save the caller's canvas workspace (one per user; RLS-scoped)."""
    client = await get_supabase()
    existing = (
        await client.table("canvas_workspaces")
        .select("id")
        .eq("user_id", tenant.user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        await (
            client.table("canvas_workspaces")
            .update({"state": state})
            .eq("user_id", tenant.user_id)
            .execute()
        )
    else:
        await client.table("canvas_workspaces").insert(
            {"tenant_id": tenant.tenant_id, "user_id": tenant.user_id, "state": state}
        ).execute()
    return {"status": "ok"}


from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint

def _copilotkit_user_id(run_input) -> str:
    # F2: bind the ADK session identity to the VERIFIED tenant user (set by
    # _CopilotKitTenantMiddleware in the same task) instead of the client-supplied
    # thread_id, namespaced by tenant so sessions can't collide/leak across tenants.
    from src.infra.tenant_context import current as _cur

    ctx = _cur()
    if ctx is not None:
        return f"{ctx.tenant_id}:{ctx.user_id}"
    return f"thread_user_{getattr(run_input, 'thread_id', 'anon')}"


# Create the ADKAgent wrapper for CopilotKit
copilotkit_agent = ADKAgent(
    adk_agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
    user_id_extractor=_copilotkit_user_id,
)

# Mount it on FastAPI
add_adk_fastapi_endpoint(app, copilotkit_agent, path="/api/v1/copilotkit/default")

