"""Reset back to the pristine anonymous first-visit state (Phase 4, step 4c).

Called by BOTH the logout handler (`src/ui/auth_view.py`) and the "Forget
everything about me" handler (`src/ui/sidebar.py`). On a shared machine,
leaving the previous user's chat, profile, and metrics on screen after
either action is a privacy leak — the product owner's explicit call is that
a signed-out visitor should see exactly what a brand-new visitor sees,
age gate included.

**Explicit-list clear, never `st.session_state.clear()`.** A blanket clear
would also wipe two keys that must survive this exact call, both staged by
the caller moments earlier:

1. `_pending_cookie` — the caller (logout / forget-me) just staged a cookie
   write/clear in this key (see `src/auth_persistence.py`). Wiping it here
   means `emit_pending_cookie()` never sees it on the next run, the JS
   delete never fires, and the real browser cookie survives — the user
   would appear logged out in THIS tab but auto-restore on the next F5.

2. `_auth_restore_done` — arguably the sharper trap. It is not merely left
   alone; it is force-set to `True` below. Streamlit's own docs describe
   `st.context.cookies` as reflecting only "the initial request" — i.e. it
   stays frozen at whatever value the browser sent when this tab's session
   first opened, for the rest of that tab's life, regardless of any
   `document.cookie` write we issue via JS in the meantime. If a user never
   went through `try_restore_session()` this session (e.g. they signed in
   directly via the login form, cookie or not), `_auth_restore_done` may
   still be unset. Leaving it unset would let `try_restore_session()` fire
   again on the very next rerun and — using that stale, frozen cookie
   snapshot — restore the OLD session right back. For logout this would
   merely fail (Supabase's own `sign_out()` already revoked the refresh
   token server-side), but forget-me never calls `sign_out()` — the
   Supabase session stays fully valid — so without this the "Forget
   everything about me" reset would be silently undone in the same click.
"""
from __future__ import annotations

import uuid

import streamlit as st

# Cleared on logout / forget-me. NOT a blanket st.session_state.clear() —
# see module docstring for the two keys that must survive instead.
_KEYS_TO_CLEAR = (
    "messages",
    "auth",
    "age_confirmed",            # age-gate flag — reset shows the gate again
    "_chat_rehydrated",
    # profile caches
    "_prefs_cache",
    "_pending_profile_update",
    "pref_expertise", "pref_types", "pref_grapes", "pref_countries",
    "pref_styles", "pref_characteristics",
    "disliked_types", "disliked_grapes", "disliked_styles",
    "pref_min_price", "pref_max_price",
    "_show_avatar_uploader", "_last_avatar_upload", "avatar_uploader",
    "_history_cache",           # "My conversations" (Defect B)
    # feedback-rating caches
    "wine_ratings", "wine_ratings_loaded",
    # session metrics / token counters
    "session_tokens_in", "session_tokens_out", "session_cost_micros",
    "last_latency_ms",
    # voice keys
    "_last_voice_digest", "_voice_widget_gen",
    # queued prompt
    "queued_prompt",
)


def reset_to_anonymous() -> None:
    """Clear the enumerated keys, rotate session_id, and rerun.

    Every cleared key that also has an entry in app.py's `_DEFAULTS` is
    re-initialised to its pristine default on the very next run by that
    module-level loop (`if _k not in st.session_state: ...`, which runs on
    every rerun since the whole script re-executes top to bottom) — this
    function only needs to remove the stale value, not know what the fresh
    one should be. Keys with no `_DEFAULTS` entry (profile/feedback/voice
    caches) are simply absent afterward, which every reader already treats
    as "nothing cached yet."

    PRESERVED (deliberately — see module docstring for why each matters):
    - `_pending_cookie`, `_auth_restore_done` (force-set to True, not just
      left alone).
    - `locale` — a device/language preference, not identity.
    - `_catalog_options_cache` — non-personal, expensive to rebuild.
    - `_welcome_picks_*` — non-personal cosmetic cache (random example
      prompts); harmless to keep, and locale-scoped rather than identity-scoped.
    """
    for key in _KEYS_TO_CLEAR:
        st.session_state.pop(key, None)

    st.session_state["session_id"] = str(uuid.uuid4())  # fresh anon rate-limit window + unreachable anon:* thread
    st.session_state["_auth_restore_done"] = True  # see module docstring — force, don't just "leave alone"

    st.rerun()
