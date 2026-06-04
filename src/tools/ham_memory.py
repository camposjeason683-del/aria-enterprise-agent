"""
ARIA-OS: Hierarchical Auto-Consolidated Memory (HAM L1)
Manages USER.md (user profile) and MEMORY.md (system memory) in Markdown format.
Automatically compresses the memory using Gemini when it exceeds a character limit.
"""
import os
import json
from typing import Dict, Any
from google.genai import Client
from src.infra.logger import log_info, log_error

# Memory dir resolved relative to this file (src/tools/ -> ../.. = repo root) so
# it works cross-platform (macOS, Linux/Cloud Run). ARIA_MEMORY_DIR overrides it
# in containers where persistent storage is mounted elsewhere.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MEMORY_DIR = os.environ.get("ARIA_MEMORY_DIR", os.path.join(_REPO_ROOT, "memory"))
LIMIT_CHARACTERS = 2500
TARGET_CHARACTERS = 1800

INITIAL_CONTENTS = {
    "user": (
        "# Perfil del Usuario (USER.md)\n\n"
        "*   **Rol**: Administrador / Comprador del Dashboard de Adquisiciones.\n"
        "*   **Preferencias**: Formato markdown estructurado en las respuestas del chat, reportes detallados compilados en PDF.\n"
        "*   **Estilo**: Profesional, analítico y directo en español.\n"
    ),
    "system": (
        "# Memoria de Trabajo del Sistema (MEMORY.md)\n\n"
        "## Reglas Críticas del Esquema de Datos\n"
        "*   **Tabla de Órdenes**: `wc_orders_cache`.\n"
        "*   **Columna del Cliente**: Usar siempre `customer_name` (NO existe `customer_id`).\n"
        "*   **Columna de Fechas**: Usar siempre `date_created` (NO usar `created_at` ni `transaction_date`).\n"
        "*   **Filtro de Estados de Órdenes**: Filtrar siempre estados inválidos: `status NOT IN ('cancelled', 'failed', 'trash', 'draft')`.\n\n"
        "## Lecciones Aprendidas de Errores Pasados\n"
        "*   **Cálculo de Churn**: El Churn mensual debe calcularse mediante análisis de cohortes (CTE/JOIN de clientes comunes), nunca restando los totales globales de clientes.\n"
        "*   **Sandbox de Python**: La ejecución de scripts de Python en el sandbox no tiene acceso directo al estado global, pero sí puede importar `src.tools.dynamic_execution` para ejecutar SQL de forma segura.\n"
    )
}

def get_memory_file_path(memory_type: str) -> str:
    """Returns the file path for user or system memory files."""
    filename = "USER.md" if memory_type.lower() == "user" else "MEMORY.md"
    return os.path.join(MEMORY_DIR, filename)

_HAM_CACHE: dict[str, tuple[float, str]] = {}  # path -> (mtime, content)


def read_ham_memory(memory_type: str) -> str:
    """Reads the memory file, cached in-process with an mtime check.

    P1: this runs inside before_model_handler on EVERY model call (5-10× per turn)
    and previously did a makedirs + 2 blocking disk reads each time. Now it serves
    from cache unless the file's mtime changed.
    """
    path = get_memory_file_path(memory_type)
    try:
        mtime = os.path.getmtime(path)
        cached = _HAM_CACHE.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        _HAM_CACHE[path] = (mtime, content)
        return content
    except FileNotFoundError:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        default_content = INITIAL_CONTENTS.get(memory_type.lower(), "")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(default_content)
            try:
                _HAM_CACHE[path] = (os.path.getmtime(path), default_content)
            except OSError:
                pass
            return default_content
        except Exception as e:
            log_error(f"read_ham_memory: Failed to write initial file at {path}: {e}")
            return ""
    except Exception as e:
        log_error(f"read_ham_memory: Failed to read file {path}: {e}")
        return ""

def write_ham_memory_sync(memory_type: str, content: str) -> bool:
    """Writes content directly to the memory file."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    path = get_memory_file_path(memory_type)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log_info(f"write_ham_memory_sync: Wrote {len(content)} characters to {path}")
        return True
    except Exception as e:
        log_error(f"write_ham_memory_sync: Failed to write to {path}: {e}")
        return False

async def compress_ham_memory(memory_type: str) -> bool:
    """
    Checks the size of the memory file and uses Gemini to summarize/compress it
    if it exceeds LIMIT_CHARACTERS, keeping only vital business rules and facts.
    """
    path = get_memory_file_path(memory_type)
    if not os.path.exists(path):
        return False
        
    content = read_ham_memory(memory_type)
    if len(content) <= LIMIT_CHARACTERS:
        return False
        
    log_info(f"compress_ham_memory: Memory file {path} exceeds limit ({len(content)} chars). Starting semantic compression...", agent="memory")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log_error("compress_ham_memory: GEMINI_API_KEY not found in environment. Skipping compression.", agent="memory")
        return False
        
    client = Client(api_key=api_key)
    
    prompt = f"""
Eres el Compresor Semántico de Memoria de Cos-Agent. Tu trabajo es re-sintetizar el siguiente archivo de memoria en formato Markdown, conservando absolutamente todas las reglas de negocio críticas, lecciones de errores aprendidas y hechos importantes sobre el usuario o el entorno, pero reduciendo el tamaño del texto para que sea menor a {TARGET_CHARACTERS} caracteres.

[CONTENIDO DEL ARCHIVO]
{content}

---

**REGLAS DE COMPRESIÓN:**
1. Mantén intactos los esquemas de base de datos, nombres de tablas, columnas y filtros obligatorios (ej. `customer_name`, `date_created`, `wc_orders_cache`).
2. Mantén las lecciones de errores metodológicos aprendidas.
3. Condensa párrafos largos a listas de viñetas claras.
4. Devuelve únicamente el contenido Markdown limpio de reemplazo, sin bloques de código ```markdown o texto adicional a su alrededor.
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config={"temperature": 0.0}
        )
        compressed = response.text.strip()
        
        # Safe checks
        if compressed and len(compressed) < len(content):
            write_ham_memory_sync(memory_type, compressed)
            log_info(f"compress_ham_memory: Successfully compressed {path} from {len(content)} to {len(compressed)} characters!", agent="memory")
            return True
        else:
            log_error("compress_ham_memory: Gemini generated empty or larger content. Skipping rewrite.", agent="memory")
            return False
            
    except Exception as e:
        log_error(f"compress_ham_memory: Error calling Gemini: {e}", agent="memory")
        return False

def manage_ham_memory(action: str, memory_type: str, content: str = None) -> dict:
    """
    Herramienta agéntica para gestionar las memorias Markdown de Cos-Agent (USER.md y MEMORY.md).
    Permite leer, escribir o añadir notas de lecciones y reglas comerciales.
    
    Args:
        action: 'read' (leer el archivo completo), 'write' (sobrescribir el archivo) o 'append' (añadir una nota al final).
        memory_type: 'user' (para USER.md) o 'system' (para MEMORY.md).
        content: El texto Markdown a escribir o la nota a añadir al final (requerido para 'write' y 'append').
    """
    memory_type = memory_type.lower().strip()
    if memory_type not in ["user", "system"]:
        return {"success": False, "error": "Invalid memory_type. Must be 'user' or 'system'."}
        
    action = action.lower().strip()
    
    if action == "read":
        data = read_ham_memory(memory_type)
        return {"success": True, "memory_type": memory_type, "content": data}
        
    elif action in ["write", "append"]:
        if not content:
            return {"success": False, "error": "Parameter 'content' is required for write or append actions."}
            
        if action == "write":
            success = write_ham_memory_sync(memory_type, content)
        else: # append
            current = read_ham_memory(memory_type)
            # Ensure proper separation
            separator = "\n" if current.endswith("\n") else "\n\n"
            new_content = current + separator + "*   " + content.strip()
            success = write_ham_memory_sync(memory_type, new_content)
            
        if success:
            # Trigger compression in background if running inside an event loop
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(compress_ham_memory(memory_type))
            except RuntimeError:
                # No running loop, run synchronously if required (or skip for safety)
                pass
            return {"success": True, "message": f"Successfully updated {memory_type} memory."}
        else:
            return {"success": False, "error": f"Failed to write to {memory_type} memory."}
            
    else:
        return {"success": False, "error": "Invalid action. Must be 'read', 'write', or 'append'."}
