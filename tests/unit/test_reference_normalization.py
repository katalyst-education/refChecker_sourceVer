import re

from refchecker.core.refchecker import ArxivReferenceChecker


def test_numbered_parser_backfills_doi_from_raw_reference_text():
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )
    references = checker._parse_references_regex(
        "[1] Smith J. 2020. A clearly named paper title. "
        "Journal of Testing. DOI: 10.1234/example-doi.\n"
        "[2] Jones A. 2021. Another clear paper title. Systems Review."
    )

    assert len(references) == 2
    assert references[0]["doi"] == "10.1234/example-doi"


def test_biblatex_parser_exposes_the_shared_venue_field():
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )
    references = checker._parse_references_regex(
        '[1] Jane Doe and John Smith. "Example Work". '
        "In: Example Proceedings (2020)."
    )

    assert references[0]["venue"] == references[0]["journal"]


def test_failed_biblatex_fallback_does_not_return_invalid_references():
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )

    references = checker._parse_references_regex("[1] A\n[2] B\n[3] C")

    assert references == []
    assert checker.fatal_error is True


def test_generic_parser_preserves_numbered_entry_order_across_reference_types():
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )
    references = checker._parse_references_regex(
        "[1] Smith J. 2020. First numbered paper title. "
        "Journal of Testing.\n"
        "[2] Jones A. 2021. Second numbered paper title. "
        "https://doi.org/10.1234/example-doi"
    )

    numbers = [
        int(match.group(1))
        for reference in references
        if (match := re.search(
            r"^\s*\[(\d+)\]",
            reference.get("raw_text", ""),
        ))
    ]
    assert numbers == [1, 2]
