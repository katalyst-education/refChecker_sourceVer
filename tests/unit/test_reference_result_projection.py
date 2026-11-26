"""Contracts for the result shape shared by scan and single-ref rechecks."""

from unittest.mock import AsyncMock

import pytest

from backend.database import _sanitize_loaded_reference_results
from backend.refchecker_wrapper import _diff_cited_vs_truth
from backend.reference_result import (
    citation_verification_input,
    derive_corrected_reference,
    merge_fresh_verification,
    project_verification_result,
)
from refchecker.utils.text_utils import compare_authors, format_corrected_reference


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


def test_projection_keeps_source_and_cited_metadata_when_display_uses_verified_doi():
    reference = _reference()
    reference.pop("doi")
    reference["extraction_provenance"] = {
        "parser": "regex", "source_text": "[17] C. Author, Cited title, 2020.", "pdf_page": 5,
    }

    result = project_verification_result(reference, _verified(), [], None, enrich_enabled=False)
    restored = citation_verification_input(result)

    assert result["doi"] == "10.1000/canonical"
    assert "doi" not in restored
    assert restored["authors"] == ["C. Author"]
    assert restored["extraction_provenance"] == reference["extraction_provenance"]
    restored["extraction_provenance"]["pdf_page"] = 6
    assert result["extraction_provenance"]["pdf_page"] == 5


def test_preprint_fallback_does_not_replace_publication_identity_from_doi_url():
    publication_doi = "10.1109/cvpr.2016.90"
    arxiv_url = "https://arxiv.org/abs/1512.03385"
    reference = dict(_reference(), url=f"https://doi.org/{publication_doi}", cited_url=arxiv_url)
    reference.pop("doi")
    evidence = {
        "title": reference["title"], "year": 2015, "url": arxiv_url,
        "_verification_basis": "arxiv_preprint_fallback",
        "externalIds": {"DOI": "10.48550/arxiv.1512.03385", "ArXiv": "1512.03385"},
    }
    result = project_verification_result(reference, evidence, [{
        "error_type": "unverified", "error_details": "Only the preprint was checked",
    }], arxiv_url, enrich_enabled=True)

    assert result["status"] == "unverified"
    assert result["doi"] == publication_doi
    assert not result["arxiv_id"]
    assert "verified_year" not in result
    assert result["supporting_evidence"]["url"] == arxiv_url


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


def test_handbook_membership_warning_preserves_the_cited_contributors():
    authors = ["J. W. Fleming", "M. J. Weber", "G. W. Day", "et al."]
    reference = {"title": "Handbook of optical materials", "authors": authors}
    verified = {"title": reference["title"], "authors": ["Marvin J. Weber"]}
    matches, details = compare_authors(authors, verified["authors"])
    assert not matches
    finding = {"warning_type": "author", "warning_details": details}

    result = project_verification_result(reference, verified, [finding], None, enrich_enabled=False)
    assert result["status"] == "warning"
    assert result["warnings"][0]["error_details"] == details
    assert result["authors"] == result["cited_metadata"]["authors"] == authors
    assert result["verified_authors"] == ["Marvin J. Weber"]
    assert result["corrected_reference"] is None
    assert derive_corrected_reference(reference, [finding]) is None
    assert ", ".join(authors) in format_corrected_reference(reference, verified, finding)

    errors, warnings = _diff_cited_vs_truth(reference, {"authors": "Marvin J. Weber"})
    assert errors == []
    assert warnings[0]["warning_details"] == details
    assert derive_corrected_reference(reference, warnings) is None

    [loaded] = _sanitize_loaded_reference_results([{
        **result,
        "corrected_reference": {"authors": ["Marvin J. Weber", *authors[1:]], "year": 2018},
    }])
    assert loaded["corrected_reference"] == {"year": 2018}
    assert loaded["cited_metadata"]["authors"] == authors


def test_truncated_database_author_list_is_also_review_only():
    authors = ["J. W. Fleming", "G. W. Day"]
    matches, details = compare_authors(authors, ["Marvin J. Weber", "et al."])
    assert not matches
    assert derive_corrected_reference(
        {"authors": authors}, [{"error_type": "author", "error_details": details}]
    ) is None


@pytest.mark.asyncio
async def test_apply_fix_cannot_use_a_saved_membership_warning_as_an_author_replacement(monkeypatch):
    from backend import main

    authors = ["J. W. Fleming", "M. J. Weber", "et al."]
    verified = ["Marvin J. Weber"]
    _, details = compare_authors(authors, verified)
    reference = {
        "index": 84,
        "ref_uid": "ref-handbook",
        "title": "Handbook of optical materials",
        "authors": authors,
        "warnings": [{"error_type": "author", "error_details": details}],
        "status": "warning",
        "verified_authors": verified,
        "corrected_reference": {"authors": ["Marvin J. Weber", "M. J. Weber", "et al."]},
    }
    monkeypatch.setattr(main.db, "get_check_references", AsyncMock(return_value=[reference]))
    monkeypatch.setattr(main.db, "lookup_verified_reference", AsyncMock(return_value={"result": reference}))
    monkeypatch.setattr(main.db, "replace_check_reference_if_unchanged", AsyncMock(return_value="saved"))
    user = main.UserInfo(id=0, name="Local", provider="local", is_admin=True)

    response = await main.verify_single_reference(
        25, "uid:ref-handbook", main._VerifySingleRequest(apply_correction=True), user,
    )

    verification_input = main.db.lookup_verified_reference.call_args.args[0]
    assert verification_input["authors"] == authors
    assert response["reference"]["authors"] == authors
    assert response["reference"]["corrected_reference"] is None
