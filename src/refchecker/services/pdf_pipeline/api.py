from __future__ import annotations

import io
import os
import tempfile

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Union

from .classification.pdf_classifier import classify_pdf
from .config import MAX_CLASSIFIER_PAGES
from .models import (
    ExtractedDocument,
    PDFExtractionError,
    build_extraction_diagnostics,
)
from .text_extractors.router import TextExtractorRouter


PDFInput = Union[
    str,
    Path,
    bytes,
    bytearray,
    io.BytesIO,
    BinaryIO,
]


@contextmanager
def _pdf_input_as_path(
    source: PDFInput,
) -> Iterator[tuple[Path, bool]]:
    """
    Normalize a PDF input to a filesystem Path.

    Returns:
        (path, is_temporary)

    Existing paths are passed through unchanged.
    Bytes / BytesIO / file-like inputs are temporarily materialized
    because some pipeline components and external tools require a path.
    """

    # ---------------------------------------------------------
    # Already a path
    # ---------------------------------------------------------

    if isinstance(source, (str, Path)):
        path = Path(source)

        if not path.exists():
            raise FileNotFoundError(
                f"PDF file not found: {path}"
            )

        yield path, False
        return

    # ---------------------------------------------------------
    # Raw bytes
    # ---------------------------------------------------------

    if isinstance(source, (bytes, bytearray)):
        pdf_bytes = bytes(source)

    # ---------------------------------------------------------
    # BytesIO / binary file-like object
    # ---------------------------------------------------------

    elif hasattr(source, "read"):
        original_position = None

        try:
            if hasattr(source, "tell"):
                original_position = source.tell()

            if hasattr(source, "seek"):
                source.seek(0)

            pdf_bytes = source.read()

        finally:
            # Don't unexpectedly change the caller's stream position.
            if (
                original_position is not None
                and hasattr(source, "seek")
            ):
                try:
                    source.seek(original_position)
                except Exception:
                    pass

    else:
        raise TypeError(
            "PDF source must be a path, bytes, "
            "BytesIO, or binary file-like object"
        )

    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError("PDF file-like input must return bytes")
    pdf_bytes = bytes(pdf_bytes)

    if not pdf_bytes:
        raise ValueError("PDF input is empty")

    # ---------------------------------------------------------
    # Some current extractors / GROBID integration require a Path,
    # so materialize the in-memory PDF exactly once here.
    # ---------------------------------------------------------

    fd, temp_name = tempfile.mkstemp(suffix=".pdf")
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(pdf_bytes)

        yield temp_path, True

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def extract_pdf(
    source: PDFInput,
    *,
    include_bibliography: bool = False,
    max_classifier_pages: int = MAX_CLASSIFIER_PAGES,
) -> ExtractedDocument:
    """
    Extract a PDF from either a filesystem path or in-memory content.
    """

    with _pdf_input_as_path(source) as (
        pdf_path,
        is_temporary,
    ):
        classification_error = None
        try:
            classification = classify_pdf(
                pdf_path,
                max_pages=max_classifier_pages,
            )
        except Exception as exc:
            classification_error = exc
            classification = {
                "type": "unknown",
                "classification_error": str(exc),
            }

        doc_type = classification.get(
            "type",
            "unknown",
        )

        router = TextExtractorRouter()
        primary_error = None
        try:
            document = router.extract(
                pdf_path,
                doc_type,
                include_bibliography=include_bibliography,
            )
        except Exception as exc:
            primary_error = exc

        if (
            primary_error is None
            and not document.full_text.strip()
            and not document.body_text.strip()
        ):
            primary_error = PDFExtractionError(
                "No text could be extracted from the PDF",
                build_extraction_diagnostics(
                    document_status="failed",
                    bibliography_status="extraction_failed",
                    extractor=document.extractor,
                    classification=classification,
                    reason="No text could be extracted from the PDF",
                ),
            )

        if primary_error is not None:
            if doc_type != "unknown":
                try:
                    document = router.fallback_extractor.extract(
                        pdf_path,
                        "unknown",
                        include_bibliography=include_bibliography,
                    )
                except Exception as fallback_error:
                    fallback_diagnostics = (
                        fallback_error.diagnostics
                        if isinstance(fallback_error, PDFExtractionError)
                        else build_extraction_diagnostics(
                            bibliography_status="extraction_failed",
                            extractor="fallback",
                            classification=classification,
                        )
                    )
                    errors = list(fallback_diagnostics.get("errors", []))
                    if isinstance(primary_error, PDFExtractionError):
                        errors.extend(primary_error.diagnostics.get("errors", []))
                    if classification_error is not None:
                        errors.append(
                            f"PDF classification failed: {classification_error}"
                        )
                    errors.append(
                        f"{doc_type} extraction failed: {primary_error}"
                    )
                    errors.append(f"Fallback extraction failed: {fallback_error}")
                    fallback_diagnostics.update({
                        "document_status": "failed",
                        "bibliography_status": "extraction_failed",
                        "extractor": "fallback",
                        "classification": classification,
                        "errors": errors,
                        "reason": (
                            "Primary and fallback PDF extraction both failed"
                        ),
                    })
                    extracted_text = getattr(
                        fallback_error,
                        "extracted_text",
                        "",
                    ) or getattr(primary_error, "extracted_text", "")
                    raise PDFExtractionError(
                        "PDF extraction failed after fallback",
                        fallback_diagnostics,
                        extracted_text=extracted_text,
                    ) from fallback_error

            else:
                primary_diagnostics = (
                    primary_error.diagnostics
                    if isinstance(primary_error, PDFExtractionError)
                    else build_extraction_diagnostics(
                        bibliography_status="extraction_failed",
                        extractor=doc_type,
                    )
                )
                errors = list(primary_diagnostics.get("errors", []))
                if classification_error is not None:
                    errors.append(
                        f"PDF classification failed: {classification_error}"
                    )
                errors.append(f"Fallback extraction failed: {primary_error}")
                primary_diagnostics.update({
                    "document_status": "failed",
                    "bibliography_status": "extraction_failed",
                    "classification": classification,
                    "errors": errors,
                    "reason": "Fallback PDF extraction failed",
                })
                raise PDFExtractionError(
                    "PDF extraction failed",
                    primary_diagnostics,
                    extracted_text=getattr(primary_error, "extracted_text", ""),
                ) from primary_error

            fallback_diagnostics = document.metadata.setdefault(
                "extraction_diagnostics",
                build_extraction_diagnostics(
                    bibliography_status=(
                        "extracted" if document.bibliography.strip()
                        else "not_found"
                    ),
                    extractor=document.extractor,
                ),
            )
            fallback_diagnostics["document_status"] = "partial"
            fallback_diagnostics.setdefault("errors", []).append(
                f"{doc_type} extraction failed; used fallback: {primary_error}"
            )
            if classification_error is not None:
                fallback_diagnostics["errors"].append(
                    f"PDF classification failed: {classification_error}"
                )
            fallback_diagnostics["reason"] = (
                "Primary extraction failed; local fallback produced text"
            )

        document.metadata["classification"] = classification
        if not document.full_text.strip() and not document.body_text.strip():
            diagnostics = document.metadata.get(
                "extraction_diagnostics",
                build_extraction_diagnostics(
                    document_status="failed",
                    bibliography_status="extraction_failed",
                    extractor=document.extractor,
                    classification=classification,
                    reason="No text could be extracted from the PDF",
                ),
            )
            diagnostics.update({
                "document_status": "failed",
                "bibliography_status": "extraction_failed",
                "classification": classification,
                "reason": "No text could be extracted after fallback",
            })
            raise PDFExtractionError(
                "No text could be extracted from the PDF after fallback",
                diagnostics,
            )

        diagnostics = document.metadata.setdefault(
            "extraction_diagnostics",
            build_extraction_diagnostics(
                bibliography_status=(
                    "not_applicable"
                    if doc_type == "presentation_slide"
                    else "extracted"
                    if document.bibliography.strip()
                    else "not_found"
                ),
                extractor=document.extractor,
                reason="",
            ),
        )
        if not diagnostics.get("classification"):
            diagnostics["classification"] = classification
        if classification_error is not None:
            diagnostics["document_status"] = "partial"
            diagnostics.setdefault("errors", []).append(
                f"PDF classification failed; used fallback: {classification_error}"
            )
            diagnostics["reason"] = (
                "Classification failed; local fallback produced text"
            )

        # Don't expose a meaningless temp path as the source filename.
        if is_temporary:
            document.file = "<memory>"

        return document