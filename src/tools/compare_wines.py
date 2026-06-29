"""Tool 4: compare_wines — compare 2–3 named wines side by side."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

FUZZY_THRESHOLD = 80  # minimum similarity score (0–100)


class CompareWinesArgs(BaseModel):
    wines: list[str] = Field(
        ..., min_length=2, max_length=3,
        description="List of 2–3 wine name strings to compare",
    )


def _fuzzy_resolve(name: str, titles: list[str]) -> tuple[str | None, int]:
    """Return (best_match_title, score) or (None, 0) if below threshold."""
    result = process.extractOne(name, titles, scorer=fuzz.WRatio)
    if result and result[1] >= FUZZY_THRESHOLD:
        return result[0], result[1]
    return None, 0


def _run(wines: list[str]) -> dict[str, Any]:
    try:
        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        titles = df["title"].tolist()
        comparison = []
        not_found = []

        for name in wines:
            match, score = _fuzzy_resolve(name, titles)
            if match is None:
                # Offer closest alternatives
                alts = process.extract(name, titles, scorer=fuzz.WRatio, limit=3)
                alt_list = [a[0] for a in alts]
                not_found.append({
                    "query": name,
                    "alternatives": alt_list,
                })
                continue

            row = df[df["title"] == match].iloc[0]
            cents = row.get("price_eur_cents")
            comparison.append({
                "wine_id":     row["wine_id"],
                "title":       row["title"],
                "matched_from": name,
                "price_eur":   round(cents / 100, 2) if cents else None,
                "type":        row.get("type"),
                "grape":       row.get("grape"),
                "country":     row.get("country"),
                "region":      row.get("region"),
                "abv_percent": row.get("abv_percent"),
                "style":       row.get("style"),
                "vintage":     "NV" if row.get("is_nv") else str(int(row["vintage_year"])) if row.get("vintage_year") else None,
                "characteristics": row.get("characteristics"),
            })

        if not_found:
            msg = "; ".join(
                f"{nf['query']!r} not found — closest: {', '.join(nf['alternatives'])}"
                for nf in not_found
            )
            return _ERR("WINE_NOT_FOUND", msg)

        if len(comparison) < 2:
            return _ERR("WINE_NOT_FOUND", "Need at least 2 resolved wines to compare.")

        return {"comparison": comparison}

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


compare_wines = StructuredTool.from_function(
    func=_run,
    name="compare_wines",
    description=(
        "Compare 2–3 specific wines by name across price, ABV, type, country, grape, style. "
        "Uses fuzzy matching to resolve names. Unresolved names → closest alternatives."
    ),
    args_schema=CompareWinesArgs,
)
