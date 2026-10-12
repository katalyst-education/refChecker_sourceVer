from pathlib import Path
from ..models import ExtractedDocument


class BaseTextExtractor:
    name = "base"

    def extract(
        self,
        pdf_path: Path,
        doc_type: str,
        include_bibliography: bool = False,
    ) -> ExtractedDocument:
        raise NotImplementedError