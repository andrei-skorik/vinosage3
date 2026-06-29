"""Per-user durable taste profile — long-term memory (SPEC §5.3, §4.3).

Reads go through the user's own authed client (auth.uid() = user_id via RLS),
mirroring src/auth.py's get_profile/get_query_history — least-privilege, and
consistent with how the rest of the app reads per-user data.

Writes (upsert/delete) go through the service-role client, mirroring
src/logging_db.py: every write swallows exceptions and reports success via a
bool return instead of raising, so a DB hiccup never breaks the chat
(extract_preferences calls this unattended, mid-turn) while the sidebar's
explicit Save/Delete buttons can still show a user-facing error.

Anonymous users (no user_id) never reach this module — their profile lives
only in st.session_state for the browser session (wired in app.py).

CARDINAL RULE (SPEC §5.3): this module only ever shapes search/ranking
inputs. A preference value is written to a structured array ONLY if it
matches a real catalog vocabulary term (type/grape/country/style); anything
else goes into the free-form `notes` field, never invented into a
structured array.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from supabase import create_client

from src.catalog import get_active_wines_df, get_service_db
from src.config import SUPABASE_ANON_KEY, SUPABASE_URL

log = logging.getLogger(__name__)

LIST_FIELDS: tuple[str, ...] = (
    "preferred_types", "preferred_grapes", "preferred_countries", "preferred_regions",
    "preferred_styles", "preferred_characteristics",
    "disliked_types", "disliked_grapes", "disliked_styles",
)

EMPTY_PROFILE: dict[str, Any] = {
    "expertise_level": "beginner",
    **{f: [] for f in LIST_FIELDS},
    "min_price_eur_cents": None,
    "max_price_eur_cents": None,
    "notes": None,
}

_NOTES_MAX_LEN = 1000


def _authed_client(access_token: str, refresh_token: str):
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.set_session(access_token, refresh_token)
    return client


# ── Read (authed client, RLS) ─────────────────────────────────────────────────

def get_preferences(access_token: str, refresh_token: str, user_id: str) -> dict[str, Any]:
    """Read this user's own row via their session (auth.uid() = user_id).

    Returns a fresh EMPTY_PROFILE on any failure or missing row (edge case
    #4: treat as empty, chat continues unpersonalised) — never raises.
    """
    try:
        client = _authed_client(access_token, refresh_token)
        resp = client.table("user_preferences").select("*").eq("user_id", user_id).limit(1).execute()
        if resp.data:
            return resp.data[0]
    except Exception as exc:
        log.warning("get_preferences failed: %s", exc)
    return dict(EMPTY_PROFILE)


# ── Write (service-role client) ───────────────────────────────────────────────

def upsert_preferences(user_id: str, **fields: Any) -> bool:
    """Upsert (insert-or-update) the caller's row. Swallows exceptions —
    returns False on failure so callers decide whether to surface an error
    (sidebar Save) or stay silent (extract_preferences)."""
    try:
        row = {"user_id": user_id, **fields}
        get_service_db().table("user_preferences").upsert(row).execute()
        return True
    except Exception as exc:
        log.warning("upsert_preferences failed: %s", exc)
        return False


def delete_preferences(user_id: str) -> bool:
    """Hard-delete this user's row (US-004 'Forget everything about me')."""
    try:
        get_service_db().table("user_preferences").delete().eq("user_id", user_id).execute()
        return True
    except Exception as exc:
        log.warning("delete_preferences failed: %s", exc)
        return False


# ── Explicit, confident-only signal extraction (SPEC §5.3 Write) ─────────────

_POSITIVE_VERBS = r"like|love|prefer|enjoy|adore"
_NEGATIVE_VERBS = r"hate|dislike|can'?t stand|cannot stand|don'?t like|do not like"
_SIGNAL_VERB = re.compile(
    rf"\bi\s+(?:generally|really|usually|definitely)?\s*"
    rf"(?P<verb>{_POSITIVE_VERBS}|{_NEGATIVE_VERBS})\b",
    re.IGNORECASE,
)
_POSITIVE_SET = {v.strip() for v in _POSITIVE_VERBS.split("|")}
_TRIM_TRAILING_CONNECTOR = re.compile(r"\b(and|but)\s+i\s*$", re.IGNORECASE)
_GENERIC_PHRASES = {"wine", "wines", "it", "this", "that", "them"}

_TYPE_ALIASES: dict[str, str] = {
    "red": "Red", "reds": "Red",
    "white": "White", "whites": "White",
    "rosé": "Rosé", "rose": "Rosé", "roses": "Rosé", "rosés": "Rosé",
    "tawny": "Tawny", "orange": "Orange", "brown": "Brown",
}


def _extract_clauses(text: str) -> list[tuple[bool, str]]:
    """Return [(is_positive, phrase), ...] for each explicit 'I like/hate X'
    clause in text. Casual mentions without this construct never match —
    that's the point (no guessing from a single ambiguous word)."""
    matches = list(_SIGNAL_VERB.finditer(text))
    clauses: list[tuple[bool, str]] = []
    for i, m in enumerate(matches):
        verb = m.group("verb").lower()
        is_positive = verb in _POSITIVE_SET
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        phrase = text[m.end():end]
        # Stop at the first sentence terminator so an unrelated trailing
        # sentence/question never gets swept into this clause's phrase.
        sentence_end = re.search(r"[.!?]", phrase)
        if sentence_end:
            phrase = phrase[:sentence_end.start()]
        phrase = _TRIM_TRAILING_CONNECTOR.sub("", phrase).strip(" ,.;!\n")
        if phrase and phrase.lower() not in _GENERIC_PHRASES:
            clauses.append((is_positive, phrase))
    return clauses


def _match_type(phrase: str, known_types: set[str]) -> str | None:
    for alias, type_name in _TYPE_ALIASES.items():
        if type_name in known_types and re.search(rf"\b{alias}\b", phrase, re.IGNORECASE):
            return type_name
    for type_name in known_types:
        if re.search(rf"\b{re.escape(type_name)}\b", phrase, re.IGNORECASE):
            return type_name
    return None


def _match_literal(phrase: str, known_values: set[str]) -> str | None:
    for value in known_values:
        if isinstance(value, str) and re.search(rf"\b{re.escape(value)}\b", phrase, re.IGNORECASE):
            return value
    return None


def _match_style(phrase: str, known_styles: set[str]) -> str | None:
    for style in known_styles:
        if not isinstance(style, str):
            continue
        words = [w for w in re.split(r"[\s&]+", style) if len(w) >= 4]
        if any(re.search(rf"\b{re.escape(w)}\b", phrase, re.IGNORECASE) for w in words):
            return style
    return None


def detect_preference_signals(text: str, existing_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect explicit taste signals in one turn and merge them (set-union,
    idempotent) with the existing profile's structured arrays.

    Returns {} if nothing explicit was said — callers should treat that as
    "no write needed" rather than upserting an unchanged row every turn.
    """
    existing_profile = existing_profile or {}
    clauses = _extract_clauses(text)
    if not clauses:
        return {}

    df = get_active_wines_df()
    known_types = set(df["type"].dropna().unique().tolist()) if not df.empty else set()
    known_grapes = set(df["grape"].dropna().unique().tolist()) if not df.empty else set()
    known_countries = set(df["country"].dropna().unique().tolist()) if not df.empty else set()
    known_styles = set(df["style"].dropna().unique().tolist()) if not df.empty else set()

    sets: dict[str, set[str]] = {f: set(existing_profile.get(f) or []) for f in LIST_FIELDS}
    note_lines: list[str] = []
    changed = False

    for is_positive, phrase in clauses:
        prefix = "preferred" if is_positive else "disliked"
        matched = False

        type_match = _match_type(phrase, known_types)
        if type_match:
            field = f"{prefix}_types"
            if field in sets and type_match not in sets[field]:
                sets[field].add(type_match)
                changed = True
            matched = True

        grape_match = _match_literal(phrase, known_grapes)
        if grape_match:
            field = f"{prefix}_grapes"
            if field in sets and grape_match not in sets[field]:
                sets[field].add(grape_match)
                changed = True
            matched = True

        if is_positive:
            country_match = _match_literal(phrase, known_countries)
            if country_match and country_match not in sets["preferred_countries"]:
                sets["preferred_countries"].add(country_match)
                changed = True
                matched = True

        style_match = _match_style(phrase, known_styles)
        if style_match:
            field = f"{prefix}_styles"
            if field in sets and style_match not in sets[field]:
                sets[field].add(style_match)
                changed = True
            matched = True

        if not matched:
            verb = "liking" if is_positive else "disliking"
            note_lines.append(f"Mentioned {verb} '{phrase}' (not a recognised catalog term).")

    existing_notes = existing_profile.get("notes") or ""
    new_notes = existing_notes
    for line in note_lines:
        if line not in existing_notes:
            new_notes = (new_notes + "\n" + line).strip() if new_notes else line
            changed = True
    new_notes = new_notes[-_NOTES_MAX_LEN:] if new_notes else None

    if not changed:
        return {}

    result: dict[str, Any] = {f: sorted(sets[f]) for f in LIST_FIELDS}
    result["notes"] = new_notes
    return result
