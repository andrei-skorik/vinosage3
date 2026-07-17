# TASK: Phase 4, step 3 of 4 — STT cost accounting (sql/10) + anon-thread housekeeping

> For Claude Code. Read `CLAUDE.md` first. Two backlog items with one theme
> (resource accounting & hygiene), disjoint files. Standard rules bite here:
> do NOT run SQL against Supabase (generate sql/10, the human applies it,
> and it must be applied BEFORE the code that writes to it ships — same
> ordering rule as sql/09); logging swallows exceptions; money is integer
> micros.

## Part A — STT spend counted toward the €1/day cap

### A1. NEW `sql/10_stt_usage.sql` (generate only; human applies)
```sql
-- VinoSage 2.0 / Phase 4: voice-transcription spend, folded into the daily
-- cost cap. Closes the step-4 known gap (STT was billed per audio second
-- but invisible to DAILY_COST_CAP_EUR because token_usage is query-keyed
-- and no query exists at transcription time). Convention notes: money in
-- integer micro-euros; OpenRouter reports usage.cost in USD — stored here
-- 1:1 as EUR-equivalent micros, consistent with the illustrative-EUR
-- pricing already used in config.CHAT_MODELS. Service-role only.
create table if not exists stt_usage (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  session_id      text not null,
  user_id         uuid references auth.users(id) on delete set null,
  model           text not null,
  seconds         numeric,
  cost_eur_micros integer not null default 0 check (cost_eur_micros >= 0)
);
create index if not exists idx_stt_usage_time on stt_usage(created_at desc);

alter table stt_usage enable row level security;
create policy stt_service on stt_usage
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
```

### A2. `src/transcribe.py` — return the cost
The success dict gains `"cost_eur_micros": int(round((usage.get("cost") or 0) * 1_000_000))`
(0 when absent). One-line comment: USD-as-EUR approximation, matching the
illustrative pricing convention. Extend one existing test to assert the
field (and 0-when-absent).

### A3. `src/logging_db.py` — `log_stt_usage(session_id, user_id, model, seconds, cost_eur_micros)`
Service-role insert, swallow-exceptions, same shape as the other helpers.

### A4. `app.py` — call it
In the voice block, after a successful transcription (any consumed outcome
that returned usage — including empty-transcript silence, which still
billed seconds), call `log_stt_usage(...)`. Best-effort; never blocks.

### A5. `src/ratelimit.py::get_daily_cost_micros` — add the STT sum
Alongside the existing token_usage aggregation, add
`sum(stt_usage.cost_eur_micros)` for today (simple `.gte("created_at", today)`
select; no batching needed — no `.in_()` involved). Same try/except: any
failure contributes 0. Extend `tests/test_ratelimit.py` (or the hardening
file): monkeypatched DB returning both sources → totals add up; stt query
failure → token total still returned.

## Part B — anon:* thread housekeeping

### B1. `src/checkpointer.py` — `sweep_anon_threads() -> int`
Deletes EVERY `anon:*` thread. Safety argument (put it in the docstring):
anonymous sessions never read checkpoint state back — their chat lives in
st.session_state, `chat_log` is never appended for them, and per-turn
channels are overwritten on each invoke — so deleting an anon thread
between turns is behaviorally invisible even for a LIVE anonymous session.
Implementation: no-op returning 0 on MemorySaver; on PostgresSaver, read
distinct `thread_id LIKE 'anon:%'` from the library's `checkpoints` table
via the existing pool (read-only query against library-owned tables is
acceptable; MUTATIONS go through the official `delete_thread` API only),
then loop `delete_thread(tid)`. Swallow everything; return the count
deleted.

### B2. `src/ui/admin.py` — button in Developer settings
`st.button(t("admin_sweep_anon_button", locale))` → spinner → 
`st.toast(t("admin_sweep_anon_done", locale, count=n))`. Manual-only by
design (no cron on Streamlit Cloud); note the future option of an
on-startup opportunistic sweep in the handoff, not in code.

### B3. Locale keys (ALL FOUR files; the parity test enforces it)
en: `"admin_sweep_anon_button": "Clean up anonymous threads"`,
`"admin_sweep_anon_done": "Removed {count} anonymous thread(s)."`
de: `"Anonyme Threads bereinigen"` / `"{count} anonyme Threads entfernt."`
ru: `"Очистить анонимные треды"` / `"Удалено анонимных тредов: {count}."`
fi: `"Siivoa anonyymit keskustelut"` / `"Poistettu {count} anonyymia keskustelua."`

### B4. Tests
MemorySaver path returns 0 and doesn't raise; PostgresSaver path with a
monkeypatched pool/delete_thread deletes only `anon:*` ids (a `user:*` id in
the fixture must survive); total failure returns 0.

## Verification
1. `pytest` — full suite green (locale-parity test passes with the new keys).
2. `git diff sql/` shows ONLY the new `10_stt_usage.sql` (01–09 untouched).
3. Report the apply-order reminder prominently: **sql/10 must be applied
   before deploy**, else `log_stt_usage` silently no-ops (swallowed) and the
   cap under-counts — degraded, not broken.
4. Handoff: both known gaps (step-4 STT cost; anon-thread orphans) marked
   resolved. STOP for review.

## Human checklist
1. Apply `sql/10_stt_usage.sql` (Supabase SQL Editor), BEFORE pulling the
   deploy.
2. Smoke: one voice question → row appears in `stt_usage`; admin analytics
   still fine; press the sweep button → toast with a count; a logged-in
   thread survives (F5 as a logged-in user still restores chat).
