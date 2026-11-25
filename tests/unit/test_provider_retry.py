from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from threading import Event
from types import SimpleNamespace

import pytest
import requests

from refchecker.checkers import provider_retry
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker, VerificationCancelled
from refchecker.checkers.provider_retry import ProviderRetryPolicy, ProviderUnavailable


def response(status, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    return result


def lookup(policy, fetch, *, scope='provider', wait=lambda _: None):
    return policy.run(scope, fetch, lambda _: [], attempts=3, wait=wait)


def test_consecutive_failures_pause_provider_and_only_one_request_probes(monkeypatch):
    clock = SimpleNamespace(now=0, monotonic=lambda: clock.now)
    monkeypatch.setattr(provider_retry, 'time', clock)
    policy = ProviderRetryPolicy()
    requests_made = []

    def missing(attempt):
        requests_made.append(attempt)
        return response(404)

    for _ in range(3):
        with pytest.raises(ProviderUnavailable) as failure:
            lookup(policy, missing)
        assert failure.value.http_status == 404
    assert requests_made == [1, 1, 1]

    with pytest.raises(ProviderUnavailable, match='60s remaining') as paused:
        lookup(policy, missing)
    assert paused.value.skipped
    assert requests_made == [1, 1, 1]

    clock.now = 60
    with pytest.raises(ProviderUnavailable) as failure:
        lookup(policy, lambda attempt: requests_made.append(attempt) or response(503))
    assert failure.value.http_status == 503
    assert requests_made == [1, 1, 1, 1]
    with pytest.raises(ProviderUnavailable, match='120s remaining'):
        lookup(policy, missing)

    clock.now = 180
    probing = Event()
    finish = Event()

    def recovered(attempt):
        requests_made.append(attempt)
        probing.set()
        assert finish.wait(2)
        return response(200)

    with ThreadPoolExecutor(max_workers=1) as pool:
        probe = pool.submit(lookup, policy, recovered)
        try:
            assert probing.wait(2)
            with pytest.raises(ProviderUnavailable, match='another request tests provider recovery'):
                lookup(policy, missing)
        finally:
            finish.set()
        assert probe.result(timeout=2) == []

    # A valid, empty response restores service and gives the next lookup
    # a full retry budget again.
    attempts = []

    def transient(attempt):
        attempts.append(attempt)
        return response(503 if attempt < 3 else 200)

    assert lookup(policy, transient) == []
    assert attempts == [1, 2, 3]


def test_retry_after_http_date_pauses_only_affected_scope(monkeypatch):
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    clock = SimpleNamespace(monotonic=lambda: 0, time=now.timestamp)
    monkeypatch.setattr(provider_retry, 'time', clock)
    policy = ProviderRetryPolicy()
    limited = response(429, {'Retry-After': format_datetime(now + timedelta(seconds=90), usegmt=True)})

    with pytest.raises(ProviderUnavailable, match='Retry after 90s'):
        lookup(policy, lambda _: limited, scope='limited-key')
    with pytest.raises(ProviderUnavailable, match='90s remaining'):
        lookup(policy, lambda _: pytest.fail('Paused provider was queried'), scope='limited-key')
    assert lookup(policy, lambda _: response(200), scope='other-key') == []


def test_cancel_interrupts_a_provider_backoff():
    checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
    checker.cancel_event = Event()
    attempts = []

    def fetch(attempt):
        attempts.append(attempt)
        return response(503)

    def wait(delay):
        if delay:
            checker.cancel_event.set()
        checker._wait_or_cancel(delay)

    policy = ProviderRetryPolicy()
    with pytest.raises(VerificationCancelled):
        lookup(policy, fetch, wait=wait)
    assert attempts == [1]
