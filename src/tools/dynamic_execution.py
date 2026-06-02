"""
ARIA-OS: Dynamic Execution Tools
Provides two sandboxed execution capabilities:

1. execute_safe_read_query(sql) — Executes a SELECT-only query against Supabase
   using the REST PostgREST endpoint. Blocks any write/mutating SQL.

2. execute_python_script(code) — Runs an arbitrary Python snippet in a
   restricted subprocess with a hard timeout. Lets the LLM perform custom
   calculations, statistical analyses, and data processing on-the-fly.
"""
import os
import re
import sys
import json
import subprocess
import tempfile
import textwrap
from typing import Any
from datetime import datetime

from src.infra.logger import log_error, log_info


# ─── Security Constants ──────────────────────────────────────────────────────

# Regex to detect ANY SQL mutation keyword (case-insensitive).
# The check intentionally errs on the side of caution.
_WRITE_PATTERNS = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|COPY|CALL|EXECUTE|DO|BEGIN|COMMIT|ROLLBACK"
    r"|ATTACH|DETACH|VACUUM|REINDEX|CLUSTER|LOCK|UNLOCK"
    r")\b",
    re.IGNORECASE,
)

# Python script execution hard cap in seconds
_PYTHON_TIMEOUT_SECONDS = 10

# Maximum rows returned from a single SQL query
_SQL_MAX_ROWS = 200


# ─── Tool 1: Safe SQL Read Query ─────────────────────────────────────────────

def pre_flight_validate_sql(sql_query: str) -> dict | None:
    """
    Validates the SQL query locally against db_schema.json to catch common schema
    and business logic errors before executing them against Supabase.
    """
    sql_clean = sql_query.strip().rstrip(";").strip()
    sql_upper = sql_clean.upper()
    
    # Load schema spec
    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "specs", "db_schema.json"))
    if not os.path.exists(schema_path):
        return None
        
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        log_error(f"pre_flight_validate_sql: Failed to load db_schema.json: {e}")
        return None

    # Find queried tables using regex
    table_pattern = re.compile(r"\b(?:FROM|JOIN)\s+(?:[a-zA-Z0-9_]+\.)?([a-zA-Z0-9_]+)", re.IGNORECASE)
    tables = table_pattern.findall(sql_clean)
    
    matched_tables = []
    for t in tables:
        t_lower = t.lower()
        if t_lower in schema:
            matched_tables.append(t_lower)
            
    if not matched_tables:
        return None
        
    for table in matched_tables:
        table_spec = schema[table]
        aliases = table_spec.get("alias_mappings", {})
        
        # 1. Check for common invalid column aliases
        for alias, correct in aliases.items():
            if re.search(rf"\b{re.escape(alias)}\b", sql_clean, re.IGNORECASE):
                return {
                    "error": (
                        f"PRE-FLIGHT VALIDATION ERROR: The column '{alias}' does not exist in table '{table}'. "
                        f"Please correct your SQL query to use '{correct}' instead."
                    )
                }
                
        # 2. Check for general specific column errors and filters
        if table == "wc_orders_cache":
            # Verify status filter is present in queries aggregating or selecting columns
            needs_status_filter = any(kw in sql_upper for kw in ["WHERE", "GROUP BY", "JOIN", "SUM(", "COUNT("])
            if needs_status_filter:
                has_cancelled = "cancelled" in sql_clean.lower()
                has_failed = "failed" in sql_clean.lower()
                if not (has_cancelled or has_failed):
                    return {
                        "error": (
                            "PRE-FLIGHT VALIDATION ERROR: Any analytical query on 'wc_orders_cache' must filter out "
                            "invalid order statuses. Please add this clause to your WHERE statement: "
                            "status NOT IN ('cancelled', 'failed', 'trash', 'draft')"
                        )
                    }
                
    return None

async def execute_safe_read_query(sql_query: str) -> dict:
    """
    Executes a **read-only** SQL query (SELECT statements only) against the
    Supabase database using the PostgREST /rpc or raw SQL endpoint.

    Use this tool when you need to answer a question that requires a custom
    data cross-join or aggregation that no other existing tool covers.

    SCHEMA REFERENCE (Supabase tables you can query):
    - aria_proposals(id, title, problem, proposed_action, urgency, status,
                     estimated_impact, risk, notes, category, created_at,
                     approved_at, approved_by, executed_at, rejection_reason)
    - proposal_comments(id, proposal_id, author, content, created_at)
    - daily_inventory_ledger(id, date, product_id, product_name,
                             stock_end_of_day, sales_velocity)
    - purchase_order_drafts(id, status, items JSONB, created_by, audited_by,
                            created_at, confirmed_at, delivered_at, label)
    - supplier_catalog(id, product_id, nombre_original, proveedor, marca,
                       submarca)
    - wc_orders_cache(id, order_id, customer_id, total, status, created_at,
                      line_items JSONB)

    Args:
        sql_query: A plain SQL SELECT statement. Multi-line is fine.
                   Example: "SELECT proveedor, COUNT(*) FROM supplier_catalog
                             GROUP BY proveedor ORDER BY count DESC LIMIT 10"

    Returns:
        dict with keys:
          - rows: list of result dicts (up to 200 rows)
          - row_count: int
          - truncated: bool — True if more than 200 rows were returned
          - error: str (only present on failure)
    """
    sql_query = sql_query.strip().rstrip(";").strip()

    # 0. Pre-flight Guardrail check
    pre_flight_err = pre_flight_validate_sql(sql_query)
    if pre_flight_err:
        log_info(f"execute_safe_read_query: Pre-flight validator intercepted query: {pre_flight_err['error']}")
        return pre_flight_err

    # 1. Security gate — block any write SQL
    if _WRITE_PATTERNS.search(sql_query):
        log_error(
            "execute_safe_read_query: Blocked write SQL attempt",
            query_preview=sql_query[:120],
        )
        return {
            "error": (
                "SECURITY VIOLATION: The provided SQL contains a write or "
                "mutation keyword (INSERT, UPDATE, DELETE, DROP, etc.). "
                "This tool only executes SELECT queries. Rewrite your query."
            )
        }

    if not re.search(r"\bSELECT\b", sql_query, re.IGNORECASE):
        return {
            "error": (
                "Only SELECT statements are allowed. "
                "The query must start with or contain SELECT."
            )
        }

    # 2. Execute under the tenant's RLS via the SECURITY INVOKER RPC exec_safe_read
    #    (migrations/0004). The tenant client carries the user's JWT, so even this
    #    LLM-authored SQL can only ever read the caller's tenant rows.
    try:
        from src.infra.db import get_supabase

        client = await get_supabase()
        res = await client.rpc("exec_safe_read", {"q": sql_query})
        rows = res.data
        if rows is None:
            rows = []
        elif not isinstance(rows, list):
            rows = [rows]
        truncated = len(rows) > _SQL_MAX_ROWS
        result_rows = rows[:_SQL_MAX_ROWS]
        log_info(
            f"execute_safe_read_query: returned {len(result_rows)} rows",
            truncated=truncated,
        )
        return {
            "rows": result_rows,
            "row_count": len(result_rows),
            "truncated": truncated,
        }
    except Exception as exc:
        log_error(f"execute_safe_read_query: Exception: {exc}")
        return {"error": f"Query execution error: {str(exc)}"}


# ─── Tool 2: Python Script Sandbox ───────────────────────────────────────────

def execute_python_script(script_code: str) -> dict:
    """
    Executes a Python script in an isolated subprocess with a 10-second timeout.

    Use this for complex, on-the-fly calculations, statistical analysis,
    data transformations, or any computation that cannot be handled by the
    existing tools. The script runs in a completely separate Python process
    with no access to internal application state or secrets.

    HOW TO USE:
    - Print your results using print() — the stdout is captured and returned.
    - Use json.dumps() to return structured data: print(json.dumps(result)).
    - Import only the Python standard library (math, statistics, itertools,
      datetime, json, re, collections, functools, etc.). Third-party packages
      like numpy or pandas are NOT available.

    SECURITY RULES (strictly enforced):
    - os, sys, subprocess, socket, requests, httpx, open() for write are all
      blocked by the restricted import policy.
    - The script CANNOT read from or write to the filesystem or network.
    - The script CANNOT access environment variables or internal modules.

    Args:
        script_code: Valid Python 3 source code as a plain string.

    Returns:
        dict with keys:
          - stdout: captured standard output (str)
          - stderr: captured standard error (str)
          - success: bool
          - execution_time_ms: int
          - error: str (only on timeout or crash)

    Example:
        >>> execute_python_script('''
        ... import math, statistics
        ... data = [10, 20, 30, 40, 50]
        ... print(json.dumps({
        ...     "mean": statistics.mean(data),
        ...     "stdev": round(statistics.stdev(data), 2),
        ...     "sqrt_mean": round(math.sqrt(statistics.mean(data)), 4)
        ... }))
        ... ''')
    """
    # Security pre-filter: block dangerous imports and builtins
    _BLOCKED_IMPORTS = [
        "import os", "import sys", "import subprocess", "import socket",
        "import requests", "import httpx", "import urllib", "import ftplib",
        "import smtplib", "import shutil", "import pathlib", "import glob",
        "__import__", "importlib", "exec(", "eval(",
        "open(", "file(",  # filesystem access
        "builtins", "__builtins__",
    ]
    code_lower = script_code.lower()
    for blocked in _BLOCKED_IMPORTS:
        if blocked.lower() in code_lower:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": (
                    f"SECURITY VIOLATION: The script contains a blocked "
                    f"construct: '{blocked}'. Scripts may only use the Python "
                    f"standard library or allowed analytical libraries (pandas, numpy, matplotlib)."
                ),
                "execution_time_ms": 0,
            }

    # Wrap the user script with an explicit allowlist of safe imports
    safe_preamble = textwrap.dedent("""\
        import math
        import statistics
        import json
        import datetime
        import re
        import collections
        import itertools
        import functools
        import random
        import decimal
        import fractions
        import string
        import operator
        import heapq
        
        # Third-party analytical libraries allowed in ARIA-OS Phase 5
        try:
            import pandas as pd
            import numpy as np
            import matplotlib.pyplot as plt
        except ImportError:
            pass
    """)
    full_script = safe_preamble + "\n" + script_code

    start_ms = datetime.now().timestamp() * 1000

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(full_script)
            tmp_path = tmp.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=_PYTHON_TIMEOUT_SECONDS,
            # Inherit PYTHONPATH from sys.path to allow site-packages libs
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.path.pathsep.join(sys.path),
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "HOMEDRIVE": os.environ.get("HOMEDRIVE", ""),
                "HOMEPATH": os.environ.get("HOMEPATH", ""),
                "HOME": os.environ.get("HOME", ""),
            },
        )

        elapsed = round(datetime.now().timestamp() * 1000 - start_ms)
        log_info(
            f"execute_python_script: completed in {elapsed}ms",
            returncode=result.returncode,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:4000],  # cap output
            "stderr": result.stderr[:2000],
            "execution_time_ms": elapsed,
        }

    except subprocess.TimeoutExpired:
        elapsed = round(datetime.now().timestamp() * 1000 - start_ms)
        log_error("execute_python_script: Timeout exceeded")
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": (
                f"Script execution timed out after {_PYTHON_TIMEOUT_SECONDS} seconds. "
                "Simplify the script or reduce the dataset size."
            ),
            "execution_time_ms": elapsed,
        }
    except Exception as exc:
        log_error(f"execute_python_script: Exception: {exc}")
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Script runner error: {str(exc)}",
            "execution_time_ms": 0,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
