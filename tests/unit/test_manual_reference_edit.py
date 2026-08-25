import pytest

from backend.reference_editing import (
    apply_manual_reference_edit,
    normalize_manual_reference_overrides,
    restore_extracted_reference_metadata,
)


def test_manual_edit_preserves_original_and_accepts_title_authors_and_year():
    reference = {
        "title": "Technologieund Innovationsmanagement",
        "authors": ["Alexander Gerybadze"],
        "year": 2004,
        "venue": "Vahlen",
        "doi": None,
        "cited_url": None,
        "status": "unverified",
        "errors": [{"error_type": "unverified"}],
        "verified_title": "Stale verified title",
    }

    apply_manual_reference_edit(
        reference,
        {
            "title": "Technologie- und Innovationsmanagement",
            "authors": ["Alexander Gerybadze", "Second Author"],
            "year": "2005",
            "venue": "Vahlen",
            "doi": "",
            "arxiv_id": "",
            "cited_url": "https://example.org/book",
        },
        edited_by=7,
    )

    assert reference["title"] == "Technologie- und Innovationsmanagement"
    assert reference["authors"] == ["Alexander Gerybadze", "Second Author"]
    assert reference["year"] == 2005
    assert reference["cited_url"] == "https://example.org/book"
    assert reference["manual_edit"]["original"]["title"] == "Technologieund Innovationsmanagement"
    assert reference["manual_edit"]["edited_by"] == 7
    assert set(reference["manual_edit"]["edited_fields"]) >= {
        "title", "authors", "year", "cited_url",
    }
    assert "errors" not in reference
    assert "verified_title" not in reference


def test_second_manual_edit_keeps_first_extracted_snapshot():
    reference = {"title": "Extracted", "authors": ["Author"], "year": 2000}
    apply_manual_reference_edit(reference, {"title": "First edit"})
    apply_manual_reference_edit(reference, {"title": "Second edit", "year": 2001})

    assert reference["manual_edit"]["original"]["title"] == "Extracted"
    assert reference["manual_edit"]["original"]["year"] == 2000


def test_restore_manual_edit_recovers_all_extracted_fields():
    reference = {
        "title": "Extracted",
        "authors": ["Original Author"],
        "year": 2000,
        "venue": "Original Venue",
    }
    apply_manual_reference_edit(
        reference,
        {"title": "Edited", "authors": ["Edited Author"], "year": 2001},
    )

    restore_extracted_reference_metadata(reference)

    assert reference["title"] == "Extracted"
    assert reference["authors"] == ["Original Author"]
    assert reference["year"] == 2000
    assert reference["venue"] == "Original Venue"
    assert "manual_edit" not in reference


def test_manual_edit_rejects_non_list_authors_and_invalid_year():
    with pytest.raises(ValueError, match="Authors must"):
        normalize_manual_reference_overrides({"authors": "One, Two"})
    with pytest.raises(ValueError, match="whole number"):
        normalize_manual_reference_overrides({"year": "two thousand"})


def test_blank_optional_text_fields_remain_verifier_safe_strings():
    normalized = normalize_manual_reference_overrides({
        "venue": "  ",
        "doi": "",
        "arxiv_id": None,
        "cited_url": "  ",
    })

    assert normalized == {
        "venue": "",
        "doi": "",
        "arxiv_id": "",
        "cited_url": "",
    }
    assert all(value.strip() == "" for value in normalized.values())
