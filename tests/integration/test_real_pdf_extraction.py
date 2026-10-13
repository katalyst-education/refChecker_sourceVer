"""Real-document regression tests using the repository's academic paper."""

import asyncio
import logging
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.refchecker_wrapper import ProgressRefChecker
from refchecker.core.bulk_pipeline import (
    BulkLLMExtractionBatcher,
    extract_bibliography_bulk,
)
from refchecker.core.refchecker import (
    ArxivReferenceChecker,
    _AUTHOR_YEAR_ENTRY_START_RE,
)
from refchecker.services.pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACADEMIC_PDF = REPOSITORY_ROOT / "paper" / "paper.pdf"
ACADEMIC_BIB = REPOSITORY_ROOT / "paper" / "paper.bib"


def test_academic_pdf_selects_references_not_architecture_heading(monkeypatch):
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.text_extractors."
        "one_column_text_extractor.extract_grobid_metadata",
        lambda _pdf_path: {},
    )
    document = PDFProcessor().extract_document(
        str(ACADEMIC_PDF),
        include_bibliography=True,
    )
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )

    _, body_text, selected_bibliography = (
        checker._select_pdf_document_content(document)
    )
    expected_reference_count = len(
        re.findall(r"(?m)^\s*@", ACADEMIC_BIB.read_text(encoding="utf-8"))
    )
    detected_entries = _AUTHOR_YEAR_ENTRY_START_RE.findall(
        selected_bibliography
    )

    assert document.doc_type == "one_column_paper"
    assert len(document.pages) == 4
    assert selected_bibliography.startswith("Allen Institute for AI.")
    assert "localisation - heuristics detect section boundaries" not in (
        selected_bibliography
    )
    assert "localisation - heuristics detect section boundaries" in body_text
    assert len(detected_entries) == expected_reference_count == 6
    assert "Allen Institute for AI. 2024." not in body_text


def test_real_pdf_extraction_and_bibliography_selection_match_across_paths(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.text_extractors."
        "one_column_text_extractor.extract_grobid_metadata",
        lambda _pdf_path: {},
    )
    monkeypatch.setattr(
        "refchecker.utils.arxiv_utils.get_bibtex_content",
        lambda _paper: None,
    )
    monkeypatch.setattr(
        "refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    parser_inputs = []
    parse_references = ArxivReferenceChecker.parse_references

    def capture_parser_input(checker, bibliography_text, *args, **kwargs):
        parser_inputs.append(bibliography_text)
        return parse_references(checker, bibliography_text, *args, **kwargs)

    monkeypatch.setattr(
        ArxivReferenceChecker,
        "parse_references",
        capture_parser_input,
    )

    cache_dir = tmp_path / "cache"
    cli_checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
        cache_dir=str(cache_dir),
    )
    cli_paper = cli_checker._create_local_file_paper(str(ACADEMIC_PDF))
    assert not cli_paper.is_bibtex
    assert not cli_paper.is_latex
    assert not cli_paper.is_text_refs
    cli_references = cli_checker.extract_bibliography(cli_paper, debug_mode=False)
    cli_document = cli_checker.last_extracted_document
    _, cli_body, cli_bibliography = (
        cli_checker._select_pdf_document_content(cli_document)
    )

    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()
    (
        webui_document,
        webui_full_text,
        webui_body,
        webui_bibliography,
    ) = webui._extract_pdf_document_scoped(str(ACADEMIC_PDF))
    webui_references, webui_method = asyncio.run(
        webui._extract_references_from_pdf(
            str(ACADEMIC_PDF),
            webui_body,
            bibliography_text=webui_bibliography,
            full_text=webui_full_text,
        )
    )

    bulk_checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
        cache_dir=str(cache_dir / "bulk"),
    )
    bulk_checker.download_pdf = lambda _paper: BytesIO(ACADEMIC_PDF.read_bytes())
    bulk_paper = SimpleNamespace(
        title="Academic RefChecker",
        file_path=str(ACADEMIC_PDF),
        get_short_id=lambda: "academic-refchecker",
        is_latex=False,
        is_bibtex=False,
        is_text_refs=False,
    )
    bulk_references = extract_bibliography_bulk(
        bulk_checker,
        bulk_paper,
        debug_mode=False,
        extraction_batcher=BulkLLMExtractionBatcher(enabled=False),
    )
    _, bulk_body, bulk_bibliography = (
        bulk_checker._select_pdf_document_content(
            bulk_checker.last_extracted_document
        )
    )

    assert cli_document.doc_type == webui_document.doc_type == (
        bulk_checker.last_extracted_document.doc_type
    )
    assert cli_document.extractor == webui_document.extractor == (
        bulk_checker.last_extracted_document.extractor
    )
    assert cli_body == webui_body == bulk_body
    assert cli_bibliography == webui_bibliography == bulk_bibliography
    assert cli_document.full_text == webui_full_text == (
        bulk_checker.last_extracted_document.full_text
    )
    assert cli_bibliography in cli_document.full_text
    assert cli_references == bulk_references == webui_references
    assert len(cli_references) == 6
    assert webui_method == "regex"
    assert cli_checker.last_reference_parser_method == "regex"
    assert bulk_checker.last_reference_parser_method == "regex"
    assert len(parser_inputs) == 3
    assert parser_inputs == [
        cli_bibliography,
        webui_bibliography,
        bulk_bibliography,
    ]
    assert cli_checker.fatal_error is False
    assert cli_checker.fatal_error_message is None
    assert bulk_checker.fatal_error is False
    assert bulk_checker.fatal_error_message is None
    assert webui._last_reference_parse_error is None
    assert cli_checker.llm_extractor is None
    assert bulk_checker.llm_extractor is None
    assert all(
        checker._split_numbered_reference_entries(bibliography) == []
        for checker, bibliography in (
            (cli_checker, cli_bibliography),
            (bulk_checker, bulk_bibliography),
        )
    )
    for document in (
        cli_document,
        webui_document,
        bulk_checker.last_extracted_document,
    ):
        diagnostics = document.metadata.get("extraction_diagnostics", {})
        assert diagnostics["document_status"] == "complete"
        assert diagnostics["bibliography_status"] == "extracted"
        assert len(document.pages) == 4

    candidate_count = len(
        _AUTHOR_YEAR_ENTRY_START_RE.findall(cli_bibliography)
    )
    assert candidate_count == 6
    normalized_bibliography = re.sub(
        r"[^a-z0-9]", "", cli_bibliography.casefold()
    )
    source_references = cli_checker._parse_bibtex_references(
        ACADEMIC_BIB.read_text(encoding="utf-8")
    )
    assert len(source_references) == 6
    assert all(
        re.sub(r"[^a-z0-9]", "", reference["title"].casefold())
        in normalized_bibliography
        for reference in source_references
    )
    expected_titles = (
        "Semantic Scholar Academic Graph Api",
        "Crossref Rest Api",
        "RefChecker Reference Based Fine Grained Hallucination Checker and Benchmark for Large Language Models",
        "OpenAlex A Fully Open Index of Scholarly Works Authors Venues Institutions and Concepts",
        "Recite Reference Checker",
        "Scite Reference Check",
    )
    title_positions = [
        normalized_bibliography.index(
            re.sub(r"[^a-z0-9]", "", title.casefold())
        )
        for title in expected_titles
    ]
    assert title_positions == sorted(title_positions)
    assert "GROBID unavailable for offline validation" in caplog.text
    logger.info(
        "Real-PDF path diagnostics: layout=%s pages=%d extractor=%s "
        "body_chars=%d bibliography_chars=%d detected_entries=%d parsed_counts=%s "
        "grobid=unavailable",
        cli_document.doc_type,
        len(cli_document.pages),
        cli_document.extractor,
        len(cli_body),
        len(cli_bibliography),
        candidate_count,
        (len(cli_references), len(webui_references), len(bulk_references)),
    )


def _raise_grobid_unavailable(**_kwargs):
    raise ValueError("GROBID unavailable for offline validation")
