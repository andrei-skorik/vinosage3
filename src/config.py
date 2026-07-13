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
# Trimmed to reasoning-capable models (SPEC §5.6) — nano/lite/mini variants are
# dropped from chat selection. google/gemini-2.5-flash stays even though it's
# not user-selected directly: it's FALLBACK_MODEL, and the registry is also
# how AgentResult.model_used gets priced for cost accounting.
CHAT_MODELS: Final[dict[str, dict[str, float]]] = {
    "anthropic/claude-haiku-4.5":   {"in": 1.00,  "out": 5.00},
    "openai/gpt-5.4":               {"in": 5.00,  "out": 15.00},
    "openai/gpt-5.2":               {"in": 3.00,  "out": 12.00},
    "google/gemini-2.5-flash":      {"in": 0.30,  "out": 2.50},
    "minimax/minimax-m2":           {"in": 0.30,  "out": 1.20},
}

# Cheap model for query translation + filter extraction — NOT in CHAT_MODELS,
# never user-selectable (get_llm() special-cases it independently of the
# allow-list check).
UTILITY_MODEL: Final  = "openai/gpt-4o-mini"
DEFAULT_MODEL: Final  = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
FALLBACK_MODEL: Final = "google/gemini-2.5-flash"

# ── User-facing Quick/In-depth mapping (SPEC §5.6) ────────────────────────────
# The sidebar exposes only these two labels — real model names/temperature
# stay confined to the admin dev panel.
QUICK_MODEL: Final    = "anthropic/claude-haiku-4.5"
INDEPTH_MODEL: Final  = "openai/gpt-5.2"

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

# ── LangSmith observability (NEW, optional — SPEC §3.5) ───────────────────────
# Read via os.getenv, never config._require(): tracing must degrade
# gracefully (app runs identically) when these are absent. LangChain/LangSmith
# read these same env-var names directly from the process environment at call
# time via their own internal callback wiring — nothing here is passed
# manually into LLM calls or the graph; this module just centralises the read
# for consistency with the rest of config.py and for the admin-panel status
# indicator. LANGSMITH_ENDPOINT is mandatory for EU-region accounts.
LANGSMITH_TRACING: Final  = os.getenv("LANGSMITH_TRACING", "")
LANGSMITH_API_KEY: Final  = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT: Final  = os.getenv("LANGSMITH_PROJECT", "")
LANGSMITH_ENDPOINT: Final = os.getenv("LANGSMITH_ENDPOINT", "")
LANGSMITH_ENABLED: Final  = bool(LANGSMITH_API_KEY) and LANGSMITH_TRACING.strip().lower() == "true"

# ── Voice input (Phase 3, step 4) ─────────────────────────────────────────────
# Speech-to-text via OpenRouter's /audio/transcriptions endpoint — same base
# URL and API key as chat/embeddings, no new secret. Whisper Large V3 Turbo:
# cheapest adequate option, covers all four locales (en/de/ru/fi).
TRANSCRIBE_MODEL: Final = os.getenv("TRANSCRIBE_MODEL", "whisper-large-v3-turbo")
