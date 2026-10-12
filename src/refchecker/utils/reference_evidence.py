"""Compare cited metadata with retrieved evidence using shared matching rules."""

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.utils.text_utils import (
    are_venues_substantially_different, compare_authors,
    titles_align_with_subtitle_tolerance,
)


def _venue(data):
    value = data.get('venue') or data.get('journal') or data.get('booktitle') or data.get('publicationVenue')
    if isinstance(value, dict):
        return value.get('name') or value.get('display_name')
    return value


def compare_reference_evidence(reference, evidence):
    """Return field findings for the original citation, never the LLM's claims.

    Missing fields are unknown, not matches. Web fallback values may have been
    copied from the request, so those cannot establish bibliographic agreement.
    This helper is shared by callers; no UI-specific matching rules live here.
    """
    evidence = evidence or {}
    fields = []
    findings = []
    copied_web_metadata = bool(evidence.get('web_metadata'))

    def compare(field, cited, actual, matches):
        if cited in (None, '', []):
            status = 'not_cited'
        elif copied_web_metadata or actual in (None, '', []):
            status = 'unknown'
        else:
            status = 'confirmed' if matches(cited, actual) else 'different'
        fields.append({'field': field, 'cited': cited, 'actual': actual, 'status': status})
        if status == 'different':
            findings.append({
                'warning_type': field,
                'warning_details': f'Cited {field} differs from the retrieved source.',
                'cited_value': cited, 'actual_value': actual,
            })
        elif status == 'unknown':
            findings.append({'error_type': 'unverified', 'error_details': f'The retrieved source does not independently confirm the cited {field}.'})

    compare('title', reference.get('title'), evidence.get('title') or evidence.get('display_name'), titles_align_with_subtitle_tolerance)
    compare('author', EnhancedHybridReferenceChecker._candidate_author_names(reference),
            EnhancedHybridReferenceChecker._candidate_author_names(evidence), lambda a, b: compare_authors(a, b)[0])
    compare('year', reference.get('year'), evidence.get('publication_year') or evidence.get('year'), lambda a, b: str(a) == str(b))
    compare('venue', _venue(reference), _venue(evidence), lambda a, b: not are_venues_substantially_different(
        a, b, citation_style=reference.get('citation_style'), paper_title=reference.get('title')))
    cited_ids = EnhancedHybridReferenceChecker._candidate_identifiers(reference)
    actual_ids = EnhancedHybridReferenceChecker._candidate_identifiers(evidence)
    for kind, value in cited_ids.items():
        compare(kind, value, actual_ids.get(kind), lambda a, b: a == b)
    checked = [field for field in fields if field['status'] != 'not_cited']
    confirmed = bool(reference.get('title')) and bool(checked) and all(field['status'] == 'confirmed' for field in checked)
    return {'confirmed': confirmed, 'fields': fields, 'findings': findings}
