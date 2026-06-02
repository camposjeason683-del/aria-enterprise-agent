# Spec — `data-science/forecasting`

**Story:** Como analista, le pido a ARIA una proyección de ventas/demanda y obtengo
un pronóstico con intervalos de confianza, calculado server-side con modelos
estadísticos — sin BigQuery/Vertex (paridad funcional con BQML ARIMA_PLUS), bajo
RLS y a costo plano.

**Patrón:** espeja `calc_sales_forecast` (`src/tools/calculations.py`). El tool
`forecast_sales` consulta la serie tenant-scopeada vía `get_supabase()` y delega la
matemática a `_fit_forecast` (función pura, testeable sin DB).

## Invariants

- **I1 (RLS):** la data entra ya acotada al tenant (cliente con JWT del request);
  el tool nunca recibe la serie como parámetro del LLM ni cruza tenants.
- **I2 (intervalos siempre):** todo punto proyectado trae `lo ≤ value ≤ hi`.
- **I3 (no-negatividad):** ventas proyectadas y `lo` nunca son negativas.
- **I4 (degradación graceful):** sin datos → `no_data`; historia < 4 puntos →
  `insufficient_history`; nunca crashea, nunca inventa.
- **I5 (determinismo):** `_fit_forecast` no usa RNG; mismos inputs ⇒ output deep-equal.
- **I6 (sin GCP):** pura numérica (statsmodels/numpy); sin red ni Vertex/BigQuery.

## Acceptance Criteria (Gherkin)

```gherkin
Scenario: Serie larga con estacionalidad usa un modelo real
  Given una serie diaria de >= 16 puntos con tendencia y estacionalidad semanal
  When _fit_forecast(serie, 30)
  Then status == "success"
  And se devuelven 30 puntos con lo <= value <= hi y value >= 0
  And model_used es SARIMAX o ETS (no el fallback)

Scenario: Serie corta cae al fallback lineal sin romperse
  Given una serie de 8 puntos (insuficiente para modelo estacional)
  When _fit_forecast(serie, 14)
  Then status == "success" y model_used == "linear-naive"

Scenario: Historia mínima insuficiente
  Given una serie de 3 puntos
  When _fit_forecast(serie, 10)
  Then status == "insufficient_history"

Scenario: Horizonte se clampa
  When _fit_forecast(serie_larga, 999)
  Then horizon == 90

Scenario: Determinismo
  Given la misma serie
  When se corre _fit_forecast dos veces
  Then ambos outputs son deep-equal

Scenario: Sin datos en el tenant
  Given un tenant sin filas en daily_inventory_ledger
  When forecast_sales("X", 30)
  Then status == "no_data" y no se inventan números
```

## Tests

`tests/test_forecasting.py` (vitest→pytest equivalente; núcleo puro, sin DB).
