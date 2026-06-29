"""Rate limiting (sliding window) and daily cost guard.

Rate limit: in-memory per-session, shared across threads via Lock.
Cost guard: queries token_usage table for today's total; falls back to 0 on error.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import NamedTuple

from src.config import DAILY_COST_CAP_MICROS, RATE_LIMIT_PER_MIN

_WINDOW_S = 60.0

_windows: dict[str, deque[float]] = {}
_lock = Lock()


class RateLimitResult(NamedTuple):
    allowed: bool
    reason: str | None = None
    retry_after_s: float | None = None


def check_rate_limit(session_id: str) -> RateLimitResult:
    """Sliding-window check: max RATE_LIMIT_PER_MIN requests per 60 s."""
    now = time.time()
    with _lock:
        q = _windows.setdefault(session_id, deque())
        while q and now - q[0] > _WINDOW_S:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            retry = _WINDOW_S - (now - q[0])
            return RateLimitResult(False, "RATE_LIMIT", round(retry, 1))
        q.append(now)
    return RateLimitResult(True)


def get_daily_cost_micros() -> int:
    """Sum cost_eur_micros from token_usage for today (UTC). Returns 0 on failure."""
    try:
        from datetime import date
        from src.catalog import get_service_db

        today = date.today().isoformat()  # e.g. "2026-06-08"
        db = get_service_db()
        # query_logs has created_at; token_usage.query_id is FK → query_logs.id
        ql = (
            db.table("query_logs")
            .select("id")
            .gte("created_at", today)
            .execute()
        )
        if not ql.data:
            return 0
        ids = [r["id"] for r in ql.data]
        # Fetch cost for those query IDs in batches to respect URL length limits
        total = 0
        for i in range(0, len(ids), 200):
            batch = ids[i : i + 200]
            tu = (
                db.table("token_usage")
                .select("cost_eur_micros")
                .in_("query_id", batch)
                .execute()
            )
            total += sum(r.get("cost_eur_micros", 0) for r in tu.data)
        return total
    except Exception:
        return 0


def check_cost_cap() -> RateLimitResult:
    """Block if today's spend already reached DAILY_COST_CAP_MICROS."""
    spent = get_daily_cost_micros()
    if spent >= DAILY_COST_CAP_MICROS:
        return RateLimitResult(False, "COST_CAP")
    return RateLimitResult(True)
