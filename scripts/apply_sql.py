"""Apply sql/*.sql files via the Supabase Management API."""
import os, sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PROJECT_REF   = os.environ.get("SUPABASE_PROJECT_REF") or sys.exit(
    "Missing SUPABASE_PROJECT_REF env var (e.g. the <ref> in https://<ref>.supabase.co)"
)
ACCESS_TOKEN  = os.environ.get("SUPABASE_ACCESS_TOKEN") or sys.exit(
    "Missing SUPABASE_ACCESS_TOKEN env var — create one at "
    "https://supabase.com/dashboard/account/tokens"
)
MGMT_URL      = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

SQL_DIR = Path(__file__).parent.parent / "sql"

def run_sql(sql: str, label: str = "") -> bool:
    r = httpx.post(MGMT_URL, headers=headers, json={"query": sql}, timeout=60)
    if r.status_code in (200, 201):
        print(f"  {label}: OK")
        return True
    else:
        print(f"  {label}: {r.status_code} — {r.text[:400]}")
        return False

files = sorted(SQL_DIR.glob("*.sql"))
ok = True
for f in files:
    print(f"\n--- {f.name} ---")
    sql = f.read_text(encoding="utf-8")
    ok = run_sql(sql, f.name) and ok

sys.exit(0 if ok else 1)
