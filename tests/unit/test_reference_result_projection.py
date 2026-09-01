"""Contracts for the result shape shared by scan and single-ref rechecks."""

from backend.reference_result import (
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


def test_fresh_reverify_replaces_all_display_derived_state():
    cited = _reference()
    projection = project_verification_result(
        cited,
        _verified(),
        [{
            "warning_type": "venue",
            "warning_details": "Venue differs",
            "requires_user_confirmation": True,
        }],
        "https://doi.org/10.1000/canonical",
        index=17,
        enrich_enabled=False,
    )
    stored = {
        **cited,
        "matched_database": "Semantic Scholar",
        "matched_db": "stale-alias",
        "errors": [{"error_type": "author", "error_details": "stale"}],
        "warnings": [],
        "infos": [{"info_type": "stale"}],
        "suggestions": [{"suggestion_type": "stale"}],
        "authoritative_urls": [{"url": "https://stale.example"}],
        "enrichment": {"cited_by_count": 99},
        "hallucination_assessment": {"verdict": "LIKELY"},
        "hallucination_check_pending": True,
        "corrected_reference": {"title": "stale"},
    }

    updated = merge_fresh_verification(stored, projection)

    for key in (
        "status", "errors", "warnings", "infos", "suggestions",
        "authoritative_urls", "matched_database", "verification_basis",
        "evidence_reconciliation", "enrichment", "corrected_reference", "hallucination_assessment",
        "verified_title", "verified_authors", "verified_year", "verified_venue",
        "verified_doi",
    ):
        assert updated.get(key) == projection.get(key)
    assert updated["matched_database"] == "CrossRef"
    assert "matched_db" not in updated
    assert "hallucination_check_pending" not in updated
    assert updated["id"] == "ref-17"
    assert updated["citation_contexts"] == cited["citation_contexts"]


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
