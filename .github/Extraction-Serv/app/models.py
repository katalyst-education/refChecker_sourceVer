from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CheckSource(str, Enum):
    URL = "url"
    FILE = "file"
    TEXT = "text"


class ExtractionRequest(BaseModel):
    source_type: CheckSource
    source_value: str
    llm_provider: Optional[str] = "anthropic"
    llm_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class TextExtractionRequest(BaseModel):
    source_text: str
    llm_provider: Optional[str] = "anthropic"
    llm_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class ExtractedReference(BaseModel):
    title: str
    authors: List[str] = []
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    cited_url: Optional[str] = None


class ExtractionResponse(BaseModel):
    paper_title: str
    paper_source: str
    extraction_method: Optional[str] = None
    bibliography_source_kind: Optional[str] = None
    references: List[Dict[str, Any]]
    summary: Dict[str, int]

