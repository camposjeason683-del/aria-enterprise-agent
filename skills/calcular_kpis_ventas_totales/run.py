import asyncio
import json
import sys
from src.tools.dynamic_execution import execute_safe_read_query

async def main():
    try:
        # Leer parámetros desde stdin
        try:
            input_data = json.loads(sys.stdin.read())
        except Exception:
            input_data = {}

        start_date = input_data.get("start_date")
        end_date = input_data.get("end_date")
        exclude_statuses = input_data.get("exclude_statuses", ["cancelled", "failed", "trash", "draft"])

        # Construcción dinámica de la consulta SQL
        query = """
            SELECT 
                COALESCE(SUM(total::numeric), 0) as total_ventas, 
                COUNT(*) as total_pedidos 
            FROM wc_orders_cache 
            WHERE 1=1
        """
        params = []

        if exclude_statuses:
            placeholders = ", ".join(f"${i+1}" for i in range(len(exclude_statuses)))
            query += f" AND status NOT IN ({placeholders})"
            params.extend(exclude_statuses)

        if start_date:
            params.append(start_date)
            query += f" AND date_created_gmt >= ${len(params)}::timestamp"

        if end_date:
            params.append(end_date)
            query += f" AND date_created_gmt <= ${len(params)}::timestamp"

        # Ejecución segura de la consulta
        result = await execute_safe_read_query(query, params)

        if result and len(result) > 0:
            row = result[0]
            total_ventas = float(row.get("total_ventas", 0))
            total_pedidos = int(row.get("total_pedidos", 0))
            ticket_promedio = total_ventas / total_pedidos if total_pedidos > 0 else 0.0
        else:
            total_ventas = 0.0
            total_pedidos = 0
            ticket_promedio = 0.0

        output = {
            "status": "success",
            "data": {
                "total_ventas": total_ventas,
                "total_pedidos": total_pedidos,
                "ticket_promedio": ticket_promedio,
                "filtros_aplicados": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "exclude_statuses": exclude_statuses
                }
            }
        }
        print(json.dumps(output))

    except Exception as e:
        error_output = {
            "status": "error",
            "message": str(e)
        }
        print(json.dumps(error_output), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())