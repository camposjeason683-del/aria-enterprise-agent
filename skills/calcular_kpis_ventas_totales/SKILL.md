---
description: "Calcula los KPIs principales de ventas (total facturado, cantidad de\
  \ pedidos y ticket promedio) a partir de la tabla de \xF3rdenes, excluyendo por\
  \ defecto estados no exitosos (cancelled, failed, trash, draft) y permitiendo filtrado\
  \ opcional por rango de fechas."
name: calcular_kpis_ventas_totales
parameters:
  properties:
    end_date:
      description: "Fecha de fin para filtrar las \xF3rdenes (formato YYYY-MM-DD o\
        \ YYYY-MM-DD HH:MM:SS)"
      type: string
    exclude_statuses:
      description: "Lista de estados de orden a excluir del c\xE1lculo. Por defecto:\
        \ ['cancelled', 'failed', 'trash', 'draft']"
      items:
        type: string
      type: array
    start_date:
      description: "Fecha de inicio para filtrar las \xF3rdenes (formato YYYY-MM-DD\
        \ o YYYY-MM-DD HH:MM:SS)"
      type: string
  required: []
  type: object
---
# Skill: calcular_kpis_ventas_totales

# Calcular KPIs de Ventas Totales

Este skill permite obtener de forma rápida y consistente los indicadores clave de rendimiento (KPIs) de ventas desde la tabla `wc_orders_cache`.

### Métricas Calculadas
- **Total Ventas**: Suma del campo `total` convertida a valor numérico.
- **Total Pedidos**: Conteo de órdenes válidas.
- **Ticket Promedio**: Total de ventas dividido por el total de pedidos.

### Consideraciones de Calidad (QC)
- **Filtro de Estados**: Por defecto, excluye automáticamente los estados `'cancelled'`, `'failed'`, `'trash'`, y `'draft'`. Esto previene la sobreestimación de ingresos por transacciones no completadas.
- **Manejo de Nulos**: Utiliza `COALESCE` para asegurar que si no hay registros, el total retornado sea `0` en lugar de `null`.
