"""Tests for the Seen-Refs cross-check warning.

This warning tells a user that they cited the same title differently in an
earlier check. It is only useful if it stays quiet when nothing is actually
wrong, so most of these tests assert the *absence* of a warning.
"""
import asyncio

import pytest

from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "xcheck.db"))
    _run(database.init_db())
    return database


MENG_TITLE = "Locating and editing factual associations in GPT"
MENG_AUTHORS = ["K. Meng", "D. Bau", "A. Andonian", "Y. Belinkov"]


def _seed(database, **overrides):
    ref = {
        "title": MENG_TITLE,
        "authors": MENG_AUTHORS,
        "year": 2022,
        "doi": "10.52202/068431-1262",
        "status": "verified",
    }
    ref.update(overrides)
    return _run(database.upsert_verified_reference(ref))


class TestAuthorNormalization:
    """The cached side is JSON; the cited side is a list or joined string."""

    def test_parses_json_encoded_author_list(self):
        assert Database._author_names('["K. Meng", "D. Bau"]') == ["K. Meng", "D. Bau"]

    def test_parses_real_list(self):
        assert Database._author_names(["K. Meng", "D. Bau"]) == ["K. Meng", "D. Bau"]

    def test_parses_comma_joined_string(self):
        assert Database._author_names("K. Meng, D. Bau") == ["K. Meng", "D. Bau"]

    def test_parses_semicolon_and_and_separators(self):
        assert Database._author_names("K. Meng; D. Bau") == ["K. Meng", "D. Bau"]
        assert Database._author_names("K. Meng and D. Bau") == ["K. Meng", "D. Bau"]

    def test_empty_values_yield_no_names(self):
        for value in (None, "", "   ", [], "[]"):
            assert Database._author_names(value) == []

    def test_malformed_json_falls_back_to_splitting(self):
        assert Database._author_names('["K. Meng", "D. Bau"') == ["K. Meng", "D. Bau"]

    @pytest.mark.parametrize(
        "names,expected",
        [
            (["K. Meng"], "meng"),
            (["Meng, K."], "meng"),
            (['"K. Meng"'], "meng"),
            (["Kevin Meng"], "meng"),
            ([], ""),
        ],
    )
    def test_first_surname_ignores_punctuation_and_order(self, names, expected):
        assert Database._first_author_surname(names) == expected

    def test_json_and_plain_forms_agree(self):
        """The exact regression: JSON quoting must not change the surname."""
        cached = Database._author_names('["K. Meng", "D. Bau", "A. Andonian"]')
        cited = Database._author_names("K. Meng, D. Bau, A. Andonian")
        assert Database._first_author_surname(cached) == Database._first_author_surname(cited)
        assert Database._first_author_surname(cached) == "meng"


class TestCrossCheckWarnings:
    @pytest.mark.parametrize('cached_is_preprint', [False, True])
    @pytest.mark.parametrize('arxiv_doi', [None, '10.48550/arXiv.1512.03385'])
    @pytest.mark.parametrize('author_conflict', [False, True])
    def test_marked_versions_only_suppress_version_diffs(
        self, db, cached_is_preprint, arxiv_doi, author_conflict,
    ):
        published = {
            'title': MENG_TITLE, 'authors': MENG_AUTHORS,
            'year': 2016, 'venue': 'CVPR', 'doi': '10.1109/cvpr.2016.90',
            'status': 'verified',
        }
        preprint = dict(published, year=2015, venue='arXiv', doi=arxiv_doi,
                        arxiv_id=None if arxiv_doi else '1512.03385')
        cached, cited = (preprint, published) if cached_is_preprint else (published, preprint)
        if author_conflict:
            cited = dict(cited, authors=['J. Smith'])
        _run(db.upsert_verified_reference(cached))

        discrepancies = _run(db.cross_check_seen_refs(cited))
        assert [d['field'] for entry in discrepancies for d in entry['diffs']] == (
            ['authors'] if author_conflict else []
        )

    @pytest.mark.parametrize('cached_is_preprint', [False, True])
    def test_cited_snapshot_distinguishes_versions_with_same_identity(self, db, cached_is_preprint):
        published = {
            'title': MENG_TITLE, 'authors': MENG_AUTHORS, 'year': 2016,
            'venue': 'CVPR', 'doi': '10.1109/cvpr.2016.90', 'status': 'verified',
        }
        preprint = dict(
            published, year=2015, venue='arXiv', authors=['J. Smith'],
            # Both results carry the publication DOI; only the citation tells
            # us which version the preprint entry actually cited.
            cited_metadata={'title': MENG_TITLE, 'year': 2015, 'arxiv_id': '1512.03385'},
        )
        cached, cited = (preprint, published) if cached_is_preprint else (published, preprint)
        assert _run(db.upsert_verified_reference(cached)) == Database.reference_identity_key(cited)

        discrepancies = _run(db.cross_check_seen_refs(cited))
        assert [d['field'] for entry in discrepancies for d in entry['diffs']] == ['authors']

    def test_unmarked_reference_still_warns_against_publication(self, db):
        _seed(db, venue='CVPR')
        cited = dict(title=MENG_TITLE, authors=MENG_AUTHORS, year=2021, venue='preprint')
        discrepancies = _run(db.cross_check_seen_refs(cited))
        assert {d['field'] for entry in discrepancies for d in entry['diffs']} == {'year', 'venue'}

    def test_same_first_author_does_not_warn(self, db):
        """Regression: JSON quoting made every cached author list look wrong.

        ``"K. Meng"`` parsed as surname ``meng"`` and never matched ``meng``,
        so a correctly cited reference was flagged on every check.
        """
        _seed(db)

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": MENG_AUTHORS,
            "year": 2022,
            "doi": "10.99999/different",
        }))

        author_diffs = [
            d for entry in result for d in entry["diffs"] if d["field"] == "authors"
        ]
        assert author_diffs == []

    def test_missing_middle_author_does_not_warn(self, db):
        """et-al truncation is a formatting difference, not a mismatch."""
        _seed(db, authors=["K. Meng", "A. Andonian", "Y. Belinkov"])

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": MENG_AUTHORS,
            "year": 2022,
            "doi": "10.99999/different",
        }))

        author_diffs = [
            d for entry in result for d in entry["diffs"] if d["field"] == "authors"
        ]
        assert author_diffs == []

    def test_genuinely_different_first_author_still_warns(self, db):
        _seed(db)

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": ["J. Smith", "D. Bau"],
            "year": 2022,
            "doi": "10.99999/different",
        }))

        author_diffs = [
            d for entry in result for d in entry["diffs"] if d["field"] == "authors"
        ]
        assert len(author_diffs) == 1
        assert "Smith" in author_diffs[0]["cited"]

    def test_author_diff_is_rendered_without_json_punctuation(self, db):
        """The user sees this string, so it must not be a raw JSON blob."""
        _seed(db)

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": ["J. Smith"],
            "year": 2022,
            "doi": "10.99999/different",
        }))

        cached = [
            d["cached"] for entry in result for d in entry["diffs"] if d["field"] == "authors"
        ][0]
        assert "[" not in cached and '"' not in cached
        assert cached.startswith("K. Meng")

    def test_year_mismatch_still_warns(self, db):
        _seed(db)

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": MENG_AUTHORS,
            "year": 2019,
            "doi": "10.99999/different",
        }))

        year_diffs = [
            d for entry in result for d in entry["diffs"] if d["field"] == "year"
        ]
        assert len(year_diffs) == 1

    def test_identical_reference_produces_no_warning(self, db):
        _seed(db)

        result = _run(db.cross_check_seen_refs({
            "title": MENG_TITLE,
            "authors": MENG_AUTHORS,
            "year": 2022,
            "doi": "10.52202/068431-1262",
        }))

        assert result == []
