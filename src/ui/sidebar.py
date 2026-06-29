"""Sidebar: language selector, model selector, session metrics, help, admin gate."""
from __future__ import annotations

import streamlit as st

from src.config import ADMIN_PASSWORD, CHAT_MODELS, DEFAULT_LOCALE, DEFAULT_MODEL
from src.i18n import t
from src.ui.auth_view import render_auth_forms, render_history_view, render_profile_widget
from src.ui.chat_view import export_messages_csv, export_messages_json

_LOCALE_FLAGS = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch", "ru": "🇷🇺 Русский", "fi": "🇫🇮 Suomi"}
_LOCALE_CODES = list(_LOCALE_FLAGS.keys())


def render_sidebar() -> None:
    locale = st.session_state.get("locale", DEFAULT_LOCALE)

    with st.sidebar:
        st.markdown(f"# 🍷 {t('app_title', locale)}")
        st.caption(t("app_tagline", locale))
        st.divider()

        # Account: profile widget if logged in, else login/register forms.
        # Optional — registering only unlocks avatar personalisation, it does
        # not gate chat access (the separate age gate handles that).
        if st.session_state.get("auth"):
            render_profile_widget(locale)
            render_history_view(locale)
        else:
            with st.expander(f"👤 {t('account_header', locale)}"):
                render_auth_forms(locale)
        st.divider()

        # Language selector
        st.markdown(f"**{t('language_label', locale)}**")
        current_idx = _LOCALE_CODES.index(locale) if locale in _LOCALE_CODES else 0
        selected = st.selectbox(
            label=t("language_label", locale),
            options=_LOCALE_CODES,
            format_func=lambda code: _LOCALE_FLAGS[code],
            index=current_idx,
            label_visibility="collapsed",
            key="locale_select",
        )
        if selected != st.session_state.get("locale"):
            st.session_state.locale = selected
            st.rerun()

        st.divider()

        # Model selector
        st.markdown(f"**{t('model_label', locale)}**")
        model_list = list(CHAT_MODELS.keys())
        current_model = st.session_state.get("model", DEFAULT_MODEL)
        model_idx = model_list.index(current_model) if current_model in model_list else 0
        selected_model = st.selectbox(
            label=t("model_label", locale),
            options=model_list,
            index=model_idx,
            label_visibility="collapsed",
            key="model_select",
        )
        if selected_model != st.session_state.get("model"):
            st.session_state.model = selected_model

        st.divider()

        # Session metrics
        tokens_in  = st.session_state.get("session_tokens_in", 0)
        tokens_out = st.session_state.get("session_tokens_out", 0)
        cost_micros = st.session_state.get("session_cost_micros", 0)
        latency_ms  = st.session_state.get("last_latency_ms", 0)

        col1, col2 = st.columns(2)
        col1.metric(t("tokens_in_label", locale),  f"{tokens_in:,}")
        col2.metric(t("tokens_out_label", locale), f"{tokens_out:,}")

        # Full-width (not 2-col like tokens above) — "€0.0072" + a long label
        # gets clipped to "€0.0..." in a half-width sidebar column.
        cost_eur = cost_micros / 1_000_000
        st.metric(t("session_cost_label", locale), f"€{cost_eur:.4f}")
        if latency_ms:
            st.metric(t("latency_label", locale), t("latency_value", locale, ms=latency_ms))

        st.divider()

        # New chat
        if st.button(f"🗑 {t('new_chat', locale)}", use_container_width=True):
            st.session_state.messages = []
            st.session_state.session_tokens_in = 0
            st.session_state.session_tokens_out = 0
            st.session_state.session_cost_micros = 0
            st.session_state.last_latency_ms = 0
            st.rerun()

        st.divider()

        # Export current session's conversation
        messages = st.session_state.get("messages", [])
        if messages:
            st.markdown(f"**{t('export_chat_header', locale)}**")
            session_tag = st.session_state.get("session_id", "session")[:8]
            col_json, col_csv = st.columns(2)
            col_json.download_button(
                t("export_json_button", locale),
                data=export_messages_json(messages),
                file_name=f"vinosage_chat_{session_tag}.json",
                mime="application/json",
                use_container_width=True,
            )
            col_csv.download_button(
                t("export_csv_button", locale),
                data=export_messages_csv(messages),
                file_name=f"vinosage_chat_{session_tag}.csv",
                mime="text/csv",
                use_container_width=True,
            )
            st.divider()

        # Help & disclaimer
        with st.expander(f"❓ {t('help_header', locale)}"):
            st.markdown(t("help_body", locale))
            st.caption(t("disclaimer", locale))

        st.divider()

        # Admin gate
        if not st.session_state.get("admin_unlocked"):
            with st.expander(f"🔒 {t('admin_header', locale)}"):
                pwd = st.text_input(
                    t("admin_password_label", locale),
                    type="password",
                    key="admin_pwd_input",
                    autocomplete="current-password",
                )
                if st.button(t("admin_unlock", locale), key="admin_unlock_btn"):
                    if pwd == ADMIN_PASSWORD:
                        st.session_state.admin_unlocked = True
                        st.rerun()
                    else:
                        st.error(t("admin_wrong_password", locale))
        else:
            st.success(t("admin_unlocked", locale))
            if st.button("🔓 Lock admin", key="admin_lock_btn"):
                st.session_state.admin_unlocked = False
                st.rerun()
