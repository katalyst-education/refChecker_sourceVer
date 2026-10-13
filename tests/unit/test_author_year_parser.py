"""Unit tests for deterministic author-year bibliography segmentation and parsing."""

import re
from pathlib import Path

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker, _AUTHOR_YEAR_ENTRY_START_RE
from refchecker.utils.text_utils import validate_parsed_references

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACADEMIC_BIB = REPOSITORY_ROOT / "paper" / "paper.bib"


@pytest.fixture
def checker():
    return ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )


REAL_PAPER_BIBLIOGRAPHY = (
    'Allen Institute for AI. 2024. "Semantic Scholar Academic Graph Api." '
    'https: //www.semanticscholar.org/product/api.\n'
    'Crossref. 2025. "Crossref Rest Api." '
    'https://www.crossref.org/documentation /retrieve-metadata/rest-api/.\n'
    'Hu, Xiangkun, Dongyu Ru, Lin Qiu, Qipeng Guo, Yun Luo, Pengfei Li, '
    'Yue Zhang, and Zheng Zhang. 2024. "RefChecker: Reference-Based '
    'Fine-Grained Hallucination Checker and Benchmark for Large Language '
    'Models." arXiv Preprint arXiv:2405.14486. https://arxiv.org/abs/2405.14486.\n'
    'Priem, Jason, Heather Piwowar, and Richard Orr. 2022. "OpenAlex: A Fully-Open '
    'Index of Scholarly Works, Authors, Venues, Institutions, and '
    'Concepts." arXiv Preprint arXiv:2205.01833. https://arxiv.org/abs/2205.01833.\n'
    'Recite. 2025. "Recite Reference Checker." https://reciteworks.com/.\n'
    'Scite. 2025. "Scite Reference Check." https://scite.ai/.'
)


def test_segment_real_paper_entries(checker):
    """The six real entries from paper/paper.pdf must segment into exactly 6 entries."""
    entries = checker._split_author_year_reference_entries(REAL_PAPER_BIBLIOGRAPHY)
    assert len(entries) == 6
    assert entries[0].startswith("Allen Institute for AI. 2024.")
    assert entries[1].startswith("Crossref. 2025.")
    assert entries[2].startswith("Hu, Xiangkun, Dongyu Ru,")
    assert entries[3].startswith("Priem, Jason, Heather Piwowar,")
    assert entries[4].startswith("Recite. 2025.")
    assert entries[5].startswith("Scite. 2025.")


def test_author_year_reference_after_leading_page_number(checker):
    bibliography = (
        'Recite. 2025. "Recite Reference Checker." https://reciteworks.com/.\n'
        '3 Scite. 2025. "Scite Reference Check." https://scite.ai/.'
    )

    entries = checker._split_author_year_reference_entries(bibliography)

    assert len(entries) == 2
    assert entries[1].startswith("Scite. 2025.")
    assert "3 Scite" not in entries[1]


def test_parse_real_paper_entries_against_bibtex(checker):
    """Verify parsed metadata of the six real entries against ground-truth BibTeX."""
    entries = checker._split_author_year_reference_entries(REAL_PAPER_BIBLIOGRAPHY)
    parsed = checker._parse_author_year_references(entries)
    assert len(parsed) == 6

    # Validate each entry individually and as a batch
    val = validate_parsed_references(parsed, require_all=True, expected_count=6)
    assert val["is_valid"] is True
    assert val["quality_score"] == 1.0

    bib_entries = checker._parse_bibtex_references(ACADEMIC_BIB.read_text(encoding="utf-8"))
    assert len(bib_entries) == 6

    # Build title -> parsed entry map for order-insensitive lookup
    by_title_key = {
        re.sub(r"[^a-z0-9]", "", r["title"].lower()): r
        for r in parsed
    }

    for bib in bib_entries:
        key = re.sub(r"[^a-z0-9]", "", bib["title"].lower())
        assert key in by_title_key, f"Missing title in parsed references: {bib['title']}"
        matched = by_title_key[key]
        assert matched["year"] == bib["year"]
        assert len(matched["authors"]) > 0

    # Specifically verify multi-author reconstruction
    hu_ref = next(r for r in parsed if "RefChecker" in r["title"])
    assert hu_ref["authors"] == [
        "Xiangkun Hu", "Dongyu Ru", "Lin Qiu", "Qipeng Guo",
        "Yun Luo", "Pengfei Li", "Yue Zhang", "Zheng Zhang",
    ]
    assert hu_ref["arxiv_id"] == "2405.14486"
    assert hu_ref["url"] == "https://arxiv.org/abs/2405.14486"

    priem_ref = next(r for r in parsed if "OpenAlex" in r["title"])
    assert (
        priem_ref["title"]
        == "OpenAlex: A Fully-Open Index of Scholarly Works, Authors, Venues, Institutions, and Concepts"
    )
    assert priem_ref["authors"] == ["Jason Priem", "Heather Piwowar", "Richard Orr"]
    assert priem_ref["arxiv_id"] == "2205.01833"


def test_author_parsing_formats(checker):
    """Test author string handling: single, inverted, initials, et al., and corporate."""
    # Corporate
    assert checker._parse_author_year_authors("Allen Institute for AI") == ["Allen Institute for AI"]
    assert checker._parse_author_year_authors("Crossref") == ["Crossref"]

    # Inverted single
    assert checker._parse_author_year_authors("Knuth, Donald E.") == ["Donald E. Knuth"]

    # Inverted first author with standard subsequent authors (Chicago / APA style)
    assert checker._parse_author_year_authors("Smith, John, Jane Doe, and Bob Brown") == [
        "John Smith", "Jane Doe", "Bob Brown"
    ]

    # Standard order with initials
    assert checker._parse_author_year_authors("J. D. Smith and A. B. Jones") == [
        "J. D. Smith", "A. B. Jones"
    ]

    # Et al.
    authors = checker._parse_author_year_authors("Vaswani, Ashish, et al.")
    assert "Ashish Vaswani" in authors
    assert "et al" in authors or "et al." in authors


def test_year_formats(checker):
    """Test standard unparenthesized, parenthesized, and letter-suffixed years."""
    raw1 = 'Smith, John. 2020. "A Great Paper." Journal of Testing 1: 1-10.'
    raw2 = 'Smith, John (2020). "A Great Paper." Journal of Testing 1: 1-10.'
    raw3 = 'Smith, John. 2020a. "A Great Paper." Journal of Testing 1: 1-10.'

    parsed1 = checker._parse_single_author_year_entry(raw1)
    parsed2 = checker._parse_single_author_year_entry(raw2)
    parsed3 = checker._parse_single_author_year_entry(raw3)

    assert parsed1["year"] == 2020
    assert parsed2["year"] == 2020
    assert parsed3["year"] == 2020


def test_title_formats(checker):
    """Test quoted (double, curly, single) and unquoted title extraction."""
    raw_double = 'Doe, Jane. 2021. "Testing Double Quotes." In Proceedings of Foo.'
    raw_curly = 'Doe, Jane. 2021. “Testing Curly Quotes.” In Proceedings of Foo.'
    raw_single = 'Doe, Jane. 2021. ‘Testing Single Quotes.’ In Proceedings of Foo.'
    raw_unquoted = 'Doe, Jane. 2021. Testing Unquoted Title Sentence. In Proceedings of Foo.'

    p_double = checker._parse_single_author_year_entry(raw_double)
    p_curly = checker._parse_single_author_year_entry(raw_curly)
    p_single = checker._parse_single_author_year_entry(raw_single)
    p_unquoted = checker._parse_single_author_year_entry(raw_unquoted)

    assert p_double["title"] == "Testing Double Quotes"
    assert p_curly["title"] == "Testing Curly Quotes"
    assert p_single["title"] == "Testing Single Quotes"
    assert p_unquoted["title"] == "Testing Unquoted Title Sentence"


def test_multiline_and_linebreak_preservation(checker):
    """Line breaks and space artifacts in URLs must be handled cleanly."""
    raw = (
        'Goodfellow, Ian,\n'
        'Yoshua Bengio, and Aaron Courville.\n'
        '2016. "Deep Learning."\n'
        'MIT Press. https: //www.deeplearningbook.org/.'
    )
    parsed = checker._parse_single_author_year_entry(raw)
    assert parsed is not None
    assert "Ian Goodfellow" in parsed["authors"]
    assert "Yoshua Bengio" in parsed["authors"]
    assert "Aaron Courville" in parsed["authors"]
    assert parsed["year"] == 2016
    assert parsed["title"] == "Deep Learning"
    assert parsed["url"] == "https://www.deeplearningbook.org/"
    assert parsed["raw_text"] == raw


def test_merged_multi_reference_rejected(checker):
    """A merged multi-reference entry must be flagged and rejected by validation."""
    merged_raw = (
        'Smith, John. 2020. "First Paper." Journal A. '
        'Doe, Jane. 2021. "Second Paper." Journal B.'
    )
    parsed = checker._parse_single_author_year_entry(merged_raw)
    assert parsed is not None
    assert parsed.get("is_merged_artifact") is True

    # When validated, require_all=True must reject the merged artifact
    val = validate_parsed_references([parsed], require_all=True)
    assert val["is_valid"] is False


def test_numbered_references_not_affected(checker):
    """Numbered bibliographies should not be segmented by author-year splitter."""
    numbered_bib = (
        '[1] A. Smith and B. Jones. "An informative title for reference one." Journal of Testing, 2020.\n'
        '[2] B. Jones and C. Brown. "Another informative title for reference two." Conference on Systems, 2021.\n'
        '[3] C. Clark and D. Davis. "A third informative title for reference three." Nature Review, 2022.'
    )
    # Numbered splitter finds them
    numbered = checker._split_numbered_reference_entries(numbered_bib)
    assert len(numbered) == 3

    # parse_references routes to regex numbered extraction
    parsed = checker.parse_references(numbered_bib)
    assert len(parsed) == 3
    assert checker.last_reference_parser_method == "regex"
    assert checker.fatal_error is False


def test_malformed_author_year_entry_handling(checker):
    """Entries missing critical fields must not fabricate data and must fail validation."""
    bad_entry = "Some arbitrary heading or incomplete sentence with no author or year."
    parsed = checker._parse_single_author_year_entry(bad_entry)
    assert parsed is None

    # When parsed via _parse_author_year_references, it yields an invalid placeholder
    parsed_list = checker._parse_author_year_references([bad_entry])
    assert len(parsed_list) == 1
    val = validate_parsed_references(parsed_list, require_all=True)
    assert val["is_valid"] is False


def test_offline_unsupported_when_author_year_fails_validation(checker):
    """When author-year entries fail validation without LLM, it sets fatal_error and unsupported."""
    # A bibliography with entries that fail validation
    invalid_bib = (
        "Author One. 2020.\n"
        "Author Two. 2021.\n"
    )
    parsed = checker.parse_references(invalid_bib)
    assert parsed == []
    assert checker.last_reference_parser_method == "unsupported"
    assert checker.fatal_error is True
    assert "Unsupported author-year bibliography format" in checker.fatal_error_message
