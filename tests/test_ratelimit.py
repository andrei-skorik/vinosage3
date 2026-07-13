"""Tests for the ratelimit.py memory-leak fix (Phase 3, step 2).

Verifies three things:
1. Rate-limit behaviour is byte-for-byte unchanged (allow up to N per window,
   block the N+1th, correct retry_after, window slides).
2. The leak is actually fixed: stale sessions are purged, so |_windows| stays
   bounded instead of growing with every session ever seen.
3. The purge never evicts a session that is still inside its window.

Time is controlled via monkeypatching time.time inside src.ratelimit — no
sleeps, tests run instantly.
"""
from __future__ import annotations

from collections import deque

import pytest

import src.ratelimit as rl
from src.config import RATE_LIMIT_PER_MIN


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Isolate module state per test: fresh dict, cleanup timer reset."""
    monkeypatch.setattr(rl, "_windows", {})
    monkeypatch.setattr(rl, "_last_cleanup", 0.0)
    yield


class _Clock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(rl.time, "time", c)
    return c


# ── 1. Behaviour unchanged ────────────────────────────────────────────────────


def test_allows_up_to_limit_then_blocks(clock):
    for _ in range(RATE_LIMIT_PER_MIN):
        assert rl.check_rate_limit("s1").allowed is True

    res = rl.check_rate_limit("s1")
    assert res.allowed is False
    assert res.reason == "RATE_LIMIT"
    assert res.retry_after_s == pytest.approx(60.0, abs=0.2)


def test_window_slides_and_unblocks(clock):
    for _ in range(RATE_LIMIT_PER_MIN):
        rl.check_rate_limit("s1")
    assert rl.check_rate_limit("s1").allowed is False

    clock.advance(61)  # entire window aged out
    assert rl.check_rate_limit("s1").allowed is True


def test_sessions_are_independent(clock):
    for _ in range(RATE_LIMIT_PER_MIN):
        rl.check_rate_limit("s1")
    assert rl.check_rate_limit("s1").allowed is False
    assert rl.check_rate_limit("s2").allowed is True  # other session unaffected


# ── 2. The leak is fixed ──────────────────────────────────────────────────────


def test_stale_sessions_are_purged(clock):
    # Simulate 500 one-shot visitors (the leak scenario: each browser session
    # calls check_rate_limit once and never returns).
    for i in range(500):
        rl.check_rate_limit(f"visitor-{i}")
    assert len(rl._windows) == 500  # pre-purge: dict has grown

    # Age everything out of the window, pass the cleanup interval, and make
    # one more call — the sweep piggybacks on it.
    clock.advance(rl._WINDOW_S + rl._CLEANUP_INTERVAL_S + 1)
    rl.check_rate_limit("fresh-session")

    # Only the fresh session remains — bounded, not unbounded.
    assert set(rl._windows) == {"fresh-session"}


def test_dict_stays_bounded_over_many_waves(clock):
    """Rolling waves of visitors must not accumulate: after each aged-out
    wave + sweep, the dict holds only the current wave (+1 trigger call)."""
    for wave in range(5):
        for i in range(100):
            rl.check_rate_limit(f"w{wave}-v{i}")
        clock.advance(rl._WINDOW_S + rl._CLEANUP_INTERVAL_S + 1)
        rl.check_rate_limit("sweeper")
        clock.advance(1)
        assert len(rl._windows) <= 101  # previous waves fully gone


def test_purge_is_rate_limited_by_interval(clock):
    """The sweep must not run on every call (that would rescan the dict per
    request) — only after _CLEANUP_INTERVAL_S has passed."""
    rl.check_rate_limit("old-session")
    clock.advance(rl._WINDOW_S + 1)  # old-session is now stale…
    rl.check_rate_limit("s2")        # …but interval hasn't passed since last sweep
    assert "old-session" in rl._windows  # not purged yet — by design

    clock.advance(rl._CLEANUP_INTERVAL_S + 1)
    rl.check_rate_limit("s3")
    assert "old-session" not in rl._windows  # purged on the next interval


# ── 3. The purge never evicts live sessions ───────────────────────────────────


def test_active_session_survives_purge_and_keeps_its_count(clock):
    # s1 has used half its budget, recently.
    half = RATE_LIMIT_PER_MIN // 2
    for _ in range(half):
        rl.check_rate_limit("s1")

    # Force the sweep to be due WITHOUT ageing s1's timestamps: rewind the
    # sweep timer instead of advancing the clock (advancing past the cleanup
    # interval would also age s1 out, since _CLEANUP_INTERVAL_S > _WINDOW_S).
    clock.advance(10)  # s1's timestamps are 10 s old — well inside the window
    rl._last_cleanup = clock.now - rl._CLEANUP_INTERVAL_S - 1
    rl.check_rate_limit("s2")  # triggers the sweep

    assert "s1" in rl._windows               # live session not evicted
    assert len(rl._windows["s1"]) == half    # and its budget is intact

    # Its remaining budget still enforces correctly.
    for _ in range(RATE_LIMIT_PER_MIN - half):
        assert rl.check_rate_limit("s1").allowed is True
    assert rl.check_rate_limit("s1").allowed is False


def test_empty_deque_sessions_are_purged(clock):
    # Manually craft the edge: a session entry whose deque is empty.
    rl._windows["ghost"] = deque()
    clock.advance(rl._CLEANUP_INTERVAL_S + 1)
    rl.check_rate_limit("s1")
    assert "ghost" not in rl._windows


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
