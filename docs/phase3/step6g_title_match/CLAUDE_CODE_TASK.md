# TASK: Phase 3, step 6g — typography-safe title matching (the 'White Ash' incident)

> For Claude Code. Root cause of the original "buttons for 2 of 3 wines" bug,
> now reproduced in isolation: recommend_for_me returned ONLY
> "Leonidas Nassiakos 'White Ash' Assyrtiko" (curly quotes in the catalog
> title), the LLM presented it with STRAIGHT apostrophes ('White Ash'), and
> chat_view._title_in_response's raw `clean.lower() in response_text.lower()`
> substring check failed — so the wine was filtered out of the feedback-button
> list as "fetched but not presented". Zero buttons rendered.

## Edit
`src/ui/chat_view.py`: replace `_title_in_response` with the reference
implementation in `title_match_reference.py` (adds `_TYPOGRAPHY` map +
`_normalize_for_match`, applied to BOTH sides of the check). The
region/vintage stripping and the empty-title-permissive behavior are
byte-identical to the current code — only the final comparison gains
normalization (curly→straight quotes, long dashes→hyphen, nbsp→space,
whitespace collapse, casefold). Deterministic; no fuzzy matching.

`_recommended_wines_for_feedback` and everything else: untouched.

## Tests
Copy `tests/test_title_matching.py` as-is (7 tests, incl. the exact incident
both directions, dash/nbsp cases, and regressions pinning that plain titles,
absent-wine rejection, vintage/region stripping and empty-title behavior are
unchanged). Adjust the import to the repo path
(`from src.ui.chat_view import _title_in_response`) and drop the sys.path
shim lines at the top.

## Verification
1. `pytest` — full suite green (+7).
2. `git diff --stat` — only chat_view.py + the new test file.
3. One handoff line: 6g — title matching typography-normalized; the only
   catalog wine with typographic quotes ('White Ash') was silently losing
   its feedback buttons.
4. STOP for review.

## Human smoke test (after fix — resumes the interrupted step-5 scenario)
The chat state is already perfect for it: the last turn presented White Ash
with no buttons. After the fix, st.rerun / next interaction re-renders
history — buttons should now appear under White Ash on that same turn.
Then continue: 👎 White Ash → sidebar: Ripe & Rounded in Disliked styles,
Disliked grapes still empty (6f) → re-ask → all_downrated (no wine names,
one question) → toggle one 👎 off → re-ask → that wine returns.
