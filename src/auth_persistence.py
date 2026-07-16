"""Login persistence across browser refresh via a cookie (Phase 4, step 4/4b).

Closes known-gap §3 (`docs/PHASE3_HANDOFF.md`): `st.session_state.auth` dies
on F5 even though the durable chat (step 9's checkpointer) survives.

**Redesign history (step 4b):** the original step-4 implementation used a
third-party browser-COMPONENT-based cookie manager. The human smoke test
failed at the first check — no cookie was ever written. Root cause: the
component's write only runs its JS if the component's HTML actually reaches
the browser in a completed script run, but the login success path called
the write and then `st.rerun()` in the SAME run (`src/ui/auth_view.py`,
login/register/logout handlers) — the run is aborted before the component
ever renders, so the write is silently lost. Same failure class as the
Phase-2 sidebar bug that led to the `_pending_profile_update` staging
pattern. The component's read side also spun up one `st.components.v1.html`
call per read — ×15-per-rerun deprecation spam for an API Streamlit is
removing. Both problems are avoided below: reads no longer use a component
at all, and writes are staged around every rerun instead of racing it.

**Current design — read natively, write via staged one-shot JS:**
- **Read:** `st.context.cookies` — native, synchronous, populated on the
  VERY FIRST script run (cookies arrive in the HTTP request headers, no
  component round-trip). This deletes the entire component-mount quirk that
  the step-4 version had to work around with a guarded rerun.
- **Write/clear:** a zero-height `st.components.v1.html` snippet
  (`_emit_cookie_js`) that sets `document.cookie` directly. It only works if
  it runs to the END of a script run — so any caller that reruns immediately
  afterward (login, register, logout, forget-me — all of them do) must
  STAGE the value in `st.session_state["_pending_cookie"]` instead of
  emitting inline; `emit_pending_cookie()`, called at the very top of
  `app.py::main()`, consumes the stage and does the actual emit on the
  NEXT run, which then survives to the end of that run untouched by any
  further rerun. `try_restore_session` is the one exception: it never
  reruns itself, so it emits the rotated token directly, in the same run.

**What's stored:** the Supabase **refresh_token** only (never the access
token, never the password), `SameSite=Lax`, `path=/`, ~30-day max age.
`st.query_params` was rejected: tokens in URLs leak via browser history,
screenshots, and Referer headers.

**Security note:** this cookie is JS-readable (not httpOnly) — accepted for
this project; still strictly better than a query-param token. The exposure
window is bounded: Supabase rotates the refresh_token on every
`refresh_session` call, so a copy of a stale cookie value stops working the
moment the legitimate client uses it next. That rotation is exactly why
`try_restore_session` emits the NEW token after every successful restore —
skipping that emit is the classic bug (logs the user out on the SECOND
refresh), pinned down by this module's tests.

All I/O here swallows exceptions — a cookie or auth failure must never
break login or chat (same convention as logging_db.py / checkpointer.py).
"""
from __future__ import annotations

import logging
import re

import streamlit as st

log = logging.getLogger(__name__)

_COOKIE_NAME = "vinosage_refresh_token"
_COOKIE_MAX_AGE_S = 30 * 24 * 60 * 60  # ~30 days

# Belt-and-braces: the token is ours (a Supabase-issued JWT), but reject
# anything that could break out of the single-quoted JS string literal below.
_UNSAFE_TOKEN_RE = re.compile(r"['\";\s]")


def read_token() -> str | None:
    """Current cookie value, if any. Native + synchronous — no component,
    no mount-timing quirk, available on the very first script run."""
    try:
        return st.context.cookies.get(_COOKIE_NAME)
    except Exception as exc:
        log.warning("read_token failed: %s", exc)
        return None


def _emit_cookie_js(value: str | None) -> None:
    """Render a zero-height component whose JS sets or deletes the cookie.

    Must run to the END of a script run — never call st.rerun() in the same
    run after this, or the JS never reaches the browser (the exact bug this
    redesign fixes). Callers that rerun immediately afterward must stage via
    save_token()/clear_token() instead; emit_pending_cookie() does the
    actual emit on the following run.
    """
    if value is not None and _UNSAFE_TOKEN_RE.search(value):
        log.warning("_emit_cookie_js: rejected a token containing unsafe characters")
        return
    try:
        if value is None:
            js = f"document.cookie = '{_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Lax';"
        else:
            js = (
                f"document.cookie = '{_COOKIE_NAME}={value}; "
                f"Max-Age={_COOKIE_MAX_AGE_S}; path=/; SameSite=Lax';"
            )
        st.components.v1.html(f"<script>{js}</script>", height=0)
    except Exception as exc:
        log.warning("_emit_cookie_js failed: %s", exc)


def save_token(refresh_token: str) -> None:
    """Stage a refresh_token write, consumed by emit_pending_cookie() on the
    NEXT script run. Login/register success calls st.rerun() immediately
    afterward, so writing inline here would be lost — see module docstring.
    """
    st.session_state["_pending_cookie"] = refresh_token


def clear_token() -> None:
    """Stage cookie deletion (logout / forget-me — both rerun immediately
    afterward, same reasoning as save_token)."""
    st.session_state["_pending_cookie"] = ""  # empty-string clear sentinel


def emit_pending_cookie() -> None:
    """Call once, at the very top of app.py::main(), before anything else.

    Consumes any write/clear staged by the PREVIOUS run's login/register/
    logout/forget-me action and actually emits the JS for it in THIS run —
    which, having just started, is guaranteed to run to completion unless
    something later reruns it again (nothing between here and the page
    finishing render does, by design).
    """
    if "_pending_cookie" not in st.session_state:
        return
    pending = st.session_state.pop("_pending_cookie")
    _emit_cookie_js(pending or None)


def try_restore_session() -> None:
    """Call once, near the top of app.py::main() (after emit_pending_cookie),
    BEFORE resolve_thread_id / chat rehydration — so a restored login's
    durable chat loads in the same run the login itself is restored.

    No-op (fast path, zero auth calls) if already authed this session, if a
    restore attempt already happened this session, or if there's no cookie.
    Never calls st.rerun() itself, so a successful restore's rotated-token
    emit happens directly, in this same run.
    """
    if st.session_state.get("auth") is not None:
        return
    if st.session_state.get("_auth_restore_done"):
        return
    st.session_state["_auth_restore_done"] = True  # never retry again this session

    token = read_token()
    if not token:
        return  # genuinely no cookie — stay anonymous, no auth calls made

    from src.auth import refresh_session
    from src.ui.auth_view import _set_authed_session  # reuse — do not duplicate its logic

    result = refresh_session(token)
    if not result.ok or result.session is None:
        _emit_cookie_js(None)  # expired/revoked/garbage — clear, stay anonymous
        return

    _set_authed_session(result.session)
    # Supabase rotates the refresh_token on every use — emit the NEW one
    # directly (no rerun happens in this flow, so the emit reaches the
    # browser normally). Skipping this is what logs the user out on the
    # SECOND refresh.
    _emit_cookie_js(result.session.refresh_token)
