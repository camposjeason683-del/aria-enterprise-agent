"""
ARIA-OS: Structured JSON Logger
Outputs newline-delimited JSON for Cloud Run / Cloud Logging ingestion.
"""
import json
import sys
import time
from dataclasses import dataclass, asdict


@dataclass
class LogEntry:
    level: str
    message: str
    agent: str = ""
    user_id: str = ""
    session_id: str = ""
    duration_ms: float = 0
    tool: str = ""
    error: str = ""

    def emit(self):
        entry = {k: v for k, v in asdict(self).items() if v}
        entry["timestamp"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        try:
            print(json.dumps(entry, ensure_ascii=False), file=sys.stdout, flush=True)
        except UnicodeEncodeError:
            # Fallback for Windows terminals with limited character maps
            print(json.dumps(entry, ensure_ascii=True), file=sys.stdout, flush=True)



def _build_entry(level: str, message: str, kwargs: dict) -> LogEntry:
    standard_keys = {"agent", "user_id", "session_id", "duration_ms", "tool", "error"}
    entry_args = {k: v for k, v in kwargs.items() if k in standard_keys}
    extra = {k: v for k, v in kwargs.items() if k not in standard_keys}
    if extra:
        message = f"{message} | Extra: {extra}"
    return LogEntry(level=level, message=message, **entry_args)


def log_info(msg: str, **kwargs):
    _build_entry("INFO", msg, kwargs).emit()


def log_error(msg: str, **kwargs):
    _build_entry("ERROR", msg, kwargs).emit()


def log_warn(msg: str, **kwargs):
    _build_entry("WARN", msg, kwargs).emit()
