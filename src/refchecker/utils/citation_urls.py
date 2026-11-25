"""Recover URLs from the printed lines of a single bibliography entry."""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


_URL_CHARS = r"[\w.:/~?#\[\]@!$&'()*+,;=%\-\u00ad]+"
_URL = re.compile(r'https?://' + _URL_CHARS, re.IGNORECASE)
_TOKEN = re.compile(_URL_CHARS)
_NEXT_LINE = re.compile(r'[ \t]*\r?\n[ \t]*')
_PROSE = re.compile(
    r'(?:https?:|www\.|doi\b|arxiv\b|url\b|isbn\b|issn\b|\[|vol\.|no\.|pp?\.|'
    r'access(?:ed| date)\b|available\b|retrieved\b|visited\b|(?:19|20)\d{2}\b|[IVXLCDM]{2,}[ \t]*(?:\r?\n|$))',
    re.IGNORECASE,
)
_UUID = re.compile(r'/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:[/?#]|$)', re.IGNORECASE)


@dataclass(frozen=True)
class CitationLink:
    original: str
    resolved: str
    alternative: str | None = None


def strip_citation_url_punctuation(value, *, punctuation='.,;!?'):
    """Trim citation punctuation and unmatched closing delimiters."""
    value = value.rstrip(punctuation)
    while value.endswith((')', ']', '}')):
        opening = {')': '(', ']': '[', '}': '{'}[value[-1]]
        if value.count(opening) >= value.count(value[-1]):
            break
        value = value[:-1].rstrip(punctuation)
    return value


def _absolute_url(value):
    try:
        parsed = urlsplit(value)
        return parsed if parsed.hostname and '.' in parsed.hostname else None
    except ValueError:
        return None


def _supported_join(left, right):
    combined = strip_citation_url_punctuation(left + right)
    if not _absolute_url(combined):
        return False
    if left.endswith('\u00ad') or not _absolute_url(left):
        return True
    if right.startswith(('/', '?', '&')) or re.match(r'^\.[a-z]{2,}(?:[/?#]|$)', right, re.I):
        return True
    if _UUID.search(combined) and not _UUID.search(left):
        return True
    if re.match(r'^[\w%-]+/[\w./~%-]+', right):
        return True
    if re.fullmatch(r'\d{2,}[.,;]?', right) and re.search(r'(?:[?&][\w-]+=\d*|[/=][\w-]{3,}\d)$', left):
        return True
    if re.search(r'%[0-9A-Fa-f]?$', left) and re.match(r'^[0-9a-fA-F]', right):
        return True
    return bool(re.search(r'\b10\.\d{4,9}/[^?#]+\)$', left) and re.match(r'^\d[\d-]+[.,;]?$', right))


def citation_links(source):
    """Yield printed links and flag a plausible continuation with weak evidence."""
    for match in _URL.finditer(source):
        first = match[0]
        joined = first
        end = match.end()
        alternative = None
        while not joined.endswith((',', ';')) and strip_citation_url_punctuation(joined, punctuation='') == joined:
            line_break = _NEXT_LINE.match(source, end)
            if not line_break or _PROSE.match(source, line_break.end()):
                break
            fragment = _TOKEN.match(source, line_break.end())
            if not fragment:
                break
            right = fragment[0]
            following = source[fragment.end():].split('\n', 1)[0].strip()
            if following and not right.endswith((',', ';', '.')):
                break
            candidate = strip_citation_url_punctuation((joined + right).replace('\u00ad', ''))
            if not _supported_join(joined, right):
                if candidate and _absolute_url(candidate):
                    alternative = candidate
                break
            joined = (joined + right).replace('\u00ad', '')
            end = fragment.end()
        yield CitationLink(
            strip_citation_url_punctuation(first.replace('\u00ad', '')),
            strip_citation_url_punctuation(joined.replace('\u00ad', '')),
            alternative,
        )
