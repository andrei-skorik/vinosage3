# TASK: hydrate feedback highlight from DB on history reload

> For Claude Code. Bug confirmed on the live logged-in UI: after Log out →
> Log in (profile intact, NOT forget-me), the rehydrated chat history shows
> all 👍/👎 buttons GREY, even though `recommendation_feedback` still holds
> the user's ratings (verified in Supabase: Lyrarakis has live `up` + `down`
> rows). The DB is the source of truth and it's correct; the UI just never
> reads it when rendering rehydrated history.

## Root cause (verify in `src/ui/chat_view.py`)
The feedback-button ACTIVE-state (green/red highlight) is read from a
session-state ratings cache that is only populated when the user CLICKS a
button in the current session (`_fold_cache` / the ratings dict, now keyed
`(query_id, wine_id)` after the last fix). On a fresh session — after
logout+login, and almost certainly after a plain F5 too — that cache starts
empty, and nothing back-fills it from `recommendation_feedback`. So
rehydrated cards render unrated. The ratings were never lost (DB intact);
they were simply never read back into the UI on load.

Confirm this is a load-time gap, not a regression of the previous
(query_id, wine_id) fix — that fix is correct within a session; this is the
missing DB→UI hydration path that predates it.

## Fix — read active state from the DB, cache as an accelerator (not the source)
The highlight decision for each card must fall back to
`recommendation_feedback` when the session cache has no entry for
`(user_id, query_id, wine_id)`:

1. New service/authed read in `src/logging_db.py` (or `src/preferences.py`,
   wherever feedback reads live): `get_feedback_ratings(user_id, query_ids)`
   → `{(query_id, wine_id): rating}` for the given turns. Batch the query_id
   list with the existing `_BATCH_SIZE`/`.in_()` pattern (a rehydrated
   history can hold many turns). Swallow exceptions → return `{}` (missing
   highlight is cosmetic; never break the render).
2. On history render, populate the ratings cache from this map ONCE per
   session (guard with a session_state flag like `_feedback_hydrated`, same
   pattern as `_chat_rehydrated`), BEFORE the first card renders — so the
   existing highlight lookup finds the DB-loaded values with zero change to
   the per-card rendering code.
3. The cache stays the fast path for same-session clicks; the DB is the
   source of truth on load. A click still writes through to both (unchanged).

Keep it keyed by `(query_id, wine_id)` throughout — do NOT reintroduce a
wine_id-only lookup (that was the leak we just fixed).

## Scope guard
- Only logged-in users hydrate (anonymous have no rows and no buttons).
- Do not touch the write path, the container key, the profile-fold logic,
  or the `(query_id, wine_id)` keying — only ADD the load-time DB read +
  cache back-fill.
- `resolve_thread_id` / checkpointer untouched — this is pure UI state.

## Tests
1. `get_feedback_ratings`: returns the composite-keyed map for given
   query_ids; batches correctly; DB failure → `{}`, no raise.
2. Hydration back-fill: given a rehydrated message list and a DB map,
   the ratings cache ends up populated for the right (query_id, wine_id)
   pairs; runs once (second call with the flag set is a no-op).
3. Same-wine-different-turn independence still holds after hydration
   (q1→up, q2→down loaded from DB render as up / down respectively — the
   regression guard for the leak we just fixed).

## Verification
1. `pytest` — full suite green + new tests.
2. `git diff --stat` — chat_view.py, logging_db.py (or preferences.py),
   test file(s). No checkpointer/graph/write-path changes.
3. STOP for review — MUST be human-smoke-verified (highlight is invisible
   to mocks).

## Human smoke test (the exact repro)
Logged in, Lyrarakis already has 👍 in turn 1 and 👎 in turn 2 (from the
prior test — the rows are still in the DB).
1. Log out → Log in → the rehydrated history shows Lyrarakis turn-1 card
   GREEN 👍 and turn-2 card RED 👎, exactly as before logout (currently both
   grey — the bug).
2. Plain F5 (no logout) → same: highlights restored from DB, not lost.
3. Other wines with no rating stay grey. No crash, no leak between turns.
