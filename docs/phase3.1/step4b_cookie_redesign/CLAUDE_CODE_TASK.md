# TASK: Phase 4, step 4b — fix login persistence (cookie never saved)

> For Claude Code. The step-4 human smoke test FAILED at the first check:
> no cookie is ever written (verified in Chrome and Edge DevTools; no
> server-side errors — the failure is browser-side). Root cause and
> redesign below. This REPLACES the extra-streamlit-components approach;
> do not patch around it.

## Root cause (confirm in code, then state it in the report)
`stx.CookieManager.set()` is a browser COMPONENT: its JS runs only if the
component's HTML reaches the browser in a completed script run. The login
success path calls `save_token()` and then (verify) `st.rerun()` in the
same run — the run is aborted, the component never renders, the cookie is
never written. Same failure class as the Phase-2 sidebar bug that led to
the `_pending_profile_update` staging pattern. Additionally, stx's `get()`
spawns a `st.components.v1.html` component per read — the ×15-per-rerun
deprecation spam in the logs ("will be removed after 2026-06-01") — i.e.
the library sits on an API Streamlit is removing.

## Approved redesign
**Read natively, write via staged one-shot JS.**

### 1. READ — `st.context.cookies` (no component at all)
`read_token()` becomes `st.context.cookies.get(_COOKIE_NAME)`. Native,
synchronous, available on the VERY FIRST run (cookies arrive in the HTTP
request headers). The entire component-mount quirk, its guarded rerun, and
its session flag are DELETED.

### 2. WRITE / CLEAR — tiny JS snippet rendered during a normal run
```python
def _emit_cookie_js(value: str | None) -> None:
    """Render a zero-height component whose JS sets or deletes the cookie.
    Must run to the END of a script run (never call st.rerun() in the same
    run after this) — otherwise the JS never reaches the browser, which is
    exactly the bug this file previously had."""
    if value is None:
        js = f"document.cookie = '{_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Lax';"
    else:
        js = (f"document.cookie = '{_COOKIE_NAME}={value}; "
              f"Max-Age={60*60*24*30}; path=/; SameSite=Lax';")
    st.components.v1.html(f"<script>{js}</script>", height=0)
```
Use whatever non-deprecated raw-HTML API the pinned Streamlit offers; if
only `components.v1.html` exists, accept the single deprecation warning on
the rare write actions (vs ×15 per rerun before) and note it. Escape/
validate the token value (it's ours, but belt-and-braces: reject values
with `'`/`;`/whitespace).

### 3. Staging around reruns (the project's own pattern)
Login/logout/forget handlers rerun immediately, so they must not emit JS
directly. They stage instead:
- login/register success → `st.session_state["_pending_cookie"] = token`
- logout / forget-me → `st.session_state["_pending_cookie"] = ""` (clear
  sentinel)
At the TOP of `main()` (right after page config, before the age gate):
pop `_pending_cookie` if present and `_emit_cookie_js(token or None)`.
The emit then survives to the end of that run.

### 4. Restore flow (unchanged logic, simpler code)
Not authed + `read_token()` returns a token → `refresh_session(token)` →
success: `_set_authed_session(...)` (reuse, as before) AND emit the ROTATED
token via `_emit_cookie_js(new_token)` **directly in this same run** (no
rerun needed here — restore happens during a normal render). Failure →
emit the clear JS, stay anonymous, swallow+log. Keep restore ABOVE the age
gate's `st.stop()` and above `resolve_thread_id`, as before.

### 5. Dependency
Remove `extra-streamlit-components` from requirements (nothing else uses
it — verify with grep). The deprecation spam disappears with it.

## Tests — adapt `tests/test_auth_persistence.py`
Same seven behaviors, new seams: monkeypatch `st.context.cookies` for reads
and capture `_emit_cookie_js` calls for writes. Keep the rotation
write-back assertion (now: emit called with the NEW token during restore).
Add one new test: staged `_pending_cookie` set by the login handler is
consumed and emitted on the next run's top-of-main hook.

## Verification
1. `pytest` — full suite green (count may shift slightly with the test
   rework; report the delta).
2. Grep: `extra-streamlit-components` appears nowhere; `CookieManager`
   gone; exactly one `_emit_cookie_js` definition.
3. Handoff: step-4 section amended — root cause of the failed smoke, the
   redesign, and one backlog line for the unrelated log finding:
   "checkpointer pickles src.rag.RetrievedWine into state (msgpack
   deprecation warning); future langgraph will block it — consider
   serializing rag_context to plain dicts before it enters AgentState."
4. STOP for review. No commit.

## Human smoke test (unchanged — the decisive one)
1. Log in → message → F5 → logged in AND chat restored → **F5 again**
   (rotation) → still logged in. DevTools: the cookie is now visible,
   SameSite=Lax, and its VALUE CHANGES between the two refreshes (rotation
   proof).
2. Log out → F5 → logged out; cookie gone from DevTools.
3. Forget everything about me → F5 → logged out, no profile, no chat.
4. Private window: anonymous, no cookie written.
5. Full browser restart → still logged in.
