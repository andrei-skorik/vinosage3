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
