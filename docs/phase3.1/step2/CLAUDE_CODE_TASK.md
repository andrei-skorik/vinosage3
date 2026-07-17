# TASK: Phase 4, step 2 of 4 — multilingual routing coverage for the 30 food nouns

> For Claude Code. Read `CLAUDE.md` and the step-3 "known gap" in
> `docs/PHASE3_HANDOFF.md` first. Scope guard: this task touches ROUTING
> DETECTION ONLY (`agent._FOOD_QUERY_KWS` DE/FI sections and
> `agent._RU_FOOD_STEMS`). The three evidence sets (`_FOOD_NOUNS`,
> `_FOOD_KWS`, `_HIST_FOOD_KWS`) match against ENGLISH catalog descriptions
> and MUST NOT gain non-English words — the `test_food_kws_sync.py` guard
> will (correctly) fail if you touch them. `pair_with_food.py` stays
> untouched, as always.

## Problem
The 30 nouns added in step 3 (prawn, crab, soup, stew, burger, ...) are
English-only in the routing set. A German user asking "Welcher Wein passt
zu Suppe?" or a Finnish user asking about "keitto" is not classified as a
food query — the mandatory pair_with_food path isn't forced and layers 2/3
never engage for those turns.

## Investigate first (report findings)
Determine how each language is matched before adding words:
- DE/FI: are they plain lowercase word-members of `_FOOD_QUERY_KWS` matched
  by the same `_in_fqkws` word check (with its English `-s` plural stem)?
  If so, German/Finnish plurals need EXPLICIT forms (German plurals are
  rarely `-s`; Finnish inflects heavily).
- RU: confirm `_RU_FOOD_STEMS` is matched by prefix (`startswith`-style).
  If a FI stem mechanism also exists, prefer stems for Finnish too.

## Human-approved vocabulary (curated; quality over coverage)
Adapt forms to the mechanism you found. If a word risks false positives in
your judgment, drop it and say so in the report — a smaller accurate list
beats a bigger noisy one.

**German** (lowercase; singular + common plural where plural isn't -s):
pudding · mousse · fondue · brownie, brownies · tarte, törtchen ·
brot · brioche · fladenbrot · nudel, nudeln · knödel, klöße, teigtaschen ·
garnele, garnelen (verify — handoff says already present) · krabbe,
krabben · tintenfisch, kalmar · oktopus, krake · jakobsmuschel,
jakobsmuscheln · wachtel, wachteln · fasan · burger · suppe, suppen ·
eintopf, gulasch, ragout · chili · tapas

**Finnish** (as stems if a stem mechanism exists, else the listed forms):
vanukas/vanukka- (pudding) · mousse · fondue · brownie · torttu/tortu-
(tart) · leipä/leivä- (bread) · nuudeli- (noodle) · katkarapu/katkarav-
(prawn) · rapu/ravu- (crab; note: substring of katkarapu — dedupe) ·
kalmari (squid) · mustekala (octopus) · kampasimpuk- (scallop) ·
viiriäi- (quail) · fasaani (pheasant) · burgeri, hampurilai- (burger) ·
keitto/keito- (soup) · muhenno- (stew) · chili · tapas
(Deliberately skipped: FI "pata" — too polysemous.)

**Russian — additions to `_RU_FOOD_STEMS`** (these are missing; суп, краб,
кальмар, осьминог, гребешк, креветк, бургер, рагу are already present —
verify, don't duplicate):
пудинг · мусс · фондю · брауни · тарт · хлеб · бриош · лепешк · лепёшк ·
лапш · пельмен · вареник · клецк · клёцк · перепел · фазан · чили · тапас

## Red-first requirement
BEFORE the edits, run three probe assertions and confirm they FAIL:
`_is_food_query("Welcher Wein passt zu Suppe?", None)`,
`_is_food_query("Какое вино подойдет к пельменям?", None)`,
`_is_food_query("Mikä viini sopii keittoon?", None)`.
Then apply the vocabulary and confirm they pass.

## Tests — new `tests/test_food_query_multilingual.py`
- Per language: 3–4 positive queries using the NEW nouns (include one
  inflected/plural form per language: "Suppen", "пельменям", "keittoon").
- Per language: 1–2 negative controls (wine-only queries containing NO food
  words) asserting `_is_food_query` stays False — guards against
  over-broad stems.
- One assertion that the three ENGLISH evidence sets are untouched (import
  and compare length to `_FOOD_NOUNS` — or simply rely on the existing sync
  test and state so).

## Verification
1. `pytest` — full suite green incl. `test_food_kws_sync.py` UNCHANGED and
   the new multilingual file.
2. `git diff --stat` — only `src/agent.py`, the new test file, handoff.
3. Report: the final vocabulary actually added per language (the human
   ratifies it post-hoc), any words you dropped and why, and the matching
   mechanisms you found.
4. Handoff: step-3 known gap marked resolved, with the vocabulary summary.
5. STOP for review.
