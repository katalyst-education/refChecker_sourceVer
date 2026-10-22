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


def test_webui_numbered_parser_extracts_pdf_book_metadata_and_url_year():
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )
    bibliography = (
        "[1] S. E. Embretson and S. P. Reise, Item Response Theory for "
        "Psychologists, ser. Multivariate applications book series. "
        "Mahwah, NJ, USA: L. Erlbaum Associates, 2000.\n"
        "[2] R. J. De Ayala, The Theory and Practice of Item Response Theory, "
        "2nd ed., ser. Methodology in the social sciences. New York, NY, USA: "
        "The Guilford Press, Apr. 2022.\n"
        "[3] L. M. Crocker and J. Algina, Introduction to Classical and Modern "
        "Test Theory. Mason, Ohio: Cengage Learning, 2008.\n"
        "[4] E. Gamma, R. Helm, R. Johnson, and J. Vlissides, Design Patterns: "
        "Elements of Reusable Object-Oriented Software, ser. Addison-Wesley "
        "professional computing series. Reading, MA, USA: Addison-Wesley, 1994.\n"
        "[5] A. P. Bradley, \ufffdThe Use of the Area Under the ROC Curve in the "
        "Evaluation of Machine Learning Algorithms,\ufffd Pattern Recognition, "
        "vol. 30, no. 7, pp. 1145\ufffd1159, Jul. 1997. [Online]. Available: "
        "https://linkinghub.elsevier.com/retrieve/pii/S0031320396001422"
    )

    expected_titles = [
        "Item Response Theory for Psychologists",
        "The Theory and Practice of Item Response Theory",
        "Introduction to Classical and Modern Test Theory",
        "Design Patterns: Elements of Reusable Object-Oriented Software",
        "The Use of the Area Under the ROC Curve in the Evaluation of Machine Learning Algorithms",
    ]
    expected_authors = [
        ["S. E. Embretson", "S. P. Reise"],
        ["R. J. De Ayala"],
        ["L. M. Crocker", "J. Algina"],
        ["E. Gamma", "R. Helm", "R. Johnson", "J. Vlissides"],
        ["A. P. Bradley"],
    ]
    expected_years = [2000, 2022, 2008, 1994, 1997]

    biblatex_references = checker._parse_biblatex_references(bibliography)
    references = checker.parse_references(bibliography)
    for parsed_references in (biblatex_references, references):
        assert len(parsed_references) == 5
        assert [reference["title"] for reference in parsed_references] == expected_titles
        assert [reference["authors"] for reference in parsed_references] == expected_authors
        assert [reference["year"] for reference in parsed_references] == expected_years
