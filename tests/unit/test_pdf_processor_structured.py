"""Tests for PDFProcessor's structured-extraction boundary."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import pymupdf

from refchecker.services.pdf_pipeline import (
    ExtractedDocument,
    PDFExtractionError,
)
from refchecker.services.pdf_processor import PDFProcessor


BODY = "Research body text with enough content to represent a paper. " * 30
BIBLIOGRAPHY = (
    "[1] Alice Smith. A first reference. Journal, 2024.\n"
    "[2] Bob Jones. A second reference. Journal, 2023."
)


def _make_pdf(path: Path, body: str = BODY, bibliography: str = BIBLIOGRAPHY):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((70, 70), "Structured extraction test paper", fontsize=16)
    page.insert_textbox(
        pymupdf.Rect(70, 110, 530, 520),
        body,
        fontsize=10,
    )
    if bibliography:
        page.insert_text((70, 560), "References", fontsize=12)
        page.insert_textbox(
            pymupdf.Rect(70, 580, 530, 720),
            bibliography,
            fontsize=10,
        )
    pdf.save(path)
    pdf.close()
    return path.read_bytes()


def _pipeline_document(include_bibliography: bool) -> ExtractedDocument:
    full_text = BODY.strip()
    if include_bibliography:
        full_text += f"\n\n## References\n{BIBLIOGRAPHY}"
    return ExtractedDocument(
        file="paper.pdf",
        doc_type="one_column_paper",
        extractor="test_pipeline",
        title="A test paper",
        body_text=BODY.strip(),
        bibliography=BIBLIOGRAPHY,
        full_text=full_text,
        pages=[{"page_number": 1, "text": BODY}],
        sections=[{"heading": "Introduction", "page_number": 1}],
        metadata={"test": "preserved"},
    )


@pytest.mark.parametrize("source_kind", ["path", "bytes", "bytearray", "bytesio"])
def test_extract_document_passes_supported_source_to_pipeline(
    monkeypatch, tmp_path, source_kind
):
    processor = PDFProcessor()
    pdf_bytes = _make_pdf(tmp_path / "input.pdf")
    if source_kind == "path":
        source = tmp_path / "input.pdf"
    elif source_kind == "bytes":
        source = pdf_bytes
    elif source_kind == "bytearray":
        source = bytearray(pdf_bytes)
    else:
        source = BytesIO(pdf_bytes)
        source.seek(11)

    expected = _pipeline_document(False)
    pipeline = Mock(return_value=expected)
    monkeypatch.setattr(
        "refchecker.services.pdf_processor.extract_pdf",
        pipeline,
    )

    result = processor.extract_document(source)

    assert result is expected
    assert result.body_text == expected.body_text
    assert result.bibliography == expected.bibliography
    assert result.pages == expected.pages
    assert result.sections == expected.sections
    assert result.metadata["test"] == "preserved"
    pipeline.assert_called_once()
    if source_kind == "bytesio":
        assert source.tell() == 11
        assert pipeline.call_args.args[0] == pdf_bytes


@pytest.mark.parametrize("include_bibliography", [False, True])
def test_extract_document_passes_bibliography_option_and_preserves_pipeline_result(
    monkeypatch, tmp_path, include_bibliography
):
    pdf_path = tmp_path / "input.pdf"
    _make_pdf(pdf_path)
    expected = _pipeline_document(include_bibliography)
    pipeline = Mock(return_value=expected)
    monkeypatch.setattr(
        "refchecker.services.pdf_processor.extract_pdf",
        pipeline,
    )

    result = PDFProcessor().extract_document(
        pdf_path,
        include_bibliography=include_bibliography,
    )

    assert result is expected
    assert result.bibliography == BIBLIOGRAPHY
    assert (BIBLIOGRAPHY in result.full_text) is include_bibliography
    assert pipeline.call_args.kwargs["include_bibliography"] is include_bibliography
    assert result.metadata["pdf_processor"]["pipeline"]["status"] == "succeeded"


def test_real_pipeline_document_extraction_needs_no_grobid_service(
    monkeypatch, tmp_path
):
    import refchecker.services.pdf_pipeline.api as api_module
    import refchecker.services.pdf_pipeline.text_extractors.one_column_text_extractor as one_col
    import refchecker.services.pdf_pipeline.text_extractors.two_column_text_extractor as two_col

    pdf_path = tmp_path / "paper.pdf"
    pdf = pymupdf.open()
    body_page = pdf.new_page(width=600, height=800)
    body_page.insert_text((70, 70), "Structured extraction test paper", fontsize=16)
    body_page.insert_textbox(
        pymupdf.Rect(70, 110, 530, 700),
        "Research body text with enough content to represent a paper. " * 12,
        fontsize=10,
    )
    references_page = pdf.new_page(width=600, height=800)
    references_page.insert_text((70, 100), "References", fontsize=12)
    references_page.insert_textbox(
        pymupdf.Rect(70, 125, 530, 700),
        BIBLIOGRAPHY,
        fontsize=10,
    )
    pdf.save(pdf_path)
    pdf.close()
    pdf_bytes = pdf_path.read_bytes()
    monkeypatch.setattr(
        api_module,
        "classify_pdf",
        lambda *_args, **_kwargs: {"type": "one_column_paper"},
    )
    no_grobid = Mock(
        return_value={
            "title": "",
            "abstract": "",
            "author_keywords": [],
            "grobid_error": "not configured",
        }
    )
    monkeypatch.setattr(one_col, "extract_grobid_metadata", no_grobid)
    monkeypatch.setattr(two_col, "extract_grobid_metadata", no_grobid)

    result = PDFProcessor().extract_document(
        pdf_bytes,
        include_bibliography=False,
    )

    assert result.body_text
    assert result.bibliography
    assert BIBLIOGRAPHY.splitlines()[0] in result.bibliography
    assert BIBLIOGRAPHY not in result.full_text
    assert result.metadata["pdf_processor"]["pipeline"]["status"] == "succeeded"
    assert no_grobid.called


@pytest.mark.parametrize(
    ("pipeline_result", "include_bibliography"),
    [
        ("raises", True),
        ("empty", True),
        ("invalid", True),
        ("raises", False),
    ],
)
def test_extract_document_falls_back_to_legacy_text_extractor(
    monkeypatch, tmp_path, pipeline_result, include_bibliography
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(_make_pdf(pdf_path))
    processor = PDFProcessor()
    if pipeline_result == "raises":
        pipeline = Mock(side_effect=RuntimeError("pipeline unavailable"))
    elif pipeline_result == "empty":
        pipeline = Mock(return_value=ExtractedDocument(
            file="paper.pdf",
            doc_type="unknown",
            extractor="broken",
        ))
    else:
        pipeline = Mock(return_value={"full_text": ""})
    legacy = Mock(return_value=f"{BODY.strip()}\nReferences\n{BIBLIOGRAPHY}")
    monkeypatch.setattr(
        "refchecker.services.pdf_processor.extract_pdf",
        pipeline,
    )
    monkeypatch.setattr(processor, "extract_text_from_pdf", legacy)
    monkeypatch.setattr(processor, "extract_title_from_pdf", lambda _path: "Title")

    result = processor.extract_document(
        pdf_path,
        include_bibliography=include_bibliography,
    )

    assert result.extractor == "legacy_pdf_processor"
    assert result.body_text.startswith(BODY.strip()[:50])
    assert BIBLIOGRAPHY in result.bibliography
    assert (BIBLIOGRAPHY in result.full_text) is include_bibliography
    assert result.metadata["pdf_processor"]["pipeline"]["status"] == "failed"
    assert result.metadata["pdf_processor"]["fallback"]["status"] == "succeeded"
    legacy.assert_called_once_with(str(pdf_path))


def test_legacy_fallback_supports_in_memory_sources_and_cleans_temporary_file(
    monkeypatch, tmp_path
):
    pdf_bytes = _make_pdf(tmp_path / "source.pdf")
    source = BytesIO(pdf_bytes)
    source.seek(9)
    processor = PDFProcessor()
    temporary_paths = []
    monkeypatch.setattr(
        "refchecker.services.pdf_processor.extract_pdf",
        Mock(side_effect=RuntimeError("pipeline failure")),
    )

    def read_legacy_text(path):
        temporary_paths.append(Path(path))
        assert Path(path).read_bytes() == pdf_bytes
        return f"{BODY.strip()}\nReferences\n{BIBLIOGRAPHY}"

    monkeypatch.setattr(processor, "extract_text_from_pdf", read_legacy_text)
    monkeypatch.setattr(processor, "extract_title_from_pdf", lambda _path: "Title")

    result = processor.extract_document(source)

    assert result.file == "<memory>"
    assert source.tell() == 9
    assert result.bibliography == BIBLIOGRAPHY
    assert len(temporary_paths) == 1
    assert not temporary_paths[0].exists()


def test_both_pipeline_and_legacy_fail_with_diagnostics(monkeypatch, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)
    processor = PDFProcessor()
    monkeypatch.setattr(
        "refchecker.services.pdf_processor.extract_pdf",
        Mock(side_effect=PDFExtractionError(
            "pipeline failed",
            {"errors": ["pipeline detail"]},
        )),
    )
    monkeypatch.setattr(
        processor,
        "extract_text_from_pdf",
        Mock(side_effect=ValueError("legacy detail")),
    )

    with pytest.raises(PDFExtractionError) as error:
        processor.extract_document(pdf_path)

    assert error.value.diagnostics["document_status"] == "failed"
    assert "pipeline detail" in error.value.diagnostics["errors"]
    assert any("legacy detail" in item for item in error.value.diagnostics["errors"])


def test_extract_text_legacy_cache_behavior_remains_unchanged(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "cache.pdf"
    _make_pdf(pdf_path, "Original cached text. " * 10, "")
    processor = PDFProcessor()

    first = processor.extract_text_from_pdf(str(pdf_path))
    _make_pdf(pdf_path, "Replacement text. " * 10, "")
    second = processor.extract_text_from_pdf(str(pdf_path))

    assert second == first
    processor.clear_cache()
    third = processor.extract_text_from_pdf(str(pdf_path))
    assert "Replacement text." in third
