"""Contracts for the result shape shared by scan and single-ref rechecks."""

from backend.reference_result import (
    derive_corrected_reference,
    merge_fresh_verification,
    project_verification_result,
)


def _reference():
    return {
        "id": "ref-17",
        "index": 17,
        "title": "Cited title",
        "authors": ["C. Author"],
        "year": 2020,
        "venue": "Cited venue",
        "doi": "10.1000/cited",
        "citation_contexts": [{"sentence": "As shown in [17]."}],
        "citation_count": 1,
    }


def _verified():
    return {
        "title": "Canonical title",
        "authors": ["Canonical Author"],
        "year": 2021,
        "venue": "Canonical venue",
        "doi": "10.1000/canonical",
        "source": "not-the-display-source",
        "_matched_database": "CrossRef",
        "_verification_basis": "catalogue",
        "_evidence_reconciliation": {
            "decision": "accept_cited_authors",
            "supporting_sources": ["CrossRef", "OpenAlex"],
        },
    }


def test_projection_preserves_cited_metadata_and_separates_verified_metadata():
    result = project_verification_result(
        _reference(), _verified(), [], "https://doi.org/10.1000/canonical",
        index=17, enrich_enabled=False,
    )

    assert result["title"] == "Cited title"
    assert result["year"] == 2020
    assert result["verified_title"] == "Canonical title"
    assert result["verified_year"] == 2021
    assert result["matched_database"] == "CrossRef"
    assert result["evidence_reconciliation"]["decision"] == "accept_cited_authors"


def test_resolved_catalogue_metadata_conflict_is_informational():
    result = project_verification_result(
        _reference(), _verified(), [{
            "info_type": "metadata_conflict",
            "info_details": "Two catalogues confirm the cited personal authors.",
            "metadata_classification": "catalogue_author_conflict_resolved",
        }], "https://doi.org/10.1000/canonical", index=17, enrich_enabled=False,
    )

    assert result["status"] == "verified"
    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["infos"][0]["info_type"] == "metadata_conflict"


def test_author_position_correction_preserves_other_cited_authors():
    reference = {
        "authors": ["A. Sinha", "P. S", "R. Balaji", "N. Bhatt"],
    }
    findings = [{
        "warning_type": "author",
        "warning_details": "Author 2 mismatch\n       cited:  P. S\n       actual: Pavan Kumar S",
        "actual_value": "Pavan Kumar S",
    }]

    correction = derive_corrected_reference(reference, findings)

    assert correction == {
        "authors": ["A. Sinha", "Pavan Kumar S", "R. Balaji", "N. Bhatt"],
    }


def test_projection_exposes_author_position_correction_for_apply_fix():
    reference = {
        "title": "BiCA",
        "authors": ["A. Sinha", "P. S", "R. Balaji", "N. Bhatt"],
    }
    finding = {
        "warning_type": "author",
        "warning_details": "Author 2 mismatch\n       cited:  P. S\n       actual: Pavan Kumar S",
        "actual_value": "Pavan Kumar S",
    }

    result = project_verification_result(reference, {}, [finding], None, enrich_enabled=False)

    assert result["corrected_reference"] == {
        "authors": ["A. Sinha", "Pavan Kumar S", "R. Balaji", "N. Bhatt"],
    }
