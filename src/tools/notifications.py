"""Proactive notifications (M9): push the morning brief / a critical anomaly to the
owner off-app via Telegram (or Twilio WhatsApp). Gated — autonomous sends fire only from
the insight/brief crons and require a configured destination. Best-effort: a delivery
failure never crashes the sweep.

Pure formatters (``_format_anomaly_alert`` / ``_format_brief``) are unit-tested; the send
needs channel credentials (TELEGRAM_BOT_TOKEN/CHAT_ID — per-tenant destinations are the
next step, stored on tenant_integrations)."""
from __future__ import annotations

import os

from src.infra.logger import log_error


def _format_anomaly_alert(anomaly: dict) -> str:
    prod = anomaly.get("product") or anomaly.get("product_name") or "un producto"
    desc = anomaly.get("description") or anomaly.get("detail") or "cambio inusual detectado"
    return f"⚠️ ARIA: {prod} — {desc}"


def _format_brief(snapshot: dict) -> str:
    pend = snapshot.get("pending_count")
    if pend is None:
        pend = len(snapshot.get("pending_proposals") or [])
    if not pend:
        return "☀️ Buen día. ARIA está al día — sin decisiones pendientes."
    return f"☀️ Buen día. Tenés {pend} decisión(es) para revisar en ARIA."


async def send_telegram(token: str, chat_id: str, text: str) -> bool:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as h:
        r = await h.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": chat_id, "text": text})
        return r.status_code < 300


async def send_alert(text: str) -> dict:
    """Best-effort push via the configured channel. Skips cleanly if none is set."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return {"status": "skipped", "reason": "sin canal de notificación configurado"}
    try:
        ok = await send_telegram(token, chat, text)
        return {"status": "sent" if ok else "failed"}
    except Exception as e:  # noqa: BLE001 — delivery must never crash the caller
        log_error("send_alert failed", error=str(e))
        return {"status": "error", "detail": str(e)}


async def notify_critical_anomaly(anomaly: dict) -> dict:
    return await send_alert(_format_anomaly_alert(anomaly))
