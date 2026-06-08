# ARIA-OS — Go-Live Checklist (una página)

Marcá cada paso en orden. Detalle completo en `DEPLOY.md`.

## ☐ Antes de empezar
- [ ] Rotar `GEMINI_API_KEY` (Google AI Studio → API keys)
- [ ] Rotar `INSFORGE_API_KEY` (InsForge Studio → Settings → API Keys → Secret)
- [ ] **NO** rotar `ARIA_ENCRYPTION_KEY` (rompe las credenciales WC guardadas)

## ☐ Backend → Render
- [ ] Render → **New → Blueprint** → conectar este repo (lee `render.yaml`)
- [ ] Cargar los secrets (dashboard): `INSFORGE_URL` · `INSFORGE_API_KEY` · `INSFORGE_JWT_SECRET` · `ARIA_ENCRYPTION_KEY` · `GEMINI_API_KEY` · `CRON_SECRET` · `WEBHOOK_SECRET` · `ALLOWED_ORIGINS`
- [ ] Deploy → URL del backend: `________________________________`
- [ ] `curl <url>/health` → `{"status":"ok"}`

## ☐ Frontend → Vercel
- [ ] Vercel → **New Project** → **Root Directory = `frontend`**
- [ ] Env: `NEXT_PUBLIC_INSFORGE_URL` · `NEXT_PUBLIC_INSFORGE_ANON_KEY` · `NEXT_PUBLIC_BACKEND_URL`=⟨url backend⟩ · `AGENT_URL`=⟨url backend⟩
- [ ] Deploy → dominio del frontend: `________________________________`
- [ ] Backend: poner ese dominio en `ALLOWED_ORIGINS` → redeploy del backend

## ☐ Scheduler → GitHub Actions
- [ ] Repo → Settings → Secrets and variables → **Actions**
- [ ] **Variable** `BACKEND_URL` = ⟨url backend⟩
- [ ] **Secret** `CRON_SECRET` = (el MISMO valor que en el backend)

## ☐ Verificación (1 comando)
- [ ] `./scripts/verify_deploy.sh <url-backend> <cron-secret>` → todo ✅
- [ ] En el navegador: **/signup** → crear empresa → caés en **/onboarding**
- [ ] Subir un CSV (fecha, producto, cantidad, precio) → ves el forecast en **/dashboard**
- [ ] Probar **/whatif** (mover el precio) y **/rules**

## ☐ Opcionales (no bloquean lanzar)
- [ ] **Stripe** (cobro): keys vía `insforge-cli` + webhook → `POST <url>/api/v1/webhooks/stripe`
- [ ] **Telegram** (alertas): `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` en el backend
- [ ] **Sentry** (errores): `SENTRY_DSN` en el backend

## ☐ Pendiente tuyo (sesión paralela)
- [ ] Commitear/mergear los cambios uncommitted (`insforge.py` order-fix + `strategic.py` pedido_config)
