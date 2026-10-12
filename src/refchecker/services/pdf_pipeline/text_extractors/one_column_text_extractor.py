from pathlib import Path
import re

import pymupdf  # PyMuPDF

from ..config import GROBID_URL
from ..models import ExtractedDocument
from .base_text_extractor import BaseTextExtractor
from .paper_helpers import (
    REPEATED_TEXT_MIN_FRACTION,
    paper_clean_text,
    paper_is_probably_junk,
    merge_reconstructed_lines_into_text_units,
    find_repeated_paper_blocks,
    remove_repeated_paper_blocks,
    build_clean_paper_text,
    extract_grobid_metadata,
    default_front_matter_trim_debug,
    trim_pages_to_first_body_heading,
    trim_text_before_references,
    split_text_and_references,
)


# ============================================================
# CHARACTER-BASED ONE-COLUMN EXTRACTION
# ============================================================

def extract_text_units_from_chars(page) -> list[str]:
    """
    Reconstruct page text from individual character positions.

    Good for one-column academic PDFs where block extraction causes broken
    spacing, broken words, or bad line grouping.
    """
    raw = page.get_text("rawdict")
    chars = []

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = float(span.get("size", 10))

                for char in span.get("chars", []):
                    value = char.get("c", "")

                    if not value:
                        continue

                    x0, y0, x1, y1 = char.get("bbox", [0, 0, 0, 0])

                    chars.append({
                        "c": value,
                        "x0": float(x0),
                        "y0": float(y0),
                        "x1": float(x1),
                        "y1": float(y1),
                        "y_center": (float(y0) + float(y1)) / 2,
                        "size": size,
                    })

    if not chars:
        return []

    chars.sort(key=lambda item: (item["y_center"], item["x0"]))

    visual_lines = []
    current_line = []
    current_y = None

    median_size = sorted(char["size"] for char in chars)[len(chars) // 2]
    y_tolerance = median_size * 0.45

    for char in chars:
        if current_y is None:
            current_line = [char]
            current_y = char["y_center"]
            continue

        if abs(char["y_center"] - current_y) <= y_tolerance:
            current_line.append(char)
            current_y = (current_y * 0.8) + (char["y_center"] * 0.2)
        else:
            visual_lines.append(current_line)
            current_line = [char]
            current_y = char["y_center"]

    if current_line:
        visual_lines.append(current_line)

    reconstructed_lines = []

    for line_chars in visual_lines:
        line_chars.sort(key=lambda item: item["x0"])

        line_font_size = sorted(
            char["size"] for char in line_chars
        )[len(line_chars) // 2]

        space_threshold = line_font_size * 0.22

        parts = []
        previous_char = None

        for char in line_chars:
            if previous_char is not None:
                gap = char["x0"] - previous_char["x1"]

                if gap > space_threshold:
                    parts.append(" ")

            parts.append(char["c"])
            previous_char = char

        text = paper_clean_text("".join(parts))

        if text and not paper_is_probably_junk(text):
            reconstructed_lines.append({
                "text": text,
                "x0": min(char["x0"] for char in line_chars),
                "y0": min(char["y0"] for char in line_chars),
                "x1": max(char["x1"] for char in line_chars),
                "y1": max(char["y1"] for char in line_chars),
                "font_size": line_font_size,
            })

    reconstructed_lines.sort(key=lambda item: (item["y0"], item["x0"]))

    return merge_reconstructed_lines_into_text_units(reconstructed_lines)


def extract_pages_text_char_based(pdf_path: Path) -> list[dict]:
    pdf = pymupdf.open(pdf_path)
    pages = []

    for page_index, page in enumerate(pdf, start=1):
        text_units = extract_text_units_from_chars(page)

        blocks = [
            {
                "text": unit,
                "page_number": page_index,
                "page_width": round(float(page.rect.width), 2),
                "page_height": round(float(page.rect.height), 2),

                # Synthetic coordinates.
                # Enough for output and repeated-text logic.
                "x0": 0,
                "y0": index,
                "x1": 0,
                "y1": index,
                "width": 0,
                "height": 0,

                # Char reconstruction currently does not preserve font metadata.
                "max_font_size": 0,
                "avg_font_size": 0,
                "font_names": [],
                "flags": [],
            }
            for index, unit in enumerate(text_units)
        ]

        pages.append({
            "page_number": page_index,
            "page_width": round(float(page.rect.width), 2),
            "page_height": round(float(page.rect.height), 2),
            "blocks": blocks,
        })

    pdf.close()
    return pages


# ============================================================
# TITLE FALLBACK
# ============================================================

def guess_title_from_text(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        line = paper_clean_text(line)

        if not line:
            continue

        if line.startswith("## "):
            continue

        if len(line.split()) > 25:
            continue

        return line

    return fallback


# ============================================================
# EXTRACTOR CLASS
# ============================================================

class OneColumnTextExtractor(BaseTextExtractor):
    name = "one_column_pymupdf_char_with_grobid_metadata"

    def extract(self,pdf_path: Path,doc_type: str,include_bibliography: bool = False) -> ExtractedDocument:
        grobid_metadata = extract_grobid_metadata(pdf_path)

        pages = extract_pages_text_char_based(pdf_path)

        repeated_blocks = find_repeated_paper_blocks(
            pages,
            min_fraction=REPEATED_TEXT_MIN_FRACTION,
        )

        cleaned_pages = remove_repeated_paper_blocks(
            pages,
            repeated_blocks,
        )

        front_matter_trim_debug = default_front_matter_trim_debug()

        # Important for edge cases:
        # page 1 may be mixed/two-column front matter even when the body is one-column.
        if grobid_metadata.get("title") or grobid_metadata.get("abstract"):
            cleaned_pages, front_matter_trim_debug = trim_pages_to_first_body_heading(
                cleaned_pages
            )

        paper = build_clean_paper_text(cleaned_pages)
        section_headings = paper.get("section_headings", [])

        title = grobid_metadata.get("title", "")
        abstract = grobid_metadata.get("abstract", "")
        author_keywords = grobid_metadata.get("author_keywords", [])

        if not title:
            title = guess_title_from_text(
                paper.get("text", ""),
                fallback=pdf_path.stem,
            )

                
        clean_text = paper.get("text", "")

        body_text, bibliography, references_debug = (
            split_text_and_references(clean_text)
        )
        logger.warning(
            "PIPELINE REFERENCES TRACE: "
            "clean=%d body=%d bibliography=%d "
            "matches=%s positions=%s reason=%s preview=%r "
            "bib_start=%r",
            len(clean_text or ""),
            len(body_text or ""),
            len(bibliography or ""),
            references_debug.get("references_match_count"),
            references_debug.get("references_candidate_positions"),
            references_debug.get("references_split_reason"),
            references_debug.get("references_start_preview"),
            (bibliography or "")[:500],
        )
        body_parts = []

        if title:
            body_parts.append(title)

        if abstract:
            body_parts.append("## Abstract\n" + abstract)

        if body_text:
            body_parts.append(body_text)

        clean_body = "\n\n".join(body_parts).strip()
        if include_bibliography and bibliography:
            full_text = (
                clean_body
                + "\n\n## References\n"
                + bibliography
            ).strip()
        else:
            full_text = clean_body
        return ExtractedDocument(
            file=pdf_path.name,
            doc_type=doc_type,
            extractor=self.name,
            title=title,
            abstract=abstract,
            author_keywords=author_keywords,

            full_text=full_text,

            body_text=clean_body,
            bibliography=bibliography,

            pages=paper.get("pages", []),

            sections=[
                {
                    "heading": item.get("heading", ""),
                    "page_number": item.get("page_number"),
                }
                for item in section_headings
            ],

            metadata={
                "body_source": "pymupdf_char_reconstruction",
                "metadata_source": (
                    "grobid"
                    if not grobid_metadata.get("grobid_error")
                        else "none"
                ),
                "grobid_url": GROBID_URL,
                "grobid_error": grobid_metadata.get("grobid_error", ""),
                "removed_repeated_blocks": sorted(repeated_blocks),
                "front_matter_trim": front_matter_trim_debug,
                "references": references_debug,
            },
        )
        