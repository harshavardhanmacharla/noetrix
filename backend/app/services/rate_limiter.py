"""
In-memory rate limiter for brute-force protection on authentication endpoints.
"""
from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Dict, List


class LoginRateLimiter:
    """Thread-safe sliding-window rate limiter for failed login attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _cleanup_old_attempts(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._failures[key] = [t for t in self._failures[key] if t > cutoff]

    def is_rate_limited(self, key: str) -> bool:
        """Check if key has exceeded the allowed failure attempts within the window."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            self._cleanup_old_attempts(key, now)
            return len(self._failures[key]) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        """Record a failed attempt for the given key."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            self._cleanup_old_attempts(key, now)
            self._failures[key].append(now)

    def reset(self, key: str) -> None:
        """Reset failed attempts for key upon successful authentication."""
        with self._lock:
            if key in self._failures:
                del self._failures[key]


login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)
