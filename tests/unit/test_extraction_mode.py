from unittest.mock import Mock, patch

from backend.refchecker_wrapper import _make_cli_checker
from refchecker.core.bulk_pipeline import parse_references_bulk
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.cache_utils import llm_cache_identity_from_extractor


GOOD_REFERENCE = {
    'title': 'A sufficiently descriptive paper title',
    'authors': ['Ada Author'],
    'year': 2024,
}
NUMBERED_ENTRIES = [
    '[1] Ada Author. A sufficiently descriptive paper title. Journal 1, 2024.',
    '[2] Bea Author. A second sufficiently descriptive title. Journal 2, 2023.',
    '[3] Cy Author. A third sufficiently descriptive title. Journal 3, 2022.',
]


def _checker(mode='cascade'):
    return ArxivReferenceChecker(
        llm_config={'disabled': True},
        extraction_mode=mode,
    )


def test_shared_parser_cascade_uses_valid_deterministic_output_before_llm():
    checker = _checker('cascade')
    checker.llm_extractor = Mock()
    expected = [dict(GOOD_REFERENCE) for _ in NUMBERED_ENTRIES]
    checker._split_numbered_reference_entries = Mock(return_value=NUMBERED_ENTRIES)
    checker._parse_references_regex = Mock(return_value=expected)

    references = checker.parse_references('[1] Ada Author. A paper title. 2024.')

    assert references == expected
    checker.llm_extractor.extract_references.assert_not_called()
    assert checker.last_reference_parser_method == 'regex'


def test_shared_parser_llm_only_bypasses_deterministic_output():
    checker = _checker('llm-only')
    checker.llm_extractor = Mock()
    checker.llm_extractor.extract_references.return_value = ['raw reference']
    checker._split_numbered_reference_entries = Mock(return_value=NUMBERED_ENTRIES)
    checker._parse_references_regex = Mock(return_value=[dict(GOOD_REFERENCE) for _ in NUMBERED_ENTRIES])
    checker._process_llm_extracted_references = Mock(return_value=[{'title': 'LLM result'}])

    references = checker.parse_references('[1] Ada Author. A paper title. 2024.')

    assert references == [{'title': 'LLM result'}]
    checker._parse_references_regex.assert_not_called()
    assert checker.llm_extractor.extract_references.call_count >= 1
    assert checker.last_reference_parser_method == 'llm'


def test_web_lightweight_checker_uses_the_same_mode_policy():
    checker = _make_cli_checker(None, 'llm-only')
    assert checker.extraction_mode == 'llm-only'


def test_bulk_cascade_uses_shared_deterministic_parser_before_batch_llm():
    checker = _checker('cascade')
    original_llm = Mock()
    checker.llm_extractor = original_llm
    expected = [dict(GOOD_REFERENCE) for _ in NUMBERED_ENTRIES]
    checker._split_numbered_reference_entries = Mock(return_value=NUMBERED_ENTRIES)
    checker._parse_references_regex = Mock(return_value=expected)
    batcher = Mock()

    references = parse_references_bulk(
        checker,
        '[1] Ada Author. A paper title. 2024.',
        batcher,
    )

    assert references == expected
    batcher.extract_references.assert_not_called()
    assert checker.llm_extractor is original_llm


def test_bibliography_cache_identity_separates_extraction_modes():
    cascade = llm_cache_identity_from_extractor(None, 'cascade')
    llm_only = llm_cache_identity_from_extractor(None, 'llm-only')

    assert cascade != llm_only
    assert cascade.endswith(':mode=cascade')
    assert llm_only.endswith(':mode=llm-only')
