# TASK: Phase 3, step 6h — make feedback un-fold the exact inverse of fold (provenance)

> For Claude Code. Bug found in the human's smoke test, inherited from
> Phase 2: toggle-off ("none") removes the wine's grape/style/type from BOTH
> preferred_* and disliked_* buckets unconditionally — but the fold (now
> guarded per §5.4 by 6f) may have added NOTHING. Observed: toggling off a
> 👎 on a wine whose grape+style were manually preferred WIPED
> preferred_grapes and preferred_styles. Un-fold must revert exactly what
> fold did — nothing more.

## Design (approved): delta provenance in the existing `reason` column
`recommendation_feedback.reason` (sql/08, currently unused) stores a JSON
delta of what the fold actually changed for THAT rating, e.g.:
`{"added_disliked_styles": ["Ripe & Rounded"], "removed_disliked_grapes": []}`
No schema change; sql/ stays untouched.

### Rules
1. **Fold (👍 or 👎):** compute the §5.4-guarded delta as 6f already does;
   apply it; serialize the applied delta to `reason` on the same feedback
   row write. Empty delta → `reason` stores `{}`.
2. **Toggle-off ("none"):** read the row's `reason`, revert exactly that
   delta (set-difference for additions, re-add for removals), THEN delete
   the row (delete_feedback already does the deletion). Missing/legacy/
   unparseable reason → revert NOTHING (safe default: profile untouched;
   the wine-id exclusion lift via row deletion is the primary effect).
3. **Rating flip (down→up or up→down):** first revert the outgoing rating's
   stored delta, then apply+record the new rating's fold. Net effect: the
   profile always reflects at most ONE active fold per (user, wine, turn).
4. All of it stays best-effort/idempotent/swallow-failures, per convention.

### Both layers
`src/preferences.py::fold_feedback` (DB truth) and
`src/ui/chat_view.py::_fold_cache` (instant sidebar mirror) must implement
identical semantics. Strongly consider having the toggle path consume
fold_feedback's returned updated profile for the `_pending_profile_update`
staging instead of duplicating delta math in the cache — if you unify,
document it; if not, add a parity test.

## Tests (extend the 6f test file or add tests/test_fold_provenance.py)
1. THE INCIDENT: manual preferred grape+style; 👎 a matching wine (fold adds
   nothing, reason == {}); toggle off → preferred arrays UNTOUCHED,
   feedback row gone.
2. 👎 a wine whose style is not preferred (fold adds disliked style, reason
   records it); toggle off → that disliked style removed, everything else
   untouched.
3. Manually-set disliked value + 👎 fold that would add the same value
   (set-union no-op) → reason records NO addition → toggle-off does NOT
   remove the manual dislike.
4. Flip down→up: down's delta reverted, up's fold applied and recorded.
5. Legacy row with reason NULL → toggle-off reverts nothing, deletes row.
6. Sidebar-cache parity on cases 1–2 (or the unification note per above).

## Verification
1. `pytest` — full suite green; 6f's tests must still pass unchanged (fold
   math itself is untouched — only recording + reverting is added).
2. `git diff sql/` empty; `git diff --stat` — preferences.py, chat_view.py,
   logging_db.py (if the reason write lives there), tests, handoff note.
3. Handoff: 6h entry — un-fold was not the inverse of fold (Phase-2 design
   "remove from both buckets"), destroyed manual preferences; fixed via
   reason-column delta provenance; legacy rows revert nothing by design.
4. STOP for review.

## Human notes (include in report)
- Before re-testing, the human must restore the polluted profile: re-add
  Assyrtiko to Preferred grapes and Crisp & Zesty to Preferred styles;
  decide Ripe & Rounded in Disliked styles consciously (it is a legitimate
  fold from the still-active White Ash 👎 — leaving it is correct).
- Step-7 smoke then reruns cleanly: toggle Skouras's 👎 off → re-ask →
  Skouras returns; profile arrays unchanged throughout.
