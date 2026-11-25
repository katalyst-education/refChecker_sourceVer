"""Regression tests for the shared, validated PDF extraction cascade."""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.extraction_quality import ground_pdf_references, merge_grounded_reference_candidates
from refchecker.utils.reference_metadata import attach_bibliography_sources


def _checker():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.extraction_mode = 'cascade'
    checker.debug_mode = False
    checker.fatal_error = False
    checker.fatal_error_message = None
    checker.llm_extractor = None
    return checker


def _layout_document(monkeypatch, *pages):
    document = MagicMock()
    document.pages = [MagicMock() for _ in pages]
    for page, raw in zip(document.pages, pages):
        page.extract_text.return_value = raw
    document.__enter__.return_value = document
    open_pdf = MagicMock(return_value=document)
    monkeypatch.setattr('pdfplumber.open', open_pdf)
    return document, open_pdf


FIRST = '[1] H. Adams, “Solar absorber characterization,” Solar Energy, vol. 18, 2020.'
SECOND = '[2] A. Baker, “Thin film deposition,” Solar Energy, vol. 19, 2021.'
THIRD = '[3] J. Chen, “Crystalline interface measurements,” Solar Energy, vol. 20, 2022.'


def test_clean_bibliography_does_not_open_pdf_again(monkeypatch):
    checker = _checker()
    bibliography = '\n'.join([FIRST, SECOND, THIRD])
    references = checker._parse_references_regex(bibliography)
    _, open_pdf = _layout_document(monkeypatch, bibliography)

    assert ground_pdf_references(
        references, bibliography, bibliography_text=bibliography, pdf_path='sample.pdf',
    ) == references
    open_pdf.assert_not_called()
    assert all(row['extraction_provenance']['pdf_page'] == 1 for row in references)


@pytest.mark.parametrize('damage', ['merged', 'number_gap', 'parser_omission'])
def test_layout_recovers_numbered_entries_on_affected_page(monkeypatch, damage):
    checker = _checker()
    bibliography = {
        'merged': FIRST + ' ' + SECOND + '\n' + THIRD,
        'number_gap': FIRST + '\n' + THIRD,
        'parser_omission': '\n'.join([FIRST, SECOND, THIRD]),
    }[damage]
    layout = '\n'.join([FIRST, SECOND, THIRD])
    references = [
        row for row in checker._parse_references_regex(bibliography) if row['entry_number'] != 2
    ]
    document, open_pdf = _layout_document(monkeypatch, 'Body.', layout, 'Appendix.')

    ground_pdf_references(
        references, 'Body.\n\f\n' + bibliography + '\n\f\nAppendix.',
        bibliography_text=bibliography, pdf_path='sample.pdf',
    )

    assert [row['entry_number'] for row in references] == [1, 2, 3]
    repaired = references[1]
    assert repaired['title'] == 'Thin film deposition'
    assert repaired['extraction_provenance']['source_text'] == SECOND
    assert repaired['extraction_provenance']['layout_recovered']
    assert repaired['extraction_provenance']['pdf_page'] == 2
    if damage == 'merged':
        assert references[0]['year'] == 2020
        assert references[0]['raw_text'] == FIRST
        assert references[0]['extraction_provenance']['source_text'] == FIRST + ' ' + SECOND
    open_pdf.assert_called_once()
    document.pages[0].extract_text.assert_not_called()
    document.pages[2].extract_text.assert_not_called()


@pytest.mark.parametrize('layout', [
    FIRST + '\n' + THIRD,
    FIRST + '\n' + SECOND + '\n' + THIRD.replace('Crystalline interface', 'Another unrelated'),
    FIRST + '\n' + THIRD + '\n' + SECOND,
])
def test_gap_remains_when_layout_cannot_confirm_both_neighbors(monkeypatch, layout):
    checker = _checker()
    bibliography = FIRST + '\n' + THIRD
    references = checker._parse_references_regex(bibliography)
    _layout_document(monkeypatch, layout)

    ground_pdf_references(
        references, bibliography, bibliography_text=bibliography, pdf_path='sample.pdf',
    )

    assert [row['entry_number'] for row in references] == [1, 3]


@pytest.mark.parametrize('second_pass_repeats_label', [False, True])
def test_layout_only_deduplicates_when_the_pdf_has_one_entry(monkeypatch, second_pass_repeats_label):
    from copy import deepcopy

    checker = _checker()
    bibliography = '\n'.join([FIRST, SECOND, THIRD])
    references = checker._parse_references_regex(bibliography)
    references.insert(2, deepcopy(references[1]))
    layout = bibliography.replace(SECOND, SECOND + '\n' + SECOND) if second_pass_repeats_label else bibliography
    _layout_document(monkeypatch, layout)

    ground_pdf_references(
        references, bibliography, bibliography_text=bibliography, pdf_path='sample.pdf',
    )

    assert len(references) == (4 if second_pass_repeats_label else 3)


def test_layout_repairs_fused_title_with_same_source_text(monkeypatch):
    checker = _checker()
    glued = FIRST.replace('Solar absorber characterization', 'SolarAbsorberCharacterization')
    bibliography = '\n'.join([glued, SECOND, THIRD])
    references = checker._parse_references_regex(bibliography)
    _layout_document(monkeypatch, '\n'.join([FIRST, SECOND, THIRD]))

    ground_pdf_references(
        references, bibliography, bibliography_text=bibliography, pdf_path='sample.pdf',
    )

    assert references[0]['title'] == 'Solar absorber characterization'
    evidence = references[0]['extraction_provenance']
    assert evidence['source_text'] == glued
    assert evidence['layout_text'] == FIRST
    assert any(repair['field'] == 'title' and repair['reason'] == 'pdf_layout' for repair in evidence['repairs'])


def test_pdf_layout_recovers_a_citation_tail_on_the_following_page(monkeypatch):
    checker = _checker()
    truncated = FIRST.split('vol.')[0].rstrip()
    bibliography = '\n'.join([truncated, SECOND, THIRD])
    references = checker._parse_references_regex(bibliography)
    _layout_document(monkeypatch, truncated, '\n'.join(['vol. 18, 2020.', SECOND, THIRD]))
    paper_text = truncated + '\n\f\n' + SECOND + '\n' + THIRD

    ground_pdf_references(
        references, paper_text, bibliography_text=bibliography, pdf_path='sample.pdf',
    )

    assert references[0]['year'] == 2020
    assert references[0]['extraction_provenance']['pdf_page'] == 1
    assert references[0]['extraction_provenance']['layout_text'].endswith('vol. 18, 2020.')


@pytest.mark.parametrize('both_spellings', [False, True])
def test_pdf_wraps_use_intact_source_spellings(monkeypatch, both_spellings):
    raw = FIRST.replace('Solar absorber characterization', 'Kinetics of amor-\nphous films in non-\nempty layers')
    body = 'The amorphous samples have a non-empty layer.'
    if both_spellings:
        body += ' A table also uses amor-phous.'
    checker = _checker()
    references = checker._parse_references_regex(raw)
    _, open_pdf = _layout_document(monkeypatch, raw)
    paper_text = body + '\n\f\nReferences\n' + raw

    ground_pdf_references(references, paper_text, bibliography_text=raw, pdf_path='sample.pdf')
    ground_pdf_references(references, paper_text, bibliography_text=raw, pdf_path='sample.pdf')

    [reference] = references
    material = 'amor-phous' if both_spellings else 'amorphous'
    assert reference['title'] == f'Kinetics of {material} films in non-empty layers'
    evidence = reference['extraction_provenance']
    assert evidence['source_text'] == raw
    assert reference['raw_text'] == raw
    assert len([repair for repair in evidence['repairs'] if repair['field'] == 'title']) == 1
    open_pdf.assert_not_called()


def test_full_pdf_and_selected_reextraction_share_the_same_recovery(monkeypatch, tmp_path):
    from backend.refchecker_wrapper import ProgressRefChecker
    from refchecker.core.bulk_pipeline import extract_bibliography_bulk
    from refchecker.utils.reference_metadata import cited_metadata_snapshot

    fourth = '[4] L. Diaz, “Solar diffusion measurements,” Solar Energy, vol. 21, 2023.'
    paper_text = 'Introduction\nBody text.\n\nReferences\n' + '\n'.join([FIRST + ' ' + SECOND, THIRD, fourth])
    _layout_document(monkeypatch, '\n'.join([FIRST, SECOND, THIRD, fourth]))
    monkeypatch.setattr('refchecker.utils.arxiv_utils.get_bibtex_content', lambda _paper: None)
    monkeypatch.setattr('refchecker.core.bulk_pipeline.get_bibtex_content', lambda _paper: None)
    monkeypatch.setattr('refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback',
                        lambda **_kwargs: (None, None))
    monkeypatch.setattr('backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback',
                        lambda **_kwargs: (None, None))
    paper = SimpleNamespace(get_short_id=lambda: 'pdf-layout', title='Sample', file_path=str(tmp_path / 'sample.pdf'))

    def local_checker():
        checker = _checker()
        checker.cache_dir = None
        checker.extract_text_from_pdf = lambda _pdf: paper_text
        checker.download_pdf = lambda _paper: io.BytesIO(b'%PDF')
        return checker

    cli = local_checker().extract_bibliography(paper)
    bulk = extract_bibliography_bulk(local_checker(), paper, False, None)
    web = ProgressRefChecker.__new__(ProgressRefChecker)
    web.llm = None
    web.extraction_mode = 'cascade'
    web.check_id = None
    web.cancel_event = None
    web.progress_callback = None
    web_refs, _ = asyncio.run(web._extract_references_from_pdf(paper.file_path, paper_text))
    selected, failures = asyncio.run(web._extract_references_for_reverification(
        paper_text, [2], pdf_path=paper.file_path,
    ))
    assert failures == []
    for refs in (cli, bulk, web_refs):
        assert [ref['entry_number'] for ref in refs] == [1, 2, 3, 4]
        assert cited_metadata_snapshot(refs[1]) == cited_metadata_snapshot(selected[0])
        assert refs[1]['extraction_provenance'] == selected[0]['extraction_provenance']


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


@pytest.mark.parametrize('printed_author', ['R. A. Marques Lameirinhas', 'T. A. Marques Lameirinhas'])
def test_alternate_pdf_layout_repairs_spacing_or_preserves_conflicting_evidence(monkeypatch, printed_author):
    raw = '[49] R.A.MarquesLameirinhas, “A photovoltaic technology review,” Energies, 2022.'
    layout = raw.replace('R.A.MarquesLameirinhas', printed_author)
    parsed = {'entry_number': 49, 'title': 'A photovoltaic technology review',
              'authors': ['R.A.MarquesLameirinhas']}
    references = attach_bibliography_sources([parsed], raw, 'regex')
    document = MagicMock()
    document.pages = [MagicMock(), MagicMock()]
    document.pages[1].extract_text.return_value = layout
    document.__enter__.return_value = document
    monkeypatch.setattr('pdfplumber.open', lambda _path: document)

    [reference] = ground_pdf_references(references, 'Introduction\n\f\n' + raw, pdf_path='paper.pdf')

    evidence = reference['extraction_provenance']
    assert evidence['pdf_page'] == 2
    assert evidence['source_text'] == raw
    assert evidence['layout_text'] == layout
    document.pages[0].extract_text.assert_not_called()
    if printed_author.startswith('R.'):
        assert reference['authors'] == [printed_author]
        assert evidence['repairs'][0]['reason'] == 'pdf_layout'
        assert not evidence.get('review')
    else:
        assert reference['authors'] == ['R.A.MarquesLameirinhas']
        assert evidence['review']['authors']['source'] == printed_author
