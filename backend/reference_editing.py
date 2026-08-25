"""Validation, provenance, and undo helpers for user-edited citations."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional


EDITABLE_REFERENCE_FIELDS = (
    "title",
    "authors",
    "year",
    "venue",
    "doi",
    "arxiv_id",
    "cited_url",
)


def reference_metadata_snapshot(reference: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-safe snapshot of all user-editable cited fields."""
    return {
        field: json.loads(json.dumps(reference.get(field), default=str))
        for field in EDITABLE_REFERENCE_FIELDS
    }


def normalize_manual_reference_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize metadata entered in the reference editor."""
    normalized: Dict[str, Any] = {}
    for field in EDITABLE_REFERENCE_FIELDS:
        if field not in overrides:
            continue
        value = overrides[field]
        if field == "authors":
            if value is None:
                normalized[field] = []
                continue
            if not isinstance(value, list):
                raise ValueError("Authors must be supplied as a list of names.")
            authors = []
            for author in value:
                if isinstance(author, dict):
                    author = author.get("name") or " ".join(
                        str(author.get(key) or "").strip()
                        for key in ("givenName", "familyName")
                    )
                name = " ".join(str(author or "").split()).strip()
                if name:
                    authors.append(name)
            normalized[field] = authors
        elif field == "year":
            if value in (None, ""):
                normalized[field] = None
                continue
            try:
                year = int(str(value).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError("Year must be a whole number.") from exc
            if year < 1 or year > 9999:
                raise ValueError("Year must be between 1 and 9999.")
            normalized[field] = year
        else:
            # Shared checkers treat cited text fields as strings and several
            # call ``.strip()`` directly. Empty editor inputs therefore remain
            # empty strings rather than becoming None.
            normalized[field] = " ".join(str(value or "").split()).strip()
    return normalized


def clear_previous_reference_verification(reference: Dict[str, Any]) -> None:
    """Drop state derived from metadata that is about to be replaced."""
    for field in (
        "corrected_reference", "dismissed_corrected_reference",
        "verified_title", "verified_authors", "verified_year", "verified_venue",
        "verified_doi", "verified_arxiv_id", "verified_url", "authoritative_urls",
        "matched_db", "matched_database", "enrichment", "errors", "warnings",
        "infos", "suggestions", "hallucination_assessment",
        "publication_year_assessment", "match_decision",
    ):
        reference.pop(field, None)


def apply_manual_reference_edit(
    reference: Dict[str, Any],
    overrides: Dict[str, Any],
    *,
    edited_by: Optional[int] = None,
) -> None:
    """Apply a manual edit while retaining the first extracted field values."""
    existing = reference.get("manual_edit")
    original = (
        existing.get("original")
        if isinstance(existing, dict) and isinstance(existing.get("original"), dict)
        else reference_metadata_snapshot(reference)
    )
    normalized = normalize_manual_reference_overrides(overrides)
    if not normalized:
        raise ValueError("No editable reference fields were supplied.")
    for field, value in normalized.items():
        reference[field] = value
    clear_previous_reference_verification(reference)
    edited_fields = [
        field for field in EDITABLE_REFERENCE_FIELDS
        if reference.get(field) != original.get(field)
    ]
    if edited_fields:
        reference["manual_edit"] = {
            "original": original,
            "edited_fields": edited_fields,
            "edited_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "edited_by": edited_by,
        }
    else:
        # Manually changing every field back to the extracted values is
        # equivalent to Undo and should not leave a misleading edit badge.
        reference.pop("manual_edit", None)


def restore_extracted_reference_metadata(reference: Dict[str, Any]) -> None:
    """Restore the persistent pre-edit snapshot for a manually edited row."""
    manual_edit = reference.get("manual_edit")
    original = manual_edit.get("original") if isinstance(manual_edit, dict) else None
    if not isinstance(original, dict):
        raise ValueError("This reference has no saved extracted metadata to restore.")
    for field in EDITABLE_REFERENCE_FIELDS:
        value = original.get(field)
        reference[field] = (
            value
            if field in ("authors", "year")
            else str(value or "")
        )
    reference.pop("manual_edit", None)
    clear_previous_reference_verification(reference)
