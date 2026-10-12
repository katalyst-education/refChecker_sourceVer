from pathlib import Path
import re

import pymupdf  # PyMuPDF

from ..config import GROBID_URL
from ..models import ExtractedDocument
from .base_text_extractor import BaseTextExtractor
from .common_helpers import join_spans_with_position_spacing
from .paper_helpers import (
    REPEATED_TEXT_MIN_FRACTION,
    paper_clean_text,
    paper_is_probably_junk,
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
# CONFIG
# ============================================================

FULL_WIDTH_BLOCK_RATIO = 0.65
FIRST_PAGE_TOP_FULL_WIDTH_ZONE = 0.30


# ============================================================
# PYMUPDF TWO-COLUMN BLOCK EXTRACTION
# ============================================================

def extract_blocks_from_two_column_pdf(pdf_path: Path) -> list[dict]:
    """
    Extract text blocks from each page with coordinates and font metadata.

    Keeps real x/y coordinates so left and right columns can be ordered separately.
    """
    pdf = pymupdf.open(pdf_path)
    pages = []

    for page_index, page in enumerate(pdf, start=1):
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)

        raw = page.get_text("dict")
        blocks = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue

            x0, y0, x1, y1 = block["bbox"]

            block_lines = []
            font_sizes = []
            font_names = []
            flags = []

            for line in block.get("lines", []):
                spans = line.get("spans", [])

                for span in spans:
                    span_text = paper_clean_text(span.get("text", ""))

                    if not span_text:
                        continue

                    font_sizes.append(float(span.get("size", 0)))
                    font_names.append(span.get("font", ""))
                    flags.append(int(span.get("flags", 0)))

                line_text = join_spans_with_position_spacing(
                    spans,
                    cleaner=paper_clean_text,
                )

                if line_text:
                    block_lines.append(line_text)

            text = paper_clean_text(" ".join(block_lines))

            if paper_is_probably_junk(text):
                continue

            if font_sizes:
                max_font_size = max(font_sizes)
                avg_font_size = sum(font_sizes) / len(font_sizes)
            else:
                max_font_size = 0
                avg_font_size = 0

            blocks.append({
                "text": text,
                "page_number": page_index,
                "page_width": round(page_width, 2),
                "page_height": round(page_height, 2),
                "x0": round(float(x0), 2),
                "y0": round(float(y0), 2),
                "x1": round(float(x1), 2),
                "y1": round(float(y1), 2),
                "width": round(float(x1 - x0), 2),
                "height": round(float(y1 - y0), 2),
                "max_font_size": round(max_font_size, 2),
                "avg_font_size": round(avg_font_size, 2),
                "font_names": sorted(set(font_names)),
                "flags": sorted(set(flags)),
            })

        ordered_blocks = order_two_column_blocks(
            blocks=blocks,
            page_width=page_width,
            page_height=page_height,
            page_number=page_index,
        )

        pages.append({
            "page_number": page_index,
            "page_width": round(page_width, 2),
            "page_height": round(page_height, 2),
            "blocks": ordered_blocks,
        })

    pdf.close()
    return pages


def order_two_column_blocks(
    blocks: list[dict],
    page_width: float,
    page_height: float,
    page_number: int,
) -> list[dict]:
    """
    Two-column reading order:
    - top full-width blocks first on page 1
    - left column top-to-bottom
    - right column top-to-bottom
    - lower full-width blocks inserted by vertical position
    """
    if not blocks:
        return []

    top_full_width = []
    normal_blocks = []
    lower_full_width = []

    for block in blocks:
        width_ratio = block["width"] / page_width
        y_center_ratio = ((block["y0"] + block["y1"]) / 2) / page_height

        if width_ratio >= FULL_WIDTH_BLOCK_RATIO:
            if page_number == 1 and y_center_ratio <= FIRST_PAGE_TOP_FULL_WIDTH_ZONE:
                top_full_width.append(block)
            else:
                lower_full_width.append(block)
        else:
            normal_blocks.append(block)

    left_column = []
    right_column = []

    for block in normal_blocks:
        x_center = (block["x0"] + block["x1"]) / 2

        if x_center < page_width * 0.50:
            left_column.append(block)
        else:
            right_column.append(block)

    top_full_width.sort(key=lambda block: (block["y0"], block["x0"]))
    lower_full_width.sort(key=lambda block: (block["y0"], block["x0"]))
    left_column.sort(key=lambda block: (block["y0"], block["x0"]))
    right_column.sort(key=lambda block: (block["y0"], block["x0"]))

    column_ordered = left_column + right_column

    output = []
    remaining_full_width = lower_full_width.copy()

    for block in column_ordered:
        while remaining_full_width and remaining_full_width[0]["y0"] <= block["y0"]:
            output.append(remaining_full_width.pop(0))

        output.append(block)

    output.extend(remaining_full_width)

    return top_full_width + output


# ============================================================
# TITLE FALLBACK
# ============================================================

def guess_title_from_pages(pages: list[dict], pdf_path: Path) -> str:
    if not pages:
        return pdf_path.stem

    first_page = pages[0]
    blocks = first_page.get("blocks", [])

    if not blocks:
        return pdf_path.stem

    page_height = first_page.get("page_height", 1) or 1

    candidates = []

    for block in blocks:
        text = paper_clean_text(block.get("text", ""))

        if not text:
            continue

        word_count = len(text.split())

        if word_count > 25:
            continue

        if block.get("y0", 0) > page_height * 0.35:
            continue

        candidates.append(block)

    if not candidates:
        for block in blocks:
            text = paper_clean_text(block.get("text", ""))
            if text:
                return text

        return pdf_path.stem

    def score_title_block(block: dict) -> float:
        text = paper_clean_text(block.get("text", ""))
        word_count = len(text.split())

        score = 0.0
        score += block.get("max_font_size", 0) * 10
        score += max(0, 100 - (block["y0"] / page_height) * 180)

        if 3 <= word_count <= 18:
            score += 20

        if text.endswith("."):
            score -= 20

        if re.match(r"^\d+(?:\.\d+)*\.?\s+", text):
            score -= 30

        return score

    candidates.sort(key=score_title_block, reverse=True)

    return paper_clean_text(candidates[0]["text"]) or pdf_path.stem


# ============================================================
# EXTRACTOR CLASS
# ============================================================

class TwoColumnTextExtractor(BaseTextExtractor):
    name = "two_column_pymupdf_with_grobid_metadata"

    def extract(self,pdf_path: Path,doc_type: str,include_bibliography: bool = False) -> ExtractedDocument:
        grobid_metadata = extract_grobid_metadata(pdf_path)

        pages = extract_blocks_from_two_column_pdf(pdf_path)

        repeated_blocks = find_repeated_paper_blocks(
            pages,
            min_fraction=REPEATED_TEXT_MIN_FRACTION,
        )

        cleaned_pages = remove_repeated_paper_blocks(
            pages,
            repeated_blocks,
        )

        front_matter_trim_debug = default_front_matter_trim_debug()

        if grobid_metadata.get("title") or grobid_metadata.get("abstract"):
            cleaned_pages, front_matter_trim_debug = trim_pages_to_first_body_heading(
                cleaned_pages
            )

        paper = build_clean_paper_text(cleaned_pages)
        section_headings = paper.get("section_headings", [])

        title = grobid_metadata.get("title") or guess_title_from_pages(pages, pdf_path)
        abstract = grobid_metadata.get("abstract", "")
        author_keywords = grobid_metadata.get("author_keywords", [])

        clean_text = paper.get("text", "")

        body_text, bibliography, references_debug = (
            split_text_and_references(clean_text)
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
                "body_source": "pymupdf_two_column_blocks",
                "metadata_source": (
                    "grobid"
                    if not grobid_metadata.get("grobid_error")
                    else "none"
                ),
                "grobid_url": GROBID_URL,
                "grobid_error": grobid_metadata.get("grobid_error", ""),
                "removed_repeated_blocks": sorted(repeated_blocks),
                "front_matter_trim": front_matter_trim_debug,
                "two_column_ordering": {
                    "full_width_block_ratio": FULL_WIDTH_BLOCK_RATIO,
                    "first_page_top_full_width_zone":
                        FIRST_PAGE_TOP_FULL_WIDTH_ZONE,
                    "strategy":
                        "top_full_width_then_left_column_then_right_column",
                },
                "references": references_debug,
                "grobid_has_references":
                    grobid_metadata.get("has_references", False),
                "grobid_reference_count":
                    grobid_metadata.get("reference_count", 0),
            },
        )