# TASK: Phase 3, step 6d — rotate the audio_input widget key (stale-recording error)

> For Claude Code. UX fix from the human's voice smoke test. Functional
> behavior is already correct (digest dedup prevents reprocessing); this
> removes a Streamlit widget-level error that forces an extra click between
> voice turns.

## Symptom
After every consumed voice recording, `st.audio_input` displays
"An error has occurred, please try again" (with the previous recording's
duration) on subsequent reruns; the user must click the widget's retry icon
before recording again.

## Cause
`st.audio_input` is built on the file-uploader infrastructure: the widget
keeps referencing the previously uploaded recording across reruns, but after
our flow consumes it and the app reruns (answer rendering, etc.), the
backing upload is stale — the widget renders its error state instead of an
empty recorder.

## Fix — key rotation (same family as the `_pending_profile_update` pattern)
A consumed recording rotates the widget key, so the next run mounts a fresh,
empty recorder — the stale reference is never re-rendered.

In `app.py`, modify the voice-input block:

```python
# Widget-key rotation: once a recording is CONSUMED (transcribed — whether
# it produced text, silence, or an error), we bump the generation counter so
# the next rerun mounts a fresh empty recorder. Without this, st.audio_input
# keeps referencing the consumed upload and renders "An error has occurred"
# until manually reset. NOT rotated on the rate-limit branch — there the
# recording was NOT consumed and the user may retry it after the window.
_voice_gen = st.session_state.setdefault("_voice_widget_gen", 0)
with st.popover(f"🎤 {t('voice_input_label', locale)}"):
    _audio = st.audio_input(
        t("voice_record_label", locale),
        key=f"voice_recorder_{_voice_gen}",
    )
```

and inside the existing `if _audio is not None:` / new-digest branch, add the
rotation line immediately after `st.session_state["_last_voice_digest"] =
_digest` (i.e. on every consumed path — success, empty transcript, and
transcription error alike):

```python
            st.session_state["_last_voice_digest"] = _digest
            st.session_state["_voice_widget_gen"] = _voice_gen + 1
```

No other logic changes: the digest dedup stays (defense-in-depth — rotation
prevents the UI error, the digest prevents reprocessing even if a stale
value ever survives), the rate-limit pre-check branch stays un-rotated, and
`voice_prompt` handling is untouched.

## Verification
1. `pytest` — full suite green, no count change expected (this is
   widget-lifecycle code, exercised by the human smoke test below; do not
   attempt to unit-test Streamlit widget mounting).
2. `git diff --stat` — only `app.py`.
3. One line in `docs/PHASE3_HANDOFF.md` step-4/6 notes: audio_input key
   rotation added (6d) to clear the consumed recording.
4. STOP for review.

## Human smoke test (after this fix)
1. Voice question → answer → WITHOUT clicking anything on the widget, open
   the popover again: recorder is empty and ready (no error banner).
2. Record a second question immediately → processed normally.
3. Rate-limit path unchanged: if you somehow hit the limit, the same
   recording stays in the widget for a retry.
