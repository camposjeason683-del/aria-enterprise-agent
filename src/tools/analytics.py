"""
ARIA-OS: Advanced Multi-Dimensional Analytics Tools
Herramientas de análisis avanzado que cruzan datos de múltiples fuentes
para generar inteligencia de negocio de nivel C-Suite.
"""
from datetime import datetime, timedelta
from src.infra.db import get_supabase
from src.tools.ledger_common import latest_ledger_date


# ─────────────────────────────────────────────────────────────────────────────
# 1. SEGMENTACIÓN BCG OPERACIONAL
# Cruza: sales_velocity × margen_bruto_real × stock_end_of_day
# ─────────────────────────────────────────────────────────────────────────────
async def classify_products_bcg(top_n: int = 50) -> dict:
    """
    Clasifica los productos del catálogo en cuadrantes BCG Operacional
    cruzando la velocidad de ventas real con el margen bruto real
    obtenido de los costos reales almacenados en wc_orders_cache.

    Cuadrantes:
    - STAR    (Stars):      Alta velocidad + Alto margen → Proteger stock agresivamente
    - COW     (Cash Cows):  Alta velocidad + Bajo margen → Reducir costos, negociar proveedor
    - FROZEN  (Frozen):     Baja velocidad + Alto margen → Bundle con Stars, marketing cruzado
    - DOG     (Dogs):       Baja velocidad + Bajo margen → Liquidar inmediato

    Args:
        top_n: Número de productos a analizar (default 50 por rendimiento).

    Returns:
        dict con cuadrantes BCG, métricas y recomendaciones.
    """
    client = await get_supabase()

    # Fetch all products to build id (UUID) <-> sku map
    prod_res = await client.table("products").select("id, sku").execute()
    id_to_sku = {p["id"]: p["sku"] for p in (prod_res.data or []) if p.get("id") and p.get("sku")}

    # 1. Obtener fecha más reciente en el ledger
    target_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")

    # 2. Obtener velocidad de ventas y stock actuales
    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity, price"
    ).eq("date", target_date).gt("sales_velocity", 0).order("sales_velocity", desc=True).limit(top_n).execute()

    ledger_items = inv_res.data or []
    if not ledger_items:
        return {"status": "no_data", "message": "Sin datos de inventario disponibles.", "bcg_matrix": {}}

    # 3. Obtener costos reales de las últimas órdenes de WooCommerce
    # Incluye todos los estados activos (WooCommerce usa statuses personalizados)
    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    cutoff_30d = (datetime.now() - timedelta(days=30)).isoformat()
    orders_res = await client.table("wc_orders_cache").select(
        "line_items"
    ).gte("date_created", cutoff_30d).in_("status", ACTIVE_STATUSES).limit(300).execute()

    # Construir mapa sku → (costo_promedio, precio_promedio, unidades_vendidas)
    product_cost_map: dict[str, dict] = {}
    for order in (orders_res.data or []):
        for item in (order.get("line_items") or []):
            sku = item.get("sku")
            if not sku:
                continue
            price = float(item.get("price") or 0)
            qty = int(item.get("quantity") or 0)
            # Extract real cost from meta_data
            cog_cost = 0.0
            for meta in (item.get("meta_data") or []):
                if meta.get("key") == "_alg_wc_cog_item_cost":
                    try:
                        cog_cost = float(meta.get("value") or 0)
                    except (ValueError, TypeError):
                        pass
                    break

            if sku not in product_cost_map:
                product_cost_map[sku] = {"total_cost": 0.0, "total_price": 0.0, "units_sold": 0}
            product_cost_map[sku]["total_cost"] += cog_cost * qty
            product_cost_map[sku]["total_price"] += price * qty
            product_cost_map[sku]["units_sold"] += qty

    # 4. Calcular velocidad media para definir umbral de "alta" vs "baja"
    velocities = [float(item.get("sales_velocity") or 0) for item in ledger_items]
    median_velocity = sorted(velocities)[len(velocities) // 2] if velocities else 1.0

    # 5. Calcular margen medio para definir umbral de "alto" vs "bajo"
    margins = []
    for pid_data in product_cost_map.values():
        total_price = pid_data["total_price"]
        total_cost = pid_data["total_cost"]
        if total_price > 0:
            margin_pct = ((total_price - total_cost) / total_price) * 100
            margins.append(margin_pct)
    median_margin = sorted(margins)[len(margins) // 2] if margins else 30.0

    # 6. Clasificar productos
    bcg = {"STAR": [], "COW": [], "FROZEN": [], "DOG": []}

    for item in ledger_items:
        pid = item.get("product_id")
        name = item.get("product_name", "")
        velocity = float(item.get("sales_velocity") or 0)
        stock = int(item.get("stock_end_of_day") or 0)
        list_price = float(item.get("price") or 0)

        # Margen real si está disponible, si no estimar 40%
        sku = id_to_sku.get(pid)
        cost_data = product_cost_map.get(sku) if sku else None
        if cost_data and cost_data["total_price"] > 0:
            margin_pct = round(((cost_data["total_price"] - cost_data["total_cost"]) / cost_data["total_price"]) * 100, 1)
            units_sold_30d = cost_data["units_sold"]
            ganancia_30d = round(cost_data["total_price"] - cost_data["total_cost"], 2)
        else:
            margin_pct = 40.0  # default estimate
            units_sold_30d = int(velocity * 30 / 7) if velocity else 0
            ganancia_30d = round(list_price * 0.40 * units_sold_30d, 2)

        high_velocity = velocity >= median_velocity
        high_margin = margin_pct >= median_margin

        entry = {
            "producto": name,
            "velocidad_7d": velocity,
            "margen_bruto_pct": margin_pct,
            "stock_actual": stock,
            "unidades_vendidas_30d": units_sold_30d,
            "ganancia_total_30d": ganancia_30d,
        }

        if high_velocity and high_margin:
            entry["cuadrante"] = "⭐ STAR"
            entry["accion"] = f"Proteger stock. Reordenar {int(velocity * 60 / 7)} unidades (cobertura 60d). Nunca dejar en quiebre."
            bcg["STAR"].append(entry)
        elif high_velocity and not high_margin:
            entry["cuadrante"] = "🐄 COW"
            entry["accion"] = "Negociar precio con proveedor o consolidar compra en volumen para mejorar margen."
            bcg["COW"].append(entry)
        elif not high_velocity and high_margin:
            entry["cuadrante"] = "🧊 FROZEN"
            entry["accion"] = "Crear bundle con Stars. Activar descuento temporal 15% para acelerar rotación."
            bcg["FROZEN"].append(entry)
        else:
            entry["cuadrante"] = "💀 DOG"
            
            # Determinar porcentaje de descuento dinámico basado en margen
            prod_name_lower = name.lower()
            is_seasonal_or_digital = "navideñ" in prod_name_lower or "digital" in prod_name_lower
            
            if is_seasonal_or_digital:
                discount_pct = 30.0
                razon = "Descuento del 30% justificado por ser un producto altamente estacional o digital sin costo marginal de almacenamiento físico."
            elif margin_pct >= 50.0:
                discount_pct = 25.0
                razon = "Descuento del 25% seleccionado debido a un alto margen original (>=50%), lo que permite una liquidación rápida manteniendo un margen neto saludable."
            elif margin_pct >= 30.0:
                discount_pct = 15.0
                razon = "Descuento del 15% para acelerar rotación sin reducir drásticamente el beneficio, protegiendo la rentabilidad unitaria."
            elif margin_pct >= 15.0:
                discount_pct = 10.0
                razon = "Descuento conservador del 10% debido a un margen moderado, evitando caer en pérdidas o en punto de equilibrio."
            else:
                discount_pct = 5.0
                razon = "Descuento mínimo del 5% seleccionado para no erosionar el bajo margen original, priorizando recuperar el costo de adquisición."
                
            entry["accion"] = (
                f"Liquidar con {discount_pct:.0f}% de descuento. No reponer. Liberar capital de trabajo. "
                f"Justificación Financiera: {razon} Liberar este capital permite reinvertirlo en productos de alta rotación (Stars/Cash Cows) mitigando el costo de almacenamiento estimado del 25% anual."
            )
            bcg["DOG"].append(entry)

    # Sort each quadrant by ganancia_total_30d desc
    for quadrant in bcg:
        bcg[quadrant].sort(key=lambda x: x["ganancia_total_30d"], reverse=True)

    return {
        "status": "success",
        "analysis_date": target_date,
        "umbral_velocidad_mediana_7d": round(median_velocity, 2),
        "umbral_margen_mediano_pct": round(median_margin, 1),
        "resumen": {
            "stars": len(bcg["STAR"]),
            "cash_cows": len(bcg["COW"]),
            "frozen": len(bcg["FROZEN"]),
            "dogs": len(bcg["DOG"]),
        },
        "bcg_matrix": bcg,
        "top_stars": bcg["STAR"][:5],
        "top_dogs": bcg["DOG"][:5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. MARKET BASKET ANALYSIS
# Cruza: co-ocurrencias de product_ids en la misma orden
# ─────────────────────────────────────────────────────────────────────────────
async def analyze_market_basket(min_orders: int = 200, top_pairs: int = 20) -> dict:
    """
    Analiza co-ocurrencias de productos en las mismas órdenes de WooCommerce
    para identificar:
    - Anchor Products: Comprados solos o como eje principal del carrito.
      Si no están en stock, el cliente NO compra.
    - Complementary Products: Siempre comprados junto a otro producto.
    - Bundle Opportunities: Pares con alta co-ocurrencia y lift elevado.

    Args:
        min_orders: Órdenes mínimas a analizar (máx 500 por rendimiento).
        top_pairs: Pares de mayor co-ocurrencia a retornar.

    Returns:
        dict con anchor products, complementary pairs, y oportunidades de bundle.
    """
    client = await get_supabase()

    # 1. Obtener órdenes recientes con line_items
    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    orders_res = await client.table("wc_orders_cache").select(
        "id, line_items"
    ).gte("date_created", cutoff).in_("status", ACTIVE_STATUSES).limit(min(min_orders, 500)).execute()

    orders = orders_res.data or []
    if not orders:
        return {"status": "no_data", "message": "Sin órdenes disponibles para análisis."}

    # 2. Construir frecuencias individuales y de pares
    from collections import defaultdict, Counter

    item_freq: Counter = Counter()        # product_id → frecuencia en órdenes
    pair_freq: Counter = Counter()        # (pid_a, pid_b) → co-ocurrencias
    name_map: dict[int, str] = {}         # product_id → nombre

    total_orders = 0
    for order in orders:
        items = order.get("line_items") or []
        if not items:
            continue
        total_orders += 1

        pids_in_order = []
        for item in items:
            pid = item.get("product_id")
            name = item.get("name", f"Producto #{pid}")
            if pid:
                pids_in_order.append(pid)
                name_map[pid] = name
                item_freq[pid] += 1

        # Count all pairs in this order (combinaciones)
        pids_unique = list(set(pids_in_order))
        for i in range(len(pids_unique)):
            for j in range(i + 1, len(pids_unique)):
                pair = (min(pids_unique[i], pids_unique[j]), max(pids_unique[i], pids_unique[j]))
                pair_freq[pair] += 1

    # 3. Identificar Anchor Products (aparecen en > 10% de órdenes, con pocos compañeros)
    anchor_threshold = max(3, total_orders * 0.08)
    anchors = []
    for pid, freq in item_freq.most_common(30):
        if freq >= anchor_threshold:
            # How many distinct products appear alongside this one?
            companions = sum(1 for (pa, pb) in pair_freq if pa == pid or pb == pid)
            anchors.append({
                "producto": name_map.get(pid, f"#{pid}"),
                "product_id": pid,
                "frecuencia_en_ordenes": freq,
                "pct_ordenes": round((freq / total_orders) * 100, 1),
                "productos_comprados_junto": companions,
                "clasificacion": "⚓ ANCHOR (Generador de Ventas)" if freq >= anchor_threshold * 1.5 else "🔵 FRECUENTE",
            })

    # 4. Top pares de mayor co-ocurrencia (oportunidades de bundle)
    bundle_opportunities = []
    for (pa, pb), co_count in pair_freq.most_common(top_pairs):
        freq_a = item_freq[pa]
        freq_b = item_freq[pb]
        # Lift = P(A∩B) / (P(A) × P(B))
        if freq_a > 0 and freq_b > 0:
            lift = round((co_count / total_orders) / ((freq_a / total_orders) * (freq_b / total_orders)), 2)
        else:
            lift = 1.0
        bundle_opportunities.append({
            "producto_a": name_map.get(pa, f"#{pa}"),
            "producto_b": name_map.get(pb, f"#{pb}"),
            "co_ocurrencias": co_count,
            "lift": lift,
            "interpretacion": (
                "🔥 Compra muy correlacionada — Bundle ideal" if lift >= 3.0 else
                "📦 Co-compra frecuente — Bundle recomendado" if lift >= 1.5 else
                "📊 Co-compra moderada"
            ),
        })

    return {
        "status": "success",
        "ordenes_analizadas": total_orders,
        "productos_unicos": len(item_freq),
        "anchor_products": sorted(anchors, key=lambda x: x["frecuencia_en_ordenes"], reverse=True)[:10],
        "top_bundle_opportunities": bundle_opportunities[:top_pairs],
        "insight": (
            f"Se analizaron {total_orders} órdenes. "
            f"Los {len([a for a in anchors if 'ANCHOR' in a['clasificacion']])} productos Anchor "
            "son críticos para la continuidad de ventas — nunca deben entrar en quiebre."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. ELASTICIDAD DE DEMANDA POR PRODUCTO
# Cruza: series temporales de price × sales_velocity en daily_inventory_ledger
# ─────────────────────────────────────────────────────────────────────────────
async def estimate_demand_elasticity(product_name: str = "", top_n: int = 20) -> dict:
    """
    Estima la elasticidad precio-demanda de productos analizando cómo varía
    la velocidad de ventas en períodos con diferentes precios registrados
    en daily_inventory_ledger.

    Elasticidad = (Δ% Ventas) / (Δ% Precio)
    - |e| > 1.5 → Elástico: muy sensible al precio. No subir precio en escasez.
    - 0.5 < |e| <= 1.5 → Moderado: sensible pero manejable.
    - |e| <= 0.5 → Inelástico: producto esencial. Sí se puede subir precio defensivo.

    Args:
        product_name: Filtrar por nombre de producto (vacío = analizar todos).
        top_n: Máximo de productos a analizar.

    Returns:
        dict con clasificación de elasticidad y recomendaciones de pricing.
    """
    import statistics

    client = await get_supabase()

    # 1. Obtener 90 días de historial de price + sales_velocity
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    q = client.table("daily_inventory_ledger").select(
        "product_name, date, price, sales_velocity"
    ).gte("date", cutoff).gt("price", 0).order("product_name").order("date")

    if product_name:
        q = q.ilike("product_name", f"%{product_name}%")

    res = await q.limit(2000).execute()
    records = res.data or []

    if not records:
        return {"status": "no_data", "message": "Sin datos de historial de precios disponibles."}

    # 2. Agrupar por producto
    from collections import defaultdict
    products: dict[str, list] = defaultdict(list)
    for r in records:
        name = r.get("product_name", "")
        price = float(r.get("price") or 0)
        velocity = float(r.get("sales_velocity") or 0)
        if price > 0:
            products[name].append({"price": price, "velocity": velocity, "date": r["date"]})

    # 3. Calcular elasticidad para cada producto con suficiente variación
    elasticity_results = []

    for name, data_points in list(products.items())[:top_n]:
        if len(data_points) < 7:
            continue

        prices = [d["price"] for d in data_points]
        velocities = [d["velocity"] for d in data_points]

        price_range = max(prices) - min(prices)
        if price_range / max(prices) < 0.02:  # < 2% de variación en precio → skip
            continue

        # Calcular elasticidad usando puntos de inicio y fin del período
        mid = len(data_points) // 2
        first_half = data_points[:mid]
        second_half = data_points[mid:]

        avg_price_1 = statistics.mean([d["price"] for d in first_half])
        avg_price_2 = statistics.mean([d["price"] for d in second_half])
        avg_vel_1 = statistics.mean([d["velocity"] for d in first_half])
        avg_vel_2 = statistics.mean([d["velocity"] for d in second_half])

        if avg_price_1 == 0 or avg_vel_1 == 0:
            continue

        delta_price_pct = (avg_price_2 - avg_price_1) / avg_price_1
        delta_vel_pct = (avg_vel_2 - avg_vel_1) / avg_vel_1 if avg_vel_1 > 0 else 0

        if abs(delta_price_pct) < 0.01:
            continue

        elasticity = round(delta_vel_pct / delta_price_pct, 2)
        abs_e = abs(elasticity)

        if abs_e > 1.5:
            clasificacion = "🔴 ELÁSTICO"
            pricing_action = "NUNCA subir precio en escasez. Demanda caería bruscamente. Usar pricing_for_scarcity con cuidado."
        elif abs_e > 0.5:
            clasificacion = "🟡 MODERADO"
            pricing_action = "Se puede subir precio hasta +8% sin impacto severo en demanda."
        else:
            clasificacion = "🟢 INELÁSTICO"
            pricing_action = "Producto esencial. Subir precio +10-15% en escasez para proteger margen. Demanda no cae."

        elasticity_results.append({
            "producto": name,
            "elasticidad": elasticity,
            "abs_elasticidad": abs_e,
            "clasificacion": clasificacion,
            "precio_promedio_actual": round(avg_price_2, 2),
            "variacion_precio_pct": round(delta_price_pct * 100, 1),
            "variacion_demanda_pct": round(delta_vel_pct * 100, 1),
            "accion_pricing": pricing_action,
        })

    # Sort by abs_elasticidad desc (most elastic first)
    elasticity_results.sort(key=lambda x: x["abs_elasticidad"], reverse=True)

    inelasticos = [e for e in elasticity_results if "INELÁSTICO" in e["clasificacion"]]
    elasticos = [e for e in elasticity_results if "ELÁSTICO" in e["clasificacion"]]

    return {
        "status": "success",
        "productos_analizados": len(elasticity_results),
        "resumen": {
            "elasticos": len(elasticos),
            "moderados": len([e for e in elasticity_results if "MODERADO" in e["clasificacion"]]),
            "inelasticos": len(inelasticos),
        },
        "inelasticos_para_pricing_defensivo": inelasticos[:5],
        "elasticos_riesgo_alta": elasticos[:5],
        "todos": elasticity_results[:top_n],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. RENTABILIDAD REAL POR SKU
# Usa costo real de wc_orders_cache._alg_wc_cog_item_cost
# ─────────────────────────────────────────────────────────────────────────────
async def rank_products_by_real_profitability(days: int = 30, top_n: int = 25) -> dict:
    """
    Genera un ranking de los productos más y menos rentables usando el costo
    real de cada unidad vendida (_alg_wc_cog_item_cost) extraído de las
    órdenes de WooCommerce. Reemplaza estimaciones del 60% con datos reales.

    Métricas calculadas:
    - Margen unitario real = precio_venta - costo_real
    - Ganancia total = margen_unitario × unidades_vendidas
    - Margen % real = (ganancia_total / revenue_total) × 100

    Args:
        days: Período de análisis en días (default 30).
        top_n: Top N productos a retornar por categoría.

    Returns:
        dict con top performers, underperformers y productos con margen negativo.
    """
    client = await get_supabase()

    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    orders_res = await client.table("wc_orders_cache").select(
        "line_items"
    ).gte("date_created", cutoff).in_("status", ACTIVE_STATUSES).limit(500).execute()

    orders = orders_res.data or []
    if not orders:
        return {"status": "no_data", "message": f"Sin órdenes en los últimos {days} días."}

    # Aggregate per product_id
    product_data: dict[int, dict] = {}

    for order in orders:
        for item in (order.get("line_items") or []):
            pid = item.get("product_id")
            name = item.get("name", "")
            price = float(item.get("price") or 0)
            qty = int(item.get("quantity") or 0)
            if not pid or qty == 0 or price == 0:
                continue

            cog_cost = None
            for meta in (item.get("meta_data") or []):
                if meta.get("key") == "_alg_wc_cog_item_cost":
                    try:
                        cog_cost = float(meta.get("value") or 0)
                    except (ValueError, TypeError):
                        pass
                    break

            if cog_cost is None:
                continue  # Skip if no real cost data

            if pid not in product_data:
                product_data[pid] = {
                    "nombre": name,
                    "revenue_total": 0.0,
                    "costo_total": 0.0,
                    "unidades": 0,
                }

            product_data[pid]["revenue_total"] += price * qty
            product_data[pid]["costo_total"] += cog_cost * qty
            product_data[pid]["unidades"] += qty

    # Build profitability list
    profitability = []
    for pid, data in product_data.items():
        rev = data["revenue_total"]
        cost = data["costo_total"]
        units = data["unidades"]
        ganancia = round(rev - cost, 2)
        margen_pct = round((ganancia / rev) * 100, 1) if rev > 0 else 0
        margen_unit = round((rev - cost) / units, 3) if units > 0 else 0

        profitability.append({
            "producto": data["nombre"],
            "product_id": pid,
            "unidades_vendidas": units,
            "revenue_total": round(rev, 2),
            "costo_total": round(cost, 2),
            "ganancia_total": ganancia,
            "margen_bruto_pct": margen_pct,
            "margen_unitario": margen_unit,
        })

    profitability.sort(key=lambda x: x["ganancia_total"], reverse=True)

    total_revenue = sum(p["revenue_total"] for p in profitability)
    total_profit = sum(p["ganancia_total"] for p in profitability)

    margin_negativo = [p for p in profitability if p["ganancia_total"] < 0]
    top_performers = profitability[:top_n]
    underperformers = sorted(profitability, key=lambda x: x["ganancia_total"])[:10]

    return {
        "status": "success",
        "periodo_dias": days,
        "productos_con_costo_real": len(profitability),
        "revenue_total_periodo": round(total_revenue, 2),
        "ganancia_total_periodo": round(total_profit, 2),
        "margen_global_pct": round((total_profit / total_revenue) * 100, 1) if total_revenue > 0 else 0,
        "top_performers": top_performers[:top_n],
        "underperformers_criticos": underperformers[:10],
        "productos_margen_negativo": margin_negativo,
        "alerta": (
            f"⚠️ {len(margin_negativo)} productos se vendieron a pérdida en los últimos {days} días."
            if margin_negativo else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. CICLO DE VIDA DEL PRODUCTO (Product Lifecycle Stage)
# Cruza: series temporales de sales_velocity en daily_inventory_ledger
# ─────────────────────────────────────────────────────────────────────────────
async def classify_product_lifecycle(days: int = 60, top_n: int = 40) -> dict:
    """
    Clasifica cada producto en su estadio del ciclo de vida basándose
    en la tendencia de velocidad de ventas en las últimas semanas.

    Estadios:
    - 🚀 CRECIMIENTO: Velocidad acelerando > +20%/período → Preparar stock extra
    - 🏆 MADUREZ:     Velocidad estable ± 10%/período → Mantener, optimizar margen
    - 📉 DECLIVE:     Velocidad bajando > -20%/período → No reordenar en exceso, liquidar
    - 💀 AGONÍA:      Velocidad < 0.3 unidades/día o caída > -50% → Liquidar YA

    Args:
        days: Período de análisis (default 60 días en dos mitades de 30d).
        top_n: Máximo de productos a clasificar.

    Returns:
        dict con clasificación de ciclo de vida y recomendaciones.
    """
    import statistics as stats

    client = await get_supabase()

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    mid_date = (datetime.now() - timedelta(days=days // 2)).strftime("%Y-%m-%d")
    today = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    res = await client.table("daily_inventory_ledger").select(
        "product_name, date, sales_velocity"
    ).gte("date", cutoff).order("product_name").order("date").limit(3000).execute()

    records = res.data or []
    if not records:
        return {"status": "no_data", "message": "Sin historial de velocidad de ventas disponible."}

    # Group by product
    from collections import defaultdict
    products: dict[str, list] = defaultdict(list)
    for r in records:
        name = r.get("product_name", "")
        vel = float(r.get("sales_velocity") or 0)
        date = r.get("date", "")
        products[name].append({"date": date, "velocity": vel})

    lifecycle_results = []

    for name, data in list(products.items())[:top_n]:
        if len(data) < 10:
            continue

        sorted_data = sorted(data, key=lambda x: x["date"])
        mid = len(sorted_data) // 2

        first_half = sorted_data[:mid]
        second_half = sorted_data[mid:]

        avg_vel_old = stats.mean([d["velocity"] for d in first_half])
        avg_vel_new = stats.mean([d["velocity"] for d in second_half])
        current_vel = avg_vel_new / 7.0  # daily

        if avg_vel_old > 0:
            pct_change = round(((avg_vel_new - avg_vel_old) / avg_vel_old) * 100, 1)
        else:
            pct_change = 100.0 if avg_vel_new > 0 else 0.0

        # Classify lifecycle stage
        if current_vel < 0.1 or avg_vel_new < 0.5:
            stage = "💀 AGONÍA"
            accion = "Liquidar inmediato. Descuento agresivo 40-50%. No reponer."
            prioridad = 1
        elif pct_change <= -40:
            stage = "💀 AGONÍA"
            accion = f"Caída de {pct_change}%. Liquidar inmediato. Descuento 40%. No reponer."
            prioridad = 1
        elif pct_change <= -15:
            stage = "📉 DECLIVE"
            accion = f"Velocidad bajando {pct_change}%. Reducir próximo reorden. Bundle con Stars. No hacer stock extra."
            prioridad = 2
        elif pct_change >= 20:
            stage = "🚀 CRECIMIENTO"
            accion = f"Velocidad creciendo {pct_change}%. Asegurar stock extra (60d cobertura). Priorizar en reorden."
            prioridad = 4
        else:
            stage = "🏆 MADUREZ"
            accion = "Producto estable. Mantener reorden estándar. Optimizar margen."
            prioridad = 3

        lifecycle_results.append({
            "producto": name,
            "estadio": stage,
            "velocidad_promedio_7d": round(avg_vel_new, 1),
            "velocidad_diaria": round(current_vel, 2),
            "cambio_velocidad_pct": pct_change,
            "accion": accion,
            "prioridad_gestion": prioridad,
        })

    lifecycle_results.sort(key=lambda x: x["prioridad_gestion"])

    en_agonia = [p for p in lifecycle_results if "AGONÍA" in p["estadio"]]
    en_crecimiento = [p for p in lifecycle_results if "CRECIMIENTO" in p["estadio"]]

    return {
        "status": "success",
        "periodo_analizado_dias": days,
        "productos_analizados": len(lifecycle_results),
        "resumen": {
            "en_agonia": len(en_agonia),
            "en_declive": len([p for p in lifecycle_results if "DECLIVE" in p["estadio"]]),
            "en_madurez": len([p for p in lifecycle_results if "MADUREZ" in p["estadio"]]),
            "en_crecimiento": len(en_crecimiento),
        },
        "productos_en_agonia": en_agonia[:10],
        "productos_en_crecimiento": en_crecimiento[:10],
        "todos": lifecycle_results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. SCORE DE RIESGO DE QUIEBRE COMPUESTO (Multi-Factor Stockout Risk)
# Combina: stock coverage + basket_anchor + BCG_star + supplier_delay
# ─────────────────────────────────────────────────────────────────────────────
async def calculate_stockout_risk_scores(top_n: int = 30) -> dict:
    """
    Calcula un Score de Riesgo de Quiebre compuesto (0-100) por producto,
    cruzando cuatro dimensiones de riesgo:

    - Stock Coverage Risk (40pts): Días de cobertura restante vs Lead Time
    - Basket Anchor Risk (30pts): Si es producto ancla del carrito (genera ventas)
    - Revenue Criticality (20pts): Si está en cuadrante Star o Cash Cow (BCG)
    - Supplier Reliability Risk (10pts): Si el proveedor tiene historial de demoras

    Score 80-100 → CRÍTICO: Reordenar HOY con capital disponible primero.
    Score 60-79  → ALTO: Reordenar esta semana.
    Score 40-59  → MEDIO: Planificar reorden próxima semana.
    Score < 40   → BAJO: Monitorear normalmente.

    Args:
        top_n: Número de productos a incluir en el análisis.

    Returns:
        dict con ranking de riesgo y recomendaciones de acción prioritaria.
    """
    client = await get_supabase()

    # Fetch all products to build id (UUID) <-> sku map
    prod_res = await client.table("products").select("id, sku").execute()
    id_to_sku = {p["id"]: p["sku"] for p in (prod_res.data or []) if p.get("id") and p.get("sku")}

    # 1. Inventario actual
    target_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")

    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity"
    ).eq("date", target_date).gt("sales_velocity", 0).order("stock_end_of_day").limit(top_n * 2).execute()

    inventory = inv_res.data or []
    if not inventory:
        return {"status": "no_data", "message": "Sin datos de inventario disponibles."}

    # 2. Anchor products from market basket (simplified: top frequency products by SKU)
    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    cutoff_30d = (datetime.now() - timedelta(days=30)).isoformat()
    orders_res = await client.table("wc_orders_cache").select(
        "line_items"
    ).gte("date_created", cutoff_30d).in_("status", ACTIVE_STATUSES).limit(200).execute()

    from collections import Counter
    product_order_freq: Counter = Counter()
    total_basket_orders = 0

    for order in (orders_res.data or []):
        items = order.get("line_items") or []
        if items:
            total_basket_orders += 1
            for item in items:
                sku = item.get("sku")
                if sku:
                    product_order_freq[sku] += 1

    anchor_threshold = max(3, total_basket_orders * 0.08)
    anchor_skus = {sku for sku, freq in product_order_freq.items() if freq >= anchor_threshold}

    # 3. Supplier delay data (simplified from purchase_order_drafts)
    po_res = await client.table("purchase_order_drafts").select(
        "items, created_at, confirmed_at, status"
    ).in_("status", ["in_transit", "delivered"]).limit(100).execute()

    delayed_providers = set()
    for po in (po_res.data or []):
        created_str = po.get("created_at", "")
        confirmed_str = po.get("confirmed_at", "")
        if not created_str or not confirmed_str:
            continue
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")).replace(tzinfo=None)
            confirmed_dt = datetime.fromisoformat(confirmed_str.replace("Z", "+00:00")).replace(tzinfo=None)
            if (confirmed_dt - created_dt).days > 3:
                for item in (po.get("items") or []):
                    prov = item.get("proveedor", "")
                    if prov and prov not in ("StrategicAdvisor", "POR IDENTIFICAR"):
                        delayed_providers.add(prov.upper())
        except Exception:
            continue

    # 4. Supplier catalog for delay lookup
    cat_res = await client.table("supplier_catalog").select("product_id, proveedor").execute()
    pid_to_prov = {str(r["product_id"]): (r.get("proveedor") or "").upper() for r in (cat_res.data or []) if r.get("product_id")}

    # 5. Calculate composite risk score
    risk_scores = []
    LEAD_TIME_DAYS = 10  # estimated standard lead time

    for item in inventory:
        pid = item.get("product_id")
        name = item.get("product_name", "")
        stock = int(item.get("stock_end_of_day") or 0)
        velocity_7d = float(item.get("sales_velocity") or 0)
        daily_velocity = velocity_7d / 7.0 if velocity_7d > 0 else 0

        # A. Stock Coverage Score (0-40 pts)
        if daily_velocity > 0:
            days_coverage = stock / daily_velocity
        else:
            days_coverage = 999

        if days_coverage <= 3:
            coverage_score = 40
        elif days_coverage <= 7:
            coverage_score = 30
        elif days_coverage <= LEAD_TIME_DAYS:
            coverage_score = 20
        elif days_coverage <= LEAD_TIME_DAYS + 7:
            coverage_score = 10
        else:
            coverage_score = 0

        # B. Basket Anchor Score (0-30 pts)
        sku = id_to_sku.get(pid)
        is_anchor = sku in anchor_skus if sku else False
        anchor_score = 30 if is_anchor else 0

        # C. Revenue Criticality Score — proxy: high velocity (0-20 pts)
        freq_in_orders = product_order_freq.get(sku, 0) if sku else 0
        if total_basket_orders > 0:
            pct_orders = freq_in_orders / total_basket_orders
        else:
            pct_orders = 0
        revenue_score = min(20, int(pct_orders * 100))

        # D. Supplier Reliability Score (0-10 pts)
        provider = pid_to_prov.get(str(pid), "")
        supplier_score = 10 if provider and any(d in provider for d in delayed_providers) else 0

        total_score = coverage_score + anchor_score + revenue_score + supplier_score

        if total_score >= 80:
            nivel = "🔴 CRÍTICO"
            accion = f"Reordenar HOY. Cobertura: {round(days_coverage, 1)} días. {'Es producto ancla de carrito.' if is_anchor else ''}"
        elif total_score >= 60:
            nivel = "🟠 ALTO"
            accion = f"Reordenar esta semana. Cobertura: {round(days_coverage, 1)} días."
        elif total_score >= 40:
            nivel = "🟡 MEDIO"
            accion = f"Planificar reorden próxima semana. Cobertura: {round(days_coverage, 1)} días."
        else:
            nivel = "🟢 BAJO"
            accion = "Monitorear. Sin acción urgente."

        risk_scores.append({
            "producto": name,
            "risk_score": total_score,
            "nivel_riesgo": nivel,
            "dias_cobertura": round(days_coverage, 1) if days_coverage < 999 else "N/A (sin ventas)",
            "es_anchor_product": is_anchor,
            "proveedor_demorado": supplier_score > 0,
            "desglose_score": {
                "cobertura_stock_40pts": coverage_score,
                "anchor_basket_30pts": anchor_score,
                "criticidad_revenue_20pts": revenue_score,
                "riesgo_proveedor_10pts": supplier_score,
            },
            "accion_prioritaria": accion,
        })

    risk_scores.sort(key=lambda x: x["risk_score"], reverse=True)

    criticos = [r for r in risk_scores if "CRÍTICO" in r["nivel_riesgo"]]
    altos = [r for r in risk_scores if "ALTO" in r["nivel_riesgo"]]

    return {
        "status": "success",
        "analysis_date": target_date,
        "productos_evaluados": len(risk_scores),
        "resumen": {
            "criticos": len(criticos),
            "alto_riesgo": len(altos),
            "medio_riesgo": len([r for r in risk_scores if "MEDIO" in r["nivel_riesgo"]]),
            "bajo_riesgo": len([r for r in risk_scores if "BAJO" in r["nivel_riesgo"]]),
        },
        "top_riesgo_critico": criticos[:10],
        "top_riesgo_alto": altos[:10],
        "ranking_completo": risk_scores[:top_n],
        "recomendacion": (
            f"🚨 {len(criticos)} productos en riesgo CRÍTICO de quiebre. "
            f"Priorizar reorden inmediato con el capital disponible."
            if criticos else
            "✅ Ningún producto en riesgo crítico inmediato."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. OPTIMIZADOR DE CAPITAL DISPONIBLE PARA REABASTECIMIENTO
# Responde: dado $X de capital, ¿cuáles productos recomprar y cuánto?
# Algoritmo: Greedy knapsack por ratio (risk_score × margen) / costo_reorden
# ─────────────────────────────────────────────────────────────────────────────
async def optimize_restock_with_budget(
    available_capital: float = 20000.0,
    coverage_target_days: int = 30,
) -> dict:
    """
    Dado un presupuesto disponible ($available_capital, por defecto $20,000 USD mensuales),
    determina cuáles productos reponer primero y en qué cantidad, maximizando la reducción
    de riesgo de quiebre y la rentabilidad por dólar invertido.

    Cálculos reales utilizados:
    - Costo unitario COGS real: extraído de wc_orders_cache._alg_wc_cog_item_cost
    - Cantidad a reponer: daily_velocity × coverage_target_days - stock_actual
    - Costo total de reorden: cog_unitario × qty_reorden
    - Score de prioridad: (risk_score × margen_pct) / costo_reorden
      → Maximiza reducción de riesgo por dólar invertido

    Algoritmo:
    1. Calcula costo real de reponer cada producto al nivel objetivo
    2. Filtra productos donde costo_reorden > 0 (requieren acción)
    3. Ordena por (risk × rentabilidad) / costo → mejor ROI de capital primero
    4. Asigna capital secuencialmente hasta agotar el presupuesto
    5. Lista productos EXCLUIDOS por falta de capital con costo diferido

    Args:
    available_capital: Presupuesto disponible en dólares (USD) (por defecto 20000.0, correspondiente al gasto mensual aproximado).
    coverage_target_days: Días de cobertura objetivo al reponer (default 30).

    Returns:
        dict con plan de compras priorizado, costo total, capital restante
        y lista de productos diferidos por falta de presupuesto.
    """
    client = await get_supabase()

    # Fetch all products to build id (UUID) <-> sku map and id <-> price map
    prod_res = await client.table("products").select("id, sku, price").execute()
    id_to_sku = {p["id"]: p["sku"] for p in (prod_res.data or []) if p.get("id") and p.get("sku")}
    id_to_price = {p["id"]: p.get("price") for p in (prod_res.data or []) if p.get("id")}

    # ── 1. Inventario actual ──────────────────────────────────────────────────
    target_date = await latest_ledger_date(client) or datetime.now().strftime("%Y-%m-%d")

    inv_res = await client.table("daily_inventory_ledger").select(
        "product_id, product_name, stock_end_of_day, sales_velocity, price"
    ).eq("date", target_date).gt("sales_velocity", 0).limit(200).execute()

    inventory = inv_res.data or []
    if not inventory:
        return {"status": "no_data", "message": "Sin datos de inventario disponibles."}

    # ── 2. COGS real por producto (promedio últimas órdenes) ──────────────────
    ACTIVE_STATUSES = ["completed", "processing", "driver-assigned", "pedido-en-camino", "armando-pedido"]
    cutoff_60d = (datetime.now() - timedelta(days=60)).isoformat()
    orders_res = await client.table("wc_orders_cache").select(
        "line_items"
    ).gte("date_created", cutoff_60d).in_("status", ACTIVE_STATUSES).limit(500).execute()

    # Build: sku → {avg_cog, avg_price, total_units}
    cog_map: dict[str, dict] = {}
    for order in (orders_res.data or []):
        for item in (order.get("line_items") or []):
            sku = item.get("sku")
            price = float(item.get("price") or 0)
            qty = int(item.get("quantity") or 0)
            if not sku or qty == 0:
                continue
            cog_val = None
            for meta in (item.get("meta_data") or []):
                if meta.get("key") == "_alg_wc_cog_item_cost":
                    try:
                        cog_val = float(meta.get("value") or 0)
                    except (ValueError, TypeError):
                        pass
                    break
            if cog_val is None:
                continue
            if sku not in cog_map:
                cog_map[sku] = {"total_cog": 0.0, "total_price": 0.0, "units": 0, "name": item.get("name", "")}
            cog_map[sku]["total_cog"] += cog_val * qty
            cog_map[sku]["total_price"] += price * qty
            cog_map[sku]["units"] += qty

    # ── 3. Anchor/frequency data for risk weighting by SKU ────────────────────
    from collections import Counter
    product_order_freq: Counter = Counter()
    total_orders_basket = 0
    for order in (orders_res.data or []):
        items = order.get("line_items") or []
        if items:
            total_orders_basket += 1
            for item in items:
                sku = item.get("sku")
                if sku:
                    product_order_freq[sku] += 1

    anchor_threshold = max(3, total_orders_basket * 0.08)
    anchor_skus = {sku for sku, freq in product_order_freq.items() if freq >= anchor_threshold}

    # ── 4. Build candidate list with real cost and risk score ────────────────
    LEAD_TIME_DAYS = 10
    candidates = []

    for item in inventory:
        pid = item.get("product_id")
        name = item.get("product_name", "")
        stock = int(item.get("stock_end_of_day") or 0)
        velocity_7d = float(item.get("sales_velocity") or 0)
        daily_vel = velocity_7d / 7.0 if velocity_7d > 0 else 0

        if daily_vel <= 0:
            continue

        days_coverage = stock / daily_vel

        # Qty needed to reach coverage_target_days
        target_stock = int(daily_vel * coverage_target_days)
        qty_needed = max(0, target_stock - stock)
        if qty_needed == 0:
            continue  # Already has enough stock

        sku = id_to_sku.get(pid)

        # COGS real/estimated
        cost_data = cog_map.get(sku) if sku else None
        if cost_data and cost_data["units"] > 0:
            avg_cog = cost_data["total_cog"] / cost_data["units"]
            avg_price = cost_data["total_price"] / cost_data["units"]
            margin_pct = ((avg_price - avg_cog) / avg_price * 100) if avg_price > 0 else 30.0
            has_real_cog = True
        else:
            # Fallback: estimate COG at 60% of ledger/product price
            list_price = float(item.get("price") or id_to_price.get(pid) or 0)
            avg_price = list_price
            avg_cog = list_price * 0.60
            margin_pct = 40.0
            has_real_cog = False

        if avg_cog > 0:
            restock_cost = round(avg_cog * qty_needed, 2)
        else:
            restock_cost = None

        # Risk score (simplified inline calculation)
        if days_coverage <= 3:
            coverage_score = 40
        elif days_coverage <= 7:
            coverage_score = 30
        elif days_coverage <= LEAD_TIME_DAYS:
            coverage_score = 20
        elif days_coverage <= LEAD_TIME_DAYS + 7:
            coverage_score = 10
        else:
            coverage_score = 0

        freq_pct = (product_order_freq.get(sku, 0) / total_orders_basket) if total_orders_basket > 0 and sku else 0
        anchor_score = 30 if sku in anchor_skus else 0
        revenue_score = min(20, int(freq_pct * 100))
        risk_score = coverage_score + anchor_score + revenue_score

        # Priority ratio: risk × profitability / cost (higher = better ROI per $ spent)
        if restock_cost and restock_cost > 0:
            priority_ratio = round((risk_score * (margin_pct / 100)) / restock_cost, 4)
        else:
            priority_ratio = 0.0

        candidates.append({
            "product_id": pid,
            "producto": name,
            "stock_actual": stock,
            "dias_cobertura_actual": round(days_coverage, 1),
            "dias_cobertura_objetivo": coverage_target_days,
            "qty_a_reponer": qty_needed,
            "cog_unitario_real": round(avg_cog, 3),
            "precio_venta_promedio": round(avg_price, 2),
            "margen_pct": round(margin_pct, 1),
            "costo_reorden_total": restock_cost if restock_cost is not None else "calculable solo con COGS real",
            "risk_score": risk_score,
            "es_anchor_product": sku in anchor_skus if sku else False,
            "priority_ratio": priority_ratio,
            "tiene_cog_real": has_real_cog,
        })

    # ── 5. Sort by priority_ratio (best ROI per dollar first) ────────────────
    candidates_with_cost = [c for c in candidates if isinstance(c["costo_reorden_total"], (int, float)) and c["costo_reorden_total"] > 0]
    candidates_no_cost = [c for c in candidates if not isinstance(c["costo_reorden_total"], (int, float))]

    candidates_with_cost.sort(key=lambda x: x["priority_ratio"], reverse=True)

    # ── 6. Greedy knapsack allocation ─────────────────────────────────────────
    budget_remaining = available_capital
    purchase_plan = []
    deferred = []
    total_spent = 0.0

    for c in candidates_with_cost:
        cost = c["costo_reorden_total"]
        if budget_remaining >= cost:
            purchase_plan.append({
                **c,
                "decision": "✅ COMPRAR",
                "costo_asignado": cost,
            })
            budget_remaining -= cost
            total_spent += cost
        else:
            # Can we buy a partial quantity?
            partial_qty = int(budget_remaining / c["cog_unitario_real"]) if isinstance(c["cog_unitario_real"], (int, float)) and c["cog_unitario_real"] > 0 else 0
            if partial_qty >= 5:  # Only worth it if at least 5 units
                partial_cost = round(partial_qty * c["cog_unitario_real"], 2)
                purchase_plan.append({
                    **c,
                    "qty_a_reponer": partial_qty,
                    "costo_reorden_total": partial_cost,
                    "decision": "⚡ COMPRAR PARCIAL (capital limitado)",
                    "costo_asignado": partial_cost,
                    "qty_diferida": c["qty_a_reponer"] - partial_qty,
                })
                budget_remaining -= partial_cost
                total_spent += partial_cost
            else:
                deferred.append({
                    **c,
                    "decision": "⏸️ DIFERIDO (capital insuficiente)",
                    "capital_faltante": round(cost - budget_remaining, 2),
                })

    # Products without real COG data
    for c in candidates_no_cost:
        deferred.append({
            **c,
            "decision": "❓ SIN COSTO REAL — requiere cotización manual con proveedor",
        })

    return {
        "status": "success",
        "analysis_date": target_date,
        "parametros": {
            "capital_disponible": available_capital,
            "cobertura_objetivo_dias": coverage_target_days,
        },
        "resumen_financiero": {
            "capital_disponible": round(available_capital, 2),
            "capital_a_gastar": round(total_spent, 2),
            "capital_restante": round(budget_remaining, 2),
            "utilizacion_presupuesto_pct": round((total_spent / available_capital) * 100, 1) if available_capital > 0 else 0,
        },
        "plan_de_compras": purchase_plan,
        "productos_diferidos": deferred,
        "resumen": {
            "productos_a_comprar": len(purchase_plan),
            "productos_diferidos": len(deferred),
            "skus_sin_cog_real": len(candidates_no_cost),
        },
        "nota": (
            f"Plan optimizado por máximo ROI por dólar invertido. "
            f"Se priorizan productos con mayor riesgo de quiebre y mayor margen. "
            f"Capital restante: ${round(budget_remaining, 2)}."
        ),
    }
