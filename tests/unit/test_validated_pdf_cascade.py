"""Regression tests for the shared, validated PDF extraction cascade."""

from pathlib import Path

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.extraction_quality import merge_grounded_reference_candidates


def test_grounded_merge_recovers_truncated_grobid_author_list():
    grobid = [{
        'title': 'Reliable Reference Extraction from PDFs',
        'authors': ['Alice Smith'],
        'year': 2024,
        'doi': '10.1000/example',
    }]
    text_parser = [{
        'title': 'Reliable reference extraction from PDFs',
        'authors': ['Alice Smith', 'Bob Jones', 'Carol Brown'],
        'year': 2024,
        'raw_text': 'Alice Smith, Bob Jones, and Carol Brown. Reliable reference extraction from PDFs. 2024.',
    }]

    merged = merge_grounded_reference_candidates(grobid, text_parser)

    assert merged[0]['authors'] == ['Alice Smith', 'Bob Jones', 'Carol Brown']
    assert merged[0]['raw_text'].startswith('Alice Smith')


def test_grounded_merge_does_not_mix_different_references():
    grobid = [{'title': 'First Paper', 'authors': ['Alice Smith'], 'year': 2024}]
    text_parser = [{'title': 'Entirely Different Work', 'authors': ['Alice Smith', 'Bob Jones'], 'year': 2024}]

    assert merge_grounded_reference_candidates(grobid, text_parser) == grobid


def test_numbered_parser_repairs_only_invalid_entries_with_llm():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.extraction_mode = 'cascade'
    checker.llm_extractor = object()
    checker.fatal_error = False
    checker.fatal_error_message = None
    checker.last_reference_parser_method = None
    checker._split_numbered_reference_entries = lambda _text: ['raw good', 'raw weak']
    checker._parse_references_regex = lambda _text: [
        {'title': 'Good Paper', 'authors': ['Alice Smith'], 'year': 2023},
        {'title': 'Weak Paper', 'authors': ['Bob Jones and Carol Brown'], 'year': 2024},
    ]
    captured = {}

    def repair(entries):
        captured['entries'] = entries
        return [{
            'title': 'Weak Paper',
            'authors': ['Bob Jones', 'Carol Brown'],
            'year': 2024,
        }]

    checker._extract_numbered_references_with_llm_chunks = repair
    checker._process_llm_extracted_references = lambda refs: refs

    references = checker.parse_references('bibliography')

    assert captured['entries'] == ['raw weak']
    assert references[0]['authors'] == ['Alice Smith']
    assert references[1]['authors'] == ['Bob Jones', 'Carol Brown']
    assert references[1]['raw_text'] == 'raw weak'


def test_initial_and_reextract_routes_use_shared_pdf_cascade():
    root = Path(__file__).resolve().parents[2]
    wrapper_source = (root / 'backend' / 'refchecker_wrapper.py').read_text(encoding='utf-8')
    main_source = (root / 'backend' / 'main.py').read_text(encoding='utf-8')
    core_source = (root / 'src' / 'refchecker' / 'core' / 'refchecker.py').read_text(encoding='utf-8')
    bulk_source = (root / 'src' / 'refchecker' / 'core' / 'bulk_pipeline.py').read_text(encoding='utf-8')

    assert 'references, pdf_method = await self._extract_references_from_pdf(' in wrapper_source
    assert 'extracted_references, _ = await extractor._extract_references_from_pdf(' in main_source
    assert 'merge_grounded_reference_candidates' in core_source
    assert 'merge_grounded_reference_candidates' in bulk_source
