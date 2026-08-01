"""Verify bounded in-memory session rate limiting."""

from __future__ import annotations

from astrbot_plugin_jx3tools.rate_limit import SessionRateLimiter


def test_rate_limit_rejects_then_recovers() -> None:
    limiter = SessionRateLimiter(2, window_seconds=60)

    assert limiter.check("session", now=0) == 0
    assert limiter.check("session", now=1) == 0
    assert limiter.check("session", now=2) == 58
    assert limiter.check("session", now=61) == 0


def test_rate_limit_bounds_session_storage() -> None:
    limiter = SessionRateLimiter(1, max_sessions=2)

    limiter.check("one", now=0)
    limiter.check("two", now=1)
    limiter.check("three", now=2)

    assert len(limiter._requests) <= 2
