"""Tool 5: wine_stats — aggregate metrics over the catalog. Numbers only."""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

VALID_METRICS = {"count", "avg_price", "min_price", "max_price", "avg_abv"}


class WineStatsFilters(BaseModel):
    type:          Optional[str]   = None
    grape:         Optional[str]   = None
    country:       Optional[str]   = None
    region:        Optional[str]   = None
    style:         Optional[str]   = None
    max_price_eur: Optional[float] = None


class WineStatsArgs(BaseModel):
    metric:  str                    = Field(..., description="count | avg_price | min_price | max_price | avg_abv")
    filters: Optional[WineStatsFilters] = Field(None)


def _run(
    metric: str,
    filters: WineStatsFilters | None = None,
) -> dict[str, Any]:
    try:
        if metric not in VALID_METRICS:
            return _ERR(
                "INVALID_ARGS",
                f"Unknown metric {metric!r}. Use one of: {', '.join(sorted(VALID_METRICS))}",
            )

        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        mask = df["is_active"].notna()

        if filters:
            if filters.type:
                mask = mask & (df["type"] == filters.type)
            if filters.grape:
                mask = mask & df["grape"].str.contains(filters.grape, case=False, na=False)
            if filters.country:
                mask = mask & (df["country"].str.lower() == filters.country.lower())
            if filters.region:
                mask = mask & df["region"].str.contains(filters.region, case=False, na=False)
            if filters.style:
                mask = mask & df["style"].str.contains(filters.style, case=False, na=False)
            if filters.max_price_eur is not None:
                max_cents = int(filters.max_price_eur * 100)
                mask = mask & (df["price_eur_cents"].notna() & (df["price_eur_cents"] <= max_cents))

        subset = df[mask]

        if subset.empty:
            return _ERR(
                "NO_MATCH",
                f"No wines match the filters; cannot compute {metric}.",
            )

        if metric == "count":
            value = int(len(subset))
            return {"metric": metric, "value": value, "sample_size": value, "filters": filters.model_dump() if filters else {}}

        if metric in ("avg_price", "min_price", "max_price"):
            price_col = subset["price_eur_cents"].dropna()
            if price_col.empty:
                return _ERR("NO_MATCH", "No wines with parseable price in this filter.")
            if metric == "avg_price":
                val = round(float(price_col.mean()) / 100, 2)
            elif metric == "min_price":
                val = round(float(price_col.min()) / 100, 2)
            else:
                val = round(float(price_col.max()) / 100, 2)
            return {
                "metric": metric,
                "value_eur": val,
                "sample_size": int(len(price_col)),
                "filters": filters.model_dump() if filters else {},
            }

        if metric == "avg_abv":
            abv_col = subset["abv_percent"].dropna()
            if abv_col.empty:
                return _ERR("NO_MATCH", "No wines with ABV data in this filter.")
            return {
                "metric": metric,
                "value_abv": round(float(abv_col.mean()), 2),
                "sample_size": int(len(abv_col)),
                "filters": filters.model_dump() if filters else {},
            }

        return _ERR("INVALID_ARGS", f"Unhandled metric: {metric}")

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


wine_stats = StructuredTool.from_function(
    func=_run,
    name="wine_stats",
    description=(
        "Compute aggregate statistics over the catalog: count, avg/min/max price, avg ABV. "
        "Returns numbers only — never a wine list. Use filter_wines to list wines."
    ),
    args_schema=WineStatsArgs,
)
