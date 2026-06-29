"""Internationalisation helper — load JSON locale files, provide t() lookup."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

_LOCALES_DIR = os.path.join(os.path.dirname(__file__), "..", "locales")


@lru_cache(maxsize=8)
def _load(locale: str) -> dict[str, str]:
    path = os.path.join(_LOCALES_DIR, f"{locale}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tlist(key: str, locale: str = "en") -> list[str]:
    """Return a translated list value for key. Returns [] if missing — no cross-locale fallback.

    No English fallback intentionally: a missing key returns [] so callers can
    detect a stale cache and skip caching rather than storing wrong-locale data.
    """
    try:
        val = _load(locale).get(key)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    return []


def t(key: str, locale: str = "en", **vars: Any) -> str:
    """Return translated string for key in locale, falling back to English."""
    text: str | None = None
    try:
        text = _load(locale).get(key)
    except Exception:
        pass
    if text is None:
        try:
            text = _load("en").get(key, key)
        except Exception:
            text = key
    if vars:
        try:
            text = text.format(**vars)
        except (KeyError, ValueError):
            pass
    return text or key
