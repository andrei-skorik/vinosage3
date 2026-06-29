"""Central configuration — all secrets via env/st.secrets, never hardcoded."""
from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


# ── Secrets ──────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY: Final = _require("OPENROUTER_API_KEY")
SUPABASE_URL: Final       = _require("SUPABASE_URL")
SUPABASE_ANON_KEY: Final  = _require("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY: Final = _require("SUPABASE_SERVICE_KEY")
ADMIN_PASSWORD: Final     = _require("ADMIN_PASSWORD")
KB_SOURCE_URL: Final      = os.getenv("KB_SOURCE_URL", "")

# ── Model registry (allow-list) ───────────────────────────────────────────────
# Pricing in EUR per million tokens (illustrative; update as provider changes)
CHAT_MODELS: Final[dict[str, dict[str, float]]] = {
    "anthropic/claude-haiku-4.5":   {"in": 1.00,  "out": 5.00},
    "anthropic/claude-3.5-haiku":   {"in": 0.80,  "out": 4.00},
    "openai/gpt-5.4":               {"in": 5.00,  "out": 15.00},
    "openai/gpt-5.4-mini":          {"in": 0.40,  "out": 1.60},
    "openai/gpt-5.2":               {"in": 3.00,  "out": 12.00},
    "openai/gpt-4.1-mini":          {"in": 0.40,  "out": 1.60},
    "openai/gpt-4o-mini":           {"in": 0.15,  "out": 0.60},
    "google/gemini-2.5-flash":      {"in": 0.30,  "out": 2.50},
    "google/gemini-2.5-flash-lite": {"in": 0.10,  "out": 0.40},
    "minimax/minimax-m2":           {"in": 0.30,  "out": 1.20},
}

# Cheap model for query translation + filter extraction (not user-selectable)
UTILITY_MODEL: Final  = "openai/gpt-4o-mini"
DEFAULT_MODEL: Final  = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
FALLBACK_MODEL: Final = "google/gemini-2.5-flash"

EMBEDDING_MODELS: Final[dict[str, int]] = {
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
    "qwen/qwen3-embedding-8b":       4096,
}
DEFAULT_EMBEDDING: Final = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM: Final     = EMBEDDING_MODELS[DEFAULT_EMBEDDING]

# ── Rate limiting & cost guard ────────────────────────────────────────────────
RATE_LIMIT_PER_MIN: Final  = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))
DAILY_COST_CAP_EUR: Final  = float(os.getenv("DAILY_COST_CAP_EUR", "1.00"))
# Stored as integer micro-euros (1 EUR = 1_000_000 micro-euros)
DAILY_COST_CAP_MICROS: Final = int(DAILY_COST_CAP_EUR * 1_000_000)

# ── OpenRouter base URL ───────────────────────────────────────────────────────
OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api/v1"
APP_TITLE: Final           = "VinoSage"
APP_REFERER: Final         = "https://vinosage.streamlit.app"

# ── Supported locales ─────────────────────────────────────────────────────────
SUPPORTED_LOCALES: Final[list[str]] = ["en", "de", "ru", "fi"]
DEFAULT_LOCALE: Final = "en"
