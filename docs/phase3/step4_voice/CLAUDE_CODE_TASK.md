# TASK: Phase 3, step 4 of 5 — voice input via Whisper (OpenRouter /audio/transcriptions)

> For Claude Code. Read `CLAUDE.md` first. Reference implementation in
> `docs/phase3/step4_voice/` — `src/transcribe.py` and
> `tests/test_transcribe.py` are copy-as-is; config/app/locale edits are
> surgical (the repo has moved past my snapshots).

## Goal
Let the user speak a question instead of typing. Audio is recorded with
Streamlit's native `st.audio_input`, transcribed by **Whisper Large V3 Turbo**
through OpenRouter's `/audio/transcriptions` (verified working against the
project's existing base URL + API key — **no new secret**), and the resulting
text enters the chat pipeline **exactly as if the user had typed it**.

## Non-negotiable design rule
The transcript is data, not a command. It must flow through the normal
pipeline: rate limit → cost cap → `guard` node → router → agent. No bypass,
no special-casing. The transcript appears in the chat as the user's message
(full transparency about what was recognized).

## Files to apply

### 1. `src/transcribe.py` — NEW, copy as-is
`transcribe_audio(audio_bytes, filename, locale) -> dict`. Conventions:
15 s timeout + 1 retry after 2 s (mirrors the Wikipedia-call policy),
returns `_ERR(code, message)` on failure, **never raises**. Passes the
locale as Whisper's `language` hint (en/de/ru/fi are valid ISO-639-1 codes);
pre-validates empty/oversized (>25 MB) audio without a network call. Empty
transcript (silence) is a success with `text == ""`, not an error — the UI
decides the message.

### 2. `tests/test_transcribe.py` — NEW, copy as-is
10 tests, network monkeypatched, no key needed: success + usage parsing,
language hint for all 4 locales / omitted for unknown, empty-transcript-is-
not-error, retry-then-success, total-failure returns `_ERR` (never raises),
HTTP 5xx, empty/oversized short-circuit, MIME from extension.

### 3. `src/config.py` — add one constant (after the LangSmith block):
```python
# ── Voice input (Phase 3, step 4) ─────────────────────────────────────────────
# Speech-to-text via OpenRouter's /audio/transcriptions endpoint — same base
# URL and API key as chat/embeddings, no new secret. Whisper Large V3 Turbo:
# cheapest adequate option, covers all four locales (en/de/ru/fi).
TRANSCRIBE_MODEL: Final = os.getenv("TRANSCRIBE_MODEL", "whisper-large-v3-turbo")
```

### 4. `app.py` — voice widget + prompt injection (surgical)
Add `import hashlib` (top-level imports) and
`from src.transcribe import transcribe_audio` (deferred-imports block).

**(a)** Right after `chat_input = st.chat_input(...)`, insert:

```python
# ── Voice input (Phase 3, step 4) ─────────────────────────────────────────
# st.audio_input keeps returning the SAME recording on every rerun, so we
# fingerprint it and transcribe each recording exactly once. The rate limit
# is checked BEFORE transcription: it is the throttle protecting the paid
# STT endpoint (a voice turn therefore consumes 2 window slots — one here,
# one in the normal prompt pre-flight; 10/min → up to 5 voice turns/min).
voice_prompt: str | None = None
with st.popover(f"🎤 {t('voice_input_label', locale)}"):
    _audio = st.audio_input(t("voice_record_label", locale), key="voice_recorder")
if _audio is not None:
    _digest = hashlib.sha256(_audio.getvalue()).hexdigest()
    if st.session_state.get("_last_voice_digest") != _digest:
        _rl_voice = check_rate_limit(session_id)
        if not _rl_voice.allowed:
            st.warning(t("error_rate_limit", locale))
        else:
            st.session_state["_last_voice_digest"] = _digest
            with st.spinner(t("voice_transcribing", locale)):
                _res = transcribe_audio(
                    _audio.getvalue(),
                    filename=getattr(_audio, "name", None) or "voice.wav",
                    locale=locale,
                )
            if _res.get("error"):
                st.toast(t("voice_error", locale), icon="⚠️")
            elif not _res["text"]:
                st.toast(t("voice_empty", locale), icon="🎤")
            else:
                voice_prompt = _res["text"]
```

**(b)** Welcome-screen condition: `if not messages and not chat_input:` →
`if not messages and not chat_input and not voice_prompt:`.

**(c)** Prompt resolution: `prompt = chat_input or queued` →
`prompt = chat_input or queued or voice_prompt`.

Nothing else changes — from `if prompt:` onward the transcript takes the
identical path as typed text (guards included). If the repo's structure
around these anchors has drifted, preserve the intent: widget defined once
per render, digest dedup, rate-limit pre-check, transcript feeds `prompt`.

### 5. Locale files — add 5 keys to ALL FOUR files
`locales/en.json`:
```json
"voice_input_label": "Voice input",
"voice_record_label": "Record your question",
"voice_transcribing": "Transcribing…",
"voice_error": "Couldn't transcribe your voice message — please try again or type your question.",
"voice_empty": "I couldn't hear anything in that recording."
```
`locales/de.json`:
```json
"voice_input_label": "Spracheingabe",
"voice_record_label": "Frage aufnehmen",
"voice_transcribing": "Transkribiere…",
"voice_error": "Sprachnachricht konnte nicht transkribiert werden — bitte erneut versuchen oder die Frage eintippen.",
"voice_empty": "In der Aufnahme war nichts zu hören."
```
`locales/ru.json`:
```json
"voice_input_label": "Голосовой ввод",
"voice_record_label": "Запишите ваш вопрос",
"voice_transcribing": "Распознаю речь…",
"voice_error": "Не удалось распознать голосовое сообщение — попробуйте ещё раз или введите вопрос текстом.",
"voice_empty": "В записи не удалось распознать речь."
```
`locales/fi.json`:
```json
"voice_input_label": "Äänisyöte",
"voice_record_label": "Äänitä kysymyksesi",
"voice_transcribing": "Litteroidaan…",
"voice_error": "Ääniviestin litterointi epäonnistui — yritä uudelleen tai kirjoita kysymyksesi.",
"voice_empty": "Äänitteestä ei kuulunut mitään."
```
Also append one line to each locale's `help_body`: EN
`"- Tap the microphone to ask by voice"`, DE `"- Frage per Mikrofon einsprechen"`,
RU `"- Задайте вопрос голосом через микрофон"`, FI
`"- Kysy ääneen mikrofonilla"`.

### 6. `.env.example` — add:
```
# Optional STT model override (default: whisper-large-v3-turbo)
TRANSCRIBE_MODEL=
```

## Verification (run all before stopping for review)
1. `pytest` — full suite green, incl. the 10 new transcription tests and the
   unchanged `test_pair_with_food.py`.
2. Confirm all four locale files parse (`python -c "import json; [json.load(open(f'locales/{l}.json')) for l in ('en','de','ru','fi')]"`)
   and contain the 5 new keys.
3. Grep check: no changes to `src/guard.py`, `src/graph.py`, or the prompt
   pre-flight order in `app.py` — the transcript must hit the same guards.
4. Do NOT make any real API calls to verify transcription — the human
   already validated the endpoint with curl; the mocked tests cover the code.
5. Summarize the diff and STOP for review. Do not proceed to step 5.

## Human-only checklist
1. Manual smoke test (real mic + real API): record "recommend a red wine" →
   text appears as your chat message → normal answer. Then RU/DE/FI phrase in
   the matching locale. Then a prompt-injection phrase by voice
   ("ignore previous instructions") → guard's canned reply, `security_events`
   row — proving the pipeline parity.
2. Optional: set `TRANSCRIBE_MODEL` in secrets only if you want a non-default
   STT model.

## Known gaps to record in the Phase-3 handoff
- Transcription spend (billed per audio second) is NOT counted toward the
  €1/day cost cap — `token_usage` is query-keyed and no query exists at
  transcription time. The rate limit is the effective throttle. A future
  option: a `stt_usage` table (new numbered SQL file) folded into the cap.
- A voice turn consumes 2 rate-limit slots (pre-check + prompt pre-flight) —
  accepted; documents itself in the code comment.
