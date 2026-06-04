"""
ARIA-OS: Skill Synthesizer
Analyzes session events of successful conversations, learns from errors rejected
by the QC Supervisor, and generates reusable dynamic skills (SKILL.md + run.py).
"""
import os
import json
import ast
import re
import asyncio
import shutil
import subprocess
from typing import List, Any, Dict
from google.genai import Client
from src.infra.logger import log_info, log_error

# Repo root resolved relative to this file (src/tools/ -> ../.. = repo root) so
# synthesized skills are written to the repo's skills/ dir cross-platform.
# ARIA_SKILLS_DIR overrides it in containers where skills live elsewhere.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_SKILLS_DIR = os.environ.get("ARIA_SKILLS_DIR", os.path.join(_REPO_ROOT, "skills"))

def extract_execution_context(events: List[Any]) -> Dict[str, Any]:
    """
    Extracts the user query, executed SQL queries, executed Python scripts,
    and any QC rejection feedback from the current session events.
    """
    context = {
        "user_query": "",
        "sql_queries": [],
        "python_scripts": [],
        "qc_rejections": [],
        "successful_python_stdout": []
    }
    
    # Identify last user query
    last_user_idx = -1
    for i, ev in enumerate(events):
        if ev.author == "user":
            last_user_idx = i
            
    if last_user_idx != -1 and events[last_user_idx].content and events[last_user_idx].content.parts:
        context["user_query"] = " ".join(p.text for p in events[last_user_idx].content.parts if p.text)
        
    start_idx = last_user_idx if last_user_idx != -1 else 0
    
    for ev in events[start_idx:]:
        # Extract QC Rejections
        if ev.author == "supervisor":
            if ev.content and ev.content.parts:
                text = " ".join(p.text for p in ev.content.parts if p.text)
                if "rechazada" in text.lower() or "❌" in text:
                    context["qc_rejections"].append(text)
                    
        # Extract function calls and responses
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if p.function_call:
                    name = p.function_call.name
                    # Convert args to dict (handle Pydantic objects or dicts)
                    args = p.function_call.args
                    if hasattr(args, "model_dump"):
                        args_dict = args.model_dump()
                    elif isinstance(args, dict):
                        args_dict = args
                    else:
                        args_dict = getattr(args, "__dict__", {})
                        
                    if name == "execute_safe_read_query":
                        q = args_dict.get("sql_query") or args_dict.get("query")
                        if q and q not in context["sql_queries"]:
                            context["sql_queries"].append(q)
                    elif name == "execute_python_script":
                        code = args_dict.get("script_code") or args_dict.get("code") or args_dict.get("script")
                        if code and code not in context["python_scripts"]:
                            context["python_scripts"].append(code)
                            
                if p.function_response:
                    resp = p.function_response.response
                    if hasattr(resp, "model_dump"):
                        resp_dict = resp.model_dump()
                    elif isinstance(resp, dict):
                        resp_dict = resp
                    else:
                        resp_dict = getattr(resp, "__dict__", {})
                        
                    # If it was a python execution and succeeded
                    if resp_dict.get("success") and resp_dict.get("stdout"):
                        context["successful_python_stdout"].append(resp_dict.get("stdout"))
                        
    return context

async def evaluate_and_synthesize_skill(events: List[Any], skills_dir: str = _DEFAULT_SKILLS_DIR) -> bool:
    """
    Sintetiza un nuevo skill si la ejecución actual contiene lógica SQL o Python útil y aprobada.
    """
    context = extract_execution_context(events)
    
    # Si no hay SQL ni código python ejecutado, no tiene sentido crear un skill
    if not context["sql_queries"] and not context["python_scripts"]:
        log_info("Skill Synthesizer: No SQL queries or Python scripts executed. Skipping synthesis.", agent="synthesizer")
        return False
        
    log_info(f"Skill Synthesizer: Found {len(context['sql_queries'])} SQL queries and {len(context['python_scripts'])} Python scripts. Starting synthesis evaluation...", agent="synthesizer")
    
    # Configurar API client de Gemini
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log_error("Skill Synthesizer: GEMINI_API_KEY not found in environment. Skipping.", agent="synthesizer")
        return False
        
    client = Client(api_key=api_key)
    
    prompt = f"""
Eres el Diseñador y Sintetizador de Skills de ARIA-OS. Tu trabajo es analizar la sesión de ejecución actual y decidir si contiene una lógica compleja (cálculos en Python, agregaciones SQL avanzadas, cruce de datos) que merezca convertirse en un **Skill persistente y reutilizable** para el sistema.

[PREGUNTA DEL USUARIO]
{context["user_query"]}

[QUERIES SQL EJECUTADAS CON ÉXITO]
{json.dumps(context["sql_queries"], indent=2)}

[CÓDIGO PYTHON EJECUTADO CON ÉXITO EN EL SANDBOX]
{json.dumps(context["python_scripts"], indent=2)}

[OUTPUTS EXITOSOS DEL SANDBOX]
{json.dumps(context["successful_python_stdout"], indent=2)}

[RECHAZOS Y ERRORES DEL QC SUPERVISOR (LO QUE ESTÁ MAL)]
{json.dumps(context["qc_rejections"], indent=2)}

---

**REGLAS Y DIRECTRICES DE SÍNTESIS:**
1. **Evalúa si vale la pena**: El skill debe resolver una tarea recurrente, como cálculos matemáticos complejos, agregación/formateo de tablas, forecasting de stock, análisis BCG, etc. Consultas SQL sumamente genéricas o triviales (ej. "SELECT * FROM products LIMIT 5") NO deben ser skills.
2. **Aprende de los errores (QC Rejections)**: Si el QC rechazó una consulta por usar 'customer_id' en lugar de 'customer_name', o por omitir filtros de estados ('cancelled', 'failed', 'trash', 'draft'), el nuevo skill **DEBE** incluir las correcciones correctas y añadir aserciones/comentarios para evitar repetir el error.
3. **Parametrización**: Identifica qué variables de la consulta pueden parametrizarse (ej. nombres de productos, límites de tiempo, umbrales de stock). Crea parámetros para el skill con tipos y valores por defecto correctos.
4. **run.py Structure**: El script de Python `run.py` se ejecutará en un subproceso. Debe:
   - Leer sus argumentos en formato JSON desde `sys.stdin`.
   - Si necesita interactuar con la base de datos, puede importar `asyncio` y `from src.tools.dynamic_execution import execute_safe_read_query`, ejecutando la consulta deseada con los parámetros dinámicos y procesando los datos.
   - Si necesita procesamiento matemático/estadístico avanzado, puede utilizar `pandas` o `numpy` (ambos instalados y permitidos en el sandbox).
   - Escribir el output final estructurado en stdout como un string JSON usando `print(json.dumps(output))`.
   - Si ocurre un error, imprimirlo en stderr e invocar `sys.exit(1)`.
5. **Nombre del Skill**: El nombre debe estar en `snake_case` (ej. `analizar_variacion_churn` o `pronosticar_demanda_producto`).

**FORMATO DE SALIDA:**
Debes responder con un objeto JSON que siga exactamente el siguiente esquema de respuesta:
{{
  "worth_promoting": true/false (si consideras útil guardarlo),
  "reason": "Justificación de por qué califica o no como skill",
  "skill_name": "nombre_del_skill",
  "description": "Una descripción clara en español de lo que hace el skill, para que el LLM sepa cuándo invocarlo",
  "parameters": {{
    "type": "object",
    "properties": {{
       "nombre_parametro": {{
          "type": "string/number/integer/boolean",
          "description": "Descripción del parámetro"
       }}
    }},
    "required": ["nombre_parametro"]
  }},
  "markdown_doc": "Contenido del archivo SKILL.md después del YAML frontmatter. Debe describir detalladamente la lógica, ejemplos de uso y advertencias basadas en errores de QC previos.",
  "python_code": "Código fuente completo y funcional para run.py, incluyendo imports de sys, json, pandas, numpy o tools de ARIA-OS. Debe ser robusto, libre de placeholders y con manejo de excepciones."
}}

Responde ÚNICAMENTE con el bloque JSON, sin markdown, sin texto adicional alrededor.
"""
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",  # was the fictitious 'gemini-3.5-flash'
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.1}
        )
        
        result = json.loads(response.text.strip())
        worth = result.get("worth_promoting", False)
        reason = result.get("reason", "")
        
        if not worth:
            log_info(f"Skill Synthesizer: Decision is NOT worth promoting. Reason: {reason}", agent="synthesizer")
            return False
            
        skill_name = result.get("skill_name", "").strip().lower()
        # Sanitize skill name to snake_case
        skill_name = re.sub(r'[^a-z0-9_]', '', skill_name.replace(" ", "_").replace("-", "_"))
        
        if not skill_name:
            log_error("Skill Synthesizer: Empty skill name generated. Aborting.", agent="synthesizer")
            return False
            
        description = result.get("description", "")
        parameters = result.get("parameters", {})
        markdown_doc = result.get("markdown_doc", "")
        python_code = result.get("python_code", "")
        
        # 1. Validate generated python code syntactically
        try:
            ast.parse(python_code)
        except SyntaxError as syntax_err:
            log_error(f"Skill Synthesizer: Generated Python code has syntax errors: {syntax_err}. Aborting.", agent="synthesizer")
            return False
            
        # 2. Prepare directory
        target_dir = os.path.join(skills_dir, skill_name)
        os.makedirs(target_dir, exist_ok=True)
        
        # 3. Create SKILL.md contents
        yaml_frontmatter = {
            "name": skill_name,
            "description": description,
            "parameters": parameters
        }
        
        import yaml
        skill_md_content = f"---\n{yaml.dump(yaml_frontmatter, default_flow_style=False)}---\n# Skill: {skill_name}\n\n{markdown_doc}\n"
        
        # 4. Write files
        md_path = os.path.join(target_dir, "SKILL.md")
        run_path = os.path.join(target_dir, "run.py")
        
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(skill_md_content)
            
        with open(run_path, "w", encoding="utf-8") as f:
            f.write(python_code)

        # E2: smoke-validate the generated skill so a runtime-broken one (e.g. an
        # unguarded int(None) on a missing param) is never persisted to compete with —
        # and break — the real tools. Run it with EMPTY args; a robust skill must
        # handle its defaults. An unhandled Python Traceback = a code bug → discard.
        try:
            proc = subprocess.run(
                ["python3", run_path],
                input="{}",
                capture_output=True,
                text=True,
                timeout=20,
                cwd=_REPO_ROOT,
                env={**os.environ, "PYTHONPATH": _REPO_ROOT},
            )
            if "Traceback (most recent call last)" in (proc.stderr or ""):
                log_error(
                    f"Skill Synthesizer: skill '{skill_name}' crashed on smoke-run "
                    f"(unhandled exception) — discarding. Stderr: {(proc.stderr or '')[:200]}",
                    agent="synthesizer",
                )
                shutil.rmtree(target_dir, ignore_errors=True)
                return False
        except subprocess.TimeoutExpired:
            log_error(f"Skill Synthesizer: skill '{skill_name}' smoke-run timed out — discarding.", agent="synthesizer")
            shutil.rmtree(target_dir, ignore_errors=True)
            return False
        except Exception as smoke_err:
            log_error(f"Skill Synthesizer: smoke-run error for '{skill_name}': {smoke_err}", agent="synthesizer")

        log_info(f"🔥 Skill Synthesizer: Successfully created dynamic skill '{skill_name}' at {target_dir}!", agent="synthesizer")
        return True
        
    except Exception as e:
        log_error(f"Skill Synthesizer: Error generating or writing skill: {e}", agent="synthesizer")
        return False
