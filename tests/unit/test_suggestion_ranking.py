from refchecker.utils.suggestion_ranking import rank_reference_suggestions, suggestion_confirms_cited_metadata


REFERENCE = {'title': 'Guidelines for performing Systematic Literature Reviews in software engineering',
             'authors': ['B. Kitchenham'], 'year': 2007}


def test_close_suggestion_is_ranked_above_wrong_work_without_claiming_verification():
    candidates = [
        {'title': 'Protocol for a Tertiary study of Systematic Literature Reviews and Evidence-based Guidelines in IT and Software Engineering',
         'authors': ['B. Kitchenham'], 'year': 2009, 'source': 'semantic_scholar'},
        {**REFERENCE, 'authors': ['Barbara Kitchenham', 'Stuart Charters'], 'source': 'llm'},
    ]
    ranked = rank_reference_suggestions(REFERENCE, candidates)
    assert ranked[0]['source'] == 'llm'
    assert ranked[0]['strong_fit'] is True
    assert ranked[0]['fit_reasons'] == ['Very close title', 'Author overlap', 'Same year']
    assert ranked[1]['strong_fit'] is False
    assert 'strong_fit' not in candidates[1]
    assert 'verified' not in ranked[0]


def test_ambiguous_or_incomplete_metadata_is_not_highlighted():
    candidates = [{**REFERENCE, 'authors': ['Someone Else']},
                  {**REFERENCE, 'year': None}, {**REFERENCE, 'year': 1990}]
    assert not any(item['strong_fit'] for item in rank_reference_suggestions(REFERENCE, candidates))


def test_conflicting_identifier_prevents_highlight():
    reference = {**REFERENCE, 'doi': '10.1000/original'}
    ranked = rank_reference_suggestions(reference, [{**REFERENCE, 'doi': '10.1000/other'}])
    assert ranked[0]['strong_fit'] is False


def test_confirmation_requires_unchanged_cited_metadata():
    assert suggestion_confirms_cited_metadata(REFERENCE, {**REFERENCE, 'url': 'https://example.org/report'})
    for changed in ({'authors': ['Barbara Kitchenham', 'Stuart Charters']}, {'year': 2009}, {'title': 'Other work'}):
        assert not suggestion_confirms_cited_metadata(REFERENCE, {**REFERENCE, **changed})
    assert not suggestion_confirms_cited_metadata({**REFERENCE, 'venue': 'Original venue'}, REFERENCE)


def test_duplicates_merge_sources_links_and_keep_database_metadata():
    candidates = [
        {**REFERENCE, 'source': 'llm', 'url': 'https://example.org/ai', 'doi': '10.1000/report'},
        {**REFERENCE, 'authors': ['Barbara Kitchenham', 'Stuart Charters'], 'source': 'crossref', 'url': 'https://doi.org/10.1000/report', 'doi': '10.1000/report'},
        {**REFERENCE, 'source': 'openalex', 'url': 'https://openalex.org/W123', 'doi': 'https://doi.org/10.1000/report'},
    ]
    ranked = rank_reference_suggestions(REFERENCE, candidates)
    assert len(ranked) == 1
    assert ranked[0]['authors'] == candidates[1]['authors']
    assert set(ranked[0]['sources']) == {'llm', 'crossref', 'openalex'}
    assert len(ranked[0]['links']) == 3
    assert len(ranked[0]['observations']) == 3
    assert ranked[0]['discovery_status'] == 'database_candidate'


def test_different_identifiers_are_not_merged_despite_identical_titles():
    ranked = rank_reference_suggestions(REFERENCE, [
        {**REFERENCE, 'doi': '10.1000/first', 'source': 'crossref'},
        {**REFERENCE, 'doi': '10.1000/second', 'source': 'openalex'},
    ])
    assert len(ranked) == 2


def test_repeated_llm_citation_is_not_source_confirmation():
    ranked = rank_reference_suggestions(REFERENCE, [{**REFERENCE, 'source': 'llm'}])
    assert ranked[0]['strong_fit']
    assert ranked[0]['discovery_status'] == 'llm_only'
