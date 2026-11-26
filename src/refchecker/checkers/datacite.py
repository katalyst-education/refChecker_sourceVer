"""DOI lookup for DataCite-registered datasets, software, and publications."""

import logging
from urllib.parse import urlsplit

import requests

from refchecker.utils.doi_utils import doi_request_path, extract_cited_doi
from refchecker.utils.error_utils import format_title_mismatch, format_year_mismatch
from refchecker.utils.text_utils import calculate_title_similarity, compare_authors

logger = logging.getLogger(__name__)
API_BASE = 'https://api.datacite.org/dois'
TITLE_MATCH_THRESHOLD = 0.6


def _year(value):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _list_field(attributes, key):
    value = attributes.get(key)
    return value if isinstance(value, list) else []


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _landing_url(value, path):
    url = _text(value)
    try:
        parsed = urlsplit(url)
        if parsed.scheme in ('https', 'http') and parsed.hostname and parsed.username is None:
            return url
    except ValueError:
        pass
    return f'https://doi.org/{path}'


class DataCiteChecker:
    """Resolve a cited DOI with the public DataCite REST API."""

    database_label = 'DataCite'

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RefChecker/1.0 (https://github.com/katalyst-education/refChecker_sourceVer)',
            'Accept': 'application/vnd.api+json',
        })

    def get_work_by_doi(self, doi: str) -> dict | None:
        """Fetch attributes; transport and protocol failures are not misses."""
        path = doi_request_path(doi)
        if not path:
            return None
        response = self.session.get(f'{API_BASE}/{path}', timeout=self.timeout, allow_redirects=False)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise requests.HTTPError(f'DataCite returned HTTP {response.status_code}', response=response)
        payload = response.json()
        data = payload.get('data') if isinstance(payload, dict) else None
        attributes = data.get('attributes') if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise ValueError('DataCite response has no record attributes')
        return attributes

    def verify_reference(self, reference: dict) -> tuple[dict | None, list[dict], str | None]:
        doi = extract_cited_doi(reference)
        path = doi_request_path(doi)
        if not path:
            return None, [], None
        attributes = self.get_work_by_doi(doi)
        if not attributes:
            return None, [], None

        title = next((title for entry in _list_field(attributes, 'titles')
                      if (title := _text(entry.get('title') if isinstance(entry, dict) else entry))), '')
        if not title:
            return None, [], None
        creators = []
        for creator in _list_field(attributes, 'creators'):
            if isinstance(creator, dict):
                given, family = _text(creator.get('givenName')), _text(creator.get('familyName'))
                name = f'{given} {family}' if given and family else _text(creator.get('name')) or family
                if name:
                    creators.append(name)
        year = _year(attributes.get('publicationYear'))
        container = attributes.get('container')
        venue = _text(container.get('title')) if isinstance(container, dict) else ''
        url = _landing_url(attributes.get('url'), path)
        cited_title = _text(reference.get('title'))
        cited_year = reference.get('year')
        cited_authors = reference.get('authors') or []
        errors = []
        if cited_title:
            score = calculate_title_similarity(cited_title, title)
            if score < TITLE_MATCH_THRESHOLD:
                logger.debug('DataCite: title mismatch for %s (score %.2f)', doi, score)
                return None, [], None
            if score < 0.9:
                errors.append({
                    'warning_type': 'title',
                    'warning_details': format_title_mismatch(cited_title, title),
                    'ref_title_correct': title,
                })
        if cited_authors and creators:
            matches, details = compare_authors(cited_authors, creators)
            if not matches:
                errors.append({
                    'error_type': 'author', 'error_details': details,
                    'ref_authors_correct': ', '.join(creators),
                })
        if cited_year and year:
            parsed_year = _year(cited_year)
            if parsed_year is None or abs(parsed_year - year) > 1:
                errors.append({
                    'warning_type': 'year',
                    'warning_details': format_year_mismatch(cited_year, year),
                    'ref_year_correct': year,
                })
        return {
            'title': title, 'authors': creators, 'year': year,
            'venue': venue or _text(attributes.get('publisher')),
            'doi': doi, 'url': url, '_matched_database': self.database_label,
        }, errors, url
