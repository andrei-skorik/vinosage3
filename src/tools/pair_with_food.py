"""Tool 2: pair_with_food — recommend wines for a given dish."""
from __future__ import annotations

import re
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

# Pairing-trigger phrases: catalog descriptions announce food pairings using a
# recognisable set of phrases.  Only text that follows one of these triggers is
# eligible as a food-pairing match.  This eliminates tasting-note false positives
# for ANY food word, including multi-word dishes like "dark chocolate":
#   "dark chocolate and a creamy texture"  → no trigger → TASTING NOTE  (no match)
#   "a perfect pairing for beef short ribs" → trigger → PAIRING  (match beef, not chocolate)
#   "a natural match for dark chocolate's intensity" → trigger → PAIRING  (match chocolate ✓)
_PAIRING_TRIGGER_RE = re.compile(
    r"\b(?:"
    r"try\s+it\s+with|try\s+with|serve\s+with|serve\s+alongside|"
    r"pair(?:s)?\s+(?:perfectly\s+|well\s+)?with|"
    r"drink\s+with|goes?\s+(?:perfectly\s+|well\s+)?with|"
    r"enjoy\s+(?:it\s+)?with|"
    r"partner\s+(?:this\s+|it\s+)?with|partner\s+for|"
    r"perfect\s+(?:with|for|pairing\s+for|match\s+for|accompaniment\s+(?:for|with|to))|"
    r"excellent\s+(?:with|match\s+for)|"
    r"delicious\s+with|fantastic\s+with|great\s+with|wonderful\s+with|lovely\s+with|"
    r"best\s+with|perfectly\s+with|ideal\s+(?:with|for)|"
    r"accompani(?:es|ment)\s+(?:for|to)|a\s+natural\s+match\s+for|"
    r"stand\s+up\s+to|suited\s+to|complemented\s+by|good\s+with"
    r")",
    re.IGNORECASE,
)


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


def _pairing_contexts(desc: str) -> list[str]:
    """Extract the lowercased text after each pairing-trigger phrase.

    Each slice runs to the next sentence terminator or 150 chars, whichever
    comes first.  Returns [] for NaN / non-string descriptions (NaN guard).
    """
    if not isinstance(desc, str):
        return []
    contexts = []
    for m in _PAIRING_TRIGGER_RE.finditer(desc):
        after = desc[m.end():]
        end = re.search(r"[.!?\r\n]", after)
        contexts.append((after[: end.start()] if end else after[:150]).lower())
    return contexts


def _desc_mentions_food(desc, title, keywords: list[str]) -> bool:
    """Return True only if the description contains a pairing trigger phrase
    followed by at least one of the given keywords.

    Anchoring matches to explicit pairing triggers ("try it with", "perfect with",
    "a natural match for", etc.) prevents tasting-note descriptors
    ("dark chocolate and a creamy texture") from being mistaken for pairing
    recommendations.  Handles NaN / non-string descriptions gracefully.
    """
    for ctx in _pairing_contexts(desc):
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", ctx):
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
