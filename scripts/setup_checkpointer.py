"""One-time setup for the LangGraph PostgresSaver checkpointer (SPEC step 9).

Run this ONCE, manually, before deploying the checkpointer change:

    python scripts/setup_checkpointer.py

It calls PostgresSaver.setup(), which creates the library-managed tables
(checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations)
in the database pointed to by DATABASE_URL.

Why this is a script and not a numbered sql/ file: the project convention
(new SQL in sql/0N_*.sql) exists so *our* schema is reviewable and append-
only. The checkpointer tables are owned and versioned by the langgraph
library itself — its setup() runs internal migrations that we must not
hand-copy, or we'd desync from the library on upgrade. This script is the
sanctioned way to apply them; a human runs it, consistent with the
"never run SQL against Supabase automatically" working rule.

DATABASE_URL: use the Supabase "Session pooler" connection string
(Settings -> Database -> Connection string -> Session pooler), e.g.
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL is not set (add it to .env / Streamlit secrets).")
        return 1

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        print("ERROR: langgraph-checkpoint-postgres is not installed.")
        print("       pip install -r requirements.txt")
        return 1

    print("Connecting and creating checkpointer tables (idempotent)...")
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
    print("OK: checkpoints / checkpoint_blobs / checkpoint_writes / "
          "checkpoint_migrations are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
