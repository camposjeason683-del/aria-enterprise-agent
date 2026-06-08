#!/usr/bin/env bash
# Post-deploy smoke for ARIA-OS — confirms the deployed backend is healthy and the
# scheduler guard works. READ-ONLY (safe against production).
#
# Usage:
#   ./scripts/verify_deploy.sh https://aria-os-backend.onrender.com <cron_secret>
#   BACKEND_URL=https://... CRON_SECRET=... ./scripts/verify_deploy.sh
set -uo pipefail

B="${1:-${BACKEND_URL:-}}"
SECRET="${2:-${CRON_SECRET:-}}"
[ -z "$B" ] && { echo "Uso: $0 <BACKEND_URL> [CRON_SECRET]  (o via env BACKEND_URL/CRON_SECRET)"; exit 2; }
B="${B%/}"
pass=0; fail=0

code() { curl -s -o /dev/null -w "%{http_code}" --max-time 30 "$@"; }
ok()   { echo "  ✅ $1 ($2)"; pass=$((pass + 1)); }
bad()  { echo "  ❌ $1 — esperado $2, fue $3"; fail=$((fail + 1)); }
eq()   { [ "$2" = "$3" ] && ok "$1" "$3" || bad "$1" "$2" "$3"; }

echo "ARIA-OS — verificación de deploy · $B"
echo "── salud ──"
eq "GET /health = 200"          200 "$(code "$B/health")"
eq "GET /api/v1/health = 200"   200 "$(code "$B/api/v1/health")"

echo "── scheduler (guard) ──"
eq "cron sin secreto = 403"     403 "$(code -X POST "$B/api/v1/cron/compile-ledger")"
eq "cron secreto malo = 403"    403 "$(code -X POST "$B/api/v1/cron/compile-ledger" -H 'X-Cron-Secret: nope')"
if [ -n "$SECRET" ]; then
  eq "cron con secreto = 200"   200 "$(code -X POST "$B/api/v1/cron/morning-brief" -H "X-Cron-Secret: $SECRET")"
else
  echo "  ⚠️  sin CRON_SECRET → salteo el happy-path (pasalo como 2do argumento)"
fi

echo "── auth gate ──"
c=$(code -X POST "$B/api/v1/chat")
if [ "$c" = 401 ] || [ "$c" = 403 ]; then
  ok "POST /api/v1/chat sin token rechazado" "$c"
else
  bad "chat sin token rechazado" "401/403" "$c"
fi

echo ""
echo "Resultado: $pass OK · $fail fallo(s)"
if [ "$fail" -eq 0 ]; then echo "🔒 DEPLOY VERIFICADO"; exit 0; else echo "⚠️  Revisá los ❌"; exit 1; fi
