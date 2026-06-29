"""Tool 2: pair_with_food — recommend wines for a given dish."""
from __future__ import annotations

import re
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

# Compound patterns for keywords that also appear as tasting-note descriptors.
# A simple word-boundary match would produce false positives:
#   "dark chocolate, vanilla and spice"  → TASTING NOTE  (no match wanted)
#   "with a chocolate dessert"           → FOOD PAIRING  (match wanted)
# Each pattern requires the keyword to appear in a food-pairing context.
_COMPOUND_FOOD_PATTERNS: dict[str, str] = {
    "chocolate": (
        # "chocolate [food]" — chocolate modifying an actual food item
        r"\bchocolate\s+(?:pudding|puddings|dessert|desserts|cake|cakes|mousse|"
        r"fondue|brownie|brownies|ice\s*cream|fondant|torte|tart|tarts|truffle|"
        r"fudge|ganache|souffl[eé])\b"
        # "with/for [a] chocolate" — chocolate itself is the dish
        r"|\b(?:with|for|alongside)\s+(?:a\s+)?chocolate\b(?!\s+(?:note|hint|flavou?r|"
        r"touch|character|aroma))"
    ),
    # "notes of chocolate cake" → TASTING NOTE  (no match)
    # "pairs with a chocolate cake" → FOOD PAIRING  (match)
    "cake": (
        r"\b(?:with|for|alongside)\s+(?:a\s+)?(?:\w+\s+){0,2}cakes?\b"
        r"(?!-like|\s+like|\s+note|\s+notes|\s+hint|\s+flavou?rs?|\s+character|\s+aroma)"
    ),
}


# Whitelist of actual food nouns. Only words from the dish name that appear in
# this set become individual search keywords. Adjective descriptors ("dark",
# "rich", "light", "milk", "white") are excluded automatically — preventing
# false positives like "dark cherry" matching a "dark chocolate cake" query.
_FOOD_NOUNS = frozenset({
    # NOTE: "cake" is intentionally absent. "Cake" appears in catalog descriptions as
    # many different types (Madeira cake, fish cakes, chocolate cake). Extracting it as
    # an individual keyword from multi-word dishes like "dark chocolate cake" causes
    # false matches (e.g. wines paired with Madeira cake or fish cakes). The "chocolate"
    # compound pattern already handles "chocolate cake" via \bchocolate\s+cake\b.
    # When the user's dish IS "cake" (single word), the full phrase is used directly.
    "chocolate", "steak", "beef", "lamb", "venison", "pork",
    "chicken", "turkey", "duck", "salmon", "tuna", "fish", "seafood", "lobster",
    "shrimp", "oyster", "sushi", "pasta", "pizza", "risotto", "mushroom", "truffle",
    "cheese", "salad", "barbecue", "curry", "spicy", "tagine", "casserole", "meat",
    "pudding", "puddings", "mousse", "fondue", "brownie", "brownies", "tart", "tarts",
    "bread", "brioche", "flatbread", "noodle", "noodles", "dumpling", "dumplings",
    "prawn", "prawns", "crab", "squid", "octopus", "scallop", "scallops",
    "quail", "pheasant", "burger", "soup", "stew", "chilli", "chili", "tapas",
})


def _desc_keywords(dish: str) -> list[str]:
    """Extract food nouns from a dish name.

    Only known food nouns become individual keywords — descriptors like 'dark',
    'rich', 'milk', 'white' are excluded automatically because they are not in
    _FOOD_NOUNS. This prevents false positives such as 'dark cherry' in a wine
    description matching a 'dark chocolate cake' query.
    The full dish phrase is always included first for exact multi-word matching.
    """
    words = [w for w in re.split(r'\W+', dish.lower()) if w in _FOOD_NOUNS]
    return list(dict.fromkeys([dish.lower()] + words))


def _desc_mentions_food(desc, title, keywords: list[str]) -> bool:
    """
    Return True only if the description mentions a keyword as a food (lowercase),
    NOT as part of a wine/product name (which would be capitalised).

    Example: "stand up to chocolate puddings" → match (lowercase 'chocolate').
             "the man behind The Chocolate Block" → no match ('Chocolate' is capitalised).

    Handles NULL descriptions (NaN from pandas) gracefully — returns False.
    """
    if not isinstance(desc, str):
        return False
    for kw in keywords:
        if kw in _COMPOUND_FOOD_PATTERNS:
            # Use compound pattern to avoid matching tasting-note uses
            # e.g. "dark chocolate notes" ≠ "with a chocolate dessert"
            if re.search(_COMPOUND_FOOD_PATTERNS[kw], desc):
                return True
        else:
            # Simple case-sensitive word-boundary match for other foods
            if re.search(r'\b' + re.escape(kw) + r'\b', desc):
                return True
    return False


class PairWithFoodArgs(BaseModel):
    dish:          str            = Field(..., min_length=2, description="Dish or cuisine name")
    prefer_type:   str            = Field("any", description="Red/White/Rosé/any")
    max_price_eur: Optional[float]= Field(None, ge=0)
    limit:         int            = Field(3, ge=1, le=8)


def _run(
    dish: str,
    prefer_type: str = "any",
    max_price_eur: float | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    try:
        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        active = df["is_active"].notna()
        keywords = _desc_keywords(dish)

        # ── Priority 1: wines whose description explicitly mentions this food ──
        # Use title-aware matching to exclude wine-name false positives.
        desc_hit = df.apply(
            lambda row: _desc_mentions_food(
                row.get("description") or "", row.get("title") or "", keywords
            ),
            axis=1,
        )
        catalog_matches = df[active & desc_hit].copy()
        catalog_matches["_source"] = "catalog_description"

        if prefer_type and prefer_type != "any":
            catalog_matches = catalog_matches[catalog_matches["type"] == prefer_type]

        if max_price_eur is not None:
            max_cents = int(max_price_eur * 100)
            catalog_matches = catalog_matches[
                catalog_matches["price_eur_cents"].notna() &
                (catalog_matches["price_eur_cents"] <= max_cents)
            ]

        # Only catalog-description evidence is ever returned — no style/type
        # fallback rules. A fallback would let the LLM invent pairing claims
        # for dishes the catalog never actually confirms.
        pool = catalog_matches.sort_values("price_eur_cents", ascending=True)

        if pool.empty:
            return {
                "dish": dish,
                "pairings": [],
                "result": "no_match",
                "agent_instruction": (
                    f"Search result: zero catalog wines mention {dish!r} in their description. "
                    f"Tell the customer directly (no apology) that the catalog has no specific "
                    f"recommendation for this dish. You may suggest they browse by wine style "
                    f"(e.g. Tawny Port for chocolate, white wines for fish) without naming "
                    f"specific wines as pairings."
                ),
            }

        results = pool.head(limit)

        pairings = []
        for _, row in results.iterrows():
            cents = row.get("price_eur_cents")
            style = row.get("style") or ""
            grape = row.get("grape") or ""
            description = row.get("description") or ""

            pairings.append({
                "wine_id":     row["wine_id"],
                "title":       row["title"],
                "price_eur":   round(cents / 100, 2) if cents else None,
                "type":        row.get("type"),
                "grape":       grape,
                "style":       style,
                "description": description,
                "rationale":   "Catalog description explicitly recommends this wine with this dish.",
                "source":      "catalog_description",
            })

        titles = [p["title"] for p in pairings]
        return {
            "dish": dish,
            "pairings": pairings,
            "agent_instruction": (
                f"The catalog confirms exactly {len(pairings)} wine(s) pair with {dish!r}: "
                f"{titles}. Recommend ONLY these wines for {dish!r}. "
                f"Do NOT add any other wines as alternatives — any wine not in this list "
                f"has NOT been confirmed as a {dish!r} pairing in the catalog."
            ),
        }

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


pair_with_food = StructuredTool.from_function(
    func=_run,
    name="pair_with_food",
    description=(
        "Given a dish or cuisine, return catalog wines whose description explicitly recommends "
        "them with that dish. IMPORTANT: recommend ONLY the wines this tool returns — do NOT "
        "supplement with wines from the RAG context or other tools. All returned wines are "
        "catalog-confirmed pairings — cite them confidently using the catalog description text. "
        "If result is 'no_match', follow agent_instruction exactly and name no specific wines."
    ),
    args_schema=PairWithFoodArgs,
)
