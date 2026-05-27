---
description: "Realiza un an\xE1lisis avanzado de retenci\xF3n de clientes para un\
  \ per\xEDodo de tiempo (por defecto 90 d\xEDas). Clasifica a los clientes en nuevos,\
  \ recurrentes, reactivados y perdidos (churn), calcula la tasa de churn, el ticket\
  \ promedio y la distribuci\xF3n de frecuencia de compra."
name: analisis_cohortes_retencion_clientes
parameters:
  properties:
    dias_analisis:
      description: "N\xFAmero de d\xEDas para definir el per\xEDodo de an\xE1lisis\
        \ actual (por defecto 90)."
      type: integer
    excluir_estados:
      description: "Lista de estados de pedido a excluir del an\xE1lisis (por defecto:\
        \ ['cancelled', 'failed', 'trash', 'draft'])."
      items:
        type: string
      type: array
    fecha_fin:
      description: "Fecha de fin del an\xE1lisis en formato 'YYYY-MM-DD'. Si se omite,\
        \ se usar\xE1 la fecha del \xFAltimo pedido registrado."
      type: string
  type: object
---
# Skill: analisis_cohortes_retencion_clientes

# Análisis de Cohortes y Retención de Clientes

Este skill permite realizar un análisis profundo del comportamiento de compra de los clientes en un período de tiempo determinado (por defecto, los últimos 90 días), comparándolo con el período inmediatamente anterior para calcular métricas de retención, reactivación y fuga (churn).

### Definiciones de Cohortes:
- **Nuevos**: Clientes que realizaron su primera compra histórica dentro del período de análisis.
- **Retenidos (Recurrentes)**: Clientes que compraron en el período de análisis y también habían comprado en el período inmediatamente anterior.
- **Reactivados**: Clientes que compraron en el período de análisis, no compraron en el período inmediatamente anterior, pero sí tenían compras históricas más antiguas.
- **Perdidos (Churn)**: Clientes que compraron en el período anterior pero no realizaron ninguna compra en el período de análisis actual.
- **Tasa de Churn (Fuga)**: Se calcula como `Clientes Perdidos / Clientes Activos en el Periodo Anterior * 100`.

### Advertencias de Uso:
- Asegúrate de que la tabla `wc_orders_cache` contenga datos actualizados.
- Por defecto, se excluyen los estados de pedido fallidos o cancelados (`cancelled`, `failed`, `trash`, `draft`) para evitar sesgar las métricas de ingresos y comportamiento real.
