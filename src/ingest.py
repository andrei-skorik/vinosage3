"""CSV normalisation + upsert into Supabase wines table.

source_key = lower(trim(title)) | vintage_year_or_NV | capacity_ml
Prices already converted to EUR (format: "EUR 11.79 per bottle").
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VALID_TYPES = {"Red", "White", "Rosé", "Tawny", "Orange", "Brown", "Mixed"}
BATCH_SIZE = 100


# ── Field parsers ─────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> tuple[int | None, str | None]:
    """'EUR 11.79 per bottle' -> (1179, 'per bottle'); unparseable -> (None, None)."""
    if not raw:
        return None, None
    m = re.search(r"[\d]+\.[\d]+", raw)
    if not m:
        return None, None
    cents = round(float(m.group()) * 100)
    unit_m = re.search(r"per bottle|per case|each", raw, re.IGNORECASE)
    unit = unit_m.group().lower() if unit_m else None
    return cents, unit


def _parse_capacity(raw: str) -> tuple[int, bool]:
    """Unit-aware: '75CL'->750, '750ML'->750, '1.5LTR'->1500.
    Returns (capacity_ml, flagged). Unrecognised -> (750, True)."""
    if not raw:
        return 750, True
    cleaned = raw.strip().upper()
    m = re.match(r"^([\d.]+)\s*(CL|ML|LTR|L)$", cleaned)
    if not m:
        return 750, True
    val, unit = float(m.group(1)), m.group(2)
    if unit == "CL":
        return int(val * 10), False
    if unit == "ML":
        return int(val), False
    if unit in ("L", "LTR"):
        return int(val * 1000), False
    return 750, True


def _parse_abv(raw: str) -> float | None:
    """'ABV 14.00%' -> 14.0."""
    if not raw:
        return None
    m = re.search(r"[\d]+\.[\d]+", raw)
    return float(m.group()) if m else None


def _parse_vintage(raw: str) -> tuple[int | None, bool]:
    """'NV' -> (None, True); '2021' -> (2021, False)."""
    if not raw or raw.strip().upper() == "NV":
        return None, True
    m = re.search(r"\d{4}", raw)
    return (int(m.group()), False) if m else (None, True)


def _source_key(title: str, vintage_year: int | None, is_nv: bool, capacity_ml: int) -> str:
    vintage_part = "NV" if (is_nv or vintage_year is None) else str(vintage_year)
    return f"{title.lower().strip()}|{vintage_part}|{capacity_ml}"


# ── Row normalisation ─────────────────────────────────────────────────────────

def normalise_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Return a wines-table dict or None if the row must be skipped."""
    # pandas.read_csv() (used by the admin panel's CSV import) infers a dtype
    # per column from the data it sees. An empty cell becomes float NaN, not
    # "" (and NaN is truthy in Python, so "if not raw" guards wouldn't catch
    # it). A column that's all-numeric in a given CSV — e.g. "Vintage" with
    # no "NV" rows to force object dtype — comes back as int/float per cell,
    # not str. csv.DictReader (the CLI ingest path) always yields "", so this
    # normalisation is a no-op there regardless. NaN's defining property is
    # that it's the only value not equal to itself.
    row = {
        k: "" if v is None or (isinstance(v, float) and v != v) else str(v)
        for k, v in row.items()
    }

    title = row.get("Title", "").strip()
    if not title:
        return None

    price_cents, price_unit = _parse_price(row.get("Approx Price", ""))
    capacity_ml, _flagged   = _parse_capacity(row.get("Capacity", ""))
    abv                     = _parse_abv(row.get("ABV", ""))
    vintage_year, is_nv     = _parse_vintage(row.get("Vintage", ""))
    raw_type                = (row.get("Type") or "").strip()
    wine_type               = raw_type if raw_type in VALID_TYPES else None

    return {
        "source_key":       _source_key(title, vintage_year, is_nv, capacity_ml),
        "title":            title,
        "description":      row.get("Description", "").strip() or None,
        "price_eur_cents":  price_cents,
        "capacity_ml":      capacity_ml,
        "grape":            row.get("Grape", "").strip() or None,
        "secondary_grapes": row.get("Secondary Grape Varieties", "").strip() or None,
        "closure":          row.get("Closure", "").strip() or None,
        "country":          row.get("Country", "").strip() or None,
        "characteristics":  row.get("Characteristics", "").strip() or None,
        "price_unit":       price_unit,
        "type":             wine_type,
        "abv_percent":      abv,
        "region":           row.get("Region", "").strip() or None,
        "style":            row.get("Style", "").strip() or None,
        "vintage_year":     vintage_year,
        "is_nv":            is_nv,
        "appellation":      row.get("Appellation", "").strip() or None,
        "is_active":        True,
    }


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and normalise the CSV.  Returns (rows, warnings)."""
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    with open(path, encoding="utf-8") as f:
        for i, raw in enumerate(csv.DictReader(f), 1):
            record = normalise_row(raw)
            if record is None:
                warnings.append(f"Row {i}: missing title — skipped")
                continue
            if record["price_eur_cents"] is None:
                warnings.append(f"Row {i} ({record['title']!r}): unparseable price — excluded from filters")
            rows.append(record)

    return rows, warnings


# ── Upsert ────────────────────────────────────────────────────────────────────

def upsert_wines(
    rows: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert rows into wines (conflict on source_key).

    Returns {"inserted": N, "updated": N, "total": N}.
    In dry_run mode just validates and returns counts without writing.
    """
    from supabase import create_client
    from src.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

    if dry_run:
        log.info("[dry-run] would upsert %d rows", len(rows))
        return {"inserted": 0, "updated": 0, "total": len(rows)}

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        client.table("wines").upsert(batch, on_conflict="source_key").execute()
        total += len(batch)
        log.info("upserted %d/%d rows", total, len(rows))

    return {"inserted": len(rows), "updated": 0, "total": total}
