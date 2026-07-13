"""Hardening tests (Phase 3, step 6) — closing inherited Phase-2 gaps #3/#4/#5.

Three self-contained groups:
- Locale parity: all four locale files carry the SAME key set and the same
  {placeholders} per key. This permanently closes the "added a key to en.json
  and forgot fi.json" class of bugs (Phase-2 gap #5, generalized).
- LangSmith graceful absence: the app imports and reports tracing disabled
  when the key is absent/empty (Phase-2 gap #4).
- Cost cap boundaries: exact-cap blocks, cap-minus-one allows, and the
  documented fail-open behavior on a DB error (Phase-2 gap #3, unit level;
  the pre-flight placement check lives in the task's spec'd part).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import src.ratelimit as rl
from src.config import DAILY_COST_CAP_MICROS

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_LOCALES = ("en", "de", "ru", "fi")


# ── Phase-2 gap #5 (generalized): locale files stay in lockstep ───────────────


def _load(locale: str) -> dict:
    return json.loads((_LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def test_all_locales_have_identical_key_sets():
    """On failure the message names the locale and the exact missing/extra
    keys — add the key to EVERY locale file, not just en.json."""
    en_keys = set(_load("en"))
    for loc in _LOCALES[1:]:
        keys = set(_load(loc))
        assert keys == en_keys, (
            f"{loc}.json drift: missing={sorted(en_keys - keys)} "
            f"extra={sorted(keys - en_keys)}"
        )


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def test_placeholders_match_across_locales():
    """A translation that drops or renames a {placeholder} breaks
    str.format at runtime in exactly one locale — catch it here instead."""
    en = _load("en")
    for loc in _LOCALES[1:]:
        data = _load(loc)
        for key, en_val in en.items():
            if not isinstance(en_val, str) or key not in data:
                continue
            loc_val = data[key]
            if not isinstance(loc_val, str):
                continue
            assert set(_PLACEHOLDER_RE.findall(en_val)) == set(_PLACEHOLDER_RE.findall(loc_val)), (
                f"{loc}.json key '{key}': placeholder mismatch vs en.json"
            )


def test_welcome_examples_present_in_all_locales():
    """welcome_examples is a list, skipped by the placeholder check — assert
    it exists and is non-empty everywhere (chips render from it)."""
    for loc in _LOCALES:
        examples = _load(loc).get("welcome_examples")
        assert isinstance(examples, list) and examples, f"{loc}.json welcome_examples"


# ── Phase-2 gap #4: LangSmith key absent → app runs, tracing off ─────────────


def test_config_imports_with_langsmith_absent():
    """Run the import in a subprocess so the module-level Final constants are
    computed fresh under a LangSmith-free environment. Empty-string env vars
    are used (python-dotenv does NOT override existing vars by default, so
    values in a local .env cannot leak back in)."""
    env = dict(os.environ)
    env.update({
        "LANGSMITH_API_KEY": "", "LANGSMITH_TRACING": "",
        "LANGSMITH_PROJECT": "", "LANGSMITH_ENDPOINT": "",
        # required secrets: dummies so config._require passes even without .env
        "OPENROUTER_API_KEY": env.get("OPENROUTER_API_KEY") or "test",
        "SUPABASE_URL": env.get("SUPABASE_URL") or "test",
        "SUPABASE_ANON_KEY": env.get("SUPABASE_ANON_KEY") or "test",
        "SUPABASE_SERVICE_KEY": env.get("SUPABASE_SERVICE_KEY") or "test",
        "ADMIN_PASSWORD": env.get("ADMIN_PASSWORD") or "test",
    })
    proc = subprocess.run(
        [sys.executable, "-c",
         "from src.config import LANGSMITH_ENABLED; print(LANGSMITH_ENABLED)"],
        capture_output=True, text=True, env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


# ── Phase-2 gap #3 (unit level): cost cap boundaries + fail-open ─────────────


def test_cost_cap_blocks_at_exact_cap(monkeypatch):
    monkeypatch.setattr(rl, "get_daily_cost_micros", lambda: DAILY_COST_CAP_MICROS)
    res = rl.check_cost_cap()
    assert res.allowed is False and res.reason == "COST_CAP"


def test_cost_cap_allows_just_under_cap(monkeypatch):
    monkeypatch.setattr(rl, "get_daily_cost_micros", lambda: DAILY_COST_CAP_MICROS - 1)
    assert rl.check_cost_cap().allowed is True


def test_cost_cap_fails_open_on_db_error(monkeypatch):
    """Documented (and here, pinned) behavior: if the spend query fails,
    get_daily_cost_micros returns 0 and the cap does NOT block — availability
    over strict accounting. If this trade-off is ever reversed, this test
    must be consciously updated, not silently broken."""
    import src.catalog as catalog

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog, "get_service_db", _boom)
    assert rl.get_daily_cost_micros() == 0
    assert rl.check_cost_cap().allowed is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
