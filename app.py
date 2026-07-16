"""VinoSage — Streamlit entrypoint."""
from __future__ import annotations

import hashlib
import re
import uuid

import streamlit as st
import streamlit.components.v1 as components

from src.config import DEFAULT_LOCALE
from src.i18n import t

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="VinoSage",
    page_icon="🍷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme accent via CSS injection ────────────────────────────────────────────
st.markdown(
    """
    <style>
    [data-testid="stChatInput"] textarea:focus {
        border-color: #7B1E3B !important;
        box-shadow: 0 0 0 1px #7B1E3B !important;
    }
    .stButton > button { border-radius: 6px; }
    div[data-testid="stStatusWidget"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS: dict = {
    "messages": [],
    "locale": DEFAULT_LOCALE,
    "answer_mode": "quick",
    "dev_model_override": None,
    "dev_temperature": 0.2,
    "dev_tools_enabled": {},
    "session_id": str(uuid.uuid4()),
    "session_tokens_in": 0,
    "session_tokens_out": 0,
    "session_cost_micros": 0,
    "last_latency_ms": 0,
    "admin_unlocked": False,
    "queued_prompt": None,
    "scroll_to_bottom": False,
    "auth": None,
    "age_confirmed": False,
    "anon_profile": {},
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Imports deferred so page_config executes before any st call ───────────────
from src.agent import run_agent  # noqa: E402
from src.auth_persistence import emit_pending_cookie, try_restore_session  # noqa: E402
from src.checkpointer import rehydrate_chat_entry, resolve_thread_id, serialize_chat_entry  # noqa: E402
from src.config import CHAT_MODELS, INDEPTH_MODEL, QUICK_MODEL  # noqa: E402
from src.graph import append_chat_log, get_thread_chat_log  # noqa: E402
from src.logging_db import log_query, log_stt_usage, log_token_usage, log_tool_calls  # noqa: E402
from src.preferences import get_preferences  # noqa: E402
from src.rag import retrieve  # noqa: E402
from src.ratelimit import check_cost_cap, check_rate_limit  # noqa: E402
from src.transcribe import transcribe_audio  # noqa: E402
from src.ui.admin import render_admin  # noqa: E402
from src.ui.auth_view import is_age_gate_passed, render_age_gate  # noqa: E402
from src.ui.chat_view import (  # noqa: E402
    render_assistant_extras,
    render_chat_history,
    render_empty_state,
    render_filter_badge,
)
from src.ui.sidebar import render_sidebar  # noqa: E402

_HISTORY_WINDOW = 10


_HIST_FOOD_KWS = {
    # "cake" omitted — see pair_with_food._FOOD_NOUNS for rationale.
    "chocolate","steak","beef","lamb","venison","pork",
    "chicken","turkey","duck","salmon","tuna","fish","seafood","lobster",
    "shrimp","shrimps","oyster","oysters","sushi","pasta","pizza","risotto",
    "mushroom","mushrooms","truffle","truffles",
    "cheese","salad","barbecue","curry","spicy","tagine","casserole","meat",
    "pudding","puddings","mousse","fondue","brownie","brownies","tart","tarts",
    "bread","brioche","flatbread","noodle","noodles","dumpling","dumplings",
    "prawn","prawns","crab","squid","octopus","scallop","scallops",
    "quail","pheasant","burger","soup","stew","chilli","chili","tapas",
}


# Pairing-trigger regex (Layer 3 of triple anti-hallucination defence — identical
# logic also lives in pair_with_food.py and agent.py, deliberately independent).
_HISTORY_PAIRING_TRIGGER_RE = re.compile(
    r"\b(?:"
    r"try\s+it\s+with|try\s+with|serve\s+with|serve\s+alongside|"
    r"pair(?:s|ing)?\s+(?:(?:very|really|so)\s+)?(?:perfectly\s+|well\s+|beautifully\s+|nicely\s+)?with|"
    r"drink\s+with|goes?\s+(?:perfectly\s+|well\s+|beautifully\s+)?with|"
    r"enjoy\s+(?:it\s+)?with|"
    r"partner\s+(?:this\s+|it\s+)?with|partner\s+for|"
    r"perfect\s+(?:with|for|pairing\s+for|match\s+for|accompaniment\s+(?:for|with|to))|"
    r"excellent\s+(?:with|match\s+for)|"
    r"delicious\s+with|fantastic\s+with|great\s+with|wonderful\s+with|lovely\s+with|"
    r"divine\s+with|a\s+dream\s+with|a\s+treat\s+with|"
    r"best\s+with|perfectly\s+with|ideal\s+(?:with|for)|"
    r"complement[s]?\s+|will\s+complement|works\s+well\s+with|"
    r"match(?:es)?\s+(?:perfectly|beautifully|well)\s+with|"
    r"(?:a\s+)?(?:perfect|fantastic|great|delicious|wonderful|excellent|ideal)\s+complement\s+(?:for|to)|"
    r"accompani(?:es|ment)\s+(?:for|to)|a\s+natural\s+match\s+for|"
    r"stand(?:s)?\s+up\s+(?:\w+\s+){0,2}to|suited\s+to|complemented\s+by|good\s+with"
    r")",
    re.IGNORECASE,
)


def _history_source_ok(wine, food_words: list[str]) -> bool:
    """Return True if wine has catalog pairing evidence for any of the food_words.

    Matches only within text that follows an explicit pairing trigger phrase —
    "dark chocolate notes" (tasting note) no longer matches a chocolate query;
    "a natural match for dark chocolate" does.
    """
    raw = (getattr(wine, "payload", {}) or {}).get("description")
    if not isinstance(raw, str):
        return False
    contexts = []
    for m in _HISTORY_PAIRING_TRIGGER_RE.finditer(raw):
        after = raw[m.end():]
        end = re.search(r"[.!?\r\n]", after)
        contexts.append((after[: end.start()] if end else after[:150]).lower())
    for ctx in contexts:
        for fw in food_words:
            stem = fw[:-1] if fw.endswith("s") and len(fw) > 3 else fw
            if re.search(r"\b" + re.escape(stem) + r"s?\b", ctx):
                return True
    return False


def _agent_history(messages: list, current_query: str = "") -> list:
    import re as _re
    def _in_hist_kws(w: str) -> bool:
        return w in _HIST_FOOD_KWS or (w.endswith("s") and len(w) > 3 and w[:-1] in _HIST_FOOD_KWS)

    query_food = [w for w in _re.findall(r'\b\w{4,}\b', current_query.lower()) if _in_hist_kws(w)]
    # Follow-up queries ("Is it the only one?") have no food keywords — inherit
    # food context from recent conversation so the pairing filter stays active.
    if not query_food and messages:
        recent = " ".join(
            m["content"] for m in messages[-6:]
            if isinstance(m.get("content"), str)
        )
        query_food = [w for w in _re.findall(r'\b\w{4,}\b', recent.lower()) if _in_hist_kws(w)]

    result = []
    for m in messages[-_HISTORY_WINDOW:]:
        if m["role"] == "assistant" and m.get("sources"):
            lines = ["[Catalog data retrieved for the following response:"]
            for w in m["sources"]:
                # Apply same food-keyword filter as RAG context: skip wines whose
                # description doesn't support the current query's food pairing.
                if query_food and not _history_source_ok(w, query_food):
                    continue
                p = getattr(w, "payload", {}) or {}
                cents = p.get("price_eur_cents")
                price = f"€{cents/100:.2f}" if cents else "N/A"
                desc = (p.get("description") or "")[:200].replace("\n", " ")
                lines.append(
                    f"  • {getattr(w, 'title', '?')} | type={p.get('type','')} | "
                    f"grape={p.get('grape','')} | country={p.get('country','')} | "
                    f"{price} | style={p.get('style','')}\n"
                    f"    Catalog description: {desc}]"
                )
            if len(lines) > 1:
                result.append({"role": "system", "content": "\n".join(lines)})
        result.append({"role": m["role"], "content": m["content"]})
    return result


def _scroll_to_bottom() -> None:
    """Scroll to the last chat message using scrollIntoView — works regardless of scroll container."""
    components.html(
        """
        <script>
        setTimeout(function() {
            var doc = window.parent.document;
            // scrollIntoView resolves the scroll container automatically
            var msgs = doc.querySelectorAll('[data-testid="stChatMessage"]');
            if (msgs.length) {
                msgs[msgs.length - 1].scrollIntoView({behavior: 'smooth', block: 'end'});
                return;
            }
            // Fallback: walk up from stMainBlockContainer to first scrollable parent
            var el = doc.querySelector('[data-testid="stMainBlockContainer"]');
            while (el && el.parentElement) {
                el = el.parentElement;
                var style = window.parent.getComputedStyle(el);
                if ((style.overflowY === 'auto' || style.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight) {
                    el.scrollTop = el.scrollHeight;
                    return;
                }
            }
            window.parent.scrollTo(0, 99999);
        }, 200);
        </script>
        """,
        height=0,
    )


def _compute_cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    pricing = CHAT_MODELS.get(model, {"in": 0.0, "out": 0.0})
    return int(input_tokens * pricing["in"] + output_tokens * pricing["out"])


def _current_user() -> dict | None:
    return st.session_state.get("auth")


def main() -> None:
    # Login persistence across F5 (Phase 4, step 4/4b). emit_pending_cookie()
    # must run first — it flushes any cookie write/clear staged by the
    # PREVIOUS run's login/register/logout/forget-me action (see
    # src/auth_persistence.py's module docstring for why the write can't
    # happen inline in that prior run). try_restore_session() must then run
    # before render_sidebar() (so the profile widget renders instead of the
    # login form in the SAME run a restore succeeds) and before
    # resolve_thread_id below (so the durable chat loads in that same run too).
    emit_pending_cookie()
    try_restore_session()

    render_sidebar()

    locale     = st.session_state.locale
    session_id = st.session_state.session_id

    # ── Durable conversation thread (SPEC step 9) ─────────────────────────────
    # Logged-in users get a stable thread keyed by user_id, so their chat log
    # survives browser refreshes and server restarts; anonymous users get a
    # per-browser-session thread (ephemeral by construction — new uuid each
    # session). Rehydration runs once per Streamlit session and only when the
    # in-memory chat is empty, so it never clobbers an ongoing conversation
    # (e.g. a user who logs in mid-chat keeps what's on screen).
    _auth_now = _current_user()
    thread_id = resolve_thread_id(_auth_now.get("user_id") if _auth_now else None, session_id)
    if _auth_now and not st.session_state.messages and not st.session_state.get("_chat_rehydrated"):
        st.session_state["_chat_rehydrated"] = True
        _persisted = get_thread_chat_log(thread_id)
        if _persisted:
            st.session_state.messages = [rehydrate_chat_entry(m) for m in _persisted]

    # Quick/In-depth is the only model choice end users ever see (SPEC §5.6).
    # A dev panel selection (admin-only) overrides it for the rest of the
    # session; the override lives in its own session key so it survives
    # reruns regardless of render order between the sidebar and admin tab.
    model = st.session_state.dev_model_override or (
        QUICK_MODEL if st.session_state.answer_mode == "quick" else INDEPTH_MODEL
    )
    temperature = st.session_state.dev_temperature  # 0.2 unless an admin changed it
    disabled_tools = [
        name for name, enabled in st.session_state.dev_tools_enabled.items() if not enabled
    ]

    # Age gate blocks all chat functionality until confirmed — registering
    # with the mandatory 18+ checkbox also satisfies it (see auth_view.py).
    if not is_age_gate_passed():
        render_age_gate(locale)
        st.stop()

    # st.chat_input at module level → Streamlit fixes it at the bottom of the page.
    # Inside a container it would render inline (wrong position).
    chat_input = st.chat_input(t("chat_placeholder", locale))

    # ── Voice input (Phase 3, step 4) ──────────────────────────────────────────
    # st.audio_input keeps returning the SAME recording on every rerun, so we
    # fingerprint it and transcribe each recording exactly once. The rate limit
    # is checked BEFORE transcription: it is the throttle protecting the paid
    # STT endpoint (a voice turn therefore consumes 2 window slots — one here,
    # one in the normal prompt pre-flight; 10/min → up to 5 voice turns/min).
    #
    # Widget-key rotation (Phase 3, step 6d): once a recording is CONSUMED
    # (transcribed — whether it produced text, silence, or an error), we bump
    # the generation counter so the next rerun mounts a fresh empty recorder.
    # Without this, st.audio_input keeps referencing the consumed upload and
    # renders "An error has occurred" until manually reset. NOT rotated on
    # the rate-limit branch — there the recording was NOT consumed and the
    # user may retry it after the window.
    voice_prompt: str | None = None
    _voice_gen = st.session_state.setdefault("_voice_widget_gen", 0)
    with st.popover(f"🎤 {t('voice_input_label', locale)}"):
        _audio = st.audio_input(
            t("voice_record_label", locale),
            key=f"voice_recorder_{_voice_gen}",
        )
    if _audio is not None:
        _digest = hashlib.sha256(_audio.getvalue()).hexdigest()
        if st.session_state.get("_last_voice_digest") != _digest:
            _rl_voice = check_rate_limit(session_id)
            if not _rl_voice.allowed:
                st.warning(t("error_rate_limit", locale))
            else:
                st.session_state["_last_voice_digest"] = _digest
                st.session_state["_voice_widget_gen"] = _voice_gen + 1
                with st.spinner(t("voice_transcribing", locale)):
                    _res = transcribe_audio(
                        _audio.getvalue(),
                        filename=getattr(_audio, "name", None) or "voice.wav",
                        locale=locale,
                    )
                if _res.get("error"):
                    st.toast(t("voice_error", locale), icon="⚠️")
                else:
                    # Any consumed outcome that returned usage — including
                    # empty-transcript silence, which still billed seconds —
                    # is logged toward the daily cost cap (Phase 4 step 3).
                    # Best-effort; never blocks the turn.
                    log_stt_usage(
                        session_id=session_id,
                        user_id=(_auth_now.get("user_id") if _auth_now else None),
                        model=_res.get("model") or "",
                        seconds=_res.get("seconds"),
                        cost_eur_micros=_res.get("cost_eur_micros") or 0,
                    )
                    if not _res["text"]:
                        st.toast(t("voice_empty", locale), icon="🎤")
                    else:
                        voice_prompt = _res["text"]

    # ── Layout: chat + optional admin tab ────────────────────────────────────
    if st.session_state.admin_unlocked:
        tabs      = st.tabs([t("app_title", locale), t("admin_header", locale)])
        chat_area = tabs[0]
        with tabs[1]:
            render_admin(locale)
    else:
        chat_area = st.container()

    user_avatar = (_current_user() or {}).get("avatar_url")

    with chat_area:
        messages = st.session_state.messages

        if messages:
            render_chat_history(messages, locale, user_avatar=user_avatar)
            if st.session_state.scroll_to_bottom:
                st.session_state.scroll_to_bottom = False
                _scroll_to_bottom()

        # Render welcome screen into a clearable placeholder so we can erase it
        # the moment a button is clicked — before the agent status widget appears.
        queued: str | None = None
        if not messages and not chat_input and not voice_prompt:
            welcome_slot = st.empty()
            with welcome_slot.container():
                render_empty_state(locale)

            # Read queued_prompt set by the button click inside render_empty_state.
            queued = st.session_state.queued_prompt
            if queued:
                st.session_state.queued_prompt = None
                welcome_slot.empty()  # remove buttons before agent output appears

        prompt = chat_input or queued or voice_prompt

        if prompt:
            # ── Pre-flight guards ─────────────────────────────────────────────
            rl = check_rate_limit(session_id)
            if not rl.allowed:
                st.warning(t("error_rate_limit", locale))
                st.stop()

            cc = check_cost_cap()
            if not cc.allowed:
                st.warning(t("error_generic", locale))
                st.stop()

            # Store & display user turn
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user", avatar=user_avatar):
                st.markdown(prompt)

            # ── Agent call with 3-step progress stepper ───────────────────────
            with st.chat_message("assistant"):
                # Own placeholder OUTSIDE st.status — the status widget's body
                # only shows the current step's caption, so anything rendered
                # inside it (like the badge) gets visually replaced once the
                # label moves on to the next step. A separate slot keeps the
                # badge visible for the rest of the turn, right where the user
                # is still looking (next to the spinner) while nothing else
                # has appeared yet.
                badge_slot = st.empty()
                with st.status(t("step_retrieve", locale), expanded=True) as status:
                    step1 = st.empty()
                    step1.caption(f"⏳ {t('step_retrieve', locale)}…")
                    try:
                        rag_result = retrieve(query=prompt, locale=locale)
                        rag_results, filter_used = rag_result.wines, rag_result.filter_used
                    except Exception:
                        rag_results, filter_used = [], {}
                    step1.caption(f"✓ {t('step_retrieve', locale)}")
                    with badge_slot.container():
                        render_filter_badge(filter_used, prompt, locale)

                    status.update(label=t("step_think", locale))
                    step2 = st.empty()
                    step2.caption(f"⏳ {t('step_think', locale)}…")

                    # Resolve this turn's taste profile: authed read (RLS) for
                    # logged-in users, the in-session dict for anonymous ones
                    # (anon profiles are never persisted — SPEC §5.3).
                    # Re-use _prefs_cache populated by the sidebar earlier this
                    # rerun; only fall back to a fresh DB read if the cache is
                    # absent (e.g. first load before sidebar had a chance to set
                    # it). This avoids a redundant Supabase call on every turn
                    # and prevents a transient timeout from silently zeroing out
                    # the profile passed to recommend_for_me.
                    auth = _current_user()
                    user_id = auth.get("user_id") if auth else None
                    if auth:
                        profile = st.session_state.get("_prefs_cache")
                        if profile is None:
                            profile = get_preferences(auth["access_token"], auth["refresh_token"], user_id)
                            st.session_state["_prefs_cache"] = profile
                        # _prefs_cache can be EMPTY_PROFILE (all-empty lists) if the DB
                        # read failed (expired token, transient timeout) while the sidebar
                        # widget keys still hold the user's last-known selections.
                        # If the cache looks empty but the sidebar widgets have data,
                        # build the profile from widget state so the agent isn't blinded.
                        _LIST_FIELDS = (
                            "preferred_types", "preferred_grapes", "preferred_countries",
                            "preferred_styles", "preferred_characteristics",
                        )
                        if not any((profile or {}).get(k) for k in _LIST_FIELDS):
                            _widget_profile = {
                                "expertise_level": st.session_state.get("pref_expertise", "beginner"),
                                "preferred_types":           list(st.session_state.get("pref_types", []) or []),
                                "preferred_grapes":          list(st.session_state.get("pref_grapes", []) or []),
                                "preferred_countries":       list(st.session_state.get("pref_countries", []) or []),
                                "preferred_styles":          list(st.session_state.get("pref_styles", []) or []),
                                "preferred_characteristics": list(st.session_state.get("pref_characteristics", []) or []),
                                "disliked_types":            list(st.session_state.get("disliked_types", []) or []),
                                "disliked_grapes":           list(st.session_state.get("disliked_grapes", []) or []),
                                "disliked_styles":           list(st.session_state.get("disliked_styles", []) or []),
                                "min_price_eur_cents": (profile or {}).get("min_price_eur_cents"),
                                "max_price_eur_cents": (profile or {}).get("max_price_eur_cents"),
                                "notes": None,
                            }
                            if any(_widget_profile.get(k) for k in _LIST_FIELDS):
                                profile = _widget_profile
                    else:
                        profile = st.session_state.anon_profile

                    result = run_agent(
                        query=prompt,
                        model=model,
                        locale=locale,
                        history=_agent_history(st.session_state.messages[:-1], current_query=prompt),
                        precomputed_rag=rag_results,
                        precomputed_filter=filter_used,
                        user_id=user_id,
                        profile=profile,
                        session_id=session_id,
                        temperature=temperature,
                        disabled_tools=disabled_tools,
                        thread_id=thread_id,
                    )
                    step2.caption(f"✓ {t('step_think', locale)}")

                    # Logged-in users' signals are already upserted to the DB by
                    # extract_preferences; anonymous signals only ever live here.
                    if not auth and result.extracted_preferences:
                        st.session_state.anon_profile = result.extracted_preferences

                    final_state = "complete" if result.status == "ok" else "error"
                    status.update(
                        label=t("step_respond", locale),
                        state=final_state,
                        expanded=False,
                    )

                if result.status != "ok":
                    st.error(t("error_generic", locale))

                # ── Update session metrics ────────────────────────────────────
                cost_micros = _compute_cost_micros(
                    result.model_used, result.input_tokens, result.output_tokens
                )
                st.session_state.session_tokens_in  += result.input_tokens
                st.session_state.session_tokens_out += result.output_tokens
                st.session_state.session_cost_micros += cost_micros
                st.session_state.last_latency_ms = result.latency_ms

                # ── DB logging (computed before rendering so feedback buttons
                # below have a real query_id to attach recommendation_feedback
                # rows to) ─────────────────────────────────────────────────────
                retrieved_ids = [str(w.wine_id) for w in result.retrieved_wines if hasattr(w, "wine_id")]
                db_status = result.status if result.status in ("ok", "error") else "ok"
                query_id = log_query(
                    session_id=session_id,
                    user_id=user_id,
                    user_query=prompt,
                    locale=locale,
                    model=result.model_used,
                    final_answer=result.answer,
                    latency_ms=result.latency_ms,
                    status=db_status,
                    error_code=result.error_code,
                    retrieved_ids=retrieved_ids,
                )
                log_tool_calls(query_id, result.tool_calls)
                log_token_usage(
                    query_id=query_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_eur_micros=cost_micros,
                )

                st.markdown(result.answer)
                render_assistant_extras(result.retrieved_wines, result.tool_calls, locale, query_id=query_id, response_text=result.answer)

            # Persist assistant turn (query_id lets historical re-renders show
            # feedback buttons too — see render_chat_history).
            assistant_entry = {
                "role": "assistant",
                "content": result.answer,
                "sources": result.retrieved_wines,
                "tool_calls": result.tool_calls,
                "filter_used": result.filter_used,
                "user_query": prompt,
                "query_id": query_id,
            }
            st.session_state.messages.append(assistant_entry)

            # Durable persistence (SPEC step 9): logged-in users only — the
            # anonymous thread is ephemeral, and writing it would just leave
            # unreachable rows behind. Appended AFTER log_query so query_id is
            # included and feedback buttons work on rehydrated history.
            # append_chat_log swallows failures (persistence never blocks chat).
            if auth:
                append_chat_log(thread_id, [
                    serialize_chat_entry({"role": "user", "content": prompt}),
                    serialize_chat_entry(assistant_entry),
                ])

            # Rerun so the sidebar re-renders with updated metrics.
            # Flag triggers auto-scroll in the next render after the rerun.
            st.session_state.scroll_to_bottom = True
            st.rerun()


if __name__ == "__main__":
    main()
