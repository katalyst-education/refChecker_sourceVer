from pathlib import Path
from pypdf import PdfReader

from ..models import (
    ExtractedDocument,
    PDFExtractionError,
    build_extraction_diagnostics,
)
from .base_text_extractor import BaseTextExtractor
from .paper_helpers import (
    assemble_document_text,
    extraction_diagnostics_from_references,
    split_text_and_references,
)


class FallbackTextExtractor(BaseTextExtractor):
    name = "fallback"

    def extract(
        self,
        pdf_path: Path,
        doc_type: str,
        include_bibliography: bool = False,
    ) -> ExtractedDocument:
        try:
            reader = PdfReader(str(pdf_path))
            page_count = len(reader.pages)
        except Exception as exc:
            diagnostics = build_extraction_diagnostics(
                document_status="failed",
                bibliography_status="extraction_failed",
                extractor=self.name,
                errors=[f"Could not open PDF for fallback extraction: {exc}"],
                reason="Fallback PDF parser could not read the document",
            )
            raise PDFExtractionError(
                "Fallback PDF extraction could not read the document",
                diagnostics,
            ) from exc

        pages = []
        failed_pages = []
        errors = []

        for page_number in range(1, page_count + 1):
            try:
                page = reader.pages[page_number - 1]
            except Exception as exc:
                pages.append({
                    "page_number": page_number,
                    "text": "",
                })
                failed_pages.append(page_number)
                errors.append(f"Page {page_number}: {exc}")
                continue

            try:
                text = page.extract_text(extraction_mode="layout")
            except TypeError:
                try:
                    text = page.extract_text()
                except Exception as exc:
                    text = ""
                    failed_pages.append(page_number)
                    errors.append(f"Page {page_number}: {exc}")
            except Exception as exc:
                text = ""
                failed_pages.append(page_number)
                errors.append(f"Page {page_number}: {exc}")

            pages.append({
                "page_number": page_number,
                "text": text or "",
            })

        extracted_text = "\n\n".join(page["text"] for page in pages).strip()
        if not extracted_text:
            diagnostics = build_extraction_diagnostics(
                document_status="failed",
                bibliography_status="extraction_failed",
                extractor=self.name,
                errors=errors or ["No text could be extracted from the PDF"],
                failed_pages=failed_pages,
                reason="No usable page text was extracted",
            )
            raise PDFExtractionError(
                "No text could be extracted from the PDF",
                diagnostics,
            )

        if doc_type == "presentation_slide":
            body_text = extracted_text
            bibliography = ""
            diagnostics = build_extraction_diagnostics(
                bibliography_status="not_applicable",
                document_status="partial" if errors else "complete",
                extractor=self.name,
                errors=errors,
                failed_pages=failed_pages,
                reason="Bibliography splitting is not applicable to slides",
            )
        else:
            try:
                body_text, bibliography, references_debug = (
                    split_text_and_references(extracted_text)
                )
            except Exception as exc:
                diagnostics = extraction_diagnostics_from_references(
                    None,
                    "",
                    extractor=self.name,
                    errors=errors + [str(exc)],
                    failed_pages=failed_pages,
                )
                diagnostics["document_status"] = "partial"
                raise PDFExtractionError(
                    "Bibliography detection failed",
                    diagnostics,
                    extracted_text=extracted_text,
                ) from exc

            diagnostics = extraction_diagnostics_from_references(
                references_debug,
                bibliography,
                extractor=self.name,
                errors=errors,
                failed_pages=failed_pages,
            )

        body_text, full_text = assemble_document_text(
            body_text,
            bibliography,
            include_bibliography,
            references_debug if doc_type != "presentation_slide" else None,
        )

        title = pdf_path.stem
        for line in body_text.splitlines():
            line = line.strip()
            if line:
                title = line
                break

        return ExtractedDocument(
            file=pdf_path.name,
            doc_type=doc_type,
            extractor=self.name,
            title=title,
            body_text=body_text,
            bibliography=bibliography,
            full_text=full_text,
            pages=pages,
            metadata={
                "extraction_diagnostics": diagnostics,
                **(
                    {"references": references_debug}
                    if doc_type != "presentation_slide"
                    else {}
                ),
            },
        )