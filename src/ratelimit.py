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

# Stale-session cleanup (memory-leak fix): _windows previously grew without
# bound — one deque per session_id, never removed. A long-lived deployment
# accumulates an entry for every browser session ever seen. The sweep below
# runs at most once per _CLEANUP_INTERVAL_S, inside the same lock as the
# window check, and drops every session whose newest timestamp has aged out
# of the rate window (its deque can never influence a future decision).
# Bound after fix: |_windows| <= sessions active in the last
# (_WINDOW_S + _CLEANUP_INTERVAL_S) seconds.
_CLEANUP_INTERVAL_S = 300.0

_windows: dict[str, deque[float]] = {}
_lock = Lock()
_last_cleanup: float = 0.0


def _purge_stale_sessions(now: float) -> None:
    """Drop sessions whose entire window has expired. Caller holds _lock."""
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL_S:
        return
    _last_cleanup = now
    stale = [sid for sid, q in _windows.items() if not q or now - q[-1] > _WINDOW_S]
    for sid in stale:
        del _windows[sid]


class RateLimitResult(NamedTuple):
    allowed: bool
    reason: str | None = None
    retry_after_s: float | None = None


def check_rate_limit(session_id: str) -> RateLimitResult:
    """Sliding-window check: max RATE_LIMIT_PER_MIN requests per 60 s."""
    now = time.time()
    with _lock:
        _purge_stale_sessions(now)
        q = _windows.setdefault(session_id, deque())
        while q and now - q[0] > _WINDOW_S:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            retry = _WINDOW_S - (now - q[0])
            return RateLimitResult(False, "RATE_LIMIT", round(retry, 1))
        q.append(now)
    return RateLimitResult(True)


def get_daily_cost_micros() -> int:
    """Sum cost_eur_micros from token_usage + stt_usage for today (UTC).

    Each source is queried and summed independently (Phase 4 step 3 added
    the stt_usage half — voice-transcription spend previously invisible to
    the cap): a failure in one source must not zero out the other, so a
    partial DB hiccup degrades to under-counting, not to blocking everyone
    out of a healthy source. Returns 0 (both) on total failure.
    """
    from datetime import date
    from src.catalog import get_service_db

    today = date.today().isoformat()  # e.g. "2026-06-08"

    token_total = 0
    try:
        db = get_service_db()
        # query_logs has created_at; token_usage.query_id is FK → query_logs.id
        ql = (
            db.table("query_logs")
            .select("id")
            .gte("created_at", today)
            .execute()
        )
        if ql.data:
            ids = [r["id"] for r in ql.data]
            # Fetch cost for those query IDs in batches to respect URL length limits
            for i in range(0, len(ids), 200):
                batch = ids[i : i + 200]
                tu = (
                    db.table("token_usage")
                    .select("cost_eur_micros")
                    .in_("query_id", batch)
                    .execute()
                )
                token_total += sum(r.get("cost_eur_micros", 0) for r in tu.data)
    except Exception:
        token_total = 0

    stt_total = 0
    try:
        db = get_service_db()
        stt = (
            db.table("stt_usage")
            .select("cost_eur_micros")
            .gte("created_at", today)
            .execute()
        )
        stt_total = sum(r.get("cost_eur_micros", 0) for r in (stt.data or []))
    except Exception:
        stt_total = 0

    return token_total + stt_total


def check_cost_cap() -> RateLimitResult:
    """Block if today's spend already reached DAILY_COST_CAP_MICROS."""
    spent = get_daily_cost_micros()
    if spent >= DAILY_COST_CAP_MICROS:
        return RateLimitResult(False, "COST_CAP")
    return RateLimitResult(True)
