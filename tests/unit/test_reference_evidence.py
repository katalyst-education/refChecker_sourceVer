from refchecker.utils.reference_evidence import compare_reference_evidence


def test_shared_matching_tolerates_formatting_and_author_initials():
    original = {'title': 'A study of software testing.', 'authors': ['B. Kitchenham'], 'year': '2007'}
    retrieved = {'title': 'A Study of Software Testing', 'authors': [{'name': 'Barbara Kitchenham'}], 'year': 2007}
    comparison = compare_reference_evidence(original, retrieved)
    assert comparison['confirmed']
    assert comparison['findings'] == []


def test_comparison_reports_missing_and_different_fields():
    original = {'title': 'A study', 'authors': ['Barbara Kitchenham'], 'year': 2007, 'doi': '10.1000/cited'}
    retrieved = {'title': 'A study', 'authors': ['Barbara Kitchenham', 'Stuart Charters'], 'doi': '10.1000/other'}
    comparison = compare_reference_evidence(original, retrieved)
    fields = {field['field']: field['status'] for field in comparison['fields']}
    assert fields['author'] == 'different'
    assert fields['year'] == 'unknown'
    assert fields['doi'] == 'different'
    assert not comparison['confirmed']


def test_webpage_request_values_are_not_treated_as_retrieved_bibliographic_metadata():
    original = {'title': 'A study', 'year': 2007}
    comparison = compare_reference_evidence(original, {**original, 'web_metadata': {'page_title': 'A study'}})
    assert not comparison['confirmed']
    assert all(field['status'] in {'unknown', 'not_cited'} for field in comparison['fields'])


def test_shared_venue_matching_accepts_equivalent_venue_names():
    original = {'title': 'A study', 'venue': 'Proceedings of the International Conference on Software Engineering'}
    retrieved = {'title': 'A study', 'venue': 'International Conference on Software Engineering'}
    assert compare_reference_evidence(original, retrieved)['confirmed']
