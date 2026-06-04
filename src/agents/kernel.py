"""
ARIA-OS: Kernel Workflow (ADK 2.0)
Deterministic graph-based routing using google.adk.Workflow.

Replaces the legacy KernelAgent (custom BaseAgent) with a zero-cost Python
routing layer. Clear intents are dispatched to the correct analyst without
any LLM call. Ambiguous queries fall back to a mini-LLM coordinator.
"""
import json
import os
import re
from typing import Any
from google.adk import Workflow, Event, Context
from google.genai import types

from src.infra.logger import log_info, log_error

# ── Accent normalization helper ──────────────────────────────────────────────
def _normalize_text(text: str) -> str:
    """A simple Spanish-specific accent remover that preserves 'ñ' and 'Ñ'."""
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ü': 'u', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O',
        'Ú': 'U', 'Ü': 'U'
    }
    for accent, clean in replacements.items():
        text = text.replace(accent, clean)
    return text.lower()

# ── Intent keyword rules ─────────────────────────────────────────────────────
_INTENT_RULES = {
    "INVENTORY": {
        "stock minimo": 3, "libro mayor": 3, "ledger": 3,
        "stock": 2, "inventario": 3, "produccion": 2, "almacen": 2,
        "warehouse": 2, "existencia": 2, "agotado": 2, "existencias": 2,
        "unidades": 1, "disponible": 1, "falta": 1, "cuantas": 1, "cuantos": 1,
        "producto": 1, "productos": 1,
    },
    "DEMAND": {
        "pronostico de ventas": 5, "proyeccion de ventas": 5,
        "pronostico de demanda": 5, "proyeccion de demanda": 5,
        "forecast": 3, "pronostico": 3, "proyeccion": 3, "proyecciones": 3, "reorden": 3,
        "reposicion": 3, "dias de inventario": 3, "lead time": 3, "estacionalidad": 3,
        "reponer": 2, "alcanza": 2, "tendencia": 2, "proyectar": 2, "pronosticar": 2,
        "dias": 1, "futuro": 1,
    },
    "SALES": {
        "churn": 3, "cancelacion": 3, "retencion": 3, "revenue": 3,
        "facturacion": 3, "ticket promedio": 3,
        "ventas": 2, "vendimos": 2, "vendio": 2, "pedidos": 2, "ordenes": 2,
        "order": 2, "clientes": 2, "cliente": 2, "completados": 2, "pendientes": 2,
        "processing": 2, "ingreso": 2, "ingresos": 2,
        "ticket": 1, "compras": 1, "compra": 1,
    },
    "PROCUREMENT": {
        "orden de compra": 3, "supplier": 3, "submarca": 3,
        "proveedor": 3, "proveedores": 3,
        "compras": 2, "compra": 2, "marca": 2, "catalogo": 2, "suministro": 2,
        "polar": 1,
        "adquisicion": 1, "adquirir": 1,
    },
    "FINANCE": {
        "p&l": 3, "break even": 3, "punto de equilibrio": 3, "margen": 3, "rentabilidad": 3,
        "ganancia": 2, "costo": 2, "precio": 2, "presupuesto": 2, "financiero": 2,
        "finanzas": 2, "margenes": 2, "costos": 2, "precios": 2, "ganancias": 2,
        "dinero": 1, "valor": 1,
    },
    "RESEARCH": {
        "busca en internet": 3, "tasa de cambio": 3, "google": 3, "deep research": 3, "web search": 3,
        "investiga": 2, "mercado": 2, "competencia": 2, "regulacion": 2, "normativa": 2,
        "internet": 2, "dolar": 2,
        "buscar": 1, "web": 1,
    },
    "STRATEGIC": {
        "propuesta estrategica": 5, "recomendacion estrategica": 5,
        "analiza el negocio": 3, "estado general del negocio": 3, "vision general": 3,
        "que propones": 3, "recomendacion general": 3, "estrategia": 3, "estrategico": 3,
        "estrategica": 3, "propuesta": 3, "propuestas": 3,
        "oportunidad": 2, "riesgo global": 2, "recomendacion": 2, "analizar": 2, "negocio": 2,
        "estado": 1, "general": 1, "idea": 1,
    },
    "REPORT": {
        "genera un reporte": 3, "genera un pdf": 3, "exportar pdf": 3,
        "pdf": 2, "reporte": 2, "documento": 2, "informe": 2, "genera": 2, "exportar": 2,
        "archivo": 1, "crea": 1,
    },
    "AUDIT": {
        "verificar todo": 3, "resumen completo": 3, "como va todo": 3, "auditoria": 3, "auditar": 3,
        "estado general": 2, "auditoria general": 2, "verificar": 2,
        "resumen": 1, "todo": 1,
    },
    "GREETING": {
        "quien eres": 3, "hola": 3, "buenos dias": 3, "buenas tardes": 3, "buenas noches": 3,
        "hey": 2, "ayuda": 2, "help": 2, "que puedes hacer": 2,
        "holaa": 1,
    },
}

# ── Node 1: Zero-cost heuristic classifier ───────────────────────────────────
def _classify_heuristic(node_input: types.Content) -> str:
    """
    Pure Python keyword scorer using word boundaries, accent normalization,
    and compound weights.
    Receives the raw user Content object from the Workflow START node.
    Returns a routing intent string (e.g. 'INVENTORY', 'AMBIGUOUS').
    """
    text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text = " ".join(p.text for p in node_input.parts if p.text)

    # Intercept background system command before scoring
    if "sistema: ejecutar barrido proactivo" in text.lower():
        log_info("Intercepted proactive sweep command → PROACTIVE", agent="kernel")
        return "PROACTIVE"

    text = _normalize_text(text)

    scores = {intent: 0 for intent in _INTENT_RULES}
    for intent, kw_weights in _INTENT_RULES.items():
        score = 0
        for kw, weight in kw_weights.items():
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, text):
                score += weight
        scores[intent] = score

    # Avoid short-circuiting reports if there's any business domain keyword
    has_business_intent = any(
        scores.get(intent, 0) > 0 
        for intent in ["INVENTORY", "DEMAND", "SALES", "PROCUREMENT", "FINANCE", "STRATEGIC", "RESEARCH"]
    )
    if has_business_intent and "REPORT" in scores:
        scores["REPORT"] = 0

    max_score = max(scores.values()) if scores else 0
    if max_score == 0:
        return "AMBIGUOUS"

    best = max(scores, key=scores.get)

    # Word count safety check for short/vague queries
    words = [w for w in text.split() if w]
    if max_score == 2 and len(words) <= 3 and best != "GREETING":
        log_info(f"Heuristic routing: AMBIGUOUS (reason: weak short query '{text}')", agent="kernel")
        return "AMBIGUOUS"

    if max_score < 2 and best != "GREETING":
        log_info(f"Heuristic routing: AMBIGUOUS (reason: low max score {max_score})", agent="kernel")
        return "AMBIGUOUS"

    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) >= 2 and sorted_scores[1] > 0:
        diff = sorted_scores[0] - sorted_scores[1]
        if (sorted_scores[0] < 4 and diff <= 1) or (sorted_scores[0] >= 4 and diff <= 2):
            log_info(f"Heuristic routing: AMBIGUOUS (reason: close scores top {sorted_scores[0]} and next {sorted_scores[1]})", agent="kernel")
            return "AMBIGUOUS"

    log_info(f"Heuristic routing: {best} (score: {max_score})", agent="kernel")
    return best


# ── Node 2: Deterministic router (emits route Event) ─────────────────────────
def _router(node_input: str) -> Event:
    """
    Converts the classified intent string into an ADK 2.0 route Event.
    The Workflow graph uses this to dispatch to the correct node/agent.
    """
    return Event(route=node_input)


# ── Terminal Node: Greeting handler (zero LLM cost) ──────────────────────────
def _greeting_node() -> Event:
    """Returns a rich greeting message without invoking any AI model."""
    return Event(
        message=(
            "¡Hola! 👋 Soy **ARIA**, tu asistente empresarial inteligente.\n\n"
            "Puedo ayudarte con:\n"
            "- 📦 **Inventario** — stock, producción, alertas\n"
            "- 📈 **Forecasting** — proyecciones, puntos de reorden\n"
            "- 💰 **Ventas** — revenue, pedidos, clientes\n"
            "- 🏢 **Proveedores** — catálogo, compras\n"
            "- 💎 **Finanzas** — márgenes, P&L\n"
            "- 🔬 **Investigación** — búsqueda web en tiempo real\n"
            "- 🧠 **Estrategia** — análisis y propuestas con aprobación\n"
            "- 📄 **Reportes** — generación de PDFs\n\n"
            "¿En qué puedo ayudarte hoy?"
        )
    )


# ── State helpers for State objects and dictionaries ──────────────────────────
def _get_state_val(state, key, default=None):
    if state is None:
        return default
    if hasattr(state, "get"):
        return state.get(key, default)
    if hasattr(state, "__getitem__"):
        try:
            return state[key]
        except KeyError:
            return default
    return getattr(state, key, default)

def _set_state_val(state, key, val):
    if state is None:
        return
    if hasattr(state, "__setitem__"):
        state[key] = val
    elif hasattr(state, "update"):
        state.update({key: val})
    else:
        setattr(state, key, val)


# ── Node 3: Quality Control Supervisor ───────────────────────────────────────
def _run_qc_audit(audit_prompt: str) -> dict | None:
    """H1: run the QC audit through the configured AI backend (InsForge AI when set,
    else Gemini with a REAL model id). Returns parsed {approved, reason} or None on
    infra failure (the caller then degrades VISIBLY). Sync on purpose — the QC node is
    sync and already blocks on its model call; uses httpx.Client to mirror that."""
    import httpx

    insforge_url = os.environ.get("INSFORGE_URL")
    insforge_key = os.environ.get("INSFORGE_API_KEY")
    if insforge_url and insforge_key:
        try:
            model = os.environ.get("INSFORGE_AI_MODEL", "openai/gpt-4o-mini")
            with httpx.Client(timeout=60.0) as http:
                r = http.post(
                    insforge_url.rstrip("/") + "/api/ai/chat/completion",
                    headers={"Authorization": f"Bearer {insforge_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": audit_prompt}]},
                )
            if r.status_code >= 400:
                log_error(f"QC audit: InsForge AI HTTP {r.status_code}", body=r.text[:200])
                return None
            text = (r.json().get("text") or "").strip()
            if text.startswith("```"):  # tolerate code-fenced JSON
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            log_error(f"QC audit: InsForge AI error: {e}")
            return None
    try:
        from google.genai import Client

        client = Client(api_key=os.environ.get("GEMINI_API_KEY"))
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=audit_prompt,
            config={"response_mime_type": "application/json", "temperature": 0.0},
        )
        return json.loads(resp.text.strip())
    except Exception as e:
        log_error(f"QC audit: Gemini error: {e}")
        return None


def _quality_control_supervisor(ctx: Context, node_input: Any) -> Event:
    """
    Audits the logic and SQL queries executed by the analyst.
    If errors are found, rejects the response and routes back to the analyst.
    Otherwise, approves the response.
    """
    analysts = {
        "sales_analyst": "SALES",
        "finance_analyst": "FINANCE",
        "inventory_analyst": "INVENTORY",
        "demand_planner": "DEMAND",
        "procurement_analyst": "PROCUREMENT",
        "strategic_advisor": "STRATEGIC",
        "coordinator_llm": "AMBIGUOUS",
    }
    
    events = ctx.session.events if (hasattr(ctx, "session") and ctx.session) else []
    
    # 1. Identify which analyst just executed
    last_analyst = None
    for ev in reversed(events):
        if ev.author in analysts:
            last_analyst = ev.author
            break
            
    if not last_analyst:
        log_info("QC Supervisor: No analyst found in history. Auto-approving.", agent="supervisor")
        return Event(route="APPROVED")
        
    intent = analysts[last_analyst]
    
    # 2. Extract analyst's response text
    text_parts = []
    for ev in reversed(events):
        if ev.author == last_analyst and ev.content and ev.content.parts:
            for p in ev.content.parts:
                if p.text:
                    text_parts.append(p.text)
            if text_parts:
                break
    analyst_response = "\n".join(reversed(text_parts)) if text_parts else ""
    
    # 3. Extract SQL queries executed in the current turn
    last_user_idx = -1
    for i, ev in enumerate(events):
        if ev.author == "user":
            last_user_idx = i
            
    executed_queries = []
    start_idx = last_user_idx if last_user_idx != -1 else 0
    for ev in events[start_idx:]:
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if p.function_call and p.function_call.name == "execute_safe_read_query":
                    args = p.function_call.args
                    query = None
                    if isinstance(args, dict):
                        query = args.get("sql_query") or args.get("query")
                    elif hasattr(args, "sql_query"):
                        query = args.sql_query
                    elif hasattr(args, "query"):
                        query = args.query
                    elif hasattr(args, "get"):
                        query = args.get("sql_query") or args.get("query")
                    if query:
                        executed_queries.append(query)
                        
    queries_str = "\n---\n".join(executed_queries) if executed_queries else "Ninguna consulta SQL ejecutada."
    
    # Extract user query
    user_query = ""
    if last_user_idx != -1 and events[last_user_idx].content and events[last_user_idx].content.parts:
        user_query = " ".join(p.text for p in events[last_user_idx].content.parts if p.text)

    # Detect if user requested a report/PDF and save parameters in state
    query_lower = user_query.lower()
    wants_report = any(kw in query_lower for kw in ["pdf", "reporte", "documento", "informe"])
    if wants_report:
        _set_state_val(ctx.state, "temp:wants_report", True)
        if "churn" in query_lower:
            _set_state_val(ctx.state, "temp:report_type", "churn")
        elif "ventas" in query_lower or "sales" in query_lower:
            _set_state_val(ctx.state, "temp:report_type", "sales")
        elif "inventario" in query_lower or "stock" in query_lower:
            _set_state_val(ctx.state, "temp:report_type", "inventory")
        else:
            _set_state_val(ctx.state, "temp:report_type", "general")
        log_info(f"QC Supervisor: Flagged wants_report=True, type={_get_state_val(ctx.state, 'temp:report_type')}", agent="supervisor")
        
    # Check/Increment retry count
    retry_key = f"temp:retry_count_{last_analyst}"
    retry_count = _get_state_val(ctx.state, retry_key, 0)
    
    if retry_count >= 3:
        log_info(f"QC Supervisor: Retry limit ({retry_count}) reached for {last_analyst}. Force approving.", agent="supervisor")
        _set_state_val(ctx.state, retry_key, 0)  # C1: reset so the next turn starts fresh
        _set_state_val(ctx.state, "temp:approved_response", analyst_response)
        if wants_report or _get_state_val(ctx.state, "temp:wants_report", False):
            return Event(route="GENERATE_REPORT")
        return Event(route="APPROVED")
        
    # 4. Audit the analyst output (via the configured AI backend — see _run_qc_audit).
    audit_prompt = f"""
Eres el Supervisor de Control de Calidad (QC) de ARIA-OS. Tu trabajo es realizar una auditoría rigurosa de las consultas SQL y el código de análisis devuelto por el analista '{last_analyst}'.

[PREGUNTA DEL USUARIO]
{user_query}

[RESPUESTA PROPUESTA POR EL ANALISTA]
{analyst_response}

[QUERIES SQL EJECUTADAS EN ESTE TURNO]
{queries_str}

Debes evaluar si la lógica aplicada por el analista es 100% correcta metodológicamente y libre de errores. Presta especial atención a las siguientes reglas críticas de negocio:

1. **Cálculo de Churn (Tasa de Cancelación) de Clientes:**
   - Para calcular el Churn Rate de un periodo (ej. últimos 3 meses), se debe usar obligatoriamente un análisis de cohortes (CTE / JOIN).
   - Se debe identificar una base activa de clientes en el periodo Baseline (ej. compras válidas en el trimestre anterior) y verificar cuáles de ESOS MISMOS clientes NO realizaron compras en el periodo Target.
   - **ERROR METODOLÓGICO GRAVE:** Restar simplemente el total de clientes del final del de inicio (ej. Clientes Marzo - Clientes Mayo). Esto mide cambio neto, no retención/churn, e ignora a los clientes nuevos. Si el agente comete este error, DEBES RECHAZAR la respuesta.

2. **Lógica de Clientes Nuevos:**
   - Un cliente nuevo es aquel cuya primera compra histórica en la tienda ocurrió durante el periodo de interés (Target). No debe tener compras válidas previas.

3. **Lógica de Base de Datos y Columnas:**
   - La tabla es `wc_orders_cache`.
   - La columna para identificar clientes es `customer_name` (NO existe `customer_id`).
   - La columna de fecha de la transacción es `date_created` (NO usar `created_at` ni `transaction_date`).
   - Se deben filtrar estados inválidos: `status NOT IN ('cancelled', 'failed', 'trash', 'draft')`.

4. **Límite de Fila y Agregación:**
   - La herramienta `execute_safe_read_query` tiene un límite estricto de truncamiento de 200 filas.
   - Si el agente descargó todas las órdenes en bruto a Python para hacer el cruce en memoria, los datos están truncados y la métrica es falsa. Todo cálculo masivo debe ocurrir del lado de la base de datos (con COUNT, SUM, etc.) devolviendo una fila consolidada.

5. **Generación de Reportes / PDF:**
   - Si el usuario solicita un PDF o Reporte, el analista SOLO debe proporcionar el texto de análisis completo y detallado en formato markdown. El analista NO debe generar el PDF por sí mismo ni usar herramientas para ello. La plataforma se encargará de compilar el PDF de forma automática a partir del texto markdown aprobado por ti. Por lo tanto, APRUEBA la respuesta si el texto del análisis es correcto metodológicamente, ignorando el hecho de que no sea un archivo PDF todavía.

**INSTRUCCIONES DE SALIDA:**
Responde en un formato JSON estructurado con las siguientes claves:
- "approved": true/false
- "reason": "Una justificación clara en español del porqué de la decisión. Si es aprobado, deja esto vacío o indica 'Aprobado'. Si es rechazado, explica detalladamente el fallo metodológico, qué query o código está mal, y da la instrucción precisa de cómo corregirlo (por ejemplo, indicando que use la columna 'customer_name' en lugar de 'customer_id', o que aplique cohortes correctas)."

Responde ÚNICAMENTE con el bloque JSON, sin markdown, sin texto adicional alrededor.
"""
    audit_result = _run_qc_audit(audit_prompt)
    if audit_result is None:
        # H1: degrade VISIBLY instead of silently shipping unaudited output.
        log_error("QC Supervisor: audit backend unavailable — approving with a visible notice.")
        analyst_response = (
            "⚠️ _(Control de calidad no disponible — esta respuesta no fue auditada.)_\n\n"
            + analyst_response
        )
        approved = True
        reason = "QC no disponible"
    else:
        approved = audit_result.get("approved", True)
        reason = audit_result.get("reason", "")
        
    if approved:
        log_info(f"QC Supervisor: Approved output from {last_analyst}.", agent="supervisor")
        _set_state_val(ctx.state, retry_key, 0)  # C1: reset retry counter on success
        _set_state_val(ctx.state, "temp:approved_response", analyst_response)
        if wants_report or _get_state_val(ctx.state, "temp:wants_report", False):
            return Event(route="GENERATE_REPORT")
        return Event(route="APPROVED")
    else:
        new_retry_count = retry_count + 1
        _set_state_val(ctx.state, retry_key, new_retry_count)
        
        feedback_message = (
            f"❌ [CONTROL DE CALIDAD] Su respuesta ha sido rechazada por el supervisor de control de calidad.\n"
            f"Motivo del rechazo:\n{reason}\n\n"
            f"Por favor, revise su lógica, corrija las consultas SQL o código correspondiente de acuerdo a las indicaciones anteriores y vuelva a generar la respuesta. (Intento {new_retry_count}/3)"
        )
        log_info(f"QC Supervisor: REJECTED output from {last_analyst}. Route: REJECTED_{intent}. Reason: {reason}", agent="supervisor")
        return Event(route=f"REJECTED_{intent}", message=feedback_message)


# ── Node 4: Approved response terminal node ──────────────────────────────────
def _approved_node(ctx: Context, node_input: Any) -> Event:
    """
    Terminal node when response is approved. Emits the final approved response.
    Also triggers the skill synthesizer in the background to evaluate and reload skills.
    """
    approved_response = _get_state_val(ctx.state, "temp:approved_response", "")
    if not approved_response:
        # Fallback to last analyst event text
        last_analyst = None
        analysts = ["sales_analyst", "finance_analyst", "inventory_analyst", "demand_planner", "procurement_analyst", "strategic_advisor", "coordinator_llm"]
        events = ctx.session.events if (hasattr(ctx, "session") and ctx.session) else []
        for ev in reversed(events):
            if ev.author in analysts:
                last_analyst = ev.author
                break
        if last_analyst:
            text_parts = []
            for ev in reversed(events):
                if ev.author == last_analyst and ev.content and ev.content.parts:
                    for p in ev.content.parts:
                        if p.text:
                            text_parts.append(p.text)
                    if text_parts:
                        break
            approved_response = "\n".join(reversed(text_parts)) if text_parts else ""

    # Trigger dynamic skill synthesis in the background
    try:
        import asyncio
        from src.tools.skill_synthesizer import evaluate_and_synthesize_skill
        from src.tools.skills_loader import refresh_dynamic_skills
        from src.agents.sales_analyst import sales_analyst
        from src.agents.finance_analyst import finance_analyst
        from src.agents.inventory_analyst import inventory_analyst
        from src.agents.demand_planner import demand_planner
        from src.agents.procurement_analyst import procurement_analyst
        from src.agents.strategic_advisor import strategic_advisor

        events = ctx.session.events if (hasattr(ctx, "session") and ctx.session) else []

        async def run_synthesis_and_refresh():
            success = await evaluate_and_synthesize_skill(events)
            if success:
                refresh_dynamic_skills([
                    sales_analyst,
                    finance_analyst,
                    inventory_analyst,
                    demand_planner,
                    procurement_analyst,
                    strategic_advisor
                ])

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(run_synthesis_and_refresh())
        else:
            asyncio.run(run_synthesis_and_refresh())
    except Exception as e:
        log_error(f"Kernel approved node: Error launching skill synthesizer background task: {e}")
            
    return Event(message=approved_response)


# ── Kernel Workflow Builder ───────────────────────────────────────────────────
def build_kernel_workflow() -> Workflow:
    """
    Assembles and returns the ARIA-OS kernel as an ADK 2.0 Workflow.

    Architecture:
        START
          ↓ [_classify_heuristic] — Python function, zero LLM cost
          ↓ [_router]             — Emits Event(route=intent)
          ↓
        ┌────────────────────────────────────────────────────────────┐
        │  INVENTORY  → inventory_analyst (LlmAgent)                 │
        │  DEMAND     → demand_planner (LlmAgent)                    │
        │  SALES      → sales_analyst (LlmAgent)                     │
        │  PROCUREMENT→ procurement_analyst (LlmAgent)               │
        │  FINANCE    → finance_analyst (LlmAgent)                   │
        │  RESEARCH   → research_pipeline (SequentialAgent)          │
        │  STRATEGIC  → strategic_advisor (StrategicAdvisor/LlmAgent)│
        │  REPORT     → document_worker (DocumentWorker/BaseAgent)   │
        │  AUDIT      → audit_pipeline (SequentialAgent)             │
        │  GREETING   → _greeting_node (Python function, no LLM)     │
        │  PROACTIVE  → proactive_pipeline (SequentialAgent)         │
        │  AMBIGUOUS  → coordinator_llm (LlmAgent fallback)          │
        └────────────────────────────────────────────────────────────┘
    """
    # Lazy imports to avoid circular dependencies at module load time
    from src.agents.demand_planner import demand_planner
    from src.agents.inventory_analyst import inventory_analyst
    from src.agents.pipelines import (
        audit_pipeline,
        proactive_pipeline,
        research_pipeline,
    )
    from src.agents.sales_analyst import sales_analyst
    from src.agents.procurement_analyst import procurement_analyst
    from src.agents.finance_analyst import finance_analyst
    from src.agents.strategic_advisor import strategic_advisor
    from src.agents.document_worker import DocumentWorker
    from src.agents.coordinator_llm import build_coordinator_llm

    document_worker = DocumentWorker(name="document_worker_kernel")
    coordinator_llm = build_coordinator_llm()

    return Workflow(
        name="kernel",
        edges=[
            # Step 1: classify intent (Python, no LLM)
            ("START", _classify_heuristic, _router),
            # Step 2: dispatch to department agent
            (
                _router,
                {
                    "INVENTORY":   inventory_analyst,
                    "DEMAND":      demand_planner,
                    "SALES":       sales_analyst,
                    "PROCUREMENT": procurement_analyst,
                    "FINANCE":     finance_analyst,
                    "RESEARCH":    research_pipeline,
                    "STRATEGIC":   strategic_advisor,
                    "REPORT":      document_worker,
                    "AUDIT":       audit_pipeline,
                    "GREETING":    _greeting_node,
                    "PROACTIVE":   proactive_pipeline,
                    "AMBIGUOUS":   coordinator_llm,
                },
            ),
            # Step 3: transition analysts to quality control supervisor
            (inventory_analyst, _quality_control_supervisor),
            (demand_planner, _quality_control_supervisor),
            (sales_analyst, _quality_control_supervisor),
            (procurement_analyst, _quality_control_supervisor),
            (finance_analyst, _quality_control_supervisor),
            (strategic_advisor, _quality_control_supervisor),
            (coordinator_llm, _quality_control_supervisor),
            # Step 4: dispatch supervisor decision (approved or reject back to analyst)
            (
                _quality_control_supervisor,
                {
                    "APPROVED": _approved_node,
                    "GENERATE_REPORT": document_worker,
                    "REJECTED_INVENTORY": inventory_analyst,
                    "REJECTED_DEMAND":   demand_planner,
                    "REJECTED_SALES":    sales_analyst,
                    "REJECTED_PROCUREMENT": procurement_analyst,
                    "REJECTED_FINANCE":   finance_analyst,
                    "REJECTED_STRATEGIC": strategic_advisor,
                    "REJECTED_AMBIGUOUS": coordinator_llm,
                },
            ),
        ],
    )
