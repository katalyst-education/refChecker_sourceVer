from __future__ import annotations

import io
import os
import tempfile

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Union

from .classification.pdf_classifier import classify_pdf
from .config import MAX_CLASSIFIER_PAGES
from .models import ExtractedDocument
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

    if not pdf_bytes:
        raise ValueError("PDF input is empty")

    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError(
            "Input does not appear to be a PDF"
        )

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
        except OSError:
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
        classification = classify_pdf(
            pdf_path,
            max_pages=max_classifier_pages,
        )

        doc_type = classification.get(
            "type",
            "unknown",
        )

        router = TextExtractorRouter()

        document = router.extract(
            pdf_path,
            doc_type,
            include_bibliography=include_bibliography,
        )

        document.metadata["classification"] = classification

        # Don't expose a meaningless temp path as the source filename.
        if is_temporary:
            document.file = "<memory>"

        return document