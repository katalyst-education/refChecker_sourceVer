from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import json


class PDFExtractionError(RuntimeError):
    """A PDF extraction failure with structured diagnostic details."""

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any],
        *,
        extracted_text: str = "",
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.extracted_text = extracted_text


def build_extraction_diagnostics(
    *,
    bibliography_status: str,
    document_status: str = "complete",
    extractor: str = "",
    classification: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    failed_pages: list[int] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Build the additive diagnostics stored in ExtractedDocument.metadata."""
    return {
        "document_status": document_status,
        "bibliography_status": bibliography_status,
        "extractor": extractor,
        "classification": classification or {},
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "failed_pages": list(failed_pages or []),
        "reason": reason,
    }


@dataclass
class ExtractedDocument:
    """Structured PDF output.

    For academic papers, ``body_text`` excludes the bibliography. The
    bibliography remains available independently; ``include_bibliography``
    controls only whether it is appended to ``full_text``. Extraction
    diagnostics live in ``metadata`` to preserve the serialized field shape.
    """

    file: str
    doc_type: str
    extractor: str

    title: str = ""
    abstract: str = ""
    author_keywords: list[str] = field(default_factory=list)

    # Text outputs
    body_text: str = ""
    bibliography: str = ""
    full_text: str = ""

    sections: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save_json(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def save_txt(self, path: Path) -> None:
        path.write_text(
            self.full_text.strip() + "\n",
            encoding="utf-8",
        )