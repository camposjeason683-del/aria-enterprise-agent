# Memoria de Trabajo del Sistema (MEMORY.md)

## Reglas Críticas del Esquema de Datos
*   **Tabla de Órdenes**: `wc_orders_cache`.
*   **Columna del Cliente**: Usar siempre `customer_name` (NO existe `customer_id`).
*   **Columna de Fechas**: Usar siempre `date_created` (NO usar `created_at` ni `transaction_date`).
*   **Filtro de Estados de Órdenes**: Filtrar siempre estados inválidos: `status NOT IN ('cancelled', 'failed', 'trash', 'draft')`.

## Lecciones Aprendidas de Errores Pasados
*   **Cálculo de Churn**: El Churn mensual debe calcularse mediante análisis de cohortes (CTE/JOIN de clientes comunes), nunca restando los totales globales de clientes.
*   **Sandbox de Python**: La ejecución de scripts de Python en el sandbox no tiene acceso directo al estado global, pero sí puede importar `src.tools.dynamic_execution` para ejecutar SQL de forma segura.
