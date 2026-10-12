from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from refchecker.core.bulk_pipeline import (
    BulkPaperResult,
    BulkLLMExtractionBatcher,
    BulkProgressReporter,
    BulkVerificationCache,
    _finalize_hallucination_on_result,
    extract_bibliography_bulk,
    parse_references_bulk,
)
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.services.pdf_pipeline import ExtractedDocument


class _FakeExtractionProvider:
    def _call_llm(self, prompt):
        assert 'ITEM 0' in prompt
        assert 'ITEM 1' in prompt
        return (
            '[\n'
            '  {"index": 0, "references": ["A One#Paper One#Venue One#2024#https://one"]},\n'
            '  {"index": 1, "references": ["B Two#Paper Two#Venue Two#2025#https://two"]}\n'
            ']'
        )


class _FakeExtractionChecker:
    def __init__(self):
        self.llm_extractor = SimpleNamespace(llm_provider=_FakeExtractionProvider())

    def _process_llm_extracted_references(self, references):
        return [{'raw': reference} for reference in references]


class _EmptyItemExtractionProvider:
    def _call_llm(self, prompt):
        assert 'ITEM 0' in prompt
        assert 'ITEM 1' in prompt
        return (
            '[\n'
            '  {"index": 0, "references": ["A One#Paper One#Venue One#2024#https://one"]},\n'
            '  {"index": 1, "references": []}\n'
            ']'
        )


class _InvalidJsonExtractionProvider:
    def _call_llm(self, prompt):
        assert 'ITEM 0' in prompt
        assert 'ITEM 1' in prompt
        return 'I found references, but this is not the requested JSON array.'


class _FallbackExtractionChecker:
    def __init__(self, provider=None):
        self.single_calls = []
        self.llm_extractor = SimpleNamespace(
            llm_provider=provider or _EmptyItemExtractionProvider(),
            extract_references=self._extract_single,
        )

    def _extract_single(self, bibliography_text):
        self.single_calls.append(bibliography_text)
        return ['Fallback Author#Fallback Paper#Fallback Venue#2026#https://fallback']

    def _process_llm_extracted_references(self, references):
        return [{'raw': reference} for reference in references]


class _EmptyExtractionBatcher:
    def extract_references(self, checker, bibliography_text):
        return []


class _RecordingExtractionBatcher:
    def __init__(self, references=None):
        self.calls = []
        self.references = references or [{'title': 'LLM Extracted'}]

    def extract_references(self, checker, bibliography_text):
        self.calls.append(bibliography_text)
        return self.references


class _DiagnosticChecker:
    def __init__(self, llm_extractor=True):
        self.fatal_error = False
        self.fatal_error_message = None
        self.llm_extractor = object() if llm_extractor else None
        self.used_regex_extraction = False

    def _parse_biblatex_references(self, bibliography_text):
        return []

    def _parse_bibtex_references(self, bibliography_text):
        return []

    def _parse_standard_acm_natbib_references(self, bibliography_text):
        return []


def test_bulk_llm_extraction_batcher_processes_multiple_items():
    batcher = BulkLLMExtractionBatcher(enabled=False)
    checker = _FakeExtractionChecker()

    results = batcher._process_batch([
        SimpleNamespace(checker=checker, bibliography_text='refs one'),
        SimpleNamespace(checker=checker, bibliography_text='refs two'),
    ])

    assert results == [
        [{'raw': 'A One#Paper One#Venue One#2024#https://one'}],
        [{'raw': 'B Two#Paper Two#Venue Two#2025#https://two'}],
    ]


def test_bulk_llm_extraction_batcher_retries_empty_items_individually():
    batcher = BulkLLMExtractionBatcher(enabled=False)
    checker = _FallbackExtractionChecker()

    results = batcher._process_batch([
        SimpleNamespace(checker=checker, bibliography_text='refs one'),
        SimpleNamespace(checker=checker, bibliography_text='refs two'),
    ])

    assert results == [
        [{'raw': 'A One#Paper One#Venue One#2024#https://one'}],
        [{'raw': 'Fallback Author#Fallback Paper#Fallback Venue#2026#https://fallback'}],
    ]
    assert checker.single_calls == ['refs two']


def test_bulk_llm_extraction_batcher_retries_invalid_json_batch_individually():
    batcher = BulkLLMExtractionBatcher(enabled=False)
    checker = _FallbackExtractionChecker(provider=_InvalidJsonExtractionProvider())

    results = batcher._process_batch([
        SimpleNamespace(checker=checker, bibliography_text='refs one'),
        SimpleNamespace(checker=checker, bibliography_text='refs two'),
    ])

    assert results == [
        [{'raw': 'Fallback Author#Fallback Paper#Fallback Venue#2026#https://fallback'}],
        [{'raw': 'Fallback Author#Fallback Paper#Fallback Venue#2026#https://fallback'}],
    ]
    assert checker.single_calls == ['refs one', 'refs two']


def test_parse_references_bulk_records_zero_reference_diagnostic():
    checker = _DiagnosticChecker(llm_extractor=True)
    bibliography_text = 'References\nSmith, Jane. A Paper That Should Be Extracted. Test Venue, 2024.'

    references = parse_references_bulk(checker, bibliography_text, _EmptyExtractionBatcher())

    assert references == []
    assert checker.fatal_error is True
    assert 'Reference extraction produced zero references using LLM extraction' in checker.fatal_error_message
    assert 'bibliography_text_chars=' in checker.fatal_error_message


def test_bulk_pdf_uses_structured_bibliography_and_keeps_body_separate():
    body_text = (
        'The manuscript discusses the method and cites prior work [1]. '
    ) * 8
    bibliography = (
        '[1] John Smith and Alice Jones. A robust method for scientific analysis. '
        'Journal of Testing, 2021.\n'
        '[2] Jane Doe and Bob Roe. An efficient approach to academic research. '
        'Conference Proceedings, 2022.\n'
        '[3] Alice Brown and Carol White. Improved models for reliable systems. '
        'Transactions on Testing, 2023.'
    )
    document = ExtractedDocument(
        file='paper.pdf',
        doc_type='one_column_paper',
        extractor='test_pipeline',
        body_text=body_text,
        bibliography=bibliography,
        full_text=f'{body_text}\n\nReferences\n{bibliography}',
        metadata={
            'extraction_diagnostics': {
                'bibliography_status': 'extracted',
                'errors': [],
                'warnings': [],
            },
        },
    )
    checker = ArxivReferenceChecker(llm_config={'disabled': True})
    checker.extraction_mode = 'llm-only'
    checker.download_pdf = MagicMock(return_value=BytesIO(b'pdf bytes'))
    checker.pdf_processor.extract_document = MagicMock(return_value=document)
    paper = SimpleNamespace(
        title='Test paper',
        file_path=None,
        get_short_id=lambda: 'test-paper',
        is_latex=False,
        is_bibtex=False,
        is_text_refs=False,
    )
    batcher = _RecordingExtractionBatcher(
        references=[{'title': 'Parsed structured reference'}]
    )

    from refchecker.core import bulk_pipeline

    with (
        patch.object(bulk_pipeline, 'get_bibtex_content', return_value=None),
        patch.object(
            bulk_pipeline,
            'parse_references_bulk',
            side_effect=lambda _checker, text, _batcher: (
                batcher.extract_references(_checker, text)
            ),
        ),
    ):
        references = extract_bibliography_bulk(
            checker,
            paper,
            debug_mode=False,
            extraction_batcher=batcher,
        )

    assert references == [{'title': 'Parsed structured reference'}]
    assert len(batcher.calls) == 1
    assert batcher.calls[0].strip() == bibliography
    assert checker.last_paper_text.strip() == body_text.strip()
    assert '[1] John Smith' not in checker.last_paper_text
    checker.pdf_processor.extract_document.assert_called_once_with(
        checker.download_pdf.return_value,
        include_bibliography=True,
    )


def test_bulk_source_bibliography_keeps_priority_over_pdf_pipeline():
    checker = ArxivReferenceChecker(llm_config={'disabled': True})
    checker.download_pdf = MagicMock()
    checker.pdf_processor.extract_document = MagicMock()
    paper = SimpleNamespace(
        title='Test paper',
        file_path=None,
        get_short_id=lambda: 'test-paper',
        is_latex=False,
        is_bibtex=False,
        is_text_refs=False,
    )
    batcher = _RecordingExtractionBatcher(
        references=[{'title': 'Source bibliography reference'}]
    )
    from refchecker.core import bulk_pipeline

    with (
        patch.object(
            bulk_pipeline,
            'get_bibtex_content',
            return_value='@article{source, title={Source bibliography}}',
        ),
        patch.object(
            bulk_pipeline,
            'parse_references_bulk',
            side_effect=lambda _checker, text, _batcher: (
                batcher.extract_references(_checker, text)
            ),
        ),
    ):
        references = extract_bibliography_bulk(
            checker,
            paper,
            debug_mode=False,
            extraction_batcher=batcher,
        )

    assert references == [{'title': 'Source bibliography reference'}]
    assert batcher.calls == ['@article{source, title={Source bibliography}}']
    checker.pdf_processor.extract_document.assert_not_called()
    checker.download_pdf.assert_not_called()


def test_bulk_pdf_pipeline_failure_uses_legacy_text_and_preserves_body():
    body_text = ('The paper cites prior work [1]. ') * 8
    bibliography = (
        '[1] John Smith and Alice Jones. A robust method for scientific analysis. '
        'Journal of Testing, 2021.\n'
        '[2] Jane Doe and Bob Roe. An efficient approach to academic research. '
        'Conference Proceedings, 2022.\n'
        '[3] Alice Brown and Carol White. Improved models for reliable systems. '
        'Transactions on Testing, 2023.'
    )
    checker = ArxivReferenceChecker(llm_config={'disabled': True})
    checker.extraction_mode = 'llm-only'
    checker.download_pdf = MagicMock(return_value=BytesIO(b'pdf bytes'))
    checker.pdf_processor.extract_document = MagicMock(
        side_effect=ValueError('pipeline failed')
    )
    checker.extract_text_from_pdf = MagicMock(
        return_value=f'{body_text}\n\nReferences\n{bibliography}'
    )
    paper = SimpleNamespace(
        title='Test paper',
        file_path=None,
        get_short_id=lambda: 'test-paper',
        is_latex=False,
        is_bibtex=False,
        is_text_refs=False,
    )
    batcher = _RecordingExtractionBatcher(
        references=[{'title': 'Legacy reference'}]
    )
    from refchecker.core import bulk_pipeline

    with (
        patch.object(bulk_pipeline, 'get_bibtex_content', return_value=None),
        patch.object(
            bulk_pipeline,
            'parse_references_bulk',
            side_effect=lambda _checker, text, _batcher: (
                batcher.extract_references(_checker, text)
            ),
        ),
    ):
        references = extract_bibliography_bulk(
            checker,
            paper,
            debug_mode=False,
            extraction_batcher=batcher,
        )

    assert references == [{'title': 'Legacy reference'}]
    assert len(batcher.calls) == 1
    assert batcher.calls[0].strip() == bibliography
    assert checker.last_paper_text.strip() == body_text.strip()
    assert '[1] John Smith' not in checker.last_paper_text
    checker.extract_text_from_pdf.assert_called_once_with(
        checker.download_pdf.return_value
    )


def test_parse_references_bulk_uses_llm_before_structured_parsers():
    checker = _DiagnosticChecker(llm_extractor=True)
    bibliography_text = (
        'References\n'
        '[1] Jane Smith and John Doe. A structured-looking paper. Test Venue, 2024.\n'
    )
    batcher = _RecordingExtractionBatcher()

    references = parse_references_bulk(checker, bibliography_text, batcher)

    assert references == [{'title': 'LLM Extracted'}]
    assert batcher.calls == [bibliography_text]
    assert checker.used_regex_extraction is False


def test_parse_references_bulk_records_missing_llm_diagnostic():
    checker = _DiagnosticChecker(llm_extractor=False)
    bibliography_text = 'References\nSmith, Jane. A Paper That Should Be Extracted. Test Venue, 2024.'

    references = parse_references_bulk(checker, bibliography_text, _EmptyExtractionBatcher())

    assert references == []
    assert checker.fatal_error is True
    assert 'no LLM extractor is configured' in checker.fatal_error_message


def test_extract_bibliography_bulk_records_missing_section_diagnostic():
    checker = _DiagnosticChecker(llm_extractor=True)
    checker.download_pdf = lambda paper: BytesIO(b'not a real pdf')
    checker.extract_text_from_pdf = lambda pdf_content: 'This paper text has no references heading.'
    checker.find_bibliography_section = lambda text: None
    checker._get_source_paper_url = lambda paper: 'https://openreview.net/forum?id=missingbib'
    paper = SimpleNamespace(get_short_id=lambda: 'missingbib', title='Missing Bibliography')

    references = extract_bibliography_bulk(checker, paper, debug_mode=True, extraction_batcher=_EmptyExtractionBatcher())

    assert references == []
    assert checker.fatal_error is True
    assert 'Could not locate a bibliography/references section' in checker.fatal_error_message
    assert 'paper_id=missingbib' in checker.fatal_error_message


def test_bulk_progress_reporter_prints_timestamped_completion(capsys):
    reporter = BulkProgressReporter(total_papers=3)

    reporter.report(
        SimpleNamespace(
            index=0,
            title='Example Paper',
            paper_id='paper-1',
            input_spec='paper-1',
            source_url='https://example.com/paper-1',
            elapsed_seconds=42.5,
            references_processed=10,
            total_errors_found=2,
            total_warnings_found=1,
            total_info_found=0,
            total_unverified_refs=3,
            errors=[],
        )
    )

    output = capsys.readouterr().out.strip()
    assert '1/3' in output
    assert 'paper-1' in output
    assert 'refs=10' in output
    assert 'errors=2' in output
    assert 'Totals: refs=10' in output


def test_verification_cache_hit_and_miss():
    cache = BulkVerificationCache()

    ref_a = {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    ref_b = {'title': 'Deep Residual Learning for Image Recognition', 'authors': ['Kaiming He'], 'year': '2016'}

    # First lookup is a miss
    assert cache.get(ref_a) is None
    assert cache.misses == 1
    assert cache.hits == 0

    # Store result
    result_a = ([{'error_type': 'year', 'error_details': 'off by one'}], 'https://arxiv.org/abs/1706.03762', {'title': 'Attention Is All You Need'})
    cache.put(ref_a, result_a)
    assert cache.size == 1

    # Second lookup is a hit
    cached = cache.get(ref_a)
    assert cached is result_a
    assert cache.hits == 1
    assert cache.misses == 1

    # Different reference is a miss
    assert cache.get(ref_b) is None


def test_verification_cache_variant_lookups():
    cache = BulkVerificationCache()

    ref_a = {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    result_a = ([{'error_type': 'year', 'error_details': 'off by one'}], 'https://arxiv.org/abs/1706.03762', {'title': 'Attention Is All You Need'})
    cache.put(ref_a, result_a)

    # Same title from different paper (slightly different author format) still hits
    # because last name 'Vaswani' normalizes the same way
    ref_a_variant = {'title': 'Attention Is All You Need', 'authors': ['A. Vaswani'], 'year': '2017'}
    assert cache.get(ref_a_variant) is result_a

    # Truly different first author last name is a miss
    ref_a_diff_author = {'title': 'Attention Is All You Need', 'authors': ['Noam Shazeer'], 'year': '2017'}
    assert cache.get(ref_a_diff_author) is None

    # But exact same normalized key hits
    ref_a_exact = {'title': '  attention is all you need  ', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    assert cache.get(ref_a_exact) is result_a


def test_verification_cache_skips_short_titles():
    cache = BulkVerificationCache()
    ref = {'title': 'Short', 'authors': ['A'], 'year': '2020'}
    cache.put(ref, 'should_not_store')
    assert cache.size == 0
    assert cache.get(ref) is None


def test_bulk_finalize_rechecks_against_llm_returned_match():
    reference = {
        'title': 'Membership inference attacks against language models via neighbourhood comparison',
        'authors': ['Justus Mattern', 'Fatemehsadat Mireshghallah'],
        'year': 2023,
        'venue': 'Findings of the Association for Computational Linguistics: ACL 2023',
    }
    error_entry = {
        'ref_title': reference['title'],
        'original_reference': reference,
        '_original_errors': [{'error_type': 'author', 'error_details': 'Wrong database match'}],
    }
    result = BulkPaperResult(
        index=0,
        input_spec='fixture://paper',
        paper_id='paper',
        title='Paper',
        source_url='fixture://paper',
        elapsed_seconds=1.0,
        references_processed=1,
        total_errors_found=1,
        total_warnings_found=0,
        total_info_found=0,
        total_unverified_refs=0,
        total_arxiv_refs=0,
        total_non_arxiv_refs=1,
        total_other_refs=0,
        papers_with_errors=1,
        papers_with_warnings=0,
        papers_with_info=0,
        errors=[error_entry],
    )
    assessment = {
        'verdict': 'LIKELY',
        'explanation': 'The checker matched a different paper, but search found this citation.',
        'link': 'https://aclanthology.org/2023.findings-acl.719/',
        'found_title': 'Membership Inference Attacks against Language Models via Neighbourhood Comparison',
        'found_authors': 'Justus Mattern, Fatemehsadat Mireshghallah',
        'found_venue': 'Findings of the Association for Computational Linguistics: ACL 2023',
        'found_year': '2023',
    }
    future = SimpleNamespace(result=lambda timeout=None: assessment)
    checker = SimpleNamespace(
        verify_reference_standard=MagicMock(return_value=(
            None,
            'https://aclanthology.org/2023.findings-acl.719/',
            {
                'title': 'Membership Inference Attacks against Language Models via Neighbourhood Comparison',
                'authors': [{'name': 'Justus Mattern'}, {'name': 'Fatemehsadat Mireshghallah'}],
                'venue': 'Findings of the Association for Computational Linguistics: ACL 2023',
                'year': 2023,
            },
        ))
    )

    _finalize_hallucination_on_result(result, [(checker, error_entry, future)])

    checker.verify_reference_standard.assert_not_called()
    assert result.errors[0]['hallucination_assessment']['verdict'] == 'UNLIKELY'
    assert result.errors[0]['hallucination_assessment']['original_verdict'] == 'LIKELY'
    assert result.errors[0]['matched_database'] == 'LLM search'


def test_bulk_finalize_removes_unverified_entry_resolved_by_llm_url():
    reference = {
        'title': 'Success and scientific realism: considerations from the philosophy of simulation',
        'authors': ['Eric Winsberg', 'Ali Mirza'],
        'year': 2017,
        'venue': 'The Routledge Handbook of Scientific Realism',
    }
    error_entry = {
        'ref_title': reference['title'],
        'original_reference': reference,
        '_original_errors': [
            {
                'error_type': 'unverified',
                'error_details': 'Paper not found by any checker',
            }
        ],
    }
    result = BulkPaperResult(
        index=0,
        input_spec='fixture://paper',
        paper_id='paper',
        title='Paper',
        source_url='fixture://paper',
        elapsed_seconds=1.0,
        references_processed=1,
        total_errors_found=0,
        total_warnings_found=0,
        total_info_found=0,
        total_unverified_refs=1,
        total_arxiv_refs=0,
        total_non_arxiv_refs=1,
        total_other_refs=0,
        papers_with_errors=0,
        papers_with_warnings=0,
        papers_with_info=0,
        errors=[error_entry],
    )
    assessment = {
        'verdict': 'UNLIKELY',
        'explanation': 'The cited book chapter exists.',
        'link': 'https://www.routledge.com/The-Routledge-Handbook-of-Scientific-Realism/Saatsi/p/book/9780367572556',
    }
    future = SimpleNamespace(result=lambda timeout=None: assessment)
    checker = SimpleNamespace(verify_reference_standard=MagicMock(return_value=(None, None, None)))

    _finalize_hallucination_on_result(result, [(checker, error_entry, future)])

    assert result.total_unverified_refs == 0
    assert result.errors == []