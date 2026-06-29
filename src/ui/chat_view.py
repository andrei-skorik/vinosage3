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
    except Exception:
        return str(result)

    return str(result)


def render_assistant_extras(
    sources: list[Any],
    tool_calls: list[dict[str, Any]],
    locale: str,
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
                )
