from refchecker.utils.publication_years import reconcile_publication_year


def _year_warning():
    return {
        "warning_type": "year",
        "warning_details": "Year mismatch:\n       cited:  2025\n       actual: 2024",
        "cited_value": "2025",
        "actual_value": "2024",
        "ref_year_correct": "2024",
    }


def test_supported_cited_year_becomes_neutral_metadata_discrepancy():
    reference = {"title": "Tumor board study", "year": 2025}
    verified = {
        "year": 2024,
        "_matched_database": "Semantic Scholar",
        "_publication_year_sources": [
            {"source": "PubMed/NCBI", "year": 2025},
            {"source": "Semantic Scholar", "year": 2024},
        ],
    }

    verified, issues = reconcile_publication_year(reference, verified, [_year_warning()])

    assert issues == [{
        "info_type": "publication_year_discrepancy",
        "info_details": "Publication dates differ across databases",
        "cited_value": "2025",
        "source_years": [
            {"source": "PubMed/NCBI", "year": 2025},
            {"source": "Semantic Scholar", "year": 2024},
        ],
        "metadata_classification": "metadata_discrepancy",
    }]
    assert verified["_publication_year_assessment"]["classification"] == "metadata_discrepancy"


def test_consistent_disagreement_becomes_likely_citation_error_warning():
    reference = {"title": "Example", "year": 2025}
    verified = {
        "year": 2024,
        "_matched_database": "Semantic Scholar",
        "_publication_year_sources": [
            {"source": "Crossref", "year": 2024},
            {"source": "OpenAlex", "year": 2024},
        ],
    }

    verified, issues = reconcile_publication_year(reference, verified, [_year_warning()])

    assert len(issues) == 1
    assert issues[0]["warning_type"] == "year"
    assert issues[0]["warning_details"] == "Likely citation error"
    assert issues[0]["metadata_classification"] == "likely_citation_error"
    assert verified["_publication_year_assessment"]["classification"] == "likely_citation_error"


def test_single_disagreeing_source_does_not_overclaim_likely_error():
    reference = {"title": "Example", "year": 2025}
    verified = {
        "year": 2024,
        "_matched_database": "Semantic Scholar",
        "_publication_year_sources": [],
    }
    original = _year_warning()

    _, issues = reconcile_publication_year(reference, verified, [original])

    assert issues == [original]
    assert "_publication_year_assessment" not in verified


def test_webui_formatter_keeps_metadata_discrepancy_verified():
    from backend.refchecker_wrapper import ProgressRefChecker

    wrapper = object.__new__(ProgressRefChecker)
    wrapper.enrich_enabled = False
    verified = {
        "title": "Tumor board study",
        "year": 2024,
        "_matched_database": "Semantic Scholar",
        "_publication_year_assessment": {
            "classification": "metadata_discrepancy",
            "cited_year": 2025,
            "sources": [
                {"source": "PubMed/NCBI", "year": 2025},
                {"source": "Semantic Scholar", "year": 2024},
            ],
        },
    }
    info = {
        "info_type": "publication_year_discrepancy",
        "info_details": "Publication dates differ across databases",
        "cited_value": "2025",
        "source_years": verified["_publication_year_assessment"]["sources"],
        "metadata_classification": "metadata_discrepancy",
    }

    result = wrapper._format_verification_result(
        {"title": "Tumor board study", "authors": [], "year": 2025},
        index=1,
        verified_data=verified,
        errors=[info],
        url="https://www.semanticscholar.org/paper/example",
    )

    assert result["status"] == "verified"
    assert result["warnings"] == []
    assert result["errors"] == []
    assert result["infos"] == [{
        "info_type": "publication_year_discrepancy",
        "info_details": "Publication dates differ across databases",
        "cited_value": "2025",
        "source_years": verified["_publication_year_assessment"]["sources"],
        "metadata_classification": "metadata_discrepancy",
    }]


def test_shared_hybrid_postprocess_reconciles_for_every_execution_path():
    from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker

    checker = object.__new__(EnhancedHybridReferenceChecker)
    checker.arxiv_citation = None
    verified = {
        "year": 2024,
        "_matched_database": "Semantic Scholar",
        "_publication_year_sources": [
            {"source": "PubMed/NCBI", "year": 2025},
            {"source": "Semantic Scholar", "year": 2024},
        ],
    }

    _, issues, _ = checker._postprocess_verification(
        verified,
        [_year_warning()],
        "https://www.semanticscholar.org/paper/example",
        {"title": "Tumor board study", "year": 2025},
    )

    assert [issue.get("info_type") for issue in issues] == ["publication_year_discrepancy"]


def test_old_cached_year_warning_is_refreshed_for_reconciliation():
    from backend.refchecker_wrapper import ProgressRefChecker

    old_result = {
        "status": "warning",
        "doi": "10.2196/64364",
        "errors": [],
        "warnings": [{"error_type": "year", "error_details": "Year mismatch"}],
    }
    reconciled_result = {
        **old_result,
        "status": "verified",
        "warnings": [],
        "publication_year_assessment": {"classification": "metadata_discrepancy"},
    }

    assert ProgressRefChecker._can_reuse_cached_result(old_result) is False
    assert ProgressRefChecker._can_reuse_cached_result(reconciled_result) is True
