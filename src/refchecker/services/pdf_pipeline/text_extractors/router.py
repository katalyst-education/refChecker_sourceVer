from pathlib import Path

from ..models import ExtractedDocument
from .fallback_text_extractor import FallbackTextExtractor
from .one_column_text_extractor import OneColumnTextExtractor
from .slide_text_extractor import SlideTextExtractor
from .two_column_text_extractor import TwoColumnTextExtractor


class TextExtractorRouter:
    def __init__(self):
        self.slide_extractor = SlideTextExtractor()
        self.one_column_extractor = OneColumnTextExtractor()
        self.two_column_extractor = TwoColumnTextExtractor()
        self.fallback_extractor = FallbackTextExtractor()

    def extract(
        self,
        pdf_path: Path,
        doc_type: str,
        include_bibliography: bool = False,
    ) -> ExtractedDocument:

        if doc_type == "presentation_slide":
            return self.slide_extractor.extract(
                pdf_path,
                doc_type,
                include_bibliography=include_bibliography,
            )

        if doc_type == "two_column_paper":
            return self.two_column_extractor.extract(
                pdf_path,
                doc_type,
                include_bibliography=include_bibliography,
            )

        if doc_type == "one_column_paper":
            return self.one_column_extractor.extract(
                pdf_path,
                doc_type,
                include_bibliography=include_bibliography,
            )

        return self.fallback_extractor.extract(
            pdf_path,
            doc_type,
            include_bibliography=include_bibliography,
        )