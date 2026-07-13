"""Tool 7: recommend_for_me — profile-conditioned, catalog-grounded picks.

Unlike the other tools, this one is built per-request with the resolved
taste profile captured in a closure (SPEC §3.3) so the LLM never passes
identity as an argument. `build_recommend_for_me_tool(profile)` is called by
the graph's `agent` node (wired in Step 3) once per turn with the profile
`load_preferences` resolved for that user/session.

The profile only ever shapes the search filter and ranking — it is never a
source of catalog truth. Every returned wine still comes from the cached
active-wines DataFrame.
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

_PREFERRED_LIST_FIELDS = (
    ("preferred_types", "type"),
    ("preferred_grapes", "grape"),
    ("preferred_countries", "country"),
    ("preferred_styles", "style"),
    ("preferred_regions", "region"),
)
_DISLIKED_LIST_FIELDS = (
    ("disliked_types", "type"),
    ("disliked_grapes", "grape"),
    ("disliked_styles", "style"),
)


class RecommendForMeArgs(BaseModel):
    occasion:      Optional[str]   = Field(None, description="Optional context, e.g. 'dinner with friends'")
    max_price_eur: Optional[float] = Field(None, ge=0, description="Optional hard ceiling overriding profile")
    limit:         int             = Field(3, ge=1, le=5)


def _excluded_wine_ids(user_id: str | None) -> set:
    """Wine_ids the user currently has an active 👎 on (Phase 3, step 5 / №1).

    A down-rated wine must never be re-recommended, even when it matches the
    profile on every other dimension — re-showing it reads as ignoring the
    user's explicit signal. Latest-rating-wins semantics live in
    src.preferences.get_downrated_wine_ids. Anonymous users have no feedback
    rows (user_id guard in the UI), so None short-circuits to no exclusion.
    Any failure returns an empty set: exclusion is best-effort and must never
    break recommendations (project convention).
    """
    if not user_id:
        return set()
    try:
        from src.preferences import get_downrated_wine_ids
        return set(get_downrated_wine_ids(user_id) or ())
    except Exception:
        return set()


def _profile_is_empty(profile: dict[str, Any]) -> bool:
    for key, _ in _PREFERRED_LIST_FIELDS:
        if profile.get(key):
            return False
    if profile.get("preferred_characteristics"):
        return False
    if profile.get("min_price_eur_cents") is not None or profile.get("max_price_eur_cents") is not None:
        return False
    return True


def _unstocked_dimension(profile: dict[str, Any], df) -> str | None:
    """Best-effort: name the first preferred value that doesn't exist in the
    catalog at all, for an honest 'we don't stock that' message."""
    for key, col in _PREFERRED_LIST_FIELDS:
        values = profile.get(key) or []
        if not values:
            continue
        known = set(df[col].dropna().unique().tolist())
        for v in values:
            if v not in known:
                return v
    return None


def _overlap_score(row, profile: dict[str, Any]) -> int:
    score = 0
    for key, col in _PREFERRED_LIST_FIELDS:
        values = profile.get(key) or []
        if values and row.get(col) in values:
            score += 1
    chars = (row.get("characteristics") or "")
    if isinstance(chars, str):
        for c in profile.get("preferred_characteristics") or []:
            if c.lower() in chars.lower():
                score += 1
    return score


def _diverse_picks(df, occasion: str | None, max_price_eur: float | None, limit: int,
                   excluded: set | None = None) -> list[dict[str, Any]]:
    """Return a varied selection when no profile filters exist: one wine per
    distinct type (Red/White/Rosé/Sparkling/…) sorted by price, capped at limit.
    Down-rated wines (excluded) are dropped here too — a user with feedback
    but a cleared profile must not see a wine they explicitly rejected.
    """
    mask = df["is_active"].notna()
    if excluded:
        mask = mask & ~df["wine_id"].isin(excluded)
    if max_price_eur is not None:
        max_cents = int(max_price_eur * 100)
        mask = mask & (df["price_eur_cents"].notna() & (df["price_eur_cents"] <= max_cents))
    pool = df[mask].copy()
    if pool.empty:
        fallback_mask = df["is_active"].notna()
        if excluded:
            fallback_mask = fallback_mask & ~df["wine_id"].isin(excluded)
        pool = df[fallback_mask].copy()
    pool = pool.sort_values("price_eur_cents", na_position="last")
    picks: list[dict] = []
    seen_types: set[str] = set()
    for row in pool.to_dict("records"):
        wtype = row.get("type") or ""
        if wtype not in seen_types:
            seen_types.add(wtype)
            picks.append(row)
            if len(picks) >= limit:
                break
    if len(picks) < limit:
        for row in pool.to_dict("records"):
            if row not in picks:
                picks.append(row)
                if len(picks) >= limit:
                    break
    return picks[:limit]


def _preferred_subset(df, base_mask, profile: dict[str, Any]):
    """Apply preferred-dimension filters with style relaxation only.

    Tries the full AND intersection first. If no match, relaxes the style
    constraint — so a user who prefers Malbec AND "Bold & Spicy" still gets
    Malbec wines when no Malbec carries that exact style label.

    Grape/type/country/region constraints are never relaxed: if the user's
    preferred grape isn't stocked (or is excluded by dislike filters), the
    caller surfaces a no_catalog_match instead of showing unrelated wines
    (SPEC §5.3).
    """
    active = [(key, col) for key, col in _PREFERRED_LIST_FIELDS if profile.get(key)]
    if not active:
        return df[base_mask]

    def _apply(skip_keys):
        m = base_mask.copy()
        for key, col in active:
            if key not in skip_keys:
                m = m & df[col].isin(profile.get(key))
        return df[m]

    # 1. Full match: all preferred dimensions
    subset = _apply(skip_keys=set())
    if not subset.empty:
        return subset

    # 2. Relax style — only when there are other identity constraints
    #    (grape/type/country/region) that can actually be satisfied.
    non_style_active = [(k, c) for k, c in active if k != "preferred_styles"]
    if non_style_active:
        identity_subset = _apply(skip_keys={"preferred_styles"})
        if not identity_subset.empty:
            return identity_subset

    # Identity constraints can't be met even without style — return empty
    # so the caller reports no_catalog_match (SPEC §5.3).
    return df.iloc[0:0]


def _build(profile: dict[str, Any], occasion: str | None, max_price_eur: float | None, limit: int,
           user_id: str | None = None) -> dict[str, Any]:
    try:
        profile = profile or {}

        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        excluded = _excluded_wine_ids(user_id)

        if _profile_is_empty(profile):
            rows = _diverse_picks(df, occasion, max_price_eur, limit, excluded=excluded)
            recommendations = []
            for row in rows:
                cents = row.get("price_eur_cents")
                recommendations.append({
                    "wine_id":   row["wine_id"],
                    "title":     row["title"],
                    "price_eur": round(cents / 100, 2) if cents else None,
                    "type":      row.get("type"),
                    "grape":     row.get("grape"),
                    "style":     row.get("style"),
                    "rationale": "General pick from our catalog.",
                })
            return {
                "recommendations": recommendations,
                "count": len(recommendations),
                "result": "no_profile_general",
                "agent_instruction": (
                    "The user has no saved taste profile. Present these as varied general picks "
                    "from our catalog. After your answer add ONE short sentence inviting them "
                    "to save preferences in the sidebar for personalised future picks."
                ),
            }

        # Hard constraints: disliked dimensions and price range always excluded.
        # Kept SEPARATE from the feedback exclusion so that, when the result
        # is empty, we can tell an honest "everything matching was one you
        # rated 👎" apart from a genuine "nothing in stock matches".
        base_hard = df["is_active"].notna()

        for key, col in _DISLIKED_LIST_FIELDS:
            values = profile.get(key) or []
            if values:
                base_hard = base_hard & ~df[col].isin(values)

        min_cents = profile.get("min_price_eur_cents")
        if min_cents is not None:
            base_hard = base_hard & (df["price_eur_cents"].notna() & (df["price_eur_cents"] >= min_cents))

        effective_max_cents = (
            int(max_price_eur * 100) if max_price_eur is not None else profile.get("max_price_eur_cents")
        )
        if effective_max_cents is not None:
            base_hard = base_hard & (df["price_eur_cents"].notna() & (df["price_eur_cents"] <= effective_max_cents))

        hard_mask = base_hard
        if excluded:
            hard_mask = hard_mask & ~df["wine_id"].isin(excluded)

        subset = _preferred_subset(df, hard_mask, profile)

        if subset.empty:
            # Honesty branch (№1): if lifting ONLY the feedback exclusion
            # yields matches, the profile itself is satisfiable — every
            # matching wine is one the user explicitly rejected. Say that,
            # rather than the misleading "nothing matches your taste".
            if excluded and not _preferred_subset(df, base_hard, profile).empty:
                return {
                    "recommendations": [],
                    "result": "all_downrated",
                    "agent_instruction": (
                        "Every catalog wine matching the user's taste profile is one they "
                        "previously rated with a thumbs-down, so nothing new can be "
                        "recommended. Say so plainly (no apology, no invention) and name "
                        "no wines. Ask ONE short question: broaden the preferences, or "
                        "revisit one of the previously rejected wines?"
                    ),
                }
            unstocked = _unstocked_dimension(profile, df)
            if unstocked:
                instruction = (
                    f"The user's preferred '{unstocked}' is not stocked. Say so plainly "
                    "(no apology, no invention) and offer the closest in-stock style; "
                    "you MAY call filter_wines to find it."
                )
            else:
                instruction = (
                    "No in-stock wine matches this combination of taste preferences. "
                    "Say so plainly (no apology, no invention) and offer the closest "
                    "in-stock alternative; you MAY call filter_wines to find it."
                )
            return {"recommendations": [], "result": "no_catalog_match", "agent_instruction": instruction}

        rows = subset.to_dict("records")
        rows.sort(key=lambda r: (-_overlap_score(r, profile), r.get("price_eur_cents") or 0))
        rows = rows[:limit]

        recommendations = []
        for row in rows:
            cents = row.get("price_eur_cents")
            matched_dims = [
                col for key, col in _PREFERRED_LIST_FIELDS
                if (profile.get(key) or []) and row.get(col) in (profile.get(key) or [])
            ]
            reason_bits = " and ".join(f"{row.get(d)}" for d in matched_dims) if matched_dims else None
            rationale = (
                f"Matches your taste for {reason_bits}." if reason_bits
                else "Closest available match from our catalog."
            )
            recommendations.append({
                "wine_id":   row["wine_id"],
                "title":     row["title"],
                "price_eur": round(cents / 100, 2) if cents else None,
                "type":      row.get("type"),
                "grape":     row.get("grape"),
                "style":     row.get("style"),
                "rationale": rationale,
            })

        profile_used: dict[str, Any] = {}
        for key, _ in _PREFERRED_LIST_FIELDS:
            if profile.get(key):
                profile_used[key] = profile[key]
        for key, _ in _DISLIKED_LIST_FIELDS:
            if profile.get(key):
                profile_used[key] = profile[key]
        if effective_max_cents is not None:
            profile_used["max_price_eur"] = round(effective_max_cents / 100, 2)
        if occasion:
            profile_used["occasion"] = occasion

        return {
            "profile_used": profile_used,
            "recommendations": recommendations,
            "count": len(recommendations),
        }

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


def build_recommend_for_me_tool(profile: dict[str, Any], user_id: str | None = None) -> StructuredTool:
    """Build a request-scoped recommend_for_me tool bound to `profile` (and the
    user's feedback exclusion list) via closure — the LLM never passes identity."""

    def _run(
        occasion: str | None = None,
        max_price_eur: float | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        return _build(profile, occasion, max_price_eur, limit, user_id=user_id)

    return StructuredTool.from_function(
        func=_run,
        name="recommend_for_me",
        description=(
            "Recommend catalog wines personalised to the current user's saved taste "
            "profile. ALWAYS call this tool FIRST — before asking any clarifying "
            "questions — whenever the user asks what they should try, drink, or buy. "
            "If the profile is empty the tool will tell you exactly what to ask; "
            "if it has preferences it returns ready-to-present wine picks. "
            "Do NOT use for a specific dish (pair_with_food), named wines "
            "(compare_wines), or explicit filter constraints (filter_wines)."
        ),
        args_schema=RecommendForMeArgs,
    )
