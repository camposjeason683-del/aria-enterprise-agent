"""
ARIA-OS: Security Callbacks
Applied globally via the Kernel. Intercepts every LLM call and tool
invocation to enforce safety invariants.
"""
import re

from google.genai import types


# ─── Threat Patterns ────────────────────────────────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|your)",
    r"system\s+prompt",
    r"reveal\s+your",
    r"act[uú]a\s+como",
    r"pretend\s+(you|to\s+be)",
    r"DAN\s+mode",
    r"jailbreak",
    r"bypass\s+(your|all|the)",
    r"olvida\s+tus",
    r"nuevas\s+instrucciones",
    r"ignore\s+all\s+rules",
    r"you\s+are\s+now",
    r"modo\s+desarrollador",
    r"developer\s+mode",
    r"do\s+anything\s+now",
    r"override\s+your",
    r"reset\s+your\s+(instructions|rules)",
    r"from\s+now\s+on\s+you\s+are",
    r"disable\s+your\s+filters",
    r"what\s+is\s+your\s+system\s+prompt",
]

_FORBIDDEN_OUTPUT = [
    "ck_", "cs_", "sb_secret_", "sb_publishable_",
    "sbp_", "service_role", "BEGIN PRIVATE KEY",
    "password=", "token=", "CONSUMER_KEY",
    "CONSUMER_SECRET", "SUPABASE_SERVICE_KEY",
    "GOOGLE_API_KEY", "OPENAI_API_KEY",
]

_DESTRUCTIVE_SQL = ["DROP ", "DELETE ", "TRUNCATE ", "ALTER ", "UPDATE ", "INSERT "]


# ─── BEFORE MODEL: Block Prompt Injection ───────────────────────────
async def block_prompt_injection(callback_context, llm_request):
    """Intercept malicious prompts BEFORE they reach the LLM."""
    if not llm_request.contents:
        return None

    last_msg = str(llm_request.contents[-1])

    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, last_msg, re.IGNORECASE):
            return types.Content(
                parts=[
                    types.Part(
                        text="⚠️ Solicitud bloqueada por política de seguridad."
                    )
                ]
            )

    return None  # Allow


def inject_ham_memory(callback_context, llm_request):
    """Injects USER.md and MEMORY.md contents into system instruction."""
    from src.tools.ham_memory import read_ham_memory
    from src.infra.logger import log_info, log_error
    try:
        user_mem = read_ham_memory("user")
        sys_mem = read_ham_memory("system")
        
        memory_injection = (
            f"\n\n=== MEMORIA JERÁRQUICA (L1 HAM) ===\n\n"
            f"[USER.md (Preferencias del Usuario)]:\n{user_mem}\n\n"
            f"[MEMORY.md (Memoria de Trabajo)]:\n{sys_mem}\n"
            f"====================================\n"
        )
        
        # Check system instruction
        original_instruction = llm_request.config.system_instruction
        if not original_instruction:
            original_instruction = types.Content(role="system", parts=[types.Part(text="")])
        elif not isinstance(original_instruction, types.Content):
            original_instruction = types.Content(role="system", parts=[types.Part(text=str(original_instruction))])
            
        if not original_instruction.parts:
            original_instruction.parts.append(types.Part(text=""))
            
        # Append memory context to the system instruction
        original_instruction.parts[0].text = (original_instruction.parts[0].text or "") + memory_injection
        llm_request.config.system_instruction = original_instruction
        log_info(f"inject_ham_memory: Successfully injected HAM L1 context for agent '{callback_context.agent_name}'")
    except Exception as e:
        log_error(f"inject_ham_memory callback failed: {e}")


async def before_model_handler(callback_context, llm_request):
    """Combined safety check and dynamic memory injection callback."""
    # 1. Safety check
    res = await block_prompt_injection(callback_context, llm_request)
    if res:
        return res
        
    # 2. Dynamic Memory injection
    inject_ham_memory(callback_context, llm_request)
    return None



# ─── BEFORE TOOL: Validate Parameters ───────────────────────────────
async def validate_tool_params(tool, args, tool_context):
    """Validate and sanitize tool parameters BEFORE execution."""
    # Block destructive SQL
    if "query" in args:
        q = str(args["query"]).upper()
        for kw in _DESTRUCTIVE_SQL:
            if kw in q:
                return {
                    "error": "Operación de escritura bloqueada. Solo lectura permitida."
                }

    # Enforce safe ranges
    if "days" in args:
        args["days"] = min(int(args.get("days", 7)), 90)

    if "limit" in args:
        args["limit"] = min(int(args.get("limit", 50)), 200)

    if "top_n" in args:
        args["top_n"] = min(int(args.get("top_n", 20)), 50)

    return None


# ─── AFTER MODEL: Sanitize Output ───────────────────────────────────
async def sanitize_output(callback_context, llm_response):
    """Clean the response AFTER the LLM generates text.
    Blocks any response that leaks credentials or internal data."""
    if not llm_response or not llm_response.content:
        return None

    text = ""
    if llm_response.content.parts:
        text = "".join(part.text for part in llm_response.content.parts if part.text)
    text_lower = text.lower()

    for forbidden in _FORBIDDEN_OUTPUT:
        if forbidden.lower() in text_lower:
            from google.adk.models.llm_response import LlmResponse
            return LlmResponse(
                content=types.Content(
                    parts=[
                        types.Part(
                            text="⚠️ Error interno: la respuesta contenía "
                            "información sensible y fue bloqueada."
                        )
                    ]
                )
            )

    # Enforce max length to prevent runaway responses
    if len(text) > 8000:
        from google.adk.models.llm_response import LlmResponse
        truncated = text[:7900] + "\n\n⚠️ [Respuesta truncada por longitud]"
        return LlmResponse(content=types.Content(parts=[types.Part(text=truncated)]))

    return None
