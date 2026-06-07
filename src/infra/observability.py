"""Error tracking (M4). Sentry init that is a NO-OP when SENTRY_DSN is unset, so dev
and tests run untouched and prod gets exception capture by setting one env var."""
from __future__ import annotations

import os

from src.infra.logger import log_info

_initialised = False


def init_observability() -> bool:
    """Initialise Sentry if SENTRY_DSN is set + the SDK is installed. Idempotent.
    Returns True when active. Never raises — observability must not break boot."""
    global _initialised
    if _initialised:
        return True
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk  # type: ignore

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            environment=os.environ.get("ARIA_ENV", "production"),
        )
        _initialised = True
        log_info("Sentry initialised", agent="observability")
        return True
    except Exception as e:  # noqa: BLE001 — a broken DSN/SDK must not crash startup
        log_info(f"Sentry init skipped: {e!r}", agent="observability")
        return False
