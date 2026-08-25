"""Regression tests for generic Crossref chapter-title collisions."""

from refchecker.checkers.crossref import CrossRefReferenceChecker


def _work(doi, author, title="Theoretische Grundlagen", year=2013, container=None):
    work = {
        "DOI": doi,
        "title": [title],
        "author": [{"given": author.rsplit(" ", 1)[0], "family": author.rsplit(" ", 1)[-1]}],
        "published": {"date-parts": [[year]]},
        "URL": f"https://doi.org/{doi}",
    }
    if container:
        work["container-title"] = [container]
    return work


def test_zero_author_overlap_title_match_runs_bibliographic_recovery(monkeypatch):
    checker = CrossRefReferenceChecker()
    wrong = _work("10.1007/978-3-658-00965-6_2", "Dirk Noosten")
    correct = _work(
        "10.1007/978-3-642-37994-9_2",
        "Daniel R. A. Schallmo",
        container="Geschäftsmodelle erfolgreich entwickeln und implementieren",
    )
    monkeypatch.setattr(checker, "search_works", lambda _title, _year: [wrong])
    monkeypatch.setattr(
        checker,
        "search_works_bibliographic",
        lambda _citation, _year: [correct, wrong],
    )

    verified, errors, _url = checker.verify_reference({
        "title": "Theoretische Grundlagen",
        "authors": ["Daniel R. A. Schallmo"],
        "year": 2013,
        "venue": "Geschäftsmodelle erfolgreich entwickeln und implementieren",
        "raw_text": (
            "Daniel R. A. Schallmo. 2013. Theoretische Grundlagen. "
            "Geschäftsmodelle erfolgreich entwickeln und implementieren."
        ),
    })

    assert verified["DOI"] == "10.1007/978-3-642-37994-9_2"
    assert not any(issue.get("error_type") == "author" for issue in errors)


def test_deferred_title_match_is_restored_when_bibliographic_search_fails(monkeypatch):
    checker = CrossRefReferenceChecker()
    wrong = _work("10.1007/978-3-658-00965-6_2", "Dirk Noosten")
    monkeypatch.setattr(checker, "search_works", lambda _title, _year: [wrong])
    monkeypatch.setattr(checker, "search_works_bibliographic", lambda _citation, _year: [])

    verified, errors, _url = checker.verify_reference({
        "title": "Theoretische Grundlagen",
        "authors": ["Daniel R. A. Schallmo"],
        "year": 2013,
    })

    assert verified["DOI"] == "10.1007/978-3-658-00965-6_2"
    assert any(issue.get("error_type") == "author" for issue in errors)
