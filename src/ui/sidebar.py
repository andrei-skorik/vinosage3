"""Sidebar: language selector, model selector, session metrics, help, admin gate."""
from __future__ import annotations

import streamlit as st

from src.catalog import get_active_wines_df
from src.config import ADMIN_PASSWORD, DEFAULT_LOCALE
from src.i18n import t
from src.preferences import EMPTY_PROFILE, delete_preferences, get_preferences, upsert_preferences
from src.ui.auth_view import render_auth_forms, render_history_view, render_profile_widget
from src.ui.chat_view import export_messages_csv, export_messages_json

_LOCALE_FLAGS = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch", "ru": "🇷🇺 Русский", "fi": "🇫🇮 Suomi"}
_LOCALE_CODES = list(_LOCALE_FLAGS.keys())

_EXPERTISE_LEVELS = ["beginner", "enthusiast", "connoisseur"]


def _catalog_options() -> dict[str, list[str]]:
    """Distinct catalog values for each taste dimension — multiselect options
    are restricted to these so a user can never save a preference that
    doesn't correspond to a real catalog value (SPEC §4.3).

    Result is stored in session_state so the full DataFrame scan runs at
    most once per browser session, not on every Streamlit rerun.
    """
    import streamlit as _st
    cached = _st.session_state.get("_catalog_options_cache")
    if cached is not None:
        return cached

    df = get_active_wines_df()
    if df.empty:
        return {"type": [], "grape": [], "country": [], "style": [], "characteristics": []}

    chars: set[str] = set()
    for raw in df["characteristics"].dropna():
        chars.update(p.strip() for p in str(raw).split(",") if p.strip())

    result = {
        "type":    sorted(df["type"].dropna().unique().tolist()),
        "grape":   sorted(df["grape"].dropna().unique().tolist()),
        "country": sorted(df["country"].dropna().unique().tolist()),
        "style":   sorted(df["style"].dropna().unique().tolist()),
        "characteristics": sorted(chars),
    }
    _st.session_state["_catalog_options_cache"] = result
    return result


def render_taste_profile(locale: str) -> None:
    auth = st.session_state.get("auth")

    with st.expander(f"👤 {t('taste_profile_header', locale)}"):
        if not auth:
            st.caption(t("taste_profile_login_hint", locale))
            return

        user_id = auth["user_id"]

        # Apply a feedback fold that happened during the previous script run
        # (written by chat_view._fold_cache before st.rerun() was called).
        # This must happen BEFORE any widget renders so the new values take
        # effect immediately — Streamlit ignores session_state writes that
        # occur after a widget with that key has already rendered.
        pending = st.session_state.pop("_pending_profile_update", None)
        if pending is not None:
            st.session_state["_prefs_cache"] = pending
            st.session_state["pref_types"]      = pending.get("preferred_types")  or []
            st.session_state["pref_grapes"]     = pending.get("preferred_grapes") or []
            st.session_state["pref_styles"]     = pending.get("preferred_styles") or []
            st.session_state["disliked_types"]  = pending.get("disliked_types")   or []
            st.session_state["disliked_grapes"] = pending.get("disliked_grapes")  or []
            st.session_state["disliked_styles"] = pending.get("disliked_styles")  or []

        if "_prefs_cache" not in st.session_state:
            with st.spinner(t("loading_profile", locale)):
                st.session_state["_prefs_cache"] = get_preferences(
                    auth["access_token"], auth["refresh_token"], user_id
                )
        profile = st.session_state["_prefs_cache"]

        is_new = profile == EMPTY_PROFILE
        if is_new:
            st.caption(t("taste_profile_empty", locale))

        options = _catalog_options()

        expertise = st.radio(
            t("expertise_label", locale),
            options=_EXPERTISE_LEVELS,
            format_func=lambda lvl: t(f"expertise_{lvl}", locale),
            index=_EXPERTISE_LEVELS.index(profile.get("expertise_level", "beginner")),
            key="pref_expertise",
        )
        pref_types = st.multiselect(
            t("pref_types_label", locale), options=options["type"],
            default=[v for v in profile.get("preferred_types") or [] if v in options["type"]],
            key="pref_types",
        )
        pref_grapes = st.multiselect(
            t("pref_grapes_label", locale), options=options["grape"],
            default=[v for v in profile.get("preferred_grapes") or [] if v in options["grape"]],
            key="pref_grapes",
        )
        pref_countries = st.multiselect(
            t("pref_countries_label", locale), options=options["country"],
            default=[v for v in profile.get("preferred_countries") or [] if v in options["country"]],
            key="pref_countries",
        )
        pref_styles = st.multiselect(
            t("pref_styles_label", locale), options=options["style"],
            default=[v for v in profile.get("preferred_styles") or [] if v in options["style"]],
            key="pref_styles",
        )
        pref_chars = st.multiselect(
            t("pref_characteristics_label", locale), options=options["characteristics"],
            default=[v for v in profile.get("preferred_characteristics") or [] if v in options["characteristics"]],
            key="pref_characteristics",
        )
        disliked_types = st.multiselect(
            t("disliked_types_label", locale), options=options["type"],
            default=[v for v in profile.get("disliked_types") or [] if v in options["type"]],
            key="disliked_types",
        )
        disliked_grapes = st.multiselect(
            t("disliked_grapes_label", locale), options=options["grape"],
            default=[v for v in profile.get("disliked_grapes") or [] if v in options["grape"]],
            key="disliked_grapes",
        )
        disliked_styles = st.multiselect(
            t("disliked_styles_label", locale), options=options["style"],
            default=[v for v in profile.get("disliked_styles") or [] if v in options["style"]],
            key="disliked_styles",
        )

        cents_to_eur = lambda c: (c / 100) if c is not None else 0.0  # noqa: E731
        min_eur = st.number_input(
            t("price_min_label", locale), min_value=0.0, step=1.0,
            value=cents_to_eur(profile.get("min_price_eur_cents")), key="pref_min_price",
        )
        max_eur = st.number_input(
            t("price_max_label", locale), min_value=0.0, step=1.0,
            value=cents_to_eur(profile.get("max_price_eur_cents")), key="pref_max_price",
        )

        if st.button(t("save_profile", locale), use_container_width=True, key="save_profile_btn"):
            if max_eur and min_eur and min_eur > max_eur:
                st.error(t("profile_save_error", locale))
            else:
                fields = {
                    "expertise_level":           expertise,
                    "preferred_types":           pref_types,
                    "preferred_grapes":          pref_grapes,
                    "preferred_countries":       pref_countries,
                    "preferred_regions":         profile.get("preferred_regions") or [],
                    "preferred_styles":          pref_styles,
                    "preferred_characteristics": pref_chars,
                    "disliked_types":            disliked_types,
                    "disliked_grapes":           disliked_grapes,
                    "disliked_styles":           disliked_styles,
                    "min_price_eur_cents":       int(min_eur * 100) if min_eur else None,
                    "max_price_eur_cents":       int(max_eur * 100) if max_eur else None,
                    "notes":                     profile.get("notes"),
                }
                if upsert_preferences(user_id, **fields):
                    st.session_state["_prefs_cache"] = {**profile, **fields}
                    st.success(t("profile_saved", locale))
                else:
                    st.error(t("profile_save_error", locale))

        with st.popover(f"🗑 {t('forget_me', locale)}", use_container_width=True):
            st.caption(t("forget_me_confirm", locale))
            col_yes, col_cancel = st.columns(2)
            if col_yes.button(t("forget_me_yes", locale), key="forget_me_yes_btn", type="primary"):
                if delete_preferences(user_id):
                    from src.graph import delete_thread
                    delete_thread(f"user:{user_id}")   # erase durable conversation too (US-004)
                    st.session_state.pop("_prefs_cache", None)
                    st.success(t("profile_deleted", locale))
                    st.rerun()
                else:
                    st.error(t("profile_save_error", locale))
            col_cancel.button(t("forget_me_cancel", locale), key="forget_me_cancel_btn")


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

        render_taste_profile(locale)
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

        # Answer speed — the only model choice end users ever see (SPEC §5.6).
        # Real model names/temperature live in the admin dev panel only; a dev
        # override (if set) takes precedence regardless of this radio's value.
        st.markdown(f"**{t('answer_mode_label', locale)}**")
        _MODE_OPTIONS = ["quick", "indepth"]
        current_mode = st.session_state.get("answer_mode", "quick")
        mode_idx = _MODE_OPTIONS.index(current_mode) if current_mode in _MODE_OPTIONS else 0
        selected_mode = st.radio(
            label=t("answer_mode_label", locale),
            options=_MODE_OPTIONS,
            format_func=lambda m: t(f"answer_mode_{m}", locale),
            index=mode_idx,
            horizontal=True,
            label_visibility="collapsed",
            key="answer_mode_radio",
        )
        if selected_mode != st.session_state.get("answer_mode"):
            st.session_state.answer_mode = selected_mode

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
