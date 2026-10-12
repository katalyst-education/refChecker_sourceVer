from pathlib import Path
from collections import Counter
import re

import pymupdf  # PyMuPDF

from ..models import ExtractedDocument
from .base_text_extractor import BaseTextExtractor
from .common_helpers import normalize_unicode_basic, normalize_for_repetition


REPEATED_TEXT_MIN_FRACTION = 0.35
MIN_TEXT_CHARS = 2


def slide_clean_text(text: str) -> str:
    if not text:
        return ""

    text = normalize_unicode_basic(text)

    # Simple slide hyphenation fix.
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slide_normalize_for_repetition(text: str) -> str:
    return normalize_for_repetition(text, slide_clean_text)


def slide_is_probably_junk(text: str) -> bool:
    text = slide_clean_text(text)

    if len(text) < MIN_TEXT_CHARS:
        return True

    if re.fullmatch(r"\d+", text):
        return True

    letters = sum(ch.isalpha() for ch in text)
    if len(text) > 0 and letters / len(text) < 0.2:
        return True

    return False


def extract_blocks_from_slide_pdf(pdf_path: Path) -> list[dict]:
    """
    Extract text blocks from each slide/page with layout coordinates
    and font-size information.

    Uses page.get_text("dict") instead of page.get_text("blocks"),
    because "blocks" does not expose font size.
    """
    pdf = pymupdf.open(pdf_path)
    slides = []

    for page_index, page in enumerate(pdf, start=1):
        page_width = page.rect.width
        page_height = page.rect.height

        raw = page.get_text("dict")
        blocks = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue

            block_lines = []
            font_sizes = []
            font_names = []
            flags = []

            x0, y0, x1, y1 = block["bbox"]

            for line in block.get("lines", []):
                line_parts = []

                for span in line.get("spans", []):
                    span_text = slide_clean_text(span.get("text", ""))

                    if not span_text:
                        continue

                    line_parts.append(span_text)
                    font_sizes.append(float(span.get("size", 0)))
                    font_names.append(span.get("font", ""))
                    flags.append(int(span.get("flags", 0)))

                if line_parts:
                    block_lines.append(" ".join(line_parts))

            text = slide_clean_text(" ".join(block_lines))

            if slide_is_probably_junk(text):
                continue

            if font_sizes:
                max_font_size = max(font_sizes)
                avg_font_size = sum(font_sizes) / len(font_sizes)
            else:
                max_font_size = 0
                avg_font_size = 0

            blocks.append({
                "text": text,
                "x0": round(float(x0), 2),
                "y0": round(float(y0), 2),
                "x1": round(float(x1), 2),
                "y1": round(float(y1), 2),
                "width": round(float(x1 - x0), 2),
                "height": round(float(y1 - y0), 2),
                "page_width": round(float(page_width), 2),
                "page_height": round(float(page_height), 2),
                "max_font_size": round(max_font_size, 2),
                "avg_font_size": round(avg_font_size, 2),
                "font_names": sorted(set(font_names)),
                "flags": sorted(set(flags)),
            })

        blocks.sort(key=lambda b: (b["y0"], b["x0"]))

        slides.append({
            "slide_number": page_index,
            "page_width": round(float(page_width), 2),
            "page_height": round(float(page_height), 2),
            "blocks": blocks,
        })

    pdf.close()
    return slides


def find_repeated_slide_blocks(slides: list[dict], min_fraction: float = 0.35) -> set[str]:
    per_slide_texts = []

    for slide in slides:
        seen_on_slide = set()

        for block in slide["blocks"]:
            norm = slide_normalize_for_repetition(block["text"])
            if norm:
                seen_on_slide.add(norm)

        per_slide_texts.extend(seen_on_slide)

    counts = Counter(per_slide_texts)

    if not slides:
        return set()

    threshold = max(2, int(len(slides) * min_fraction))

    return {
        text for text, count in counts.items()
        if count >= threshold
    }


def remove_repeated_slide_blocks(slides: list[dict], repeated: set[str]) -> list[dict]:
    cleaned_slides = []

    for slide in slides:
        cleaned_blocks = []

        for block in slide["blocks"]:
            norm = slide_normalize_for_repetition(block["text"])

            if norm in repeated:
                continue

            cleaned_blocks.append(block)

        cleaned_slides.append({
            **slide,
            "blocks": cleaned_blocks,
        })

    return cleaned_slides


BULLET_PREFIX_RE = re.compile(
    r"""^\s*(
        [•●▪▫◦‣⁃·∙-]          |
        \d+[\).:]              |
        [a-zA-Z][\).:]         |
        [ivxlcdmIVXLCDM]+[\).:]
    )\s+""",
    re.VERBOSE,
)


def starts_with_bullet_dot(text: str) -> bool:
    text = slide_clean_text(text)
    return bool(text and BULLET_PREFIX_RE.match(text))


def estimate_slide_body_font_size(blocks: list[dict]) -> float:
    sizes = [
        b.get("avg_font_size", 0)
        for b in blocks
        if b.get("avg_font_size", 0) > 0
    ]

    if not sizes:
        return 0

    sizes = sorted(sizes)
    return sizes[len(sizes) // 2]


def guess_slide_title(slide: dict) -> str:
    blocks = slide["blocks"]

    if not blocks:
        return ""

    page_height = slide["page_height"]
    page_width = slide["page_width"]

    body_font_size = estimate_slide_body_font_size(blocks)

    candidates = []

    for block in blocks:
        text = slide_clean_text(block["text"])
        if not text:
            continue

        word_count = len(text.split())

        if block["y0"] > page_height * 0.40:
            continue

        if starts_with_bullet_dot(text):
            continue

        if word_count > 18:
            continue

        font_size = block.get("max_font_size", 0)

        if body_font_size and font_size < body_font_size * 1.10:
            continue

        candidates.append(block)

    if not candidates:
        for block in blocks:
            text = slide_clean_text(block["text"])
            if block["y0"] <= page_height * 0.40 and not starts_with_bullet_dot(text):
                return text

        return blocks[0]["text"]

    def score_title_block(block: dict) -> float:
        text = slide_clean_text(block["text"])
        word_count = len(text.split())

        score = 0.0
        score += block.get("max_font_size", 0) * 10
        score += max(0, 100 - (block["y0"] / page_height) * 180)
        score += min((block["width"] / page_width) * 20, 20)

        if 2 <= word_count <= 12:
            score += 20

        if text.endswith("."):
            score -= 20

        if starts_with_bullet_dot(text):
            score -= 200

        return score

    candidates.sort(key=score_title_block, reverse=True)
    return candidates[0]["text"]


def build_clean_slide_text(slides: list[dict]) -> list[dict]:
    output_slides = []

    for slide in slides:
        title = guess_slide_title(slide)

        lines = []
        seen = set()

        for block in slide["blocks"]:
            text = slide_clean_text(block["text"])
            if not text:
                continue

            norm = slide_normalize_for_repetition(text)
            if norm in seen:
                continue

            seen.add(norm)
            lines.append(text)

        output_slides.append({
            "slide_number": slide["slide_number"],
            "title_guess": title,
            "text": "\n".join(lines).strip(),
            "blocks": slide["blocks"],
        })

    return output_slides


class SlideTextExtractor(BaseTextExtractor):
    name = "slide"

    def extract(self,pdf_path: Path,doc_type: str,include_bibliography: bool = False) -> ExtractedDocument:
        slides = extract_blocks_from_slide_pdf(pdf_path)

        repeated_blocks = find_repeated_slide_blocks(
            slides,
            min_fraction=REPEATED_TEXT_MIN_FRACTION,
        )

        cleaned_slides = remove_repeated_slide_blocks(slides, repeated_blocks)
        final_slides = build_clean_slide_text(cleaned_slides)

        text_parts = []
        title = ""

        for slide in final_slides:
            if not title and slide.get("title_guess"):
                title = slide["title_guess"]

            text_parts.append(f"=== Slide {slide['slide_number']} ===")

            if slide.get("title_guess"):
                text_parts.append(f"Title guess: {slide['title_guess']}")

            text_parts.append("")
            text_parts.append(slide.get("text", ""))
            text_parts.append("")

        full_text = "\n".join(text_parts).strip()

        return ExtractedDocument(
            file=pdf_path.name,
            doc_type=doc_type,
            extractor=self.name,
            title=title,
            full_text=full_text,
            pages=final_slides,
            metadata={
                "removed_repeated_blocks": sorted(repeated_blocks),
            },
        )