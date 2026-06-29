"""Embedding helpers: embed_text(), reconcile_embeddings().

Only writer of the embedding column. Idempotent — safe to re-run.
Rows with needs_embedding=false and embedding IS NOT NULL are skipped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI
from supabase import create_client

from src.config import (
    DEFAULT_EMBEDDING,
    EMBEDDING_DIM,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    APP_TITLE,
    APP_REFERER,
)

log = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 50   # rows per embedding API call
DB_BATCH_SIZE    = 50   # rows per Supabase update call

_openai_client: OpenAI | None = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": APP_REFERER,
                "X-Title": APP_TITLE,
            },
        )
    return _openai_client


def build_embedded_text(wine: dict[str, Any]) -> str:
    """Exact embedded-text formula from SPEC 2.1 (≤8 000 chars)."""
    parts: list[str] = []

    title = wine.get("title") or ""
    if title:
        parts.append(title)

    if wine.get("type"):
        parts.append(f"Type: {wine['type']}")
    if wine.get("grape"):
        parts.append(f"Grape: {wine['grape']}")

    region  = wine.get("region") or ""
    country = wine.get("country") or ""
    loc = ", ".join(filter(None, [region, country]))
    if loc:
        parts.append(f"Region: {loc}")

    if wine.get("style"):
        parts.append(f"Style: {wine['style']}")
    if wine.get("characteristics"):
        parts.append(f"Notes: {wine['characteristics']}")
    if wine.get("description"):
        parts.append(wine["description"])

    text = ". ".join(parts)
    return text[:8000]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Call the embedding model; returns list of vectors."""
    client = _get_openai()

    kwargs: dict[str, Any] = {"model": DEFAULT_EMBEDDING, "input": texts}
    # text-embedding-3-large supports explicit dimension reduction
    if DEFAULT_EMBEDDING == "openai/text-embedding-3-large":
        kwargs["dimensions"] = EMBEDDING_DIM

    response = client.embeddings.create(**kwargs)
    vectors = [item.embedding for item in response.data]

    # Guard: reject wrong-dimension vectors
    for i, v in enumerate(vectors):
        if len(v) != EMBEDDING_DIM:
            raise ValueError(
                f"Expected {EMBEDDING_DIM}-dim vector, got {len(v)} for text index {i}"
            )
    return vectors


def embed_text(text: str) -> list[float]:
    """Convenience wrapper for a single text."""
    return embed_texts([text])[0]


def reconcile_embeddings(*, batch_size: int = EMBED_BATCH_SIZE) -> dict[str, int]:
    """Embed all wines where needs_embedding=true.

    Returns {"processed": N, "failed": N, "skipped": N}.
    Partial failure leaves failed rows flagged for the next run.
    """
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Fetch all pending rows — paginate to bypass the default 1000-row limit
    pending: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            db.table("wines")
            .select(
                # source_key + title included: required for upsert NOT NULL constraint
                "wine_id,source_key,title,type,grape,region,country,"
                "style,characteristics,description"
            )
            .eq("needs_embedding", True)
            .eq("is_active", True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = resp.data
        pending.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    log.info("reconcile: %d rows pending embedding", len(pending))

    if not pending:
        return {"processed": 0, "failed": 0, "skipped": 0}

    processed = failed = 0

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        texts = [build_embedded_text(w) for w in batch]

        try:
            vectors = embed_texts(texts)
        except Exception as exc:
            log.error("embedding batch %d-%d failed: %s", i, i + len(batch), exc)
            failed += len(batch)
            continue

        # PostgREST requires vector as string "[x,y,...]", not a JSON array.
        # Use bulk_update_embeddings RPC to avoid 1-request-per-row overhead.
        def _vec_str(v: list[float]) -> str:
            return "[" + ",".join(f"{x:.8g}" for x in v) + "]"

        rpc_payload = [
            {"wine_id": w["wine_id"], "embedding": _vec_str(v)}
            for w, v in zip(batch, vectors)
        ]
        db.rpc("bulk_update_embeddings", {"updates": rpc_payload}).execute()

        processed += len(batch)
        log.info(
            "reconcile: embedded %d/%d (failed so far: %d)",
            processed,
            len(pending),
            failed,
        )

    return {"processed": processed, "failed": failed, "skipped": 0}
