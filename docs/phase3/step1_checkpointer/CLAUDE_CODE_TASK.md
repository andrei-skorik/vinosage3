# TASK: Build step 9 — PostgresSaver checkpointer (Phase 3, step 1 of 5)

> For Claude Code. Read `CLAUDE.md` and `docs/PHASE2_HANDOFF.md` first, as always.
> This task implements SPEC §5.10 step 9. Reference implementation files are
> provided in `docs/phase3/step1_checkpointer/` — **apply and adapt them, do not
> re-derive the design from scratch.** Where the reference files conflict with
> the actual repo state (drifted line numbers, renamed helpers), the repo wins;
> preserve the reference design intent.

## Goal
Replace the *storage* of short-term conversation memory (currently
`st.session_state` only) with a durable LangGraph `PostgresSaver` checkpointer
on the existing Supabase Postgres, so logged-in users' conversations survive
browser refresh and server restart.

## Approved design decisions (do not re-litigate)
1. **Thread identity:** `thread_id = "user:{user_id}"` for logged-in users,
   `"anon:{session_id}"` for anonymous. Rationale: `session_id` is a per-browser
   `uuid4()` that dies on refresh, so keying by it would make persistence
   unreachable; anonymous users remain ephemeral by construction, satisfying
   the handoff constraint.
2. **`DATABASE_URL` via `os.getenv` with graceful fallback to `MemorySaver`**
   (same philosophy as the LangSmith key). Missing URL or Postgres outage must
   never break chat. Do NOT use `config._require` for this key.
3. **`app.py::_agent_history` is NOT removed or modified.** It carries the
   third anti-hallucination layer (`_history_source_ok`) and must keep
   filtering history at read time, every turn. Only the *store* changes.

## Files to apply (reference implementation)
From `docs/phase3/step1_checkpointer/`:

| Reference file | Action |
|---|---|
| `src/checkpointer.py` | NEW — copy as-is |
| `src/graph.py` | MODIFIED — diff against repo `src/graph.py`; apply: `_append_chat_log` reducer + `chat_log: Annotated[...]` channel in `AgentState`, `compile(checkpointer=get_checkpointer())`, `thread_id` param in `run_via_graph`, new helpers `append_chat_log` / `get_thread_chat_log` / `delete_thread` |
| `src/agent.py` | MODIFIED — `run_agent` gains `thread_id: str \| None = None`, passed through to `run_via_graph` |
| `app.py` | MODIFIED — three edits: (1) resolve `thread_id` + one-time rehydration block right after `session_id` in `main()`; (2) pass `thread_id=thread_id` to `run_agent`; (3) after the assistant message append + `log_query`, call `append_chat_log(thread_id, [...])` for logged-in users only |
| `scripts/setup_checkpointer.py` | NEW — copy as-is |
| `tests/test_checkpointer.py` | NEW — copy as-is |
| `requirements.txt` | ADD three deps (see below) |

If the repo's `graph.py` / `agent.py` / `app.py` have drifted from the
reference snapshots, port the *changes* (they are small and localized), not
the whole files.

## Additional edits (not in reference files — repo files I didn't have)
1. **`src/ui/sidebar.py` — GDPR hook:** in the "Forget everything about me"
   handler, next to the existing `delete_preferences(user_id)` call, add:
   ```python
   from src.graph import delete_thread
   delete_thread(f"user:{user_id}")   # erase durable conversation too (US-004)
   ```
   Best-effort, same swallow-failure spirit; `delete_thread` already swallows.
2. **`.env.example`:** add
   ```
   # Durable conversation state (SPEC step 9). Optional — app degrades to
   # in-memory history when absent. Use the Supabase Session pooler URI.
   DATABASE_URL=
   ```

## requirements.txt
Add, then pin the resolved versions after `pip install` (project convention:
exact pins):
```
langgraph-checkpoint-postgres>=2.0
psycopg[binary]>=3.2
psycopg-pool>=3.2
```

## Constraints (from CLAUDE.md — restated because they bite here)
- Do NOT run SQL against Supabase, and do NOT execute
  `scripts/setup_checkpointer.py` yourself — it performs DDL. Tell the human
  to run it once after setting `DATABASE_URL`.
- The retry→fallback loop in `agent_node` must remain byte-identical.
- `test_pair_with_food.py` must pass unchanged.
- All new persistence calls swallow exceptions (never block chat).
- Do not touch `sql/01–09`, the three anti-hallucination layers, or the tools.

## Verification (run all before stopping for review)
1. `pytest` — full suite green, including `tests/test_checkpointer.py` and the
   unchanged `test_pair_with_food.py`.
2. `python -c "import src.checkpointer, src.graph"` with `DATABASE_URL` unset —
   must not raise; log line should say MemorySaver fallback.
3. Grep check: `_agent_history` and `_history_source_ok` in `app.py` are
   unmodified (compare with `git diff`).
4. Summarize the diff and STOP for human review. Do not proceed to the next
   Phase-3 step in the same run.

## Human-only checklist (report these back to the human at the end)
1. Add `DATABASE_URL` (Supabase → Settings → Database → Session pooler URI)
   to `.env` and Streamlit secrets.
2. Run once: `python scripts/setup_checkpointer.py`.
3. Manual smoke test: log in → send 2 messages → refresh (F5) → history
   restored; open a private window anonymously → chat → refresh → history
   gone (expected).

## Known accepted gaps (record in the Phase-3 handoff, do not fix now)
- Guard-blocked turns are not persisted to the durable log (canned replies
  vanish on refresh — accepted).
- Anonymous invocations still checkpoint transient per-turn state under
  `anon:*` threads; rows are orphaned and harmless. Future housekeeping:
  periodic `delete_thread` sweep of `anon:*`.
