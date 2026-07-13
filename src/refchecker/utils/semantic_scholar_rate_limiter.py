"""
Shared Semantic Scholar Rate Limiter utility.

Semantic Scholar allows 1 request/second across all endpoints.
This singleton enforces that limit proactively across all checkers.
"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class SemanticScholarRateLimiter:
    _instance = None
    _lock = threading.Lock()
    DEFAULT_DELAY = 1.1  # Slightly above 1.0s for safety margin

    def __init__(self, delay: float = DEFAULT_DELAY):
        self._delay = delay
        self._last_request_time: float = 0.0
        self._request_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SemanticScholarRateLimiter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def wait(self) -> float:
        """Block until it is safe to send the next request. Returns seconds waited."""
        with self._request_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            wait_time = max(0.0, self._delay - elapsed)
            if wait_time > 0:
                logger.debug(f"SemanticScholarRateLimiter: waiting {wait_time:.3f}s")
                time.sleep(wait_time)
            self._last_request_time = time.monotonic()
            return wait_time

    def set_delay(self, delay: float) -> None:
        """Update the minimum delay. Called when the setting changes"""
        with self._request_lock:
            self._delay = max(1.0, delay)   # never go below SS hard limit of 1.0 s
            logger.info(f"SemanticScholarRateLimiter: delay updated to {self._delay}s")