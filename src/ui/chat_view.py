"""Chat view helpers — rendering history, empty state, and message details."""
from __future__ import annotations

import csv
import io
import json
import random
import re
from typing import Any

import streamlit as st

from src.i18n import t, tlist

_EXAMPLE_COUNT = 3


_SUGGESTION_ICONS = ("🍷", "🍾")


def render_empty_state(locale: str) -> None:
    """Render the welcome screen. Clicked button label is written to queued_prompt."""
    with st.container(key="welcome"):
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
        with st.container(key="suggestions"):
            cols = st.columns(len(picks))
            for i, (col, label) in enumerate(zip(cols, picks)):
                icon = _SUGGESTION_ICONS[i % len(_SUGGESTION_ICONS)]
                with col:
                    if st.button(f"{icon} {label}", use_container_width=True, key=f"example_{i}"):
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


# Typographic-to-ASCII normalization map (Phase 3, step 6g). LLMs routinely
# rewrite curly quotes, long dashes, and non-breaking spaces as their plain
# ASCII forms, so an exact substring match between a catalog title and the
# model's reply silently fails for any wine whose title contains typography
# (the 'White Ash' incident: catalog stores curly quotes, the LLM emitted
# straight ones, and the wine lost its feedback buttons).
_TYPOGRAPHY = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # ' ' ‚ ‛
    "′": "'", "´": "'", "`": "'",                        # ′ ´ `
    "“": '"', "”": '"', "„": '"', "‟": '"',  # " " „ ‟
    "–": "-", "—": "-", "−": "-",                  # – — −
    " ": " ",                                                  # nbsp
})


def _normalize_for_match(s: str) -> str:
    """Casefold + typography-to-ASCII + whitespace collapse, for robust
    title-in-text matching. Deterministic; no fuzzy matching needed."""
    s = s.translate(_TYPOGRAPHY)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _title_in_response(title: str, response_text: str) -> bool:
    """True if the wine's brand+variety name appears in the LLM response.

    Strips the vintage year and region (after the first comma) before matching
    so that "Whale Cove Sauvignon Blanc 2021/22, South Africa" matches the
    response text "Whale Cove Sauvignon Blanc" regardless of formatting.
    Both sides are typography-normalized (see _normalize_for_match): the
    catalog stores curly quotes ('White Ash') while LLMs emit straight ones
    ('White Ash'), and a raw substring check breaks on exactly that.
    """
    clean = re.sub(r",.*$", "", title)                          # drop region
    clean = re.sub(r"\s+\d{4}(?:/\d{2,4})?$", "", clean)      # drop vintage
    clean = _normalize_for_match(clean)
    if not clean:
        return True
    return clean in _normalize_for_match(response_text)


def _recommended_wines_for_feedback(
    tool_calls: list[dict[str, Any]],
    response_text: str = "",
) -> list[dict[str, Any]]:
    """Wines worth collecting 👍/👎 on — only pair_with_food / recommend_for_me
    results (SPEC §4.2): those are the tools that actually recommended
    specific wines, unlike filter_wines/compare_wines/wine_stats.

    When response_text is provided, only wines whose name actually appears in
    the LLM's reply are included — this prevents feedback buttons from showing
    up for wines the tool fetched but the model chose not to present.
    """
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
        elif tc.get("tool_name") == "filter_wines":
            items = result.get("wines") or []
        else:
            continue
        for w in items:
            wid = w.get("wine_id")
            if not wid or wid in seen_ids:
                continue
            if response_text and not _title_in_response(w.get("title", ""), response_text):
                continue
            seen_ids.add(wid)
            wines.append(w)
    return wines


def _fold_profile_dict(
    profile: dict[str, Any],
    wine: dict[str, Any],
    direction: str,
    delta: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Mirror fold_feedback's logic (SPEC §5.4 + Phase 3 step 6h provenance)
    onto a plain profile dict.

    Extracted from _fold_cache's closure so it is unit-testable directly.
    Unified (step 6h) with fold_feedback's own pure math — this calls the
    SAME _compute_and_apply_fold / _revert_fold_delta functions preferences.py
    uses, instead of maintaining a second copy that can silently drift out of
    sync (which is exactly what happened before step 6f's parity test).

    direction == "up" / "down": computes and applies its own fresh delta from
    `wine`'s attributes (identical math to fold_feedback given the same
    starting profile).
    direction == "none": reverts EXACTLY the `delta` passed in (the caller
    reads it from the row's recorded reason) — never a blanket removal.
    Falsy/missing `delta` means "revert nothing", the safe default.
    """
    from src.preferences import _compute_and_apply_fold, _revert_fold_delta

    p: dict[str, Any] = dict(profile)
    pt  = set(p.get("preferred_types")  or [])
    pg  = set(p.get("preferred_grapes") or [])
    ps  = set(p.get("preferred_styles") or [])
    dt  = set(p.get("disliked_types")   or [])
    dg  = set(p.get("disliked_grapes")  or [])
    ds  = set(p.get("disliked_styles")  or [])

    if direction in ("up", "down"):
        _compute_and_apply_fold(pt, pg, ps, dt, dg, ds, wine, direction)
    elif direction == "none" and delta:
        _revert_fold_delta(pt, pg, ps, dt, dg, ds, delta)

    p.update({
        "preferred_types":  sorted(pt),
        "preferred_grapes": sorted(pg),
        "preferred_styles": sorted(ps),
        "disliked_types":   sorted(dt),
        "disliked_grapes":  sorted(dg),
        "disliked_styles":  sorted(ds),
    })
    return p


def _rating_key(query_id: str | None, wine_id: str) -> str:
    """Composite identity a card's feedback state is scoped by.

    The write path (log_feedback/delete_feedback/get_feedback_reason) and
    the container/button widget keys were already scoped by (query_id,
    wine_id) — this is the SAME scoping applied to the in-memory `ratings`
    cache and the CSS marker that drives the highlight JS, both of which
    used to key on wine_id alone. Without it, rating a wine in one turn
    visually "leaked" its colour onto every other turn's card for that same
    wine (the recommend_for_me repeat-recommendation scenario in particular).
    """
    return f"{query_id}:{wine_id}"


def _toggle_feedback(
    wine: dict[str, Any],
    direction: str,
    *,
    ratings: dict[str, str | None],
    user_id: str | None,
    session_id: str,
    query_id: str | None,
    locale: str,
    fold_cache: Any = None,
) -> None:
    """Persist (or clear) one wine's rating (US-005).

    Extracted from render_feedback_buttons' render loop so it is unit-testable
    without a Streamlit context (Phase 3 step 6, gap #1) — pure refactor, zero
    behavior change. Anonymous users (user_id=None) write nothing to the DB —
    log_feedback, fold_feedback, and delete_feedback are all gated on user_id
    (Phase 3 step 6b): with no user_id, recommendation_feedback's
    unique(user_id, query_id, wine_id) can't deduplicate NULL-user rows
    (Postgres NULL != NULL), so anonymous re-taps would insert duplicates and
    skew the admin feedback-insights analytics (SPEC Appendix B; CLAUDE.md:
    "anonymous users never write preferences/feedback to the DB"). The UI
    layer (render_feedback_buttons) hides these buttons entirely for
    anonymous users; this gate is defense-in-depth behind that.

    Un-fold is the exact inverse of fold, not a blanket wipe (Phase 3 step
    6h): every applied fold's delta is serialized into the feedback row's
    `reason` column, and a toggle-off (or a rating flip) reverts EXACTLY
    that delta — read back via get_feedback_reason — before the row is
    deleted (toggle-off) or the new rating's fold is applied (flip). A
    missing/legacy/unparseable reason reverts nothing, the safe default.
    """
    from src.logging_db import delete_feedback, get_feedback_reason, log_feedback
    from src.preferences import fold_feedback

    wine_id = str(wine.get("wine_id", ""))
    key = _rating_key(query_id, wine_id)
    previous = ratings.get(key)

    if previous == direction:
        # Toggle off: revert exactly what the active fold recorded, then
        # delete the row (delete_feedback removes ALL rows for this wine,
        # matching its existing no-query_id-scoped behavior).
        ratings[key] = None
        if user_id:
            reason = get_feedback_reason(user_id=user_id, query_id=query_id, wine_id=wine_id)
            fold_feedback(user_id, wine, "none", delta=reason)
            delete_feedback(user_id=user_id, wine_id=wine_id)
            if fold_cache:
                fold_cache(wine, "none", delta=reason)
        return

    # Flipping from an active opposite rating (down->up or up->down): revert
    # the outgoing rating's recorded delta FIRST, so the profile never holds
    # more than one active fold per (user, wine) at a time. Read the reason
    # before log_feedback's upsert below overwrites this same row.
    if user_id and previous:
        prior_reason = get_feedback_reason(user_id=user_id, query_id=query_id, wine_id=wine_id)
        if prior_reason:
            fold_feedback(user_id, wine, "none", delta=prior_reason)
            if fold_cache:
                fold_cache(wine, "none", delta=prior_reason)

    ratings[key] = direction
    if not user_id:
        return

    _, applied_delta = fold_feedback(user_id, wine, direction)
    ok = log_feedback(
        session_id=session_id,
        query_id=query_id,
        wine_id=wine.get("wine_id"),
        wine_title=wine.get("title"),
        rating=direction,
        user_id=user_id,
        reason=json.dumps(applied_delta),
    )
    if ok:
        if fold_cache:
            fold_cache(wine, direction)
        st.toast(t("feedback_saved", locale))


def _hydrate_feedback_ratings(user_id: str, ratings: dict[str, str | None]) -> None:
    """Back-fill `ratings` from `recommendation_feedback`, exactly once per
    session (docs/phase3.1/fix_feedback_hydration).

    Extracted from render_feedback_buttons so it's unit-testable without a
    Streamlit context (same rationale as _toggle_feedback). `ratings` is a
    same-session accelerator only — clicks keep it current via
    _toggle_feedback, but a FRESH session (logout->login, or a plain F5
    restoring the durable thread via the checkpointer) starts with none,
    even though the DB still holds every prior rating. Without this,
    rehydrated cards render grey — not because the rating was lost, but
    because it was never read back into the UI.

    Guarded by `_feedback_hydrated` — the SAME key
    `src/ui/session_reset.py::reset_to_anonymous` clears on logout/forget-me,
    so a fresh login re-hydrates instead of trusting a stale "already done"
    flag carried over from the previous session in the same browser tab.
    Collects every query_id across the WHOLE session's message history (not
    just the turn currently rendering) so one hydration covers the entire
    rehydrated conversation.
    """
    if st.session_state.get("_feedback_hydrated"):
        return

    from src.logging_db import get_feedback_ratings

    all_query_ids = [
        m.get("query_id") for m in st.session_state.get("messages", []) if m.get("query_id")
    ]
    loaded = get_feedback_ratings(user_id, all_query_ids)
    ratings.update({_rating_key(qid, wid): rating for (qid, wid), rating in loaded.items()})
    st.session_state["_feedback_hydrated"] = True


def render_feedback_buttons(
    tool_calls: list[dict[str, Any]],
    query_id: str | None,
    locale: str,
    response_text: str = "",
) -> None:
    """👍/👎 under each recommended wine (US-005).

    Buttons turn green (👍) or red (👎) when active.  Clicking the same
    button again toggles the rating off and the button returns to white.
    State lives in st.session_state['wine_ratings'] for the browser session.
    A failed DB write is silent — only success triggers st.toast (SPEC §5.4).

    Colouring mechanism: each button label embeds a zero-width space (U+200B)
    followed by a unique marker string (_rating_key(query_id, wine_id) +
    direction suffix — NOT wine_id alone, see the fix note by `mines` below)
    that is completely invisible to the user.  A single components.v1.html() call
    injects JS that scans all <button> elements in the parent document for this
    hidden marker, then either sets the active colour or removes any previously
    set inline styles (= toggle-off reset).  This avoids the layout-shift
    problem caused by injecting hidden <span> elements via st.markdown and also
    correctly resets buttons that were coloured in a prior render cycle.
    """
    if not query_id:
        return
    wines = _recommended_wines_for_feedback(tool_calls, response_text)
    if not wines:
        return

    import streamlit.components.v1 as components

    session_id = st.session_state.get("session_id", "")
    auth = st.session_state.get("auth")
    user_id = auth.get("user_id") if auth else None

    # Anonymous users never write feedback to the DB (Phase 3 step 6b — see
    # _toggle_feedback's docstring for the NULL-dedup rationale). Hiding the
    # buttons entirely, rather than rendering them and letting the gate in
    # _toggle_feedback silently no-op, avoids a UI that looks broken (a click
    # with no visible effect and no toast).
    if not user_id:
        st.caption(t("feedback_login_hint", locale))
        return

    if "wine_ratings" not in st.session_state:
        st.session_state["wine_ratings"] = {}
    ratings: dict[str, str | None] = st.session_state["wine_ratings"]
    _hydrate_feedback_ratings(user_id, ratings)

    def _fold_cache(wine: dict[str, Any], direction: str, delta: dict[str, list[str]] | None = None) -> None:
        """Mirror fold_feedback's logic onto _prefs_cache in-place.

        fold_feedback() already wrote the change to Supabase; this function
        applies the same mutation (via _fold_profile_dict) to the cached
        profile dict so the sidebar reflects the new preference on the very
        next rerun — no extra DB round-trip needed.  Then the multiselect
        widget keys are popped so Streamlit re-initialises them from the
        updated cache (widgets ignore `default` when their key already
        exists in session_state). `delta` is forwarded for direction="none"
        reverts (Phase 3 step 6h) — ignored for "up"/"down", which compute
        their own fresh delta from `wine`.
        """
        cache = st.session_state.get("_prefs_cache")
        if not cache:
            return
        p = _fold_profile_dict(cache, wine, direction, delta=delta)
        # Store as a pending update.  The sidebar's render_taste_profile() reads
        # this key at the TOP of its execution — before any multiselect renders —
        # and applies it to both _prefs_cache and the widget keys.  Setting widget
        # keys before the widget renders is the only reliable Streamlit pattern;
        # setting them after the widget has already rendered in the same run is
        # silently discarded on reruns caused by st.rerun() in some versions.
        st.session_state["_pending_profile_update"] = p

    def _toggle(wine: dict[str, Any], direction: str) -> None:
        _toggle_feedback(
            wine, direction,
            ratings=ratings, user_id=user_id, session_id=session_id,
            query_id=query_id, locale=locale, fold_cache=_fold_cache,
        )

    # color_map: active marker → CSS colour (absent = reset to default).
    # mines:     ALL markers for THIS message's wines — scopes the JS so it
    #            never touches buttons belonging to a different message.
    #            The marker itself must be (query_id, wine_id)-derived, not
    #            wine_id alone: the injected JS matches markers by class name
    #            across the WHOLE parent document (querySelectorAll has no
    #            per-message scoping), so a wine_id-only marker is identical
    #            across every turn that recommends the same wine — one
    #            turn's script would then recolour (or reset) a sibling
    #            turn's card for that wine, same leak as the ratings-dict one.
    color_map: dict[str, str] = {}
    mines: dict[str, bool] = {}

    for w in wines:
        wine_id = str(w.get("wine_id", ""))
        key = _rating_key(query_id, wine_id)
        current = ratings.get(key)
        safe = key.replace("-", "").replace(":", "")   # valid CSS class (alnum only)
        mk_u, mk_d = "fbm" + safe + "u", "fbm" + safe + "d"
        mines[mk_u] = True
        mines[mk_d] = True

        if current == "up":
            color_map[mk_u] = "#28a745"
        elif current == "down":
            color_map[mk_d] = "#dc3545"

        with st.container(border=True, key=f"wine_card_{query_id}_{wine_id}"):
            col_label, col_up, col_down = st.columns([6, 1, 1], vertical_alignment="center")

            meta_parts = [p for p in (w.get("region") or w.get("country"),) if p]
            price = w.get("price_eur")
            if price is not None:
                meta_parts.append(f"€{price:.2f}")
            meta = " · ".join(meta_parts)
            label_md = f"**{w.get('title', '')}**"
            if meta:
                label_md += f"  \n:gray[{meta}]"
            col_label.markdown(label_md)

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
    response_text: str = "",
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

    render_feedback_buttons(tool_calls, query_id, locale, response_text)


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
        avatar = (user_avatar or "👤") if role == "user" else "🍷"
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
                    response_text=msg.get("content", ""),
                )
