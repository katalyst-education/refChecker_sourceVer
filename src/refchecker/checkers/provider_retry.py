"""Bound HTTP retries and share provider health across checker instances."""

from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import threading
import time

import requests


def retry_after_seconds(response, default):
    value = response.headers.get('Retry-After')
    if value:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                seconds = when.timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                return default
        if math.isfinite(seconds):
            return max(0, seconds)
    return default


class ProviderUnavailable(Exception):
    """A display-safe failure without a request URL or credentials."""

    def __init__(self, detail, *, http_status=None, skipped=False):
        super().__init__(detail)
        self.http_status = http_status
        self.skipped = skipped

    def finding(self):
        return {
            'error_type': 'api_failure',
            'error_details': str(self),
            'http_status': self.http_status,
            'provider_skipped': self.skipped,
        }


@dataclass
class _Health:
    failures: int = 0
    generation: int = 0
    blocked_until: float | None = None
    cooldown: float = 0
    probing: bool = False


class ProviderRetryPolicy:
    """Give each lookup one budget and let one request test an expired pause."""

    FAILURE_THRESHOLD = 3
    INITIAL_COOLDOWN = 60
    MAX_COOLDOWN = 900
    MAX_RETRY_DELAY = 30
    AUTH_COOLDOWN = 3600

    def __init__(self):
        self._lock = threading.Lock()
        self._health = {}

    @staticmethod
    def _check_pause(health):
        if health.blocked_until is not None:
            remaining = math.ceil(health.blocked_until - time.monotonic())
            if remaining > 0:
                raise ProviderUnavailable(f'Skipped during provider cooldown ({remaining}s remaining)', skipped=True)
        if health.probing:
            raise ProviderUnavailable('Skipped while another request tests provider recovery', skipped=True)

    def _start(self, scope):
        with self._lock:
            health = self._health.setdefault(scope, _Health())
            self._check_pause(health)
            health.probing = health.blocked_until is not None
            return health, health.generation, health.probing

    def _finish(self, health, generation, *, succeeded=False, failed=False, pause=None):
        with self._lock:
            if generation != health.generation:
                # A parallel response may supply a longer server-directed pause.
                if pause is not None and health.blocked_until is not None:
                    health.blocked_until = max(health.blocked_until, time.monotonic() + pause)
                return
            if succeeded:
                if health.probing:
                    health.generation += 1
                health.failures = 0
                health.blocked_until = None
                health.cooldown = 0
            elif failed or pause is not None:
                health.failures += 1
                if pause is not None or health.probing or health.failures >= self.FAILURE_THRESHOLD:
                    health.cooldown = min(self.MAX_COOLDOWN, max(self.INITIAL_COOLDOWN, health.cooldown * 2))
                    delay = health.cooldown if pause is None else max(1, pause)
                    health.blocked_until = time.monotonic() + delay
                    health.generation += 1
            # A cancelled or rejected probe leaves recovery undecided and
            # releases its slot for the next eligible reference.
            health.probing = False

    def run(self, scope, fetch, parse, *, attempts, wait, pace=None, rate_limit_delay=60, query_rejections=(400, 422)):
        health, generation, probe = self._start(scope)
        succeeded = failed = False
        pause = None
        budget = 1 if probe else max(1, attempts)
        try:
            for attempt in range(budget):
                wait(0)
                if pace is not None:
                    pace()
                with self._lock:
                    if health.generation != generation:
                        self._check_pause(health)
                        raise ProviderUnavailable('Skipped after provider availability changed', skipped=True)
                response = None
                try:
                    response = fetch(attempt + 1)
                    status = response.status_code
                    if 200 <= status < 300:
                        data = parse(response)
                        succeeded = True
                        return data
                    if status == 429:
                        pause = max(1, retry_after_seconds(response, rate_limit_delay))
                        raise ProviderUnavailable(f'Provider rate limited requests. Retry after {math.ceil(pause)}s', http_status=status)
                    if status == 401:
                        pause = self.AUTH_COOLDOWN
                        raise ProviderUnavailable('Provider requires valid credentials', http_status=status)
                    if status in query_rejections:
                        raise ProviderUnavailable('Provider rejected this query or restricted access to its results', http_status=status)
                    transient = status == 408 or (500 <= status < 600 and status not in (501, 505))
                    failure = ProviderUnavailable('Provider request failed', http_status=status)
                except requests.exceptions.RequestException as exc:
                    transient = isinstance(exc, (
                        requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                        requests.exceptions.InvalidJSONError,
                    ))
                    failure = ProviderUnavailable(f'Provider request failed ({type(exc).__name__})')

                if not transient:
                    failed = True
                    raise failure from None
                delay = 2 ** attempt
                if response is not None:
                    delay = retry_after_seconds(response, delay)
                    if delay > self.MAX_RETRY_DELAY:
                        pause = delay
                        raise failure from None
                if attempt + 1 == budget:
                    failed = True
                    raise failure from None
                wait(min(self.MAX_RETRY_DELAY, delay))
        finally:
            self._finish(health, generation, succeeded=succeeded, failed=failed, pause=pause)
