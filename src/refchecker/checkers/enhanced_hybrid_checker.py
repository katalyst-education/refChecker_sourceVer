#!/usr/bin/env python3
"""
Enhanced Hybrid Reference Checker with Multiple API Sources

This module provides an improved hybrid reference checker that intelligently combines
multiple API sources for optimal reliability and performance. It replaces Google Scholar
with more reliable alternatives while maintaining backward compatibility.

New API Integration Priority:
1. Local Semantic Scholar Database (fastest, offline)
2. Semantic Scholar API (reliable, good coverage)  
3. OpenAlex API (excellent reliability, replaces Google Scholar)
4. CrossRef API (best for DOI-based verification)
5. DNB, TIB, ZDB, Open Library, and specialist indexes
6. Google Books (keyed, book-only final fallback)

Usage:
    from enhanced_hybrid_checker import EnhancedHybridReferenceChecker
    
    checker = EnhancedHybridReferenceChecker(
        semantic_scholar_api_key="your_key",
        db_path="path/to/db.sqlite",
        contact_email="your@email.com"
    )
    
    verified_data, errors, url = checker.verify_reference(reference)
"""

import logging
import os
import random
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from typing import Callable, Dict, List, Tuple, Optional, Any

from refchecker.utils.database_config import DATABASE_LABELS, DATABASE_LOOKUP_ORDER
from refchecker.utils.reference_fixups import fixup_reference_fields

logger = logging.getLogger(__name__)


class VerificationCancelled(Exception):
    """Raised when a caller cancels a long-running verification."""


def _venue_text(venue: Any) -> str:
    """Flatten a venue value to plain text.

    Venue fields don't always arrive as strings. Semantic Scholar returns
    ``journal`` as an object (``{'name': ..., 'volume': ...}``) and Crossref
    returns ``container-title`` as a list, so code that fell back from an empty
    ``venue`` to ``journal`` could hand a dict to string comparisons. That
    raised ``AttributeError: 'dict' object has no attribute 'strip'`` inside the
    wrong-paper check, which the caller recorded as a checker failure — the
    reference was reported unverified even though the database had matched it.
    """
    if venue is None:
        return ''
    if isinstance(venue, str):
        return venue.strip()
    if isinstance(venue, dict):
        for key in ('name', 'title', 'container-title', 'fullName', 'display_name'):
            value = venue.get(key)
            if value:
                return _venue_text(value)
        return ''
    if isinstance(venue, (list, tuple)):
        for item in venue:
            text = _venue_text(item)
            if text:
                return text
        return ''
    return str(venue).strip()


class EnhancedHybridReferenceChecker:
    """
    Enhanced hybrid reference checker with multiple API sources for improved reliability
    """

    def _initialize_checker(self, module_name: str, class_name: str, log_name: str,
                            *args: Any, error_level: str = 'warning', **kwargs: Any) -> Any:
        """Initialize an optional checker and keep logging behavior consistent."""
        try:
            module = import_module(f'.{module_name}', package=__package__)
            checker_class = getattr(module, class_name)
            checker = checker_class(*args, **kwargs)
            logger.debug(f"Enhanced Hybrid: {log_name} initialized")
            return checker
        except Exception as exc:
            log_message = f"Enhanced Hybrid: Failed to initialize {log_name}: {exc}"
            if error_level == 'error':
                logger.error(log_message)
            else:
                logger.warning(log_message)
            return None
    
    def __init__(self, semantic_scholar_api_key: Optional[str] = None,
                 db_path: Optional[str] = None,
                 db_paths: Optional[Dict[str, str]] = None,
                 contact_email: Optional[str] = None,
                 paperclip_api_key: Optional[str] = None,
                 google_books_api_key: Optional[str] = None,
                 enable_openalex: bool = True,
                 enable_crossref: bool = True,
                 enable_open_library: bool = True,
                 enable_econbiz: bool = True,
                 enable_dnb: bool = True,
                 enable_zdb: bool = True,
                 enable_google_books: Optional[bool] = None,
                 google_books_include_magazines: Optional[bool] = None,
                 enable_arxiv_citation: bool = True,
                 enable_acl_anthology: bool = True,
                 enable_paperclip: Optional[bool] = None,
                 debug_mode: bool = False,
                 cache_dir: Optional[str] = None,
                 enable_tib: bool = True,
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 cancel_event: Optional[threading.Event] = None):
        """
        Initialize the enhanced hybrid reference checker
        
        Args:
            semantic_scholar_api_key: Optional API key for Semantic Scholar
            paperclip_api_key: Optional API key for Paperclip secondary verification
            google_books_api_key: Optional API key for the final Google Books fallback
            db_path: Optional path to local Semantic Scholar database
            contact_email: Email for polite pool access to APIs
            enable_openalex: Whether to use OpenAlex API
            enable_crossref: Whether to use CrossRef API
            enable_open_library: Whether to use Open Library as a book-reference fallback
            enable_econbiz: Whether to use EconBiz for economics and business literature
            enable_dnb: Whether to use the DNB catalogue SRU API
            enable_tib: Whether to use the TIB catalogue SRU API
            enable_zdb: Whether to use the ZDB catalogue SRU API
            enable_google_books: Whether to use Google Books as the final book/magazine fallback
            google_books_include_magazines: Whether explicit magazine citations may use that fallback
            enable_arxiv_citation: Whether to use ArXiv Citation checker as authoritative source
            enable_acl_anthology: Whether to use ACL Anthology API
            debug_mode: Whether to enable debug logging
        """
        self.contact_email = contact_email
        self.debug_mode = debug_mode
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        
        # Initialize ArXiv Citation checker (authoritative source for ArXiv papers)
        self.arxiv_citation = None
        if enable_arxiv_citation:
            self.arxiv_citation = self._initialize_checker(
                'arxiv_citation', 'ArXivCitationChecker', 'ArXiv Citation checker'
            )
        
        # Initialize local database checkers (S2 first, then optional additional DBs)
        resolved_db_paths = dict(db_paths or {})
        if db_path and 's2' not in resolved_db_paths:
            resolved_db_paths['s2'] = db_path
        self.db_paths = resolved_db_paths

        self.local_db = None  # Backward-compat alias for S2 local DB
        self.local_db_checkers: List[Tuple[str, str, Any]] = []
        for db_name in DATABASE_LOOKUP_ORDER:
            db_file = resolved_db_paths.get(db_name)
            if not db_file:
                continue
            checker_key = f'local_{db_name}'
            checker_label = DATABASE_LABELS.get(db_name, db_name.upper())
            checker = self._initialize_checker(
                'local_semantic_scholar',
                'LocalNonArxivReferenceChecker',
                f'local {checker_label} database',
                db_path=db_file,
                database_label=checker_label,
                database_key=checker_key,
                error_level='error',
            )
            if checker is None:
                raise RuntimeError(
                    f"Failed to open local {checker_label} database at {db_file}. "
                    f"Check that the file exists and contains a valid 'papers' table."
                )
            self.local_db_checkers.append((checker_key, checker_label, checker))
            if db_name == 's2':
                self.local_db = checker
            logger.debug(f"Enhanced Hybrid: Local {checker_label} database enabled at {db_file}")
        
        # Initialize Semantic Scholar API
        self.semantic_scholar = self._initialize_checker(
            'semantic_scholar', 'NonArxivReferenceChecker', 'Semantic Scholar API',
            api_key=semantic_scholar_api_key, error_level='error'
        )
        
        # Initialize OpenAlex API
        self.openalex = None
        if enable_openalex:
            self.openalex = self._initialize_checker(
                'openalex', 'OpenAlexReferenceChecker', 'OpenAlex API', email=contact_email
            )
        
        # Initialize CrossRef API
        self.crossref = None
        if enable_crossref:
            self.crossref = self._initialize_checker(
                'crossref', 'CrossRefReferenceChecker', 'CrossRef API', email=contact_email
            )

        self.open_library = None
        if enable_open_library:
            self.open_library = self._initialize_checker(
                'open_library', 'OpenLibraryReferenceChecker', 'Open Library API', email=contact_email
            )

        self.econbiz = None
        if enable_econbiz:
            self.econbiz = self._initialize_checker(
                'econbiz', 'EconBizReferenceChecker', 'EconBiz API', email=contact_email
            )

        self.dnb = None
        if enable_dnb:
            self.dnb = self._initialize_checker(
                'dnb_sru', 'DnbSruReferenceChecker', 'DNB catalogue SRU API', email=contact_email
            )

        self.tib = None
        if enable_tib:
            self.tib = self._initialize_checker(
                'dnb_sru', 'TibSruReferenceChecker', 'TIB catalogue SRU API', email=contact_email
            )

        self.zdb = None
        if enable_zdb:
            self.zdb = self._initialize_checker(
                'dnb_sru', 'ZdbSruReferenceChecker', 'ZDB catalogue SRU API', email=contact_email
            )

        if enable_google_books is None:
            enable_google_books = bool(
                google_books_api_key or os.environ.get('GOOGLE_BOOKS_API_KEY')
            )
        if google_books_include_magazines is None:
            google_books_include_magazines = str(
                os.environ.get('REFCHECKER_GOOGLE_BOOKS_INCLUDE_MAGAZINES', 'true')
            ).strip().lower() in {'1', 'true', 'yes', 'on'}
        self.google_books_include_magazines = bool(google_books_include_magazines)
        self.google_books = None
        if enable_google_books:
            self.google_books = self._initialize_checker(
                'google_books', 'GoogleBooksReferenceChecker', 'Google Books API',
                api_key=google_books_api_key,
                include_magazines=self.google_books_include_magazines,
            )

        
        # Initialize OpenReview checker
        self.openreview = self._initialize_checker(
            'openreview_checker', 'OpenReviewReferenceChecker', 'OpenReview checker'
        )
        
        # Initialize DBLP checker (curated CS bibliography, strong for conferences)
        self.dblp = self._initialize_checker(
            'dblp', 'DBLPReferenceChecker', 'DBLP checker', email=contact_email
        )
        
        # Initialize ACL Anthology checker (NLP/CL bibliography)
        self.acl_anthology = None
        if enable_acl_anthology:
            self.acl_anthology = self._initialize_checker(
                'acl_anthology', 'ACLAnthologyReferenceChecker', 'ACL Anthology checker',
                email=contact_email
            )

        # Paperclip is an OPTIONAL secondary tier — biomedical full-text
        # corpus (PMC, bioRxiv, medRxiv) plus arXiv. Auth-gated.
        #
        # Activation: enable_paperclip defaults to "auto" — when None,
        # the tier turns itself on if PAPERCLIP_API_KEY is present in
        # the environment. Callers that explicitly want it off (e.g.
        # offline tests) pass False; callers that always want it on
        # despite a missing key (e.g. testing the dry-run path) pass
        # True. End users only need to set the API key — no constructor
        # flag, no pip install — and the tier activates on the next
        # run.
        if enable_paperclip is None:
            enable_paperclip = bool(paperclip_api_key or os.environ.get('PAPERCLIP_API_KEY'))
        self.paperclip = None
        if enable_paperclip:
            self.paperclip = self._initialize_checker(
                'paperclip', 'PaperclipReferenceChecker', 'Paperclip secondary checker',
                api_key=paperclip_api_key
            )
            if self.paperclip is not None and not getattr(self.paperclip, 'enabled', False):
                # _initialize_checker succeeded but PAPERCLIP_API_KEY was
                # missing or the SDK isn't installed — drop the instance
                # so the fallback list doesn't try a permanently-disabled
                # checker.
                logger.debug("Paperclip instance created but not enabled; dropping")
                self.paperclip = None
        
        # Google Scholar removed - using more reliable APIs only

        # Propagate cache_dir to all sub-checkers for API response caching
        self.cache_dir = cache_dir
        all_local_checkers = [checker for _, _, checker in self.local_db_checkers]
        for checker in (self.arxiv_citation, *all_local_checkers, self.semantic_scholar,
                        self.openalex, self.crossref, self.open_library, self.econbiz,
                        self.dnb, self.tib, self.zdb,
                        self.google_books,
                        self.openreview, self.dblp,
                        self.acl_anthology, self.paperclip):
            if checker is not None:
                checker.cache_dir = cache_dir

        # Track API performance for adaptive selection
        self.api_stats = {
            'arxiv_citation': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'semantic_scholar': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'openalex': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'crossref': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'open_library': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'econbiz': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'dnb': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'tib': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'zdb': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'google_books': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'openreview': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'dblp': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'acl_anthology': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'paperclip': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
        }
        for checker_key, _, _ in self.local_db_checkers:
            self.api_stats.setdefault(
                checker_key,
                {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            )
        
        # Track failed API calls for retry logic - OPTIMIZED CONFIGURATION
        self.retry_base_delay = 1  # Base delay for retrying throttled APIs (seconds)
        self.retry_backoff_factor = 1.5  # Exponential backoff multiplier
        self.max_retry_delay = 20  # Maximum delay cap in seconds
        
        # Per-API concurrency semaphores for bulk mode.
        # Each API independently limits its own concurrent calls, so a 429
        # backoff on one API doesn't block calls to other APIs.
        # local_db has no limit (instant), ArXiv is rate-limited to 1 (3s gap),
        # others allow moderate parallelism.
        self._api_semaphores: Dict[str, threading.Semaphore] = {
            'arxiv_citation': threading.Semaphore(2),   # ArXiv has 3s rate gap
            'semantic_scholar': threading.Semaphore(3),  # moderate parallelism
            'crossref': threading.Semaphore(3),
            'openalex': threading.Semaphore(3),
            'open_library': threading.Semaphore(1),
            'econbiz': threading.Semaphore(1),
            'dnb': threading.Semaphore(1),
            'tib': threading.Semaphore(1),
            'zdb': threading.Semaphore(1),
            'google_books': threading.Semaphore(1),
            'dblp': threading.Semaphore(2),
            'openreview': threading.Semaphore(2),
            'acl_anthology': threading.Semaphore(2),
            # Conservative concurrency cap for Paperclip — pricing /
            # rate limits aren't publicly documented, so hold at 2 to
            # avoid burst-hammering the service in bulk mode.
            'paperclip': threading.Semaphore(2),
        }
        for checker_key, _, _ in self.local_db_checkers:
            self._api_semaphores.setdefault(checker_key, threading.Semaphore(100))

        # Cumulative timing accumulators (wall-clock seconds per API, thread-safe)
        self._api_total_time: Dict[str, float] = {k: 0.0 for k in self.api_stats}
        self._api_sem_wait_time: Dict[str, float] = {k: 0.0 for k in self.api_stats}
        self._api_retry_sleep_time: float = 0.0
        self._api_time_lock = threading.Lock()
    
    def _emit_database_event(self, **event: Any) -> None:
        """Publish a display-safe database transition to an optional caller."""
        # Some lightweight callers and tests intentionally construct this
        # checker with ``__new__`` and inject only the providers they need.
        # Keep these optional orchestration hooks compatible with that usage.
        callback = getattr(self, 'progress_callback', None)
        if callback is None:
            return
        try:
            callback(dict(event))
        except Exception as exc:
            logger.debug("Database progress callback failed: %s", exc)

    def _raise_if_cancelled(self) -> None:
        cancel_event = getattr(self, 'cancel_event', None)
        if cancel_event is not None and cancel_event.is_set():
            raise VerificationCancelled("Reference verification cancelled")

    def _wait_or_cancel(self, delay: float) -> None:
        cancel_event = getattr(self, 'cancel_event', None)
        if cancel_event is not None:
            if cancel_event.wait(max(0.0, delay)):
                raise VerificationCancelled("Reference verification cancelled")
        else:
            time.sleep(delay)

    def _update_api_stats(self, api_name: str, success: bool, duration: float):
        """Update API performance statistics"""
        if api_name in self.api_stats:
            stats = self.api_stats[api_name]
            if success:
                stats['success'] += 1
            else:
                stats['failure'] += 1
            
            # Update average time (simple moving average)
            total_calls = stats['success'] + stats['failure']
            stats['avg_time'] = ((stats['avg_time'] * (total_calls - 1)) + duration) / total_calls

    @staticmethod
    def _append_attempted_api(attempted_apis: List[str], api_name: str) -> None:
        """Track unique checker attempts in first-seen order."""
        if api_name and api_name not in attempted_apis:
            attempted_apis.append(api_name)

    @staticmethod
    def _coerce_text(value: Any) -> str:
        """Normalize mixed payload shapes into plain text."""
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ('title', 'name', 'text', 'value', 'venue', 'journal', 'url', 'doi'):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
            return ''
        return str(value)

    def _format_api_name(self, api_name: str) -> str:
        """Convert internal checker names into user-facing labels."""
        if api_name.startswith('local_'):
            local_key = api_name.replace('local_', '')
            label = DATABASE_LABELS.get(local_key)
            if label:
                return f'local {label} DB'
        return {
            'arxiv_citation': 'ArXiv',
            'semantic_scholar': 'Semantic Scholar',
            'openalex': 'OpenAlex',
            'crossref': 'CrossRef',
            'open_library': 'Open Library',
            'econbiz': 'EconBiz',
            'dnb': 'DNB Catalogue',
            'tib': 'TIB Catalogue',
            'zdb': 'ZDB Catalogue',
            'google_books': 'Google Books',
            'dblp': 'DBLP',
            'openreview': 'OpenReview',
            'acl_anthology': 'ACL Anthology',
        }.get(api_name, api_name.replace('_', ' '))

    def _annotate_match_source(
        self,
        verified_data: Optional[Dict[str, Any]],
        api_name: str,
        api_instance: Any,
    ) -> Optional[Dict[str, Any]]:
        """Attach the matched checker/database to the verified payload."""
        if not isinstance(verified_data, dict):
            return verified_data
        local_label = getattr(api_instance, 'database_label', None)
        if not isinstance(local_label, str) or not local_label.strip():
            local_label = None
        matched_label = local_label or self._format_api_name(api_name)
        verified_data.setdefault('_matched_checker', api_name)
        verified_data.setdefault('_matched_database', matched_label)
        return verified_data

    @staticmethod
    def _database_trace_summary(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a compact, stable candidate summary for INFO traces."""
        if not isinstance(data, dict):
            return {}
        external_ids = data.get('externalIds') or data.get('ids') or {}
        if not isinstance(external_ids, dict):
            external_ids = {}
        return {
            'title': data.get('title') or data.get('display_name'),
            'year': data.get('publication_year') or data.get('year'),
            'doi': data.get('doi') or data.get('DOI') or external_ids.get('DOI') or external_ids.get('doi'),
            'id': (
                data.get('paperId') or data.get('id') or data.get('ppn')
                or data.get('idn') or data.get('zdb_id') or data.get('key')
            ),
        }

    def _configured_database_names(self) -> List[str]:
        """List every configured primary database in execution-order terms."""
        names = [key for key, _, _ in self._iter_local_db_checkers()]
        for name in (
            'semantic_scholar', 'crossref', 'openalex', 'open_library', 'econbiz',
            'dnb', 'tib', 'zdb', 'dblp', 'acl_anthology', 'openreview',
            'paperclip', 'google_books',
        ):
            if getattr(self, name, None) is not None:
                names.append(name)
        return names

    def _iter_local_db_checkers(self) -> List[Tuple[str, str, Any]]:
        """Return configured local DB checkers, honoring legacy test setup."""
        # TODO: remove legacy `self.local_db` fallback after dependent tests are
        # fully migrated to assert against `local_db_checkers`.
        if self.local_db_checkers:
            return self.local_db_checkers
        if self.local_db is not None:
            return [('local_s2', 'Semantic Scholar', self.local_db)]
        return []

    def _local_db_miss_is_authoritative(self, local_checker: Any) -> bool:
        """Whether a local S2 miss may suppress the Semantic Scholar API call.

        Skipping the API on a miss is only sound against a fully ingested
        snapshot. A database that is still being built answers "not found" for
        everything it hasn't reached yet, which would silently turn coverage
        gaps into unverified references.
        """
        checker_reports_coverage = getattr(local_checker, 'has_complete_coverage', None)
        if not callable(checker_reports_coverage):
            return True
        try:
            if checker_reports_coverage():
                return True
        except Exception as e:
            logger.debug("Could not read local DB coverage state: %s", e)
            return True
        logger.debug(
            "Enhanced Hybrid: local S2 database is still being built; "
            "querying the Semantic Scholar API instead of trusting the miss"
        )
        return False

    def _pick_preferred_result(
        self,
        current: Optional[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]],
        candidate: Optional[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]],
        reference: Dict[str, Any],
    ) -> Optional[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]]:
        """Return the better verification result for a single reference.

        Ranking prefers:
        1) complete metadata over incomplete
        2) no DOI mismatch over DOI mismatch
        3) no major author discrepancy over major discrepancy
        4) fewer non-unverified errors
        """
        if candidate is None:
            return current
        if current is None:
            return candidate

        def _score(result):
            data, errors, _url = result
            issues = errors or []
            non_unverified_errors = sum(
                1
                for issue in issues
                if issue.get('error_type') and str(issue.get('error_type')).lower() != 'unverified'
            )
            return (
                0 if self._is_data_complete(data or {}, reference) else 1,
                1 if self._has_doi_mismatch(issues) else 0,
                1 if self._has_major_author_discrepancy(issues) else 0,
                non_unverified_errors,
            )

        return candidate if _score(candidate) < _score(current) else current

    def _format_failure_detail(self, api_name: str, failure_type: str,
                               detail: Optional[str] = None) -> str:
        """Create a short, specific checker failure description."""
        api_label = self._format_api_name(api_name)
        cleaned_detail = ' '.join(str(detail).split()) if detail else ''
        if cleaned_detail:
            if cleaned_detail.lower().startswith(api_label.lower()):
                return cleaned_detail
            return f'{api_label}: {cleaned_detail}'

        fallback_details = {
            'timeout': f'{api_label}: request timed out',
            'throttled': f'{api_label}: rate limited or temporarily unavailable',
            'server_error': f'{api_label}: server error',
            'other': f'{api_label}: unexpected checker error',
        }
        return fallback_details.get(failure_type, f'{api_label}: verification failed')

    @staticmethod
    def _url_failure_message(subreason: str, web_url: str) -> str:
        """Describe why a cited URL did not confirm the reference.

        The distinction matters: a page we were blocked from reading tells us
        nothing about its contents, so reporting it as a mismatch states a
        conclusion that was never actually checked.
        """
        subreason = subreason or ''
        if 'non-existent' in subreason:
            return f'Non-existent web page: {web_url}'
        if 'could not be accessed' in subreason:
            return f'Cited URL could not be accessed to confirm the reference: {web_url}'
        if 'URL references paper' in subreason:
            return f'Paper not verified but URL references paper: {web_url}'
        return f'Cited URL does not reference this paper: {web_url}'

    def _build_unverified_error_details(self, attempted_apis: List[str],
                                        failed_apis: List[Dict[str, Any]]) -> str:
        """Summarize which checkers returned no match versus which failed."""
        failed_api_names = {failed_api['name'] for failed_api in failed_apis}
        negative_attempts = [
            self._format_api_name(api_name)
            for api_name in attempted_apis
            if api_name not in failed_api_names
        ]
        failure_details = [
            failed_api.get('failure_detail') or self._format_failure_detail(
                failed_api['name'],
                failed_api.get('failure_type', 'other'),
            )
            for failed_api in failed_apis
        ]

        if negative_attempts and failure_details:
            return (
                f"Paper not found by any checker; no match in {', '.join(negative_attempts)}; "
                f"checker failures: {'; '.join(failure_details)}"
            )
        if negative_attempts:
            return f"Paper not found by any checker; no match in {', '.join(negative_attempts)}"
        if failure_details:
            return f"All available checkers failed: {'; '.join(failure_details)}"
        return 'Paper not found by any checker'
    
    def _try_api(self, api_name: str, api_instance: Any, reference: Dict[str, Any], is_retry: bool = False) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool, str, str]:
        """
        Try to verify reference with a specific API and track performance.
        
        Uses per-API semaphores so different APIs don't block each other.
        A 429 backoff on Semantic Scholar won't prevent ArXiv or DB lookups.
        
        Returns:
            Tuple of (verified_data, errors, url, success, failure_type, failure_detail)
            failure_type can be: 'none', 'not_found', 'throttled', 'timeout', 'other'
        """
        if not api_instance:
            return None, [], None, False, 'none', ''
        self._raise_if_cancelled()
        
        # Acquire per-API semaphore (limits concurrent calls to this specific API)
        sem = self._api_semaphores.get(api_name)
        sem_wait_start = time.time()
        if sem is not None:
            sem.acquire()
        sem_wait = time.time() - sem_wait_start
        
        start_time = time.time()
        failure_type = 'none'
        logger.info(
            "[DATABASE_TRACE] stage=request database=%s label=%r retry=%s "
            "semaphore_wait_ms=%d title=%r authors=%r year=%r doi=%r",
            api_name,
            getattr(api_instance, 'database_label', None) or self._format_api_name(api_name),
            is_retry,
            round(sem_wait * 1000),
            reference.get('title'),
            reference.get('authors'),
            reference.get('year'),
            reference.get('doi') or reference.get('DOI'),
        )
        self._emit_database_event(
            database=api_name,
            label=getattr(api_instance, 'database_label', None) or self._format_api_name(api_name),
            status='searching',
            attempt=2 if is_retry else 1,
        )
        
        try:
            verified_data, errors, url = api_instance.verify_reference(reference)
            self._raise_if_cancelled()
            duration = time.time() - start_time
            
            # Check if we got API failure errors indicating retryable failure
            api_failure_errors = [err for err in errors if err.get('error_type') == 'api_failure']
            if api_failure_errors:
                # This is a retryable API failure, not a verification result
                self._update_api_stats(api_name, False, duration)
                api_failure_detail = api_failure_errors[0].get('error_details', 'temporary API failure')
                logger.info(
                    "[DATABASE_TRACE] stage=result database=%s status=api_failure "
                    "duration_ms=%d detail=%r",
                    api_name, round(duration * 1000), api_failure_detail,
                )
                logger.debug(f"Enhanced Hybrid: {api_name} API failed in {duration:.2f}s: {api_failure_detail}")
                self._emit_database_event(
                    database=api_name, label=self._format_api_name(api_name),
                    status='rate_limited', attempt=2 if is_retry else 1,
                    duration_ms=round(duration * 1000),
                )
                return None, [], None, False, 'throttled', self._format_failure_detail(
                    api_name,
                    'throttled',
                    api_failure_detail,
                )  # Treat API failures as throttling for retry logic
            
            # Consider it successful if we found data or verification errors (i.e., we could verify something)
            success = verified_data is not None or len(errors) > 0
            self._update_api_stats(api_name, success, duration)

            if success:
                # v0.7.63 (Allen 2021 vs Zhang 2010): wrong-paper rejection.
                # When a checker title-matched to a paper with a HUGE year gap
                # AND zero author-surname overlap, it's almost certainly the
                # WRONG paper (Semantic Scholar's /paper/search/match returns
                # the most-cited paper sharing the title, regardless of year
                # or author). Reject the candidate so the next API in the
                # priority list (or the local DB) gets a chance. Skip this
                # for DOI/ArXiv-anchored matches — those identifiers are
                # authoritative and any year/author mismatch is a real
                # error we want to surface, not a wrong-paper drift.
                if self._is_wrong_paper_match(reference, verified_data, errors, api_name):
                    logger.info(
                        "[DATABASE_TRACE] stage=result database=%s status=rejected_wrong_paper "
                        "duration_ms=%d candidate=%r errors=%r",
                        api_name,
                        round(duration * 1000),
                        self._database_trace_summary(verified_data),
                        errors,
                    )
                    logger.debug(
                        f"Enhanced Hybrid: {api_name} returned wrong-paper match "
                        f"(year+author both off) — rejecting and falling through to next API"
                    )
                    self._emit_database_event(
                        database=api_name, label=self._format_api_name(api_name),
                        status='rejected_wrong_paper', attempt=2 if is_retry else 1,
                        duration_ms=round(duration * 1000),
                        candidate=self._database_trace_summary(verified_data),
                    )
                    return None, [], None, False, 'not_found', ''
                verified_data = self._annotate_match_source(verified_data, api_name, api_instance)
                verification_basis = (
                    verified_data.get('_verification_basis')
                    if isinstance(verified_data, dict)
                    else None
                )
                result_status = (
                    'verified_fulltext_evidence'
                    if verification_basis == 'econbiz_fulltext_evidence'
                    else 'matched'
                )
                logger.info(
                    "[DATABASE_TRACE] stage=result database=%s status=%s duration_ms=%d "
                    "candidate=%r error_count=%d url=%r",
                    api_name,
                    result_status,
                    round(duration * 1000),
                    self._database_trace_summary(verified_data),
                    len(errors or []),
                    url,
                )
                retry_info = " (retry)" if is_retry else ""
                logger.debug(f"Enhanced Hybrid: {api_name} successful in {duration:.2f}s{retry_info}, URL: {url}")
                self._emit_database_event(
                    database=api_name, label=self._format_api_name(api_name),
                    status='matched', attempt=2 if is_retry else 1,
                    duration_ms=round(duration * 1000),
                    candidate=self._database_trace_summary(verified_data),
                )
                return verified_data, errors, url, True, 'none', ''
            else:
                logger.info(
                    "[DATABASE_TRACE] stage=result database=%s status=not_found duration_ms=%d",
                    api_name, round(duration * 1000),
                )
                logger.debug(f"Enhanced Hybrid: {api_name} found no results in {duration:.2f}s")
                self._emit_database_event(
                    database=api_name, label=self._format_api_name(api_name),
                    status='no_match', attempt=2 if is_retry else 1,
                    duration_ms=round(duration * 1000),
                )
                return None, [], None, False, 'not_found', ''
        except VerificationCancelled:
            self._emit_database_event(
                database=api_name, label=self._format_api_name(api_name),
                status='cancelled', attempt=2 if is_retry else 1,
                duration_ms=round((time.time() - start_time) * 1000),
            )
            raise
        except requests.exceptions.Timeout as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            failure_type = 'timeout'
            logger.info(
                "[DATABASE_TRACE] stage=result database=%s status=timeout duration_ms=%d detail=%r",
                api_name, round(duration * 1000), str(e),
            )
            logger.debug(f"Enhanced Hybrid: {api_name} timed out in {duration:.2f}s: {e}")
            self._emit_database_event(
                database=api_name, label=self._format_api_name(api_name),
                status='timed_out', attempt=2 if is_retry else 1,
                duration_ms=round(duration * 1000),
            )
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                str(e) or None,
            )
            
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            
            # Check if it's a rate limiting or server error that should be retried
            error_str = str(e).lower()
            status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
            
            if (status_code == 429) or "429" in str(e) or "rate limit" in error_str:
                failure_type = 'throttled'
                self.api_stats[api_name]['throttled'] += 1
                logger.debug(f"Enhanced Hybrid: {api_name} rate limited in {duration:.2f}s: {e}")
            elif (status_code and status_code >= 500) or "500" in str(e) or "502" in str(e) or "503" in str(e) or "server error" in error_str or "service unavailable" in error_str:
                failure_type = 'server_error'
                logger.debug(f"Enhanced Hybrid: {api_name} server error in {duration:.2f}s: {e}")
            else:
                failure_type = 'other'
                logger.debug(f"Enhanced Hybrid: {api_name} failed in {duration:.2f}s: {e}")

            logger.info(
                "[DATABASE_TRACE] stage=result database=%s status=%s duration_ms=%d "
                "http_status=%r detail=%r",
                api_name, failure_type, round(duration * 1000), status_code, str(e),
            )
            event_status = 'rate_limited' if failure_type == 'throttled' else 'failed'
            self._emit_database_event(
                database=api_name, label=self._format_api_name(api_name),
                status=event_status, attempt=2 if is_retry else 1,
                duration_ms=round(duration * 1000),
            )

            failure_detail = str(e).strip()
            if status_code and str(status_code) not in failure_detail:
                failure_detail = f'HTTP {status_code}: {failure_detail}' if failure_detail else f'HTTP {status_code}'
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                failure_detail or None,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            failure_type = 'other'
            logger.info(
                "[DATABASE_TRACE] stage=result database=%s status=exception duration_ms=%d "
                "exception=%s detail=%r",
                api_name, round(duration * 1000), type(e).__name__, str(e),
            )
            logger.debug(f"Enhanced Hybrid: {api_name} failed in {duration:.2f}s: {e}")
            if api_name == 'semantic_scholar':
                logger.exception("Enhanced Hybrid: Semantic Scholar raised an unexpected error")
            self._emit_database_event(
                database=api_name, label=self._format_api_name(api_name),
                status='failed', attempt=2 if is_retry else 1,
                duration_ms=round(duration * 1000),
            )
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                str(e) or None,
            )
        finally:
            # Accumulate timing stats
            call_duration = time.time() - start_time
            with self._api_time_lock:
                self._api_total_time[api_name] = self._api_total_time.get(api_name, 0) + call_duration
                self._api_sem_wait_time[api_name] = self._api_sem_wait_time.get(api_name, 0) + sem_wait
            # Release per-API semaphore so other refs can use this API
            if sem is not None:
                sem.release()
    
    def _should_try_doi_apis_first(self, reference: Dict[str, Any]) -> bool:
        """
        Determine if we should prioritize DOI-based APIs (CrossRef) for this reference
        """
        url_text = self._coerce_text(reference.get('url')).lower()
        raw_text = self._coerce_text(reference.get('raw_text')).lower()
        # Check if reference has DOI information
        has_doi = (reference.get('doi') or 
                  (url_text and ('doi.org' in url_text or 'doi:' in url_text)) or
                  (raw_text and ('doi' in raw_text)))
        return has_doi

    def _is_google_books_reference(
        self,
        reference: Dict[str, Any],
        best_result: Optional[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]] = None,
    ) -> bool:
        """Return whether a citation is safely eligible for Google Books.

        Avoid querying it for ordinary papers merely because all
        scholarly sources missed them. Open Library identifying the best match
        is itself strong evidence that the citation is a book.
        """
        from .google_books import GoogleBooksReferenceChecker

        print_type = GoogleBooksReferenceChecker.infer_print_type(reference)
        if print_type == 'magazines':
            return bool(getattr(self, 'google_books_include_magazines', False))
        if print_type == 'books':
            return True
        if best_result and isinstance(best_result[0], dict):
            return best_result[0].get('_matched_checker') == 'open_library'
        return False

    @staticmethod
    def _has_doi_mismatch(errors: List[Dict[str, Any]]) -> bool:
        """Return whether a result disputes the explicitly cited DOI."""
        for issue in errors or []:
            issue_type = issue.get('error_type') or issue.get('warning_type') or ''
            details = issue.get('error_details') or issue.get('warning_details') or ''
            if str(issue_type).lower() == 'doi' and 'mismatch' in str(details).lower():
                return True
        return False
    
    def _is_data_complete(self, verified_data: Dict[str, Any], reference: Dict[str, Any]) -> bool:
        """
        Check if the verified data is sufficiently complete for the reference verification
        
        Args:
            verified_data: Paper data returned by API
            reference: Original reference data
            
        Returns:
            True if data is complete enough to use, False if incomplete
        """
        if not verified_data:
            return False
        
        # If the reference has authors, the verified data should also have authors
        cited_authors = reference.get('authors', [])
        found_authors = verified_data.get('authors', [])
        
        # If we cited authors but found none, the data is incomplete
        if cited_authors and not found_authors:
            logger.debug(f"Enhanced Hybrid: Data incomplete - cited authors {cited_authors} but found none")
            return False
        
        return True
    
    def _merge_arxiv_with_semantic_scholar(
        self,
        arxiv_data: Dict[str, Any],
        arxiv_errors: List[Dict[str, Any]],
        arxiv_url: str,
        ss_data: Dict[str, Any],
        ss_errors: List[Dict[str, Any]],
        ss_url: str,
        reference: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Merge ArXiv verification results with Semantic Scholar data.
        
        ArXiv is authoritative for title/author/year, but Semantic Scholar
        provides venue information and additional URLs (DOI, S2 page).
        
        Args:
            arxiv_data: Verified data from ArXiv
            arxiv_errors: Errors/warnings from ArXiv verification
            arxiv_url: ArXiv URL
            ss_data: Data from Semantic Scholar
            ss_errors: Errors from Semantic Scholar (used for venue checking)
            ss_url: Semantic Scholar URL
            reference: Original reference
            
        Returns:
            Tuple of (merged_data, merged_errors)
        """
        merged_data = dict(arxiv_data) if arxiv_data else {}
        merged_errors = list(arxiv_errors) if arxiv_errors else []
        
        if not ss_data:
            return merged_data, merged_errors
        
        # Add Semantic Scholar URL to external IDs
        if 'externalIds' not in merged_data:
            merged_data['externalIds'] = {}
        
        ss_external_ids = ss_data.get('externalIds', {})
        
        # Add S2 paper ID
        if ss_data.get('paperId'):
            merged_data['externalIds']['S2PaperId'] = ss_data['paperId']
        
        # Add DOI if available from Semantic Scholar
        if ss_external_ids.get('DOI') and not merged_data['externalIds'].get('DOI'):
            merged_data['externalIds']['DOI'] = ss_external_ids['DOI']
        
        # Store Semantic Scholar URL
        merged_data['_semantic_scholar_url'] = ss_url
        
        # Check for venue mismatch - if paper was published at a venue but citation only says arXiv
        ss_venue = self._coerce_text(ss_data.get('venue', ''))
        cited_venue = self._coerce_text(
            reference.get('venue', reference.get('journal', ''))
        ).strip().lower()
        
        # Normalize ArXiv venue names
        is_cited_as_arxiv = (
            not cited_venue or 
            cited_venue in ['arxiv', 'arxiv preprint', 'arxiv.org', 'preprint']
        )
        
        # Check if Semantic Scholar shows a real publication venue
        if ss_venue and is_cited_as_arxiv:
            # Ignore generic/empty venues
            ss_venue_lower = ss_venue.lower().strip()
            is_real_venue = (
                ss_venue_lower and 
                ss_venue_lower not in ['arxiv', 'arxiv.org', 'preprint', ''] and
                not ss_venue_lower.startswith('arxiv')
            )
            
            if is_real_venue:
                # This paper was published at a venue but is only cited as arXiv
                logger.debug(f"Enhanced Hybrid: Paper published at '{ss_venue}' but cited as arXiv")
                merged_errors.append({
                    'warning_type': 'venue',
                    'warning_details': f"Paper was published at venue but cited as arXiv preprint:\n       cited:  arXiv\n       actual: {ss_venue}",
                    'ref_venue_correct': ss_venue
                })
                # Also add the venue to merged data
                merged_data['venue'] = ss_venue
        
        return merged_data, merged_errors

    def _is_wrong_paper_match(self, reference, verified_data, errors, api_name):
        """Detect when a checker matched the WRONG paper.

        v0.7.63 fired on year-gap-≥5 + zero-author-overlap (Allen 2021 vs
        Zhang 2010). v0.7.67 broadens this with three additional signals
        for cases where the year is close enough to slip through:

          - SHORT cited title (≤3 tokens, e.g. "Osteoporosis", "Discoid
            meniscus") is a generic word/phrase that re-occurs across
            many papers. Treat zero-surname-overlap as wrong-paper even
            when the year gap is small.
          - Year-gap-≥2 + venue-mismatch + zero-overlap is also wrong-
            paper signature (Niu/Warindra discoid meniscus case: 2022
            Clin Sports Med vs 2024 Orthopaedic Proceedings).
          - Same-authors but the cited title is a SHORT generic phrase
            AND the actual title is far longer (length ratio ≥3) AND
            venue doesn't match → wrong paper. Catches the Ensrud 2017
            "Osteoporosis" review vs same-authors 2025 JAMA Netw Open
            "Identifying Younger Postmenopausal Women..." case.

        Always skipped when the match is DOI/ArXiv/PMID-anchored — those
        identifiers are authoritative and any drift is a real citation
        error worth surfacing.
        """
        if not verified_data:
            return False

        # DOI/ArXiv/PMID-anchored matches are authoritative; never reject.
        try:
            cited_doi = self._coerce_text(reference.get('doi')).strip()
            if cited_doi:
                for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
                    if cited_doi.lower().startswith(prefix):
                        cited_doi = cited_doi[len(prefix):]
                        break
                vd_doi = self._coerce_text(verified_data.get('doi')).strip()
                vd_ext = verified_data.get('externalIds') or {}
                vd_doi = vd_doi or vd_ext.get('DOI') or vd_ext.get('doi') or ''
                if vd_doi and cited_doi.lower() == str(vd_doi).strip().lower():
                    return False
            # ArXiv ID anchored?
            ref_url = (
                f"{self._coerce_text(reference.get('url'))} "
                f"{self._coerce_text(reference.get('venue'))}"
            )
            if 'arxiv.org' in ref_url.lower() or (reference.get('externalIds', {}) or {}).get('ArXiv'):
                return False
            # PMID anchored?
            cited_pmid = (
                reference.get('pmid')
                or (reference.get('externalIds') or {}).get('PubMed')
                or (reference.get('externalIds') or {}).get('PMID')
                or ''
            )
            cited_pmid = str(cited_pmid or '').strip()
            if cited_pmid:
                vd_ext = verified_data.get('externalIds') or {}
                vd_pmid = (
                    str(verified_data.get('pmid') or '').strip()
                    or str(vd_ext.get('PubMed') or '').strip()
                    or str(vd_ext.get('PMID') or '').strip()
                )
                if vd_pmid and cited_pmid == vd_pmid:
                    return False
        except Exception:
            pass

        # ── Year-gap calculation ──
        try:
            cited_year = int(reference.get('year')) if reference.get('year') else None
        except (TypeError, ValueError):
            cited_year = None
        actual_year = verified_data.get('year')
        try:
            actual_year = int(actual_year) if actual_year else None
        except (TypeError, ValueError):
            actual_year = None

        year_gap = None
        if cited_year and actual_year:
            year_gap = abs(cited_year - actual_year)
        else:
            for err in errors or []:
                etype = err.get('error_type') or err.get('warning_type') or ''
                if etype != 'year':
                    continue
                try:
                    correct_year = int(err.get('ref_year_correct') or 0)
                    cy = cited_year or int((err.get('cited_value') or '0') or 0)
                    if correct_year and cy:
                        year_gap = abs(correct_year - cy)
                        break
                except (TypeError, ValueError):
                    continue

        # ── Surname-overlap calculation ──
        try:
            from refchecker.utils.text_utils import normalize_diacritics_simple
        except Exception:
            normalize_diacritics_simple = lambda s: s  # noqa: E731

        def _surnames(names):
            out = set()
            for n in (names or []):
                if isinstance(n, dict):
                    n = n.get('name') or n.get('full_name') or ''
                if not n:
                    continue
                s = normalize_diacritics_simple(str(n).strip().lower())
                toks = [t for t in s.replace(',', ' ').split() if t]
                if not toks:
                    continue
                while toks and len(toks[-1].rstrip('.')) <= 3 and toks[-1].rstrip('.').isalpha():
                    if len(toks) == 1:
                        break
                    toks.pop()
                if toks:
                    for t in toks[-2:]:
                        if len(t) >= 3:
                            out.add(t)
            return out

        cited_surnames = _surnames(reference.get('authors'))
        actual_surnames = _surnames(verified_data.get('authors') or [])
        if not cited_surnames or not actual_surnames:
            # Can't determine overlap; for the title+venue branch we may
            # still proceed below, but it requires title/venue mismatch.
            surname_overlap = None
        else:
            surname_overlap = len(cited_surnames & actual_surnames)

        # ── Title/venue helpers ──
        def _str(x):
            return self._coerce_text(x).strip()

        cited_title = _str(reference.get('title'))
        actual_title = _str(verified_data.get('title'))
        cited_title_tokens = len(cited_title.split())
        actual_title_tokens = len(actual_title.split())
        short_cited = 0 < cited_title_tokens <= 3
        if cited_title_tokens > 0 and actual_title_tokens > 0:
            length_ratio = max(cited_title_tokens, actual_title_tokens) / max(
                1, min(cited_title_tokens, actual_title_tokens)
            )
        else:
            length_ratio = 1.0
        title_length_mismatch = length_ratio >= 3.0

        venue_match = self._venues_compatible(
            reference.get('venue') or reference.get('journal') or '',
            verified_data.get('venue') or verified_data.get('journal') or '',
        )

        # ── Rules ──
        # Zero-author-overlap branch
        if surname_overlap == 0:
            if year_gap is not None and year_gap >= 5:
                logger.debug(
                    f"Enhanced Hybrid: wrong-paper on {api_name} — year_gap={year_gap}, "
                    f"zero author overlap"
                )
                return True
            if short_cited:
                logger.debug(
                    f"Enhanced Hybrid: wrong-paper on {api_name} — short cited title "
                    f"'{cited_title}' with zero author overlap"
                )
                return True
            if year_gap is not None and year_gap >= 2 and not venue_match:
                logger.debug(
                    f"Enhanced Hybrid: wrong-paper on {api_name} — year_gap={year_gap}, "
                    f"venue mismatch, zero author overlap"
                )
                return True

        # Same-authors-but-generic-title branch (Ensrud "Osteoporosis"):
        # short cited title + wide title-length mismatch + venue mismatch
        # → wrong paper regardless of author overlap.
        if short_cited and title_length_mismatch and not venue_match:
            logger.debug(
                f"Enhanced Hybrid: wrong-paper on {api_name} — short generic cited title "
                f"'{cited_title}' ({cited_title_tokens} tok) vs much longer actual "
                f"({actual_title_tokens} tok), venue mismatch"
            )
            return True

        return False

    def _venues_compatible(self, cited_venue, actual_venue):
        """Cheap venue-equivalence check used by `_is_wrong_paper_match`.

        Tries (in order):
          1. Exact match after lowercase + punctuation strip
          2. Substring containment either direction
          3. `is_acceptable_abbreviation` from `venue_abbreviations`
             (handles NLM abbreviation ↔ full title pairs)

        Returns True when either string is empty (don't penalise missing
        venue data) and True on any positive signal. Conservative — when
        in doubt, return True (don't trigger wrong-paper rejection on a
        venue we simply can't classify).
        """
        cv = _venue_text(cited_venue)
        av = _venue_text(actual_venue)
        if not cv or not av:
            return True  # missing data — don't reject on venue signal

        def _norm(s):
            import re as _re
            s = s.lower()
            s = _re.sub(r'[\.,;:\(\)\[\]\"\'`]', ' ', s)
            s = _re.sub(r'\s+', ' ', s).strip()
            return s

        cv_n = _norm(cv)
        av_n = _norm(av)
        if not cv_n or not av_n:
            return True
        if cv_n == av_n:
            return True
        if cv_n in av_n or av_n in cv_n:
            return True

        try:
            from refchecker.utils.venue_abbreviations import is_acceptable_abbreviation
            if is_acceptable_abbreviation(cv, av) or is_acceptable_abbreviation(av, cv):
                return True
        except Exception:
            pass
        return False

    def _has_major_author_discrepancy(self, errors):
        """Check if errors indicate a major author discrepancy.
        
        A major discrepancy means the DB entry's authors are completely
        different from the cited authors — suggesting a corrupt or wrong
        database entry (e.g., S2 duplicate with fabricated authors).
        
        Returns True only when there's zero overlap between cited and
        actual author last names, indicating the DB matched the wrong paper.
        """
        for error in errors:
            if error.get('error_type') != 'author':
                continue
            details = error.get('error_details', '')
            actual_str = error.get('ref_authors_correct', '')
            if not actual_str or not details:
                continue
            # Only flag if it says no authors matched at all.
            details_lower = details.lower()
            if 'no matching authors' in details_lower:
                logger.debug(
                    "Enhanced Hybrid: Major author discrepancy — no cited authors overlap with actual '%s'",
                    actual_str,
                )
                return True
            if 'not found in author list' not in details:
                continue
            # Extract cited author name from the error details
            # Format: "Author 1 mismatch\n       cited:  Name (not found...)\n       actual: ..."
            import re
            cited_match = re.search(r'cited:\s+(.+?)(?:\s+\(not found)', details)
            if not cited_match:
                continue
            cited_name = cited_match.group(1).strip().lower()
            actual_names = actual_str.lower()
            # Extract last names from cited author
            cited_parts = cited_name.split()
            # Check if ANY part of the cited name appears in actual authors
            has_overlap = False
            for part in cited_parts:
                if len(part) > 2 and part in actual_names:
                    has_overlap = True
                    break
            if not has_overlap:
                logger.debug(f"Enhanced Hybrid: Major author discrepancy — cited '{cited_name}' has no overlap with actual '{actual_str}'")
                return True
        return False

    def _verify_arxiv_parallel(self, reference, failed_apis, attempted_apis):
        """Run ArXiv citation + Semantic Scholar API in parallel for ArXiv refs.
        
        Called after local DB was tried and either failed or had discrepancies.
        ArXiv BibTeX is the authoritative source for authors/title.
        S2 API provides venue metadata for merging.
        
        Returns result tuple or None if both failed.
        """
        logger.debug("Enhanced Hybrid: ArXiv reference — running ArXiv citation + Semantic Scholar in parallel")
        
        futures = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="HybridAPI") as pool:
            if self.arxiv_citation:
                self._append_attempted_api(attempted_apis, 'arxiv_citation')
                futures['arxiv_citation'] = pool.submit(
                    self._try_api, 'arxiv_citation', self.arxiv_citation, reference)
            if self.semantic_scholar:
                self._append_attempted_api(attempted_apis, 'semantic_scholar')
                futures['semantic_scholar'] = pool.submit(
                    self._try_api, 'semantic_scholar', self.semantic_scholar, reference)
        
        arxiv_result = None
        ss_result = None
        
        for name, future in futures.items():
            verified_data, errors, url, success, failure_type, failure_detail = future.result()
            if name == 'arxiv_citation':
                if success:
                    arxiv_result = (verified_data, errors, url)
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'arxiv_citation',
                        'instance': self.arxiv_citation,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
            elif name == 'semantic_scholar':
                if success:
                    ss_result = (verified_data, errors, url)
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'semantic_scholar',
                        'instance': self.semantic_scholar,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
        
        # Merge results
        if arxiv_result and ss_result:
            ss_data, ss_errors, ss_url = ss_result
            if ss_data:
                ss_venue = self.semantic_scholar.get_venue_from_paper_data(ss_data)
                if ss_venue and 'arxiv' in ss_venue.lower():
                    logger.debug("Enhanced Hybrid: Semantic Scholar only found ArXiv venue, skipping merge")
                    return arxiv_result
            arxiv_data, arxiv_errors, arxiv_url = arxiv_result
            merged_data, merged_errors = self._merge_arxiv_with_semantic_scholar(
                arxiv_data, arxiv_errors, arxiv_url,
                ss_data, ss_errors, ss_url,
                reference)
            return merged_data, merged_errors, arxiv_url
        
        if arxiv_result:
            return arxiv_result
        if ss_result:
            return ss_result
        return None

    def _handle_arxiv_result(self, result, reference):
        """Return an ArXiv verification result, short-circuiting wrong IDs.

        The ArXiv citation checker is authoritative for an explicit cited
        ArXiv ID.  A title error with very low similarity means that ID points
        at a different paper, so do not let a later title search against a
        database mask the bad cited URL.
        """
        verified_data, errors, url = result

        has_title_error = any(
            e.get('error_type') == 'title' for e in (errors or [])
        )
        if has_title_error:
            cited_title = reference.get('title', 'unknown')
            actual_title = (verified_data or {}).get('title', 'unknown')
            # Compute similarity to distinguish "completely different paper"
            # from "same paper, revised title between versions". Truly
            # different papers score 0.0-0.1; revised titles score higher.
            from refchecker.utils.text_utils import compare_titles_with_latex_cleaning
            title_sim = compare_titles_with_latex_cleaning(cited_title, actual_title)
            if title_sim < 0.25:
                arxiv_url = reference.get('cited_url') or reference.get('url', '') or url
                logger.debug(
                    f"Enhanced Hybrid: ArXiv URL points to a different paper "
                    f"(cited: '{cited_title}', actual: '{actual_title}', "
                    f"sim={title_sim:.2f}) — returning as unverified"
                )
                return None, [
                    {
                        'error_type': 'unverified',
                        'error_details': f'Could not verify: {cited_title}',
                    },
                    {
                        'error_type': 'url',
                        'error_details': f'Cited URL does not reference this paper: {arxiv_url}',
                    },
                ], arxiv_url

            logger.debug(
                f"Enhanced Hybrid: ArXiv title mismatch but titles "
                f"are similar (sim={title_sim:.2f}), treating as "
                f"version update: '{cited_title}' vs '{actual_title}'"
            )

        return result

    def _verify_non_arxiv_parallel(
        self,
        reference,
        failed_apis,
        attempted_apis,
        skip_ss: bool = False,
        force_all_databases: bool = False,
    ):
        """Query the general-purpose remote metadata sources in parallel.
        
        Returns (result, incomplete_results) where result is a complete
        (verified_data, errors, url) tuple or None, and incomplete_results
        is a dict of {'crossref': ..., 'openalex': ...} for Phase 3 fallback.
        incomplete_results are kept as local variables to avoid thread-safety
        issues when multiple threads share the same checker instance.
        """
        last_crossref_result = None
        last_openalex_result = None
        last_doi_mismatch_result = None
        best_result = None
        doi_first = self._should_try_doi_apis_first(reference)

        # A cited DOI is more authoritative than a title match.  Ask CrossRef
        # for that DOI before Semantic Scholar can select the same work's
        # arXiv record and report the publisher DOI as a mismatch.
        if doi_first and self.crossref:
            self._append_attempted_api(attempted_apis, 'crossref')
            verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                'crossref', self.crossref, reference,
            )
            if success:
                result = (verified_data, errors, url)
                best_result = self._pick_preferred_result(best_result, result, reference)
                if (
                    not force_all_databases
                    and self._is_data_complete(verified_data, reference)
                    and not self._has_doi_mismatch(errors)
                ):
                    return result, {}
                last_crossref_result = result
                if self._has_doi_mismatch(errors):
                    last_doi_mismatch_result = result
            elif failure_type not in ('none', 'not_found'):
                failed_apis.append({
                    'name': 'crossref',
                    'instance': self.crossref,
                    'failure_type': failure_type,
                    'failure_detail': failure_detail,
                    'active': True,
                })
        
        if self.semantic_scholar and skip_ss:
            logger.info(
                "Skipping Semantic Scholar lookup due to local-S2 authoritative miss for title=%r doi=%r",
                reference.get('title', ''),
                reference.get('doi', ''),
            )

        # Launch the general remote catalogues together so DNB/TIB/ZDB cannot be
        # hidden behind an early successful result from another source.
        fallback_apis = []
        if self.semantic_scholar and not skip_ss:
            fallback_apis.append(('semantic_scholar', self.semantic_scholar))
        if self.crossref and not doi_first:
            fallback_apis.append(('crossref', self.crossref))
        if self.openalex:
            fallback_apis.append(('openalex', self.openalex))
        open_library = getattr(self, 'open_library', None)
        if open_library:
            fallback_apis.append(('open_library', open_library))
        econbiz = getattr(self, 'econbiz', None)
        if econbiz:
            fallback_apis.append(('econbiz', econbiz))
        dnb = getattr(self, 'dnb', None)
        if dnb:
            fallback_apis.append(('dnb', dnb))
        tib = getattr(self, 'tib', None)
        if tib:
            fallback_apis.append(('tib', tib))
        zdb = getattr(self, 'zdb', None)
        if zdb:
            fallback_apis.append(('zdb', zdb))
        if self.dblp:
            fallback_apis.append(('dblp', self.dblp))
        acl_anthology = getattr(self, 'acl_anthology', None)
        if acl_anthology:
            fallback_apis.append(('acl_anthology', acl_anthology))
        # Paperclip runs at the END of the priority list — it's a
        # secondary/biomedical-fallback signal, not a primary metadata
        # source. Only opted-in users (PAPERCLIP_API_KEY set + SDK
        # installed) ever hit this.
        paperclip = getattr(self, 'paperclip', None)
        if paperclip:
            fallback_apis.append(('paperclip', paperclip))

        logger.info(
            "[DATABASE_TRACE] stage=parallel_plan title=%r force_all=%s doi_first=%s "
            "skip_semantic_scholar=%s launched=%s",
            reference.get('title'),
            force_all_databases,
            bool(doi_first),
            skip_ss,
            [name for name, _ in fallback_apis],
        )

        if fallback_apis:
            logger.debug(
                "Enhanced Hybrid: launching %d remote metadata APIs in parallel",
                len(fallback_apis),
            )
            futures = {}
            with ThreadPoolExecutor(max_workers=len(fallback_apis), thread_name_prefix="HybridAPI") as pool:
                for api_name, api_instance in fallback_apis:
                    self._append_attempted_api(attempted_apis, api_name)
                    futures[api_name] = pool.submit(
                        self._try_api, api_name, api_instance, reference)

            priority = [
                'semantic_scholar', 'crossref', 'openalex', 'dnb', 'tib', 'zdb',
                'open_library', 'econbiz',
                'dblp', 'acl_anthology', 'paperclip',
            ]
            for api_name in priority:
                if api_name not in futures:
                    continue
                verified_data, errors, url, success, failure_type, failure_detail = futures[api_name].result()
                if not success and failure_type not in ('none', 'not_found'):
                    api_inst = dict(fallback_apis)[api_name]
                    failed_apis.append({
                        'name': api_name,
                        'instance': api_inst,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
                if success:
                    result = (verified_data, errors, url)
                    best_result = self._pick_preferred_result(best_result, result, reference)
                    if (not force_all_databases) and self._is_data_complete(verified_data, reference):
                        return (verified_data, errors, url), {}
                    if api_name == 'crossref':
                        last_crossref_result = result
                    elif api_name == 'openalex':
                        last_openalex_result = result
                    if doi_first and self._has_doi_mismatch(errors):
                        last_doi_mismatch_result = last_doi_mismatch_result or result

        arxiv_title_result = self._try_arxiv_title_search(reference, attempted_apis)
        if arxiv_title_result is not None:
            best_result = self._pick_preferred_result(best_result, arxiv_title_result, reference)
            if not force_all_databases:
                return arxiv_title_result, {}
        
        # Try OpenReview as a secondary step (not parallelized — rare path)
        if self.openreview:
            if hasattr(self.openreview, 'is_openreview_reference') and self.openreview.is_openreview_reference(reference):
                self._append_attempted_api(attempted_apis, 'openreview')
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api('openreview', self.openreview, reference)
                if success:
                    result = (verified_data, errors, url)
                    best_result = self._pick_preferred_result(best_result, result, reference)
                    if not force_all_databases:
                        return result, {}
                if failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'openreview',
                        'instance': self.openreview,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
            elif hasattr(self.openreview, 'verify_reference_by_search'):
                venue = self._coerce_text(
                    reference.get('venue', reference.get('journal', ''))
                ).lower()
                openreview_venues = ['iclr', 'icml', 'neurips', 'nips', 'aaai', 'ijcai',
                    'international conference on learning representations',
                    'international conference on machine learning',
                    'neural information processing systems']
                if any(v in venue for v in openreview_venues):
                    self._append_attempted_api(attempted_apis, 'openreview')
                    verified_data, errors, url, success, failure_type, failure_detail = self._try_openreview_search(reference)
                    if success:
                        result = (verified_data, errors, url)
                        best_result = self._pick_preferred_result(best_result, result, reference)
                        if not force_all_databases:
                            return result, {}
                    if failure_type not in ('none', 'not_found'):
                        failed_apis.append({
                            'name': 'openreview',
                            'instance': self.openreview,
                            'failure_type': failure_type,
                            'failure_detail': failure_detail,
                            'active': True,
                        })

        # Google Books is intentionally sequential and last. It is never
        # launched with the normal fallback pool, so a complete result from
        # Open Library or any scholarly source consumes no Google quota.
        google_books_eligible = force_all_databases or self._is_google_books_reference(
            reference, best_result
        )
        google_books = getattr(self, 'google_books', None)
        if not google_books and google_books_eligible:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=skipped reason=not_configured title=%r",
                reference.get('title', ''),
            )
        elif google_books and not google_books_eligible:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=skipped reason=not_eligible title=%r",
                reference.get('title', ''),
            )
        elif google_books:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=fallback_reached forced=%s title=%r",
                force_all_databases,
                reference.get('title', ''),
            )
            self._append_attempted_api(attempted_apis, 'google_books')
            google_books_reference = reference
            if force_all_databases:
                google_books_reference = {
                    **reference,
                    '_google_books_force_all': True,
                }
            verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                'google_books', google_books, google_books_reference,
            )
            if success:
                logger.info(
                    "GOOGLE_BOOKS_API_TRACE event=fallback_result outcome=match title=%r",
                    reference.get('title', ''),
                )
                result = (verified_data, errors, url)
                best_result = self._pick_preferred_result(best_result, result, reference)
                if not force_all_databases and self._is_data_complete(verified_data, reference):
                    return result, {}
            elif failure_type not in ('none', 'not_found'):
                logger.info(
                    "GOOGLE_BOOKS_API_TRACE event=fallback_result outcome=%s title=%r",
                    failure_type,
                    reference.get('title', ''),
                )
                failed_apis.append({
                    'name': 'google_books',
                    'instance': google_books,
                    # Retain the force-all override for retries.  Retrying the
                    # original reference can make Google Books classify it as
                    # unsupported media and skip the request, which incorrectly
                    # turns an API failure into a reported "no match".
                    'reference': google_books_reference,
                    'failure_type': failure_type,
                    'failure_detail': failure_detail,
                    'active': True,
                })
            else:
                logger.info(
                    "GOOGLE_BOOKS_API_TRACE event=fallback_result outcome=no_match title=%r",
                    reference.get('title', ''),
                )
        
        # Return None with any incomplete results for Phase 3 fallback
        incomplete = {}
        if last_crossref_result:
            incomplete['crossref'] = last_crossref_result
        if last_openalex_result:
            incomplete['openalex'] = last_openalex_result
        if last_doi_mismatch_result:
            incomplete['doi_mismatch'] = last_doi_mismatch_result
        if best_result is not None:
            # Preserve the strongest successful-but-incomplete response (for
            # example Semantic Scholar metadata without an author list) so the
            # final fallback can still verify the reference after every source
            # has had a chance to provide a more complete record.
            incomplete['best'] = best_result
        if force_all_databases and best_result is not None:
            return best_result, {}
        return None, incomplete

    def _try_arxiv_title_search(self, reference, attempted_apis):
        """Try ArXiv title search for non-ArXiv citations before loose venue fallbacks."""
        if not self.arxiv_citation or not hasattr(self.arxiv_citation, 'find_arxiv_id_by_title'):
            return None

        title = self._coerce_text(reference.get('title', '')).strip()
        if not title:
            return None

        try:
            arxiv_id, _ = self.arxiv_citation.extract_arxiv_id(reference)
        except Exception:
            arxiv_id = None
        if arxiv_id:
            return None

        try:
            arxiv_id = self.arxiv_citation.find_arxiv_id_by_title(
                title,
                authors=reference.get('authors', []),
                year=reference.get('year'),
            )
        except Exception as exc:
            logger.debug("Enhanced Hybrid: ArXiv title search failed: %s", exc)
            return None

        if not arxiv_id:
            return None

        arxiv_reference = dict(reference)
        arxiv_reference['url'] = f'https://arxiv.org/abs/{arxiv_id}'
        self._append_attempted_api(attempted_apis, 'arxiv_citation')
        verified_data, errors, url, success, _failure_type, _failure_detail = self._try_api(
            'arxiv_citation',
            self.arxiv_citation,
            arxiv_reference,
        )
        if success and verified_data is not None:
            logger.debug("Enhanced Hybrid: ArXiv title search verification succeeded for %s", arxiv_id)
            return verified_data, errors, url
        return None

    # ------------------------------------------------------------------
    # Post-verification checks (shared by CLI, WebUI, and bulk paths)
    # ------------------------------------------------------------------

    def _extract_verified_arxiv_id(
        self,
        reference: Dict[str, Any],
        verified_data: Optional[Dict[str, Any]],
        url: Optional[str],
    ) -> Optional[str]:
        """Return the best ArXiv ID available from reference or verified data."""
        from refchecker.utils.url_utils import extract_arxiv_id_from_url

        for candidate in (
            reference.get('url'),
            reference.get('cited_url'),
            reference.get('venue'),
            url,
        ):
            arxiv_id = extract_arxiv_id_from_url(candidate or '')
            if arxiv_id:
                return arxiv_id

        if verified_data:
            ext = verified_data.get('externalIds') or {}
            arxiv_id = ext.get('ArXiv') or ext.get('arxiv')
            if arxiv_id:
                return str(arxiv_id)

        return None

    def _apply_arxiv_version_warnings(
        self,
        verified_data: Optional[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        url: Optional[str],
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Convert version-only ArXiv metadata mismatches to warnings.

        This normalizes the result at the shared checker layer so CLI, bulk,
        and WebUI all see the same warning-only record before any presentation
        or hallucination code runs.
        """
        if not self.arxiv_citation or not errors:
            return verified_data, errors, url
        if any(e.get('warning_type') and 'update' in e.get('warning_type', '').lower() for e in errors):
            return verified_data, errors, url

        arxiv_id = self._extract_verified_arxiv_id(reference, verified_data, url)
        if not arxiv_id:
            return verified_data, errors, url

        try:
            arxiv_ref = dict(reference)
            arxiv_ref['url'] = f'https://arxiv.org/abs/{arxiv_id}'
            arxiv_data, arxiv_errors, arxiv_url = self.arxiv_citation.verify_reference(arxiv_ref)
        except Exception as exc:
            logger.debug("Enhanced Hybrid: shared ArXiv version check failed: %s", exc)
            return verified_data, errors, url

        if not arxiv_data or not arxiv_errors:
            return verified_data, errors, url

        has_version_warning = any(
            e.get('warning_type') and 'update' in e.get('warning_type', '').lower()
            for e in arxiv_errors
        )
        has_real_error = any(e.get('error_type') for e in arxiv_errors)
        if not has_version_warning or has_real_error:
            return verified_data, errors, url

        annotated_data = self._annotate_match_source(
            arxiv_data,
            'arxiv_citation',
            self.arxiv_citation,
        )
        logger.debug(
            "Enhanced Hybrid: ArXiv version update converted errors to warnings for %s",
            arxiv_id,
        )
        return annotated_data, arxiv_errors, arxiv_url or url

    def _check_arxiv_id_mismatch(self, reference: Dict[str, Any],
                                  verified_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Check if the cited ArXiv ID actually points to the cited paper.

        Returns a list of errors (arxiv_id or title type) if there's a
        mismatch, or an empty list if the ID is correct or absent.
        """
        from refchecker.utils.url_utils import extract_arxiv_id_from_url
        from refchecker.utils.text_utils import calculate_title_similarity, compare_authors

        ref_arxiv_id = None
        if reference.get('url') and 'arxiv.org/abs/' in reference['url']:
            ref_arxiv_id = extract_arxiv_id_from_url(reference['url'])
        if not ref_arxiv_id and reference.get('venue'):
            ref_arxiv_id = extract_arxiv_id_from_url(reference['venue'])
        if not ref_arxiv_id:
            return []

        # Look up what the ArXiv ID actually points to
        actual_paper = None
        if self.arxiv_citation:
            try:
                actual_data, _, _ = self.arxiv_citation.verify_reference(
                    {'url': f'https://arxiv.org/abs/{ref_arxiv_id}',
                     'title': '', 'authors': [], 'raw_text': ''}
                )
                if actual_data:
                    actual_paper = actual_data
            except Exception:
                pass

        # Check verified_data for ArXiv ID mismatch
        if verified_data:
            ext = verified_data.get('externalIds', {})
            correct_id = ext.get('ArXiv') or ext.get('arxiv')
            if correct_id and ref_arxiv_id != correct_id:
                return [{'error_type': 'arxiv_id',
                         'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} should be {correct_id}"}]

        if not actual_paper:
            return []

        expected_title = self._coerce_text(reference.get('title', '')).strip()
        if not expected_title:
            return []

        actual_title = actual_paper.get('title', '')
        title_sim = calculate_title_similarity(expected_title.lower(), actual_title.lower())

        if title_sim < 0.4:
            # Titles very different — check authors to distinguish wrong ID vs inaccurate title
            expected_authors = reference.get('authors', [])
            actual_authors_raw = actual_paper.get('authors', [])
            actual_author_names = [
                a.get('name', str(a)) if isinstance(a, dict) else str(a)
                for a in actual_authors_raw
            ]
            authors_match = False
            if expected_authors and actual_author_names:
                try:
                    authors_match, _ = compare_authors(expected_authors, actual_author_names)
                except Exception:
                    pass
            if authors_match:
                return [{'error_type': 'title',
                         'error_details': f"Inaccurate title: cited as '{expected_title}' but ArXiv paper is titled '{actual_title}'"}]
            else:
                return [{'error_type': 'arxiv_id',
                         'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} points to '{actual_title}'"}]
        return []

    def _try_arxiv_re_verify(self, errors: List[Dict[str, Any]],
                              verified_data: Optional[Dict[str, Any]],
                              reference: Dict[str, Any]) -> Optional[Tuple]:
        """Re-verify against ArXiv when the DB likely matched the wrong paper.

        Triggers when there's an author error with ≤10% overlap (catastrophic
        mismatch). Returns (errors, url, verified_data) on success, or None.
        """
        author_err = next(
            (e for e in errors if (e.get('error_type') or '').lower() == 'author'),
            None,
        )
        if author_err is None:
            return None

        cited_authors = author_err.get('ref_authors_cited', '')
        correct_authors = author_err.get('ref_authors_correct', '')
        if not cited_authors:
            ref_authors = reference.get('authors', [])
            cited_authors = ', '.join(
                a.get('name', a) if isinstance(a, dict) else str(a)
                for a in ref_authors
            ) if isinstance(ref_authors, list) else str(ref_authors)
        if not cited_authors or not correct_authors:
            return None

        from refchecker.core.hallucination_policy import _compute_author_overlap
        overlap = _compute_author_overlap(cited_authors, correct_authors)

        # Trigger re-verification when:
        # 1. Catastrophic mismatch (≤10% overlap — wrong paper matched), OR
        # 2. Cited has slightly MORE authors than the DB entry (1-2 extra)
        #    AND high overlap — S2/DB may have incomplete author data while
        #    ArXiv has the complete list.  Don't trigger for large differences
        #    (≥3 extra) as those indicate fabricated author lists.
        # 3. DB/S2 has MORE authors than cited AND high overlap — likely an
        #    ArXiv version update where authors were added in a newer version.
        #    The ArXiv version checker can match the cited authors to a
        #    historical version and convert the error to a warning.
        # 4. High overlap but first author differs — likely an author
        #    reordering between ArXiv versions (e.g. preprint vs published).
        cited_count = len([a for a in cited_authors.split(',') if a.strip()])
        correct_count = len([a for a in correct_authors.split(',') if a.strip()])
        cited_more = 0 < (cited_count - correct_count) <= 2
        correct_more = 0 < (correct_count - cited_count)

        # Check for first-author order change with high overall overlap
        first_author_differs = False
        if overlap is not None and overlap >= 0.8 and cited_count == correct_count:
            cited_first = cited_authors.split(',')[0].strip().lower() if cited_authors else ''
            correct_first = correct_authors.split(',')[0].strip().lower() if correct_authors else ''
            if cited_first and correct_first and cited_first != correct_first:
                first_author_differs = True

        if overlap is not None and overlap <= 0.1:
            logger.debug(
                "DB match has catastrophic author mismatch (%.0f%% overlap) — "
                "attempting ArXiv re-verification for '%s'",
                overlap * 100, reference.get('title', '')[:60],
            )
        elif cited_more and overlap is not None and overlap >= 0.5:
            logger.debug(
                "DB has fewer authors (%d) than cited (%d), overlap %.0f%% — "
                "attempting ArXiv re-verification for '%s'",
                correct_count, cited_count, overlap * 100,
                reference.get('title', '')[:60],
            )
        elif correct_more and overlap is not None and overlap >= 0.5:
            logger.debug(
                "DB has more authors (%d) than cited (%d), overlap %.0f%% — "
                "likely ArXiv version update, attempting ArXiv re-verification for '%s'",
                correct_count, cited_count, overlap * 100,
                reference.get('title', '')[:60],
            )
        elif first_author_differs:
            logger.debug(
                "First-author order change with %.0f%% overlap — "
                "attempting ArXiv re-verification for '%s'",
                overlap * 100, reference.get('title', '')[:60],
            )
        else:
            return None

        if not self.arxiv_citation:
            return None

        arxiv_id = None
        try:
            arxiv_id, _ = self.arxiv_citation.extract_arxiv_id(reference)
        except Exception:
            pass
        if not arxiv_id and verified_data:
            ext = verified_data.get('externalIds') or {}
            arxiv_id = ext.get('ArXiv') or ext.get('arxiv') or None

        if not arxiv_id:
            return None

        try:
            # Ensure the reference has an ArXiv URL for the citation checker
            re_ref = dict(reference)
            if not re_ref.get('url') or 'arxiv.org' not in re_ref.get('url', ''):
                re_ref['url'] = f'https://arxiv.org/abs/{arxiv_id}'
            arxiv_data, arxiv_errors, arxiv_url = self.arxiv_citation.verify_reference(re_ref)
            if arxiv_data is not None:
                arxiv_data = self._annotate_match_source(
                    arxiv_data,
                    'arxiv_citation',
                    self.arxiv_citation,
                )
                logger.debug("ArXiv re-verification succeeded for %s", arxiv_id)
                return arxiv_errors or [], arxiv_url, arxiv_data
        except Exception as exc:
            logger.debug("ArXiv re-verification failed: %s", exc)

        return None

    def _postprocess_verification(
        self,
        verified_data: Optional[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        url: Optional[str],
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Apply post-verification checks shared by all code paths.

        1. ArXiv re-verification for catastrophic author mismatches
        2. Independent ArXiv ID mismatch check
        3. Error formatting

        Called at the end of verify_reference() so CLI, WebUI, and bulk
        all get identical results.
        """
        # 1. ArXiv re-verify when the DB matched the wrong paper
        if errors and verified_data is not None:
            re_result = self._try_arxiv_re_verify(errors, verified_data, reference)
            if re_result is not None:
                errors, url, verified_data = re_result

        # 2. Convert ArXiv version-only metadata differences to warnings.
        if errors and verified_data is not None:
            verified_data, errors, url = self._apply_arxiv_version_warnings(
                verified_data, errors, url, reference,
            )

        # 3. Independent ArXiv ID check — skip when the hybrid checker
        #    already verified the paper with no errors (avoids false
        #    positives from paraphrased titles in the S2 API).
        #    Also skip when version checking already converted title errors
        #    to warnings (e.g., "title (v9 vs v10 update)") — the version
        #    checker has already handled the title discrepancy.
        if errors:  # only when there are existing errors
            already_has_arxiv = any(e.get('error_type') == 'arxiv_id' for e in errors)
            has_version_title_warning = any(
                'title' in (e.get('warning_type') or '').lower()
                and 'update' in (e.get('warning_type') or '').lower()
                for e in errors
            )
            if not already_has_arxiv and not has_version_title_warning:
                arxiv_errors = self._check_arxiv_id_mismatch(reference, verified_data)
                if arxiv_errors:
                    errors = (errors or []) + arxiv_errors

        # 4. Reconcile publication years across authoritative metadata sources.
        # A database may use the online-first year while PubMed/Crossref uses
        # the issue/print year.  When the cited year is supported by any reliable
        # source, keep the reference verified and surface the disagreement as an
        # informational item instead of a warning/error.  This lives here (the
        # shared verifier entry point) so CLI, bulk, and WebUI remain identical.
        if errors and verified_data is not None:
            try:
                from refchecker.utils.publication_years import reconcile_publication_year
                verified_data, errors = reconcile_publication_year(
                    reference, verified_data, errors,
                )
            except Exception as exc:
                # Cross-source metadata is supplementary evidence. A provider
                # outage must never break or erase the primary verification.
                logger.debug("Publication-year reconciliation skipped: %s", exc)

        return verified_data, errors or [], url

    def verify_reference(
        self,
        reference: Dict[str, Any],
        force_all_databases: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Verify a reference and apply post-processing checks.

        This is the single entry point used by CLI, WebUI, and bulk paths.
        All verification logic lives here so every mode gets identical results.
        """
        self._raise_if_cancelled()
        # Repair field swaps before comparisons. This shared entry point is
        # used by CLI, WebUI, and bulk paths, and the fixup is idempotent.
        fixup_reference_fields(reference)

        # Configuration tracing is diagnostic only.  Keep it from preventing
        # the verification entry point from reaching its core logic when a
        # lightweight caller supplies just the verifier dependencies.
        try:
            configured_databases = self._configured_database_names()
        except AttributeError:
            configured_databases = []
        logger.info(
            "[DATABASE_TRACE] stage=verification_start title=%r authors=%r year=%r "
            "doi=%r force_all=%s configured=%s",
            reference.get('title'),
            reference.get('authors'),
            reference.get('year'),
            reference.get('doi') or reference.get('DOI'),
            force_all_databases,
            configured_databases,
        )

        if force_all_databases:
            verified_data, errors, url = self._verify_reference_core(
                reference,
                force_all_databases=True,
            )
        else:
            # Keep the default call compatible with lightweight wrappers and
            # tests that implement the original one-argument core contract.
            verified_data, errors, url = self._verify_reference_core(reference)

        self._raise_if_cancelled()
        # Post-process: ArXiv re-verify, independent ArXiv ID check
        verified_data, errors, url = self._postprocess_verification(
            verified_data, errors, url, reference,
        )
        self._raise_if_cancelled()

        # Cross-attribution: after a primary match lands, ask the
        # secondary signal sources (Paperclip + Wikidata) whether they
        # also have this paper. Stamp the union as `_verified_by` so
        # the FE renders "via Semantic Scholar + Paperclip + Wikidata"
        # instead of single-source attribution. Cheap: Paperclip is a
        # single DOI/title lookup, Wikidata is a single SPARQL — both
        # gated on Paperclip being enabled / Wikidata being reachable.
        if isinstance(verified_data, dict):
            try:
                self._cross_verify_secondary(verified_data, reference)
            except Exception as e:
                logger.debug("Cross-attribution skipped: %s", e)

        logger.info(
            "[DATABASE_TRACE] stage=verification_final title=%r status=%s "
            "matched_database=%r matched_checker=%r candidate=%r error_count=%d url=%r",
            reference.get('title'),
            'matched' if isinstance(verified_data, dict) else ('errors_only' if errors else 'not_found'),
            verified_data.get('_matched_database') if isinstance(verified_data, dict) else None,
            verified_data.get('_matched_checker') if isinstance(verified_data, dict) else None,
            self._database_trace_summary(verified_data),
            len(errors or []),
            url,
        )

        return verified_data, errors, url

    def _cross_verify_secondary(self, verified_data: Dict[str, Any], reference: Dict[str, Any]) -> None:
        """Ask Paperclip + Wikidata whether they also confirm the matched paper.

        The primary verifier already stamped `_matched_database`. This
        adds any secondary confirmations to `_verified_by` so users see
        all sources that independently confirmed the same paper.

        Mutates `verified_data` in place — appending to `_verified_by`.
        Doesn't raise; any source that errors out is silently skipped.
        """
        primary = verified_data.get('_matched_database') or verified_data.get('_matched_checker') or 'verified'
        confirmations = [primary]

        # Canonical DOI for cross-source lookup: prefer the primary
        # verifier's DOI, fall back to the cited DOI.
        doi = (
            verified_data.get('doi')
            or verified_data.get('DOI')
            or (verified_data.get('ids') or {}).get('doi')
            or (verified_data.get('externalIds') or {}).get('DOI')
            or reference.get('doi')
        )
        if isinstance(doi, str):
            doi = doi.strip()
            for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
                if doi.lower().startswith(prefix):
                    doi = doi[len(prefix):]
                    break

        # --- Paperclip cross-check ---
        # Don't re-query when Paperclip WAS the primary source.
        if self.paperclip and 'paperclip' not in primary.lower() and 'Paperclip' != primary:
            try:
                pc_ref = dict(reference)
                if doi:
                    pc_ref['doi'] = doi
                pc_data, _pc_errors, _pc_url = self.paperclip.verify_reference(pc_ref)
                if pc_data:
                    confirmations.append('Paperclip')
            except Exception as e:
                logger.debug("Paperclip cross-check failed: %s", e)

        # --- Wikidata cross-check ---
        # Single SPARQL query: ?work wdt:P356 "<DOI>" — returns a binding
        # iff Wikidata has this paper as an entity. No auth required;
        # short timeout so a slow Wikidata can't drag verification.
        if doi:
            try:
                import requests
                sparql = (
                    'SELECT ?work WHERE { '
                    f'?work wdt:P356 "{doi.upper()}" . '
                    '} LIMIT 1'
                )
                resp = requests.get(
                    'https://query.wikidata.org/sparql',
                    params={'query': sparql, 'format': 'json'},
                    headers={
                        'User-Agent': 'RefChecker/0.7 (https://github.com/ArioMoniri/refchecker)',
                        'Accept': 'application/sparql-results+json',
                    },
                    timeout=4.0,
                )
                if resp.status_code == 200:
                    bindings = (resp.json().get('results') or {}).get('bindings') or []
                    if bindings:
                        confirmations.append('Wikidata')
            except Exception as e:
                logger.debug("Wikidata cross-check failed: %s", e)

        # Dedup-preserve-order. Stamp even on single-confirmation so the
        # FE always has the verified_by list (matches enrichment.py's
        # contract of falling back to [source_label]).
        seen = set()
        deduped = []
        for s in confirmations:
            key = (s or '').strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        verified_data['_verified_by'] = deduped

    def _verify_reference_core(
        self,
        reference: Dict[str, Any],
        force_all_databases: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Core verification logic — parallel API calls + retries + fallbacks."""
        # Normal scans skip URL-only references, but an explicit "Search all DBs"
        # request must still enter the checker pipeline.
        authors = reference.get('authors', [])
        if authors and "URL Reference" in authors and not force_all_databases:
            logger.debug("Enhanced Hybrid: Skipping verification for URL reference")
            return None, [], reference.get('cited_url') or reference.get('url')
        
        title = self._coerce_text(reference.get('title', '')).strip()
        cited_url = self._coerce_text(reference.get('cited_url') or reference.get('url'))
        if not title and cited_url and not force_all_databases:
            logger.debug(f"Enhanced Hybrid: Skipping verification for URL-only reference: {cited_url}")
            return None, [], cited_url
        
        failed_apis = []
        attempted_apis = []
        db_not_found = False
        incomplete_data = None
        local_doi_mismatch_result = None
        forced_best_result = None
        is_arxiv = self.arxiv_citation and self.arxiv_citation.is_arxiv_reference(reference)
        
        # ── PHASE 1: Parallel API calls ──
        
        if is_arxiv:
            # For explicit ArXiv refs, the cited ArXiv ID/URL is the source of
            # truth. Verify it before local DB title search so a clean-looking
            # database match cannot hide a wrong cited ArXiv target.
            result = self._verify_arxiv_parallel(reference, failed_apis, attempted_apis)
            if result is not None:
                return self._handle_arxiv_result(result, reference)

            # ArXiv was unavailable or returned no result; fall back to local
            # DB lookups so offline/bulk runs can still verify by metadata.
            for local_key, _, local_checker in self._iter_local_db_checkers():
                self._append_attempted_api(attempted_apis, local_key)
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                    local_key,
                    local_checker,
                    reference,
                )
                if success:
                    if not self._has_major_author_discrepancy(errors):
                        return verified_data, errors, url
                    logger.debug(
                        "Enhanced Hybrid: %s has major author discrepancy for ArXiv ref, falling back to ArXiv citation",
                        local_key,
                    )
                elif failure_type == 'not_found' and local_key == 'local_s2':
                    # Only S2 local DB is treated as "global coverage" for skip-SS optimization.
                    # Other local DBs (OpenAlex/CrossRef/DBLP) are partial and should not suppress
                    # Semantic Scholar API attempts when they return not_found.
                    db_not_found = self._local_db_miss_is_authoritative(local_checker)
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': local_key,
                        'instance': local_checker,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
        else:
            # Non-ArXiv: try local DB first (instant), then parallel remote APIs
            for local_key, _, local_checker in self._iter_local_db_checkers():
                self._append_attempted_api(attempted_apis, local_key)
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                    local_key,
                    local_checker,
                    reference,
                )
                if success:
                    # A title match may identify the right work but expose only
                    # its arXiv DOI.  Keep searching configured local databases
                    # and DOI-aware remote sources for the DOI that was actually
                    # cited before accepting that mismatch warning.
                    if (
                        self._should_try_doi_apis_first(reference)
                        and self._has_doi_mismatch(errors)
                    ):
                        local_doi_mismatch_result = local_doi_mismatch_result or (
                            verified_data, errors, url,
                        )
                        logger.debug(
                            "Enhanced Hybrid: %s returned a DOI mismatch; continuing authoritative DOI lookup",
                            local_key,
                        )
                        if force_all_databases:
                            forced_best_result = self._pick_preferred_result(
                                forced_best_result,
                                (verified_data, errors, url),
                                reference,
                            )
                        continue
                    if force_all_databases:
                        forced_best_result = self._pick_preferred_result(
                            forced_best_result,
                            (verified_data, errors, url),
                            reference,
                        )
                        continue
                    return verified_data, errors, url
                if failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': local_key,
                        'instance': local_checker,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
                elif failure_type == 'not_found' and local_key == 'local_s2':
                    # See note above: only local_s2 controls skip_ss behavior.
                    db_not_found = self._local_db_miss_is_authoritative(local_checker)
            
            # Skip SS API when the 233M-paper local DB returned not_found —
            # if it's not in the DB, it's almost certainly not on SS either.
            result, incomplete_data = self._verify_non_arxiv_parallel(
                reference,
                failed_apis,
                attempted_apis,
                # In explicit force-all mode we must not suppress Semantic Scholar
                # based on local-DB miss heuristics.
                skip_ss=(db_not_found and not force_all_databases),
                force_all_databases=force_all_databases,
            )
            if result is not None:
                if force_all_databases:
                    forced_best_result = self._pick_preferred_result(
                        forced_best_result,
                        result,
                        reference,
                    )
                else:
                    return result
            if force_all_databases and forced_best_result is not None:
                return forced_best_result
            if result is not None:
                return result
            if local_doi_mismatch_result is not None:
                incomplete_data = incomplete_data or {}
                incomplete_data.setdefault('doi_mismatch', local_doi_mismatch_result)
        
        # Store incomplete results for Phase 3 fallback (thread-safe: returned
        # as local values from _verify_non_arxiv_parallel, not shared state)
        crossref_result = incomplete_data.get('crossref') if incomplete_data else None
        openalex_result = incomplete_data.get('openalex') if incomplete_data else None
        doi_mismatch_result = incomplete_data.get('doi_mismatch') if incomplete_data else None
        parallel_best_result = incomplete_data.get('best') if incomplete_data else None
        
        # PHASE 2: If no API succeeded in Phase 1, retry failed APIs.
        # Skip retries when the local DB definitively returned not_found —
        # if a paper isn't in a 233M-paper database, retrying throttled
        # remote APIs is almost certainly wasted time and the main cause
        # of verification timeouts.
        if failed_apis and self.local_db and db_not_found:
            logger.debug(f"Enhanced Hybrid: Skipping Phase 2 retries — local DB (233M papers) returned not_found, retrying remote APIs is unlikely to help")
        elif failed_apis:
            logger.debug(f"Enhanced Hybrid: Phase 1 complete, no success. Retrying {len(failed_apis)} failed APIs")
            
            # Sort failed APIs to prioritize Semantic Scholar retries
            retryable_failures = [
                api for api in failed_apis
                if api.get('failure_type') in ('throttled', 'timeout', 'server_error') and api.get('active', True)
            ]
            semantic_scholar_retries = [api for api in retryable_failures if api['name'] == 'semantic_scholar']
            other_retries = [api for api in retryable_failures if api['name'] != 'semantic_scholar']
            
            # Try other APIs first, then Semantic Scholar with more aggressive retries
            retry_order = other_retries + semantic_scholar_retries
            
            for failed_api in retry_order:
                api_name = failed_api['name']
                api_instance = failed_api['instance']
                failure_type = failed_api['failure_type']

                # Use base delay for first retry of each API
                delay = min(self.retry_base_delay, self.max_retry_delay)
                
                # Add jitter to prevent thundering herd (±25% randomization)
                jitter = delay * 0.25 * (2 * random.random() - 1)
                final_delay = max(0.5, delay + jitter)
                
                logger.debug(f"Enhanced Hybrid: Waiting {final_delay:.1f}s before retrying {api_name} after {failure_type} failure")
                self._emit_database_event(
                    database=api_name, label=self._format_api_name(api_name),
                    status='retry_wait', attempt=2, delay_seconds=round(final_delay, 2),
                )
                self._wait_or_cancel(final_delay)
                with self._api_time_lock:
                    self._api_retry_sleep_time += final_delay
                
                logger.debug(f"Enhanced Hybrid: Retrying {api_name}")
                self._append_attempted_api(attempted_apis, api_name)
                retry_reference = failed_api.get('reference', reference)
                verified_data, errors, url, success, retry_failure_type, retry_failure_detail = self._try_api(
                    api_name, api_instance, retry_reference, is_retry=True,
                )
                if success:
                    logger.debug(f"Enhanced Hybrid: {api_name} succeeded on retry after {failure_type} (delay: {final_delay:.1f}s)")
                    return verified_data, errors, url

                failed_api['failure_type'] = retry_failure_type
                failed_api['failure_detail'] = retry_failure_detail
                failed_api['active'] = retry_failure_type not in ('none', 'not_found')
                
                # For Semantic Scholar, try additional retries with increasing delays
                if api_name == 'semantic_scholar' and not success:
                    for retry_attempt in range(2):  # Additional 2 retries for Semantic Scholar
                        retry_delay = delay * (self.retry_backoff_factor ** (retry_attempt + 1))
                        retry_delay = min(retry_delay, self.max_retry_delay)
                        retry_jitter = retry_delay * 0.25 * (2 * random.random() - 1)
                        final_retry_delay = max(1.0, retry_delay + retry_jitter)
                        
                        logger.debug(f"Enhanced Hybrid: Additional Semantic Scholar retry {retry_attempt + 2} after {final_retry_delay:.1f}s")
                        self._emit_database_event(
                            database=api_name, label=self._format_api_name(api_name),
                            status='retry_wait', attempt=retry_attempt + 3,
                            delay_seconds=round(final_retry_delay, 2),
                        )
                        self._wait_or_cancel(final_retry_delay)
                        with self._api_time_lock:
                            self._api_retry_sleep_time += final_retry_delay
                        
                        self._append_attempted_api(attempted_apis, api_name)
                        verified_data, errors, url, success, retry_failure_type, retry_failure_detail = self._try_api(api_name, api_instance, reference, is_retry=True)
                        if success:
                            logger.debug(f"Enhanced Hybrid: {api_name} succeeded on retry {retry_attempt + 2} (delay: {final_retry_delay:.1f}s)")
                            return verified_data, errors, url

                        failed_api['failure_type'] = retry_failure_type
                        failed_api['failure_detail'] = retry_failure_detail
                        failed_api['active'] = retry_failure_type not in ('none', 'not_found')
        
        # PHASE 3: If all APIs failed or returned incomplete data, use best available incomplete data as fallback
        incomplete_results = [
            r for r in [parallel_best_result, crossref_result, openalex_result, doi_mismatch_result]
            if r is not None
        ]
        if incomplete_results:
            # Prefer CrossRef over OpenAlex for incomplete data (usually more reliable)
            best_incomplete = (
                parallel_best_result
                or crossref_result
                or openalex_result
                or doi_mismatch_result
            )
            logger.debug("Enhanced Hybrid: No complete data found, using incomplete data as fallback")
            return best_incomplete
        
        # If all APIs failed, return unverified with source tracking metadata
        active_failures = [api for api in failed_apis if api.get('active', True)]
        failed_count = len(active_failures)
        failed_api_names = {api['name'] for api in active_failures}
        failure_reason = self._build_unverified_error_details(attempted_apis, active_failures)
        sources_checked = len(attempted_apis)
        sources_negative = len([api_name for api_name in attempted_apis if api_name not in failed_api_names])
        
        if failed_count > 0:
            logger.debug(f"Enhanced Hybrid: Verification ended with {failed_count} active checker failures after {sources_checked} attempts")
        else:
            logger.debug("Enhanced Hybrid: All available APIs failed to verify reference")
        
        # PHASE 4: If the reference has a URL, try web page verification as final fallback.
        # This handles non-academic references (websites, datasets, tools) whose
        # cited URL is valid and contains the reference title.
        web_url = reference.get('cited_url') or reference.get('url', '')
        if web_url and web_url.startswith('http'):
            try:
                from refchecker.checkers.webpage_checker import WebPageChecker
                webpage_checker = WebPageChecker()
                wp_data, wp_errors, wp_url = webpage_checker.verify_raw_url_for_unverified_reference(reference)
                if wp_data:
                    logger.debug(f"Enhanced Hybrid: Web page verification succeeded for {web_url}")
                    return wp_data, wp_errors, wp_url
                else:
                    logger.debug(f"Enhanced Hybrid: Web page verification did not confirm reference")
                    # Build error list: include both a URL-specific error and the
                    # underlying unverified error so the user sees *why* it failed.
                    errors_out = []
                    if wp_errors:
                        subreason = wp_errors[0].get('error_details', '')
                        errors_out.append({
                            'error_type': 'unverified',
                            'error_details': failure_reason,
                            'sources_checked': sources_checked,
                            'sources_negative': sources_negative,
                        })
                        url_msg = self._url_failure_message(subreason, web_url)
                        errors_out.append({
                            'error_type': 'url' if 'URL references paper' not in subreason else 'unverified',
                            'error_details': url_msg,
                        })
                    else:
                        errors_out.append({
                            'error_type': 'unverified',
                            'error_details': failure_reason,
                            'sources_checked': sources_checked,
                            'sources_negative': sources_negative,
                        })
                    return None, errors_out, wp_url
            except Exception as exc:
                logger.debug(f"Enhanced Hybrid: Web page verification failed: {exc}")

        return None, [{
            'error_type': 'unverified',
            'error_details': failure_reason,
            'sources_checked': sources_checked,
            'sources_negative': sources_negative,
        }], None
    
    def _try_openreview_search(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool, str, str]:
        """
        Try to verify reference using OpenReview search
        
        Returns:
            Tuple of (verified_data, errors, url, success, failure_type, failure_detail)
        """
        if not self.openreview:
            return None, [], None, False, 'none', ''
        
        start_time = time.time()
        failure_type = 'none'
        
        try:
            verified_data, errors, url = self.openreview.verify_reference_by_search(reference)
            duration = time.time() - start_time
            
            # Consider it successful if we found data or verification errors
            success = verified_data is not None or len(errors) > 0
            self._update_api_stats('openreview', success, duration)
            
            if success:
                logger.debug(f"Enhanced Hybrid: OpenReview search successful in {duration:.2f}s, URL: {url}")
                return verified_data, errors, url, True, 'none', ''
            else:
                logger.debug(f"Enhanced Hybrid: OpenReview search found no results in {duration:.2f}s")
                return None, [], None, False, 'not_found', ''
                
        except requests.exceptions.Timeout as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            failure_type = 'timeout'
            logger.debug(f"Enhanced Hybrid: OpenReview search timed out in {duration:.2f}s: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
            
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            
            # Check if it's a rate limiting error
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in [429, 503]:
                    failure_type = 'throttled'
                elif e.response.status_code >= 500:
                    failure_type = 'server_error'
                else:
                    failure_type = 'other'
            else:
                failure_type = 'other'
            
            logger.debug(f"Enhanced Hybrid: OpenReview search failed in {duration:.2f}s: {type(e).__name__}: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            failure_type = 'other'
            logger.debug(f"Enhanced Hybrid: OpenReview search error in {duration:.2f}s: {type(e).__name__}: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for all APIs
        
        Returns:
            Dictionary with performance statistics
        """
        stats = {}
        for api_name, api_stats in self.api_stats.items():
            total_calls = api_stats['success'] + api_stats['failure']
            if total_calls > 0:
                success_rate = api_stats['success'] / total_calls
                stats[api_name] = {
                    'success_rate': success_rate,
                    'total_calls': total_calls,
                    'avg_time': api_stats['avg_time'],
                    'success_count': api_stats['success'],
                    'failure_count': api_stats['failure']
                }
            else:
                stats[api_name] = {
                    'success_rate': 0,
                    'total_calls': 0,
                    'avg_time': 0,
                    'success_count': 0,
                    'failure_count': 0
                }
        return stats
    
    def log_performance_summary(self):
        """Log a summary of API performance statistics (only if debug mode is enabled)"""
        if not self.debug_mode:
            return
            
        stats = self.get_performance_stats()
        logger.info("Enhanced Hybrid API Performance Summary:")
        for api_name, api_stats in stats.items():
            if api_stats['total_calls'] > 0:
                logger.info(f"  {api_name}: {api_stats['success_rate']:.2%} success rate, "
                           f"{api_stats['total_calls']} calls, {api_stats['avg_time']:.2f}s avg")
            else:
                logger.info(f"  {api_name}: not used")
    
    def normalize_paper_title(self, title: str) -> str:
        """
        Normalize paper title for comparison (delegates to Semantic Scholar checker)
        """
        if self.semantic_scholar:
            return self.semantic_scholar.normalize_paper_title(title)
        else:
            # Use the centralized normalization function from text_utils
            from refchecker.utils.text_utils import normalize_paper_title as normalize_title
            return normalize_title(title)
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[Any]) -> Tuple[bool, str]:
        """
        Compare author lists (delegates to shared utility)
        """
        from refchecker.utils.text_utils import compare_authors
        return compare_authors(cited_authors, correct_authors)

# Backward compatibility alias
HybridReferenceChecker = EnhancedHybridReferenceChecker
