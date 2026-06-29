"""Initial catalog load + embedding.

Usage:
    python scripts/seed.py               # full seed + embed
    python scripts/seed.py --dry-run     # validate CSV only, no DB writes
    python scripts/seed.py --skip-embed  # upsert rows but skip embedding step
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make src/ importable from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.ingest import load_csv, upsert_wines
from src.embeddings import reconcile_embeddings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CSV_PATH = Path(__file__).parent.parent / "data" / "WineDataset.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed VinoSage catalog")
    parser.add_argument("--dry-run",    action="store_true", help="Validate CSV, no DB writes")
    parser.add_argument("--skip-embed", action="store_true", help="Upsert rows but skip embedding")
    args = parser.parse_args()

    # 1. Load + normalise CSV
    log.info("Loading %s …", CSV_PATH)
    rows, warnings = load_csv(CSV_PATH)

    log.info("Parsed %d rows, %d warnings", len(rows), len(warnings))
    for w in warnings[:20]:
        log.warning("  %s", w)
    if len(warnings) > 20:
        log.warning("  … and %d more warnings", len(warnings) - 20)

    if args.dry_run:
        log.info("[dry-run] stopping before DB write")
        sys.exit(0)

    # 2. Upsert into Supabase (triggers set needs_embedding=true for new/changed rows)
    log.info("Upserting %d rows into Supabase …", len(rows))
    result = upsert_wines(rows)
    log.info("Upsert done: %s", result)

    if args.skip_embed:
        log.info("--skip-embed: skipping reconcile")
        sys.exit(0)

    # 3. Embed all pending rows
    log.info("Embedding pending rows via OpenRouter …")
    embed_result = reconcile_embeddings()
    log.info("Embed done: %s", embed_result)

    # 4. Final verification
    from supabase import create_client
    from src.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    total    = db.table("wines").select("wine_id", count="exact").execute().count
    embedded = (
        db.table("wines")
        .select("wine_id", count="exact")
        .eq("needs_embedding", False)
        .not_.is_("embedding", "null")
        .execute()
        .count
    )
    pending = (
        db.table("wines")
        .select("wine_id", count="exact")
        .eq("needs_embedding", True)
        .execute()
        .count
    )

    log.info("── Seed complete ──────────────────────────")
    log.info("  Total wines : %d", total)
    log.info("  Embedded    : %d", embedded)
    log.info("  Pending     : %d", pending)
    log.info("  Failures    : %d", embed_result["failed"])

    if embed_result["failed"] > 0:
        log.warning("Some rows failed to embed — re-run seed.py to retry")
        sys.exit(1)


if __name__ == "__main__":
    main()
