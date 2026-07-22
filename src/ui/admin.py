"""Admin panel — dev settings, catalog stats, CSV import, audit log."""
from __future__ import annotations

import io

import streamlit as st

from src.catalog import get_service_db, invalidate_cache
from src.config import CHAT_MODELS, LANGSMITH_ENABLED, LANGSMITH_PROJECT
from src.i18n import t

# Mirrors the CHECK constraint in sql/09_tool_logs_extend.sql — the 5
# original tools + the 2 added in v2.0. Default: all enabled.
_ALL_TOOLS = (
    "filter_wines", "pair_with_food", "calculate_budget", "compare_wines", "wine_stats",
    "explain_wine_concept", "recommend_for_me",
)

# Sentinel for the dev-panel model selectbox — see _resolve_model_override.
_NO_MODEL_OVERRIDE = "— auto (Quick/In-Depth) —"


def _resolve_model_override(selected: str) -> str | None:
    """None means "don't override — let Quick/In-Depth decide" (SPEC §5.6).

    st.selectbox always returns a concrete option, never None — so without
    this sentinel mapping, merely rendering the selectbox (i.e. an admin
    unlocking the dev panel just to look, without touching the dropdown)
    would silently start overriding every user's Quick/In-Depth toggle for
    the rest of the session, since `app.py` treats any truthy
    dev_model_override as "use this instead." Only an explicit pick of a
    real model should override; picking the sentinel again restores normal
    behaviour.
    """
    return None if selected == _NO_MODEL_OVERRIDE else selected


def render_admin(locale: str) -> None:
    st.subheader(t("admin_dev_header", locale))
    _render_dev_settings(locale)
    st.divider()

    st.subheader(t("admin_stats_header", locale))
    _render_stats(locale)
    st.divider()

    st.subheader(t("admin_analytics_header", locale))
    _render_analytics(locale)
    st.divider()

    st.subheader(t("admin_users_header", locale))
    _render_user_stats(locale)
    st.divider()

    st.subheader(t("admin_feedback_header", locale))
    _render_feedback_insights(locale)
    st.divider()

    st.subheader(t("admin_security_header", locale))
    _render_security_events(locale)
    st.divider()

    st.subheader(t("admin_import_header", locale))
    _render_import(locale)
    st.divider()

    st.subheader(t("admin_audit_header", locale))
    _render_audit(locale)


def _render_dev_settings(locale: str) -> None:
    """Real model/temperature/tool-toggle controls + read-only system prompt.

    Everything here is dev-only (US-007): no model name, temperature, or
    system prompt is ever shown outside this password-gated tab. Defaults
    (0.2, all tools enabled) match the end-user path exactly, and the model
    selectbox defaults to the "auto" sentinel (see _resolve_model_override)
    for the same reason — simply unlocking the tab must change nothing until
    an admin explicitly moves a control.
    """
    model_list = [_NO_MODEL_OVERRIDE] + list(CHAT_MODELS.keys())
    current = st.session_state.get("dev_model_override") or _NO_MODEL_OVERRIDE
    idx = model_list.index(current) if current in model_list else 0
    selected_model = st.selectbox(
        t("admin_model_label", locale), options=model_list, index=idx, key="dev_model_select",
    )
    st.session_state.dev_model_override = _resolve_model_override(selected_model)

    st.session_state.dev_temperature = st.slider(
        t("admin_temp_label", locale),
        min_value=0.0, max_value=1.0,
        value=float(st.session_state.get("dev_temperature", 0.2)),
        step=0.05,
        key="dev_temp_slider",
    )

    st.markdown(f"**{t('admin_tools_label', locale)}**")
    enabled_map: dict[str, bool] = dict(st.session_state.get("dev_tools_enabled", {}))
    cols = st.columns(2)
    for i, name in enumerate(_ALL_TOOLS):
        with cols[i % 2]:
            enabled_map[name] = st.checkbox(
                name, value=enabled_map.get(name, True), key=f"dev_tool_{name}"
            )
    st.session_state.dev_tools_enabled = enabled_map

    st.markdown(f"**{t('admin_system_prompt_label', locale)}**")
    from src.agent import _EXPERTISE_NOTES, _LOCALE_NAMES, SYSTEM_PROMPT_TEMPLATE
    locale_name = _LOCALE_NAMES.get(locale, "English")
    st.code(SYSTEM_PROMPT_TEMPLATE.format(
        locale_name=locale_name,
        expertise_note=_EXPERTISE_NOTES["beginner"],
    ), language=None)

    # Diagnostic only — never required, never blocks the app (SPEC §3.5).
    if LANGSMITH_ENABLED:
        st.caption(f"🟢 LangSmith tracing: ON · project `{LANGSMITH_PROJECT or 'default'}`")
    else:
        st.caption("⚪ LangSmith tracing: OFF (no LANGSMITH_API_KEY / LANGSMITH_TRACING set)")

    # Anonymous checkpoint-thread housekeeping (Phase 4, step 3). Manual-only
    # by design — Streamlit Cloud has no cron; an on-startup opportunistic
    # sweep is a possible future option (see docs/PHASE3_HANDOFF.md), not
    # implemented here.
    if st.button(t("admin_sweep_anon_button", locale), key="admin_sweep_anon_btn"):
        with st.spinner("Sweeping…"):
            from src.checkpointer import sweep_anon_threads
            n = sweep_anon_threads()
        st.toast(t("admin_sweep_anon_done", locale, count=n))


def _render_stats(locale: str) -> None:
    try:
        db = get_service_db()
        result = db.table("wines").select("needs_embedding", count="exact").execute()
        total = result.count or len(result.data)
        pending = sum(1 for r in result.data if r.get("needs_embedding"))
        embedded = total - pending

        col1, col2, col3 = st.columns(3)
        col1.metric(t("total_wines", locale), total)
        col2.metric(t("embedded_wines", locale), embedded)
        col3.metric(t("pending_embed", locale), pending)
    except Exception as exc:
        st.error(f"Stats unavailable: {exc}")


_ANALYTICS_WINDOW = 500  # most recent query_logs rows to aggregate over
_BATCH_SIZE = 200        # respects URL length limits on .in_() filters


def _render_analytics(locale: str) -> None:
    try:
        import pandas as pd
        db = get_service_db()

        ql = (
            db.table("query_logs")
            .select("id, created_at, status, locale, latency_ms")
            .order("created_at", desc=True)
            .limit(_ANALYTICS_WINDOW)
            .execute()
        )
        if not ql.data:
            st.info(t("analytics_no_data", locale))
            return

        ql_df = pd.DataFrame(ql.data)
        ql_df["created_at"] = pd.to_datetime(ql_df["created_at"])
        ql_df["date"] = ql_df["created_at"].dt.date
        ids = ql_df["id"].tolist()

        # Queries over time
        st.markdown(f"**{t('analytics_queries_over_time', locale)}**")
        st.bar_chart(ql_df.groupby("date").size())

        # Cost over time — join token_usage (batched .in_() to avoid URL limits)
        tu_rows: list[dict] = []
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            tu = db.table("token_usage").select("query_id, cost_eur_micros").in_("query_id", batch).execute()
            tu_rows.extend(tu.data)

        st.markdown(f"**{t('analytics_cost_over_time', locale)}**")
        if tu_rows:
            tu_df = pd.DataFrame(tu_rows)
            merged = tu_df.merge(ql_df[["id", "date"]], left_on="query_id", right_on="id", how="left")
            cost_by_date = merged.groupby("date")["cost_eur_micros"].sum() / 1_000_000
            st.line_chart(cost_by_date)
        else:
            st.caption(t("analytics_no_data", locale))

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**{t('analytics_status_breakdown', locale)}**")
            st.bar_chart(ql_df["status"].value_counts())
        with col2:
            st.markdown(f"**{t('analytics_locale_breakdown', locale)}**")
            st.bar_chart(ql_df["locale"].value_counts())

        # Tool usage — batched fetch over the same query_id window
        tcl_rows: list[dict] = []
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            tcl = db.table("tool_call_logs").select("tool_name").in_("query_id", batch).execute()
            tcl_rows.extend(tcl.data)

        st.markdown(f"**{t('analytics_tool_usage', locale)}**")
        if tcl_rows:
            tcl_df = pd.DataFrame(tcl_rows)
            st.bar_chart(tcl_df["tool_name"].value_counts())
        else:
            st.caption(t("analytics_no_data", locale))

    except Exception as exc:
        st.error(f"Analytics unavailable: {exc}")


def _render_user_stats(locale: str) -> None:
    """Per-user totals computed on read (Block 2: no new aggregates table) —
    same batched-join pattern as _render_analytics, restricted to non-null
    user_id rows."""
    try:
        import pandas as pd
        db = get_service_db()

        ql = (
            db.table("query_logs")
            .select("id, user_id, created_at")
            .order("created_at", desc=True)
            .limit(_ANALYTICS_WINDOW)
            .execute()
        )
        ql_df = pd.DataFrame(ql.data) if ql.data else pd.DataFrame(columns=["id", "user_id", "created_at"])
        ql_df = ql_df[ql_df["user_id"].notna()]
        if ql_df.empty:
            st.caption(t("analytics_no_data", locale))
            return

        ids = ql_df["id"].tolist()
        tu_rows: list[dict] = []
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            tu = (
                db.table("token_usage")
                .select("query_id, input_tokens, output_tokens, cost_eur_micros")
                .in_("query_id", batch)
                .execute()
            )
            tu_rows.extend(tu.data)
        tu_df = pd.DataFrame(tu_rows) if tu_rows else pd.DataFrame(
            columns=["query_id", "input_tokens", "output_tokens", "cost_eur_micros"]
        )

        fb = db.table("recommendation_feedback").select("user_id, rating").execute()
        fb_df = pd.DataFrame(fb.data) if fb.data else pd.DataFrame(columns=["user_id", "rating"])
        fb_df = fb_df[fb_df["user_id"].notna()]

        stats = ql_df.groupby("user_id").agg(
            query_count=("id", "count"),
            last_active=("created_at", "max"),
        ).reset_index()

        merged = tu_df.merge(ql_df[["id", "user_id"]], left_on="query_id", right_on="id", how="left")
        merged["total_tokens"] = merged["input_tokens"].fillna(0) + merged["output_tokens"].fillna(0)
        tok_cost = merged.groupby("user_id").agg(
            total_tokens=("total_tokens", "sum"),
            total_cost_micros=("cost_eur_micros", "sum"),
        ).reset_index()
        stats = stats.merge(tok_cost, on="user_id", how="left")

        if not fb_df.empty:
            fb_counts = fb_df.groupby(["user_id", "rating"]).size().unstack(fill_value=0).reset_index()
            for col in ("up", "down"):
                if col not in fb_counts.columns:
                    fb_counts[col] = 0
            fb_counts = fb_counts.rename(columns={"up": "feedback_up", "down": "feedback_down"})
            stats = stats.merge(fb_counts[["user_id", "feedback_up", "feedback_down"]], on="user_id", how="left")

        for col in ("total_tokens", "total_cost_micros", "feedback_up", "feedback_down"):
            if col not in stats.columns:
                stats[col] = 0
        stats[["total_tokens", "total_cost_micros", "feedback_up", "feedback_down"]] = (
            stats[["total_tokens", "total_cost_micros", "feedback_up", "feedback_down"]].fillna(0)
        )
        stats["total_cost_eur"] = stats["total_cost_micros"] / 1_000_000

        st.dataframe(
            stats[["user_id", "query_count", "total_tokens", "total_cost_eur",
                   "feedback_up", "feedback_down", "last_active"]],
            use_container_width=True,
        )
    except Exception as exc:
        st.error(f"Per-user stats unavailable: {exc}")


def _render_feedback_insights(locale: str) -> None:
    """Phase 3, step 5 — №2 (per-wine feedback: a purchasing signal) and
    №4 (acceptance rate: continuous online quality metric, complementing the
    offline Ragas evals). Read-only aggregates; the math lives in
    src.feedback_insights so it's unit-testable without Streamlit or a DB."""
    try:
        from src.feedback_insights import feedback_aggregates

        db = get_service_db()
        fb = (
            db.table("recommendation_feedback")
            .select("wine_id, wine_title, rating, query_id, created_at")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        if not fb.data:
            st.caption(t("analytics_no_data", locale))
            return

        qids = list({r["query_id"] for r in fb.data if r.get("query_id")})
        ql_rows: list[dict] = []
        for i in range(0, len(qids), _BATCH_SIZE):
            batch = qids[i : i + _BATCH_SIZE]
            ql = db.table("query_logs").select("id, model, locale").in_("id", batch).execute()
            ql_rows.extend(ql.data)

        agg = feedback_aggregates(fb.data, ql_rows)

        col1, col2, col3 = st.columns(3)
        col1.metric(t("feedback_ratings_total", locale), agg["total_up"] + agg["total_down"])
        acc = agg["overall_acceptance"]
        col2.metric(t("feedback_acceptance_label", locale), f"{acc:.0%}" if acc is not None else "—")
        col3.metric("👍 / 👎", f"{agg['total_up']} / {agg['total_down']}")

        if len(agg["trend"]) > 1:
            st.markdown(f"**{t('feedback_trend_label', locale)}**")
            st.line_chart(agg["trend"])

        st.markdown(f"**{t('feedback_by_wine_label', locale)}**")
        st.dataframe(agg["per_wine"], use_container_width=True)

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if not agg["by_model"].empty:
                st.markdown(f"**{t('feedback_breakdown_model', locale)}**")
                st.dataframe(agg["by_model"], use_container_width=True)
        with bcol2:
            if not agg["by_locale"].empty:
                st.markdown(f"**{t('feedback_breakdown_locale', locale)}**")
                st.dataframe(agg["by_locale"], use_container_width=True)

    except Exception as exc:
        st.error(f"Feedback insights unavailable: {exc}")


def _render_security_events(locale: str) -> None:
    try:
        import pandas as pd
        db = get_service_db()
        result = (
            db.table("security_events")
            .select("created_at, event_type, severity, action_taken, matched_rule, user_query")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        if not result.data:
            st.caption(t("admin_security_empty", locale))
            return
        df = pd.DataFrame(result.data)
        df["user_query"] = df["user_query"].astype(str).str.slice(0, 120)
        st.dataframe(df, use_container_width=True)
    except Exception as exc:
        st.error(f"Security events unavailable: {exc}")


def _render_import(locale: str) -> None:
    uploaded = st.file_uploader(
        t("admin_import_label", locale),
        type=["csv"],
        key="admin_csv_uploader",
    )

    col_sync, col_import = st.columns([1, 2])

    with col_sync:
        if st.button(t("admin_sync_button", locale), key="admin_sync_btn"):
            with st.spinner("Syncing…"):
                try:
                    from src.embeddings import reconcile_embeddings
                    reconcile_embeddings()
                    invalidate_cache()
                    st.success(t("admin_sync_success", locale))
                except Exception as exc:
                    st.error(str(exc))

    with col_import:
        if uploaded and st.button(t("admin_import_button", locale), key="admin_import_btn"):
            with st.spinner("Importing…"):
                try:
                    import pandas as pd
                    from src.ingest import normalise_row, upsert_wines
                    from src.embeddings import reconcile_embeddings

                    df = pd.read_csv(io.StringIO(uploaded.read().decode("utf-8")))
                    rows = []
                    for _, row in df.iterrows():
                        norm = normalise_row(row.to_dict())
                        if norm:
                            rows.append(norm)

                    if rows:
                        upsert_wines(rows)
                        reconcile_embeddings()
                        invalidate_cache()
                        st.success(t("admin_import_success", locale, count=len(rows)))
                    else:
                        st.warning("No valid rows found in CSV.")
                except Exception as exc:
                    st.error(t("admin_import_error", locale, error=str(exc)))


def _render_audit(locale: str) -> None:
    try:
        import pandas as pd
        db = get_service_db()
        result = (
            db.table("catalog_audit")
            .select("created_at, action, actor, wine_id, diff")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        if result.data:
            df = pd.DataFrame(result.data)
            show_cols = [c for c in ["created_at", "action", "actor", "wine_id"] if c in df.columns]
            st.dataframe(df[show_cols], use_container_width=True)
        else:
            st.info("No audit entries yet.")
    except Exception as exc:
        st.error(f"Audit log unavailable: {exc}")
