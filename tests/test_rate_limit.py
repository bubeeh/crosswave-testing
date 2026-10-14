"""Test del rate limiter per piattaforma (persistente su SQLite)."""

from __future__ import annotations

import pytest

from player_engine.core.errors import RateLimitedError
from player_engine.resolver.rate_limit import RateLimiter
from player_engine.storage.db import init_db
from player_engine.storage.repos import RateLimitRepo


def _limiter(interval: float = 5.0) -> RateLimiter:
    conn = init_db(":memory:")
    return RateLimiter(RateLimitRepo(conn), interval=interval)


def test_first_request_allowed():
    rl = _limiter()
    assert rl.check("youtube", now=100.0).allowed is True


def test_second_request_within_interval_blocked():
    rl = _limiter()
    rl.release("youtube", now=100.0)
    gate = rl.check("youtube", now=101.0)
    assert gate.allowed is False
    assert gate.retry_after == pytest.approx(4.0)


def test_request_after_interval_allowed():
    rl = _limiter()
    rl.release("youtube", now=100.0)
    assert rl.check("youtube", now=105.5).allowed is True


def test_acquire_raises_when_blocked():
    rl = _limiter()
    rl.release("bandcamp", now=100.0)
    with pytest.raises(RateLimitedError):
        rl.acquire("https://x", "bandcamp", now=101.0)


def test_platforms_are_independent():
    rl = _limiter()
    rl.release("youtube", now=100.0)
    assert rl.check("soundcloud", now=100.0).allowed is True
