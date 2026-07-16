"""Tests for src/transcribe.py (Phase 3, step 4).

Network is monkeypatched (src.transcribe.httpx.post) — no real API calls,
no API key needed, tests run instantly (the retry sleep is patched out).
"""
from __future__ import annotations

from typing import Any

import pytest

import src.transcribe as tr


class _Resp:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tr.httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(tr.time, "sleep", lambda *_: None)


# ── Success paths ─────────────────────────────────────────────────────────────


def test_success_returns_text_and_usage(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        captured.update(url=url, data=data, files=files, timeout=timeout, headers=headers)
        return _Resp({"text": " Recommend a red wine. ", "usage": {"seconds": 4, "cost": 0.0012}})

    monkeypatch.setattr(tr.httpx, "post", fake_post)
    res = tr.transcribe_audio(b"RIFF....", filename="voice.wav", locale="en")

    assert res == {
        "text": "Recommend a red wine.", "model": tr.TRANSCRIBE_MODEL, "seconds": 4,
        "cost_eur_micros": 1200,
    }
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["data"]["model"] == tr.TRANSCRIBE_MODEL
    assert captured["data"]["language"] == "en"
    assert captured["timeout"] == tr._TIMEOUT_S
    # multipart tuple: (filename, bytes, mime)
    assert captured["files"]["file"][0] == "voice.wav"
    assert captured["files"]["file"][2] == "audio/wav"


def test_all_four_locales_pass_language_hint(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda url, headers=None, data=None, files=None, timeout=None:
            (seen.append(data.get("language")), _Resp({"text": "ok"}))[1],
    )
    for loc in ("en", "de", "ru", "fi"):
        tr.transcribe_audio(b"x", locale=loc)
    assert seen == ["en", "de", "ru", "fi"]


def test_unsupported_locale_omits_language_hint(monkeypatch):
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda url, headers=None, data=None, files=None, timeout=None:
            (seen.update(data), _Resp({"text": "ok"}))[1],
    )
    tr.transcribe_audio(b"x", locale="xx")
    assert "language" not in seen  # Whisper auto-detects


def test_empty_transcript_is_success_not_error(monkeypatch):
    """Silence -> empty text. The caller messages it; it is not an _ERR."""
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda *a, **k: _Resp({"text": "  ", "usage": {"seconds": 1}}),
    )
    res = tr.transcribe_audio(b"x")
    assert "error" not in res
    assert res["text"] == ""
    # Silence still bills seconds; usage.cost absent here -> 0, never crashes.
    assert res["cost_eur_micros"] == 0


def test_punctuation_only_transcript_normalized_to_empty(monkeypatch):
    """The real smoke-test case: Whisper returned '.' on silence."""
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda *a, **k: _Resp({"text": " . ", "usage": {"seconds": 1}}),
    )
    res = tr.transcribe_audio(b"x")
    assert "error" not in res
    assert res["text"] == ""


def test_real_words_are_not_normalized_away(monkeypatch):
    """Guard the guard: single-word and Cyrillic transcripts must survive."""
    for text in ("Merlot?", "да"):
        monkeypatch.setattr(
            tr.httpx, "post",
            lambda *a, _t=text, **k: _Resp({"text": _t}),
        )
        assert tr.transcribe_audio(b"x")["text"] == text


# ── Retry -> failure paths ────────────────────────────────────────────────────


def test_retry_then_success(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise tr.httpx.ConnectTimeout("slow")
        return _Resp({"text": "second try"})

    monkeypatch.setattr(tr.httpx, "post", flaky)
    res = tr.transcribe_audio(b"x")
    assert res["text"] == "second try"
    assert calls["n"] == 2


def test_total_failure_returns_err_never_raises(monkeypatch):
    def always_fail(*a, **k):
        raise tr.httpx.ConnectTimeout("down")

    monkeypatch.setattr(tr.httpx, "post", always_fail)
    res = tr.transcribe_audio(b"x")  # must NOT raise
    assert res["error"]["code"] == "TRANSCRIBE_FAILED"


def test_http_error_status_returns_err(monkeypatch):
    monkeypatch.setattr(tr.httpx, "post", lambda *a, **k: _Resp({}, status=500))
    res = tr.transcribe_audio(b"x")
    assert res["error"]["code"] == "TRANSCRIBE_FAILED"


# ── Input validation (no network round-trips) ─────────────────────────────────


def test_empty_audio_short_circuits(monkeypatch):
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda *a, **k: pytest.fail("network must not be called for empty audio"),
    )
    res = tr.transcribe_audio(b"")
    assert res["error"]["code"] == "EMPTY_AUDIO"


def test_oversized_audio_short_circuits(monkeypatch):
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda *a, **k: pytest.fail("network must not be called for oversized audio"),
    )
    res = tr.transcribe_audio(b"x" * (tr._MAX_AUDIO_BYTES + 1))
    assert res["error"]["code"] == "AUDIO_TOO_LARGE"


def test_mime_derived_from_extension(monkeypatch):
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        tr.httpx, "post",
        lambda url, headers=None, data=None, files=None, timeout=None:
            (seen.update(files), _Resp({"text": "ok"}))[1],
    )
    tr.transcribe_audio(b"x", filename="clip.mp3")
    assert seen["file"][2] == "audio/mpeg"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
