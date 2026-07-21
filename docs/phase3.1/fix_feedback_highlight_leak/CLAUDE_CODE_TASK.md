# TASK: fix feedback-highlight leak across turns (per-turn active state)

> For Claude Code. Follow-up to the wine-card duplicate-key fix. That fix
> corrected the container KEY and the DB WRITE scoping, but the button's
> ACTIVE-STATE (green/red highlight) READ is still scoped by wine_id only.
> Confirmed on the live logged-in UI: 👍 on a wine in turn 1 also lights up
> the SAME wine's card in a later turn (different query_id) — a visual lie,
> and a state/data desync if the user then clicks the 2nd card.

## Root cause (verify in `src/ui/chat_view.py::render_feedback_buttons`)
The write path and the button keys already scope by `(query_id, wine_id)`
(that's why the DB rows are correct). But the code that decides whether a
button renders in its ACTIVE (highlighted) style — reading the current
rating to pick the CSS class / button type — keys the lookup by `wine_id`
alone. So every card for that wine, across all turns, reads the same single
rating and highlights identically. Find that lookup (likely a
`st.session_state` ratings cache or a `_load_feedback_state(...)` /
`get_feedback(...)` call keyed by wine_id) and confirm.

## Fix
Scope the active-state read by `(query_id, wine_id)`, exactly like the write
and the button keys already are. Concretely:
- If the highlight reads from a session_state ratings dict, its keys must be
  `f"{query_id}:{wine_id}"` (or a nested `{query_id: {wine_id: rating}}`) —
  both where it's READ (highlight decision) and WRITE (the `_toggle_feedback`
  / `_fold_cache` path that updates the cache after a click). They must use
  the identical composite key or the desync just moves.
- If it reads from the DB per render, the query must filter on BOTH
  `query_id` AND `wine_id` (the `recommendation_feedback` unique key is
  `(user_id, query_id, wine_id)` — a wine_id-only read returns whichever row
  Postgres happens to order first, hence the leak).

Do NOT change the write scoping (already correct) or the container key
(already fixed). Only the active-state read (and its mirror cache write, if
one exists) needs the query_id added.

## Grep for other wine_id-only scoping in the same file
While here, grep `render_feedback_buttons` and its helpers for any other
`wine_id`-keyed lookup that should be `(query_id, wine_id)` — toggle-off
handling, the `_fold_cache` staging, the "already rated?" check. Report any
found; fix the ones that govern per-card state, leave profile-fold logic
(which is legitimately wine-level, not card-level) alone. State that
distinction in the report.

## Tests
`render_feedback_buttons` is Streamlit-bound, so test the state layer:
1. Same wine_id under two different query_ids: setting rating on
   (q1, wine) leaves (q2, wine) unrated — the exact leak, at the
   cache/lookup level.
2. Toggling (q1, wine) does not alter (q2, wine).
3. The composite key round-trips (write then read returns what was written
   for that query_id, not a sibling turn's).
If a small pure helper must be extracted from `render_feedback_buttons` to
make the state layer testable (as was done for `_toggle_feedback` earlier),
do the minimal extraction and describe it.

## Verification
1. `pytest` — full suite green + the new state tests.
2. `git diff --stat` — only `chat_view.py` + the test file.
3. STOP for review. This one MUST be human-smoke-verified (logged-in,
   the mock tests can't see the highlight): the exact failing case below.

## Human smoke test (the exact repro)
Profile: only Assyrtiko preferred, feedback table cleared, logged in.
1. "Recommend me something for tonight" twice in a row (same wines both
   turns — the repro from the duplicate-key fix).
2. 👍 Lyrarakis in the FIRST card → the second turn's Lyrarakis card must
   STAY unrated (grey). Before this fix it goes green too.
3. Now 👎 that same Lyrarakis in the SECOND card → first card stays 👍,
   second shows 👎 — independent per-turn state, no desync, and the app
   doesn't crash (duplicate-key fix still holds).
