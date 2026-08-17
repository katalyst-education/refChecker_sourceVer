import unittest
from unittest.mock import patch

from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker


class TestSemanticScholarTitleFallback(unittest.TestCase):
    def setUp(self):
        self.checker = NonArxivReferenceChecker()

    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch("refchecker.checkers.semantic_scholar.find_best_match")
    def test_low_score_match_still_runs_relevance_search(
        self,
        mock_find_best_match,
        mock_match_paper_by_title,
        mock_search_paper,
    ):
        mock_match_paper_by_title.return_value = {
            "title": "Completely unrelated paper",
            "authors": [],
            "externalIds": {},
        }
        expected = {
            "paperId": "kitchenham-2007",
            "title": "Guidelines for performing Systematic Literature Reviews in software engineering",
            "authors": [{"name": "Barbara Kitchenham"}],
            "externalIds": {},
            "url": "https://www.semanticscholar.org/paper/kitchenham-2007",
        }
        mock_search_paper.return_value = [expected]
        mock_find_best_match.return_value = (expected, 0.99)

        verified_data, _errors, _url = self.checker.verify_reference({
            "title": "Guidelines for performing Systematic Literature Reviews in software engineering",
            "authors": ["Barbara Kitchenham"],
            "year": 2007,
        })

        self.assertIsNotNone(verified_data)
        self.assertEqual(verified_data.get("paperId"), "kitchenham-2007")
        mock_match_paper_by_title.assert_called_once()
        mock_search_paper.assert_called_once()

    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    def test_author_prefix_in_title_is_stripped_for_search(self, mock_match_paper_by_title, mock_search_paper):
        mock_match_paper_by_title.return_value = None
        mock_search_paper.return_value = []

        verified_data, errors, _url = self.checker.verify_reference({
            "title": "Kitchenham, B.: Guidelines for performing Systematic Literature Reviews in software engineering",
            "authors": ["Barbara Kitchenham"],
            "year": 2007,
        })

        self.assertIsNone(verified_data)
        self.assertEqual(errors, [])
        self.assertTrue(mock_match_paper_by_title.called)
        called_query = mock_match_paper_by_title.call_args.args[0]
        self.assertFalse(called_query.lower().startswith("kitchenham, b.:"))
        self.assertEqual(
            called_query,
            "Guidelines for performing Systematic Literature Reviews in software engineering",
        )
        self.assertTrue(mock_search_paper.called)
        searched_queries = [call.args[0] for call in mock_search_paper.call_args_list]
        self.assertIn(called_query, searched_queries)

    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch("refchecker.checkers.semantic_scholar.find_best_match")
    def test_author_fallback_accepts_score_above_threshold(
        self,
        mock_find_best_match,
        mock_match_paper_by_title,
        mock_search_paper,
    ):
        mock_match_paper_by_title.return_value = None
        candidate = {
            "paperId": "bf3910a40028240b821790738896954638932e33",
            "title": "Protocol for a Tertiary study of Systematic Literature Reviews and Evidence-based Guidelines in IT and Software Engineering",
            "authors": [{"name": "Barbara Kitchenham"}],
            "year": 2009,
            "externalIds": {},
        }
        # First call: title relevance search (no results). Second call: author fallback search.
        mock_search_paper.side_effect = [[], [candidate]]
        mock_find_best_match.return_value = (candidate, 0.523)

        verified_data, errors, _url = self.checker.verify_reference({
            "title": "Guidelines for performing Systematic Literature Reviews in software engineering",
            "authors": ["Barbara Kitchenham"],
            "year": 2007,
        })

        self.assertIsNotNone(verified_data)
        self.assertEqual(verified_data.get("paperId"), "bf3910a40028240b821790738896954638932e33")
        self.assertEqual(mock_search_paper.call_count, 2)

    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    def test_title_relevance_handles_dict_author_shapes(self, mock_match_paper_by_title, mock_search_paper):
        mock_match_paper_by_title.return_value = None
        candidate = {
            "paperId": "os-2004",
            "title": "Ontological Semantics",
            "authors": [{"name": "Sergei Nirenburg"}, {"name": "Victor Raskin"}],
            "year": 2004,
            "externalIds": {},
            "url": "https://www.semanticscholar.org/paper/os-2004",
        }
        mock_search_paper.return_value = [candidate]

        verified_data, errors, _url = self.checker.verify_reference({
            "title": "Ontological Semantics",
            "authors": [{"name": "S Nirenburg"}, {"name": "V Raskin"}],
            "year": 2004,
        })

        self.assertIsNotNone(verified_data)
        self.assertEqual(verified_data.get("paperId"), "os-2004")
        self.assertFalse(any(e.get("error_type") == "api_failure" for e in errors))

    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    def test_arxiv_lookup_accepts_dict_title_payload(self, mock_get_paper_by_arxiv_id):
        mock_get_paper_by_arxiv_id.return_value = {
            "title": "Ontological Semantics",
            "authors": [{"name": "Sergei Nirenburg"}, {"name": "Victor Raskin"}],
            "year": 2004,
            "externalIds": {},
            "url": "https://arxiv.org/abs/2501.00001",
        }

        verified_data, errors, _url = self.checker.verify_reference({
            "title": {"text": "Ontological Semantics"},
            "authors": [{"name": "S Nirenburg"}, {"name": "V Raskin"}],
            "year": 2004,
            "url": "https://arxiv.org/abs/2501.00001",
        })

        self.assertIsNotNone(verified_data)
        self.assertEqual(verified_data.get("title"), "Ontological Semantics")
        self.assertFalse(any(e.get("error_type") == "api_failure" for e in errors))


if __name__ == "__main__":
    unittest.main()
