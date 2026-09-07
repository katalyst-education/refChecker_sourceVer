"""Regression tests for verification-only report exports."""

import io
import zipfile

from backend import export


def _check(**overrides):
    check = {
        "paper_title": "A Study of Citation Verification",
        "timestamp": "2026-06-08T10:00:00Z",
        "results": [
            {
                "index": 1,
                "title": "Attention Is All You Need",
                "authors": [{"name": "A. Vaswani"}],
                "year": 2017,
                "status": "verified",
                "errors": [],
                "warnings": [],
            },
            {
                "index": 2,
                "title": "An unresolved reference",
                "authors": [],
                "status": "unverified",
                "errors": [{"error_type": "unverified", "error_details": "No configured source matched"}],
                "warnings": [],
            },
        ],
    }
    check.update(overrides)
    return check


def test_html_and_markdown_render_verification_results():
    html = export.serialize_check_to_html(_check())
    markdown = export.serialize_check_to_markdown(_check())
    assert html.startswith("<!doctype html>")
    assert markdown.startswith("# A Study of Citation Verification")
    assert "Attention Is All You Need" in html
    assert "An unresolved reference" in markdown


def test_pdf_and_docx_are_real_documents():
    pdf = export.render_check_to_pdf(_check())
    docx = export.render_check_to_docx(_check())
    assert pdf[:5] == b"%PDF-"
    archive = zipfile.ZipFile(io.BytesIO(docx))
    assert "word/document.xml" in archive.namelist()


def test_section_selection_uses_only_current_sections():
    assert export.ALL_SECTIONS == ("summary", "issues", "references")
    assert export.parse_sections("summary,references") == {"summary", "references"}
    assert export.parse_sections("removed,unknown") == set(export.ALL_SECTIONS)


def test_dispatcher_returns_content_type_and_extension():
    content, media_type, extension = export.render_export(_check(), "md")
    assert content.startswith("# A Study of Citation Verification")
    assert media_type.startswith("text/markdown")
    assert extension == "md"
