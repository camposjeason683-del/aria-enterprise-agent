"""
ARIA-OS: FastAPI Gateway + ADK Runner
Main entrypoint for the enterprise agentic system.
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

from src.agents.coordinator import build_root_agent  # noqa: E402
from src.config import ALLOWED_AUDIO_TYPES, ALLOWED_IMAGE_TYPES  # noqa: E402
from src.config import APP_NAME, MAX_FILE_SIZE, MAX_MESSAGE_LENGTH  # noqa: E402
from src.infra.db import close_supabase, get_supabase  # noqa: E402
from src.infra.logger import log_error, log_info  # noqa: E402
from src.infra.rate_limiter import rate_limiter  # noqa: E402


# ─── Lifecycle ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_info("🟢 ARIA-OS starting up")
    await get_supabase()  # Warm up connection
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
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ─── ADK Runner ──────────────────────────────────────────────────────
root_agent = build_root_agent()
session_service = InMemorySessionService()
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


# ─── Kill Switch ─────────────────────────────────────────────────────
async def is_ai_active() -> bool:
    """Read the kill switch flag from the database with auto-reconnect retry."""
    for attempt in range(2):
        try:
            client = await get_supabase()
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
    return False



# ─── Helper: Session management ─────────────────────────────────────
async def get_or_create_session(user_id: str, session_id: str = ""):
    session = None
    if session_id:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id or None
        )
    return session


# ─── Helper: Upload to Supabase Storage ─────────────────────────────
async def save_to_storage(data: bytes, filename: str) -> str:
    client = await get_supabase()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"uploads/{ts}_{filename}"
    await client.storage.from_("aria-artifacts").upload(path, data)
    url = client.storage.from_("aria-artifacts").get_public_url(path)
    return url


# ─── Chat Endpoint (Multimodal) ─────────────────────────────────────
@app.post("/api/v1/chat")
async def chat(
    message: str = Form(""),
    session_id: str = Form(""),
    user_id: str = Form("default"),
    file: UploadFile | None = File(None),
):
    start = time.time()

    # 1. Kill Switch
    if not await is_ai_active():
        raise HTTPException(503, "ARIA está desactivada por el administrador.")

    # 2. Rate Limit
    if not rate_limiter.is_allowed(user_id):
        raise HTTPException(
            429,
            f"Límite de solicitudes excedido. "
            f"Quedan {rate_limiter.remaining(user_id)} intentos.",
        )

    # 3. Build multimodal parts
    parts: list[types.Part] = []

    if message.strip():
        if len(message) > MAX_MESSAGE_LENGTH:
            raise HTTPException(400, f"Mensaje demasiado largo (máx {MAX_MESSAGE_LENGTH} chars).")
        parts.append(types.Part(text=message.strip()))

    if file:
        content_bytes = await file.read()
        if len(content_bytes) > MAX_FILE_SIZE:
            raise HTTPException(413, "Archivo excede 10MB.")

        mime = file.content_type or "application/octet-stream"

        if mime in ALLOWED_IMAGE_TYPES:
            parts.append(types.Part.from_bytes(data=content_bytes, mime_type=mime))
            if not message.strip():
                parts.append(types.Part(text="Analiza esta imagen."))
        elif mime in ALLOWED_AUDIO_TYPES:
            # Audio → transcribe then send as text
            try:
                from src.tools.audio import transcribe_audio
                transcript = await transcribe_audio(content_bytes, mime)
                parts.append(types.Part(text=f"[Transcripción de audio]: {transcript}"))
            except Exception:
                parts.append(types.Part(text="[Audio recibido pero no pudo ser transcrito]"))
        else:
            artifact_url = await save_to_storage(content_bytes, file.filename or "file")
            parts.append(
                types.Part(
                    text=f"[Archivo adjunto]: {file.filename} "
                    f"({len(content_bytes)} bytes). URL: {artifact_url}"
                )
            )

    if not parts:
        raise HTTPException(400, "Envía un mensaje, imagen o archivo.")

    # 4. Session
    session = await get_or_create_session(user_id, session_id)

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

    # 6. Usage log (fire-and-forget)
    try:
        client = await get_supabase()
        await client.table("aria_usage_log").insert(
            {
                "user_id": user_id,
                "session_id": session.id,
                "agent": last_agent,
                "message_preview": message[:100] if message else "[file]",
                "response_time_ms": duration,
                "input_type": "image" if file and file.content_type in ALLOWED_IMAGE_TYPES
                else "audio" if file and file.content_type in ALLOWED_AUDIO_TYPES
                else "file" if file
                else "text",
            }
        ).execute()
    except Exception:
        pass  # Non-critical

    return {
        "response": "\n".join(response_parts),
        "session_id": session.id,
        "agent": last_agent,
        "response_time_ms": duration,
        "remaining_requests": rate_limiter.remaining(user_id),
    }


# ─── Admin Endpoints ─────────────────────────────────────────────────
@app.post("/api/v1/admin/kill-switch")
async def toggle_kill_switch(active: bool):
    client = await get_supabase()
    await (
        client.table("system_config")
        .upsert({"key": "ai_active", "value": str(active).lower()})
        .execute()
    )
    log_info(f"Kill switch toggled: {active}")
    return {"ai_active": active}


@app.get("/api/v1/proposals")
async def list_proposals(status: str = "pending"):
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
async def approve_proposal(proposal_id: str, user_id: str = "admin"):
    client = await get_supabase()
    await (
        client.table("aria_proposals")
        .update(
            {
                "status": "approved",
                "approved_by": user_id,
                "approved_at": datetime.now().isoformat(),
            }
        )
        .eq("id", proposal_id)
        .execute()
    )
    return {"status": "approved", "proposal_id": proposal_id}


@app.post("/api/v1/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, reason: str = ""):
    client = await get_supabase()
    await (
        client.table("aria_proposals")
        .update({"status": "rejected", "rejection_reason": reason})
        .eq("id", proposal_id)
        .execute()
    )
    return {"status": "rejected", "proposal_id": proposal_id}


@app.post("/api/v1/proposals/{proposal_id}/execute")
async def execute_proposal(proposal_id: str):
    from src.tools.strategic import execute_approved_proposal
    res = await execute_approved_proposal(proposal_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@app.post("/api/v1/proposals/{proposal_id}/comment")
async def add_proposal_comment(
    proposal_id: str,
    content: str = Form(...),
    author: str = Form("admin")
):
    client = await get_supabase()
    
    # 1. Insert the user's comment
    await client.table("proposal_comments").insert({
        "proposal_id": proposal_id,
        "author": author,
        "content": content
    }).execute()
    
    # 2. Check if AI active
    if not await is_ai_active():
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



@app.post("/api/v1/cron/morning-brief")
async def trigger_morning_brief(user_id: str = "system_cron"):
    # Target morning_brief pipeline directly
    session = await get_or_create_session(user_id, "cron_session")
    
    response_parts = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="Genera el reporte de la mañana.")])
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)
                    
    log_info("Morning brief cron executed", user_id=user_id)
    return {"status": "success", "pipeline_output": "\n".join(response_parts)}


@app.post("/api/v1/cron/proactive-sweep")
async def trigger_proactive_sweep(user_id: str = "system_cron"):
    # Run the proactive pipeline to scan for stockouts & delayed OCs
    session = await get_or_create_session(user_id, "proactive_session")
    
    response_parts = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="SISTEMA: EJECUTAR BARRIDO PROACTIVO. Llama obligatoriamente a la herramienta `execute_proactive_sweep_auto` para realizar la consolidación, cálculos matemáticos y registro de propuestas de reabastecimiento y liquidación directamente en la base de datos con toda la lista de items. NUNCA intentes registrar propuestas manualmente ni fragmentadas en este barrido. Una vez ejecutada, presenta un resumen ordenado y profesional de las propuestas registradas.")])
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)
                    
    log_info("Proactive sweep cron executed", user_id=user_id)
    return {"status": "success", "pipeline_output": "\n".join(response_parts)}


@app.get("/api/v1/health")
async def health():
    db_ok = False
    try:
        client = await get_supabase()
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
