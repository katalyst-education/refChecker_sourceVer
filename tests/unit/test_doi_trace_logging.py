import logging

import refchecker.checkers.crossref as crossref_module
from refchecker.checkers.crossref import CrossRefReferenceChecker
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.llm.providers import _doi_trace_contexts


def test_doi_trace_context_preserves_visible_pdf_line_break():
    text = (
        "[18] A. Krzyzewska. Climate change in Poland. "
        "doi:10.2478/mgrsd-\n2023-0017\n"
        "[19] Next reference. doi:10.1000/next"
    )

    contexts = _doi_trace_contexts(text)

    assert contexts[0] == "10.2478/mgrsd-\\n2023-0017"
    assert contexts[1] == "10.1000/next"


def test_llm_reference_parser_logs_input_and_parsed_doi(caplog):
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    ref_text = (
        "A. Krzyzewska#Climate change in Poland - the assessment of the conversation "
        "with ChatGPT#Miscellanea Geographica#2024#"
        "https://doi.org/10.2478/mgrs-2023-0017"
    )

    with caplog.at_level(logging.INFO, logger="refchecker.core.refchecker"):
        parsed = checker._create_structured_llm_references(ref_text)

    assert parsed["doi"] == "10.2478/mgrs-2023-0017"
    assert "[DOI_TRACE] stage=parser_input" in caplog.text
    assert "[DOI_TRACE] stage=parser_output" in caplog.text
    assert "10.2478/mgrs-2023-0017" in caplog.text


def test_crossref_logs_direct_miss_title_fallback_and_mismatch(monkeypatch, caplog):
    checker = CrossRefReferenceChecker()
    work = {
        "title": ["Climate change in Poland - the assessment of the conversation with ChatGPT"],
        "DOI": "10.2478/mgrsd-2023-0017",
        "author": [],
        "published": {"date-parts": [[2024]]},
        "URL": "https://doi.org/10.2478/mgrsd-2023-0017",
    }
    monkeypatch.setattr(checker, "get_work_by_doi", lambda _doi: None)
    monkeypatch.setattr(checker, "search_works", lambda _title, _year: [work])
    monkeypatch.setattr(crossref_module, "find_best_match", lambda *_args: (work, 1.0))
    monkeypatch.setattr(
        "refchecker.utils.doi_utils.validate_doi_resolves",
        lambda _doi: False,
    )

    reference = {
        "title": "Climate change in Poland - the assessment of the conversation with ChatGPT",
        "authors": [],
        "year": 2024,
        "doi": "10.2478/mgrs-2023-0017",
    }
    with caplog.at_level(logging.INFO, logger="refchecker.checkers.crossref"):
        verified, errors, _url = checker.verify_reference(reference)

    assert verified["DOI"] == "10.2478/mgrsd-2023-0017"
    assert errors[0]["error_type"] == "doi"
    assert "stage=crossref_input" in caplog.text
    assert "stage=crossref_direct_lookup status=not_found" in caplog.text
    assert "stage=crossref_title_fallback" in caplog.text
    assert "stage=crossref_compare result=mismatch" in caplog.text
