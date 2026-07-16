"""LangGraph checkpointer — durable conversation state (SPEC §5.10 step 9).

Persists the per-thread chat log via ``PostgresSaver`` on the existing
Supabase PostgreSQL instance, so conversations survive browser refreshes
and server restarts for logged-in users.

Design decisions (see PHASE3 notes for rationale):

- **DATABASE_URL is read via ``os.getenv``, not ``config._require()``** —
  the same graceful-degradation philosophy as the LangSmith key (SPEC §3.5):
  durable checkpointing is an enhancement; its absence (or a Postgres
  outage) must never break chat. Without the URL we fall back to an
  in-process ``MemorySaver``, which behaves exactly like the pre-step-9
  session-only memory.

- **Thread identity**: logged-in users get ``thread_id = user_id`` (stable
  across refreshes/restarts — this is what makes persistence real);
  anonymous users get ``thread_id = session_id`` (a per-browser-session
  uuid4), which makes their thread ephemeral by construction — satisfying
  the "anonymous sessions get no persistence guarantee" constraint without
  a separate code path. The mapping lives in ``resolve_thread_id``.

- **The sacred layer-3 filter is untouched.** ``app.py::_agent_history``
  (with ``_history_source_ok``) still transforms the chat log into
  LLM-ready history at read time, every turn. This module only changes
  *where the log survives*, never how it is filtered.

- **All I/O here swallows exceptions** (project convention: persistence and
  logging never block the chat reply).

Connection string: use the Supabase **Session pooler** URI (port 5432 on
``*.pooler.supabase.com``) or the direct connection. ``prepare_threshold=0``
keeps psycopg compatible with PgBouncer-style pooling either way.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Read via os.getenv (NOT config._require) — see module docstring.
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

_checkpointer: Any = None
_pool: Any = None


def get_checkpointer():
    """Return the process-wide checkpointer (PostgresSaver or MemorySaver).

    Created lazily on first call; cached for the process lifetime. Falls
    back to MemorySaver on any failure so the app always starts.
    """
    global _checkpointer, _pool
    if _checkpointer is not None:
        return _checkpointer

    if DATABASE_URL:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=1,
                max_size=4,
                open=True,
                kwargs={
                    "autocommit": True,          # required by PostgresSaver
                    "prepare_threshold": 0,      # PgBouncer/pooler-safe
                    "row_factory": dict_row,     # required by PostgresSaver
                },
            )
            _checkpointer = PostgresSaver(_pool)
            log.info("Checkpointer: PostgresSaver active (durable threads)")
            return _checkpointer
        except Exception as exc:  # missing driver, bad URL, DB down — degrade
            log.warning(
                "Checkpointer: PostgresSaver unavailable (%s); "
                "falling back to in-process MemorySaver", exc
            )

    from langgraph.checkpoint.memory import MemorySaver

    _checkpointer = MemorySaver()
    log.info("Checkpointer: MemorySaver active (session-only, no durability)")
    return _checkpointer


def is_durable() -> bool:
    """True when the active checkpointer persists across restarts.

    Used by the admin panel status indicator only.
    """
    cp = get_checkpointer()
    return type(cp).__name__ == "PostgresSaver"


def sweep_anon_threads() -> int:
    """Delete every ``anon:*`` checkpoint thread (Phase 4 step 3 housekeeping).

    Safety argument: anonymous sessions never read checkpoint state back —
    their chat lives in ``st.session_state``, ``chat_log`` is never appended
    for them (app.py only calls ``append_chat_log`` for logged-in users),
    and every other per-turn channel is simply overwritten on the graph's
    next invoke. So deleting an ``anon:*`` thread between turns is
    behaviorally invisible even for a LIVE anonymous session — there is
    nothing durable for them to lose.

    No-op (returns 0) on ``MemorySaver`` — nothing to sweep; it's already
    ephemeral and per-process. On ``PostgresSaver``, reads distinct
    ``anon:*`` thread_ids directly from the library-owned ``checkpoints``
    table (read-only query against langgraph-checkpoint-postgres' own
    schema, not this project's ``sql/``) via the existing connection pool,
    then deletes each one through the official ``delete_thread`` API only —
    mutations never touch the library's tables directly. The ``anon:``
    prefix is re-checked in Python after the fetch as a second, independent
    guard (defense-in-depth: a ``user:*`` thread must never be swept even if
    the SQL filter were ever loosened). Swallows all exceptions; manual/
    best-effort by design (admin-triggered — no cron on Streamlit Cloud).
    """
    cp = get_checkpointer()
    if type(cp).__name__ != "PostgresSaver":
        return 0
    try:
        from src.graph import delete_thread  # local import: graph.py imports this module

        with _pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'anon:%'"
                )
                rows = cur.fetchall()

        thread_ids = [
            (row["thread_id"] if isinstance(row, dict) else row[0])
            for row in rows
        ]
        anon_ids = [tid for tid in thread_ids if tid.startswith("anon:")]

        count = 0
        for tid in anon_ids:
            if delete_thread(tid):
                count += 1
        return count
    except Exception as exc:
        log.warning("sweep_anon_threads failed: %s", exc)
        return 0


def resolve_thread_id(user_id: str | None, session_id: str) -> str:
    """Stable thread for logged-in users; ephemeral for anonymous.

    - logged-in: ``user:{user_id}`` — survives refresh & restart.
    - anonymous: ``anon:{session_id}`` — new uuid every browser session, so
      the thread is unreachable after refresh (ephemeral by construction).
    """
    return f"user:{user_id}" if user_id else f"anon:{session_id}"


# ── Chat-log (de)serialization ────────────────────────────────────────────────
# st.session_state.messages entries carry RetrievedWine objects in "sources".
# For durable storage we flatten them to plain dicts; on rehydration we wrap
# them back into PersistedWine, whose attributes (wine_id/title/similarity/
# payload) match every getattr() access site in chat_view.py, app.py
# (_agent_history / _history_source_ok) and the CSV export.


@dataclass
class PersistedWine:
    """Attribute-compatible stand-in for rag.RetrievedWine after rehydration."""
    wine_id: Any = None
    title: str | None = None
    similarity: float | None = None
    payload: dict = field(default_factory=dict)


def serialize_wine(w: Any) -> dict[str, Any]:
    return {
        "wine_id":    getattr(w, "wine_id", None),
        "title":      getattr(w, "title", None),
        "similarity": getattr(w, "similarity", None),
        "payload":    dict(getattr(w, "payload", {}) or {}),
    }


def serialize_chat_entry(m: dict[str, Any]) -> dict[str, Any]:
    """Flatten one st.session_state.messages entry to JSON-safe primitives."""
    entry = {k: v for k, v in m.items() if k != "sources"}
    if m.get("sources"):
        entry["sources"] = [serialize_wine(w) for w in m["sources"]]
    return entry


def rehydrate_chat_entry(m: dict[str, Any]) -> dict[str, Any]:
    """Inverse of serialize_chat_entry — restore attribute access on sources."""
    entry = dict(m)
    if entry.get("sources"):
        entry["sources"] = [
            PersistedWine(
                wine_id=s.get("wine_id"),
                title=s.get("title"),
                similarity=s.get("similarity"),
                payload=s.get("payload") or {},
            )
            for s in entry["sources"]
        ]
    return entry
