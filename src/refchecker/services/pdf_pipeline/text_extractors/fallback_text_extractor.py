from pathlib import Path
from pypdf import PdfReader

from ..models import ExtractedDocument
from .base_text_extractor import BaseTextExtractor


class FallbackTextExtractor(BaseTextExtractor):
    name = "fallback"

    def extract(self,pdf_path: Path,doc_type: str,include_bibliography: bool = False) -> ExtractedDocument:
        reader = PdfReader(str(pdf_path))
        pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text(extraction_mode="layout")
            except TypeError:
                text = page.extract_text()

            pages.append({
                "page_number": page_number,
                "text": text or "",
            })

        full_text = "\n\n".join(page["text"] for page in pages).strip()

        title = pdf_path.stem
        for line in full_text.splitlines():
            line = line.strip()
            if line:
                title = line
                break

        return ExtractedDocument(
            file=pdf_path.name,
            doc_type=doc_type,
            extractor=self.name,
            title=title,
            full_text=full_text,
            pages=pages,
        )