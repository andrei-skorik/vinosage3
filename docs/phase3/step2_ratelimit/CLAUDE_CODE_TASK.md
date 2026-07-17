# TASK: Phase 3, step 2 of 5 — fix the ratelimit.py memory leak

> For Claude Code. Read `CLAUDE.md` first, as always. Reference implementation
> in `docs/phase3/step2_ratelimit/` — apply and adapt; repo wins on drift.

## Problem
`src/ratelimit.py` keeps one `deque` per `session_id` in the module-level
`_windows` dict and **never removes entries**. Every browser session ever seen
adds a key forever. On a long-lived deployment this silently degrades the
instance over time (unbounded memory growth).

## Approved fix (do not re-design)
Lazy periodic sweep, piggybacked on `check_rate_limit`, inside the existing
`_lock`:
- New module constants/state: `_CLEANUP_INTERVAL_S = 300.0`, `_last_cleanup`.
- New helper `_purge_stale_sessions(now)`: runs at most once per interval;
  deletes every session whose deque is empty OR whose **newest** timestamp
  (`q[-1]`) is older than `_WINDOW_S` — such a deque can never influence a
  future decision.
- Called as the first line inside the `with _lock:` block of
  `check_rate_limit`, before `setdefault`.
- Memory bound after fix: `|_windows| <= sessions active in the last
  (_WINDOW_S + _CLEANUP_INTERVAL_S) seconds`.

Explicitly out of scope: no new dependencies, no TTL-dict libraries, no
changes to `get_daily_cost_micros` / `check_cost_cap`, no signature changes.
Rate-limit semantics must be byte-identical (same allow/block decisions,
same `retry_after_s`).

## Files to apply
From `docs/phase3/step2_ratelimit/`:

| Reference file | Action |
|---|---|
| `src/ratelimit.py` | MODIFIED — diff against repo; the change is: the comment block + `_CLEANUP_INTERVAL_S` + `_last_cleanup` + `_purge_stale_sessions()` near the top, and one added line (`_purge_stale_sessions(now)`) inside `check_rate_limit`'s lock. Nothing else changes. |
| `tests/test_ratelimit.py` | NEW — copy as-is (8 tests: behaviour-unchanged ×3, leak-fixed ×3, no-false-eviction ×2). Time is monkeypatched; no sleeps. |

Note: the reference tests were verified on Python 3.12; you fixed a PEP 649
lazy-annotation issue in step 1's tests on Python 3.14 — this test file has no
function-local `Annotated` definitions, so it should be unaffected, but if
3.14 surprises appear, apply the same module-level-import remedy without
changing assertions.

## Verification (run all before stopping for review)
1. `pytest` — full suite green, including the new `tests/test_ratelimit.py`
   and the unchanged `test_pair_with_food.py`.
2. `git diff src/ratelimit.py` — confirm the diff touches ONLY the documented
   locations (no behavioural edits to the window check itself).
3. Summarize the diff and STOP for human review. Do not proceed to the next
   Phase-3 step in the same run.

## Human-only checklist
None — this step needs no secrets, no SQL, no manual smoke test beyond CI.
