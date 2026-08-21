"""Regression tests for safe per-reference document re-extraction."""

from backend.reference_matching import find_reextracted_reference_index


def test_reextracted_reference_is_matched_by_title_after_order_shift():
    target = {
        "index": 27,
        "title": "Kostenrechnung im Dienstleistungsbetrieb",
        "authors": ["J. Lachhammer"],
        "year": 1979,
    }
    extracted = [
        {"title": "Earlier reference"},
        {"title": "Berliner Start-up Relayr erhält 30 Millionen"},
        {
            "title": "Kostenrechnung im Dienstleistungsbetrieb",
            "authors": ["J. Lachhammer"],
            "year": 1979,
        },
    ]

    assert find_reextracted_reference_index(extracted, target, preferred_index=1) == 2


def test_missing_reextracted_reference_does_not_fall_back_to_position():
    target = {
        "title": "Kostenrechnung im Dienstleistungsbetrieb",
        "authors": ["J. Lachhammer"],
        "year": 1979,
    }
    extracted = [
        {"title": "Earlier reference"},
        {"title": "Berliner Start-up Relayr erhält 30 Millionen"},
    ]

    assert find_reextracted_reference_index(extracted, target, preferred_index=1) is None


def test_reextracted_reference_title_match_ignores_punctuation():
    target = {"title": "Costs & Services: An Introduction"}
    extracted = [{"title": "Costs and Services"}, {"title": "Costs Services — An Introduction"}]

    assert find_reextracted_reference_index(extracted, target) == 1


def test_reextracted_reference_can_match_doi_when_title_changes():
    target = {
        "title": "Imperfectly extracted title",
        "doi": "https://doi.org/10.1000/ABC.1",
    }
    extracted = [
        {"title": "Unrelated", "doi": "10.1000/other"},
        {"title": "Canonical title", "doi": "doi:10.1000/abc.1"},
    ]

    assert find_reextracted_reference_index(extracted, target) == 1
