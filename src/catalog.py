"""Supabase client + in-memory cached active-wines DataFrame (TTL=60 s).

app-driven edits must call invalidate_cache() after writing so the next
read reflects the change immediately instead of waiting for the TTL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from supabase import Client, create_client

from src.config import SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY, SUPABASE_URL

_CACHE_TTL = 60  # seconds
_cache: dict[str, Any] = {"df": None, "ts": None}

_service_client: Client | None = None
_anon_client: Client | None = None


def get_service_db() -> Client:
    global _service_client
    if _service_client is None:
        _service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _service_client


def get_anon_db() -> Client:
    global _anon_client
    if _anon_client is None:
        _anon_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _anon_client


def invalidate_cache() -> None:
    _cache["df"] = None
    _cache["ts"] = None


def _fetch_all_active() -> list[dict]:
    db = get_anon_db()
    rows: list[dict] = []
    offset, page_size = 0, 1000
    while True:
        r = (
            db.table("wines")
            .select("*")
            .eq("is_active", True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows.extend(r.data)
        if len(r.data) < page_size:
            break
        offset += page_size
    return rows


def get_active_wines_df() -> pd.DataFrame:
    """Return cached DataFrame of active wines; refresh if stale."""
    now = datetime.now(timezone.utc)
    if (
        _cache["df"] is None
        or _cache["ts"] is None
        or (now - _cache["ts"]).total_seconds() > _CACHE_TTL
    ):
        rows = _fetch_all_active()
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        _cache["df"] = df
        _cache["ts"] = now
    return _cache["df"]
