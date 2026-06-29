"""Tool 3: calculate_budget — fit N bottles into a total budget."""
from __future__ import annotations

import random
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.catalog import get_active_wines_df

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731


class CalculateBudgetArgs(BaseModel):
    total_eur: float = Field(..., gt=0, description="Total budget in euros")
    quantity:  int   = Field(..., ge=1, le=24, description="Number of bottles")
    type:      str   = Field("any", description="Red/White/Rosé/any")
    strategy:  str   = Field(
        "maximize_quality",
        description="maximize_quality | spread | cheapest",
    )


def _run(
    total_eur: float,
    quantity: int,
    type: str = "any",
    strategy: str = "maximize_quality",
) -> dict[str, Any]:
    try:
        df = get_active_wines_df()
        if df.empty:
            return _ERR("INTERNAL", "Catalog not available")

        total_cents = int(total_eur * 100)
        ceiling_cents = total_cents // quantity  # max per bottle

        pool = df[df["price_eur_cents"].notna()].copy()

        if type != "any":
            pool = pool[pool["type"] == type]

        affordable = pool[pool["price_eur_cents"] <= ceiling_cents]

        if affordable.empty:
            cheapest = pool["price_eur_cents"].min() if not pool.empty else None
            msg = (
                f"Cannot fit {quantity} bottles into €{total_eur:.2f}. "
                f"Per-bottle ceiling is €{ceiling_cents/100:.2f}. "
            )
            if cheapest:
                msg += f"Cheapest available bottle is €{cheapest/100:.2f}."
            return _ERR("NO_MATCH", msg)

        # Build basket according to strategy
        if strategy == "cheapest":
            sorted_pool = affordable.sort_values("price_eur_cents", ascending=True)
        elif strategy == "maximize_quality":
            sorted_pool = affordable.sort_values("price_eur_cents", ascending=False)
        else:  # spread — diversify by type/country
            sorted_pool = affordable.sample(frac=1, random_state=42)

        # Pick `quantity` bottles (repeat rows if not enough unique wines)
        basket_rows = []
        candidates = sorted_pool.to_dict("records")
        if len(candidates) >= quantity:
            basket_rows = candidates[:quantity]
        else:
            # repeat best wines to fill quantity
            while len(basket_rows) < quantity:
                basket_rows.extend(candidates)
            basket_rows = basket_rows[:quantity]

        grand_total_cents = sum(r["price_eur_cents"] for r in basket_rows)
        within_budget = grand_total_cents <= total_cents

        basket = []
        for row in basket_rows:
            basket.append({
                "wine_id":   row["wine_id"],
                "title":     row["title"],
                "price_eur": round(row["price_eur_cents"] / 100, 2),
                "type":      row.get("type"),
                "country":   row.get("country"),
            })

        return {
            "per_bottle_ceiling_eur": round(ceiling_cents / 100, 2),
            "basket":         basket,
            "selected_count": len(basket),
            "grand_total_eur": round(grand_total_cents / 100, 2),
            "within_budget":   within_budget,
        }

    except Exception as exc:
        return _ERR("INTERNAL", str(exc))


calculate_budget = StructuredTool.from_function(
    func=_run,
    name="calculate_budget",
    description=(
        "Fit a number of bottles into a total euro budget. "
        "Returns a basket + grand total. Strategy: maximize_quality | spread | cheapest."
    ),
    args_schema=CalculateBudgetArgs,
)
