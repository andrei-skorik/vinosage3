"""Age gate + login/register forms + profile widget (avatar upload, logout).

Auth is optional — anonymous users can chat freely after confirming the age
gate. Registering only unlocks the avatar personalisation feature; it does
not gate any catalog/chat functionality by itself.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import streamlit as st

from src.auth import (
    AuthSession,
    create_profile,
    default_avatar_url,
    get_profile,
    get_query_history,
    sign_in,
    sign_out,
    sign_up,
    upload_avatar,
)

AVATAR_MAX_UPLOAD_MB = 2
from src.i18n import t

_HISTORY_ANSWER_PREVIEW = 400  # chars shown before truncating a past answer


def is_age_gate_passed() -> bool:
    auth = st.session_state.get("auth")
    if auth and auth.get("is_adult"):
        return True
    return bool(st.session_state.get("age_confirmed"))


def render_age_gate(locale: str) -> None:
    """Blocking screen — must be passed before any chat functionality renders."""
    st.markdown(f"## {t('age_gate_title', locale)}")
    st.markdown(t("age_gate_body", locale))
    col1, col2 = st.columns(2)
    if col1.button(t("age_gate_yes", locale), use_container_width=True, type="primary", key="age_yes"):
        st.session_state.age_confirmed = True
        st.rerun()
    if col2.button(t("age_gate_no", locale), use_container_width=True, key="age_no"):
        st.error(t("age_gate_blocked", locale))


def _set_authed_session(
    session: AuthSession,
    is_adult_hint: bool | None = None,
    known_profile: dict[str, Any] | None = None,
) -> None:
    """known_profile skips the get_profile() round-trip when the caller already
    knows the values (e.g. right after registration, where we just inserted
    them ourselves — re-fetching what we wrote a moment ago is pure latency)."""
    if known_profile is not None:
        profile = known_profile
    else:
        profile = get_profile(session.access_token, session.refresh_token, session.user_id)
    st.session_state.auth = {
        "user_id":       session.user_id,
        "email":         session.email,
        "access_token":  session.access_token,
        "refresh_token": session.refresh_token,
        "is_adult":      (profile.get("is_adult") if profile else is_adult_hint) or False,
        "avatar_url":    profile.get("avatar_url") if profile else None,
    }
    # A confirmed-adult login satisfies the age gate too — no need to ask twice.
    if st.session_state.auth["is_adult"]:
        st.session_state.age_confirmed = True


def render_auth_forms(locale: str) -> None:
    """Login / register tabs — shown in the sidebar when no one is logged in."""
    tab_login, tab_register = st.tabs([t("login_tab", locale), t("register_tab", locale)])

    with tab_login:
        with st.form("login_form", border=False):
            email = st.text_input(
                t("email_label", locale), key="login_email", autocomplete="username"
            )
            # autocomplete="current-password" tells the browser this is an
            # existing password to fill in, not one to generate — without it,
            # browsers guess from form context (and guess wrong here, since
            # the register tab's password fields sit in the same DOM).
            password = st.text_input(
                t("password_label", locale),
                type="password",
                key="login_password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(t("login_button", locale), use_container_width=True)
        if submitted:
            result = sign_in(email, password)
            if result.ok and result.session:
                _set_authed_session(result.session)
                st.rerun()
            else:
                st.error(t("auth_error_invalid", locale))

    with tab_register:
        with st.form("register_form", border=False):
            email = st.text_input(
                t("email_label", locale), key="register_email", autocomplete="username"
            )
            password = st.text_input(
                t("password_label", locale),
                type="password",
                key="register_password",
                autocomplete="new-password",
            )
            confirm = st.text_input(
                t("confirm_password_label", locale),
                type="password",
                key="register_confirm",
                autocomplete="new-password",
            )
            is_adult = st.checkbox(t("age_confirm_checkbox", locale), key="register_is_adult")
            submitted = st.form_submit_button(t("register_button", locale), use_container_width=True)
        if submitted:
            if not is_adult:
                st.error(t("age_confirm_required", locale))
            elif password != confirm:
                st.error(t("password_mismatch", locale))
            elif len(password) < 6:
                st.error(t("password_too_short", locale))
            else:
                result = sign_up(email, password)
                if result.ok and result.session:
                    create_profile(
                        result.session.access_token,
                        result.session.refresh_token,
                        result.session.user_id,
                        is_adult=True,
                    )
                    _set_authed_session(
                        result.session,
                        known_profile={
                            "is_adult": True,
                            "avatar_url": default_avatar_url(result.session.user_id),
                        },
                    )
                    st.success(t("register_success", locale))
                    st.rerun()
                elif result.error == "confirm_email":
                    st.info(t("auth_check_email", locale))
                else:
                    st.error(t("auth_error_register", locale, error=result.error))


def render_profile_widget(locale: str) -> None:
    """Logged-in view: avatar + email + (collapsed) avatar upload + logout.

    Every user gets a deterministic placeholder avatar at registration (see
    default_avatar_url) — the upload widget itself stays hidden until the
    user asks for it, instead of always being shown. Streamlit has no click
    handler for st.image, so a small pencil button next to the avatar is the
    closest available stand-in for "click the avatar to change it."
    """
    auth = st.session_state.get("auth")
    if not auth:
        return

    col_avatar, col_edit, col_info = st.columns([1, 1, 2])
    with col_avatar:
        if auth.get("avatar_url"):
            st.image(auth["avatar_url"], width=40)
        else:
            st.markdown("### 👤")
    with col_edit:
        if st.button("✏️", key="toggle_avatar_upload", help=t("change_avatar_button", locale)):
            st.session_state["_show_avatar_uploader"] = not st.session_state.get(
                "_show_avatar_uploader", False
            )
    with col_info:
        # Show only the local part of the email (before "@") as a display
        # name — also avoids Streamlit's markdown auto-linking bare emails
        # into mailto: links, which isn't useful here.
        st.caption(auth["email"].split("@")[0])

    if st.session_state.get("_show_avatar_uploader"):
        uploaded = st.file_uploader(
            t("avatar_upload_label", locale),
            type=["png", "jpg", "jpeg"],
            key="avatar_uploader",
            max_upload_size=AVATAR_MAX_UPLOAD_MB,
        )
        # st.file_uploader keeps returning the SAME file object on every rerun
        # until the user removes it — without this guard, the upload (and
        # st.rerun() below) would fire again on every single rerun, looping.
        upload_identity = (uploaded.name, uploaded.size) if uploaded is not None else None
        if uploaded is not None and st.session_state.get("_last_avatar_upload") != upload_identity:
            ext = uploaded.name.rsplit(".", 1)[-1].lower()
            url = upload_avatar(
                auth["access_token"], auth["refresh_token"], auth["user_id"], uploaded.read(), f"avatar.{ext}"
            )
            st.session_state["_last_avatar_upload"] = upload_identity
            if url:
                st.session_state.auth["avatar_url"] = f"{url}?t={int(time.time())}"  # cache-bust
                st.session_state["_show_avatar_uploader"] = False  # collapse once done
                st.success(t("avatar_upload_success", locale))
                st.rerun()
            else:
                st.error(t("avatar_upload_error", locale))

    if st.button(f"🚪 {t('logout_button', locale)}", use_container_width=True, key="logout_btn"):
        sign_out(auth["access_token"], auth["refresh_token"])
        st.session_state.auth = None
        st.rerun()


def _format_local_time(iso_ts: str) -> str:
    """query_logs.created_at comes back from Supabase as UTC (e.g.
    '...T08:09:23+00:00'). Convert to the server's local timezone before
    display — for a locally-run app this matches the user's own clock."""
    if not iso_ts:
        return ""
    try:
        return datetime.fromisoformat(iso_ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_ts[:16].replace("T", " ")


def render_history_view(locale: str) -> None:
    """Read-only list of this user's past queries, pulled from query_logs.

    Persists across browser sessions/devices (unlike the in-memory current
    chat) — only visible to logged-in users, and only their own rows thanks
    to the ql_own_read RLS policy.
    """
    auth = st.session_state.get("auth")
    if not auth:
        return

    with st.expander(f"📜 {t('history_header', locale)}"):
        # Fetched only on explicit click, never automatically on login/rerun —
        # this is the one query_logs round-trip we can fully defer until the
        # user actually wants to see it.
        if "_history_cache" not in st.session_state:
            if st.button(t("history_load", locale), key="history_load_btn"):
                st.session_state["_history_cache"] = get_query_history(
                    auth["access_token"], auth["refresh_token"], auth["user_id"]
                )
                st.rerun()
            return

        if st.button(t("history_refresh", locale), key="history_refresh_btn"):
            st.session_state.pop("_history_cache", None)
            st.rerun()

        history = st.session_state["_history_cache"]

        if not history:
            st.caption(t("history_empty", locale))
            return

        for row in history:
            ts = _format_local_time(row.get("created_at") or "")
            answer = row.get("final_answer") or ""
            if len(answer) > _HISTORY_ANSWER_PREVIEW:
                answer = answer[:_HISTORY_ANSWER_PREVIEW].rstrip() + "…"
            with st.container(border=True):
                st.caption(ts)
                st.markdown(f"🧑 {row.get('user_query', '')}")
                st.markdown(f"🤖 {answer}")
