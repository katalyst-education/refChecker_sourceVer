import unittest
from unittest.mock import patch

from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker
from refchecker.utils.venue_utils import (
    get_crossref_venue,
    resolve_publication_type,
    resolve_venue_for_validation,
)


class TestSemanticScholarVenueFallback(unittest.TestCase):
    def setUp(self):
        self.checker = NonArxivReferenceChecker()

    @patch("refchecker.utils.venue_utils.lookup_crossref_work_via_doi")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi")
    def test_doi_venue_match_suppresses_primary_venue_warning(self, mock_get_paper_by_doi, mock_lookup_work):
        mock_get_paper_by_doi.return_value = {
            "paperId": "8dae26ef1adac2a8a8972f9cd5d276ab3693d2a5",
            "title": "Learning environment interoperability in software engineering education",
            "authors": [{"name": "D. Bigler"}],
            "year": 2024,
            "venue": "Conference on Software Engineering Education and Training",
            "externalIds": {"DOI": "10.1109/CSEET62301.2024.10663056"},
            "url": "https://www.semanticscholar.org/paper/8dae26ef1adac2a8a8972f9cd5d276ab3693d2a5",
        }
        mock_lookup_work.return_value = {
            "type": "proceedings-article",
            "container-title": [
                "36th International Conference on Software Engineering Education and Training (CSEE&T)"
            ],
        }

        verified_data, errors, _url = self.checker.verify_reference({
            "title": "Learning environment interoperability in software engineering education",
            "authors": ["D. Bigler"],
            "year": 2024,
            "venue": "36th International Conference on Software Engineering Education and Training (CSEE&T)",
            "url": "https://doi.org/10.1109/CSEET62301.2024.10663056",
        })

        self.assertIsNotNone(verified_data)
        venue_issues = [
            error for error in errors
            if error.get("warning_type") == "venue" or error.get("error_type") == "venue"
        ]
        self.assertEqual(venue_issues, [])

    def test_crossref_whole_book_uses_publisher_instead_of_series(self):
        work = {
            "DOI": "10.1007/978-3-322-91279-4",
            "type": "book",
            "publisher": "Gabler Verlag",
            "container-title": [
                "Bochumer Beiträge zur Unternehmungsführung und Unternehmensforschung"
            ],
        }

        self.assertEqual(get_crossref_venue(work), "Gabler Verlag")

    def test_crossref_book_chapter_keeps_containing_book_as_venue(self):
        work = {
            "type": "book-chapter",
            "publisher": "Example Publisher",
            "container-title": ["The Example Handbook"],
        }

        self.assertEqual(get_crossref_venue(work), "The Example Handbook")

    def test_semantic_scholar_book_type_needs_no_isbn(self):
        resolution = resolve_publication_type(
            reference={"title": "A Book Without an ISBN"},
            verified_data={"publicationTypes": ["Book"]},
        )

        self.assertEqual(resolution.publication_type, "whole-book")
        self.assertEqual(resolution.confidence, "high")
        self.assertEqual(resolution.source, "semantic_scholar.publicationTypes")

    def test_book_without_doi_or_isbn_does_not_treat_series_as_publisher(self):
        venue, used_doi_metadata = resolve_venue_for_validation(
            "Gabler Verlag",
            "Bochumer Beiträge zur Unternehmungsführung und Unternehmensforschung",
            {"title": "Marketing-Accounting im Dienstleistungsbereich"},
            paper_data={"publicationTypes": ["Book"]},
        )

        self.assertEqual(venue, "Gabler Verlag")
        self.assertFalse(used_doi_metadata)

    @patch("refchecker.utils.venue_utils.lookup_crossref_work_via_doi")
    def test_book_venue_validation_uses_publisher_not_series(self, mock_lookup_work):
        mock_lookup_work.return_value = {
            "DOI": "10.1007/978-3-322-91279-4",
            "type": "book",
            "publisher": "Gabler Verlag",
            "container-title": [
                "Bochumer Beiträge zur Unternehmungsführung und Unternehmensforschung"
            ],
        }

        venue, used_doi_metadata = resolve_venue_for_validation(
            "Gabler Verlag",
            "Bochumer Beiträge zur Unternehmungsführung und Unternehmensforschung",
            {"doi": "10.1007/978-3-322-91279-4"},
            paper_data={"publicationTypes": ["Book"]},
        )

        self.assertEqual(venue, "Gabler Verlag")
        self.assertTrue(used_doi_metadata)

    @patch("refchecker.utils.venue_utils.lookup_crossref_work_via_doi")
    def test_unknown_doi_type_does_not_claim_series_as_correction(self, mock_lookup_work):
        mock_lookup_work.return_value = {
            "publisher": "Correct Publisher",
            "container-title": ["A Series Name"],
        }

        venue, _used_doi_metadata = resolve_venue_for_validation(
            "Cited Publisher",
            "A Series Name",
            {"doi": "10.1000/unknown-type"},
        )

        self.assertEqual(venue, "Cited Publisher")

    @patch("refchecker.utils.venue_utils.lookup_crossref_work_via_doi")
    def test_legacy_venue_string_from_doi_lookup_is_ignored_safely(self, mock_lookup_work):
        mock_lookup_work.return_value = "Legacy Venue"

        venue, _used_doi_metadata = resolve_venue_for_validation(
            "Cited Venue",
            "Verified Venue",
            {"doi": "10.1000/legacy-cache-shape"},
        )

        self.assertEqual(venue, "Verified Venue")


if __name__ == "__main__":
    unittest.main()
