from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import json


@dataclass
class ExtractedDocument:
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