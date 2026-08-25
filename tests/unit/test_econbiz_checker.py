import logging
from unittest.mock import Mock, patch

from refchecker.checkers.econbiz import EconBizReferenceChecker
from backend.reference_status import classify_verification_result


CITED_REFERENCE = {
    "title": "Methoden zur Wiederverwendung von Referenzmodellen – Übersicht und Taxonomie",
    "authors": ["Peter Fettke", "Peter Loos"],
    "year": 2002,
}


def test_title_query_preserves_unicode_terms_and_ignores_punctuation():
    query = EconBizReferenceChecker._title_terms_query(CITED_REFERENCE["title"])

    assert query.startswith("title:(Methoden zur Wiederverwendung")
    assert "Übersicht" in query
    assert "–" not in query


def test_strict_metadata_match_verifies_reference(monkeypatch):
    checker = EconBizReferenceChecker()
    calls = []

    def fake_search(query, *, fulltext=False, limit=10):
        calls.append((query, fulltext))
        return [{
            "_score": 1.0,
            "id": "10000000001",
            "title": CITED_REFERENCE["title"],
            "creator": ["Fettke, Peter", "Loos, Peter"],
            "date": ["2002"],
            "source": "econis",
            "type": "article",
        }]

    monkeypatch.setattr(checker, "search", fake_search)
    data, errors, url = checker.verify_reference(dict(CITED_REFERENCE))

    assert errors == []
    assert data["econbiz_id"] == "10000000001"
    assert data["authors"] == [{"name": "Fettke, Peter"}, {"name": "Loos, Peter"}]
    assert data["year"] == 2002
    assert url == "https://www.econbiz.de/Record/-/10000000001"
    assert len(calls) == 1
    assert calls[0][1] is False


def test_fulltext_container_evidence_verifies_reference(monkeypatch):
    checker = EconBizReferenceChecker()

    def fake_search(query, *, fulltext=False, limit=10):
        if not fulltext:
            return []
        assert '"Methoden zur Wiederverwendung von Referenzmodellen"' in query
        assert "Fettke AND Loos" in query
        return [{
            "_score": 0.53663725,
            "id": "10005852170",
            "title": "Referenzmodellierung 2002 : Methoden - Modelle - Erfahrungen",
            "contributor": ["Becker, Jörg", "Knackstedt, Ralf"],
            "date": ["2002-08-01"],
            "source": "als-doc",
            "type": "book",
        }]

    monkeypatch.setattr(checker, "search", fake_search)
    data, errors, url = checker.verify_reference(dict(CITED_REFERENCE))

    assert data is not None
    assert url == "https://www.econbiz.de/Record/-/10005852170"
    assert errors == []
    assert data["title"] == CITED_REFERENCE["title"]
    assert data["authors"] == [{"name": "Peter Fettke"}, {"name": "Peter Loos"}]
    assert data["year"] == 2002
    assert data["_verification_basis"] == "econbiz_fulltext_evidence"
    assert data["supporting_evidence_source"] == "EconBiz full-text search"
    assert data["supporting_evidence_id"] == "10005852170"
    assert data["supporting_evidence_title"].startswith("Referenzmodellierung 2002")

    status, sanitized = classify_verification_result(
        CITED_REFERENCE, data, errors, url,
    )
    assert status == "verified"
    assert sanitized == []


def test_fulltext_candidate_requires_relevance_and_matching_year(monkeypatch):
    checker = EconBizReferenceChecker()
    monkeypatch.setattr(checker, "search", lambda query, *, fulltext=False, limit=10: (
        [] if not fulltext else [
            {
                "_score": 0.29,
                "id": "low-score",
                "title": "Low relevance container",
                "date": ["2002"],
            },
            {
                "_score": 0.90,
                "id": "wrong-year",
                "title": "Wrong year container",
                "date": ["2012"],
            },
        ]
    ))

    assert checker.verify_reference(dict(CITED_REFERENCE)) == (None, [], None)


@patch("refchecker.checkers.econbiz.requests.get")
def test_search_uses_documented_fulltext_parameter_and_utf8_query(
    mock_get, monkeypatch, caplog,
):
    checker = EconBizReferenceChecker()
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {"status": 200, "hits": {"hits": [], "total": 0}}
    mock_get.return_value = response

    with caplog.at_level(logging.INFO, logger="refchecker.checkers.econbiz"):
        checker.search('"Ökonomie" AND Müller', fulltext=True)

    params = mock_get.call_args.kwargs["params"]
    assert params["q"] == '"Ökonomie" AND Müller'
    assert params["fulltext"] == "true"
    assert params["sort"] == "score desc"
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "stage=request" in message
        and 'query=\'"Ökonomie" AND Müller\'' in message
        and "fulltext=True" in message
        for message in messages
    )
    assert any("stage=search_result" in message for message in messages)
