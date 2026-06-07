# ARIA-OS — Guía de deploy (la última milla)

Todo el código está construido, testeado y mergeado. Lo que falta es **conectar tus
cuentas externas y desplegar**. Esta guía es el paso a paso.

```
   ┌── Vercel ────────┐      ┌── Render / Cloud Run ──┐      ┌── InsForge ──┐
   │ frontend (Next)  │ ───► │ backend (FastAPI+ADK)  │ ───► │ Postgres+RLS │
   └──────────────────┘      └────────────┬───────────┘      │ Auth         │
                                          │                   └──────────────┘
   ┌── GitHub Actions ┐      hits cron    │  llama
   │ scheduler (cron) │ ───────────────►  │  ───►  Gemini · WooCommerce · Stripe · Telegram
   └──────────────────┘                   └────────────────────────────────────────────────
```

## 0. Prerequisitos
- **GitHub** (el repo ya está) · **Render** (o Cloud Run) para el backend · **Vercel** para el frontend.
- InsForge ya está provisto (proyecto aria-os, migraciones 0001–0014 aplicadas).
- Opcionales (se conectan después, sin bloquear el lanzamiento): Stripe, un bot de Telegram, Sentry.

---

## 1. Backend → Render (recomendado; lo más simple)
1. **Rotá los secretos primero** (higiene): generá nuevos `GEMINI_API_KEY` (AI Studio) e
   `INSFORGE_API_KEY` (InsForge Studio → API Keys → Secret). **No rotes `ARIA_ENCRYPTION_KEY`**
   salvo que re-encriptes `tenant_integrations` (rompe la desencriptación de creds WC).
2. Render → **New → Blueprint** → conectá este repo. Lee `render.yaml` automáticamente.
3. Cargá los env vars marcados `sync:false` en el dashboard (ver la tabla del §4).
4. Deploy. Render usa el `Dockerfile` (que ahora bindea a `$PORT`). Health check: `/health`.
5. Anotá la URL pública, ej. `https://aria-os-backend.onrender.com`.

> Alternativa Cloud Run: `cloud-run-service.yaml` ya tiene la forma correcta — reemplazá
> `PROJECT_ID`, creá los secretos en Secret Manager, `gcloud run services replace cloud-run-service.yaml`.

## 2. Frontend → Vercel
1. Vercel → **New Project** → importá el repo · **Root Directory = `frontend`** (importante).
   Detecta Next.js (hay `frontend/vercel.json`).
2. Env vars (Production):
   - `NEXT_PUBLIC_INSFORGE_URL` = la URL de InsForge.
   - `NEXT_PUBLIC_INSFORGE_ANON_KEY` = la publishable key (no la secret).
   - `NEXT_PUBLIC_BACKEND_URL` = **la URL del backend del §1**.
   - `AGENT_URL` = la misma URL del backend.
3. Deploy. Anotá el dominio (ej. `https://app.tudominio.com`).
4. **Volvé al backend** y poné ese dominio en `ALLOWED_ORIGINS` (CORS) → redeploy del backend.

## 3. Activar el scheduler (los cron brains, 24/7)
El workflow `.github/workflows/cron.yml` ya está. Para activarlo:
1. GitHub → repo → Settings → **Secrets and variables → Actions**.
2. **Variable** `BACKEND_URL` = la URL del backend del §1.
3. **Secret** `CRON_SECRET` = **el mismo valor** que pusiste en el backend.
4. Listo: corre `compile-ledger → proactive-sweep → insight-sweep` cada hora y
   `morning-brief` diario. (Probado en vivo: sin secreto → 403, con secreto → 200.)

## 4. Checklist de env vars (qué va dónde)

| Variable | Backend (Render) | Frontend (Vercel) | GitHub | Qué es |
|---|:--:|:--:|:--:|---|
| `INSFORGE_URL` | ✅ | — | — | endpoint InsForge |
| `INSFORGE_API_KEY` | ✅ secret | — | — | InsForge **secret** key |
| `INSFORGE_JWT_SECRET` | ✅ secret | — | — | verifica JWTs |
| `ARIA_ENCRYPTION_KEY` | ✅ secret | — | — | cifra creds WC (no rotar a la ligera) |
| `GEMINI_API_KEY` | ✅ secret | — | — | el LLM |
| `CRON_SECRET` | ✅ secret | — | ✅ secret | mismo valor en ambos |
| `WEBHOOK_SECRET` | ✅ secret | — | — | firma de webhooks |
| `ALLOWED_ORIGINS` | ✅ | — | — | el dominio del frontend |
| `NEXT_PUBLIC_INSFORGE_URL` | — | ✅ | — | InsForge (browser) |
| `NEXT_PUBLIC_INSFORGE_ANON_KEY` | — | ✅ | — | publishable key |
| `NEXT_PUBLIC_BACKEND_URL` / `AGENT_URL` | — | ✅ | — | URL del backend |
| `BACKEND_URL` | — | — | ✅ var | URL del backend (scheduler) |

Opcionales (conectar después): `SENTRY_DSN` (backend), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
(alertas), Stripe keys vía `insforge-cli` (cobro).

## 5. Conectar la data del cliente
- **CSV/Sheets** — cero config previa. El cliente sube su CSV en `/onboarding` (o conecta un
  Google Sheet público). Es el camino más corto a primer valor.
- **WooCommerce** — el cliente pega su URL + consumer key/secret en `/onboarding`; se guardan
  encriptadas. El scheduler sincroniza órdenes → ledger automáticamente.
- **Stripe** (para cobrar) — configurá las keys con `insforge-cli`; apuntá el webhook de Stripe a
  `POST {backend}/api/v1/webhooks/stripe`. El enforce de suscripción ya funciona.
- **Telegram** (alertas) — creá un bot, seteá `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

## 6. Verificación post-deploy
1. `curl https://<backend>/health` → `{"status":"ok"}`.
2. Andá al frontend → **/signup** → creá una empresa → caés en **/onboarding**.
3. Subí un CSV de ventas (columnas: fecha, producto, cantidad, precio) → ves el primer
   forecast en **/dashboard**.
4. Probá **/whatif** (mové el precio) y **/rules**.
5. (Si activaste el scheduler) esperá un tick o disparalo a mano:
   `curl -X POST https://<backend>/api/v1/cron/compile-ledger -H "X-Cron-Secret: <secret>"` → 200.

## 7. Rollback
- Backend/frontend: Render y Vercel guardan deploys anteriores → "Rollback" en el dashboard.
- Migraciones: cada `migrations/00XX_*.sql` tiene su SQL de reverse comentado.
- Código: cada feature es un PR mergeado → `git revert <merge>`.

## Notas
- **Puertos**: local = `:8000` (uvicorn) y el `frontend/.env.local` ya apunta ahí; en prod el
  contenedor usa `$PORT` (Render) o 8080 (Cloud Run) detrás de la URL pública.
- **Demo data**: el tenant `demo` tiene un ledger curado (arquetipos). **No corras
  `compile-ledger` sobre el demo** — recomputaría su ledger desde las órdenes random del seed.
  Para producción real esto no aplica (cada tenant compila desde SU data).
- **Rotación de secretos**: documentá cuándo rotás `CRON_SECRET`/`WEBHOOK_SECRET` (hay que
  actualizarlos en backend + GitHub a la vez).
