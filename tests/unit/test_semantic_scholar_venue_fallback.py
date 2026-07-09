import unittest
from unittest.mock import patch

from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker


class TestSemanticScholarVenueFallback(unittest.TestCase):
    def setUp(self):
        self.checker = NonArxivReferenceChecker()

    @patch("refchecker.utils.venue_utils.lookup_venue_via_doi")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi")
    def test_doi_venue_match_suppresses_primary_venue_warning(self, mock_get_paper_by_doi, mock_lookup_doi_venue):
        mock_get_paper_by_doi.return_value = {
            "paperId": "8dae26ef1adac2a8a8972f9cd5d276ab3693d2a5",
            "title": "Learning environment interoperability in software engineering education",
            "authors": [{"name": "D. Bigler"}],
            "year": 2024,
            "venue": "Conference on Software Engineering Education and Training",
            "externalIds": {"DOI": "10.1109/CSEET62301.2024.10663056"},
            "url": "https://www.semanticscholar.org/paper/8dae26ef1adac2a8a8972f9cd5d276ab3693d2a5",
        }
        mock_lookup_doi_venue.return_value = "36th International Conference on Software Engineering Education and Training (CSEE&T)"

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


if __name__ == "__main__":
    unittest.main()
