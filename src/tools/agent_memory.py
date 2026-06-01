"""
ARIA-OS: Department Memory System (FS-IPC)
Provides a persistent JSON-based shared memory for agents to communicate
and persist business metrics, forecasts, and calculations across turns.
"""
import os
import json
from src.infra.logger import log_info, log_error

# Memory dir resolved relative to this file (src/tools/ -> ../.. = repo root) so
# it works cross-platform (macOS, Linux/Cloud Run). ARIA_MEMORY_DIR overrides it
# in containers where persistent storage is mounted elsewhere.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MEMORY_DIR = os.environ.get("ARIA_MEMORY_DIR", os.path.join(_REPO_ROOT, "memory"))
MEMORY_FILE = os.path.join(MEMORY_DIR, "shared_memory.json")

def manage_agent_memory(action: str, key: str, value: str = None) -> dict:
    """
    Reads or writes to the persistent department memory shared by the analyst agents.
    
    Use this tool to save key calculated metrics (like calculated churn rates,
    top customer names, forecasts) so that other agents or future turns can reuse them
    without recalculating or querying the database again.

    Args:
        action: 'read' to retrieve a value, or 'write' to store a value.
        key: The unique string identifier for the metric or insight (e.g., 'sales:churn_rate_apr_2026', 'finance:cogs_q1').
        value: The string value or JSON string to store (required only if action is 'write').

    Returns:
        dict: containing 'success' (bool), and either 'value' (for read) or 'message' (for write).
    """
    if not os.path.exists(MEMORY_DIR):
        try:
            os.makedirs(MEMORY_DIR)
        except Exception as e:
            log_error(f"Failed to create memory directory: {e}")
            return {"success": False, "error": f"Failed to initialize memory directory: {str(e)}"}

    # Initialize shared memory file if it doesn't exist
    if not os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
        except Exception as e:
            log_error(f"Failed to create memory file: {e}")
            return {"success": False, "error": f"Failed to initialize memory file: {str(e)}"}

    try:
        if action == "read":
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            val = data.get(key)
            log_info(f"Department Memory read: key='{key}' -> found: {val is not None}")
            return {"success": True, "key": key, "value": val}
            
        elif action == "write":
            if value is None:
                return {"success": False, "error": "Value argument is required for action 'write'"}
                
            # Read first, to avoid overwrite races
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            data[key] = value
            
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            log_info(f"Department Memory write: key='{key}' successfully updated")
            return {"success": True, "key": key, "message": f"Successfully wrote value for key '{key}'"}
            
        else:
            return {"success": False, "error": f"Unknown action: '{action}'. Must be 'read' or 'write'."}
            
    except Exception as e:
        log_error(f"Error accessing Department Memory: {e}")
        return {"success": False, "error": str(e)}
