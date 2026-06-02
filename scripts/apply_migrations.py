"""Apply migrations/*.sql to the linked InsForge project via the REST Migrations
API. Targets INSFORGE_URL explicitly (never the MCP/Cinco backend).

Usage: python3 scripts/apply_migrations.py [glob]   # default: migrations/0*.sql
"""
import glob
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

URL = os.environ["INSFORGE_URL"].rstrip("/")
KEY = os.environ["INSFORGE_API_KEY"]
pattern = sys.argv[1] if len(sys.argv) > 1 else "migrations/0*.sql"

print(f"Target: {URL}")
for path in sorted(glob.glob(pattern)):
    stem = os.path.basename(path)[:-4]          # 0001_tenancy_core
    version, _, name = stem.partition("_")
    name = name.replace("_", "-")
    sql = open(path, encoding="utf-8").read()
    resp = httpx.post(
        f"{URL}/api/database/migrations",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={"version": version, "name": name, "sql": sql},
        timeout=120,
    )
    ok = resp.status_code < 300
    print(f"{'✓' if ok else '✗'} {os.path.basename(path)} → {resp.status_code} {resp.text[:240]}")
    if not ok:
        sys.exit(1)
print("All migrations applied.")
