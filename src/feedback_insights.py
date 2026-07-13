"""Pure aggregation for the admin "Recommendation feedback" section.

Phase 3, step 5 — features №2 (per-wine feedback table: a purchasing signal
for the shop) and №4 (acceptance rate: a free, continuous online quality
metric complementing the offline Ragas evals).

No Streamlit, no DB here: this module takes plain row dicts and returns
DataFrames/scalars, so the math is unit-testable in isolation. The fetching
and rendering live in src/ui/admin.py (_render_feedback_insights), following
the same service-role + batched-.in_() pattern as _render_user_stats.
"""
from __future__ import annotations

from typing import Any


def feedback_aggregates(
    fb_rows: list[dict[str, Any]],
    ql_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate recommendation_feedback rows into admin-panel views.

    Args:
        fb_rows: recommendation_feedback dicts with at least
            wine_id, wine_title, rating, query_id, created_at.
        ql_rows: query_logs dicts (id, model, locale) for the involved
            query_ids — enables the by-model / by-locale breakdowns.
            Optional: without it those breakdowns come back empty.

    Returns dict:
        total_up / total_down: int
        overall_acceptance: float in [0,1] | None (no ratings yet)
        per_wine:  DataFrame [wine, up, down, total, down_share] sorted by
                   total desc — the purchasing signal (№2)
        trend:     Series acceptance-by-date (feedback's own created_at)
        by_model / by_locale: DataFrame [value, up, down, acceptance] (№4)
    """
    import pandas as pd

    empty = {
        "total_up": 0, "total_down": 0, "overall_acceptance": None,
        "per_wine": pd.DataFrame(), "trend": pd.Series(dtype=float),
        "by_model": pd.DataFrame(), "by_locale": pd.DataFrame(),
    }

    fb = pd.DataFrame(fb_rows) if fb_rows else pd.DataFrame()
    if fb.empty or "rating" not in fb.columns:
        return empty
    fb = fb[fb["rating"].isin(["up", "down"])].copy()
    if fb.empty:
        return empty

    total_up = int((fb["rating"] == "up").sum())
    total_down = int((fb["rating"] == "down").sum())
    overall = total_up / (total_up + total_down)

    # ── №2: per-wine table ────────────────────────────────────────────────────
    # wine_title is denormalised in sql/08 precisely so this survives wine
    # deletion; fall back to the id for legacy rows without a title.
    if "wine_title" in fb.columns:
        fb["wine"] = fb["wine_title"].fillna(fb.get("wine_id"))
    else:
        fb["wine"] = fb.get("wine_id")
    per_wine = (
        fb.groupby("wine")["rating"].value_counts().unstack(fill_value=0)
    )
    for col in ("up", "down"):
        if col not in per_wine.columns:
            per_wine[col] = 0
    per_wine["total"] = per_wine["up"] + per_wine["down"]
    per_wine["down_share"] = (per_wine["down"] / per_wine["total"]).round(2)
    per_wine = (
        per_wine[["up", "down", "total", "down_share"]]
        .sort_values(["total", "down_share"], ascending=[False, False])
        .reset_index()
    )

    # ── №4: acceptance trend by date ─────────────────────────────────────────
    trend = pd.Series(dtype=float)
    if "created_at" in fb.columns:
        dated = fb[fb["created_at"].notna()].copy()
        if not dated.empty:
            dated["date"] = pd.to_datetime(dated["created_at"]).dt.date
            trend = dated.groupby("date")["rating"].apply(
                lambda s: float((s == "up").mean())
            )

    # ── №4: by-model / by-locale via the query_logs join ─────────────────────
    def _rate_by(df: "pd.DataFrame", col: str) -> "pd.DataFrame":
        if col not in df.columns or df[col].isna().all():
            return pd.DataFrame()
        g = df.copy()
        g[col] = g[col].fillna("—")
        out = g.groupby(col)["rating"].value_counts().unstack(fill_value=0)
        for c in ("up", "down"):
            if c not in out.columns:
                out[c] = 0
        out["acceptance"] = (out["up"] / (out["up"] + out["down"])).round(2)
        return out[["up", "down", "acceptance"]].sort_values("acceptance").reset_index()

    by_model = pd.DataFrame()
    by_locale = pd.DataFrame()
    ql = pd.DataFrame(ql_rows) if ql_rows else pd.DataFrame()
    if not ql.empty and "id" in ql.columns and "query_id" in fb.columns:
        joined = fb.merge(
            ql.rename(columns={"id": "query_id"}),
            on="query_id", how="left", suffixes=("", "_ql"),
        )
        by_model = _rate_by(joined, "model")
        by_locale = _rate_by(joined, "locale")

    return {
        "total_up": total_up, "total_down": total_down,
        "overall_acceptance": overall,
        "per_wine": per_wine, "trend": trend,
        "by_model": by_model, "by_locale": by_locale,
    }
