from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import join_wrapped_url_lines


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

JSTOR_ENTRY = (
    '[2] S. Retalis and A. Papasalouros, "Designing and Generating '
    'Educational Adaptive Hypermedia Applications," Journal of Educational '
    'Technology & Society, vol. 8, no. 3, pp. 26-35, 2005. [Online]. '
    'Available: https://www.jstor.org/stable/jeductechsoci.8.3.\n'
    '26'
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


def test_jstor_period_delimited_numeric_url_wrap_is_preserved():
    bibliography = (
        '[1] A. Author, "Previous work," Journal of Tests, 2004.\n'
        f'{JSTOR_ENTRY}\n'
        '[3] N. A. Anindyaputri, R. A. Yuana, and P. Hatta, "Enhancing '
        'Students Ability," Journal of Tests, 2006.'
    )
    original_bibliography = bibliography

    joined = join_wrapped_url_lines(bibliography)
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"
    references = checker.parse_references(bibliography)
    retalis = next(
        reference for reference in references
        if "Designing and Generating Educational Adaptive Hypermedia Applications"
        in (reference.get("title") or "")
    )

    assert retalis["url"] == (
        "https://www.jstor.org/stable/jeductechsoci.8.3.26"
    )
    assert "26" not in (retalis.get("venue") or "")
    assert len(references) == 3
    assert bibliography == original_bibliography
    assert "https://www.jstor.org/stable/jeductechsoci.8.3.\n26" in bibliography
    assert "https://www.jstor.org/stable/jeductechsoci.8.3.26" in joined


def test_period_delimited_url_wrap_does_not_join_prose_or_reference_marker():
    prose = (
        "[Online]. Available: https://example.org/stable/item.8.3.\n"
        "The following numeric value is 26 words long."
    )
    next_reference = (
        "[Online]. Available: https://example.org/stable/item.8.3.\n"
        "[37] Another reference."
    )
    unrelated_number = (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://example.org/stable/item.8.3.\n"
        "27\n[37] Another reference."
    )

    assert join_wrapped_url_lines(prose) == prose
    assert join_wrapped_url_lines(next_reference) == next_reference
    assert join_wrapped_url_lines(unrelated_number) == unrelated_number


def test_period_delimited_url_wrap_survives_space_normalization():
    text = (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://www.jstor.org/stable/jeductechsoci.8.3. 26\n[37] "
        "Another reference."
    )

    assert join_wrapped_url_lines(text) == (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://www.jstor.org/stable/jeductechsoci.8.3.26\n[37] "
        "Another reference."
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
