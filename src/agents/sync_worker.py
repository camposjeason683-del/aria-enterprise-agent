"""
ARIA-OS: WooCommerce Sync Worker (Non-LLM)
Department: Inventory & Operations
"""
import os
import httpx
from typing import AsyncGenerator
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types
from src.infra.db import get_supabase
from src.infra.logger import log_error, log_info
from src.tools.ledger_common import latest_ledger_date

class SyncWorker(BaseAgent):
    """
    Worker that synchronizes WooCommerce/Google Sheets data using the frontend's API
    or falls back to direct WooCommerce query or cached database history.
    Purely deterministic, no LLM involved.
    """
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        import dotenv
        import httpx
        from datetime import datetime
        
        client = await get_supabase()
        
        yield Event(
            author=self.name,
            content=types.Content(parts=[
                types.Part(text="🔄 Iniciando validación y sincronización de datos...")
            ])
        )
        
        sync_success = False
        sync_error_msg = ""
        
        # Load CRON_SECRET from .env.local (at repo root, resolved relative to this
        # file: src/agents/ -> ../.. = repo root) to authenticate with the Next.js
        # sync endpoint. Falls back to os.environ below, so on Cloud Run (no file)
        # the env var — or the root .env loaded by main.py — still works.
        env_local_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env.local")
        env_local = dotenv.dotenv_values(env_local_path)
        cron_secret = env_local.get("CRON_SECRET") or os.environ.get("CRON_SECRET")
        if cron_secret:
            cron_secret = cron_secret.replace('"', '').replace("'", "").strip()
            
        frontend_url = "http://localhost:3000"
        
        # 1. Attempt frontend API synchronization (reuses full fallback to Google Sheets, de-duplication and ledger compilation)
        if cron_secret:
            try:
                log_info("Triggering frontend /api/sync-stock endpoint...", agent="sync_worker")
                async with httpx.AsyncClient(timeout=45.0) as http:
                    headers = {"Authorization": f"Bearer {cron_secret}"}
                    resp = await http.get(f"{frontend_url}/api/sync-stock", headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            sync_success = True
                            msg = f"✅ Sincronización exitosa con el Frontend. {data.get('processed', 0)} productos procesados."
                            log_info(msg, agent="sync_worker")
                            yield Event(
                                author=self.name,
                                content=types.Content(parts=[types.Part(text=msg)])
                            )
                        else:
                            sync_error_msg = f"API del Frontend retornó éxito: False. Detalles: {data.get('error')}"
                    else:
                        sync_error_msg = f"HTTP {resp.status_code} de la API del Frontend."
            except Exception as e:
                sync_error_msg = f"No se pudo contactar al Frontend: {repr(e)}"
                log_info(f"Frontend sync trigger failed/skipped: {sync_error_msg}", agent="sync_worker")
        else:
            sync_error_msg = "CRON_SECRET no configurado en .env.local"
            log_info(sync_error_msg, agent="sync_worker")

        # 2. Local WooCommerce orders sync to wc_orders_cache (Always run to keep orders cache updated)
        log_info("Starting local WooCommerce orders sync to wc_orders_cache...", agent="sync_worker")
        wc_url = os.environ.get("WOOCOMMERCE_API_URL")
        wc_key = os.environ.get("WOOCOMMERCE_API_KEY")
        wc_secret = os.environ.get("WOOCOMMERCE_API_SECRET")
        
        if not all([wc_url, wc_key, wc_secret]):
            msg = "Faltan credenciales locales de WooCommerce en .env para sincronizar wc_orders_cache"
            log_info(msg, agent="sync_worker")
            if not sync_success:
                sync_error_msg += f" | {msg}"
        else:
            try:
                all_orders = []
                page = 1
                max_pages = 5
                
                async with httpx.AsyncClient(timeout=45.0) as http:
                    while page <= max_pages:
                        resp = await http.get(
                            f"{wc_url}/wp-json/wc/v3/orders",
                            auth=(wc_key, wc_secret),
                            params={"per_page": 100, "page": page, "orderby": "date", "order": "desc"}
                        )
                        resp.raise_for_status()
                        orders = resp.json()
                        
                        if not orders:
                            break
                            
                        all_orders.extend(orders)
                        total_pages = int(resp.headers.get("x-wp-totalpages", 1))
                        if page >= total_pages:
                            break
                        page += 1
                        
                if all_orders:
                    upserts = []
                    for o in all_orders:
                        upserts.append({
                            "id": o["id"],
                            "status": o["status"],
                            "total": o["total"],
                            "currency": o["currency"],
                            "customer_name": f"{o['billing']['first_name']} {o['billing']['last_name']}".strip(),
                            "date_created": o["date_created"],
                            "line_items": o["line_items"]
                        })
                    await client.table("wc_orders_cache").upsert(upserts).execute()
                    
                    # If this succeeds and we didn't have sync_success before, we can set it to True
                    if not sync_success:
                        sync_success = True
                        
                    msg = f"✅ Sincronización directa de órdenes completada. {len(upserts)} órdenes procesadas."
                    log_info(msg, agent="sync_worker")
                    yield Event(
                        author=self.name,
                        content=types.Content(parts=[types.Part(text=msg)])
                    )
                else:
                    if not sync_success:
                        sync_error_msg += " | No se encontraron órdenes nuevas en WooCommerce."
            except Exception as e:
                msg = f"Falló la sincronización directa: {repr(e)}"
                log_info(msg, agent="sync_worker")
                if not sync_success:
                    sync_error_msg += f" | {msg}"
                    
        # 3. Final State Validation & Cache fallback
        if not sync_success:
            try:
                latest_date = await latest_ledger_date(client)
            except Exception as db_err:
                latest_date = None
                sync_error_msg += f" | Error de base de datos al buscar histórico: {db_err}"
                
            if latest_date:
                warn_msg = (
                    f"⚠️ Advertencia: No se pudieron sincronizar datos frescos en vivo (Detalles: {sync_error_msg}). "
                    f"Para mantener la operatividad y evaluar propuestas, se continuará el análisis utilizando "
                    f"los últimos datos disponibles en la base de datos (fecha: {latest_date})."
                )
                log_info(warn_msg, agent="sync_worker")
                yield Event(
                    author=self.name,
                    content=types.Content(parts=[types.Part(text=warn_msg)])
                )
            else:
                err_msg = f"❌ Error crítico: No se pudo obtener datos nuevos y no existen datos históricos en la base de datos. Detalle: {sync_error_msg}"
                log_error(err_msg, agent="sync_worker")
                yield Event(
                    author=self.name,
                    content=types.Content(parts=[types.Part(text=err_msg)])
                )
                raise RuntimeError(err_msg)
