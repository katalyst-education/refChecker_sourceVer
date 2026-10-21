from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import clean_url, join_wrapped_url_lines


LASEK_ENTRY = (
    "[2] J. Lasek, Z. Szl\u00e1vik, and S. Bhulai, \u201cThe Predictive Power of "
    "Ranking Systems in\nAssociation Football,\u201d International Journal of "
    "Applied Pattern Recognition, vol. 1,\nno. 1, p. 27, 2013. [Online]. "
    "Available: http://www.inderscience.com/link.php?id=\n52339"
)

CEDTECH_ENTRY = (
    '[2] N. Kara and N. Sevim, "Adaptive Learning Systems: Beyond Teaching '
    'Machines," Contemporary Educational Technology, vol. 4, no. 2, Jun. '
    '2013. [Online]. Available: https://www.cedtech.net/article/\n'
    'adaptive-learning-systems-beyond-teaching-machines-6095'
)


def _numbered_bibliography(entry):
    return (
        '[1] A. Author, "Earlier work," Journal of Tests, 2012.\n'
        f"{entry}\n"
        '[3] B. Other, "Later work," Journal of Tests, 2014.'
    )


def test_join_wrapped_url_lines_repairs_query_value_wrap():
    text = "Available: http://www.inderscience.com/link.php?id=\n52339"
    assert join_wrapped_url_lines(text) == (
        "Available: http://www.inderscience.com/link.php?id=52339"
    )


def test_join_wrapped_url_lines_preserves_printed_hyphen_and_multiple_wraps():
    text = (
        "URL https://methods.\nsagepub.com/book/mono/intro-\n"
        "chpt/monotone-homogeneity-model."
    )
    assert join_wrapped_url_lines(text) == (
        "URL https://methods.sagepub.com/book/mono/intro-"
        "chpt/monotone-homogeneity-model."
    )


def test_join_wrapped_url_lines_does_not_merge_next_entry_or_prose():
    complete = "See https://example.com/page.\nSmith"
    assert join_wrapped_url_lines(complete) == complete

    next_entry = "http://example.com/a?id=\n[3] B. Other, Title, 2014."
    assert join_wrapped_url_lines(next_entry) == next_entry

    text_after = "http://example.com/a?id=\nNext sentence follows here."
    assert join_wrapped_url_lines(text_after) == text_after


def test_join_wrapped_url_with_newline_normalized_to_space():
    text = (
        "[Online]. Available: https://www.cedtech.net/article/ "
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert join_wrapped_url_lines(text) == (
        "[Online]. Available: https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )


def test_numbered_pdf_reference_keeps_complete_wrapped_url():
    checker = ArxivReferenceChecker()

    references = checker._parse_references_regex(_numbered_bibliography(LASEK_ENTRY))

    urls = [reference.get("url") for reference in references]
    assert "http://www.inderscience.com/link.php?id=52339" in urls
    lasek = next(r for r in references if "Lasek" in r.get("raw_text", ""))
    assert lasek["url"] == "http://www.inderscience.com/link.php?id=52339"
    assert "Available: 52339" not in lasek["title"]
    assert len(references) == 3


def test_parse_references_cascade_keeps_complete_wrapped_url_offline():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"

    references = checker.parse_references(_numbered_bibliography(LASEK_ENTRY))

    urls = [reference.get("url") for reference in references]
    assert "http://www.inderscience.com/link.php?id=52339" in urls
    assert len(references) == 3


def test_screenshot_shaped_cedtech_url_is_complete_in_shared_parser():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"
    bibliography = _numbered_bibliography(CEDTECH_ENTRY)

    references = checker.parse_references(bibliography)

    kara = next(reference for reference in references if "Kara" in reference.get("raw_text", ""))
    assert kara["url"] == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert "article/\nadaptive-learning" in bibliography


def test_screenshot_shaped_cedtech_url_is_complete_after_line_whitespace_normalization():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"
    bibliography = _numbered_bibliography(CEDTECH_ENTRY).replace(
        "article/\nadaptive-learning",
        "article/ adaptive-learning",
    )

    references = checker.parse_references(bibliography)

    kara = next(reference for reference in references if "Kara" in reference.get("raw_text", ""))
    assert kara["url"] == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )


def test_wrapped_tu_darmstadt_hostname_and_escaped_underscores_are_repaired():
    text = (
        "https://ww\n"
        "w.tu-darmstadt.de/universitaet/aktuelles\\_meldungen/"
        "einzelansicht\\_525\n"
        "888.de.jsp"
    )
    assert join_wrapped_url_lines(text) == (
        "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
        "einzelansicht_525888.de.jsp"
    )


def test_wrapped_jstor_numeric_suffix_is_repaired():
    text = "https://www.jstor.org/stable/jeductechsoci.8.3.\n26"
    assert join_wrapped_url_lines(text) == (
        "https://www.jstor.org/stable/jeductechsoci.8.3.26"
    )


def test_wrapped_cedtech_path_is_repaired_after_space_normalization():
    text = (
        "https://www.cedtech.net/article/ "
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert join_wrapped_url_lines(text) == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )


def test_wrapped_query_value_and_following_parameter_are_repaired():
    text = "https://example.org/article?id=\n12345&lang=en"
    assert join_wrapped_url_lines(text) == (
        "https://example.org/article?id=12345&lang=en"
    )


def test_all_supplied_wrapped_urls_are_extracted_from_reference_text():
    wrapped_urls = [
        (
            "https://ww\n"
            "w.tu-darmstadt.de/universitaet/aktuelles\\_meldungen/"
            "einzelansicht\\_525\n"
            "888.de.jsp",
            "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
            "einzelansicht_525888.de.jsp",
        ),
        (
            "https://www.jstor.org/stable/jeductechsoci.8.3.\n26",
            "https://www.jstor.org/stable/jeductechsoci.8.3.26",
        ),
        (
            "https://www.cedtech.net/article/\n"
            "adaptive-learning-systems-beyond-teaching-machines-6095",
            "https://www.cedtech.net/article/"
            "adaptive-learning-systems-beyond-teaching-machines-6095",
        ),
        (
            "http://www.inderscience.com/link.php?id=\n52339",
            "http://www.inderscience.com/link.php?id=52339",
        ),
    ]
    for index, (wrapped_url, expected_url) in enumerate(wrapped_urls):
        entry = (
            f'[1] A. Author, "Title {index}," Journal, 2020. {wrapped_url}'
        )
        references = ArxivReferenceChecker()._parse_references_regex(entry)
        assert references[0]["url"] == expected_url


def test_wrapped_url_repair_stops_at_access_metadata_and_strips_final_period():
    text = "https://example.com.\naccessed: Nov. 07, 2025"
    assert join_wrapped_url_lines(text) == text
    assert clean_url(text.splitlines()[0]) == "https://example.com"

    year_after_url = "https://example.com/article.\n2025"
    assert join_wrapped_url_lines(year_after_url) == year_after_url
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(
        '[1] A. Author, "A title," Journal, 2020. ' + text
    )
    assert references[0]["url"] == "https://example.com"


def test_wrapped_url_repair_does_not_consume_next_reference_marker():
    text = "https://example.com/page [37] Smith, J..."
    assert join_wrapped_url_lines(text) == text
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(
        '[1] A. Author, "A title," Journal, 2020. ' + text
    )
    assert references[0]["url"] == "https://example.com/page"


def test_wrapped_url_repair_does_not_join_ordinary_prose():
    text = "https://example.com/some-path\nand normal prose follows here"
    assert join_wrapped_url_lines(text) == text
    after_slash = "https://example.com/article/\nSmith et al. continue here"
    assert join_wrapped_url_lines(after_slash) == after_slash


def test_complete_doi_url_is_unchanged():
    text = "https://doi.org/10.1234/example.123"
    assert join_wrapped_url_lines(text) == text


def test_clean_url_preserves_balanced_parentheses():
    assert clean_url("https://example.org/wiki/Title_(example).") == (
        "https://example.org/wiki/Title_(example)"
    )


def test_two_references_with_wrapped_urls_remain_separate():
    bibliography = (
        '[1] A. Author, "First title," Journal, 2020. '
        "https://example.org/article?id=\n12345\n"
        '[2] B. Author, "Second title," Journal, 2021. '
        "https://example.net/item/456"
    )
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(bibliography)
    assert len(references) == 2
    assert [reference["url"] for reference in references] == [
        "https://example.org/article?id=12345",
        "https://example.net/item/456",
    ]
