"""User decisions for speculative reference-match warnings."""

import pytest

from backend.reference_status import classify_verification_result
from backend.database import _sanitize_loaded_reference_results


def test_candidate_warning_keeps_confirmation_metadata_during_classification():
    status, issues = classify_verification_result(
        {"title": "Original"},
        {"title": "Candidate"},
        [{
            "warning_type": "possible_alternative",
            "warning_details": "Possibly this work was meant.",
            "requires_user_confirmation": True,
            "match_provenance": "author_fallback",
            "ref_title_correct": "Candidate",
        }],
        None,
    )

    assert status == "warning"
    assert issues[0]["requires_user_confirmation"] is True
    assert issues[0]["match_provenance"] == "author_fallback"


@pytest.fixture
def warning_client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as backend_main
    from backend.auth import UserInfo, require_user

    backend_main.app.dependency_overrides[require_user] = (
        lambda: UserInfo(id=1, provider="test")
    )
    existing = [{
        "id": "candidate-1",
        "index": 1,
        "title": "Guidelines for performing Systematic Literature Reviews",
        "status": "warning",
        "errors": [],
        "warnings": [{
            "error_type": "possible_alternative",
            "error_details": "Title and authors could not be found.",
            "requires_user_confirmation": True,
        }],
        "corrected_reference": {"title": "A different candidate"},
    }]
    captured = {}

    async def get_refs(check_id, user_id=None):
        return [dict(ref, warnings=[dict(w) for w in ref["warnings"]]) for ref in existing]

    async def replace_refs(check_id, refs, user_id=None):
        captured["refs"] = refs
        return True

    monkeypatch.setattr(backend_main.db, "get_check_references", get_refs)
    monkeypatch.setattr(backend_main.db, "replace_check_references", replace_refs)

    client = TestClient(backend_main.app)
    try:
        yield client, captured
    finally:
        backend_main.app.dependency_overrides.clear()


def test_dismiss_moves_confirmation_warning_to_audit_list(warning_client):
    client, captured = warning_client
    response = client.post(
        "/api/history/42/references/candidate-1/warning-decision",
        json={"warning_type": "possible_alternative", "decision": "dismissed"},
    )

    assert response.status_code == 200
    reference = response.json()["reference"]
    assert reference["status"] == "unverified"
    assert reference["warnings"] == []
    assert reference["dismissed_warnings"][0]["user_decision"] == "dismissed"
    assert reference["match_decision"] == "kept_cited"
    assert reference["corrected_reference"] is None
    assert reference["dismissed_corrected_reference"]["title"] == "A different candidate"
    assert captured["refs"][0]["dismissed_warnings"]


def test_only_confirmation_warnings_can_be_dismissed(warning_client):
    client, _ = warning_client
    response = client.post(
        "/api/history/42/references/candidate-1/warning-decision",
        json={"warning_type": "year", "decision": "dismissed"},
    )

    assert response.status_code == 404


def test_old_dismissal_is_loaded_as_kept_cited_without_active_candidate():
    loaded = _sanitize_loaded_reference_results([{
        "title": "Original",
        "status": "unverified",
        "corrected_reference": {"title": "Rejected candidate"},
        "dismissed_warnings": [{
            "error_type": "possible_alternative",
            "user_decision": "dismissed",
        }],
    }])[0]

    assert loaded["match_decision"] == "kept_cited"
    assert loaded["corrected_reference"] is None
    assert loaded["dismissed_corrected_reference"]["title"] == "Rejected candidate"
