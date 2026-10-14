from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import join_wrapped_url_lines


LASEK_ENTRY = (
    "[2] J. Lasek, Z. Szl\u00e1vik, and S. Bhulai, \u201cThe Predictive Power of "
    "Ranking Systems in\nAssociation Football,\u201d International Journal of "
    "Applied Pattern Recognition, vol. 1,\nno. 1, p. 27, 2013. [Online]. "
    "Available: http://www.inderscience.com/link.php?id=\n52339"
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
