import sys
import json
import asyncio
from datetime import datetime, timedelta

try:
    from src.tools.dynamic_execution import execute_safe_read_query
except ImportError:
    async def execute_safe_read_query(sql, *args, **kwargs):
        raise ImportError("No se pudo importar execute_safe_read_query de ARIA-OS.")

async def main():
    try:
        try:
            input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
        except Exception:
            input_data = {}

        dias_analisis = input_data.get("dias_analisis", 90)
        fecha_fin_str = input_data.get("fecha_fin", None)
        excluir_estados = input_data.get("excluir_estados", ["cancelled", "failed", "trash", "draft"])

        if not fecha_fin_str:
            query_max_date = "SELECT MAX(date_created) as max_date FROM wc_orders_cache;"
            res = await execute_safe_read_query(query_max_date)
            if res and res[0].get('max_date'):
                max_date_val = res[0]['max_date']
                if isinstance(max_date_val, str):
                    fecha_fin = datetime.fromisoformat(max_date_val.replace('Z', '+00:00'))
                else:
                    fecha_fin = max_date_val
            else:
                fecha_fin = datetime.now()
        else:
            fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d")

        fecha_inicio = fecha_fin - timedelta(days=dias_analisis)
        fecha_inicio_previo = fecha_inicio - timedelta(days=dias_analisis)

        f_fin = fecha_fin.strftime("%Y-%m-%d %H:%M:%S")
        f_ini = fecha_inicio.strftime("%Y-%m-%d %H:%M:%S")
        f_ini_prev = fecha_inicio_previo.strftime("%Y-%m-%d %H:%M:%S")

        estados_str = ", ".join([f"'{e}'" for e in excluir_estados])

        q_general = f"""
        SELECT
            COUNT(id) as total_orders,
            COALESCE(SUM(total::numeric), 0) as total_revenue,
            COALESCE(AVG(total::numeric), 0) as average_order_value,
            COUNT(DISTINCT customer_name) as unique_customers,
            CASE WHEN COUNT(DISTINCT customer_name) > 0
                 THEN COUNT(id)::numeric / COUNT(DISTINCT customer_name)
                 ELSE 0 END as avg_orders_per_customer
        FROM wc_orders_cache
        WHERE date_created >= '{f_ini}' AND date_created <= '{f_fin}'
          AND status NOT IN ({estados_str});
        """

        q_freq = f"""
        WITH customer_order_counts AS (
            SELECT customer_name, COUNT(id) as order_count
            FROM wc_orders_cache
            WHERE date_created >= '{f_ini}' AND date_created <= '{f_fin}'
              AND status NOT IN ({estados_str})
            GROUP BY customer_name
        )
        SELECT
            order_count,
            COUNT(*) as customer_count,
            ROUND((COUNT(*)::numeric / (SELECT COUNT(*) FROM customer_order_counts) * 100), 2) as percentage
        FROM customer_order_counts
        GROUP BY order_count
        ORDER BY order_count;
        """

        q_cohorts = f"""
        WITH Target_Customers AS (
            SELECT DISTINCT customer_name
            FROM wc_orders_cache
            WHERE date_created >= '{f_ini}' AND date_created <= '{f_fin}'
              AND status NOT IN ({estados_str})
        ),
        Previous_Customers AS (
            SELECT DISTINCT customer_name
            FROM wc_orders_cache
            WHERE date_created >= '{f_ini_prev}' AND date_created < '{f_ini}'
              AND status NOT IN ({estados_str})
        ),
        New_Customers AS (
            SELECT tc.customer_name
            FROM Target_Customers tc
            LEFT JOIN wc_orders_cache p ON tc.customer_name = p.customer_name
              AND p.date_created < '{f_ini}'
              AND p.status NOT IN ({estados_str})
            WHERE p.customer_name IS NULL
        ),
        Retained_Customers AS (
            SELECT tc.customer_name
            FROM Target_Customers tc
            JOIN Previous_Customers pc ON tc.customer_name = pc.customer_name
        ),
        Reactivated_Customers AS (
            SELECT tc.customer_name
            FROM Target_Customers tc
            WHERE tc.customer_name NOT IN (SELECT customer_name FROM New_Customers)
              AND tc.customer_name NOT IN (SELECT customer_name FROM Retained_Customers)
        ),
        Lost_Customers AS (
            SELECT pc.customer_name
            FROM Previous_Customers pc
            LEFT JOIN Target_Customers tc ON pc.customer_name = tc.customer_name
            WHERE tc.customer_name IS NULL
        )
        SELECT 'Nuevos' as tipo, COUNT(DISTINCT customer_name) as total FROM New_Customers
        UNION ALL
        SELECT 'Retenidos' as tipo, COUNT(DISTINCT customer_name) as total FROM Retained_Customers
        UNION ALL
        SELECT 'Reactivados' as tipo, COUNT(DISTINCT customer_name) as total FROM Reactivated_Customers
        UNION ALL
        SELECT 'Perdidos' as tipo, COUNT(DISTINCT customer_name) as total FROM Lost_Customers
        UNION ALL
        SELECT 'Activos Periodo Anterior' as tipo, COUNT(DISTINCT customer_name) as total FROM Previous_Customers;
        """

        res_general = await execute_safe_read_query(q_general)
        res_freq = await execute_safe_read_query(q_freq)
        res_cohorts = await execute_safe_read_query(q_cohorts)

        cohort_map = {row['tipo']: int(row['total']) for row in res_cohorts} if res_cohorts else {}
        nuevos = cohort_map.get('Nuevos', 0)
        retenidos = cohort_map.get('Retenidos', 0)
        reactivados = cohort_map.get('Reactivados', 0)
        perdidos = cohort_map.get('Perdidos', 0)
        activos_anterior = cohort_map.get('Activos Periodo Anterior', 0)

        churn_rate = 0.0
        if activos_anterior > 0:
            churn_rate = round((perdidos / activos_anterior) * 100, 2)

        output = {
            "periodo_analisis": {
                "inicio": f_ini,
                "fin": f_fin,
                "dias": dias_analisis
            },
            "periodo_anterior": {
                "inicio": f_ini_prev,
                "fin": f_ini
            },
            "metricas_generales": res_general[0] if res_general else {},
            "cohortes_clientes": {
                "nuevos": nuevos,
                "recurrentes_retenidos": retenidos,
                "reactivados": reactivados,
                "perdidos_churn": perdidos,
                "activos_periodo_anterior": activos_anterior,
                "churn_rate_porcentaje": churn_rate
            },
            "distribucion_frecuencia_compra": res_freq if res_freq else []
        }

        print(json.dumps(output, default=str, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())