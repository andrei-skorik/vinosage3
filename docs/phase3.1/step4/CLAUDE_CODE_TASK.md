# TASK: Phase 4, step 4 of 4 — login persistence across browser refresh (F5)

> For Claude Code. Read `CLAUDE.md` and the "Known accepted gaps" §3 in
> `docs/PHASE3_HANDOFF.md` first. This is the auth-sensitive task of the
> batch — run it LAST, alone, and stop for review. Do not touch RLS, the
> age gate, or `config._require` (do-not-touch list).

## Problem
`st.session_state.auth` (set in `src/ui/auth_view.py::_set_authed_session`)
dies on F5, so the user is logged out even though their durable chat (step
9's checkpointer) survives and reloads once they log back in. Pre-existing
gap; now the most visible UX seam in the product.

## Approved design — refresh token in a browser cookie
- **Mechanism:** a cookie-manager Streamlit component (e.g.
  `extra-streamlit-components` CookieManager or `streamlit-cookies-controller`
  — pick the one that is maintained and works on the pinned Streamlit;
  justify the choice in the report, pin it in requirements, freeze exact
  version after install). Do NOT use `st.query_params` for the token —
  tokens in URLs leak via history/screenshots/referrers.
- **What's stored:** the Supabase **refresh_token** only (never the access
  token, never the password), expiry ~30 days, `SameSite=Lax`, `path=/`.
- **Security note for the handoff (required):** a component cookie is
  JS-readable (not httpOnly) — accepted for this project; strictly better
  than query params; the token is single-use (see rotation below).

## Flows
1. **Login / register success** (`_set_authed_session` call sites): also
   write the refresh_token cookie.
2. **App start, not authed:** read the cookie → if present, attempt
   `supabase.auth.refresh_session(<token>)` (anon client, the same one
   auth_view uses). Success → rebuild session via the existing
   `_set_authed_session` (reuse it — do not duplicate its logic) → **write
   the NEW refresh_token back to the cookie** (Supabase rotates refresh
   tokens: the old one is consumed; skipping the write-back logs the user
   out on the SECOND refresh — the classic bug here, test for it). Failure
   (expired/revoked/garbage) → delete the cookie, stay anonymous, no error
   surfaced (swallow + log).
3. **Logout:** delete the cookie (alongside the existing sign-out).
4. **"Forget everything about me":** delete the cookie too (it's part of
   "everything").
5. **Ordering in `app.py::main()`:** cookie-restore MUST run before
   `resolve_thread_id` / chat rehydration, so the durable chat loads in the
   same run the login is restored.
6. **Component-mount quirk (handle explicitly):** cookie components return
   nothing on the very first script run (the frontend component mounts
   async). Standard pattern: instantiate the manager at the top of main();
   if cookies aren't ready yet and restore hasn't been attempted, allow ONE
   guarded rerun (session-state flag) — never an unguarded rerun loop.

## Structure
New `src/auth_persistence.py` (save_token / read_token / clear_token /
try_restore_session), so `app.py` gains ~5 lines and auth_view gains the
write/clear calls. All I/O swallows exceptions — a cookie failure must
never break login or chat.

## Tests (logic-level; the component itself is smoke-tested by the human)
Monkeypatch the cookie manager + supabase auth client:
1. Valid token → session restored via `_set_authed_session`, NEW rotated
   token written back (assert the write-back — this is the critical one).
2. Invalid/expired token → cookie cleared, no exception, stays anonymous.
3. Logout and Forget-me paths clear the cookie.
4. No cookie → no auth calls at all (fast path).

## Verification
1. `pytest` — full suite green; `test_checkpointer.py` untouched and green
   (thread identity unchanged — restore happens BEFORE thread resolution,
   it doesn't alter `resolve_thread_id`).
2. `git diff --stat` — auth_persistence.py (new), app.py, auth_view.py,
   sidebar.py (forget-me), requirements.txt, tests, handoff.
3. Handoff: known-gap §3 marked resolved, with the security note and the
   rotation caveat documented. STOP for review.

## Human smoke test (the decisive one — component behavior is browser-only)
1. Log in → send a message → **F5** → still logged in AND chat restored in
   one go. → **F5 again** (rotation check — must survive a SECOND refresh).
2. Log out → F5 → still logged out.
3. Log in → "Forget everything about me" → F5 → logged out, no profile, no
   chat.
4. Private window sanity: anonymous flow unchanged (no cookie written).
5. Close browser fully, reopen → still logged in (cookie, not session
   cookie).
