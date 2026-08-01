"""Bounded in-memory request limiting for JX3 queries."""

from __future__ import annotations

import time
from collections import deque


class SessionRateLimiter:
    """Limit requests per AstrBot session without persisting session identifiers."""

    def __init__(
        self,
        requests_per_minute: int,
        *,
        window_seconds: float = 60.0,
        max_sessions: int = 1_000,
    ) -> None:
        self.requests_per_minute = max(1, requests_per_minute)
        self.window_seconds = window_seconds
        self.max_sessions = max_sessions
        self._requests: dict[str, deque[float]] = {}

    def check(self, session_key: str, *, now: float | None = None) -> float:
        """Return zero when allowed, otherwise return seconds until retry."""
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        history = self._requests.setdefault(session_key, deque())
        while history and history[0] <= cutoff:
            history.popleft()

        if len(history) >= self.requests_per_minute:
            return max(0.1, history[0] + self.window_seconds - current)

        history.append(current)
        if len(self._requests) > self.max_sessions:
            self._prune(cutoff)
        return 0.0

    def clear(self) -> None:
        """Drop all ephemeral request histories."""
        self._requests.clear()

    def _prune(self, cutoff: float) -> None:
        stale = [
            key
            for key, history in self._requests.items()
            if not history or history[-1] <= cutoff
        ]
        for key in stale:
            self._requests.pop(key, None)

        overflow = len(self._requests) - self.max_sessions
        if overflow > 0:
            oldest = sorted(
                self._requests,
                key=lambda key: self._requests[key][-1],
            )[:overflow]
            for key in oldest:
                self._requests.pop(key, None)
