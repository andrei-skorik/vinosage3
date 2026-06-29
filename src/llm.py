"""OpenRouter ChatOpenAI factory + retry → fallback logic."""
from __future__ import annotations

import logging
import time
from typing import Any

from langchain_openai import ChatOpenAI

from src.config import (
    APP_REFERER,
    APP_TITLE,
    CHAT_MODELS,
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    UTILITY_MODEL,
)

log = logging.getLogger(__name__)

_llm_cache: dict[str, ChatOpenAI] = {}


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0.2) -> ChatOpenAI:
    """Return a cached ChatOpenAI instance for the given model."""
    if model not in CHAT_MODELS and model != UTILITY_MODEL:
        log.warning("Model %r not in allow-list; falling back to %s", model, DEFAULT_MODEL)
        model = DEFAULT_MODEL

    key = f"{model}:{temperature}"
    if key not in _llm_cache:
        _llm_cache[key] = ChatOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
            model=model,
            temperature=temperature,
            timeout=30,
            max_retries=0,
            model_kwargs={
                "extra_headers": {
                    "HTTP-Referer": APP_REFERER,
                    "X-Title": APP_TITLE,
                }
            },
        )
    return _llm_cache[key]


def get_utility_llm() -> ChatOpenAI:
    return get_llm(UTILITY_MODEL, temperature=0.0)


def llm_invoke_with_retry(
    messages: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
) -> Any:
    """Invoke LLM with one retry after 2 s, then fallback to FALLBACK_MODEL.

    Returns the AIMessage response or raises on total failure.
    """
    for attempt, m in enumerate([model, model, FALLBACK_MODEL]):
        try:
            if attempt == 1:
                time.sleep(2)
            llm = get_llm(m)
            return llm.invoke(messages)
        except Exception as exc:
            log.warning("LLM attempt %d with %s failed: %s", attempt + 1, m, exc)
            if attempt == 2:
                raise
    raise RuntimeError("All LLM attempts exhausted")  # unreachable
