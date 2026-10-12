"""Rank discovery suggestions against the citation, without verifying them."""

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


def suggestion_confirms_cited_metadata(reference, candidate):
    """Compatibility wrapper; callers must supply retrieved metadata."""
    from refchecker.utils.reference_evidence import compare_reference_evidence
    return compare_reference_evidence(reference, candidate)['confirmed']


def merge_reference_suggestions(candidates):
    """Combine records for one work while retaining each source's metadata."""
    import re
    from refchecker.utils.text_utils import enhanced_name_match

    def same_work(left, right):
        left_ids = EnhancedHybridReferenceChecker._candidate_identifiers(left)
        right_ids = EnhancedHybridReferenceChecker._candidate_identifiers(right)
        shared = set(left_ids) & set(right_ids)
        if any(left_ids[k] != right_ids[k] for k in shared):
            return False
        if shared:
            return True
        def title(item):
            return re.sub(r'[^\w]+', ' ', str(item.get('title') or '').casefold()).strip()
        if not title(left) or title(left) != title(right):
            return False
        if left.get('year') and right.get('year') and str(left['year']) != str(right['year']):
            return False
        authors_left = EnhancedHybridReferenceChecker._candidate_author_names(left)
        authors_right = EnhancedHybridReferenceChecker._candidate_author_names(right)
        return bool(authors_left and authors_right and any(enhanced_name_match(a, b) for a in authors_left for b in authors_right))

    groups = []
    for candidate in candidates:
        # Re-merging retains observations, including links from earlier passes.
        for observation in candidate.get('observations') or [candidate]:
            observation = {k: v for k, v in observation.items() if k not in {'observations', 'sources', 'discovery_status', 'strong_fit', 'fit_reasons'}}
            group = next((group for group in groups if all(same_work(member, observation) for member in group)), None)
            if group is None:
                groups.append([observation])
            elif observation not in group:
                group.append(observation)
    merged = []
    for group in groups:
        database_records = [item for item in group if item.get('source') not in (None, 'llm')]
        primary = (database_records or group)[0]
        sources = list(dict.fromkeys(item.get('source') or 'unknown' for item in group))
        links = []
        for item in group:
            for link in ([{'url': item['url'], 'type': item.get('source')}] if item.get('url') else []) + (item.get('links') or []):
                if isinstance(link, dict) and link.get('url') and not any(old['url'] == link['url'] for old in links):
                    links.append(link)
        merged.append({**primary, 'sources': sources, 'observations': group, 'links': links,
                       'discovery_status': 'database_candidate' if database_records else 'llm_only'})
    return merged


def rank_reference_suggestions(reference, candidates):
    # Use the same identity evidence as database verification. An LLM's own
    # confidence or explanation is never evidence that a publication exists.
    assessor = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
    ranked = []
    for candidate in merge_reference_suggestions(candidates):
        identity = assessor._assess_candidate_identity(reference, candidate)
        similarity = identity.get('title_similarity') or 0.0
        author_match = identity.get('author_overlap') is True
        year_gap = identity.get('year_gap')
        compatible = identity.get('status') != 'wrong_match'
        strong = compatible and (
            bool(identity.get('matching_identifiers'))
            or (similarity >= 0.9 and author_match and year_gap is not None and year_gap <= 1)
        )
        reasons = []
        if similarity >= 0.9:
            reasons.append('Very close title')
        if author_match:
            reasons.append('Author overlap')
        if year_gap == 0:
            reasons.append('Same year')
        if identity.get('matching_identifiers'):
            reasons.append('Matching identifier')
        score = similarity + (0.1 if author_match else 0) + (0.05 if year_gap == 0 else 0)
        ranked.append({
            **candidate,
            'strong_fit': bool(strong),
            'fit_reasons': reasons,
            '_ranking_score': score if compatible else -1,
        })
    ranked.sort(key=lambda item: (item['strong_fit'], item['_ranking_score'], item['discovery_status'] == 'database_candidate'), reverse=True)
    for candidate in ranked:
        candidate.pop('_ranking_score')
    return ranked
