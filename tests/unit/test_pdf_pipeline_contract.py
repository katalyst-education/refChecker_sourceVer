"""Contract tests for structured PDF extraction output."""

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import pytest

from refchecker.services.pdf_pipeline import (
    ExtractedDocument,
    PDFExtractionError,
    extract_pdf,
)
from refchecker.services.pdf_pipeline.models import build_extraction_diagnostics
from refchecker.services.pdf_pipeline.text_extractors import (
    fallback_text_extractor as fallback_module,
    one_column_text_extractor as one_column_module,
    two_column_text_extractor as two_column_module,
)
from refchecker.services.pdf_pipeline.text_extractors import paper_helpers
from refchecker.services.pdf_pipeline.text_extractors.fallback_text_extractor import (
    FallbackTextExtractor,
)
from refchecker.services.pdf_pipeline.text_extractors.one_column_text_extractor import (
    OneColumnTextExtractor,
)
from refchecker.services.pdf_pipeline.text_extractors.paper_helpers import (
    assemble_document_text,
    extraction_diagnostics_from_references,
    split_text_and_references,
)
from refchecker.services.pdf_pipeline.text_extractors.two_column_text_extractor import (
    TwoColumnTextExtractor,
)


BODY_TEXT = "The extraction contract preserves each body sentence. " * 50
BIBLIOGRAPHY = (
    "[1] Alice Smith. First Reference Title. 2024.\n"
    "[2] Bob Jones. Second Reference Title. 2023."
)
PAPER_TEXT = f"{BODY_TEXT}\n## References\n{BIBLIOGRAPHY}"


def test_extracted_document_keeps_legacy_constructor_and_serialization_shape():
    document = ExtractedDocument(
        "paper.pdf",
        "one_column_paper",
        "test",
        "Paper title",
        "Abstract",
        ["keyword"],
        "Body",
        "References",
        "Complete text",
    )

    assert document.body_text == "Body"
    assert document.bibliography == "References"
    assert document.full_text == "Complete text"
    assert list(document.to_dict()) == [
        "file",
        "doc_type",
        "extractor",
        "title",
        "abstract",
        "author_keywords",
        "body_text",
        "bibliography",
        "full_text",
        "sections",
        "pages",
        "metadata",
    ]


def test_reference_split_exposes_bibliography_separately():
    body, bibliography, debug = split_text_and_references(PAPER_TEXT)
    diagnostics = extraction_diagnostics_from_references(
        debug,
        bibliography,
        extractor="contract-test",
    )

    assert body.strip() == BODY_TEXT.strip()
    assert "[1]" not in body
    assert bibliography == BIBLIOGRAPHY
    assert diagnostics["document_status"] == "complete"
    assert diagnostics["bibliography_status"] == "extracted"


def test_reference_split_finds_early_long_numbered_bibliography():
    bibliography = "\n".join(
        f"[{index}] Author {index}. Reference title with enough detail. "
        f"Journal of Testing, 20{index % 25:02d}."
        for index in range(1, 121)
    )
    text = f"Short article body.\nReferences\n{bibliography}"

    body, found_bibliography, debug = split_text_and_references(text)

    assert len(text[:text.index("References")]) / len(text) < 0.60
    assert body == "Short article body."
    assert found_bibliography == bibliography
    assert "[120]" in found_bibliography
    assert debug["references_found"] is True


def test_reference_split_supports_author_year_bibliographies():
    text = (
        "Short paper body.\nBibliography\n"
        "Smith, J. (2020). A first reference title. Journal One.\n"
        "Jones, A. and Lee, B. (2021). A second reference title. Journal Two.\n"
        "Taylor, C. (2022). A third reference title. Journal Three."
    )

    body, bibliography, debug = split_text_and_references(text)

    assert body == "Short paper body."
    assert bibliography.startswith("Smith, J. (2020)")
    assert bibliography.endswith("Journal Three.")
    assert debug["references_found"] is True


def test_reference_split_keeps_appendices_out_of_bibliography():
    text = (
        "Paper body.\nReferences\n"
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. 2023.\n"
        "Appendix A: Additional proof\n"
        "The proof remains part of the document body."
    )

    body, bibliography, debug = split_text_and_references(text)
    body_without_references, full_text = assemble_document_text(
        body,
        bibliography,
        True,
        debug,
    )

    assert bibliography.endswith("[2] Bob Jones. Second reference. 2023.")
    assert "Appendix A: Additional proof" in body_without_references
    assert "Appendix A: Additional proof" not in bibliography
    assert full_text.index("[2] Bob Jones") < full_text.index("Appendix A")
    assert body_without_references.index("Appendix A") < len(body_without_references)


def test_reference_heading_without_bibliographic_evidence_is_not_accepted():
    text = (
        "Short article body.\nReferences\n"
        "Introduction to the next chapter\n"
        "Methods and discussion continue here."
    )

    body, bibliography, debug = split_text_and_references(text)

    assert body == text.strip()
    assert bibliography == ""
    assert debug["references_found"] is False
    assert debug["references_split_reason"] == "reference_heading_not_verified"


def test_reference_split_ignores_early_toc_heading_when_real_heading_follows():
    bibliography = (
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. 2023."
    )
    text = (
        "Contents\nReferences\nIntroduction continues with citation [7].\n"
        "The main body discusses several papers from 2020.\n"
        + ("More body text. " * 30)
        + "\nReferences\n"
        + bibliography
    )

    body, found_bibliography, debug = split_text_and_references(text)

    assert body.startswith("Contents\nReferences")
    assert "The main body discusses" in body
    assert found_bibliography == bibliography
    assert debug["references_candidate_positions"][-1] > 0.60


def test_no_detected_heading_is_distinct_from_detection_failure():
    body, bibliography, debug = split_text_and_references(BODY_TEXT)
    diagnostics = extraction_diagnostics_from_references(
        debug,
        bibliography,
        extractor="contract-test",
    )

    assert body == BODY_TEXT.strip()
    assert bibliography == ""
    assert diagnostics["bibliography_status"] == "not_found"
    assert diagnostics["reason"] == "no_reference_heading_found"

    failed_detection = extraction_diagnostics_from_references(
        None,
        "",
        extractor="contract-test",
        errors=["splitter unavailable"],
    )
    assert failed_detection["document_status"] == "partial"
    assert failed_detection["bibliography_status"] == "detection_failed"


def test_extracted_document_diagnostics_are_additive_metadata():
    diagnostics = build_extraction_diagnostics(
        bibliography_status="not_found",
        extractor="fallback",
        reason="no_reference_heading_found",
    )
    document = ExtractedDocument(
        file="paper.pdf",
        doc_type="unknown",
        extractor="fallback",
        body_text=BODY_TEXT,
        full_text=BODY_TEXT,
        metadata={"extraction_diagnostics": diagnostics},
    )

    serialized = document.to_dict()
    assert serialized["metadata"]["extraction_diagnostics"] == diagnostics
    assert "extraction_diagnostics" not in serialized


def _fallback_extractor(monkeypatch, pages):
    class Reader:
        def __init__(self, _path):
            self.pages = pages

    monkeypatch.setattr(fallback_module, "PdfReader", Reader)
    return FallbackTextExtractor()


class _TextPage:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error

    def extract_text(self, extraction_mode=None):
        if self.error:
            raise self.error
        return self.text


@pytest.mark.parametrize("include_bibliography", [False, True])
def test_fallback_extractor_obeys_body_bibliography_and_full_text_contract(
    monkeypatch, tmp_path, include_bibliography
):
    extractor = _fallback_extractor(
        monkeypatch,
        [_TextPage(PAPER_TEXT)],
    )

    document = extractor.extract(
        tmp_path / "paper.pdf",
        "unknown",
        include_bibliography=include_bibliography,
    )

    assert document.body_text.strip() == BODY_TEXT.strip()
    assert document.bibliography == BIBLIOGRAPHY
    if include_bibliography:
        assert document.full_text.endswith(BIBLIOGRAPHY)
    else:
        assert document.full_text == document.body_text
        assert "[1]" not in document.full_text
    assert (
        document.metadata["extraction_diagnostics"]["bibliography_status"]
        == "extracted"
    )


def test_fallback_extractor_reports_not_found_without_claiming_detection_failure(
    monkeypatch, tmp_path
):
    extractor = _fallback_extractor(monkeypatch, [_TextPage(BODY_TEXT)])
    document = extractor.extract(tmp_path / "paper.pdf", "unknown")

    assert document.body_text == BODY_TEXT.strip()
    assert document.bibliography == ""
    assert document.full_text == document.body_text
    assert (
        document.metadata["extraction_diagnostics"]["bibliography_status"]
        == "not_found"
    )


def test_fallback_extractor_marks_partial_page_extraction(monkeypatch, tmp_path):
    extractor = _fallback_extractor(
        monkeypatch,
        [
            _TextPage(BODY_TEXT),
            _TextPage(error=OSError("page stream is unreadable")),
        ],
    )
    document = extractor.extract(tmp_path / "paper.pdf", "unknown")
    diagnostics = document.metadata["extraction_diagnostics"]

    assert document.body_text == BODY_TEXT.strip()
    assert diagnostics["document_status"] == "partial"
    assert diagnostics["failed_pages"] == [2]
    assert "page stream is unreadable" in diagnostics["errors"][0]


def test_fallback_extractor_keeps_pages_when_a_page_object_cannot_be_loaded(
    monkeypatch, tmp_path
):
    class BrokenPageList:
        def __len__(self):
            return 2

        def __getitem__(self, index):
            if index == 0:
                return _TextPage(BODY_TEXT)
            raise ValueError("page object is malformed")

    class Reader:
        def __init__(self, _path):
            self.pages = BrokenPageList()

    monkeypatch.setattr(fallback_module, "PdfReader", Reader)

    document = FallbackTextExtractor().extract(
        tmp_path / "paper.pdf",
        "unknown",
    )

    assert document.body_text == BODY_TEXT.strip()
    assert document.metadata["extraction_diagnostics"]["document_status"] == "partial"
    assert document.metadata["extraction_diagnostics"]["failed_pages"] == [2]


def test_fallback_extractor_surfaces_total_extraction_failure(monkeypatch, tmp_path):
    extractor = _fallback_extractor(
        monkeypatch,
        [_TextPage(error=OSError("broken page"))],
    )

    with pytest.raises(PDFExtractionError) as error:
        extractor.extract(tmp_path / "paper.pdf", "unknown")

    assert error.value.diagnostics["document_status"] == "failed"
    assert (
        error.value.diagnostics["bibliography_status"]
        == "extraction_failed"
    )
    assert error.value.diagnostics["failed_pages"] == [1]


def test_fallback_extractor_preserves_text_when_bibliography_detection_fails(
    monkeypatch, tmp_path
):
    extractor = _fallback_extractor(monkeypatch, [_TextPage(PAPER_TEXT)])
    monkeypatch.setattr(
        fallback_module,
        "split_text_and_references",
        lambda _text: (_ for _ in ()).throw(RuntimeError("split failed")),
    )

    with pytest.raises(PDFExtractionError) as error:
        extractor.extract(tmp_path / "paper.pdf", "unknown")

    assert error.value.diagnostics["document_status"] == "partial"
    assert (
        error.value.diagnostics["bibliography_status"]
        == "detection_failed"
    )
    assert error.value.extracted_text == PAPER_TEXT


def test_fallback_extractor_wraps_malformed_pdf_as_diagnostic_error(
    monkeypatch, tmp_path
):
    class BrokenReader:
        def __init__(self, _path):
            raise ValueError("malformed xref table")

    monkeypatch.setattr(fallback_module, "PdfReader", BrokenReader)

    with pytest.raises(PDFExtractionError, match="could not read") as error:
        FallbackTextExtractor().extract(tmp_path / "broken.pdf", "unknown")

    assert error.value.diagnostics["document_status"] == "failed"
    assert "malformed xref table" in error.value.diagnostics["errors"][0]


def _run_mocked_paper_extractor(module, extractor, include_bibliography):
    source_pages = [{"page_number": 1, "blocks": []}]
    fake_paper = {
        "text": PAPER_TEXT,
        "pages": source_pages,
        "section_headings": [],
    }
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                module,
                "extract_grobid_metadata",
                return_value={
                    "title": "Paper title",
                    "abstract": "",
                    "author_keywords": [],
                    "grobid_error": "disabled in test",
                },
            )
        )
        extraction_function = (
            "extract_pages_text_char_based"
            if module is one_column_module
            else "extract_blocks_from_two_column_pdf"
        )
        stack.enter_context(
            patch.object(module, extraction_function, return_value=source_pages)
        )
        stack.enter_context(
            patch.object(module, "find_repeated_paper_blocks", return_value=set())
        )
        stack.enter_context(
            patch.object(
                module,
                "remove_repeated_paper_blocks",
                side_effect=lambda pages, _repeated: pages,
            )
        )
        stack.enter_context(
            patch.object(
                module,
                "trim_pages_to_first_body_heading",
                side_effect=lambda pages: (pages, {}),
            )
        )
        stack.enter_context(
            patch.object(module, "build_clean_paper_text", return_value=fake_paper)
        )
        return extractor.extract(
            Path("paper.pdf"),
            "one_column_paper"
            if module is one_column_module
            else "two_column_paper",
            include_bibliography=include_bibliography,
        )


@pytest.mark.parametrize(
    ("module", "extractor"),
    [
        (one_column_module, OneColumnTextExtractor()),
        (two_column_module, TwoColumnTextExtractor()),
    ],
)
@pytest.mark.parametrize("include_bibliography", [False, True])
def test_paper_extractors_preserve_bibliography_and_apply_include_flag(
    module, extractor, include_bibliography
):
    document = _run_mocked_paper_extractor(
        module,
        extractor,
        include_bibliography,
    )

    assert document.body_text.startswith("Paper title")
    assert document.body_text.strip().endswith(BODY_TEXT.strip())
    assert document.bibliography == BIBLIOGRAPHY
    if include_bibliography:
        assert document.full_text.endswith(BIBLIOGRAPHY)
    else:
        assert document.full_text == document.body_text
        assert "[1]" not in document.full_text
    assert (
        document.metadata["extraction_diagnostics"]["bibliography_status"]
        == "extracted"
    )
    assert any(
        "GROBID metadata extraction failed" in warning
        for warning in document.metadata["extraction_diagnostics"]["warnings"]
    )


@pytest.mark.parametrize(
    "extractor",
    [OneColumnTextExtractor(), TwoColumnTextExtractor()],
)
def test_existing_extractor_signatures_accept_include_bibliography(extractor):
    import inspect

    assert "include_bibliography" in inspect.signature(extractor.extract).parameters


def test_pipeline_wraps_classifier_failure_with_extraction_diagnostics(monkeypatch):
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.api.classify_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad PDF")),
    )

    with pytest.raises(PDFExtractionError) as error:
        extract_pdf(b"%PDF-1.7 test input")

    assert error.value.diagnostics["document_status"] == "failed"
    assert (
        error.value.diagnostics["bibliography_status"]
        == "extraction_failed"
    )
    assert any(
        "bad PDF" in detail
        for detail in error.value.diagnostics["errors"]
    )


def _make_pdf_bytes(text="PDF extraction input"):
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.mark.parametrize("source_kind", ["path", "bytes", "bytearray", "bytesio"])
def test_api_supports_pdf_source_forms_and_repeated_extraction(
    monkeypatch, tmp_path, source_kind
):
    import refchecker.services.pdf_pipeline.api as api_module

    pdf_bytes = _make_pdf_bytes()
    monkeypatch.setattr(
        api_module,
        "classify_pdf",
        lambda *_args, **_kwargs: {"type": "unknown", "confidence": "low"},
    )
    temp_paths = []
    original_mkstemp = tempfile.mkstemp

    def track_temp_file(*args, **kwargs):
        result = original_mkstemp(*args, **kwargs)
        temp_paths.append(Path(result[1]))
        return result

    monkeypatch.setattr(api_module.tempfile, "mkstemp", track_temp_file)

    if source_kind == "path":
        source = tmp_path / "input.pdf"
        source.write_bytes(pdf_bytes)
    elif source_kind == "bytes":
        source = pdf_bytes
    elif source_kind == "bytearray":
        source = bytearray(pdf_bytes)
    else:
        source = BytesIO(pdf_bytes)
        source.seek(7)

    first = extract_pdf(source)
    second = extract_pdf(source)

    assert "PDF extraction input" in first.body_text
    assert second.body_text == first.body_text
    if source_kind == "bytesio":
        assert source.tell() == 7
    assert all(not path.exists() for path in temp_paths)


def test_api_uses_fallback_after_classifier_failure_and_reports_it(monkeypatch):
    import refchecker.services.pdf_pipeline.api as api_module

    document = ExtractedDocument(
        file="paper.pdf",
        doc_type="unknown",
        extractor="fallback",
        body_text="Extracted locally",
        full_text="Extracted locally",
    )

    class Router:
        def __init__(self):
            self.fallback_extractor = Fallback()

        def extract(self, _path, _doc_type, *, include_bibliography):
            return self.fallback_extractor.extract(
                None, "unknown",
                include_bibliography=include_bibliography,
            )

    class Fallback:
        def extract(self, *_args, **_kwargs):
            return document

    router = Router()
    monkeypatch.setattr(
        api_module,
        "classify_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("classifier unavailable")
        ),
    )
    monkeypatch.setattr(api_module, "TextExtractorRouter", lambda: router)

    result = extract_pdf(b"%PDF-1.7")

    assert result.body_text == "Extracted locally"
    assert result.metadata["classification"]["type"] == "unknown"
    diagnostics = result.metadata["extraction_diagnostics"]
    assert diagnostics["document_status"] == "partial"
    assert diagnostics["classification"] == result.metadata["classification"]
    assert any("classifier unavailable" in error for error in diagnostics["errors"])


def test_api_reports_malformed_pdf_after_classifier_and_fallback_failures(
    monkeypatch,
):
    import refchecker.services.pdf_pipeline.api as api_module

    monkeypatch.setattr(
        api_module,
        "classify_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("classifier cannot read document")
        ),
    )

    with pytest.raises(PDFExtractionError, match="PDF extraction failed") as error:
        extract_pdf(b"not a valid PDF")

    diagnostics = error.value.diagnostics
    assert diagnostics["document_status"] == "failed"
    assert diagnostics["bibliography_status"] == "extraction_failed"
    assert any(
        "classifier cannot read document" in detail
        for detail in diagnostics["errors"]
    )
    assert any(
        "Could not open PDF for fallback extraction" in detail
        for detail in diagnostics["errors"]
    )


def test_api_retries_failed_classified_extractor_with_local_fallback(monkeypatch):
    import refchecker.services.pdf_pipeline.api as api_module

    document = ExtractedDocument(
        file="paper.pdf",
        doc_type="unknown",
        extractor="fallback",
        body_text="Fallback text",
        full_text="Fallback text",
    )

    class Fallback:
        def extract(self, *_args, **_kwargs):
            return document

    class Router:
        fallback_extractor = Fallback()

        def extract(self, *_args, **_kwargs):
            raise RuntimeError("PyMuPDF extractor failed")

    monkeypatch.setattr(
        api_module,
        "classify_pdf",
        lambda *_args, **_kwargs: {"type": "one_column_paper"},
    )
    monkeypatch.setattr(api_module, "TextExtractorRouter", Router)

    result = extract_pdf(b"%PDF-1.7")

    assert result.body_text == "Fallback text"
    diagnostics = result.metadata["extraction_diagnostics"]
    assert diagnostics["document_status"] == "partial"
    assert diagnostics["extractor"] == "fallback"
    assert any("PyMuPDF extractor failed" in error for error in diagnostics["errors"])


def test_grobid_metadata_uses_configured_url_and_short_timeout(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")
    response = type(
        "Response",
        (),
        {
            "text": (
                '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
                "<teiHeader><fileDesc><titleStmt>"
                "<title>Configured title</title>"
                "</titleStmt></fileDesc></teiHeader></TEI>"
            ),
            "raise_for_status": lambda self: None,
        },
    )()
    post = Mock(return_value=response)
    monkeypatch.setattr(paper_helpers, "USE_GROBID_METADATA", True)
    monkeypatch.setattr(
        paper_helpers,
        "GROBID_URL",
        "http://grobid-service:8070/api/processFulltextDocument",
    )
    monkeypatch.setattr(paper_helpers, "GROBID_METADATA_TIMEOUT", 3)
    monkeypatch.setattr(paper_helpers.requests, "post", post)

    metadata = paper_helpers.extract_grobid_metadata(pdf_path)

    assert metadata["title"] == "Configured title"
    post.assert_called_once()
    assert post.call_args.args[0] == (
        "http://grobid-service:8070/api/processFulltextDocument"
    )
    assert post.call_args.kwargs["timeout"] == 3


def test_two_column_references_keep_column_and_page_order(monkeypatch):
    def block(text, x0, y0, x1, y1):
        return {
            "text": text,
            "page_number": 1,
            "page_width": 600,
            "page_height": 800,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "width": x1 - x0,
            "height": y1 - y0,
            "max_font_size": 10,
            "avg_font_size": 10,
            "font_names": [],
            "flags": [],
        }

    first_page_blocks = [
        block("Body in the left column.", 50, 100, 270, 130),
        block("## References", 50, 590, 550, 620),
        block(
            "[1] First reference. 2024.\n[2] Second reference. 2023.",
            50,
            635,
            270,
            705,
        ),
        block(
            "[3] Third reference. 2022.\n[4] Fourth reference. 2021.",
            320,
            100,
            550,
            175,
        ),
    ]
    second_page_blocks = [
        block(
            "[5] Fifth reference. 2020.\n[6] Sixth reference. 2019.",
            50,
            100,
            270,
            175,
        ),
        block(
            "[7] Seventh reference. 2018.\n[8] Eighth reference. 2017.",
            320,
            100,
            550,
            175,
        ),
    ]
    pages = [
        {
            "page_number": 1,
            "page_width": 600,
            "page_height": 800,
            "blocks": two_column_module.order_two_column_blocks(
                first_page_blocks, 600, 800, 1
            ),
        },
        {
            "page_number": 2,
            "page_width": 600,
            "page_height": 800,
            "blocks": two_column_module.order_two_column_blocks(
                second_page_blocks, 600, 800, 2
            ),
        },
    ]
    monkeypatch.setattr(
        two_column_module,
        "extract_blocks_from_two_column_pdf",
        lambda _path: pages,
    )
    monkeypatch.setattr(
        two_column_module,
        "extract_grobid_metadata",
        lambda _path: {
            "title": "Paper title",
            "abstract": "",
            "author_keywords": [],
            "grobid_error": "GROBID unavailable",
        },
    )
    monkeypatch.setattr(
        two_column_module,
        "find_repeated_paper_blocks",
        lambda _pages, **_kwargs: set(),
    )
    monkeypatch.setattr(
        two_column_module,
        "trim_pages_to_first_body_heading",
        lambda source_pages: (source_pages, {}),
    )

    document = TwoColumnTextExtractor().extract(
        Path("paper.pdf"),
        "two_column_paper",
        include_bibliography=True,
    )

    ordered_ids = [
        f"[{index}]"
        for index in range(1, 9)
    ]
    positions = [
        document.bibliography.index(reference_id)
        for reference_id in ordered_ids
    ]
    assert positions == sorted(positions)
    assert "Body in the left column." in document.body_text
    assert all(reference_id not in document.body_text for reference_id in ordered_ids)
    assert document.full_text.index("[8]") > document.full_text.index("[1]")
    assert any(
        "GROBID metadata extraction failed" in warning
        for warning in document.metadata["extraction_diagnostics"]["warnings"]
    )


def test_real_two_column_pdf_preserves_references_across_columns_and_pages(
    monkeypatch, tmp_path
):
    import pymupdf

    pdf_path = tmp_path / "two-column.pdf"
    pdf = pymupdf.open()
    first_page = pdf.new_page(width=600, height=800)
    first_page.insert_text((50, 100), "Paper title", fontsize=16)
    first_page.insert_textbox(
        pymupdf.Rect(50, 150, 280, 350),
        "Left column body text.",
        fontsize=10,
    )
    first_page.insert_textbox(
        pymupdf.Rect(320, 150, 550, 350),
        "Right column body text.",
        fontsize=10,
    )
    for page_number, start_number in ((2, 1), (3, 9)):
        page = pdf.new_page(width=600, height=800)
        if page_number == 2:
            page.insert_text((50, 70), "References", fontsize=12)
        left_entries = "\n".join(
            f"[{index}] Left reference {index}. 20{index:02d}."
            for index in range(start_number, start_number + 4)
        )
        right_entries = "\n".join(
            f"[{index}] Right reference {index}. 20{index:02d}."
            for index in range(start_number + 4, start_number + 8)
        )
        page.insert_textbox(
            pymupdf.Rect(50, 100, 280, 500),
            left_entries,
            fontsize=10,
        )
        page.insert_textbox(
            pymupdf.Rect(320, 100, 550, 500),
            right_entries,
            fontsize=10,
        )
    pdf.save(pdf_path)
    pdf.close()

    monkeypatch.setattr(
        two_column_module,
        "extract_grobid_metadata",
        lambda _path: {
            "title": "Paper title",
            "abstract": "",
            "author_keywords": [],
            "grobid_error": "GROBID unavailable",
        },
    )
    monkeypatch.setattr(
        two_column_module,
        "trim_pages_to_first_body_heading",
        lambda pages: (pages, {}),
    )

    document = TwoColumnTextExtractor().extract(
        pdf_path,
        "two_column_paper",
        include_bibliography=True,
    )

    reference_ids = [f"[{index}]" for index in range(1, 17)]
    offsets = [document.bibliography.index(item) for item in reference_ids]
    assert offsets == sorted(offsets)
    assert "Left column body text." in document.body_text
    assert "Right column body text." in document.body_text
    assert all(item not in document.body_text for item in reference_ids)
    assert all(item in document.full_text for item in reference_ids)


def test_real_one_column_pdf_extracts_body_and_bibliography(monkeypatch, tmp_path):
    import pymupdf

    pdf_path = tmp_path / "one-column.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((70, 70), "Paper title", fontsize=16)
    page.insert_textbox(
        pymupdf.Rect(70, 110, 530, 470),
        BODY_TEXT,
        fontsize=10,
    )
    page.insert_text((70, 510), "References", fontsize=12)
    page.insert_textbox(
        pymupdf.Rect(70, 535, 530, 650),
        BIBLIOGRAPHY,
        fontsize=10,
    )
    pdf.save(pdf_path)
    pdf.close()
    monkeypatch.setattr(
        one_column_module,
        "extract_grobid_metadata",
        lambda _path: {
            "title": "Paper title",
            "abstract": "",
            "author_keywords": [],
            "grobid_error": "GROBID unavailable",
        },
    )
    monkeypatch.setattr(
        one_column_module,
        "trim_pages_to_first_body_heading",
        lambda pages: (pages, {}),
    )

    document = OneColumnTextExtractor().extract(
        pdf_path,
        "one_column_paper",
        include_bibliography=True,
    )

    assert document.body_text.startswith("Paper title")
    assert "[1]" not in document.body_text
    assert "[1]" in document.bibliography
    assert "[2]" in document.bibliography
    assert "[2]" in document.full_text


def test_grobid_config_uses_project_environment(monkeypatch):
    import importlib
    from refchecker.services.pdf_pipeline import config as pdf_config

    monkeypatch.setenv("GROBID_URL", "http://grobid-service:8070")
    monkeypatch.setenv("GROBID_METADATA_TIMEOUT", "4.5")
    importlib.reload(pdf_config)

    assert (
        pdf_config.GROBID_URL
        == "http://grobid-service:8070/api/processFulltextDocument"
    )
    assert pdf_config.GROBID_METADATA_TIMEOUT == 4.5

    monkeypatch.undo()
    importlib.reload(pdf_config)


def test_api_preserves_bytesio_position_and_attaches_classification(monkeypatch):
    source = BytesIO(b"%PDF-1.7 test input")
    source.seek(5)
    document = ExtractedDocument(
        file="paper.pdf",
        doc_type="unknown",
        extractor="test",
        body_text="Body",
        bibliography="",
        full_text="Body",
    )

    class Router:
        def extract(self, pdf_path, doc_type, *, include_bibliography):
            assert pdf_path.read_bytes() == b"%PDF-1.7 test input"
            assert doc_type == "unknown"
            assert include_bibliography is False
            return document

    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.api.classify_pdf",
        lambda *_args, **_kwargs: {"type": "unknown", "confidence": "low"},
    )
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.api.TextExtractorRouter",
        Router,
    )

    result = extract_pdf(source)

    assert source.tell() == 5
    assert result.file == "<memory>"
    assert result.metadata["classification"]["type"] == "unknown"
    assert (
        result.metadata["extraction_diagnostics"]["bibliography_status"]
        == "not_found"
    )
