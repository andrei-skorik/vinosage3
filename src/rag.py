"""Advanced RAG: multi-query translation + self-query filter + RRF fusion.

retrieve() is the single entry point. Translation always happens in English
(catalog text is English) regardless of the user's locale.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.catalog import get_anon_db
from src.config import DEFAULT_LOCALE
from src.embeddings import embed_text

log = logging.getLogger(__name__)

K_PER_VARIANT = 8   # candidates per query variant
K_FINAL       = 8   # returned after fusion
RRF_K         = 60  # constant in the RRF formula


class RetrievedWine(BaseModel):
    wine_id:    str
    title:      str
    similarity: float
    payload:    dict[str, Any]


class RetrieveResult(BaseModel):
    """retrieve() return value: ranked wines + the self-query filter that was
    extracted from the user's query (exposed so the UI can show the user what
    was understood, e.g. "Searching for: Red · Italy · ≤ €20.00")."""
    wines:       list[RetrievedWine]
    filter_used: dict[str, Any] = Field(default_factory=dict)


# ── Query translation (multi-query) ──────────────────────────────────────────

_TRANSLATE_PROMPT = """\
Rewrite the wine-search query below into {n} diverse English paraphrases.
Focus on wine attributes: type, grape variety, region, flavour profile, food pairing, price.
Return a JSON array of {n} strings and nothing else.

Query: {query}"""


def _translate_query(query: str, n: int = 3) -> list[str]:
    """Return n English paraphrases via UTILITY_MODEL (temp=0)."""
    from src.llm import get_utility_llm

    llm = get_utility_llm()
    prompt = _TRANSLATE_PROMPT.format(n=n, query=query)
    try:
        resp = llm.invoke([{"role": "user", "content": prompt}])
        raw = resp.content.strip()
        # strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        variants = json.loads(raw)
        if isinstance(variants, list) and len(variants) == n:
            return [str(v) for v in variants]
    except Exception as exc:
        log.warning("query translation failed: %s", exc)
    return [query] * n  # fallback: use original query


# ── Self-query filter extraction ──────────────────────────────────────────────

_FILTER_PROMPT = """\
Extract wine metadata filters from the query. Return a JSON object with ONLY the
keys that apply: type, country, grape, style, max_price_eur.
Valid type values: Red, White, Rosé, Tawny, Orange, Brown, Mixed.
max_price_eur must be a number (euros).
Return an empty object {{}} if no clear filter is present.
Return JSON only, no explanation.

Query: {query}"""


def _extract_filter(query: str) -> dict[str, Any]:
    from src.llm import get_utility_llm

    llm = get_utility_llm()
    prompt = _FILTER_PROMPT.format(query=query)
    try:
        resp = llm.invoke([{"role": "user", "content": prompt}])
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as exc:
        log.warning("filter extraction failed: %s", exc)
    return {}


# ── Supabase match_wines RPC ──────────────────────────────────────────────────

def _match_wines(
    query_embedding: list[float],
    filter_dict: dict[str, Any],
    k: int = K_PER_VARIANT,
) -> list[dict[str, Any]]:
    db = get_anon_db()
    vec_str = "[" + ",".join(f"{x:.8g}" for x in query_embedding) + "]"
    try:
        resp = db.rpc(
            "match_wines",
            {
                "query_embedding": vec_str,
                "match_count": k,
                "filter": filter_dict,
            },
        ).execute()
        return resp.data or []
    except Exception as exc:
        log.error("match_wines RPC failed: %s", exc)
        return []


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def _rrf_fuse(result_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for results in result_lists:
        for rank, item in enumerate(results, 1):
            wid = item["wine_id"]
            scores[wid] = scores.get(wid, 0.0) + 1.0 / (k + rank)
            payloads[wid] = item

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**payloads[wid], "rrf_score": score}
        for wid, score in merged
    ]


# ── Public entry point ────────────────────────────────────────────────────────

def retrieve(
    query: str,
    locale: str = DEFAULT_LOCALE,
    k: int = K_FINAL,
    metadata_filter: dict[str, Any] | None = None,
) -> RetrieveResult:
    """Multi-query + self-query filter + RRF.

    Translation always happens in English regardless of locale
    (catalog text is stored in English).
    """
    # 1. Multi-query translation
    variants = [query] + _translate_query(query, n=3)   # original + 3 paraphrases

    # 2. Self-query filter (use caller-provided filter if given)
    filter_dict: dict[str, Any] = metadata_filter if metadata_filter is not None else _extract_filter(query)

    # 3. Per-variant similarity search
    result_lists: list[list[dict]] = []
    filter_applied = filter_dict
    for variant in variants:
        try:
            vec = embed_text(variant)
        except Exception as exc:
            log.warning("embed failed for variant %r: %s", variant[:40], exc)
            continue

        hits = _match_wines(vec, filter_dict, k=K_PER_VARIANT)

        # If no hits with filter, retry without it (SPEC 5.2 fallback)
        if not hits and filter_dict:
            log.info("no results under filter %s; retrying without", filter_dict)
            hits = _match_wines(vec, {}, k=K_PER_VARIANT)
            filter_applied = {}  # the filter was dropped — reflect that to the caller

        result_lists.append(hits)

    if not result_lists:
        return RetrieveResult(wines=[], filter_used=filter_applied)

    # 4. RRF fusion + dedup
    fused = _rrf_fuse(result_lists)[:k]

    wines = [
        RetrievedWine(
            wine_id=row["wine_id"],
            title=row["title"],
            similarity=row.get("similarity", row.get("rrf_score", 0.0)),
            payload=row.get("payload", {}),
        )
        for row in fused
    ]
    return RetrieveResult(wines=wines, filter_used=filter_applied)
