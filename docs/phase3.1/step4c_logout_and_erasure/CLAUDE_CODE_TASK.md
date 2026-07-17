# TASK: Phase 4, step 4c — logout session hygiene + Forget-me history erasure

> For Claude Code. Two adjacent defects surfaced by the (otherwise passing)
> step-4b smoke test. Neither touches the cookie mechanics — those are
> confirmed working, do not modify `_emit_cookie_js`/read paths.

## Defect A — logout leaves the previous user's chat on screen
Privacy issue on shared machines: after "Log out", `st.session_state.auth`
and the cookie are cleared, but `messages`, feedback-rating caches, profile
caches, metrics etc. stay rendered until a manual refresh. Required
behavior: logout immediately resets to the pristine anonymous first-visit
state (age gate included — per the product owner's explicit call).

### Fix — `reset_to_anonymous()` (explicit-list reset, NOT a blanket clear)
New helper (place it where auth_view and sidebar can both import it, e.g.
`src/ui/session_reset.py` or alongside auth_persistence):
- **CLEARS** (delete keys if present): `messages`, `auth`, the age-gate flag
  (find its actual key), `_chat_rehydrated`, profile caches
  (`_prefs_cache`, `_pending_profile_update`, taste-profile widget keys),
  feedback-rating caches, session metrics/token counters, voice keys
  (`_last_voice_digest`, `_voice_widget_gen`), any queued prompt.
  Enumerate what you actually find in the codebase — grep session_state
  writes — and list the final set in the report.
- **GENERATES a fresh `session_id`** (new anonymous rate-limit window and a
  new unreachable `anon:*` thread — consistent with anonymity by
  construction).
- **PRESERVES (the trap — get this wrong and logout self-defeats):**
  `_pending_cookie` — the logout handler has JUST staged the cookie
  deletion; wiping the stage means the cookie survives and the user
  auto-logs back in on the next F5. Also preserve `locale` (language choice
  is a device preference, not identity) and `_catalog_options_cache`
  (non-personal, expensive to rebuild).
- Ends with `st.rerun()`.

Call it from BOTH the logout handler and the forget-me handler (after their
existing deletions/staging). A blanket `st.session_state.clear()` is
explicitly forbidden — document why in the helper's docstring (the
`_pending_cookie` trap above).

## Defect B — "Forget everything about me" leaves My conversations intact
The history feature reads `query_logs` by `user_id`; forget-me never
touches those rows, so the full conversation history survives (and reloads
even after re-login).

### Approved semantics — anonymize + scrub, do NOT hard-delete
Hard-deleting `query_logs` would cascade into `token_usage`, silently
shrinking `get_daily_cost_micros()` — i.e. forget-me would RESET a user's
contribution to the global €1/day cap (spend → forget → spend again).
Instead, new service-role helper `erase_user_history(user_id) -> bool`
(in `src/logging_db.py`, next to its siblings):
```
update query_logs
   set user_id = NULL,
       user_query = '[erased]',
       final_answer = '[erased]'
 where user_id = :uid
```
(adapt column names to the real schema — check 01/05 sql files read-only;
if `query_logs` lacks `final_answer`, scrub whatever content columns it
has). Identity unlinked, content erased, numeric cost rows intact and still
counted by the cap. Returns bool; swallow exceptions but surface `False` so
the forget-me UI can show the existing generic error instead of a false
success. Also clear the sidebar's loaded-history session cache (covered by
Defect A's reset, but verify the key is in the list).

Note for the handoff (GDPR honesty): `tool_call_logs`/`token_usage` retain
non-personal operational rows linked to now-anonymous query ids;
`security_events.user_id` is already `ON DELETE SET NULL`-style — verify
whether forget-me should also null it explicitly (it references
auth.users, and the auth USER isn't deleted by forget-me — so yes, add
`security_events` user_id nulling for the same user, content stays for
security audit; state this trade-off in the handoff).

## Tests
1. `reset_to_anonymous()` on a fake session dict: clears the enumerated
   keys, PRESERVES `_pending_cookie` + `locale` + catalog cache, rotates
   `session_id`.
2. The self-defeat regression: stage a cookie-clear, run the reset, assert
   the stage survives.
3. `erase_user_history`: issues the anonymize+scrub update for exactly the
   given user; DB failure → returns False, never raises.
4. Forget-me handler wiring: calls preferences-delete, thread-delete,
   feedback-delete, cookie-clear, history-erase, AND the session reset
   (monkeypatched recorders; order not gated except reset last).

## Verification
1. `pytest` — full suite green; report the delta.
2. `git diff sql/` — EMPTY (this is an UPDATE via service client, no schema
   change; sql/01–05 read-only as always).
3. Handoff: both findings documented under "Phase 4, step 4c" with the
   cost-cap rationale for anonymize-over-delete; GDPR note per above.
4. STOP for review.

## Human smoke test
1. Log in → chat → Log out → IMMEDIATELY: age gate shown, no chat, no
   profile visible; F5 → still logged out (the `_pending_cookie` trap
   check); DevTools: cookie gone.
2. Log in as the same user → chat history from BEFORE the logout is still
   there (logout must not erase server-side history — only forget-me does).
3. "Forget everything about me" → confirm → immediate pristine state; log
   back in → My conversations EMPTY; profile empty; Supabase spot-check:
   the user's old `query_logs` rows have `user_id NULL` and
   `user_query = '[erased]'`; today's cost total in the admin analytics
   unchanged by the erasure.
