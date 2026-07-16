"""Write-only observability logging to Supabase.

All writes use the service-role client (RLS: log tables allow service role only).
Every function swallows exceptions — a logging failure must never break the chat path.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

log = logging.getLogger(__name__)


def _db():
    from src.catalog import get_service_db
    return get_service_db()


def log_query(
    *,
    session_id: str,
    user_query: str,
    locale: str,
    model: str,
    final_answer: str,
    latency_ms: int,
    status: str,
    error_code: str | None = None,
    retrieved_ids: list[str] | None = None,
    user_id: str | None = None,
) -> str:
    """Insert into query_logs. Returns the new query UUID.

    user_id is None for anonymous sessions — the column is nullable so
    existing anonymous-only logging keeps working unchanged.
    """
    qid = str(uuid4())
    try:
        _db().table("query_logs").insert({
            "id":            qid,
            "session_id":    session_id,
            "user_id":       user_id,
            "locale":        locale,
            "user_query":    user_query[:2000],
            "final_answer":  final_answer[:4000],
            "model":         model,
            "latency_ms":    latency_ms,
            "status":        status,
            "error_code":    error_code,
            "retrieved_ids": json.dumps(retrieved_ids) if retrieved_ids else None,
        }).execute()
    except Exception as exc:
        log.warning("log_query failed: %s", exc)
    return qid


def log_tool_calls(query_id: str, tool_calls: list[dict[str, Any]]) -> None:
    """Insert one row per tool call into tool_call_logs."""
    if not tool_calls:
        return
    try:
        rows = []
        for tc in tool_calls:
            args = tc.get("arguments", {})
            rows.append({
                "query_id":  query_id,
                "tool_name": tc.get("tool_name", "filter_wines"),
                "arguments": json.dumps(args) if not isinstance(args, str) else args,
                "success":   True,
            })
        _db().table("tool_call_logs").insert(rows).execute()
    except Exception as exc:
        log.warning("log_tool_calls failed: %s", exc)


def log_security_event(
    *,
    session_id: str,
    user_query: str,
    event_type: str,
    severity: str,
    action_taken: str,
    user_id: str | None = None,
    locale: str | None = None,
    matched_rule: str | None = None,
    model: str | None = None,
) -> None:
    """Insert into security_events. Never visible to users — service-role only."""
    try:
        _db().table("security_events").insert({
            "session_id":   session_id,
            "user_id":      user_id,
            "locale":       locale,
            "event_type":   event_type,
            "severity":     severity,
            "user_query":   user_query[:2000],
            "matched_rule": matched_rule,
            "action_taken": action_taken,
            "model":        model,
        }).execute()
    except Exception as exc:
        log.warning("log_security_event failed: %s", exc)


def log_feedback(
    *,
    session_id: str,
    query_id: str,
    wine_id: str | None,
    wine_title: str | None,
    rating: str,
    user_id: str | None = None,
    reason: str | None = None,
) -> bool:
    """Upsert into recommendation_feedback.

    Logged-in users: upsert on the (user_id, query_id, wine_id) unique
    constraint — re-tapping 👍/👎 changes the existing row's rating instead
    of duplicating it (sql/08_feedback.sql). Anonymous users (user_id=None)
    always insert — Postgres treats NULL != NULL, so the unique constraint
    never applies to them anyway, and there's no per-user profile to fold
    the rating into regardless.

    Returns False (never raises) on failure so the caller stays silent —
    SPEC §5.4: a feedback write failure must not surface an error to the user.
    """
    row = {
        "session_id": session_id,
        "user_id":    user_id,
        "query_id":   query_id,
        "wine_id":    wine_id,
        "wine_title": wine_title,
        "rating":     rating,
        "reason":     reason,
    }
    try:
        if user_id:
            _db().table("recommendation_feedback").upsert(
                row, on_conflict="user_id,query_id,wine_id"
            ).execute()
        else:
            _db().table("recommendation_feedback").insert(row).execute()
        return True
    except Exception as exc:
        log.warning("log_feedback failed: %s", exc)
        return False


def delete_feedback(*, user_id: str, wine_id: str) -> None:
    """Delete all recommendation_feedback rows for this user + wine.

    Called on toggle-off so that white buttons mean 'no opinion' in the DB
    as well as in the UI.  Swallows all exceptions — a delete failure must
    not break the chat path (SPEC §5.4 principle).
    """
    try:
        _db().table("recommendation_feedback") \
            .delete() \
            .eq("user_id", user_id) \
            .eq("wine_id", wine_id) \
            .execute()
    except Exception as exc:
        log.warning("delete_feedback failed: %s", exc)


def delete_all_feedback(user_id: str) -> None:
    """Delete EVERY recommendation_feedback row for this user (GDPR
    'Forget everything about me' — US-004), not just one wine.

    Unlike delete_feedback (per-wine, used by the toggle-off UI flow), this
    has no wine_id filter. Called alongside delete_preferences/delete_thread
    in the sidebar's forget-me handler so the GDPR erasure is complete —
    without it, a user's historical 👍/👎 ratings survived under their
    user_id even after "forgetting everything." Swallows all exceptions —
    same best-effort principle as the other forget-me deletions.
    """
    try:
        _db().table("recommendation_feedback") \
            .delete() \
            .eq("user_id", user_id) \
            .execute()
    except Exception as exc:
        log.warning("delete_all_feedback failed: %s", exc)


def erase_user_history(user_id: str) -> bool:
    """Anonymize + scrub this user's query_logs rows (GDPR 'Forget everything
    about me' — US-004) — NEVER hard-delete them.

    Hard-deleting query_logs would cascade (ON DELETE CASCADE, sql/01) into
    token_usage, silently shrinking ratelimit.get_daily_cost_micros()'s
    running total — i.e. forget-me would let a user reset their own
    contribution to the shared daily cost cap (spend -> forget -> spend
    again). Instead this unlinks identity and erases content while leaving
    the numeric cost rows intact and still counted:
      - query_logs: user_id -> NULL, user_query/final_answer -> '[erased]'.
      - security_events: user_id -> NULL for the same user. The column's own
        FK is `on delete set null` (sql/07), but that only fires if the
        auth.users row itself is deleted — forget-me does not delete the
        account, only the user's data, so it needs this explicit UPDATE too.
        The event content (user_query, matched_rule, etc.) is intentionally
        LEFT INTACT — those rows exist for security audit, not
        personalisation, and unlinking the identity is enough for GDPR
        purposes here (see the handoff for this trade-off spelled out).

    Returns False (never raises) on any failure, so the forget-me UI can
    show its existing generic error instead of a false success.
    """
    try:
        _db().table("query_logs").update({
            "user_id":      None,
            "user_query":   "[erased]",
            "final_answer": "[erased]",
        }).eq("user_id", user_id).execute()
        _db().table("security_events").update({
            "user_id": None,
        }).eq("user_id", user_id).execute()
        return True
    except Exception as exc:
        log.warning("erase_user_history failed: %s", exc)
        return False


def get_feedback_reason(*, user_id: str, query_id: str | None, wine_id: str) -> dict[str, Any] | None:
    """Read the fold-delta provenance recorded in this exact
    (user_id, query_id, wine_id) row's `reason` column (Phase 3 step 6h).

    Returns the parsed delta dict, or None if the row/reason is missing,
    NULL, or unparseable. Callers MUST treat None as "revert nothing" — the
    only safe default for a row that predates this feature (legacy) or was
    never actually folded (e.g. a 👎 whose value was already preferred, so
    the fold itself applied nothing — see fold_feedback).
    """
    if not query_id:
        return None
    try:
        resp = (
            _db()
            .table("recommendation_feedback")
            .select("reason")
            .eq("user_id", user_id)
            .eq("query_id", query_id)
            .eq("wine_id", wine_id)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        raw = resp.data[0].get("reason")
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        log.warning("get_feedback_reason failed: %s", exc)
        return None


def get_latest_ratings(user_id: str) -> dict[str, str]:
    """Return {wine_id: rating} for the user's most recent rating per wine.

    Used to pre-populate st.session_state['wine_ratings'] on session start so
    buttons for previously-rated wines appear with the correct colour without
    requiring the user to click again.  Fetches at most 500 rows (covers any
    realistic usage history) and takes the first occurrence of each wine_id
    (rows are ordered newest-first, so that IS the latest rating).
    Swallows all exceptions — a read failure returns an empty dict, the UI
    simply shows uncoloured buttons and writes the rating again on next click.
    """
    try:
        rows = (
            _db()
            .table("recommendation_feedback")
            .select("wine_id,rating")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
            .data
        )
        seen: dict[str, str] = {}
        for row in rows:
            wid = str(row.get("wine_id") or "")
            if wid and wid not in seen:
                seen[wid] = row["rating"]
        return seen
    except Exception as exc:
        log.warning("get_latest_ratings failed: %s", exc)
        return {}


def log_token_usage(
    *,
    query_id: str,
    input_tokens: int,
    output_tokens: int,
    cost_eur_micros: int,
) -> None:
    """Upsert into token_usage (PK = query_id)."""
    if not (input_tokens or output_tokens):
        return
    try:
        _db().table("token_usage").upsert({
            "query_id":       query_id,
            "input_tokens":   input_tokens,
            "output_tokens":  output_tokens,
            "cost_eur_micros": cost_eur_micros,
        }).execute()
    except Exception as exc:
        log.warning("log_token_usage failed: %s", exc)


def log_stt_usage(
    *,
    session_id: str,
    user_id: str | None,
    model: str,
    seconds: float | None,
    cost_eur_micros: int,
) -> None:
    """Insert into stt_usage (sql/10 — Phase 4 step 3).

    Folds voice-transcription spend into the daily cost cap alongside
    token_usage (see ratelimit.get_daily_cost_micros). Called for every
    consumed voice recording, including silent ones that still billed
    seconds. Swallows all exceptions — a logging failure must never break
    the chat path.
    """
    try:
        _db().table("stt_usage").insert({
            "session_id":      session_id,
            "user_id":         user_id,
            "model":           model,
            "seconds":         seconds,
            "cost_eur_micros": cost_eur_micros,
        }).execute()
    except Exception as exc:
        log.warning("log_stt_usage failed: %s", exc)
