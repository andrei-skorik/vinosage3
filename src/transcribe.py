"""Voice input: audio bytes -> text via OpenRouter /audio/transcriptions.

Phase 3, step 4. Model: Whisper Large V3 Turbo (verified working against
OpenRouter's OpenAI-compatible endpoint with the project's existing API key
and base URL — same gateway, same auth, no new secrets).

Project conventions honoured:
- Timeout (15 s) + exactly 1 retry after a 2 s sleep — mirrors the external
  Wikipedia-call policy in explain_wine_concept (SPEC §3.5 pattern).
- Returns ``_ERR(code, message)`` on any failure and NEVER raises past its
  boundary. A transcription failure must never break the chat UI; app.py
  shows a toast and the user can type instead.
- The transcript is DATA, not a command: app.py feeds it into the normal
  prompt pipeline, where the guard node, rate limit, cost cap, and router
  treat it exactly like typed text. This module does no interpretation.

Cost note: OpenRouter bills transcription per audio second (the response's
``usage.cost`` field). This spend is NOT counted toward the €1/day cap
(token_usage is query-keyed; no query exists yet at transcription time) —
recorded as a known gap; the sliding-window rate limit is the effective
throttle (app.py checks it BEFORE transcribing).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from src.config import (
    APP_REFERER,
    APP_TITLE,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    SUPPORTED_LOCALES,
    TRANSCRIBE_MODEL,
)

log = logging.getLogger(__name__)

_ERR = lambda code, msg: {"error": {"code": code, "message": msg}}   # noqa: E731

_TIMEOUT_S = 15.0
_RETRY_SLEEP_S = 2.0
# OpenAI-compatible transcription endpoints cap uploads at 25 MB; reject
# earlier with a clear code instead of burning a network round-trip.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024

_MIME_BY_EXT = {
    "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "ogg": "audio/ogg", "webm": "audio/webm", "flac": "audio/flac",
}


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "voice.wav",
    locale: str = "en",
) -> dict[str, Any]:
    """Transcribe recorded audio to text.

    Success: ``{"text": str, "model": str, "seconds": float | None}``
    (``text`` may be empty for silent recordings — the caller decides how to
    message that; it is NOT an error).
    Failure: ``{"error": {"code": ..., "message": ...}}``.
    """
    if not audio_bytes:
        return _ERR("EMPTY_AUDIO", "No audio data received")
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        return _ERR("AUDIO_TOO_LARGE", f"Audio exceeds {_MAX_AUDIO_BYTES // (1024*1024)} MB limit")

    data: dict[str, str] = {"model": TRANSCRIBE_MODEL}
    # Whisper accepts an ISO-639-1 language hint — improves accuracy and
    # latency. Our locales (en/de/ru/fi) are all valid codes; anything else
    # (defensive) omits the hint and lets Whisper auto-detect.
    if locale in SUPPORTED_LOCALES:
        data["language"] = locale

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    files = {"file": (filename, audio_bytes, _MIME_BY_EXT.get(ext, "audio/wav"))}
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": APP_REFERER,
        "X-Title": APP_TITLE,
    }

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            if attempt == 1:
                time.sleep(_RETRY_SLEEP_S)
            resp = httpx.post(
                f"{OPENROUTER_BASE_URL}/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
            text = (payload.get("text") or "").strip()
            # Whisper hallucinates filler on silent/near-silent audio
            # ("." / "…" / "Thank you."). A transcript with no letters or
            # digits carries no query content — normalize it to empty so the
            # UI shows the "couldn't hear anything" toast instead of burning
            # an LLM turn on punctuation. (Plausible-word hallucinations like
            # "Thank you." are indistinguishable from real speech and are
            # accepted as-is — known limitation.)
            if not re.search(r"\w", text):
                text = ""
            usage = payload.get("usage") or {}
            return {"text": text, "model": TRANSCRIBE_MODEL, "seconds": usage.get("seconds")}
        except Exception as exc:
            log.warning("Transcription attempt %d failed: %s", attempt + 1, exc)
            last_exc = exc

    return _ERR("TRANSCRIBE_FAILED", str(last_exc))
