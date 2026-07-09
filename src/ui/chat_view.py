"""Chat view helpers — rendering history, empty state, and message details."""
from __future__ import annotations

import csv
import io
import json
import random
from typing import Any

import streamlit as st

from src.i18n import t, tlist

_EXAMPLE_COUNT = 3


def render_empty_state(locale: str) -> None:
    """Render the welcome screen. Clicked button label is written to queued_prompt."""
    st.markdown(f"## {t('welcome_title', locale)}")
    st.markdown(t("welcome_body", locale))
    st.markdown("")

    # Cache picks so button keys map to the same labels across reruns.
    cache_key = f"_welcome_picks_{locale}"
    if cache_key not in st.session_state:
        pool = tlist("welcome_examples", locale)
        if not pool:
            return
        st.session_state[cache_key] = random.sample(pool, min(_EXAMPLE_COUNT, len(pool)))

    picks: list[str] = st.session_state[cache_key]
    cols = st.columns(len(picks))
    for i, (col, label) in enumerate(zip(cols, picks)):
        with col:
            if st.button(label, use_container_width=True, key=f"example_{i}"):
                st.session_state.queued_prompt = label


def _format_filter_chips(filter_used: dict[str, Any]) -> str:
    """Render the extracted self-query filter as a compact chip string,
    e.g. 'Red · Italy · ≤ €20.00'."""
    parts: list[str] = []
    for key in ("type", "grape", "country", "style"):
        val = filter_used.get(key)
        if val:
            parts.append(str(val))
    max_price = filter_used.get("max_price_eur")
    if max_price is not None:
        try:
            parts.append(f"≤ €{float(max_price):.2f}")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)


def render_filter_badge(filter_used: dict[str, Any], query: str, locale: str) -> None:
    """Show what was understood from the user's request, right after retrieval —
    so the user can confirm it was read correctly. Prefers the structured
    self-query filter (e.g. "Red · Italy · ≤ €20.00"); falls back to echoing
    the original query text when no hard filter was extracted (pairing /
    open-ended requests like "suggest a dessert wine for chocolate")."""
    chips = _format_filter_chips(filter_used) if filter_used else ""
    if chips:
        st.caption(f"🔍 {t('searching_for_label', locale)} {chips}")
    elif query:
        st.caption(f"🔍 {t('searching_for_label', locale)} “{query}”")


def _format_tool_result(tool_name: str, result: Any, locale: str) -> str:
    """Human-readable one-line summary of a tool's actual return value.

    Falls back to a generic string for unrecognised shapes — never raises,
    since this is purely cosmetic.
    """
    if result is None:
        return ""
    if not isinstance(result, dict):
        return str(result)

    if "error" in result:
        err = result["error"]
        return f"⚠️ {err.get('message') or err.get('code', '?')}"

    try:
        if tool_name == "pair_with_food":
            dish = result.get("dish", "")
            pairings = result.get("pairings", [])
            if not pairings:
                return t("tool_no_pairing", locale, dish=dish)
            titles = ", ".join(p["title"] for p in pairings)
            return t("tool_pairing_found", locale, dish=dish, count=len(pairings), titles=titles)

        if tool_name == "filter_wines":
            wines = result.get("wines", [])
            titles = ", ".join(w["title"] for w in wines)
            return t("tool_filter_found", locale, count=result.get("count", len(wines)), titles=titles)

        if tool_name == "calculate_budget":
            basket = result.get("basket", [])
            total = result.get("grand_total_eur")
            if total is None:
                return str(result)
            count = result.get("selected_count", len(basket))
            return t("tool_budget_result", locale, count=count, total=f"{total:.2f}")

        if tool_name == "compare_wines":
            comp = result.get("comparison", [])
            titles = ", ".join(c["title"] for c in comp)
            return t("tool_compare_result", locale, titles=titles)

        if tool_name == "wine_stats":
            metric = result.get("metric", "")
            value = result.get("value", result.get("value_eur", result.get("value_abv")))
            return t("tool_stats_result", locale, metric=metric, value=value)

        if tool_name == "explain_wine_concept":
            concept = result.get("concept", "")
            return t("tool_explain_result", locale, concept=concept)

        if tool_name == "recommend_for_me":
            recs = result.get("recommendations", [])
            titles = ", ".join(r["title"] for r in recs)
            return t("tool_recommend_result", locale, count=result.get("count", len(recs)), titles=titles)
    except Exception:
        return str(result)

    return str(result)


def _recommended_wines_for_feedback(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wines worth collecting 👍/👎 on — only pair_with_food / recommend_for_me
    results (SPEC §4.2): those are the tools that actually recommended
    specific wines, unlike filter_wines/compare_wines/wine_stats."""
    wines: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for tc in tool_calls:
        result = tc.get("result")
        if not isinstance(result, dict):
            continue
        if tc.get("tool_name") == "pair_with_food":
            items = result.get("pairings") or []
        elif tc.get("tool_name") == "recommend_for_me":
            items = result.get("recommendations") or []
        else:
            continue
        for w in items:
            wid = w.get("wine_id")
            if wid and wid not in seen_ids:
                seen_ids.add(wid)
                wines.append(w)
    return wines


def render_feedback_buttons(tool_calls: list[dict[str, Any]], query_id: str | None, locale: str) -> None:
    """👍/👎 under each recommended wine (US-005).

    Buttons turn green (👍) or red (👎) when active.  Clicking the same
    button again toggles the rating off and the button returns to white.
    State lives in st.session_state['wine_ratings'] for the browser session.
    A failed DB write is silent — only success triggers st.toast (SPEC §5.4).

    Colouring mechanism: each button label embeds a zero-width space (U+200B)
    followed by a unique marker string (wine_id + direction suffix) that is
    completely invisible to the user.  A single components.v1.html() call
    injects JS that scans all <button> elements in the parent document for this
    hidden marker, then either sets the active colour or removes any previously
    set inline styles (= toggle-off reset).  This avoids the layout-shift
    problem caused by injecting hidden <span> elements via st.markdown and also
    correctly resets buttons that were coloured in a prior render cycle.
    """
    if not query_id:
        return
    wines = _recommended_wines_for_feedback(tool_calls)
    if not wines:
        return

    from src.logging_db import log_feedback, get_latest_ratings, delete_feedback
    from src.preferences import fold_feedback
    import streamlit.components.v1 as components

    session_id = st.session_state.get("session_id", "")
    auth = st.session_state.get("auth")
    user_id = auth.get("user_id") if auth else None

    if "wine_ratings" not in st.session_state:
        st.session_state["wine_ratings"] = {}
        st.session_state["wine_ratings_loaded"] = False
    ratings: dict[str, str | None] = st.session_state["wine_ratings"]

    # Load the user's existing ratings from the DB exactly once per session so
    # that wines rated in previous conversations appear with the correct button
    # colour and don't generate a redundant DB write on the next click.
    if user_id and not st.session_state.get("wine_ratings_loaded"):
        loaded = get_latest_ratings(user_id)
        ratings.update(loaded)
        st.session_state["wine_ratings_loaded"] = True

    def _toggle(wine: dict[str, Any], direction: str) -> None:
        wine_id = str(wine.get("wine_id", ""))
        if ratings.get(wine_id) == direction:
            # Same button again → toggle off: white buttons = no opinion.
            # Delete the DB record and remove attributes from the profile.
            ratings[wine_id] = None
            if user_id:
                delete_feedback(user_id=user_id, wine_id=wine_id)
                fold_feedback(user_id, wine, "none")
            return
        ratings[wine_id] = direction
        ok = log_feedback(
            session_id=session_id,
            query_id=query_id,
            wine_id=wine.get("wine_id"),
            wine_title=wine.get("title"),
            rating=direction,
            user_id=user_id,
        )
        if ok:
            if user_id:
                fold_feedback(user_id, wine, direction)
            st.toast(t("feedback_saved", locale))

    # color_map: active marker → CSS colour (absent = reset to default).
    # mines:     ALL markers for THIS message's wines — scopes the JS so it
    #            never touches buttons belonging to a different message.
    color_map: dict[str, str] = {}
    mines: dict[str, bool] = {}

    for w in wines:
        wine_id = str(w.get("wine_id", ""))
        current = ratings.get(wine_id)
        safe = wine_id.replace("-", "")      # 32 hex chars; valid CSS class
        mk_u, mk_d = "fbm" + safe + "u", "fbm" + safe + "d"
        mines[mk_u] = True
        mines[mk_d] = True

        if current == "up":
            color_map[mk_u] = "#28a745"
        elif current == "down":
            color_map[mk_d] = "#dc3545"

        col_label, col_up, col_down = st.columns([6, 1, 1])
        col_label.caption(w.get("title", ""))

        # Hidden anchor spans are injected in each column.  Pure-CSS <style>
        # via st.markdown is scoped by React and can't reliably reach siblings,
        # so styling is done via JS below.  The base CSS (injected into <head>
        # once per session) collapses the stMarkdownContainer wrappers so the
        # spans never cause a layout shift.
        with col_up:
            # Button first so it sits at the top of the column, aligned with
            # the wine name label.  The anchor span follows (collapsed to zero
            # height by the base CSS injected into <head> below).
            if st.button("👍", key=f"fb_up_{query_id}_{wine_id}", help=t("feedback_up", locale)):
                _toggle(w, "up")
                st.rerun()
            st.markdown(f'<span class="{mk_u}"></span>', unsafe_allow_html=True)

        with col_down:
            if st.button("👎", key=f"fb_down_{query_id}_{wine_id}", help=t("feedback_down", locale)):
                _toggle(w, "down")
                st.rerun()
            st.markdown(f'<span class="{mk_d}"></span>', unsafe_allow_html=True)

    color_map_json = json.dumps(color_map)
    mines_json = json.dumps(mines)
    components.html(
        f"""<script>
var COLORS = {color_map_json};
var MINE   = {mines_json};
var pDoc   = window.parent.document;

// ── Base CSS (once per page load): collapse fbm marker containers ────────────
// Injected into <head> so it is global and not scoped by React.
if (!pDoc.getElementById('vino-fb-base')) {{
    var bs = pDoc.createElement('style');
    bs.id = 'vino-fb-base';
    bs.textContent =
        'div[data-testid="stMarkdownContainer"]:has(span[class^="fbm"]){{' +
        'height:0!important;overflow:hidden!important;' +
        'min-height:0!important;padding:0!important;margin:0!important}}';
    pDoc.head.appendChild(bs);
}}

// ── Per-render: colour active buttons, reset inactive ones ───────────────────
// Scoped to MINE so each message manages only its own buttons.
function apply() {{
    pDoc.querySelectorAll('span[class^="fbm"]').forEach(function(span) {{
        var mk = span.className.trim();
        if (!(mk in MINE)) return;
        var vb  = span.closest('[data-testid="stVerticalBlock"]');
        var btn = vb && vb.querySelector('button');
        if (!btn) return;
        var c = COLORS[mk];
        if (c) {{
            btn.style.setProperty('background',    c, 'important');
            btn.style.setProperty('border-color',  c, 'important');
            btn.style.setProperty('color', 'white', 'important');
        }} else {{
            btn.style.removeProperty('background');
            btn.style.removeProperty('border-color');
            btn.style.removeProperty('color');
        }}
    }});
}}
(function run(n) {{ apply(); if (n > 0) setTimeout(function(){{ run(n-1); }}, 150); }})(10);
</script>""",
        height=0,
    )


def render_assistant_extras(
    sources: list[Any],
    tool_calls: list[dict[str, Any]],
    locale: str,
    query_id: str | None = None,
) -> None:
    if sources:
        label = t("sources_label", locale, count=len(sources))
        with st.expander(label, expanded=False):
            for w in sources:
                payload = getattr(w, "payload", {}) or {}
                cents = payload.get("price_eur_cents")
                price = f"€{cents / 100:.2f}" if cents else "N/A"
                country = payload.get("country", "")
                wine_type = payload.get("type", "")
                title = getattr(w, "title", str(w))
                parts = [p for p in [country, wine_type] if p]
                meta = " · ".join(parts)
                st.markdown(f"**{title}** — {price}" + (f" · {meta}" if meta else ""))

    if tool_calls:
        label = t("actions_label", locale)
        with st.expander(label, expanded=False):
            for tc in tool_calls:
                name = tc.get("tool_name", "?")
                summary = _format_tool_result(name, tc.get("result"), locale)
                if summary:
                    st.markdown(f"🔧 **{name}** → {summary}")
                else:
                    st.code(f"🔧 {name}", language=None)

    render_feedback_buttons(tool_calls, query_id, locale)


def _serialize_sources(sources: list[Any]) -> list[dict[str, Any]]:
    """Convert RetrievedWine objects into plain JSON-serializable dicts."""
    out = []
    for w in sources:
        payload = getattr(w, "payload", {}) or {}
        cents = payload.get("price_eur_cents")
        out.append({
            "title":     getattr(w, "title", None),
            "price_eur": round(cents / 100, 2) if cents else None,
            "country":   payload.get("country"),
            "type":      payload.get("type"),
        })
    return out


def export_messages_json(messages: list[dict[str, Any]]) -> str:
    """Serialize the full conversation (current session) to a JSON string."""
    serializable = []
    for m in messages:
        entry: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        if m.get("sources"):
            entry["sources"] = _serialize_sources(m["sources"])
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        if m.get("filter_used"):
            entry["filter_used"] = m["filter_used"]
        serializable.append(entry)
    return json.dumps(serializable, ensure_ascii=False, indent=2, default=str)


def export_messages_csv(messages: list[dict[str, Any]]) -> str:
    """Flatten the conversation (current session) into a CSV string —
    one row per turn, sources/tools summarised as semicolon-joined lists."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["turn", "role", "content", "sources", "tools_used", "filter_used"])
    for i, m in enumerate(messages, start=1):
        sources = m.get("sources") or []
        source_titles = "; ".join(getattr(w, "title", "") or "" for w in sources)
        tool_names = "; ".join(tc.get("tool_name", "") for tc in (m.get("tool_calls") or []))
        filter_used = m.get("filter_used") or {}
        filter_str = json.dumps(filter_used, ensure_ascii=False) if filter_used else ""
        writer.writerow([i, m["role"], m["content"], source_titles, tool_names, filter_str])
    return buf.getvalue()


def render_chat_history(
    messages: list[dict[str, Any]],
    locale: str,
    user_avatar: str | None = None,
) -> None:
    for msg in messages:
        role = msg["role"]
        avatar = user_avatar if role == "user" else None
        with st.chat_message(role, avatar=avatar):
            if role == "assistant":
                # Badge first — mirrors the live view, where it appears during
                # "Searching catalog", before the answer is even computed.
                render_filter_badge(msg.get("filter_used", {}), msg.get("user_query", ""), locale)
            st.markdown(msg["content"])
            if role == "assistant":
                render_assistant_extras(
                    msg.get("sources", []),
                    msg.get("tool_calls", []),
                    locale,
                    query_id=msg.get("query_id"),
                )
