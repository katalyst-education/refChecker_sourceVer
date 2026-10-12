"""A cited URL we could not read must not be reported as a content mismatch.

Reference 1 of a real production check (id 952) was a Hugging Face model card:

    Kimi K3: Model weights and technical report
    venue: Open-weight release
    url:   https://huggingface.co/moonshotai/Kimi-K3

The page exists and returns 200 on request, but when Hugging Face blocked the
run with a 403 the reference was reported as
"Cited URL does not reference this paper" - a claim about content that was
never fetched.
"""

import pytest

from refchecker.checkers.webpage_checker import WebPageChecker


KIMI_URL = 'https://huggingface.co/moonshotai/Kimi-K3'


@pytest.mark.parametrize('status', [None, 401, 403, 429, 500, 503, 404])
def test_scholarly_url_access_failure_is_not_a_missing_page(status, monkeypatch):
    from unittest.mock import Mock
    from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker

    checker = WebPageChecker()
    response = None if status is None else Mock(status_code=status)
    monkeypatch.setattr(checker, '_respectful_request', lambda *args, **kwargs: response)
    reference = {
        'title': 'Guidelines for performing Systematic Literature Reviews in software engineering',
        'venue': 'EBSE Technical Report EBSE-2007-01',
        'url': 'https://www.semanticscholar.org/paper/bf3910a40028240b821790738896954638932e33',
    }
    data, errors, url = checker.verify_raw_url_for_unverified_reference(reference)
    reason = checker.check_unverified_url_reference(reference)
    assert data is None
    assert reason == errors[0]['error_details']
    message = EnhancedHybridReferenceChecker._url_failure_message(reason, url)
    if status == 404:
        assert 'Non-existent web page' in message
    else:
        assert 'could not be accessed' in message
        assert 'Non-existent' not in message
        assert 'does not reference' not in message


@pytest.fixture
def checker():
    return WebPageChecker()


class TestTrustedHostsAreWebContent:
    """The two helpers disagreed: huggingface.co was trusted by one and unknown
    to the other, so a blocked model card produced a hard error."""

    def test_model_card_host_counts_as_web_content(self, checker):
        assert checker._is_web_content_venue('Open-weight release', KIMI_URL) is True

    def test_helpers_agree_on_trusted_hosts(self, checker):
        for url in [
            KIMI_URL,
            'https://www.anthropic.com/news/some-announcement',
            'https://ai.google.dev/gemma/docs',
        ]:
            assert checker._is_trusted_web_content_url(url) is True
            assert checker._is_web_content_venue('Open-weight release', url) is True

    def test_academic_venue_still_wins(self, checker):
        """An academic venue must not be reclassified just because the host is
        a trusted web-content domain."""
        assert checker._is_web_content_venue(
            'International Conference on Machine Learning', KIMI_URL
        ) is False

    def test_academic_host_is_not_web_content(self, checker):
        assert checker._is_web_content_venue(
            'Open-weight release', 'https://arxiv.org/abs/2501.00001'
        ) is False

    def test_empty_venue_is_unchanged(self, checker):
        """No venue means there is nothing to classify."""
        assert checker._is_web_content_venue('', KIMI_URL) is False


class TestBlockedUrlIsVerifiedNotErrored:
    def test_403_on_a_model_card_verifies_instead_of_erroring(self, checker, monkeypatch):
        class _Blocked:
            status_code = 403
            headers = {}

        monkeypatch.setattr(checker, '_respectful_request', lambda *a, **k: _Blocked())

        data, errors, url = checker.verify_raw_url_for_unverified_reference({
            'title': 'Kimi K3: Model weights and technical report',
            'authors': ['Moonshot AI'],
            'year': 2026,
            'venue': 'Open-weight release',
            'cited_url': KIMI_URL,
        })

        assert errors == []
        assert data is not None
        assert data['_matched_database'] == 'Web Page'
        assert url == KIMI_URL


class TestInaccessibleUrlMessage:
    """Even when a URL cannot be classified as web content, the message must
    describe what happened rather than assert a mismatch."""

    @staticmethod
    def _msg(subreason):
        from refchecker.checkers.enhanced_hybrid_checker import (
            EnhancedHybridReferenceChecker,
        )
        return EnhancedHybridReferenceChecker._url_failure_message(subreason, KIMI_URL)

    def test_blocked_url_reports_access_failure_not_a_mismatch(self):
        msg = self._msg('paper not verified; cited URL could not be accessed')
        assert 'could not be accessed' in msg
        assert 'does not reference this paper' not in msg
        assert KIMI_URL in msg

    def test_missing_page_still_reports_non_existent(self):
        assert self._msg('non-existent web page').startswith('Non-existent web page')

    def test_url_references_paper_is_unchanged(self):
        assert 'URL references paper' in self._msg('URL references paper')

    def test_genuine_mismatch_still_says_so(self):
        """A page we did read and that did not mention the reference must keep
        the strong wording."""
        assert 'does not reference this paper' in self._msg('title not found on page')

    def test_empty_subreason_falls_back_to_mismatch(self):
        assert 'does not reference this paper' in self._msg('')


def test_message_wording_exists_in_source():
    """Guard the exact wording: the old message asserted a content mismatch for
    a page that was never read."""
    import inspect
    from refchecker.checkers.enhanced_hybrid_checker import (
        EnhancedHybridReferenceChecker,
    )

    src = inspect.getsource(EnhancedHybridReferenceChecker._url_failure_message)
    assert 'could not be accessed to confirm the' in src
