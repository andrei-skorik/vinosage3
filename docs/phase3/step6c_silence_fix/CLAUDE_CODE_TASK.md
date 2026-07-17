# TASK: Phase 3, step 6c — normalize Whisper silence hallucinations

> For Claude Code. Micro-fix from the human's voice smoke test: on silent
> audio Whisper returned "." (not an empty string), which passed the
> `if not res["text"]` check and burned a full LLM turn + rate-limit slot +
> retrieval on a punctuation mark. Known Whisper behavior (the human's very
> first curl test produced " Thank you." on 1 s of silence).

## Edits

### 1. `src/transcribe.py`
Add `import re` (top). After the line
`text = (payload.get("text") or "").strip()`, insert:

```python
            # Whisper hallucinates filler on silent/near-silent audio
            # ("." / "…" / "Thank you."). A transcript with no letters or
            # digits carries no query content — normalize it to empty so the
            # UI shows the "couldn't hear anything" toast instead of burning
            # an LLM turn on punctuation. (Plausible-word hallucinations like
            # "Thank you." are indistinguishable from real speech and are
            # accepted as-is — known limitation.)
            if not re.search(r"\w", text):
                text = ""
```

### 2. `tests/test_transcribe.py` — add two tests
```python
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
            lambda *a, **k, _t=text: _Resp({"text": _t}),
        )
        assert tr.transcribe_audio(b"x")["text"] == text
```

### 3. `docs/PHASE3_HANDOFF.md`
One line in the step-4 known-gaps area: punctuation-only silence
hallucinations are normalized to empty (6c); plausible-word hallucinations
("Thank you.") remain accepted — indistinguishable from real speech.

## Verification
1. `pytest` — full suite green (217 + 2 = 219 expected).
2. No other files changed (`git diff --stat`).
3. STOP for review; amend into the staged hardening work or commit separately
   at the human's preference.
