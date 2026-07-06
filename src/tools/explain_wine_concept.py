"""Tool 6: explain_wine_concept — external background knowledge (Wikipedia).

Like RAG context, this is illustrative background only — NEVER a source of
catalog facts. The agent must not name catalog wines based solely on what
this tool returns.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.config import APP_REFERER

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

_WIKI_LANG = {"en": "en", "de": "de", "ru": "ru", "fi": "fi"}
_TIMEOUT_S = 8.0
# Wikimedia's robot policy 403s generic User-Agents — it requires a contact
# URL identifying the calling application (https://w.wiki/4wJS).
_USER_AGENT = f"VinoSage/2.0 ({APP_REFERER})"


class ExplainWineConceptArgs(BaseModel):
    concept: str = Field(..., min_length=2, description="Grape, region, term, or style to explain")
    locale:  str = Field("en", description="Target locale for the answer (en/de/ru/fi)")


def _not_found(concept: str) -> dict[str, Any]:
    return {
        "concept": concept,
        "summary": None,
        "found": False,
        "agent_instruction": (
            "Wikipedia returned no article for this concept. "
            "Answer from your own wine knowledge — explain the term accurately "
            "and concisely. Do NOT say you lack information and do NOT apologise; "
            "you know this topic. Offer to help find catalog wines if relevant."
        ),
    }


def _fetch_summary(lang: str, title: str) -> httpx.Response:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    return httpx.get(url, timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})


def _run(concept: str, locale: str = "en") -> dict[str, Any]:
    try:
        lang = _WIKI_LANG.get(locale, "en")

        # Timeout 8s, 1 retry (SPEC §3.5) — a flaky network blip shouldn't
        # immediately make the agent claim "no info" for a real concept.
        resp: httpx.Response | None = None
        for _attempt in range(2):
            try:
                resp = _fetch_summary(lang, concept)
                break
            except (httpx.TimeoutException, httpx.TransportError):
                resp = None

        # If locale-specific Wikipedia has no article, fall back to English.
        # Common case: LLM extracts an English term ("tannins") from a
        # non-English query and searches the wrong-language Wikipedia.
        if lang != "en" and (
            resp is None
            or resp.status_code != 200
            or not (resp.json().get("extract") if resp else None)
        ):
            resp = None
            for _attempt in range(2):
                try:
                    resp = _fetch_summary("en", concept)
                    break
                except (httpx.TimeoutException, httpx.TransportError):
                    resp = None

        if resp is None:
            return _not_found(concept)
        if resp.status_code == 404:
            return _not_found(concept)
        if resp.status_code != 200:
            return _not_found(concept)

        data = resp.json()
        extract = data.get("extract")
        if not extract:
            return _not_found(concept)

        page_url = (data.get("content_urls") or {}).get("desktop", {}).get("page", "")

        return {
            "concept": concept,
            "summary": extract,
            "source": "Wikipedia",
            "source_url": page_url,
            "found": True,
        }

    except Exception as exc:
        return _ERR("EXTERNAL_API", str(exc))


explain_wine_concept = StructuredTool.from_function(
    func=_run,
    name="explain_wine_concept",
    description=(
        "Explain a wine concept (grape, region, term, style) using an external "
        "knowledge source (Wikipedia). Background only — never a source of catalog "
        "facts. Use for definitional/educational questions, not recommendations."
    ),
    args_schema=ExplainWineConceptArgs,
)
