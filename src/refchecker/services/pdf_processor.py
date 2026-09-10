#!/usr/bin/env python3
"""
PDF Processing Service for ArXiv Reference Checker.

Provides a single interface for PDF extraction through the clean pdf_pipeline.

Supported inputs:
    - str path
    - pathlib.Path
    - bytes
    - bytearray
    - io.BytesIO
    - binary file-like objects
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import tempfile

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, Optional, Union

from .pdf_pipeline import (
    ExtractedDocument,
    extract_pdf,
    split_text_and_references,
)


logger = logging.getLogger(__name__)


PDFInput = Union[
    str,
    Path,
    bytes,
    bytearray,
    io.BytesIO,
    BinaryIO,
]


@dataclass
class Paper:
    """Represents a paper with metadata."""

    title: str
    authors: list
    abstract: str = ""
    year: Optional[int] = None
    venue: str = ""
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    pdf_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "url": self.url,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "pdf_path": self.pdf_path,
        }


class PDFProcessor:
    """
    Service for processing PDFs using the clean PDF pipeline.

    The processor accepts both filesystem paths and in-memory PDFs.

    In-memory PDFs are temporarily materialized to disk because the
    underlying pdf_pipeline currently expects a filesystem Path.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or {}

        # Cache complete extraction results.
        #
        # Path inputs use path + modification metadata as the key.
        # In-memory PDFs use a SHA-256 hash of the PDF bytes.
        self.cache: dict[str, ExtractedDocument] = {}

    # ------------------------------------------------------------------
    # INPUT NORMALIZATION
    # ------------------------------------------------------------------

    @staticmethod
    def _read_pdf_bytes(source: PDFInput) -> bytes:
        """
        Read an in-memory/file-like PDF without unnecessarily changing
        the caller's stream position.
        """

        if isinstance(source, bytes):
            data = source

        elif isinstance(source, bytearray):
            data = bytes(source)

        elif isinstance(source, io.BytesIO):
            # getvalue() does not move the BytesIO cursor.
            data = source.getvalue()

        elif hasattr(source, "read"):
            original_position = None

            try:
                if hasattr(source, "tell"):
                    try:
                        original_position = source.tell()
                    except Exception:
                        original_position = None

                if hasattr(source, "seek"):
                    try:
                        source.seek(0)
                    except Exception:
                        pass

                data = source.read()

            finally:
                if (
                    original_position is not None
                    and hasattr(source, "seek")
                ):
                    try:
                        source.seek(original_position)
                    except Exception:
                        pass

            if isinstance(data, bytearray):
                data = bytes(data)

            if not isinstance(data, bytes):
                raise TypeError(
                    "PDF file-like object must return bytes, "
                    f"not {type(data).__name__}"
                )

        else:
            raise TypeError(
                "PDF source must be a path, bytes, bytearray, "
                "BytesIO, or binary file-like object"
            )

        if not data:
            raise ValueError("PDF input is empty")

        # Basic sanity check. This catches accidental HTML/error pages,
        # text files, etc. before they enter the extraction pipeline.
        if not data.startswith(b"%PDF-"):
            raise ValueError(
                "Input does not appear to contain valid PDF data"
            )

        return data

    @staticmethod
    def _path_cache_key(path: Path) -> str:
        """
        Build a cache key for a filesystem PDF.

        Including size and modification time avoids returning an old
        extraction result when the file at the same path changes.
        """
        resolved = path.resolve()
        stat = resolved.stat()

        return (
            f"path:{resolved}:"
            f"{stat.st_size}:"
            f"{stat.st_mtime_ns}"
        )

    @staticmethod
    def _bytes_cache_key(data: bytes) -> str:
        """Build a stable cache key for an in-memory PDF."""
        digest = hashlib.sha256(data).hexdigest()
        return f"bytes:{digest}"

    @contextmanager
    def _temporary_pdf_path(
        self,
        data: bytes,
    ) -> Iterator[Path]:
        """
        Materialize PDF bytes as a temporary file.

        mkstemp is used instead of keeping NamedTemporaryFile open,
        which avoids Windows file-locking problems when another library
        attempts to reopen the PDF.
        """
        fd, temp_name = tempfile.mkstemp(
            suffix=".pdf",
            prefix="refchecker_pdf_",
        )

        temp_path = Path(temp_name)

        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(data)

            yield temp_path

        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug(
                    "Could not delete temporary PDF %s: %s",
                    temp_path,
                    exc,
                )

    # ------------------------------------------------------------------
    # MAIN EXTRACTION API
    # ------------------------------------------------------------------

    def extract_document(
        self,
        source: PDFInput,
    ) -> ExtractedDocument:
        """
        Extract and classify a PDF using the clean PDF pipeline.

        ``source`` may be:
            - a string path
            - pathlib.Path
            - bytes
            - bytearray
            - io.BytesIO
            - another binary file-like object

        Returns an ExtractedDocument containing:
            document.title
            document.abstract
            document.body_text
            document.bibliography
            document.full_text
            document.pages
            document.sections
            document.metadata
        """

        # --------------------------------------------------------------
        # Filesystem input
        # --------------------------------------------------------------

        if isinstance(source, (str, Path)):
            pdf_path = Path(source)

            if not pdf_path.exists():
                raise FileNotFoundError(
                    f"PDF file not found: {pdf_path}"
                )

            if not pdf_path.is_file():
                raise ValueError(
                    f"PDF path is not a file: {pdf_path}"
                )

            cache_key = self._path_cache_key(pdf_path)

            if cache_key in self.cache:
                logger.debug(
                    "Using cached PDF extraction for %s",
                    pdf_path,
                )
                return self.cache[cache_key]

            try:
                document = extract_pdf(
                    pdf_path,
                    include_bibliography=True,
                )

            except Exception as exc:
                logger.error(
                    "Error extracting PDF %s: %s",
                    pdf_path,
                    exc,
                )
                raise

            self.cache[cache_key] = document

            logger.debug(
                "Extracted %d characters from %s using %s "
                "(body=%d, bibliography=%d)",
                len(document.full_text or ""),
                pdf_path,
                document.extractor,
                len(document.body_text or ""),
                len(document.bibliography or ""),
            )

            return document

        # --------------------------------------------------------------
        # In-memory input
        # --------------------------------------------------------------

        data = self._read_pdf_bytes(source)
        cache_key = self._bytes_cache_key(data)

        if cache_key in self.cache:
            logger.debug(
                "Using cached extraction for in-memory PDF %s",
                cache_key[:20],
            )
            return self.cache[cache_key]

        try:
            with self._temporary_pdf_path(data) as temp_path:
                document = extract_pdf(
                    temp_path,
                    include_bibliography=True,
                )

        except Exception as exc:
            logger.error(
                "Error extracting in-memory PDF: %s",
                exc,
            )
            raise

        # Do not expose the deleted temporary filename as if it were a
        # meaningful source file.
        try:
            document.file = "<memory>"
        except Exception:
            pass

        document.metadata.setdefault(
            "source_type",
            "memory",
        )

        self.cache[cache_key] = document

        logger.debug(
            "Extracted %d characters from in-memory PDF using %s "
            "(body=%d, bibliography=%d)",
            len(document.full_text or ""),
            document.extractor,
            len(document.body_text or ""),
            len(document.bibliography or ""),
        )

        return document

    # ------------------------------------------------------------------
    # CONVENIENCE / BACKWARDS-COMPATIBILITY METHODS
    # ------------------------------------------------------------------

    def extract_text_from_pdf(
        self,
        source: PDFInput,
    ) -> str:
        """
        Return full PDF text.

        This method is backwards-compatible with existing RefChecker
        callers while also accepting BytesIO and raw bytes.
        """
        document = self.extract_document(source)
        return document.full_text or ""

    def extract_body_from_pdf(
        self,
        source: PDFInput,
    ) -> str:
        """
        Return cleaned manuscript body without the bibliography.
        """
        document = self.extract_document(source)
        return document.body_text or ""

    def extract_bibliography_from_pdf(
        self,
        source: PDFInput,
    ) -> str:
        """
        Return the bibliography already identified by pdf_pipeline.
        """
        document = self.extract_document(source)
        return document.bibliography or ""

    def extract_title_from_pdf(
        self,
        source: PDFInput,
    ) -> Optional[str]:
        """
        Return the title detected by pdf_pipeline.
        """
        try:
            document = self.extract_document(source)
            return document.title or None

        except Exception as exc:
            logger.warning(
                "Could not extract PDF title: %s",
                exc,
            )
            return None

    def extract_bibliography_from_text(
        self,
        text: str,
    ) -> str:
        """
        Compatibility method for callers that already have plain text.

        New PDF code should prefer:
            extract_bibliography_from_pdf(source)
        """
        if not text:
            return ""

        _, bibliography, _ = split_text_and_references(text)

        return bibliography or ""

    # ------------------------------------------------------------------
    # PAPER OBJECT
    # ------------------------------------------------------------------

    def create_local_file_paper(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Paper:
        """
        Create a Paper object from a local file.

        This method intentionally remains path-based because the resulting
        Paper represents a local file and stores its path.
        """

        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"File not found: {file_path}"
            )

        document = None

        if file_path.lower().endswith(".pdf"):
            try:
                document = self.extract_document(file_path)

            except Exception as exc:
                logger.warning(
                    "Could not extract PDF %s: %s",
                    file_path,
                    exc,
                )

        if metadata:
            title = metadata.get(
                "title",
                (
                    document.title
                    if document and document.title
                    else os.path.basename(file_path)
                ),
            )

            authors = metadata.get(
                "authors",
                [],
            )

            abstract = metadata.get(
                "abstract",
                document.abstract if document else "",
            )

            year = metadata.get("year")
            venue = metadata.get("venue", "")
            url = metadata.get("url", "")
            doi = metadata.get("doi", "")
            arxiv_id = metadata.get("arxiv_id", "")

        else:
            title = (
                document.title
                if document and document.title
                else os.path.splitext(
                    os.path.basename(file_path)
                )[0]
            )

            authors = []

            abstract = (
                document.abstract
                if document
                else ""
            )

            year = None
            venue = ""
            url = ""
            doi = ""
            arxiv_id = ""

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            venue=venue,
            url=url,
            doi=doi,
            arxiv_id=arxiv_id,
            pdf_path=file_path,
        )

    # ------------------------------------------------------------------
    # CACHE
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Clear all cached PDF extraction results."""
        self.cache.clear()
        logger.debug("PDF extraction cache cleared")