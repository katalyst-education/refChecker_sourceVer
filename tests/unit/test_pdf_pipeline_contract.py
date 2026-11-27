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
from refchecker.services.pdf_pipeline.text_extractors.common_helpers import (
    identifier_line_continues,
    join_spans_with_position_spacing,
    merge_drawn_identifier_fragments,
    restore_drawn_identifier_underscores,
)
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


@pytest.mark.parametrize("raw_chars", [False, True])
def test_drawn_underscore_restored_only_for_matching_identifier_span(raw_chars):
    def span(text, x0, x1):
        result = {"bbox": (x0, 0, x1, 10), "origin": (x0, 8), "size": 10}
        if raw_chars:
            result["chars"] = [{"c": char} for char in text]
        else:
            result["text"] = text
        return result

    spans = [span("https://example.org/a", 0, 30), span(" ", 30, 34), span("b", 34, 39)]
    stroke = {
        "type": "s", "width": 0.5,
        "items": [("l", Mock(x=30, y=9), Mock(x=34, y=9))],
    }

    repaired = restore_drawn_identifier_underscores(spans, [stroke])

    assert (repaired[1]["chars"][0]["c"] if raw_chars else repaired[1]["text"]) == "_"
    assert (spans[1]["chars"][0]["c"] if raw_chars else spans[1]["text"]) == " "
    assert restore_drawn_identifier_underscores(spans, []) == spans
    wide_stroke = dict(stroke, items=[("l", Mock(x=25, y=9), Mock(x=40, y=9))])
    assert restore_drawn_identifier_underscores(spans, [wide_stroke]) == spans


def test_drawn_space_is_not_changed_in_normal_prose():
    spans = [
        {"text": "ordinary", "bbox": (0, 0, 30, 10), "origin": (0, 8), "size": 10},
        {"text": " ", "bbox": (30, 0, 34, 10), "origin": (30, 8), "size": 10},
        {"text": "words", "bbox": (34, 0, 50, 10), "origin": (34, 8), "size": 10},
    ]
    stroke = {
        "type": "s", "width": 0.5,
        "items": [("l", Mock(x=30, y=9), Mock(x=34, y=9))],
    }

    assert restore_drawn_identifier_underscores(spans, [stroke]) == spans


def test_drawn_underscore_in_title_before_identifier_is_restored():
    spans = [
        {"text": "A", "bbox": (0, 0, 4, 10), "origin": (0, 8), "size": 10},
        {"text": " ", "bbox": (4, 0, 8, 10), "origin": (4, 8), "size": 10},
        {"text": "title https://example.org", "bbox": (8, 0, 90, 10), "origin": (8, 8), "size": 10},
    ]
    stroke = {
        "type": "s", "width": 0.5,
        "items": [("l", Mock(x=4, y=9), Mock(x=8, y=9))],
    }

    repaired = restore_drawn_identifier_underscores(spans, [stroke])
    assert repaired[1]["text"] == "_"


def test_drawn_underscore_in_identifier_continuation_is_restored():
    spans = [
        {"text": "nella+Scuola", "bbox": (0, 0, 30, 10), "origin": (0, 8), "size": 10},
        {"text": " ", "bbox": (30, 0, 34, 10), "origin": (30, 8), "size": 10},
        {"text": "09", "bbox": (34, 0, 42, 10), "origin": (34, 8), "size": 10},
    ]
    stroke = {
        "type": "s", "width": 0.5,
        "items": [("l", Mock(x=30, y=9), Mock(x=34, y=9))],
    }

    assert restore_drawn_identifier_underscores(spans, [stroke]) == spans
    repaired = restore_drawn_identifier_underscores(spans, [stroke], continuation=True)
    assert repaired[1]["text"] == "_"


def test_identifier_context_survives_multiple_wrapped_lines():
    lines = [
        "https://research-",
        "and-innovation.ec.europa.eu/strategy/strategy-research-and-",
        "innovation/democracy-and-rights/gender-equality-research-and-",
    ]
    continuation = False
    for line in lines:
        continuation = identifier_line_continues(line, continuation)
        assert continuation
    assert not identifier_line_continues("ordinary prose here", continuation)
    assert not identifier_line_continues("ending-with-hyphen-", False)

    text = "\n".join(lines + ["innovation_en"])
    assert paper_helpers.fix_broken_line_hyphenation(text) == text
    assembled = []
    for line in text.splitlines():
        paper_helpers.append_text_line(assembled, line)
    assert "\n".join(assembled) == text


@pytest.mark.parametrize("raw_chars", [False, True])
def test_split_identifier_fragments_require_contiguous_baseline_strokes(raw_chars):
    def span(value, x0, x1, baseline):
        result = {
            "bbox": (x0, baseline - 8, x1, baseline + 2),
            "origin": (x0, baseline), "size": 10,
        }
        if raw_chars:
            result["chars"] = [{"c": char} for char in value]
        else:
            result["text"] = value
        return result

    lines = [
        {"bbox": (0, 0, 30, 10), "spans": [span("https://example.org/", 0, 30, 8)]},
        {"bbox": (0, 10, 30, 20), "spans": [span("file2024", 0, 30, 18)]},
        {"bbox": (38, 10, 65, 20), "spans": [span("1.pdf", 38, 65, 18)]},
    ]
    strokes = [
        {"type": "s", "width": 0.5,
         "items": [("l", Mock(x=start, y=19), Mock(x=end, y=19))]}
        for start, end in ((30, 34), (34, 38))
    ]
    page = Mock()
    page.get_drawings.return_value = strokes

    merged = merge_drawn_identifier_fragments(lines, page)

    assert len(merged) == 2
    spans = merged[1]["spans"]
    value = "".join(
        "".join(char["c"] for char in span["chars"]) if raw_chars else span["text"]
        for span in spans
    )
    assert value == "file2024__1.pdf"
    assert merged[1]["_source_text"] == "file2024\n1.pdf"
    page.get_drawings.return_value = strokes[:1]
    assert merge_drawn_identifier_fragments(lines, page) == lines
    page.get_drawings.return_value = strokes + strokes[:1]
    assert merge_drawn_identifier_fragments(lines, page) == lines
    non_url = [dict(lines[0], spans=[span("ordinary prose/", 0, 30, 8)]), *lines[1:]]
    page.get_drawings.reset_mock()
    assert merge_drawn_identifier_fragments(non_url, page) == non_url
    page.get_drawings.assert_not_called()


def test_two_column_block_bounds_ignore_empty_lines(monkeypatch):
    right_text = "A right-column reference continuation."
    left_text = "A left-column reference."
    blocks = [
        {
            "type": 0, "bbox": (40, 100, 550, 210),
            "lines": [
                {"bbox": (320, 100, 550, 110), "spans": [
                    {"text": right_text, "bbox": (320, 100, 550, 110), "size": 10}
                ]},
                {"bbox": (40, 200, 42, 210), "spans": [
                    {"text": " ", "bbox": (40, 200, 42, 210), "size": 10}
                ]},
            ],
        },
        {
            "type": 0, "bbox": (40, 150, 280, 160),
            "lines": [{"bbox": (40, 150, 280, 160), "spans": [
                {"text": left_text, "bbox": (40, 150, 280, 160), "size": 10}
            ]}],
        },
    ]
    page = Mock()
    page.rect.width = 600
    page.rect.height = 800
    page.get_text.return_value = {"blocks": blocks}
    document = Mock()
    document.__iter__ = Mock(return_value=iter([page]))
    monkeypatch.setattr(two_column_module.pymupdf, "open", lambda _: document)

    pages = two_column_module.extract_blocks_from_two_column_pdf(Path("example.pdf"))

    assert [block["text"] for block in pages[0]["blocks"]] == [left_text, right_text]
    assert pages[0]["blocks"][1]["x0"] == 320


def test_two_column_keeps_adjacent_year_after_citation_title(monkeypatch):
    def block(text, box):
        return {
            "type": 0, "bbox": box,
            "lines": [{"bbox": box, "spans": [{
                "text": text, "bbox": box, "size": 8, "font": "Example", "flags": 0,
            }]}],
        }

    source = [
        block('[3] ABET, "Criteria for Accrediting Engineering Programs, 2019-2020,"',
              (315, 700, 563, 709)),
        block("2020.", (330, 710, 348, 718)),
        block("2021.", (330, 750, 348, 758)),
    ]
    page = Mock()
    page.rect.width = 612
    page.rect.height = 792
    page.get_text.return_value = {"blocks": source}
    document = Mock()
    document.__iter__ = Mock(return_value=iter([page]))
    monkeypatch.setattr(two_column_module.pymupdf, "open", lambda _: document)

    pages = two_column_module.extract_blocks_from_two_column_pdf(Path("example.pdf"))

    assert pages[0]["blocks"][0]["text"].endswith('\n2020.')
    assert "2021." not in pages[0]["blocks"][0]["text"]


@pytest.mark.parametrize(("preceding", "expected"), [
    ("[4] N. Fouad et al., Why Women Leave Engineering, University of Wisconsin-Milwaukee,", True),
    ("Previous reference continuation.\n[4] J. Piaget, The Psychology of Intelligence. London: Routledge,", True),
    ("Previous reference continuation.\nDiscussion mentions [4],", False),
    ("This discussion mentions [4],", False),
    ("[4] A. Author, A completed citation.", False),
])
def test_two_column_keeps_adjacent_year_after_unquoted_citation(monkeypatch, preceding, expected):
    def block(text, box):
        return {
            "type": 0, "bbox": box,
            "lines": [{"bbox": box, "spans": [{
                "text": line, "bbox": box, "size": 10, "font": "Example", "flags": 0,
            }]} for line in text.splitlines()],
        }

    page = Mock()
    page.rect.width = 612
    page.rect.height = 792
    page.get_text.return_value = {"blocks": [
        block(preceding, (72, 71, 286, 97)),
        block("2011.", (72, 105, 97, 119)),
    ]}
    document = Mock()
    document.__iter__ = Mock(return_value=iter([page]))
    monkeypatch.setattr(two_column_module.pymupdf, "open", lambda _: document)

    pages = two_column_module.extract_blocks_from_two_column_pdf(Path("example.pdf"))

    assert pages[0]["blocks"][0]["text"].endswith("\n2011.") is expected


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


def test_pdf_text_cleanup_repairs_missing_glyph_in_publisher_label():
    assert paper_helpers.paper_clean_text("Pubisher: McKinsey & Company") == (
        "Publisher: McKinsey & Company"
    )
    assert paper_helpers.paper_clean_text_preserve_lines(
        "Pubisher: McKinsey & Company\nNext line"
    ) == "Publisher: McKinsey & Company\nNext line"
    assert paper_helpers.paper_clean_text(
        "Studierende: Nationalit\ufffdat, Geschlecht, Studienfach,\ufffd"
    ) == 'Studierende: Nationalität, Geschlecht, Studienfach,"'
    assert paper_helpers.paper_clean_text(
        "\ufffdBereicherung f\ufffdur die Medizin von morgen.\ufffd"
    ) == '"Bereicherung für die Medizin von morgen."'


def test_pdf_text_cleanup_repairs_joined_conjunctions_without_changing_normal_words():
    assert paper_helpers.paper_clean_text(
        "Project-Based Learning: Definitionsand Qualities"
    ) == "Project-Based Learning: Definitions and Qualities"
    assert paper_helpers.paper_clean_text_preserve_lines(
        "Definitionsand Qualities\nStandard practice"
    ) == "Definitions and Qualities\nStandard practice"
    assert paper_helpers.paper_clean_text("Finland and standard") == (
        "Finland and standard"
    )


def test_span_joining_preserves_spaces_and_avoids_breaking_urls_or_punctuation():
    clean = lambda text: text.strip()

    spans = [
        {"text": "UNESCO, ", "bbox": (0, 0, 30, 8), "size": 8},
        {"text": "Education", "bbox": (31.2, 0, 70, 8), "size": 8},
    ]
    assert join_spans_with_position_spacing(spans, clean) == "UNESCO, Education"

    separate_spaces = [
        {"text": "10.1007/978-3-030-34350-7_37.", "bbox": (0, 0, 80, 8), "size": 8},
        {"text": " ", "bbox": (80, 0, 83, 8), "size": 8},
        {"text": "pp.", "bbox": (83, 0, 90, 8), "size": 8},
        {"text": " ", "bbox": (90, 0, 93, 8), "size": 8},
        {"text": "383-393.", "bbox": (93, 0, 110, 8), "size": 8},
    ]
    doi_line = join_spans_with_position_spacing(separate_spaces, clean)
    assert doi_line == "10.1007/978-3-030-34350-7_37. pp. 383-393."

    from refchecker.core.refchecker import ArxivReferenceChecker

    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    ref = checker._parse_quoted_numbered_references([
        '[1] A. Smith, "Learning methods," Journal of Testing, 2020, DOI: '
        + doi_line
    ])[0]
    assert ref["doi"] == "10.1007/978-3-030-34350-7_37"
    assert ref["url"] == "https://doi.org/10.1007/978-3-030-34350-7_37"

    tightly_spaced_words = [
        {"text": "Project", "bbox": (0, 0, 25, 8), "size": 8},
        {"text": "Based", "bbox": (26, 0, 48, 8), "size": 8},
    ]
    assert join_spans_with_position_spacing(tightly_spaced_words, clean) == (
        "Project Based"
    )

    url_spans = [
        {"text": "https://example.com/", "bbox": (0, 0, 65, 8), "size": 8},
        {"text": "path", "bbox": (67, 0, 82, 8), "size": 8},
        {"text": ",", "bbox": (85, 0, 87, 8), "size": 8},
    ]
    assert join_spans_with_position_spacing(url_spans, clean) == (
        "https://example.com/path,"
    )


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


def test_appendix_heading_on_next_page_does_not_merge_into_last_reference():
    parts = [
        "Paper body.\nReferences\n"
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. https://doi.org/10.1111/example"
    ]
    paper_helpers.append_page_text(
        parts, "Appendix A. Keyword Lexicon\nSupplemental explanatory text."
    )

    body, bibliography, _ = split_text_and_references("\n\n".join(parts))

    assert bibliography.endswith("https://doi.org/10.1111/example")
    assert "Appendix A. Keyword Lexicon" in body


@pytest.mark.parametrize(
    "page_header",
    ["Bibliography 85", "Bibliography\n86"],
)
def test_reference_split_removes_bibliography_page_headers(page_header):
    text = (
        "Paper body.\nReferences\n"
        "[1] Alice Smith. First reference. 2024.\n"
        f"{page_header}\n"
        "[2] Bob Jones. Second reference. 2023."
    )

    _, bibliography, debug = split_text_and_references(text)

    assert debug["references_found"] is True
    assert bibliography == (
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. 2023."
    )


def test_reference_split_stops_at_english_declaration_section():
    declaration = "Declaration\nI certify that I wrote this thesis independently."
    text = (
        "Paper body.\nReferences\n"
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. 2023.\n"
        f"{declaration}"
    )

    body, bibliography, debug = split_text_and_references(text)

    assert debug["references_found"] is True
    assert bibliography.endswith("[2] Bob Jones. Second reference. 2023.")
    assert "Declaration" not in bibliography
    assert declaration in body


def test_reference_split_stops_at_inline_extracted_declaration():
    declaration = "Declaration I hereby certify that this thesis is my own work."
    text = (
        "Paper body.\nReferences\n"
        '[1] Alice Smith. First reference. 2024. [Online]. Available: https://example.org/1\n'
        '[2] Bob Jones. Second reference. 2023. [Online]. Available: https://example.org/2 '
        f"{declaration}"
    )

    body, bibliography, debug = split_text_and_references(text)

    assert debug["references_found"] is True
    assert "[2] Bob Jones" in bibliography
    assert "Declaration" not in bibliography
    assert declaration in body


@pytest.mark.parametrize(
    "post_bibliography",
    [
        "Anhang A: Zusätzliche Tabellen\nAnhangstext bleibt erhalten.",
        "7. Anhangsverzeichnis\nAnhang 1 Tabellen bleiben erhalten.",
        "Eidesstattliche Erklärung\nDie Erklärung bleibt erhalten.",
    ],
)
def test_german_post_bibliography_sections_remain_outside_references(
    post_bibliography,
):
    text = (
        "Paper body.\nReferences\n"
        "[1] Alice Smith. First reference. 2024.\n"
        "[2] Bob Jones. Second reference. 2023.\n"
        f"{post_bibliography}"
    )

    body, bibliography, debug = split_text_and_references(text)
    body_without_references, full_text = assemble_document_text(
        body,
        bibliography,
        True,
        debug,
    )

    assert "Anhang" not in bibliography
    assert "Erklärung" not in bibliography
    assert post_bibliography in body_without_references
    assert post_bibliography in full_text


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


def test_cleaning_toc_reference_entry_does_not_create_a_bibliography_boundary():
    toc_entry = "5. Literaturverzeichnis ........ 23"
    body_sections = "\n".join(
        f"{index}. Numbered chapter section with descriptive body text."
        for index in range(1, 35)
    )
    actual_references = (
        "Mueller, A. (2020): A grounded reference entry. Journal One.\n"
        "Schmidt, B. (2021): Another grounded reference entry. Journal Two."
    )
    pages = [
        {
            "page_number": 1,
            "blocks": [
                {"text": "Inhaltsverzeichnis"},
                {"text": toc_entry},
                {"text": body_sections},
            ],
        },
        {
            "page_number": 12,
            "blocks": [
                {"text": "5. Literaturverzeichnis"},
                {"text": actual_references},
            ],
        },
    ]

    paper = paper_helpers.build_clean_paper_text(pages)
    body, bibliography, debug = split_text_and_references(paper["text"])

    assert toc_entry in paper["text"]
    assert debug["references_heading"].removeprefix("## ") == (
        "5. Literaturverzeichnis"
    )
    assert bibliography == actual_references
    assert body.startswith("Inhaltsverzeichnis")


def test_directory_entry_page_numbers_are_preserved():
    toc_entry = "1. Introduction ........ 3"
    pages = [{
        "page_number": 1,
        "blocks": [
            {"text": "Contents"},
            {"text": toc_entry},
            {"text": "Introduction starts here."},
        ],
    }]

    paper = paper_helpers.build_clean_paper_text(pages)

    assert toc_entry in paper["text"]


def test_reference_heading_with_single_inline_author_year_entry_is_accepted():
    text = (
        "Paper body.\n"
        "9. Literaturverzeichnis Bernhardsson-Laros, Nils (2016): "
        "A supported reference entry. Journal One."
    )

    body, bibliography, debug = split_text_and_references(text)

    assert body == "Paper body."
    assert bibliography.startswith("Bernhardsson-Laros, Nils (2016)")
    assert debug["references_found"] is True


def test_reference_heading_at_page_start_is_not_joined_to_body_page():
    parts = ["The body page ends with an unfinished sentence"]
    page_text = (
        "Literaturverzeichnis Collins, K. (2008). "
        "Game Sound: An Introduction.\n"
        "Second author reference (2020). Journal Two."
    )

    paper_helpers.append_page_text(parts, page_text)

    assert parts[1].startswith("Literaturverzeichnis Collins")
    body, bibliography, debug = split_text_and_references(
        "\n\n".join(parts)
    )
    assert body == "The body page ends with an unfinished sentence"
    assert bibliography.startswith("Collins, K. (2008)")
    assert debug["references_found"] is True


def test_similar_numbered_references_are_not_deduplicated():
    first = (
        "[133] J. Stamper, S. Ritter, and K. Koedinger, "
        "Algebra I 2005-2006 Development Data Set, 2010."
    )
    second = (
        "[134] J. Stamper, S. Ritter, and K. Koedinger, "
        "Algebra I 2006-2007 Development Data Set, 2010."
    )
    pages = [
        {
            "page_number": 1,
            "blocks": [
                {"text": "Bibliography"},
                {"text": first},
                {"text": second},
            ],
        }
    ]

    assert paper_helpers.paper_normalize_for_repetition(first) == (
        paper_helpers.paper_normalize_for_repetition(second)
    )
    extracted = paper_helpers.build_clean_paper_text(pages)

    assert "[133]" in extracted["text"]
    assert "[134]" in extracted["text"]


def test_repeated_table_headers_at_distinct_positions_are_preserved():
    blocks = []
    for index in range(3):
        y0 = 10 + index * 20
        blocks.extend([
            {
                "text": "Summe Prozent",
                "x0": 10,
                "y0": y0,
                "x1": 100,
                "y1": y0 + 5,
            },
            {
                "text": f"Group {index + 1} value {index + 10}",
                "x0": 10,
                "y0": y0 + 5,
                "x1": 100,
                "y1": y0 + 10,
            },
        ])
    blocks.append({
        "text": "Summe Prozent",
        "x0": 10,
        "y0": 10,
        "x1": 100,
        "y1": 15,
    })

    extracted = paper_helpers.build_clean_paper_text([
        {"page_number": 1, "page_height": 100, "blocks": blocks},
    ])

    assert extracted["text"].count("Summe Prozent") == 3


def test_character_extraction_preserves_short_table_cells():
    from refchecker.services.pdf_pipeline.text_extractors.one_column_text_extractor import (
        extract_text_units_from_chars,
    )

    class Page:
        def get_text(self, mode):
            assert mode == "rawdict"
            chars = []
            for row, value in enumerate(("A", "2", "M2")):
                x = 20.0
                row_chars = []
                for character in value:
                    row_chars.append({
                        "c": character,
                        "bbox": [x, 20 + row * 20, x + 5, 30 + row * 20],
                    })
                    x += 5
                chars.append({
                    "type": 0,
                    "lines": [{
                        "spans": [{
                            "size": 10,
                            "chars": row_chars,
                        }],
                    }],
                })
            return {"blocks": chars}

    units = extract_text_units_from_chars(Page())
    extracted = "\n".join(units)

    assert "A" in extracted
    assert "2" in extracted
    assert "M2" in extracted


def test_one_column_page_falls_back_to_native_text_when_character_text_loses_tokens(
    monkeypatch,
):
    class Page:
        rect = type("Rect", (), {"width": 600, "height": 800})()

        def get_text(self, mode):
            assert mode == "text"
            return "The page source includes the missing table value 978."

    class Pdf:
        def __iter__(self):
            return iter([Page()])

        def close(self):
            pass

    monkeypatch.setattr(
        one_column_module.pymupdf,
        "open",
        lambda _path: Pdf(),
    )
    monkeypatch.setattr(
        one_column_module,
        "extract_text_units_from_chars",
        lambda _page: ["The page source includes"],
    )

    pages = one_column_module.extract_pages_text_char_based(
        Path("table.pdf")
    )

    assert "978" in pages[0]["blocks"][0]["text"]


def test_one_column_native_fallback_restores_drawn_url_underscore(monkeypatch):
    class Page:
        def get_text(self, mode):
            if mode == "text":
                return "https://example.org/a b missing"
            assert mode == "dict"
            return {"blocks": [{"lines": [{"spans": [
                {"text": "https://example.org/a", "bbox": (0, 0, 30, 10), "origin": (0, 8), "size": 10},
                {"text": " ", "bbox": (30, 0, 34, 10), "origin": (30, 8), "size": 10},
                {"text": "b missing", "bbox": (34, 0, 70, 10), "origin": (34, 8), "size": 10},
            ]}]}]}

        def get_drawings(self):
            return [{
                "type": "s", "width": 0.5,
                "items": [("l", Mock(x=30, y=9), Mock(x=34, y=9))],
            }]

    monkeypatch.setattr(
        one_column_module, "extract_text_units_from_chars",
        lambda _page: ["https://example.org/a_b"],
    )

    assert one_column_module.extract_page_text_units(Page()) == [
        "https://example.org/a_b missing"
    ]


def test_one_column_native_fallback_restores_split_identifier_strokes(monkeypatch):
    def span(value, x0, x1, baseline):
        return {
            "text": value, "bbox": (x0, baseline - 8, x1, baseline + 2),
            "origin": (x0, baseline), "size": 10,
        }

    class Page:
        def get_text(self, mode):
            if mode == "text":
                return "https://example.org/\nfile2024\n1 .pdf, missing"
            assert mode == "dict"
            return {"blocks": [{"lines": [
                {"bbox": (0, 0, 30, 10), "spans": [span("https://example.org/", 0, 30, 8)]},
                {"bbox": (0, 10, 30, 20), "spans": [span("file2024", 0, 30, 18)]},
                {"bbox": (38, 10, 65, 20), "spans": [
                    span("1", 38, 42, 18), span(" ", 42, 46, 18),
                    span(".pdf, missing", 46, 65, 18),
                ]},
            ]}]}

        def get_drawings(self):
            return [
                {"type": "s", "width": 0.5,
                 "items": [("l", Mock(x=start, y=19), Mock(x=end, y=19))]}
                for start, end in ((30, 34), (34, 38), (42, 46))
            ]

    monkeypatch.setattr(
        one_column_module, "extract_text_units_from_chars",
        lambda _page: ["https://example.org/file2024__1_.pdf"],
    )

    assert one_column_module.extract_page_text_units(Page()) == [
        "https://example.org/\nfile2024__1_.pdf, missing"
    ]


def test_character_reconstruction_preserves_source_order_for_overlapping_glyphs():
    from refchecker.services.pdf_pipeline.text_extractors.one_column_text_extractor import (
        extract_text_units_from_chars,
    )

    class Page:
        def get_text(self, mode):
            assert mode == "rawdict"
            chars = []
            x = 100.0
            for index, character in enumerate("Steffen"):
                if index == 5:
                    x -= 5.02
                chars.append({
                    "c": character,
                    "bbox": [x, 20, x + 4.5, 30],
                })
                x += 5
            return {
                "blocks": [{
                    "type": 0,
                    "lines": [{
                        "spans": [{
                            "size": 10,
                            "chars": chars,
                        }],
                    }],
                }],
            }

    units = extract_text_units_from_chars(Page())

    assert "Steffen" in units


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


def test_fix_split_uppercase_words_preserves_articles_and_initials():
    assert (
        paper_helpers.fix_split_uppercase_words("OpenAlex: A Fully-Open Index")
        == "OpenAlex: A Fully-Open Index"
    )
    assert (
        paper_helpers.fix_split_uppercase_words("A Large Language Model")
        == "A Large Language Model"
    )
    assert paper_helpers.fix_split_uppercase_words("I Believe") == "I Believe"
    assert paper_helpers.fix_split_uppercase_words("John J Smith") == "John J Smith"
    assert paper_helpers.fix_split_uppercase_words("S ICHERUNG") == "SICHERUNG"
    assert (
        paper_helpers.fix_split_uppercase_words("M ASCHINENDATEN")
        == "MASCHINENDATEN"
    )
    assert (
        paper_helpers.fix_split_uppercase_words(
            "John J Smith and J R R Tolkien"
        )
        == "John J Smith and J R R Tolkien"
    )
    assert (
        paper_helpers.fix_split_uppercase_words("NASA, AI, eBay, and iPhone")
        == "NASA, AI, eBay, and iPhone"
    )


def test_paper_text_normalization_preserves_multilingual_names_and_case():
    text = (
        "J\u00fcrgen M\u00fcller, Garc\u00eda M\u00e1rquez, and "
        "\u0141ukasz \u017b\u00f3\u0142\u0107"
    )
    assert paper_helpers.paper_clean_text(text) == text
    assert (
        paper_helpers.paper_clean_text(
            "\u00c4u\u00dfere \u00d6konomie der \u00dcbertragung"
        )
        == "\u00c4u\u00dfere \u00d6konomie der \u00dcbertragung"
    )


def test_fix_broken_line_hyphenation_compound_titles_and_coordination():
    assert paper_helpers.fix_broken_line_hyphenation("IoT-\neducation") == "IoT-education"
    assert paper_helpers.fix_broken_line_hyphenation("AI-\npowered") == "AI-powered"
    assert paper_helpers.fix_broken_line_hyphenation("McGet-\ntrick") == "McGettrick"
    assert paper_helpers.fix_broken_line_hyphenation("university-\nindustry") == "university-industry"
    assert paper_helpers.fix_broken_line_hyphenation("univers-\nity") == "university"
    lines = []
    paper_helpers.append_text_line(lines, '"IoT-')
    paper_helpers.append_text_line(lines, 'education policies"')
    assert "\n".join(lines) == '"IoT-\neducation policies"'
    lines = []
    paper_helpers.append_text_line(lines, "student self-")
    paper_helpers.append_text_line(lines, "assessment")
    assert "\n".join(lines) == "student self-\nassessment"
    lines = []
    paper_helpers.append_text_line(lines, "university-")
    paper_helpers.append_text_line(lines, "industry partnerships")
    assert "\n".join(lines) == "university-\nindustry partnerships"
    assert (
        paper_helpers.fix_broken_line_hyphenation("A Fully-\nOpen Index")
        == "A Fully-Open Index"
    )
    assert (
        paper_helpers.fix_broken_line_hyphenation("Fine-\nGrained Benchmark")
        == "Fine-Grained Benchmark"
    )
    assert (
        paper_helpers.fix_broken_line_hyphenation("Reference-\nBased Verification")
        == "Reference-Based Verification"
    )
    assert (
        paper_helpers.fix_broken_line_hyphenation("pre- and post-processing")
        == "pre- and post-processing"
    )
    assert (
        paper_helpers.fix_broken_line_hyphenation("differ- ent")
        == "different"
    )


def test_fix_broken_line_hyphenation_preserves_url_continuation_blocks():
    relative_url = "stories/news/article/eroeffnet-\ngroessten-makerspace/"
    schemeless_url = "www.science.apa.at/power-\nsearch/17012929664440812974"
    assert paper_helpers.fix_broken_line_hyphenation(relative_url) == relative_url
    assert paper_helpers.fix_broken_line_hyphenation(schemeless_url) == schemeless_url
    assert paper_helpers.fix_broken_line_hyphenation("a/b/this differ-\nent") == "a/b/this different"


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
