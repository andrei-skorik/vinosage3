"""Tool 1: filter_wines — return wines matching hard constraints."""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

VALID_TYPES = {"Red", "White", "Rosé", "Tawny", "Orange", "Brown", "Mixed"}


class FilterWinesArgs(BaseModel):
    type:          Optional[str]   = Field(None, description="Wine type: Red/White/Rosé/Tawny/Orange/Brown/Mixed")
    grape:         Optional[str]   = Field(None, description="Grape variety (partial match ok)")
    country:       Optional[str]   = Field(None, description="Country of origin")
    region:        Optional[str]   = Field(None, description="Region")
    style:         Optional[str]   = Field(None, description="Style label")
    min_price_eur: Optional[float] = Field(None, ge=0)
    max_price_eur: Optional[float] = Field(None, ge=0)
    min_abv:       Optional[float] = Field(None, ge=0, le=25)
    max_abv:       Optional[float] = Field(None, ge=0, le=25)
    limit:         int             = Field(5, ge=1, le=20)


def _run(
    type: str | None = None,
    grape: str | None = None,
    country: str | None = None,
    region: str | None = None,
    style: str | None = None,
    min_price_eur: float | None = None,
    max_price_eur: float | None = None,
    min_abv: float | None = None,
    max_abv: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    try:
        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        mask = df["is_active"].notna()  # all-True Series with correct index

        if type:
            if type not in VALID_TYPES:
                known = sorted(VALID_TYPES)
                return _ERR("UNKNOWN_VALUE", f"Type {type!r} not valid. Use one of: {', '.join(known)}")
            mask = mask & (df["type"] == type)

        if grape:
            mask = mask & df["grape"].str.contains(grape, case=False, na=False)

        if country:
            mask = mask & (df["country"].str.lower() == country.lower())

        if region:
            mask = mask & df["region"].str.contains(region, case=False, na=False)

        if style:
            mask = mask & df["style"].str.contains(style, case=False, na=False)

        if min_price_eur is not None:
            min_cents = int(min_price_eur * 100)
            mask = mask & (df["price_eur_cents"].notna() & (df["price_eur_cents"] >= min_cents))

        if max_price_eur is not None:
            max_cents = int(max_price_eur * 100)
            mask = mask & (df["price_eur_cents"].notna() & (df["price_eur_cents"] <= max_cents))

        if min_abv is not None:
            mask = mask & (df["abv_percent"].notna() & (df["abv_percent"] >= min_abv))

        if max_abv is not None:
            mask = mask & (df["abv_percent"].notna() & (df["abv_percent"] <= max_abv))

        results = df[mask].head(limit)

        if results.empty:
            # Build helpful suggestions
            known_countries = sorted(df["country"].dropna().unique().tolist())
            known_grapes = sorted(df["grape"].dropna().unique().tolist())[:10]
            return _ERR(
                "NO_MATCH",
                f"No wines match the filters. "
                f"Known countries: {', '.join(known_countries[:8])}… "
                f"Known grapes: {', '.join(known_grapes)}…",
            )

        wines = []
        for _, row in results.iterrows():
            cents = row.get("price_eur_cents")
            wines.append({
                "wine_id":     row["wine_id"],
                "title":       row["title"],
                "price_eur":   round(cents / 100, 2) if cents else None,
                "type":        row.get("type"),
                "grape":       row.get("grape"),
                "country":     row.get("country"),
                "region":      row.get("region"),
                "abv_percent": row.get("abv_percent"),
                "style":       row.get("style"),
                "description": row.get("description") or "",
                "vintage":     "NV" if row.get("is_nv") else str(int(row["vintage_year"])) if row.get("vintage_year") else None,
            })

        return {"count": len(wines), "wines": wines}

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


filter_wines = StructuredTool.from_function(
    func=_run,
    name="filter_wines",
    description=(
        "Return catalog wines matching hard constraints (type, grape, country, "
        "region, style, price range, ABV). Use wine_stats for aggregates."
    ),
    args_schema=FilterWinesArgs,
)
