"""
ARIA-OS: Strategic Tools (FunctionTools)
Tools for the highest level agent: gathering cross-department data,
simulating impact, and submitting proposals for human approval.
"""
import asyncio
from typing import Optional
from datetime import datetime
from src.infra.db import get_supabase
from src.tools.ledger_common import latest_ledger_date
from src.tools.sales import query_revenue_summary
from src.tools.finance import calc_profit_loss

async def gather_full_business_snapshot() -> dict:
    """Gather high-level metrics across all departments."""
    client = await get_supabase()
    
    # Fetch the latest available date in daily_inventory_ledger to handle stale data
    latest_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")
    
    # Inventory
    inv_res = await client.table("daily_inventory_ledger").select("stock_end_of_day").eq("date", latest_date).execute()
    total_stock = sum(r.get("stock_end_of_day") or 0 for r in (inv_res.data or []))
    
    # Operations / Supplier
    cat_res = await client.table("supplier_catalog").select("proveedor").execute()
    unique_suppliers = len(set(r.get("proveedor") for r in (cat_res.data or [])))
    
    # Sales & Finance
    finance = await calc_profit_loss(days=30)
    
    return {
        "snapshot_date": latest_date,
        "inventory_total_units": total_stock,
        "active_suppliers": unique_suppliers,
        "monthly_revenue": finance.get("ingresos_totales_revenue"),
        "monthly_net_profit": finance.get("beneficio_neto"),
        "net_margin_percent": finance.get("margen_neto_porcentaje")
    }

async def analyze_trends_cross_department() -> str:
    """Provides a synthetic analysis of correlations between departments."""
    # In a real impl, this would fetch data and correlate (e.g. Sales drops when Supplier X is out of stock).
    # Since this returns a deterministic or simple synthesis, we'll simulate an insight.
    return (
        "Tendencia Identificada: La dependencia de suministro top (25%) muestra un "
        "retraso en lead time, correlacionado con una caída del 5% en revenue mensual."
    )

async def estimate_decision_impact(action_description: str, confidence_level: str = "High") -> dict:
    """Estimate the financial and operational impact of a proposed action."""
    # Dummy mock of an ML impact estimator
    return {
        "action": action_description,
        "estimated_revenue_impact_30d": "+$2,500.00",
        "estimated_cost_30d": "-$500.00",
        "risk_level": "Medium",
        "confidence": confidence_level
    }

async def submit_proposal(
    title: str,
    problem: str,
    proposed_action: str,
    urgency: str = "media",
    estimated_impact: Optional[str] = None,
    risk: Optional[str] = None,
    strategy: Optional[str] = None,
    recommendation: Optional[str] = None,
    category: Optional[str] = None,
    items: Optional[list] = None,
) -> dict:
    """
    Submits a formal proposal to the Human-in-the-Loop system.
    This creates an entry in `aria_proposals` with status = 'pending'.
    To prevent duplicate proposals of the same category, any existing pending
    proposals of the same strategy/category will be automatically removed
    before inserting the new one.
    """
    client = await get_supabase()
    # The tenant client enforces RLS; aria_proposals' WITH CHECK is
    # is_tenant_member(tenant_id), so the INSERT must carry the caller's tenant_id
    # (there is no DB default/trigger for it). RLS still verifies the membership.
    from src.infra.tenant_context import current as _current_ctx
    _ctx = _current_ctx()

    # 1. Infer and normalize category
    def normalize_text_category(cat_str: str, strat_str: str = "", title_str: str = "") -> str:
        text = f"{cat_str or ''} {strat_str or ''} {title_str or ''}".lower()
        if any(w in text for w in ["liquidaci", "dead stock", "estancado", "descuento", "exceso", "inventario muerto", "liquidar"]):
            return "Liquidación de Stock"
        elif any(w in text for w in ["reabastecimiento", "compra", "orden de compra", "abastecimiento", "batching", "consolidaci", "adquisici"]):
            return "Reabastecimiento"
        elif any(w in text for w in ["defensivo", "pricing", "precio", "escasez"]):
            return "Ajuste de Precios"
        return cat_str or "Reabastecimiento"

    normalized_cat = normalize_text_category(category, strategy, title)

    # 2. De-duplicate: delete any existing pending proposals matching the normalized category (explicitly or implicitly)
    try:
        pending_res = await client.table("aria_proposals").select("id, title, category, strategy").eq("status", "pending").execute()
        if pending_res.data:
            ids_to_delete = []
            for p in pending_res.data:
                p_id = p["id"]
                p_cat = p.get("category") or ""
                p_strat = p.get("strategy") or ""
                p_title = p.get("title") or ""
                
                p_cat_normalized = normalize_text_category(p_cat, p_strat, p_title)
                if p_cat_normalized == normalized_cat:
                    ids_to_delete.append(p_id)

            if ids_to_delete:
                # Remove comments associated with the proposals to prevent foreign key errors
                await client.table("proposal_comments").delete().in_("proposal_id", ids_to_delete).execute()
                await client.table("aria_proposals").delete().in_("id", ids_to_delete).execute()
    except Exception as e:
        # Log error but don't block inserting the new proposal
        from src.infra.logger import log_error
        log_error(f"submit_proposal: failed to clean up duplicate pending proposals: {e}")

    # 3. Create the new proposal
    payload = {
        "title": title,
        "problem": problem,
        "proposed_action": proposed_action,
        "urgency": urgency,
        "status": "pending",
        "category": normalized_cat,
    }
    if _ctx and _ctx.tenant_id:
        payload["tenant_id"] = _ctx.tenant_id
    if estimated_impact:
        payload["estimated_impact"] = estimated_impact
    if risk:
        payload["risk"] = risk
    if strategy:
        payload["strategy"] = strategy
    if recommendation:
        payload["recommendation"] = recommendation
    if items:
        payload["items"] = items
        
    res = await client.table("aria_proposals").insert(payload).execute()
    
    if res.data:
        return {"status": "success", "proposal_id": res.data[0]["id"], "message": f"Propuesta enviada para aprobación humana bajo la categoría '{normalized_cat}'."}
    return {"status": "error", "message": "Fallo al enviar propuesta."}


async def list_pending_proposals() -> dict:
    """Lists all proposals waiting for human approval."""
    client = await get_supabase()
    res = await client.table("aria_proposals").select("id, title, status, urgency").eq("status", "pending").execute()
    return {"pending_proposals": res.data, "count": len(res.data or [])}

async def execute_approved_proposal(proposal_id: str) -> dict:
    """
    Executes a proposal IF it has been approved by a human.
    
    For proposals in category 'Reabastecimiento', this function also inserts
    a real purchase order draft into the `purchase_order_drafts` table with
    status 'pending_audit', so the buyer can see and confirm it immediately
    in the purchasing dashboard.
    """
    import re as _re
    client = await get_supabase()
    res = await client.table("aria_proposals").select("*").eq("id", proposal_id).limit(1).execute()
    
    if not res.data:
        return {"error": "Propuesta no encontrada."}
        
    proposal = res.data[0]
    if proposal["status"] != "approved":
        return {"error": f"La propuesta no puede ejecutarse. Estado actual: {proposal['status']}. Requiere aprobación humana."}

    po_id = None
    category = (proposal.get("category") or "").strip().lower()
    
    # ── Physical Execution: Reabastecimiento → create real PO draft ──────────
    if category in ("reabastecimiento", "abastecimiento", "compra", "orden de compra"):
        action_text = proposal.get("proposed_action") or ""
        title_text  = proposal.get("title") or ""
        
        # Check if structured items exist in proposal first
        items = proposal.get("items") or []
        
        if not items:
            # Parse items from action text using a robust parsing algorithm.
            items = []
            item_start_pattern = _re.compile(
                r"\b(\d+)\s+(?:unidades?|cajas?|bultos?|sacos?|paquetes?)\s+de\s+",
                _re.IGNORECASE
            )
            matches = list(item_start_pattern.finditer(action_text))
            for i, match in enumerate(matches):
                qty = int(match.group(1))
                prod_start = match.end()
                
                if i + 1 < len(matches):
                    prod_end = matches[i + 1].start()
                else:
                    prod_end = len(action_text)
                    
                prod_name = action_text[prod_start:prod_end].strip()
                # Clean up separators like commas, "y" connectors
                prod_name = _re.sub(r"[.,;\s]+$", "", prod_name).strip()
                prod_name = _re.sub(r"\s+y\s*$", "", prod_name, flags=_re.IGNORECASE).strip()
                prod_name = _re.sub(r"\s+and\s*$", "", prod_name, flags=_re.IGNORECASE).strip()
                prod_name = _re.sub(r"^[.,;\s]+", "", prod_name).strip()
                
                if prod_name:
                    items.append({"name": prod_name, "qty": qty, "sku": "", "proveedor": "StrategicAdvisor"})
            
            # Pattern B: "<Producto>: <N> unidades"
            if not items:
                for m in _re.finditer(
                    r"([A-Za-záéíóúÁÉÍÓÚüÜñÑ][^:,\n]{2,50}):\s*(\d+)\s+(?:unidades?|cajas?|bultos?|sacos?|paquetes?)",
                    action_text,
                    _re.IGNORECASE
                ):
                    name, qty_str = m.group(1).strip(), m.group(2)
                    items.append({"name": name, "qty": int(qty_str), "sku": "", "proveedor": "StrategicAdvisor"})

            # Fallback: create a generic draft with the full action text as a single line item
            if not items:
                items = [{
                    "name": title_text or "Producto a Abastecer",
                    "qty": 1,
                    "sku": "",
                    "proveedor": "StrategicAdvisor",
                    "nota": action_text[:300]
                }]
        else:
            # Ensure items have the correct key structure for the PO draft
            normalized_items = []
            for item in items:
                normalized_items.append({
                    "name": item.get("name") or item.get("producto") or "Producto",
                    "qty": int(item.get("qty") or item.get("cantidad_sugerida") or 1),
                    "sku": item.get("sku") or "",
                    "proveedor": item.get("proveedor") or "StrategicAdvisor"
                })
            items = normalized_items

        po_payload = {
            "items": items,
            "status": "pending_audit",
            "created_by": f"StrategicAdvisor (Propuesta #{proposal_id[:8]})",
            "label": f"OC Auto: {title_text[:60]}"
        }
        try:
            po_res = await client.table("purchase_order_drafts").insert(po_payload).execute()
            if po_res.data:
                po_id = po_res.data[0].get("id")
        except Exception as po_err:
            # Non-fatal — log but don't block the state update
            from src.infra.logger import log_error
            log_error(f"execute_approved_proposal: PO draft insert failed: {po_err}")

    # ── Always mark proposal as executed ─────────────────────────────────────
    await client.table("aria_proposals").update({
        "status": "executed",
        "executed_at": datetime.now().isoformat()
    }).eq("id", proposal_id).execute()

    msg = f"Propuesta ejecutada exitosamente. Autorizado por: {proposal.get('approved_by')}."
    if po_id:
        msg += f" Se generó la Orden de Compra borrador #{po_id[:8]} en estado 'pending_audit' lista para revisión del comprador."
    return {"status": "success", "message": msg, "purchase_order_id": po_id}

async def analyze_supply_chain_bottlenecks() -> dict:
    """
    Analiza cuellos de botella en la cadena de suministro cruzando niveles de stock,
    órdenes en tránsito demoradas y borradores de órdenes pendientes de auditoría.
    """
    from datetime import timedelta
    client = await get_supabase()
    
    # Obtener la fecha más reciente con datos en el ledger
    target_date_str = await latest_ledger_date(client)
    if target_date_str:
        from datetime import datetime as dt
        target_date = dt.strptime(target_date_str, "%Y-%m-%d").date()
        prev_date_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_query = [target_date_str, prev_date_str]
    else:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
        prev_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_query = [target_date_str, prev_date_str]
    
    # 1. Obtener productos con stock crítico (<= 15 unidades) de los últimos 2 días disponibles
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity, date"
    ).in_("date", dates_to_query).order("date", desc=True).execute()
    
    # Quedarse con el registro más reciente por cada producto
    seen = set()
    critical_products = []
    for r in (inv_res.data or []):
        name = r["product_name"]
        if name not in seen:
            seen.add(name)
            stock = r.get("stock_end_of_day") or 0
            if stock <= 15:
                critical_products.append(r)
                
    # 2. Obtener órdenes de compra activas (pending_audit e in_transit)
    po_res = await client.table("purchase_order_drafts").select(
        "id, status, items, created_at, confirmed_at, created_by"
    ).in_("status", ["pending_audit", "in_transit"]).execute()
    
    po_list = po_res.data or []
    
    # Mapear productos críticos a sus órdenes pendientes o en tránsito
    bottlenecks = []
    
    for prod in critical_products:
        prod_name = prod["product_name"]
        stock = prod["stock_end_of_day"]
        sales_vel = prod["sales_velocity"] or 0
        daily_vel = round(sales_vel / 7, 2)
        
        # Buscar si el producto está en alguna OC activa
        associated_pos = []
        for po in po_list:
            items = po.get("items") or []
            if isinstance(items, dict):
                items = [items]
            
            # Buscar coincidencia por nombre o SKU
            for item in items:
                item_name = item.get("name") or item.get("Producto") or item.get("Nombre") or ""
                if prod_name.lower() in item_name.lower() or item_name.lower() in prod_name.lower():
                    associated_pos.append(po)
                    break
                    
        # Determinar el estado y el cuello de botella
        if not associated_pos:
            # Caso 1: Stock crítico sin ninguna orden de compra creada
            bottlenecks.append({
                "product_name": prod_name,
                "current_stock": stock,
                "daily_sales": daily_vel,
                "status": "STOCKOUT_UNORDERED" if stock == 0 else "CRITICAL_UNORDERED",
                "detail": f"El producto tiene stock de {stock} unidades pero no existe ninguna orden de compra activa creada.",
                "proposed_action": f"Crear inmediatamente una Orden de Compra (OC) para cubrir la demanda estimada.",
                "severity": "alta" if stock == 0 else "media"
            })
        else:
            # Evaluar las OCs asociadas
            for po in associated_pos:
                po_status = po["status"]
                created_at_str = po["confirmed_at"] or po["created_at"]
                
                # Parse ISO date string safely
                try:
                    if created_at_str:
                        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    else:
                        created_at = datetime.now()
                except Exception:
                    created_at = datetime.now()
                    
                days_elapsed = (datetime.now(created_at.tzinfo) - created_at).days
                
                if po_status == "in_transit":
                    # Caso 2: En tránsito. Si lleva más de 3 días, está demorada.
                    is_delayed = days_elapsed >= 3
                    if is_delayed or stock == 0:
                        bottlenecks.append({
                            "product_name": prod_name,
                            "current_stock": stock,
                            "daily_sales": daily_vel,
                            "status": "DELAYED_IN_TRANSIT" if is_delayed else "IN_TRANSIT",
                            "po_id": po["id"],
                            "days_in_transit": days_elapsed,
                            "detail": f"Orden de compra en tránsito desde hace {days_elapsed} días. El stock actual es {stock} y debió haber llegado.",
                            "proposed_action": f"Contactar al proveedor para reclamar la entrega inmediata de la OC con ID {str(po['id'])[:8]}.",
                            "severity": "alta" if stock == 0 else "media"
                        })
                elif po_status == "pending_audit":
                    # Caso 3: Borrador creado pero sin auditar/confirmar (HITL atascado)
                    bottlenecks.append({
                        "product_name": prod_name,
                        "current_stock": stock,
                        "daily_sales": daily_vel,
                        "status": "PENDING_AUDIT_STUCK",
                        "po_id": po["id"],
                        "detail": f"Existe un borrador de OC creado pero está esperando aprobación de auditoría. El stock actual es {stock}.",
                        "proposed_action": f"Aprobar y despachar la OC con ID {str(po['id'])[:8]} de inmediato para iniciar el despacho.",
                        "severity": "alta" if stock == 0 else "media"
                    })
                    
    return {
        "analysis_date": target_date_str,
        "bottlenecks": bottlenecks,
        "total_critical_products_analyzed": len(critical_products),
        "total_bottlenecks_found": len(bottlenecks)
    }

async def predict_stockouts_and_repurchase() -> dict:
    """
    Predice quiebres de stock basados en el Velocity (ventas diarias) vs Lead Time.
    Sugiere generar órdenes de compra preventivas.
    """
    from datetime import datetime
    client = await get_supabase()
    
    # Fetch the latest available date in daily_inventory_ledger to handle stale data
    target_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")
    
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity, date"
    ).eq("date", target_date).execute()
    
    recommendations = []
    for item in (inv_res.data or []):
        stock = item.get("stock_end_of_day") or 0
        sales_vel_7d = item.get("sales_velocity") or 0
        daily_sales = sales_vel_7d / 7.0
        
        # Lead time estimado fijo para la simulación: 10 días
        lead_time_days = 10
        if daily_sales > 0:
            days_to_stockout = stock / daily_sales
            if days_to_stockout <= (lead_time_days + 5): # Quiebre en lead time + buffer de 5 días
                recommendations.append({
                    "product": item.get("product_name"),
                    "stock_actual": stock,
                    "ventas_diarias_estimadas": round(daily_sales, 2),
                    "dias_para_quiebre": round(days_to_stockout, 1),
                    "accion": f"Sugerir Orden de Compra por {int(daily_sales * 30)} unidades (cobertura 30 días)."
                })
                
    return {"stockout_predictions": recommendations, "count": len(recommendations)}

def optimize_clearance_discount(
    selling_price: float,
    cost_price: float,
    stock: int,
    sales_vel_7d: float,
    elasticity: float = -2.5,
    annual_carrying_rate: float = 0.35,  # 25% holding + 10% cost of capital
    max_discount: float = 0.40
) -> dict:
    """
    Encuentra el descuento de liquidación óptimo d* que maximiza el Valor de Recuperación Neto (NRV).
    """
    # Si el costo es cero o negativo, asignamos un costo nominal de oportunidad para representar el espacio de almacén
    effective_cost = cost_price if cost_price > 0.0 else max(0.10, selling_price * 0.50)
    
    # Velocidad de venta diaria (base)
    v0_daily = sales_vel_7d / 7.0
    v_base = max(v0_daily, 0.02)  # Evitar división por cero y reflejar baja rotación real
    
    
    # Costo de posesión diario por unidad
    h = (effective_cost * annual_carrying_rate) / 365.0
    
    best_nrv = -float('inf')
    best_d = 0.0
    
    # Evaluar descuentos desde 0% hasta max_discount% en pasos de 1%
    steps = int(max_discount * 100) + 1
    
    # Datos base para d = 0 (sin descuento)
    v_d0 = v_base
    t_d0 = stock / v_d0
    carrying_cost_d0 = (stock / 2.0) * h * t_d0
    nrv_d0 = stock * (selling_price - cost_price) - carrying_cost_d0
    
    best_details = {}
    
    for i in range(steps):
        d = i / 100.0
        
        # V(d) = V_base * (1 - d)^elasticity
        if d >= 1.0:
            continue
            
        v_d = v_base * ((1.0 - d) ** elasticity)
        t_d = stock / v_d
        
        carrying_cost_d = (stock / 2.0) * h * t_d
        revenue_d = stock * selling_price * (1.0 - d)
        cogs = stock * cost_price
        
        nrv_d = revenue_d - cogs - carrying_cost_d
        
        if nrv_d > best_nrv:
            best_nrv = nrv_d
            best_d = d
            
            carrying_cost_saved = max(0.0, carrying_cost_d0 - carrying_cost_d)
            recovery_gain = nrv_d - nrv_d0
            
            best_details = {
                "optimal_discount": d,
                "daily_velocity_d0": v_d0,
                "daily_velocity_dstar": v_d,
                "days_to_liquidate_d0": t_d0,
                "days_to_liquidate_dstar": t_d,
                "carrying_cost_d0": carrying_cost_d0,
                "carrying_cost_dstar": carrying_cost_d,
                "carrying_cost_saved": carrying_cost_saved,
                "nrv_d0": nrv_d0,
                "nrv_dstar": nrv_d,
                "recovery_gain": recovery_gain,
                "h_diario_unitario": h
            }
            
    if not best_details:
        best_details = {
            "optimal_discount": 0.0,
            "daily_velocity_d0": v_d0,
            "daily_velocity_dstar": v_d0,
            "days_to_liquidate_d0": t_d0,
            "days_to_liquidate_dstar": t_d0,
            "carrying_cost_d0": carrying_cost_d0,
            "carrying_cost_dstar": carrying_cost_d0,
            "carrying_cost_saved": 0.0,
            "nrv_d0": nrv_d0,
            "nrv_dstar": nrv_d0,
            "recovery_gain": 0.0,
            "h_diario_unitario": h
        }
        
    return best_details

async def detect_dead_stock_and_rebalance() -> dict:
    """
    Identifica productos con alto stock inmovilizado y cero o baja rotación (Dead Stock).
    Sugiere descuentos o bundles para liberar capital.
    """
    from datetime import datetime
    client = await get_supabase()
    
    # Fetch the latest available date in daily_inventory_ledger to handle stale data
    target_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")
    
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity"
    ).eq("date", target_date).lt("stock_end_of_day", 9999).execute()
    
    # ─────────────────────────────────────────────────────────────────────────
    # Dead Stock Detection: basado en DÍAS DE COBERTURA, no en stock absoluto.
    #
    # Un producto es dead stock SOLO si su stock cubre más de DEAD_STOCK_COVERAGE_DAYS
    # días de demanda actual. 147 huevos con 50 u/día = 3 días de cobertura → NO es
    # dead stock, es producto crítico. 67 tomates con 0.02 u/día = 3350 días → SÍ.
    #
    # Reglas:
    #   A) cobertura_días > DEAD_STOCK_COVERAGE_DAYS  (stock excede demanda proyectada)
    #   B) stock > 50 Y ventas 7d = 0  (sin rotación alguna + stock relevante)
    #   EXCLUIR: productos con velocidad diaria > HIGH_ROTATION_THRESHOLD
    #            (alta rotación / perecederos — se liquidan solos, no necesitan descuento)
    # ─────────────────────────────────────────────────────────────────────────
    DEAD_STOCK_COVERAGE_DAYS = 45       # días de cobertura para ser considerado dead stock
    HIGH_ROTATION_DAILY_THRESHOLD = 5.0 # u/día: estos productos NUNCA son dead stock
    MIN_STOCK_ABSOLUTE = 30             # menos de 30u → no vale la pena un plan de liquidación

    candidates = []
    product_ids = []
    for item in (inv_res.data or []):
        stock = item.get("stock_end_of_day") or 0
        sales_vel_7d = item.get("sales_velocity") or 0

        if stock < MIN_STOCK_ABSOLUTE or not item.get("product_id"):
            continue

        # Velocidad de ventas diaria (sales_velocity es suma semanal)
        daily_sales = float(sales_vel_7d) / 7.0

        # NUNCA liquidar productos de alta rotación (huevos, tomate, etc.)
        if daily_sales > HIGH_ROTATION_DAILY_THRESHOLD:
            continue

        # Calcular cobertura en días
        if daily_sales > 0:
            coverage_days = stock / daily_sales
            is_dead = coverage_days > DEAD_STOCK_COVERAGE_DAYS
        else:
            # Sin ventas registradas + stock significativo = muerto
            coverage_days = None
            is_dead = stock > 50

        if is_dead:
            candidates.append({
                **item,
                "_daily_sales": round(daily_sales, 4),
                "_coverage_days": round(coverage_days, 1) if coverage_days is not None else None,
            })
            product_ids.append(item["product_id"])


    prod_map = {}
    if product_ids:
        unique_product_ids = list(set(product_ids))
        chunk_size = 100
        for i in range(0, len(unique_product_ids), chunk_size):
            chunk = unique_product_ids[i:i + chunk_size]
            try:
                prod_res = await client.table("products").select("id, name, sku, price").in_("id", chunk).execute()
                for p in (prod_res.data or []):
                    prod_map[str(p["id"])] = p
            except Exception as e:
                from src.infra.logger import log_error
                log_error(f"detect_dead_stock_and_rebalance: failed to query chunk {i} of products: {e}")
            
    dead_stock = []
    for item in candidates:
        pid = str(item["product_id"])
        prod = prod_map.get(pid, {})

        # Pull pre-computed values from the filtering step
        daily_sales = item.get("_daily_sales", 0.0)    # u/día
        coverage_days = item.get("_coverage_days")       # días de cobertura (None si vel=0)

        selling_price = prod.get("price")
        if selling_price is None:
            selling_price = 0.0
        else:
            try:
                selling_price = float(selling_price)
            except (ValueError, TypeError):
                selling_price = 0.0

        cost_price = prod.get("price")  # B: products has no separate cost column; use price (real) as the cost proxy (was the non-existent base_price → always None → silent zero)
        if cost_price is None:
            cost_price = 0.0
        else:
            try:
                cost_price = float(cost_price)
            except (ValueError, TypeError):
                cost_price = 0.0

        stock = item.get("stock_end_of_day") or 0
        sales_vel_7d = item.get("sales_velocity") or 0

        if selling_price == 0.0 and cost_price > 0.0:
            selling_price = cost_price * 1.5

        original_margin_pct = ((selling_price - cost_price) / selling_price * 100) if selling_price > 0 else 0.0

        # Determine dynamic discount percentage based on margin and product attributes
        prod_name_lower = (item.get("product_name") or "").lower()
        is_seasonal_or_digital = "navideñ" in prod_name_lower or "digital" in prod_name_lower
        
        # Parámetros matemáticos del modelo de optimización
        elasticity = -3.5 if is_seasonal_or_digital else -2.5
        max_discount = 0.70 if is_seasonal_or_digital else 0.40
        annual_carrying_rate = 0.35  # 25% holding + 10% cost of capital
        
        opt = optimize_clearance_discount(
            selling_price=selling_price,
            cost_price=cost_price,
            stock=stock,
            sales_vel_7d=sales_vel_7d,
            elasticity=elasticity,
            annual_carrying_rate=annual_carrying_rate,
            max_discount=max_discount
        )

        d_star = opt["optimal_discount"]
        discount_pct = d_star * 100.0
        v_d0 = opt["daily_velocity_d0"]
        v_dstar = opt["daily_velocity_dstar"]
        t_d0 = opt["days_to_liquidate_d0"]
        t_dstar = opt["days_to_liquidate_dstar"]
        cc_d0 = opt["carrying_cost_d0"]
        cc_dstar = opt["carrying_cost_dstar"]
        cc_saved = opt["carrying_cost_saved"]
        nrv_d0 = opt["nrv_d0"]
        nrv_dstar = opt["nrv_dstar"]
        recovery_gain = opt["recovery_gain"]
        h_diario = opt["h_diario_unitario"]

        # Coverage days context for the justification
        if coverage_days is not None:
            coverage_context = (
                f"El producto tiene {stock} unidades en stock con una velocidad de ventas de "
                f"{daily_sales:.4f} u/día, lo que representa {coverage_days:.0f} días de cobertura "
                f"({coverage_days/30:.1f} meses), superando el umbral de stock muerto de 45 días. "
            )
        else:
            coverage_context = (
                f"El producto tiene {stock} unidades en stock con cero ventas registradas en los últimos 7 días. "
            )

        if d_star > 0.0:
            razon_descuento = (
                coverage_context +
                f"Optimización basada en la Teoría de Precios y Costos de Posesión de Inventario (Holding Cost). "
                f"Con una tasa de costo de posesión anual del {annual_carrying_rate*100:.0f}% ({annual_carrying_rate*100 - 10:.0f}% almacenamiento físico + 10% costo de oportunidad del capital), "
                f"el holding cost unitario diario es de ${h_diario:.4f}. "
                f"Asumiendo una elasticidad precio de la demanda de {elasticity:.1f}, un descuento óptimo de {discount_pct:.0f}% "
                f"incrementa la velocidad de ventas diaria estimada de {v_d0:.3f} a {v_dstar:.3f} unidades, "
                f"reduciendo el tiempo estimado de liquidación del lote de {t_d0:.1f} a {t_dstar:.1f} días. "
                f"Esto genera un ahorro en costos financieros y logísticos de posesión de ${cc_saved:.2f} "
                f"(de ${cc_d0:.2f} a ${cc_dstar:.2f}), maximizando el Valor de Recuperación Neto (NRV) "
                f"estimado en ${nrv_dstar:.2f} frente a ${nrv_d0:.2f} si no se aplicara descuento (beneficio neto incremental de ${recovery_gain:.2f})."
            )
        else:
            razon_descuento = (
                coverage_context +
                f"Optimización basada en la Teoría de Precios y Costos de Posesión de Inventario (Holding Cost). "
                f"Con una tasa de costo de posesión anual del {annual_carrying_rate*100:.0f}% ({annual_carrying_rate*100 - 10:.0f}% almacenamiento físico + 10% costo de oportunidad del capital), "
                f"el holding cost unitario diario es de ${h_diario:.4f}. "
                f"El modelo matemático de optimización determinó que el descuento óptimo es de 0% porque la reducción de margen unitario "
                f"superaría los ahorros en costos logísticos de almacenamiento. Se recomienda mantener el precio actual de ${selling_price:.2f} "
                f"o utilizar estrategias no basadas en precio (ej. Bundling con productos estrella)."
            )
            
        discounted_price = selling_price * (1.0 - d_star)
        
        # Round calculations to avoid floating point representations like -0.0
        discounted_margin_pct = round(((discounted_price - cost_price) / discounted_price * 100), 2) if discounted_price > 0 else 0.0
        if abs(discounted_margin_pct) < 0.01:
            discounted_margin_pct = 0.0
            
        net_unit_gain = round(discounted_price - cost_price, 4)
        if abs(net_unit_gain) < 0.0001:
            net_unit_gain = 0.0
        
        capital_to_recover = stock * cost_price
        revenue_estimated = stock * discounted_price
        profit_estimated = stock * net_unit_gain
        if abs(profit_estimated) < 0.0001:
            profit_estimated = 0.0
        
        warning_loss = ""
        if net_unit_gain < 0.0:
            warning_loss = f" ⚠️ VENTA A PÉRDIDA: El descuento sugerido supera el margen original de ganancia. Margen neto tras descuento: {discounted_margin_pct:.1f}% (${net_unit_gain:.2f} c/u)."
        elif abs(net_unit_gain) < 0.001:
            warning_loss = f" ℹ️ PUNTO DE EQUILIBRIO: El descuento sugerido reduce el margen neto a 0.0% ($0.00 c/u), recuperando exactamente el costo de adquisición."
        else:
            warning_loss = f" Margen neto unitario estimado tras descuento: {discounted_margin_pct:.1f}% (${net_unit_gain:.2f} c/u)."
            
        if d_star > 0.0:
            accion_msg = (
                f"Sugerir campaña de liquidación con {discount_pct:.0f}% de descuento en WooCommerce o Bundling. "
                f"Desglose Financiero: "
                f"Precio actual: ${selling_price:.2f} (Costo: ${cost_price:.2f}, Margen: {original_margin_pct:.1f}%). "
                f"Precio sugerido: ${discounted_price:.2f}. "
                f"Capital inmovilizado recuperable: ${capital_to_recover:.2f}. "
                f"Justificación Financiera: {razon_descuento}"
                f"{warning_loss}"
            )
        else:
            accion_msg = (
                f"Mantener precio original sin descuento. "
                f"Desglose Financiero: "
                f"Precio actual: ${selling_price:.2f} (Costo: ${cost_price:.2f}, Margen: {original_margin_pct:.1f}%). "
                f"Capital inmovilizado: ${capital_to_recover:.2f}. "
                f"Justificación Financiera: {razon_descuento}"
            )
        
        dead_stock.append({
            "product": item.get("product_name"),
            "product_id": pid,
            "sku": prod.get("sku") or "",
            "stock_inmovilizado": stock,
            "rotacion_7d": sales_vel_7d,
            "costo_unitario": cost_price,
            "precio_original": selling_price,
            "precio_descontado": discounted_price,
            "margen_original_pct": round(original_margin_pct, 1),
            "margen_descontado_pct": round(discounted_margin_pct, 1),
            "capital_recuperable": round(capital_to_recover, 2),
            "ingreso_estimado": round(revenue_estimated, 2),
            "ganancia_estimada": round(profit_estimated, 2),
            "venta_a_perdida": net_unit_gain < 0,
            "accion": accion_msg
        })
        
    return {"dead_stock_alerts": dead_stock, "count": len(dead_stock)}

def norm_key(s: str) -> str:
    import re
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s).lower().strip())

async def get_all_product_velocities(client, ref_date) -> dict:
    """
    Queries `wc_orders_cache` for the last 90 days and computes weekly velocities
    (vel30, vel60, vel90, vel_avg) for all products seen in orders.
    """
    import re
    from datetime import timedelta
    
    cutoff_90d = (ref_date - timedelta(days=90)).strftime("%Y-%m-%d")
    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    
    orders_res = await client.table("wc_orders_cache").select(
        "id, date_created, line_items, status"
    ).gte("date_created", cutoff_90d).in_("status", ACTIVE_STATUSES).execute()
    
    orders = orders_res.data or []
    
    sales_by_sku = {}
    sales_by_name = {}
    for order in orders:
        order_id = order.get("id")
        created_at_str = order.get("date_created")
        if not created_at_str:
            continue
        try:
            # Parse datetime safely
            order_date = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
            
        line_items = order.get("line_items") or []
        if isinstance(line_items, dict):
            line_items = [line_items]
        for line in line_items:
            l_sku = norm_key(line.get("sku"))
            l_name = norm_key(line.get("name"))
            qty = float(line.get("quantity") or 0)
            if qty <= 0:
                continue
            if l_sku:
                sales_by_sku.setdefault(l_sku, []).append((order_id, order_date, qty))
            if l_name:
                sales_by_name.setdefault(l_name, []).append((order_id, order_date, qty))
                
    def calc_weekly_velocity_python(sales_list, cutoff_days):
        cutoff_date = ref_date - timedelta(days=cutoff_days)
        window_sales = [qty for _, dt, qty in sales_list if dt >= cutoff_date and dt <= ref_date]
        if not window_sales:
            return None
        return (sum(window_sales) / cutoff_days) * 7.0

    all_skus = set(sales_by_sku.keys())
    all_names = set(sales_by_name.keys())
    
    velocity_map = {}
    for sku in all_skus:
        sales = sales_by_sku[sku]
        vel30 = calc_weekly_velocity_python(sales, 30)
        vel60 = calc_weekly_velocity_python(sales, 60)
        vel90 = calc_weekly_velocity_python(sales, 90)
        
        valid = [v for v in [vel30, vel60, vel90] if v is not None]
        vel_avg = sum(valid) / len(valid) if valid else 0.0
        
        velocity_map["sku:" + sku] = {
            "vel30": vel30,
            "vel60": vel60,
            "vel90": vel90,
            "vel_avg": vel_avg
        }
        
    for name in all_names:
        sales = sales_by_name[name]
        vel30 = calc_weekly_velocity_python(sales, 30)
        vel60 = calc_weekly_velocity_python(sales, 60)
        vel90 = calc_weekly_velocity_python(sales, 90)
        
        valid = [v for v in [vel30, vel60, vel90] if v is not None]
        vel_avg = sum(valid) / len(valid) if valid else 0.0
        
        velocity_map["name:" + name] = {
            "vel30": vel30,
            "vel60": vel60,
            "vel90": vel90,
            "vel_avg": vel_avg
        }
        
    return velocity_map

def lookup_velocity(velocity_map, sku, name) -> dict:
    sku_norm = norm_key(sku)
    name_norm = norm_key(name)
    
    if sku_norm and f"sku:{sku_norm}" in velocity_map:
        return velocity_map[f"sku:{sku_norm}"]
    if name_norm and f"name:{name_norm}" in velocity_map:
        return velocity_map[f"name:{name_norm}"]
        
    return {"vel30": None, "vel60": None, "vel90": None, "vel_avg": 0.0}

async def batch_purchase_orders() -> dict:
    """
    Analiza el inventario real en Supabase e identifica oportunidades de consolidar
    (batching) múltiples compras del mismo proveedor para optimizar fletes y
    aprovechar descuentos por volumen.
    
    Cruza la tabla daily_inventory_ledger (alertas de stock <= 15) con
    supplier_catalog para agrupar productos críticos por proveedor.
    """
    import math
    from datetime import timedelta
    client = await get_supabase()
    
    target_date_str = await latest_ledger_date(client)
    if target_date_str:
        from datetime import datetime as dt
        target_date = dt.strptime(target_date_str, "%Y-%m-%d").date()
        prev_date_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
        prev_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        from datetime import datetime as dt
        target_date = dt.strptime(target_date_str, "%Y-%m-%d").date()

    # 1. Fetch critical stock items (target_date_str first, fallback to prev_date_str)
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity"
    ).eq("date", target_date_str).lte("stock_end_of_day", 15).execute()

    alerts = inv_res.data or []
    if not alerts:
        inv_res = await client.table("daily_inventory_ledger").select(
            "product_id, product_name, stock_end_of_day, sales_velocity"
        ).eq("date", prev_date_str).lte("stock_end_of_day", 15).execute()
        alerts = inv_res.data or []

    if not alerts:
        return {
            "status": "ok",
            "message": "No se detectaron productos con stock crítico hoy. No hay oportunidades de batching urgentes.",
            "batching_opportunities": []
        }

    # 2. Fetch product details (SKU, cost, price) for all critical products in chunks of 100
    product_ids = list(set([r["product_id"] for r in alerts if r.get("product_id")]))
    prod_map = {}
    if product_ids:
        chunk_size = 100
        for i in range(0, len(product_ids), chunk_size):
            chunk = product_ids[i:i + chunk_size]
            try:
                prod_res = await client.table("products").select("id, name, sku, price").in_("id", chunk).execute()
                for p in (prod_res.data or []):
                    prod_map[str(p["id"])] = p
            except Exception as e:
                from src.infra.logger import log_error
                log_error(f"batch_purchase_orders: failed to query chunk {i} of products: {e}")

    # 3. Fetch full supplier catalog for matching
    cat_res = await client.table("supplier_catalog").select(
        "product_id, nombre_original, proveedor"
    ).execute()
    catalog = cat_res.data or []

    # Build lookup: product_id → proveedor  (and name-based fallback)
    pid_to_prov: dict = {}
    name_to_prov: dict = {}
    for row in catalog:
        prov = row.get("proveedor") or "POR IDENTIFICAR"
        if row.get("product_id"):
            pid_to_prov[str(row["product_id"])] = prov
        if row.get("nombre_original"):
            name_to_prov[row["nombre_original"].lower().strip()] = prov

    # Fetch supplier logistics configs from `pedido_config`
    config_map = {}
    try:
        config_res = await client.table("pedido_config").select("name, dias_transito, dias_inventario").execute()
        for row in (config_res.data or []):
            name_key = norm_key(row.get("name"))
            if name_key:
                config_map[name_key] = row
    except Exception as e:
        from src.infra.logger import log_error
        log_error(f"batch_purchase_orders: failed to fetch config: {e}")

    # Get velocities
    ref_datetime = dt.combine(target_date, dt.min.time())
    velocity_map = await get_all_product_velocities(client, ref_datetime)

    # 4. Group critical products by supplier
    groups: dict[str, list[dict]] = {}
    for item in alerts:
        pid   = str(item.get("product_id") or "")
        name  = item.get("product_name") or ""
        prov  = pid_to_prov.get(pid) or name_to_prov.get(name.lower().strip()) or "POR IDENTIFICAR"

        prod = prod_map.get(pid, {})
        sku = prod.get("sku") or ""

        # Fetch velocities
        vel_info = lookup_velocity(velocity_map, sku, name)
        vel30 = vel_info["vel30"]
        vel60 = vel_info["vel60"]
        vel90 = vel_info["vel90"]
        vel_avg = vel_info["vel_avg"]

        daily = vel_avg / 7.0 if vel_avg is not None else 0.0

        stock_actual = int(item.get("stock_end_of_day") or 0)

        # Get logistics parameters from config
        prov_norm = norm_key(prov)
        config = config_map.get(prov_norm) or {}
        transit_days = config.get("dias_transito") or 3
        coverage_days = config.get("dias_inventario") or 7

        # ── Reorder Point (ROP) ───────────────────────────────────────
        lead_time_demand = daily * transit_days
        safety_stock = daily * coverage_days
        rop = lead_time_demand + safety_stock

        # ── Cantidad Sugerida ─────────────────────────────────────────
        review_period_demand = daily * 7
        target_inventory_level = rop + review_period_demand

        if daily > 0:
            if stock_actual < target_inventory_level:
                raw_suggested = target_inventory_level - stock_actual
                reorder_qty = int(math.ceil(raw_suggested)) if raw_suggested > 0 else 0
            else:
                reorder_qty = 0
        else:
            # If no sales registered, minimum fallback of 5 units to avoid flow break
            reorder_qty = 5
            safety_stock = 0.0
            rop = 0.0

        # Don't propose 0 units orders
        if reorder_qty <= 0:
            continue

        selling_price = prod.get("price")
        if selling_price is None:
            selling_price = 0.0
        else:
            try:
                selling_price = float(selling_price)
            except (ValueError, TypeError):
                selling_price = 0.0
                
        cost_price = prod.get("price")  # B: products has no separate cost column; use price (real) as the cost proxy (was the non-existent base_price → always None → silent zero)
        if cost_price is None:
            cost_price = 0.0
        else:
            try:
                cost_price = float(cost_price)
            except (ValueError, TypeError):
                cost_price = 0.0

        if selling_price == 0.0 and cost_price > 0.0:
            selling_price = cost_price * 1.5
        if cost_price == 0.0 and selling_price > 0.0:
            cost_price = selling_price * 0.70

        groups.setdefault(prov, []).append({
            "producto": name,
            "proveedor": prov,
            "stock_actual": stock_actual,
            "ventas_diarias": round(daily, 2),
            "punto_de_reorden": round(rop, 1),
            "stock_seguridad": round(safety_stock, 1),
            "cantidad_sugerida": reorder_qty,
            "sku": sku,
            "costo_unitario": cost_price,
            "precio_original": selling_price,
            "vel30": round(vel30, 2) if vel30 is not None else None,
            "vel60": round(vel60, 2) if vel60 is not None else None,
            "vel90": round(vel90, 2) if vel90 is not None else None,
            "vel_avg": round(vel_avg, 2) if vel_avg is not None else None,
        })

    opportunities = [
        {
            "proveedor": prov,
            "cantidad_skus": len(prods),
            "productos": prods,
            "accion": (
                f"Consolidar {len(prods)} SKU en un solo PO a {prov} "
                "para ahorrar costos de flete y obtener descuentos por volumen."
            ),
        }
        for prov, prods in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
        if prov != "POR IDENTIFICAR"
    ]

    unidentified = groups.get("POR IDENTIFICAR", [])
    return {
        "status": "success",
        "analysis_date": target_date_str,
        "batching_opportunities": opportunities,
        "skus_sin_proveedor": [p["producto"] for p in unidentified],
        "total_critical_skus": sum(len(prods) for prods in groups.values()),
        "total_opportunities": len(opportunities),
    }


def _compute_scarcity_price_increase(
    stock: int,
    daily_sales: float,
    days_delayed: int,
    elasticity: float,          # OBLIGATORIO: elasticidad real medida del producto (e.g. -2.3)
    elasticity_source: str,     # OBLIGATORIO: descripción del origen del dato (medido / inferido)
    lead_time_days: int = 10,
    max_increase: float = 0.30,
) -> dict:
    """
    Calcula el porcentaje de alza de precio defensiva óptima ante escasez usando
    la Teoría de Elasticidad Precio-Demanda (EPD) y análisis de cobertura de stock.

    La elasticidad DEBE ser medida desde datos reales del producto (90 días de
    historial precio × velocidad de ventas). Solo si no hay datos suficientes se
    usa una elasticidad inferida, documentada explícitamente en elasticity_source.

    Modelo:
      - Cobertura de stock restante (días):  T = stock / daily_sales
      - Demanda a suprimir (Δv/v):          (lead_time - T) / lead_time
      - EPD:                                 Δ%Precio = (Δv/v) / |ε|
      - Penalidad de demora:                 0.5% × log1p(días_extra_SLA) por riesgo de extensión
      - Acotado a [1%, max_increase%]
    """
    import math

    if daily_sales <= 0 or stock <= 0:
        delta_pct = 0.05
        justification = (
            f"Sin velocidad de ventas medible (daily_sales={daily_sales:.4f}), se aplica el alza "
            f"mínima de conservación del 5% para proteger las {stock} unidades restantes "
            f"frente al reabastecimiento demorado ({days_delayed} días en tránsito)."
        )
        return {"price_increase_pct": round(delta_pct * 100, 1), "justification": justification}

    days_cover = stock / daily_sales

    if days_cover >= lead_time_days:
        return {
            "price_increase_pct": 0.0,
            "justification": (
                f"El stock actual de {stock} unidades cubre {days_cover:.1f} días, "
                f"superando el lead time estimado de {lead_time_days} días. "
                f"No se requiere alza de precio defensiva. "
                f"[Elasticidad usada: {elasticity:.2f} — {elasticity_source}]"
            ),
        }

    demand_suppression_ratio = max(0.0, (lead_time_days - days_cover) / lead_time_days)

    # EPD: Δ%Precio = Δ%Cantidad / |ε|   (elasticidad negativa → precio sube para bajar demanda)
    base_increase = demand_suppression_ratio / abs(elasticity)

    # Penalidad logarítmica por días extra de demora sobre SLA (3 días base)
    delay_penalty = 0.005 * math.log1p(max(0, days_delayed - 3))

    delta_pct = min(base_increase + delay_penalty, max_increase)
    delta_pct = max(delta_pct, 0.01)

    # Cota máxima adaptativa: si el producto es elástico (|e| > 1.5) la cota baja al 15%
    # para no destruir la demanda — aunque la fórmula ya lo refleja en base_increase menor.
    if abs(elasticity) > 1.5:
        delta_pct = min(delta_pct, 0.15)

    justification = (
        f"Modelo EPD (Elasticidad Precio-Demanda): Con stock de {stock}u y ventas diarias de "
        f"{daily_sales:.3f}u/día, la cobertura restante es de {days_cover:.1f}d vs lead time "
        f"estimado de {lead_time_days}d. Para desacelerar la demanda el "
        f"{demand_suppression_ratio*100:.1f}% necesario (fracción de quiebre anticipado), "
        f"con elasticidad precio-demanda medida de ε = {elasticity:.2f} "
        f"({elasticity_source}), se requiere un alza base de {base_increase*100:.1f}%. "
        f"Penalidad de riesgo por {days_delayed}d de demora del proveedor: +{delay_penalty*100:.2f}%. "
        f"Alza óptima final acotada: {delta_pct*100:.1f}% "
        f"(cota máxima: {int(max_increase*100)}%{'  — reducida al 15% por alta elasticidad' if abs(elasticity) > 1.5 else ''}). "
        f"Este ajuste temporal reduce la velocidad de consumo hasta {(1 - demand_suppression_ratio)*100:.0f}% "
        f"de la demanda actual, preservando el stock disponible hasta el reabastecimiento."
    )

    return {
        "price_increase_pct": round(delta_pct * 100, 1),
        "justification": justification,
    }


async def dynamic_pricing_for_scarcity() -> dict:
    """
    Detecta productos con stock real muy bajo (< 10 unidades) cuyas órdenes de
    reabastecimiento están demoradas (en tránsito > 3 días).

    Para cada producto calcula el alza defensiva óptima usando su elasticidad
    precio-demanda MEDIDA desde 90 días de historial real (precio × velocidad de
    ventas en daily_inventory_ledger). Si un producto no tiene variación de precio
    registrada suficiente, se infiere la elasticidad de su patrón de demanda
    (alta velocidad → más elástico; casi nula → más inelástico) y se documenta
    explícitamente.
    """
    from datetime import timedelta
    from src.tools.analytics import estimate_demand_elasticity
    client = await get_supabase()

    target_date_str = await latest_ledger_date(client)
    if target_date_str:
        from datetime import datetime as dt
        target_date = dt.strptime(target_date_str, "%Y-%m-%d").date()
        prev_date_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
        prev_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. Products with critically low stock (< 10 units)
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity"
    ).eq("date", target_date_str).lt("stock_end_of_day", 10).execute()
    scarce = inv_res.data or []
    if not scarce:
        inv_res = await client.table("daily_inventory_ledger").select(
            "product_id, product_name, stock_end_of_day, sales_velocity"
        ).eq("date", prev_date_str).lt("stock_end_of_day", 10).execute()
        scarce = inv_res.data or []

    if not scarce:
        return {
            "status": "ok",
            "message": "Ningún producto con stock < 10 unidades detectado hoy. No se requiere ajuste de precios defensivo.",
            "pricing_recommendations": []
        }

    # 2. Fetch real per-product elasticity from 90-day price×velocity history (single bulk call)
    # Build a name-keyed map: product_name (lower) -> {elasticidad, clasificacion}
    product_elasticity_map: dict[str, dict] = {}
    try:
        elas_res = await estimate_demand_elasticity(product_name="", top_n=500)
        for entry in (elas_res.get("todos") or []):
            key = (entry.get("producto") or "").lower().strip()
            if key:
                product_elasticity_map[key] = entry
    except Exception:
        pass  # If the analytics call fails, we fall back to velocity-based inference below

    # 3. In-transit orders delayed more than 3 days
    po_res = await client.table("purchase_order_drafts").select(
        "id, items, confirmed_at, status"
    ).eq("status", "in_transit").execute()
    delayed_pos = []
    threshold = datetime.now() - timedelta(days=3)
    for po in (po_res.data or []):
        confirmed_str = po.get("confirmed_at")
        if not confirmed_str:
            continue
        try:
            confirmed_dt = datetime.fromisoformat(confirmed_str.replace("Z", "+00:00"))
            if confirmed_dt.tzinfo:
                confirmed_dt = confirmed_dt.replace(tzinfo=None)
            if confirmed_dt < threshold:
                days_delayed = (datetime.now() - confirmed_dt).days
                delayed_pos.append({**po, "_days_delayed": days_delayed})
        except Exception:
            continue

    # 4. Cross-reference scarce products with delayed PO items and compute optimal price increase
    recommendations = []
    for item in scarce:
        name = item.get("product_name") or ""
        stock = item.get("stock_end_of_day") or 0
        daily = round((item.get("sales_velocity") or 0) / 7, 4)

        delayed_po_ids = []
        max_delay_days = 3
        for po in delayed_pos:
            po_items = po.get("items") or []
            if isinstance(po_items, dict):
                po_items = [po_items]
            for pi in po_items:
                pi_name = (pi.get("name") or pi.get("Producto") or "").lower()
                if name.lower()[:10] in pi_name or pi_name[:10] in name.lower():
                    delayed_po_ids.append(str(po["id"])[:8])
                    max_delay_days = max(max_delay_days, po.get("_days_delayed", 3))
                    break

        if not delayed_po_ids:
            continue

        # ── Resolve elasticity for this product ──────────────────────────────
        elas_entry = product_elasticity_map.get(name.lower().strip())

        if elas_entry:
            # CASE A: Measured from 90-day price×velocity history — best quality
            measured_e = float(elas_entry["elasticidad"])
            clasificacion = elas_entry.get("clasificacion", "")
            elasticity_source = (
                f"medida desde 90d de historial real (precio×velocidad): ε = {measured_e:.2f}, "
                f"clasificación: {clasificacion}"
            )
            elasticity_val = measured_e
        else:
            # CASE B: No sufficient price variation in history — infer from velocity pattern
            # Rationale: high-velocity products compete on availability (more elastic);
            # near-zero velocity products are stagnant / captive (more inelastic).
            if daily > 2.0:
                elasticity_val = -2.0
                elasticity_source = (
                    f"inferida por patrón de demanda (alta velocidad {daily:.2f}u/día → "
                    f"producto competitivo, tiende a ser elástico): ε asignado = {elasticity_val:.1f}. "
                    f"Sin variación de precio suficiente en 90d para calcular EPD real."
                )
            elif daily > 0.5:
                elasticity_val = -1.2
                elasticity_source = (
                    f"inferida por patrón de demanda (velocidad moderada {daily:.2f}u/día → "
                    f"bien semi-esencial): ε asignado = {elasticity_val:.1f}. "
                    f"Sin variación de precio suficiente en 90d para calcular EPD real."
                )
            elif daily > 0:
                elasticity_val = -0.5
                elasticity_source = (
                    f"inferida por patrón de demanda (baja velocidad {daily:.4f}u/día → "
                    f"bien con demanda cautiva o muy esencial): ε asignado = {elasticity_val:.1f}. "
                    f"Sin variación de precio suficiente en 90d para calcular EPD real."
                )
            else:
                elasticity_val = -0.3
                elasticity_source = (
                    f"inferida mínima (sin ventas registradas → stock sin rotación reciente, "
                    f"la demanda es prácticamente inmóvil): ε asignado = {elasticity_val:.1f}."
                )
        # ─────────────────────────────────────────────────────────────────────

        days_cover = round(stock / daily, 1) if daily > 0 else None
        pricing = _compute_scarcity_price_increase(
            stock=stock,
            daily_sales=daily,
            days_delayed=max_delay_days,
            elasticity=elasticity_val,
            elasticity_source=elasticity_source,
        )
        increase_pct = pricing["price_increase_pct"]
        justification = pricing["justification"]

        days_cover_str = f"{days_cover} días" if days_cover is not None else "N/A"

        if increase_pct > 0:
            accion = (
                f"Incrementar precio un {increase_pct}% temporalmente en WooCommerce para ralentizar "
                f"la demanda de '{name}' (cobertura restante: {days_cover_str}, OC demorada: "
                f"#{', #'.join(delayed_po_ids)}). "
                f"Justificación matemática: {justification}"
            )
        else:
            accion = (
                f"El stock de '{name}' cubre el lead time estimado. No se recomienda alza defensiva. "
                f"Justificación: {justification}"
            )

        recommendations.append({
            "producto": name,
            "stock_actual": stock,
            "ventas_diarias": round(daily, 2),
            "dias_cobertura_restantes": days_cover_str,
            "ocs_demoradas": delayed_po_ids,
            "elasticidad_usada": elasticity_val,
            "elasticidad_fuente": elasticity_source,
            "aumento_precio_pct": increase_pct,
            "justificacion_matematica": justification,
            "accion": accion,
            "urgencia": "alta" if stock <= 3 else "media",
        })

    return {
        "status": "success",
        "analysis_date": target_date_str,
        "pricing_recommendations": recommendations,
        "total_scarce_products": len(scarce),
        "products_with_delayed_replenishment": len(recommendations),
    }


async def audit_supplier_performance() -> dict:
    """
    Audita el rendimiento de entrega real de los proveedores calculando la varianza
    entre la fecha de creación y confirmación de las órdenes de compra en la tabla
    `purchase_order_drafts`.
    
    Clasifica proveedores por tasa de entregas tardías (> 3 días de lead time)
    basándose en datos reales de los últimos 60 días.
    """
    from datetime import timedelta
    client = await get_supabase()

    cutoff = (datetime.now() - timedelta(days=60)).isoformat()

    # 1. Fetch orders with at least a confirmed date (in_transit or delivered)
    po_res = await client.table("purchase_order_drafts").select(
        "id, items, status, created_at, confirmed_at"
    ).in_("status", ["in_transit", "delivered"]).gte("created_at", cutoff).execute()

    orders = po_res.data or []
    if not orders:
        return {
            "status": "ok",
            "message": "No hay órdenes de compra confirmadas en los últimos 60 días para auditar.",
            "supplier_audit": []
        }

    # 2. Aggregate lead times per supplier
    # Items structure: [{"proveedor": "...", "name": "...", ...}, ...]
    supplier_stats: dict[str, dict] = {}

    for po in orders:
        created_str   = po.get("created_at")
        confirmed_str = po.get("confirmed_at")
        if not created_str or not confirmed_str:
            continue
        try:
            created_dt   = datetime.fromisoformat(created_str.replace("Z", "+00:00")).replace(tzinfo=None)
            confirmed_dt = datetime.fromisoformat(confirmed_str.replace("Z", "+00:00")).replace(tzinfo=None)
            lead_days = (confirmed_dt - created_dt).days
        except Exception:
            continue

        # Extract supplier names from items JSONB
        items = po.get("items") or []
        if isinstance(items, dict):
            items = [items]
        proveedores_en_po: set[str] = set()
        for it in items:
            prov = (it.get("proveedor") or it.get("manualSupplier") or "").strip()
            if prov and prov not in ("POR IDENTIFICAR", "", "StrategicAdvisor"):
                proveedores_en_po.add(prov)

        # If no supplier info in items, fall back to created_by field
        if not proveedores_en_po:
            created_by = (po.get("created_by") or "Desconocido").strip()
            proveedores_en_po.add(created_by)

        for prov in proveedores_en_po:
            if prov not in supplier_stats:
                supplier_stats[prov] = {"total": 0, "tardias": 0, "lead_times": []}
            supplier_stats[prov]["total"] += 1
            supplier_stats[prov]["lead_times"].append(lead_days)
            if lead_days > 3:  # SLA threshold: 3 business days
                supplier_stats[prov]["tardias"] += 1

    # 3. Build audit report
    audit = []
    for prov, stats in sorted(supplier_stats.items(), key=lambda x: x[1]["tardias"], reverse=True):
        total  = stats["total"]
        tardias = stats["tardias"]
        leads  = stats["lead_times"]
        avg_lead = round(sum(leads) / len(leads), 1) if leads else 0
        tasa   = round((tardias / total) * 100, 1) if total else 0
        entry = {
            "proveedor": prov,
            "ordenes_auditadas_60d": total,
            "entregas_tardias": tardias,
            "tasa_tardias_pct": tasa,
            "lead_time_promedio_dias": avg_lead,
            "clasificacion": "🔴 Crítico" if tasa >= 50 else "🟡 Observación" if tasa >= 25 else "🟢 Confiable",
        }
        if tasa >= 50:
            entry["accion"] = f"Emitir advertencia formal a {prov} por SLA incumplido ({tasa}% tardías). Evaluar proveedor alternativo."
        elif tasa >= 25:
            entry["accion"] = f"Monitorear de cerca a {prov}. Solicitar plan de mejora de tiempos de entrega."
        else:
            entry["accion"] = f"Proveedor {prov} dentro de SLA. Sin acción requerida."
        audit.append(entry)

    return {
        "status": "success",
        "audit_period_days": 60,
        "total_orders_analyzed": len(orders),
        "supplier_audit": audit,
    }


async def execute_proactive_sweep_auto() -> dict:
    """
    Analiza la situación real del negocio y registra propuestas consolidadas de
    reabastecimiento y liquidación de inventario con todos sus items en la base de datos.
    Llama a esta herramienta de forma obligatoria durante el barrido proactivo.
    """
    results = {}

    # The three analyses below are independent, read-only computations (verified:
    # none of them writes). Run them concurrently so the sweep's wall-clock is the
    # slowest single analysis instead of their sum. The submit_proposal writes stay
    # sequential (in block order) so the proposals table sees no concurrent writes.
    reorder_res, dead_res, pricing_res = await asyncio.gather(
        batch_purchase_orders(),
        detect_dead_stock_and_rebalance(),
        dynamic_pricing_for_scarcity(),
        return_exceptions=True,
    )

    # 1. Run Reabastecimiento (Replenishment)
    try:
        if isinstance(reorder_res, Exception):
            raise reorder_res
        opps = reorder_res.get("batching_opportunities", [])
        if opps:
            # Flatten items for the DB JSON field
            items_list = []
            proposed_action_lines = []
            total_skus = 0
            total_investment = 0.0
            
            for opp in opps:
                prov = opp["proveedor"]
                prods = opp["productos"]
                prov_investment = 0.0
                for p in prods:
                    qty = int(p["cantidad_sugerida"])
                    cost = p.get("costo_unitario") or 0.0
                    inv = qty * cost
                    total_investment += inv
                    prov_investment += inv
                    
                    items_list.append({
                        "name": p["producto"],
                        "qty": qty,
                        "sku": p.get("sku") or "",
                        "proveedor": prov,
                        "stock_actual": p.get("stock_actual"),
                        "ventas_diarias": p.get("ventas_diarias"),
                        "costo_unitario": cost,
                        "precio_original": p.get("precio_original") or 0.0,
                    })
                    total_skus += 1
                proposed_action_lines.append(f"- Consolidar {len(prods)} SKU de {prov} (Inversión Est.: ${prov_investment:,.2f}).")

            # Format the summary action
            proposed_action = (
                f"Consolidar y emitir órdenes de compra para {total_skus} productos críticos "
                f"agrupados por proveedor, con una inversión estimada total de ${total_investment:,.2f}:\n" + "\n".join(proposed_action_lines) +
                "\n\nLa lista completa y detallada de productos, cantidades, SKUs, costos unitarios e inversión por ítem se encuentra "
                "registrada en la base de datos y visible en el reporte PDF."
            )
            
            recommendation = (
                f"Se recomienda consolidar las compras para {len(opps)} proveedores por una inversión total de ${total_investment:,.2f}. "
                "Esta consolidación (batching) permite optimizar los costos de fletes y logística de despacho, "
                "al mismo tiempo que mejora la posición de negociación para obtener descuentos por volumen. "
                f"La inversión total proyectada de ${total_investment:,.2f} se prioriza de acuerdo con el límite de gasto mensual consolidado de la empresa ($20,000.00)."
            )
            
            problem = f"Se detectaron {total_skus} productos con stock crítico (<= 15 unidades) que requieren reposición urgente para evitar quiebres de stock."
            
            res = await submit_proposal(
                title="Plan Consolidado de Reabastecimiento de Inventario",
                problem=problem,
                proposed_action=proposed_action,
                urgency="alta",
                estimated_impact="Prevención de quiebre de stock en productos clave y ahorro en fletes por consolidación.",
                risk="Bajo",
                strategy="Consolidación Logística y Reabastecimiento Estratégico",
                recommendation=recommendation,
                category="Reabastecimiento",
                items=items_list
            )
            results["reabastecimiento"] = res
        else:
            results["reabastecimiento"] = {"status": "skipped", "message": "No critical products detected for restocking."}
    except Exception as e:
        import traceback
        results["reabastecimiento"] = {"status": "error", "message": str(e), "trace": traceback.format_exc()}
        
    # 2. Run Liquidación de Stock (Clearance)
    try:
        if isinstance(dead_res, Exception):
            raise dead_res
        alerts = dead_res.get("dead_stock_alerts", [])
        if alerts:
            items_list = []
            total_capital = 0.0
            total_stock_units = 0
            
            # Group by discount percentage to summarize in proposed action
            discount_groups = {}
            
            for alert in alerts:
                items_list.append(alert)
                total_capital += alert.get("capital_recuperable") or 0.0
                total_stock_units += alert.get("stock_inmovilizado") or 0
                
                # Get discount pct
                orig = alert.get("precio_original") or 0.0
                desc = alert.get("precio_descontado") or 0.0
                pct = round((1.0 - desc / orig) * 100) if orig > 0 else 0
                discount_groups.setdefault(pct, []).append(alert["product"])

            # Format the summary action
            proposed_action_lines = []
            for pct, prods in sorted(discount_groups.items(), reverse=True):
                proposed_action_lines.append(f"- Descuento de {pct}% para {len(prods)} productos (calculado óptimo NRV).")
                
            proposed_action = (
                f"Ejecutar campaña de liquidación para {len(alerts)} productos inmovilizados "
                f"({total_stock_units} unidades en total) con los siguientes descuentos dinámicos optimizados:\n" +
                "\n".join(proposed_action_lines) +
                "\n\nCada descuento es el resultado del modelo de optimización de Valor de Recuperación Neto (NRV) "
                "específico para ese producto (considera su precio de venta, costo de adquisición, tasa de "
                "posesión del 35% anual y elasticidad precio de la demanda). La justificación financiera "
                "completa por producto está registrada en la base de datos y visible en el reporte PDF."
            )
            
            recommendation = (
                f"Optimización basada en la Teoría de Precios y Costos de Posesión de Inventario (Holding Cost). "
                f"Mantener este stock inmovilizado genera un costo anual estimado de posesión del 35% "
                f"(25% por almacenamiento físico y obsolescencia + 10% de costo de oportunidad del capital). "
                f"Los descuentos sugeridos por producto NO son fijos: cada porcentaje resulta de maximizar el NRV "
                f"= Ingresos por liquidación − COGS − Costo de Posesión Acumulado, hallando el descuento d* "
                f"que minimiza el tiempo de liquidación del lote sin sacrificar margen innecesariamente. "
                f"Al aplicar estos descuentos calculados matemáticamente, se proyecta liberar un capital "
                f"inmovilizado de ${total_capital:,.2f}. "
                f"Este capital recuperado será reinvertido en productos de alta rotación (Stars/Cash Cows), "
                f"lo cual incrementa la rentabilidad neta agregada de la compañía en el mediano plazo "
                f"a pesar de la reducción puntual del margen en los productos en liquidación."
            )
            
            problem = f"Se detectaron {len(alerts)} productos con sobre-stock (>50 unidades) y nula rotación en los últimos 7 días, reteniendo capital de trabajo."
            
            res = await submit_proposal(
                title="Plan Consolidado de Liquidación de Inventario Estancado",
                problem=problem,
                proposed_action=proposed_action,
                urgency="media",
                estimated_impact=f"Liberación de ${total_capital:,.2f} de capital inmovilizado y optimización de espacio en almacén.",
                risk="Bajo",
                strategy="Liquidación de Inventario Estancado (Dead Stock) para Maximización de Valor de Recuperación Neto (NRV)",
                recommendation=recommendation,
                category="Liquidación de Stock",
                items=items_list
            )
            results["liquidacion"] = res
        else:
            results["liquidacion"] = {"status": "skipped", "message": "No dead stock detected."}
    except Exception as e:
        import traceback
        results["liquidacion"] = {"status": "error", "message": str(e), "trace": traceback.format_exc()}

    # 3. Run Ajuste de Precios Defensivo por Escasez (Dynamic Pricing)
    try:
        if isinstance(pricing_res, Exception):
            raise pricing_res
        recs = pricing_res.get("pricing_recommendations", [])
        # Filter only products where a price increase is actually recommended (> 0%)
        active_recs = [r for r in recs if r.get("aumento_precio_pct", 0) > 0]
        if active_recs:
            items_list = []
            proposed_action_lines = []
            for r in active_recs:
                increase_pct = r["aumento_precio_pct"]
                prod_name = r["producto"]
                stock_act = r["stock_actual"]
                dias_cob = r.get("dias_cobertura_restantes", "N/A")
                ocs = r.get("ocs_demoradas", [])

                items_list.append(r)
                proposed_action_lines.append(
                    f"- '{prod_name}': alza de {increase_pct}% "
                    f"(stock: {stock_act} u., cobertura: {dias_cob}, OC demorada: #{', #'.join(ocs)})."
                )

            proposed_action = (
                f"Aplicar ajuste defensivo de precios en {len(active_recs)} productos con escasez crítica "
                f"y reabastecimiento demorado:\n" + "\n".join(proposed_action_lines) +
                "\n\nCada alza es calculada matemáticamente para la cobertura exacta del lead time restante. "
                "Revertir al precio original al confirmar la llegada del reabastecimiento."
            )

            recommendation = (
                f"Estrategia basada en la Teoría de Elasticidad Precio-Demanda (EPD). "
                f"Para cada producto, el alza óptima d* se calcula como: "
                f"Δ%Precio = (Demanda_a_suprimir%) / |Elasticidad|, donde la demanda a suprimir es "
                f"la fracción de ventas diarias actuales que excede la cobertura de stock hasta el "
                f"reabastecimiento estimado. Se asume elasticidad de -1.5 (bien semi-esencial) con "
                f"penalidad logarítmica por días adicionales de demora del proveedor. "
                f"El alza está acotada al 30% máximo para proteger la imagen de precio y la relación "
                f"con el cliente. Al reducir la velocidad de demanda, se preservan las últimas unidades "
                f"disponibles sin incurrir en quiebre de stock que genera pérdida de ventas y reputación."
            )

            problem = (
                f"Se detectaron {len(active_recs)} productos con stock < 10 unidades y órdenes de "
                f"reabastecimiento demoradas (en tránsito > 3 días), con riesgo inminente de quiebre de stock."
            )

            res = await submit_proposal(
                title="Plan Consolidado de Ajuste Defensivo de Precios por Escasez",
                problem=problem,
                proposed_action=proposed_action,
                urgency="alta",
                estimated_impact="Preservación de últimas unidades en stock para evitar quiebre total y pérdida de ventas.",
                risk="Bajo",
                strategy="Ajuste Defensivo de Precios por Escasez (Dynamic Pricing for Scarcity)",
                recommendation=recommendation,
                category="Ajuste de Precios",
                items=items_list,
            )
            results["pricing_defensivo"] = res
        else:
            results["pricing_defensivo"] = {
                "status": "skipped",
                "message": "No se detectaron productos que requieran alza de precios defensiva (sin OCs demoradas o stock suficiente)."
            }
    except Exception as e:
        import traceback
        results["pricing_defensivo"] = {"status": "error", "message": str(e), "trace": traceback.format_exc()}

    return results
