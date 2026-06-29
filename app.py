"""VinoSage — Streamlit entrypoint."""
from __future__ import annotations

import uuid

import streamlit as st
import streamlit.components.v1 as components

from src.config import DEFAULT_LOCALE, DEFAULT_MODEL
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
    "model": DEFAULT_MODEL,
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
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Imports deferred so page_config executes before any st call ───────────────
from src.agent import run_agent  # noqa: E402
from src.config import CHAT_MODELS  # noqa: E402
from src.logging_db import log_query, log_token_usage, log_tool_calls  # noqa: E402
from src.rag import retrieve  # noqa: E402
from src.ratelimit import check_cost_cap, check_rate_limit  # noqa: E402
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
    "shrimp","oyster","sushi","pasta","pizza","risotto","mushroom","truffle",
    "cheese","salad","barbecue","curry","spicy","tagine","casserole","meat",
}


_HISTORY_COMPOUND: dict[str, str] = {
    "chocolate": (
        r"\bchocolate\s+(?:pudding|puddings|dessert|desserts|cake|cakes|mousse|"
        r"fondue|brownie|brownies|ice\s*cream|fondant|torte|tart|tarts|truffle|"
        r"fudge|ganache|souffl[eé])\b"
        r"|\b(?:with|for|alongside)\s+(?:a\s+)?chocolate\b(?!\s+(?:note|hint|"
        r"flavou?r|touch|character|aroma))"
    ),
    "cake": (
        r"\b(?:with|for|alongside)\s+(?:a\s+)?(?:\w+\s+){0,2}cakes?\b"
        r"(?!-like|\s+like|\s+note|\s+notes|\s+hint|\s+flavou?rs?|\s+character|\s+aroma)"
    ),
}


def _history_source_ok(wine, food_words: list[str]) -> bool:
    """Return True if wine has catalog pairing evidence for any of the food_words.

    Uses compound patterns for keywords that appear both as tasting notes and food
    pairings (e.g. "chocolate"): "dark chocolate notes" ≠ "with a chocolate dessert".
    """
    import re as _re
    raw = (getattr(wine, "payload", {}) or {}).get("description")
    if not isinstance(raw, str):
        return False
    for fw in food_words:
        if fw in _HISTORY_COMPOUND:
            if _re.search(_HISTORY_COMPOUND[fw], raw):
                return True
        else:
            if _re.search(r'\b' + _re.escape(fw) + r'\b', raw):
                return True
    return False


def _agent_history(messages: list, current_query: str = "") -> list:
    import re as _re
    query_food = [w for w in _re.findall(r'\b\w{4,}\b', current_query.lower())
                  if w in _HIST_FOOD_KWS]
    # Follow-up queries ("Is it the only one?") have no food keywords — inherit
    # food context from recent conversation so the pairing filter stays active.
    if not query_food and messages:
        recent = " ".join(
            m["content"] for m in messages[-6:]
            if isinstance(m.get("content"), str)
        )
        query_food = [w for w in _re.findall(r'\b\w{4,}\b', recent.lower())
                      if w in _HIST_FOOD_KWS]

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
    render_sidebar()

    locale     = st.session_state.locale
    model      = st.session_state.model
    session_id = st.session_state.session_id

    # Age gate blocks all chat functionality until confirmed — registering
    # with the mandatory 18+ checkbox also satisfies it (see auth_view.py).
    if not is_age_gate_passed():
        render_age_gate(locale)
        st.stop()

    # st.chat_input at module level → Streamlit fixes it at the bottom of the page.
    # Inside a container it would render inline (wrong position).
    chat_input = st.chat_input(t("chat_placeholder", locale))

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
        if not messages and not chat_input:
            welcome_slot = st.empty()
            with welcome_slot.container():
                render_empty_state(locale)

            # Read queued_prompt set by the button click inside render_empty_state.
            queued = st.session_state.queued_prompt
            if queued:
                st.session_state.queued_prompt = None
                welcome_slot.empty()  # remove buttons before agent output appears

        prompt = chat_input or queued

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

                    result = run_agent(
                        query=prompt,
                        model=model,
                        locale=locale,
                        history=_agent_history(st.session_state.messages[:-1], current_query=prompt),
                        precomputed_rag=rag_results,
                        precomputed_filter=filter_used,
                    )
                    step2.caption(f"✓ {t('step_think', locale)}")

                    final_state = "complete" if result.status == "ok" else "error"
                    status.update(
                        label=t("step_respond", locale),
                        state=final_state,
                        expanded=False,
                    )

                if result.status != "ok":
                    st.error(t("error_generic", locale))

                st.markdown(result.answer)
                render_assistant_extras(result.retrieved_wines, result.tool_calls, locale)

            # Persist assistant turn
            st.session_state.messages.append({
                "role": "assistant",
                "content": result.answer,
                "sources": result.retrieved_wines,
                "tool_calls": result.tool_calls,
                "filter_used": result.filter_used,
                "user_query": prompt,
            })

            # ── Update session metrics ────────────────────────────────────────
            cost_micros = _compute_cost_micros(
                result.model_used, result.input_tokens, result.output_tokens
            )
            st.session_state.session_tokens_in  += result.input_tokens
            st.session_state.session_tokens_out += result.output_tokens
            st.session_state.session_cost_micros += cost_micros
            st.session_state.last_latency_ms = result.latency_ms

            # ── DB logging ────────────────────────────────────────────────────
            retrieved_ids = [str(w.wine_id) for w in result.retrieved_wines if hasattr(w, "wine_id")]
            db_status = result.status if result.status in ("ok", "error") else "ok"
            query_id = log_query(
                session_id=session_id,
                user_id=(_current_user() or {}).get("user_id"),
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

            # Rerun so the sidebar re-renders with updated metrics.
            # Flag triggers auto-scroll in the next render after the rerun.
            st.session_state.scroll_to_bottom = True
            st.rerun()


if __name__ == "__main__":
    main()
