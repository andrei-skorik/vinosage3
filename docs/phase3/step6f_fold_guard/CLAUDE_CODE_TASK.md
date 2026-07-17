# TASK: Phase 3, step 6f — enforce the §5.4 fold guard ("positive preference wins")

> For Claude Code. Bug found in the human's smoke test: a 👎 on two Assyrtiko
> wines added "Assyrtiko" to disliked_grapes even though "Assyrtiko" was in
> preferred_grapes at fold time. SPEC §5.4 is explicit: "👎 → add that wine's
> grape/style to the corresponding disliked_* array (set-union) ONLY IF it
> isn't in the matching preferred_* array (explicit positive preference wins
> over a single 👎)." The style fold behaved correctly in the same incident
> (Crisp & Zesty was NOT preferred → legitimately disliked), so the guard is
> missing or broken specifically somewhere in the grape/type dimension logic
> — or the implementation "moves" values from preferred to disliked, which
> is equally non-spec.

## Investigate first, then fix
1. Read `src/preferences.py::fold_feedback` — determine which it is:
   (a) the preferred-membership guard is missing/inverted for some
   dimensions, or (b) the fold deliberately removes the value from
   preferred_* and adds it to disliked_* ("move" semantics). Report which.
2. Read `src/ui/chat_view.py::_fold_cache` — it MIRRORS fold logic locally
   for the instant sidebar update, so whatever is wrong in fold_feedback is
   almost certainly duplicated there. Both must be fixed identically.

## Required behavior (exactly §5.4, no interpretation)
- 👎 on a wine: for each of type/grape/style — add the wine's value to
  disliked_* (set-union) ONLY IF the value is NOT currently in the matching
  preferred_* array. Never remove anything from preferred_* on a 👎.
- 👍 on a wine: add type/grape/style to preferred_* (set-union). Per the
  same precedence logic, a 👍'd value should also be REMOVED from the
  matching disliked_* if present (a fresh explicit positive beats a stored
  dislike) — check what the current code does here; if it doesn't remove,
  add it, and note it in the report as a §5.4-consistency extension.
- Toggle-off (rating "none"): unchanged (row deletion; no profile edits
  beyond what the existing code already does — verify and report).
- Idempotent, best-effort, swallow-failures — all as before.

## Tests
Extend the existing preferences-fold test file (Phase 2 created one — find
it) or add `tests/test_fold_guard.py`:
1. 👎 on a wine whose grape IS preferred → disliked_grapes unchanged,
   preferred_grapes unchanged; the wine's style (not preferred) IS added to
   disliked_styles. (This is the exact observed incident.)
2. 👎 on a wine with no preferred overlap → all three dimensions folded into
   disliked_* as before.
3. 👍 on a wine whose grape is currently disliked → grape moves out of
   disliked_grapes and into preferred_grapes.
4. Same assertions against `_fold_cache` (the sidebar mirror) — the two
   implementations must not diverge; if practical, add a small parity test
   that runs both on the same inputs and compares resulting profiles.

## Data cleanup note for the human (put in your report)
The smoke-test profile is now polluted (Assyrtiko in disliked_grapes,
possibly missing from preferred). The human should manually fix it in the
sidebar (remove Assyrtiko from Disliked grapes, re-add to Preferred grapes
if gone, decide on Crisp & Zesty consciously) BEFORE re-running the 6e smoke
scenario — otherwise disliked-Assyrtiko (a hard, never-relaxed constraint)
forces no_catalog_match and muddies the test.

## Verification
1. `pytest` — full suite green; `test_pair_with_food.py` unchanged.
2. `git diff --stat` — only preferences.py, chat_view.py, test file(s),
   handoff note.
3. One handoff line: 6f — fold guard enforced per §5.4 (+ what you found in
   the investigate step).
4. STOP for review.
