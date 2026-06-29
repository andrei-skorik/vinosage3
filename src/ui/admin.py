"""Admin panel — catalog stats, CSV import, audit log."""
from __future__ import annotations

import io

import streamlit as st

from src.catalog import get_service_db, invalidate_cache
from src.i18n import t


def render_admin(locale: str) -> None:
    st.subheader(t("admin_stats_header", locale))
    _render_stats(locale)
    st.divider()

    st.subheader(t("admin_analytics_header", locale))
    _render_analytics(locale)
    st.divider()

    st.subheader(t("admin_import_header", locale))
    _render_import(locale)
    st.divider()

    st.subheader(t("admin_audit_header", locale))
    _render_audit(locale)


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
