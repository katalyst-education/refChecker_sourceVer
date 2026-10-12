"""Integration tests for structured PDF extraction in the CLI checker."""

import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.services.pdf_pipeline import ExtractedDocument, PDFExtractionError
from refchecker.services.pdf_processor import PDFProcessor


BODY_TEXT = (
    "The manuscript discusses the method and results. "
    "Prior work is cited in this section [1]. "
) * 8
BIBLIOGRAPHY = (
    "[1] John Smith and Alice Jones. A robust method for scientific analysis. "
    "Journal of Testing, 2021.\n"
    "[2] Jane Doe and Bob Roe. An efficient approach to academic research. "
    "Conference Proceedings, 2022.\n"
    "[3] Alice Brown and Carol White. Improved models for reliable systems. "
    "Transactions on Testing, 2023."
)


def _checker_and_paper(tmp_path, suffix=".pdf"):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    pdf_path = tmp_path / f"paper{suffix}"
    pdf_path.write_bytes(b"not used by the mocked structured extractor")
    paper = checker._create_local_file_paper(str(pdf_path))
    return checker, paper


def _document(bibliography=BIBLIOGRAPHY, *, full_text=None, status="extracted"):
    full_text = full_text or f"{BODY_TEXT}\n\n## References\n{BIBLIOGRAPHY}"
    return ExtractedDocument(
        file="paper.pdf",
        doc_type="one_column_paper",
        extractor="test_pipeline",
        title="Test paper",
        body_text=BODY_TEXT,
        bibliography=bibliography,
        full_text=full_text,
        pages=[{"page_number": 1, "text": BODY_TEXT}],
        sections=[{"heading": "Introduction", "page_number": 1}],
        metadata={
            "extraction_diagnostics": {
                "document_status": "complete",
                "bibliography_status": status,
                "errors": [],
                "warnings": [],
            },
            "pdf_processor": {"pipeline": {"status": "succeeded"}},
        },
    )


@pytest.fixture
def no_grobid():
    with patch(
        "refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback",
        return_value=(None, None),
    ) as fallback:
        yield fallback


def _stub_pdf_input(checker, document):
    checker.download_pdf = Mock(return_value=io.BytesIO(b"pdf bytes"))
    checker.pdf_processor.extract_document = Mock(return_value=document)
    return checker.pdf_processor.extract_document


def test_pdf_pipeline_bibliography_flows_to_existing_parser_and_preserves_body(
    tmp_path, no_grobid
):
    checker, paper = _checker_and_paper(tmp_path)
    document = _document()
    pipeline = _stub_pdf_input(checker, document)

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        references = checker.extract_bibliography(paper)

    assert len(references) == 3
    assert [reference["entry_number"] for reference in references] == [1, 2, 3]
    assert checker.last_reference_parser_method == "regex"
    assert checker.last_extracted_document is document
    assert checker.last_paper_text == document.body_text
    assert "[1] John Smith" not in checker._paper_text_for_ai_detection(paper)
    assert BIBLIOGRAPHY in checker.last_extracted_document.full_text
    pipeline.assert_called_once_with(
        checker.download_pdf.return_value,
        include_bibliography=True,
    )
    no_grobid.assert_called_once()


def test_empty_structured_body_is_recovered_from_full_text_without_reextracting(
    tmp_path, no_grobid
):
    checker, paper = _checker_and_paper(tmp_path)
    document = _document()
    document.body_text = ""
    pipeline = _stub_pdf_input(checker, document)
    checker.parse_references = Mock(return_value=[{"title": "Parsed reference"}])

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        checker.extract_bibliography(paper)

    assert checker.last_paper_text
    assert "[1] John Smith" not in checker.last_paper_text
    assert checker._paper_text_for_ai_detection(paper) == checker.last_paper_text
    pipeline.assert_called_once()


def test_missing_pipeline_bibliography_uses_legacy_detection(tmp_path, no_grobid):
    checker, paper = _checker_and_paper(tmp_path)
    document = _document(
        bibliography="",
        status="not_found",
    )
    _stub_pdf_input(checker, document)
    parser = Mock(return_value=[{"title": "Parsed reference"}])
    checker.parse_references = parser

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        references = checker.extract_bibliography(paper)

    assert references == [{"title": "Parsed reference"}]
    parsed_bibliography = parser.call_args.args[0]
    assert "[1] John Smith" in parsed_bibliography
    assert "[3] Alice Brown" in parsed_bibliography


def test_pipeline_error_retries_existing_legacy_pdf_text_extraction(
    tmp_path, no_grobid, caplog
):
    checker, paper = _checker_and_paper(tmp_path)
    checker.download_pdf = Mock(return_value=io.BytesIO(b"pdf bytes"))
    checker.pdf_processor.extract_document = Mock(
        side_effect=PDFExtractionError(
            "both structured and processor fallback failed",
            {"errors": ["pipeline diagnostic"]},
        )
    )
    checker.extract_text_from_pdf = Mock(
        return_value=f"{BODY_TEXT}\n\nReferences\n{BIBLIOGRAPHY}"
    )
    checker.parse_references = Mock(return_value=[{"title": "Recovered reference"}])

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        references = checker.extract_bibliography(paper)

    assert references == [{"title": "Recovered reference"}]
    checker.extract_text_from_pdf.assert_called_once_with(
        checker.download_pdf.return_value
    )
    assert checker.last_extracted_document is None
    assert BODY_TEXT.strip() in checker.last_paper_text
    assert "[1] John Smith" not in checker.last_paper_text
    assert checker.parse_references.call_args.args[0].lstrip().startswith("[1]")
    assert "pipeline diagnostic" in caplog.text


def test_empty_structured_document_retries_existing_legacy_pdf_text_extraction(
    tmp_path, no_grobid
):
    checker, paper = _checker_and_paper(tmp_path)
    empty_document = _document(bibliography="", status="not_found")
    empty_document.body_text = ""
    empty_document.full_text = ""
    checker.download_pdf = Mock(return_value=io.BytesIO(b"pdf bytes"))
    checker.pdf_processor.extract_document = Mock(return_value=empty_document)
    checker.extract_text_from_pdf = Mock(
        return_value=f"{BODY_TEXT}\n\nReferences\n{BIBLIOGRAPHY}"
    )
    checker.parse_references = Mock(return_value=[{"title": "Recovered reference"}])

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        references = checker.extract_bibliography(paper)

    assert references == [{"title": "Recovered reference"}]
    checker.extract_text_from_pdf.assert_called_once()
    assert checker.last_extracted_document is None


def test_partial_pipeline_bibliography_recovers_broader_detected_text(
    tmp_path, no_grobid
):
    checker, paper = _checker_and_paper(tmp_path)
    partial = BIBLIOGRAPHY.splitlines()[0]
    document = _document(
        bibliography=partial,
        full_text=f"{BODY_TEXT}\n\n## References\n{BIBLIOGRAPHY}",
    )
    _stub_pdf_input(checker, document)
    checker.parse_references = Mock(return_value=[{"title": "Recovered reference"}])

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        checker.extract_bibliography(paper)

    parsed_bibliography = checker.parse_references.call_args.args[0]
    assert "[1] John Smith" in parsed_bibliography
    assert "[2] Jane Doe" in parsed_bibliography
    assert "[3] Alice Brown" in parsed_bibliography


def test_unvalidated_extra_numbered_markers_do_not_replace_pipeline_bibliography():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    detected = (
        "Body text [1] is cited here.\n\nReferences\n"
        "[1] this is not a reference\n"
        "[2] neither is this\n"
        "[3] and this is not one either"
    )
    pipeline_bibliography = "[1] this is not a reference"
    document = _document(
        bibliography=pipeline_bibliography,
        full_text=detected,
    )

    _, _, selected_bibliography = checker._select_pdf_document_content(document)

    assert selected_bibliography == pipeline_bibliography


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        (".bib", "@article{smith2021, title={A Test}, author={Smith, John}}"),
        (
            ".bbl",
            r"\begin{thebibliography}{1}\bibitem{smith2021} John Smith. A Test. 2021."
            r"\end{thebibliography}",
        ),
    ],
)
def test_source_bibliography_files_keep_priority_over_pdf_pipeline(
    tmp_path, suffix, content
):
    checker, paper = _checker_and_paper(tmp_path, suffix=suffix)
    checker.parse_references = Mock(return_value=[{"title": "Source reference"}])
    checker.pdf_processor.extract_document = Mock()
    checker.download_pdf = Mock()
    with patch(
        "refchecker.utils.arxiv_utils.get_bibtex_content",
        return_value=content,
    ):
        if suffix == ".bbl":
            with patch(
                "refchecker.core.refchecker.extract_latex_references",
                return_value=[{"title": "Source reference"}],
            ):
                references = checker.extract_bibliography(paper)
        else:
            references = checker.extract_bibliography(paper)

    assert references == [{"title": "Source reference"}]
    assert checker.last_extracted_document is None
    checker.pdf_processor.extract_document.assert_not_called()
    checker.download_pdf.assert_not_called()


def test_text_reference_input_keeps_existing_non_pdf_parser_path(tmp_path):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference_path = tmp_path / "references.txt"
    reference_path.write_text(BIBLIOGRAPHY, encoding="utf-8")
    paper = SimpleNamespace(
        file_path=str(reference_path),
        is_text_refs=True,
        title="Text reference input",
        get_short_id=lambda: "text-reference-input",
    )
    checker.parse_references = Mock(return_value=[{"title": "Text reference"}])
    checker.pdf_processor.extract_document = Mock()

    with patch("refchecker.utils.arxiv_utils.get_bibtex_content", return_value=None):
        references = checker.extract_bibliography(paper)

    assert references == [{"title": "Text reference"}]
    checker.pdf_processor.extract_document.assert_not_called()
    assert checker.last_bibliography_extraction_method == "text"


def test_pdf_processor_include_bibliography_views_do_not_share_stale_cache():
    processor = PDFProcessor()
    with_bibliography = _document()
    without_bibliography = _document()
    without_bibliography.full_text = BODY_TEXT
    pipeline = Mock(side_effect=[with_bibliography, without_bibliography])
    with patch(
        "refchecker.services.pdf_processor.extract_pdf",
        pipeline,
    ):
        included = processor.extract_document(
            b"pdf bytes",
            include_bibliography=True,
        )
        omitted = processor.extract_document(
            b"pdf bytes",
            include_bibliography=False,
        )

    assert BIBLIOGRAPHY in included.full_text
    assert BIBLIOGRAPHY not in omitted.full_text
    assert omitted.bibliography == BIBLIOGRAPHY
    assert [call.kwargs["include_bibliography"] for call in pipeline.call_args_list] == [
        True,
        False,
    ]
