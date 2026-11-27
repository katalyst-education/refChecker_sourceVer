"""Regression tests for verification-only report exports."""

import io
import zipfile

import pytest

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


@pytest.mark.parametrize("correction", [
    {"warnings": [{"error_type": "year", "ref_year_correct": 2024}]},
    {"corrected_reference": {"year": 2024}},
])
def test_year_only_correction_preserves_cited_bibliography(correction):
    ref = {
        "index": 7, "bibtex_key": "source2020", "status": "warning",
        "title": "Recovered title", "authors": ["Recovered author"], "year": 2025,
        "doi": "10.1234/recovered", "verified_url": "https://example.org/recovered",
        "cited_metadata": {
            "title": "Cited paper", "authors": [{"name": "Doe, Alice"}, "Bob Smith"],
            "year": 2020, "journal": "Cited journal", "doi": "10.1234/cited",
            "url": "https://dx.doi.org/10.1234/cited",
        },
        **correction,
    }
    check = _check(results=[ref])
    report_options = {"corrections": True, "sections": {"references"}}
    md = export.serialize_check_to_markdown(check, **report_options)
    diff = next(line for line in md.splitlines() if "should be:" in line)
    assert "~~(2020).~~" in diff and "**(2024).**" in diff
    assert "Doe, Alice, Bob Smith." in diff
    assert diff.endswith("Cited paper. Cited journal. doi:10.1234/cited")
    html = export.serialize_check_to_html(check, **report_options)
    assert "line-through;" in html and "(2024)." in html
    archive = zipfile.ZipFile(io.BytesIO(export.render_check_to_docx(check, **report_options)))
    assert b"should be: Doe, Alice, Bob Smith. (2024). Cited paper." in archive.read("word/document.xml")
    assert "should be:" not in export.serialize_check_to_markdown(check)
    for style in export.CITATION_STYLES:
        [row] = export.serialize_reference_list([ref], style)
        citation = row["formatted"]
        for part in ("Doe, Alice", "Bob Smith", "Cited paper", "2024", "Cited journal", "10.1234/cited"):
            assert part in citation
        assert "Recovered" not in citation and "recovered" not in citation
    bibtex = export.serialize_reference_list([ref], "bibtex")[0]["formatted"]
    assert bibtex.startswith("@article{source2020,")
    assert "author = {Doe, Alice and Bob Smith}" in bibtex
    assert export.serialize_reference_as_style(ref, "apa").endswith(ref["cited_metadata"]["url"])


def test_stored_fields_override_issue_evidence_but_only_when_present():
    ref = {
        "title": "Cited paper", "year": 2020, "venue": "Cited venue",
        "errors": [{"error_type": "title", "ref_title_correct": "Verified title", "ref_year_correct": 2022}],
        "warnings": [{"warning_type": "venue", "actual_value": "Verified venue"}],
        "corrected_reference": {"year": 2024, "title": "", "journal": "Stored journal"},
    }
    assert export._correction_lines(ref)[1] == "(2024). Verified title. Stored journal"


def test_legacy_actual_text_year_but_not_partial_author_evidence():
    ref = {
        "title": "Legacy paper", "year": 2020, "authors": ["Alice Doe", "Bob Smith"],
        "warnings": [{"warning_type": "year", "warning_details": "Year mismatch:\n cited: 2020\n actual: 2024"}],
        "errors": [{
            "error_type": "author", "actual_value": "Robert Smith",
            "error_details": "Author 2 mismatch:\n cited: Bob Smith\n actual: Robert Smith",
        }],
    }
    assert export._correction_lines(ref)[1] == "Alice Doe, Bob Smith. (2024). Legacy paper"
    ref["errors"][0]["ref_authors_correct"] = "Alice Doe and Robert Smith"
    assert "author = {Alice Doe and Robert Smith}" in export.serialize_reference_as_style(ref, "bibtex")


def test_no_suggestion_or_enrichment_without_evidenced_fields():
    ref = {
        "title": "Display title", "authors": ["Display author"], "doi": "10.1234/display",
        "verified_url": "https://example.org/verified", "verified_doi": "10.1234/verified",
        "cited_metadata": {"title": "Cited paper"},
        "errors": [{"error_type": "unverified", "actual_value": "No record found"}],
        "corrected_reference": {"matched_database": "a database"},
    }
    assert export._correction_lines(ref)[1] is None
    assert export.serialize_reference_as_style(ref, "apa") == "Cited paper."


@pytest.mark.parametrize("field,old_url,new_value,new_url", [
    ("doi", "https://dx.doi.org/10.1234/original", "https://doi.org/10.1234/correct",
     "https://doi.org/10.1234/correct"),
    ("arxiv_id", "https://arxiv.org/pdf/2401.00001", "arXiv:2501.00001",
     "https://arxiv.org/abs/2501.00001"),
])
def test_identifier_fix_rewrites_only_its_link_family(field, old_url, new_value, new_url):
    issue = {"error_type": field, f"ref_{field}_correct": new_value}
    ref = {"cited_metadata": {"title": "Paper", "url": old_url}, "errors": [issue]}
    assert export._correction_lines(ref)[0].endswith(old_url)
    assert export.serialize_reference_as_style(ref, "apa").endswith(new_url)
    assert old_url not in export._correction_lines(ref)[1]
    unrelated = "https://example.org/paper"
    ref["cited_metadata"]["url"] = unrelated
    assert export.serialize_reference_as_style(ref, "apa").endswith(unrelated)
    ref["cited_metadata"]["url"] = old_url
    ref["corrected_reference"] = {"verified_url": unrelated}
    assert export.serialize_reference_as_style(ref, "apa").endswith(unrelated)


@pytest.mark.parametrize("snapshots,expected_title", [
    ({}, "Outer paper"),
    ({"original_reference": {"title": "Legacy paper"}}, "Legacy paper"),
    ({"cited_metadata": {"title": "Modern paper"},
      "original_reference": {"title": "Legacy paper"}}, "Modern paper"),
    ({"cited_metadata": {}, "original_reference": {"title": "Legacy paper"}}, None),
], ids=["outer", "legacy", "modern", "empty-modern"])
def test_citation_snapshot_precedence_in_report_and_bibtex(snapshots, expected_title):
    ref = {
        "title": "Outer paper", "doi": "10.1234/outer", "year": 2020,
        "warnings": [{"warning_type": "year", "ref_year_correct": 2024}],
        **snapshots,
    }
    report = export.serialize_check_to_markdown(
        _check(results=[ref]), corrections=True, sections={"references"},
    )
    diff = next(line for line in report.splitlines() if "should be:" in line)
    bibtex = export.serialize_reference_as_style(ref, "bibtex")
    assert "2024" in diff and "year = {2024}" in bibtex
    for title in ("Outer paper", "Legacy paper", "Modern paper"):
        assert (title in diff) == (title == expected_title)
        assert (f"title = {{{title}}}" in bibtex) == (title == expected_title)
    assert ("10.1234/outer" in diff) == (expected_title == "Outer paper")


@pytest.mark.parametrize("old_url,new_url,correction", [
    ("https://arxiv.org/pdf/2401.00001", "https://arxiv.org/abs/2501.00001",
     {"errors": [{"error_type": "arxiv_id", "ref_arxiv_id_correct": "2501.00001"}]}),
    ("https://doi.org/10.1234/paper", "https://example.org/fixed",
     {"corrected_reference": {"verified_url": "https://example.org/fixed"}}),
    ("https://dx.doi.org/10.1234/paper", "https://doi.org/10.1234/paper",
     {"corrected_reference": {"url": "https://doi.org/10.1234/paper"}}),
], ids=["arxiv-id", "stored-url", "resolver-only"])
def test_report_shows_url_change_with_unchanged_doi(old_url, new_url, correction):
    ref = {
        "title": "Paper", "cited_metadata": {"title": "Paper", "doi": "10.1234/paper", "url": old_url},
        **correction,
    }
    report = export.serialize_check_to_markdown(
        _check(results=[ref]), corrections=True, sections={"references"},
    )
    diff = next(line for line in report.splitlines() if "should be:" in line)
    assert "doi:10.1234/paper" in diff
    assert f"~~{old_url}~~" in diff
    assert f"**{new_url}**" in diff


def test_report_does_not_duplicate_changed_doi_as_resolver_url():
    ref = {
        "title": "Paper",
        "cited_metadata": {"title": "Paper", "doi": "10.1234/old", "url": "https://dx.doi.org/10.1234/old"},
        "errors": [{"error_type": "doi", "ref_doi_correct": "10.1234/new"}],
    }
    report = export.serialize_check_to_markdown(
        _check(results=[ref]), corrections=True, sections={"references"},
    )
    diff = next(line for line in report.splitlines() if "should be:" in line)
    assert "~~doi:10.1234/old~~" in diff and "**doi:10.1234/new**" in diff
    assert "https://" not in diff
