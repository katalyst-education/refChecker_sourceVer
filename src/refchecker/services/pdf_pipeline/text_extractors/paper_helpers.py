from pathlib import Path
import re
import xml.etree.ElementTree as ET

import requests

from ..config import GROBID_URL
from .common_helpers import (
    normalize_unicode_basic,
    normalize_for_repetition,
)


# ============================================================
# CONFIG
# ============================================================

REPEATED_TEXT_MIN_FRACTION = 0.35
REPEATED_TEXT_MIN_COUNT = 3
REPEATED_TEXT_TOP_ZONE = 0.12
REPEATED_TEXT_BOTTOM_ZONE = 0.88

MIN_TEXT_CHARS = 2

DROP_REFERENCES_SECTION = False
INCLUDE_PAGE_HEADERS = False

USE_GROBID_METADATA = True


# ============================================================
# TEXT CLEANING
# ============================================================

COORDINATION_HYPHEN_WORDS = {
    "und", "oder", "bzw", "sowie",
    "and", "or",
}

KEEP_HYPHEN_SECOND_PARTS = {
    "based", "driven", "oriented", "related", "specific",
    "dependent", "independent", "aware", "centric", "focused",
    "guided", "supported", "enhanced", "enabled", "mediated",
    "assisted", "generated", "making", "solving", "learning",
    "teaching", "training", "testing", "seeking", "sharing",
    "taking", "setting", "building", "processing", "mining",
    "ranking", "matching", "checking", "tracking", "monitoring",
}

KEEP_HYPHEN_FIRST_PARTS = {
    "decision", "problem", "evidence", "rule", "case", "model",
    "data", "knowledge", "context", "task", "domain", "user",
    "machine", "deep", "self", "semi", "cross", "multi", "non",
    "pre", "post", "real", "time", "state", "of", "the", "art",
}


def fix_broken_line_hyphenation(text: str) -> str:
    """
    Fix line-break hyphenation while preserving common real compounds.

    Examples:
        unterschied- liche -> unterschiedliche
        decision- making -> decision-making
        media- and information-literate -> media- and information-literate
    """
    if not text:
        return ""

    def repl(match: re.Match) -> str:
        before = match.group(1)
        after = match.group(2)

        before_lower = before.lower()
        after_lower = after.lower()

        if after_lower in COORDINATION_HYPHEN_WORDS:
            return f"{before}- {after}"

        if (
            before_lower in KEEP_HYPHEN_FIRST_PARTS
            or after_lower in KEEP_HYPHEN_SECOND_PARTS
        ):
            return f"{before}-{after}"

        if after[:1].isupper():
            return f"{before}- {after}"

        return before + after

    return re.sub(
        r"\b([^\W\d_]+)-\s+([^\W\d_]+)\b",
        repl,
        text,
        flags=re.UNICODE,
    )


def fix_split_uppercase_words(text: str) -> str:
    """
    Fix artifacts like:
        S ICHERUNG -> SICHERUNG
        M ASCHINENDATEN -> MASCHINENDATEN
    """
    if not text:
        return ""

    upper_chars = "A-ZÄÖÜ"
    lower_chars = "a-zäöüß"

    previous = None

    while previous != text:
        previous = text
        text = re.sub(
            rf"\b([{upper_chars}])\s+([{upper_chars}][{upper_chars}{lower_chars}]{{2,}})\b",
            r"\1\2",
            text,
        )

    return text


def paper_clean_text(text: str) -> str:
    if not text:
        return ""

    text = normalize_unicode_basic(text)
    text = fix_broken_line_hyphenation(text)
    text = fix_split_uppercase_words(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def paper_normalize_for_repetition(text: str) -> str:
    return normalize_for_repetition(text, paper_clean_text)


# ============================================================
# GROBID METADATA
# ============================================================

def grobid_ns(tag: str) -> str:
    return f"{{http://www.tei-c.org/ns/1.0}}{tag}"



def extract_grobid_metadata(pdf_path: Path) -> dict:
    metadata = {
        "title": "",
        "abstract": "",
        "author_keywords": [],
        "has_references": False,
        "reference_count": 0,
        "grobid_error": "",
    }

    if not USE_GROBID_METADATA:
        return metadata

    try:
        with pdf_path.open("rb") as file_handle:
            files = {
                "input": (pdf_path.name, file_handle, "application/pdf"),
            }
            response = requests.post(GROBID_URL, files=files, timeout=120)

        response.raise_for_status()
        root = ET.fromstring(response.text)

        title_el = root.find(f".//{grobid_ns('titleStmt')}/{grobid_ns('title')}")
        if title_el is not None:
            metadata["title"] = paper_clean_text(" ".join(title_el.itertext()))

        abstract_el = root.find(f".//{grobid_ns('profileDesc')}/{grobid_ns('abstract')}")
        if abstract_el is not None:
            metadata["abstract"] = paper_clean_text(" ".join(abstract_el.itertext()))

        keywords = []
        for kw_el in root.findall(f".//{grobid_ns('textClass')}//{grobid_ns('term')}"):
            keyword = paper_clean_text(" ".join(kw_el.itertext()))
            if keyword:
                keywords.append(keyword)

        metadata["author_keywords"] = keywords

        reference_entries = root.findall(
            f".//{grobid_ns('listBibl')}//{grobid_ns('biblStruct')}"
        )
        metadata["reference_count"] = len(reference_entries)
        metadata["has_references"] = len(reference_entries) > 0

    except Exception as exc:
        metadata["grobid_error"] = str(exc)

    return metadata


# ============================================================
# FRONT-MATTER TRIMMING
# ============================================================

BODY_START_BLOCK_RE = re.compile(
    r"""
    (?:
        # Numbered or Roman introduction can appear anywhere inside a messy block:
        (?<![A-Za-z0-9])
        (?:
            1
            |
            I
        )
        \s*(?:[.\-–—:]|\s)\s*
        (introduction|einleitung|background|motivation|related\s+work)
        \b
        |
        # Plain heading is only trusted near the beginning of a block:
        ^\s*
        (?:\#\#\s*)?
        (introduction|einleitung|background|motivation|related\s+work)
        \b
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def find_body_start_in_block(text: str) -> int | None:
    """
    Find body start even when embedded inside a messy block.

    Examples:
        "... Abstract text 1. Introduction This paper presents ..."
        "... Keywords ... I. INTRODUCTION Recent work ..."
        "Introduction This paper presents ..."
    """
    if not text:
        return None

    match = BODY_START_BLOCK_RE.search(text)

    if not match:
        return None

    return match.start()


def default_front_matter_trim_debug() -> dict:
    return {
        "body_start_found": False,
        "body_start_page": None,
        "body_start_block_index": None,
        "body_start_preview": "",
    }


def trim_pages_to_first_body_heading(pages: list[dict]) -> tuple[list[dict], dict]:
    """
    Remove title/authors/abstract/front matter from PyMuPDF body extraction.

    This trims at block level, before build_clean_paper_text().
    That is more reliable than trimming the final merged string.
    """
    debug = default_front_matter_trim_debug()

    trimmed_pages = []
    found = False

    for page in pages:
        if found:
            trimmed_pages.append(page)
            continue

        blocks = page.get("blocks", [])

        for block_index, block in enumerate(blocks):
            text = paper_clean_text(block.get("text", ""))
            start_index = find_body_start_in_block(text)

            if start_index is None:
                continue

            found = True

            kept_text = text[start_index:].strip()
            new_blocks = []

            if kept_text:
                new_blocks.append({
                    **block,
                    "text": kept_text,
                })

            new_blocks.extend(blocks[block_index + 1:])

            trimmed_pages.append({
                **page,
                "blocks": new_blocks,
            })

            debug["body_start_found"] = True
            debug["body_start_page"] = page.get("page_number")
            debug["body_start_block_index"] = block_index
            debug["body_start_preview"] = kept_text[:250]

            break

    if not found:
        return pages, debug

    return trimmed_pages, debug


# ============================================================
# TOC / DIRECTORY ENTRY DETECTION
# ============================================================

ROMAN_PAGE_RE = r"(?:[ivxlcdmIVXLCDM]+)"

DOT_LEADER_RE = re.compile(
    r"""
    (?:
        \.{3,}
        |
        (?:\.\s*){4,}
    )
    """,
    re.VERBOSE,
)


def is_likely_directory_entry(text: str) -> bool:
    text = paper_clean_text(text)

    if not text:
        return False

    if not any(ch.isalpha() for ch in text):
        return False

    has_dot_leader = bool(DOT_LEADER_RE.search(text))

    starts_with_numbered_entry = bool(
        re.match(r"^\s*\d+(?:\.\d+)*\.?\s+\S+", text)
    )

    starts_with_table_or_figure = bool(
        re.match(
            r"^\s*(?:"
            r"tab(?:elle)?\.?|table|"
            r"abb(?:ildung)?\.?|figure|fig\."
            r")\s*\d+(?:\.\d+)*\b",
            text,
            re.IGNORECASE,
        )
    )

    ends_with_arabic_page_number = bool(re.search(r"\s+\d+\s*$", text))
    ends_with_roman_page_number = bool(re.search(rf"\s+{ROMAN_PAGE_RE}\s*$", text))
    ends_with_page_ref = ends_with_arabic_page_number or ends_with_roman_page_number

    starts_with_text = bool(
        re.match(
            r"^\s*[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9 ,:/()\-]+",
            text,
        )
    )

    return (
        has_dot_leader
        and ends_with_page_ref
        and (
            starts_with_numbered_entry
            or starts_with_table_or_figure
            or starts_with_text
        )
    ) or (
        starts_with_table_or_figure
        and ends_with_page_ref
    )


def clean_directory_entry_for_output(text: str) -> str:
    text = paper_clean_text(text)

    if not is_likely_directory_entry(text):
        return text

    text = DOT_LEADER_RE.sub(" ", text)
    text = re.sub(rf"\s+(?:\d+|{ROMAN_PAGE_RE})\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# ============================================================
# JUNK FILTERING
# ============================================================

def is_punctuation_only_junk(text: str) -> bool:
    text = paper_clean_text(text)

    if not text:
        return True

    letters = sum(ch.isalpha() for ch in text)
    words = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", text)

    if letters == 0:
        return True

    if len(words) == 0:
        return True

    if len(words) == 1 and letters / max(len(text), 1) < 0.10:
        return True

    return False


def paper_is_probably_junk(text: str) -> bool:
    text = paper_clean_text(text)

    if len(text) < MIN_TEXT_CHARS:
        return True

    if re.fullmatch(r"\d+", text):
        return True

    if is_punctuation_only_junk(text):
        return True

    return False


# ============================================================
# LINE / PAGE MERGING
# ============================================================

def should_merge_hyphenated_linebreak(previous: str, current: str) -> bool:
    previous = paper_clean_text(previous)
    current = paper_clean_text(current)

    if not previous or not current:
        return False

    if not previous.endswith("-"):
        return False

    first_word_match = re.match(r"^([^\W\d_]+)\b", current, flags=re.UNICODE)
    if not first_word_match:
        return False

    first_word = first_word_match.group(1)

    if first_word.lower() in COORDINATION_HYPHEN_WORDS:
        return False

    if first_word[:1].isupper():
        return False

    return True


def append_text_line(lines: list[str], text: str) -> None:
    text = paper_clean_text(text)

    if not text:
        return

    if lines and should_merge_hyphenated_linebreak(lines[-1], text):
        lines[-1] = lines[-1][:-1] + text
    else:
        lines.append(text)


def is_page_top_noise_line(text: str) -> bool:
    text = paper_clean_text(text)

    if not text:
        return True

    if re.fullmatch(r"\d+", text):
        return True

    if re.fullmatch(
        r"\d+(?:\.\d+)*\.?\s+"
        r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9 ,:/()\-]{1,80}"
        r"\s+\d+",
        text,
    ):
        return True

    return False


SENTENCE_END_RE = re.compile(r"""[.!?。！？]["')\]]*$""")


def looks_like_continuation(previous: str, current: str) -> bool:
    previous = paper_clean_text(previous)
    current = paper_clean_text(current)

    if not previous or not current:
        return False

    if previous.endswith("-"):
        return False

    if current.startswith("## "):
        return False

    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-ZÄÖÜ]", current):
        return False

    if SENTENCE_END_RE.search(previous):
        return False

    if current[:1].islower():
        return True

    if previous[-1:] in {",", ";", ":", "(", "[", "{", "/"}:
        return True

    return True


def split_first_real_line(page_text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in page_text.splitlines()]

    first_index = None

    for index, line in enumerate(lines):
        if line.strip():
            first_index = index
            break

    if first_index is None:
        return "", ""

    first_line = lines[first_index].strip()
    remaining_lines = lines[first_index + 1:]
    remaining = "\n".join(remaining_lines).strip()

    return first_line, remaining


def append_page_text(parts: list[str], page_text: str) -> None:
    page_text = page_text.strip()

    if not page_text:
        return

    if not parts:
        parts.append(page_text)
        return

    first_line, remaining = split_first_real_line(page_text)

    if not first_line:
        return

    if should_merge_hyphenated_linebreak(parts[-1], first_line):
        parts[-1] = parts[-1].rstrip()[:-1] + paper_clean_text(first_line)

        if remaining:
            parts.append(remaining)

        return

    if parts[-1].rstrip().endswith("-"):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]

        while lines and is_page_top_noise_line(lines[0]):
            lines.pop(0)

        if lines and should_merge_hyphenated_linebreak(parts[-1], lines[0]):
            parts[-1] = parts[-1].rstrip()[:-1] + paper_clean_text(lines[0])

            remaining_after_merge = "\n".join(lines[1:]).strip()
            if remaining_after_merge:
                parts.append(remaining_after_merge)

            return

    if looks_like_continuation(parts[-1], first_line):
        parts[-1] = parts[-1].rstrip() + " " + paper_clean_text(first_line)

        if remaining:
            parts.append(remaining)

        return

    parts.append(page_text)


# ============================================================
# RECONSTRUCTED LINE MERGING
# ============================================================

def should_start_new_text_unit(
    previous: dict,
    current: dict,
) -> bool:
    prev_text = paper_clean_text(previous["text"])
    curr_text = paper_clean_text(current["text"])

    if not prev_text or not curr_text:
        return True

    if (
        is_likely_directory_entry(prev_text)
        or is_likely_directory_entry(curr_text)
    ):
        return True

    # ---------------------------------------------------------
    # Explicit numbered reference/list entry:
    #
    # [1] Smith ...
    # [23] Miller ...
    #
    # These are strong structural boundaries and must not be
    # merged into the preceding visual line.
    # ---------------------------------------------------------
    if re.match(
        r"^\s*\[\d{1,4}\]\s+",
        curr_text,
    ):
        return True

    # Existing decimal/section numbering:
    #
    # 1. Introduction
    # 2. Methods
    # 12. Smith ...
    # ---------------------------------------------------------
    if re.match(
        r"^\d+(?:\.\d+)*\.?\s+[A-ZÄÖÜ]",
        curr_text,
    ):
        return True

    prev_height = max(
        previous["y1"] - previous["y0"],
        1,
    )

    vertical_gap = (
        current["y0"] - previous["y1"]
    )

    if vertical_gap > prev_height * 0.85:
        return True

    same_visual_band = (
        abs(
            current["y0"]
            - previous["y0"]
        )
        <= previous["font_size"] * 0.35
    )

    if not same_visual_band:
        indent_delta = abs(
            current["x0"]
            - previous["x0"]
        )

        if (
            indent_delta
            > previous["font_size"] * 4
        ):
            return True

    return False


def merge_reconstructed_lines_into_text_units(lines: list[dict]) -> list[str]:
    if not lines:
        return []

    units = []
    current = lines[0].copy()

    for line in lines[1:]:
        prev_text = paper_clean_text(current["text"])
        curr_text = paper_clean_text(line["text"])

        if not curr_text:
            continue

        if should_merge_hyphenated_linebreak(prev_text, curr_text):
            current["text"] = prev_text[:-1] + curr_text
            current["x1"] = line["x1"]
            current["y1"] = line["y1"]
            continue

        if should_start_new_text_unit(current, line):
            units.append(paper_clean_text(current["text"]))
            current = line.copy()
        else:
            current["text"] = paper_clean_text(prev_text + " " + curr_text)
            current["x1"] = line["x1"]
            current["y1"] = line["y1"]

    if current.get("text"):
        units.append(paper_clean_text(current["text"]))

    return units


# ============================================================
# REPEATED HEADER / FOOTER REMOVAL
# ============================================================

def find_repeated_paper_blocks(
    pages: list[dict],
    min_fraction: float = REPEATED_TEXT_MIN_FRACTION,
) -> set[str]:
    if not pages:
        return set()

    occurrences: dict[str, list[tuple[int, float]]] = {}

    for page in pages:
        page_height = page.get("page_height", 0) or 1
        seen_on_page = set()

        for block in page["blocks"]:
            norm = paper_normalize_for_repetition(block["text"])

            if not norm or norm in seen_on_page:
                continue

            seen_on_page.add(norm)

            y_center = ((block.get("y0", 0) + block.get("y1", 0)) / 2) / page_height
            occurrences.setdefault(norm, []).append((page["page_number"], y_center))

    threshold = max(REPEATED_TEXT_MIN_COUNT, int(len(pages) * min_fraction))
    repeated = set()

    for norm, hits in occurrences.items():
        page_count = len({page_number for page_number, _ in hits})

        if page_count < threshold:
            continue

        top_hits = sum(y <= REPEATED_TEXT_TOP_ZONE for _, y in hits)
        bottom_hits = sum(y >= REPEATED_TEXT_BOTTOM_ZONE for _, y in hits)

        if top_hits >= threshold or bottom_hits >= threshold:
            repeated.add(norm)

    return repeated


def remove_repeated_paper_blocks(pages: list[dict], repeated: set[str]) -> list[dict]:
    cleaned_pages = []

    for page in pages:
        cleaned_blocks = []

        for block in page["blocks"]:
            norm = paper_normalize_for_repetition(block["text"])

            if norm in repeated:
                continue

            cleaned_blocks.append(block)

        cleaned_pages.append({
            **page,
            "blocks": cleaned_blocks,
        })

    return cleaned_pages


# ============================================================
# PAPER STRUCTURE DETECTION
# ============================================================

SECTION_HEADING_RE = re.compile(
    r"""^\s*
    (?:
        \d+(?:\.\d+)*\.?\s+
    )?
    [A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-:,/&() ]{2,100}
    \s*$
    """,
    re.VERBOSE,
)

COMMON_SECTION_HEADINGS = {
    "abstract", "keywords", "introduction", "background", "related work",
    "literature review", "method", "methods", "methodology", "materials and methods",
    "results", "findings", "discussion", "limitations", "conclusion", "conclusions",
    "references", "bibliography", "acknowledgements", "acknowledgments", "appendix",

    "zusammenfassung", "einleitung", "hintergrund", "methode", "methoden",
    "methodik", "ergebnisse", "diskussion", "fazit", "schlussfolgerung",
    "literatur", "referenzen", "literaturverzeichnis", "quellen",
    "quellenverzeichnis", "danksagung", "anhang",
}


def strip_numbering_for_heading(text: str) -> str:
    text = paper_clean_text(text).lower()

    text = re.sub(
        r"^(?:"
        r"\d+(?:\.\d+)*\.?"
        r"|[ivxlcdm]+\.?"
        r")\s+",
        "",
        text,
    )

    return text.strip(" .:;-\t")


def estimate_paper_body_font_size(blocks: list[dict]) -> float:
    sizes = [
        block.get("avg_font_size", 0)
        for block in blocks
        if block.get("avg_font_size", 0) > 0
    ]

    if not sizes:
        return 0

    sizes = sorted(sizes)
    return sizes[len(sizes) // 2]


def looks_bold(block: dict) -> bool:
    font_names = " ".join(block.get("font_names", [])).lower()

    return any(
        token in font_names
        for token in ("bold", "semibold", "demibold", "black")
    )


def is_probably_section_heading(block: dict, body_font_size: float) -> bool:
    text = paper_clean_text(block.get("text", ""))

    if not text:
        return False

    words = text.split()

    if len(words) > 12:
        return False

    simplified = strip_numbering_for_heading(text)

    if text.endswith(".") and simplified not in COMMON_SECTION_HEADINGS:
        return False

    is_common_heading = simplified in COMMON_SECTION_HEADINGS
    matches_heading_shape = bool(SECTION_HEADING_RE.match(text))

    font_size = block.get("max_font_size", 0)
    is_larger_than_body = bool(body_font_size and font_size >= body_font_size * 1.05)
    is_boldish = looks_bold(block)

    return is_common_heading or (
        matches_heading_shape
        and (is_larger_than_body or is_boldish)
    )

# ============================================================
# REFERENCES DETECTION / TRIMMING
# ============================================================

REFERENCE_START_RE = re.compile(
    r"""
    ^\s*
    (?:\#\#\s*)?
    (?:
        (?:\d+(?:\.\d+)*|[ivxlcdm]+)
        \s*[\.\-–—:]?\s+
    )?
    (
        references
        | bibliography
        | works\s+cited
        | literature\s+cited
        | literatur
        | referenzen
        | literaturverzeichnis
        | quellen
        | quellenverzeichnis
    )
    \b
    (?!.*\.{3,}.*\d+\s*$)
    """,
    flags=re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)


def is_references_heading(text: str) -> bool:
    text = paper_clean_text(text)
    simplified = strip_numbering_for_heading(text)

    return simplified in {
        "references",
        "bibliography",
        "literatur",
        "referenzen",
        "literaturverzeichnis",
        "quellen",
        "quellenverzeichnis",
    } or bool(REFERENCE_START_RE.match(text))

def trim_text_before_references(text: str) -> tuple[str, dict]:
    """
    Backwards-compatible wrapper.

    Prefer split_text_and_references() for new code.
    """
    body_text, _, debug = split_text_and_references(text)

    old_debug = {
        "references_trimmed": debug["references_found"],
        "references_start_preview": debug["references_start_preview"],
        "references_match_count": debug["references_match_count"],
        "references_trim_reason": debug["references_split_reason"],
        "references_candidate_positions": debug[
            "references_candidate_positions"
        ],
    }

    return body_text, old_debug
def split_text_and_references(
        text: str,
    ) -> tuple[str, str, dict]:
        """
        Split cleaned paper text into body and bibliography.
    
        Reference-heading candidates are scored using the text that follows
        them rather than blindly choosing the final "References" occurrence.
        """
    
        debug = {
            "references_found": False,
            "references_start_preview": "",
            "references_match_count": 0,
            "references_candidate_positions": [],
            "references_candidate_scores": [],
            "references_split_reason": "",
        }
    
        if not text:
            return "", "", debug
    
        matches = list(
            REFERENCE_START_RE.finditer(text)
        )
    
        debug["references_match_count"] = len(matches)
    
        debug["references_candidate_positions"] = [
            round(
                match.start() / max(len(text), 1),
                3,
            )
            for match in matches
        ]
    
        if not matches:
            debug["references_split_reason"] = (
                "no_reference_heading_found"
            )
            return text.strip(), "", debug
    
        # ---------------------------------------------------------
        # Ignore obvious TOC/front-matter occurrences.
        # ---------------------------------------------------------
    
        min_start_ratio = 0.60
    
        plausible_matches = [
            match
            for match in matches
            if (
                match.start() / max(len(text), 1)
                >= min_start_ratio
            )
        ]
    
        if not plausible_matches:
            debug["references_split_reason"] = (
                "no_late_reference_heading_found"
            )
            return text.strip(), "", debug
    
        # ---------------------------------------------------------
        # Score each candidate by how bibliography-like the text
        # immediately following it appears.
        #
        # This is much safer than plausible_matches[-1].
        # ---------------------------------------------------------
    
        scored_candidates = []
    
        for match in plausible_matches:
            after = text[match.end():]
    
            # Inspect enough text to see several references without
            # allowing the rest of a huge thesis to dominate scoring.
            sample = after[:12000]
    
            score = 0
    
            # ---- numbered references: [1], [2], ...
            bracket_numbers = [
                int(value)
                for value in re.findall(
                    r"\[(\d{1,4})\]",
                    sample,
                )
            ]
    
            if bracket_numbers:
                score += min(
                    len(bracket_numbers),
                    30,
                ) * 2
    
                # A bibliography beginning at [1] is extremely strong
                # evidence that this is the real bibliography heading.
                first_number = bracket_numbers[0]
    
                if first_number == 1:
                    score += 100
    
                elif first_number <= 3:
                    score += 60
    
                elif first_number <= 10:
                    score += 20
    
                # Reward sequential numbering.
                sequential_pairs = 0
    
                for previous, current in zip(
                    bracket_numbers,
                    bracket_numbers[1:],
                ):
                    if current == previous + 1:
                        sequential_pairs += 1
    
                score += min(
                    sequential_pairs,
                    20,
                ) * 3
    
            # ---- "1. ..." style numbered references
            decimal_numbers = [
                int(value)
                for value in re.findall(
                    r"(?m)^\s*(\d{1,4})[.)]\s+",
                    sample,
                )
            ]
    
            if decimal_numbers:
                score += min(
                    len(decimal_numbers),
                    30,
                ) * 2
    
                if decimal_numbers[0] == 1:
                    score += 80
    
            # ---- common bibliography metadata
            years = re.findall(
                r"\b(?:18|19|20)\d{2}[a-z]?\b",
                sample,
                flags=re.IGNORECASE,
            )
    
            score += min(
                len(years),
                30,
            )
    
            dois = re.findall(
                r"\b10\.\d{4,9}/\S+",
                sample,
                flags=re.IGNORECASE,
            )
    
            score += min(
                len(dois),
                10,
            ) * 2
    
            # A candidate extremely close to EOF is suspicious if
            # there is almost no bibliography after it.
            remaining_ratio = (
                len(after) / max(len(text), 1)
            )
    
            if remaining_ratio < 0.02:
                score -= 50
    
            scored_candidates.append(
                {
                    "match": match,
                    "score": score,
                    "first_bracket_number": (
                        bracket_numbers[0]
                        if bracket_numbers
                        else None
                    ),
                    "bracket_count": len(
                        bracket_numbers
                    ),
                    "decimal_count": len(
                        decimal_numbers
                    ),
                }
            )
    
        debug["references_candidate_scores"] = [
            {
                "position": round(
                    item["match"].start()
                    / max(len(text), 1),
                    3,
                ),
                "score": item["score"],
                "first_bracket_number": (
                    item["first_bracket_number"]
                ),
                "bracket_count": (
                    item["bracket_count"]
                ),
                "decimal_count": (
                    item["decimal_count"]
                ),
            }
            for item in scored_candidates
        ]
    
        # Highest bibliography evidence wins.
        #
        # On equal scores choose the EARLIER candidate rather than
        # the later one. Once a real References section begins,
        # another occurrence inside it should not replace it.
        best = max(
            scored_candidates,
            key=lambda item: (
                item["score"],
                -item["match"].start(),
            ),
        )
    
        match = best["match"]
    
        body_text = text[
            :match.start()
        ].strip()
    
        bibliography_text = text[
            match.end():
        ].strip()
    
        debug["references_found"] = True
        debug["references_split_reason"] = (
            "scored_reference_heading"
        )
    
        debug["references_start_preview"] = text[
            match.start():
            match.start() + 250
        ]
    
        return (
            body_text,
            bibliography_text,
            debug,
        )
# ============================================================
# FINAL PAPER TEXT BUILDING
# ============================================================

def build_clean_paper_text(pages: list[dict]) -> dict:
    output_pages = []
    section_headings = []
    inside_references = False

    total_pages = len(pages)
    min_reference_page_ratio = 0.60

    for page in pages:
        blocks = page["blocks"]
        body_font_size = estimate_paper_body_font_size(blocks)

        page_number = page.get("page_number", 1)
        page_ratio = page_number / max(total_pages, 1)
        allow_reference_cut = page_ratio >= min_reference_page_ratio

        lines = []
        seen = set()

        for block in blocks:
            text = paper_clean_text(block["text"])

            # Very important:
            # TOC/directory entries must be handled before reference detection.
            if is_likely_directory_entry(text):
                text = clean_directory_entry_for_output(text)

                if text:
                    append_text_line(lines, text)

                continue

            if not text:
                continue

            norm = paper_normalize_for_repetition(text)

            if norm in seen:
                continue

            seen.add(norm)

            if (
                DROP_REFERENCES_SECTION
                and allow_reference_cut
                and is_references_heading(text)
            ):
                section_headings.append({
                    "page_number": page["page_number"],
                    "heading": text,
                })
                inside_references = True
                break

            if is_probably_section_heading(block, body_font_size):
                section_headings.append({
                    "page_number": page["page_number"],
                    "heading": text,
                })

                append_text_line(lines, f"## {text}")
                continue

            if inside_references and DROP_REFERENCES_SECTION:
                continue

            append_text_line(lines, text)

        output_pages.append({
            "page_number": page["page_number"],
            "text": "\n".join(lines).strip(),
            "blocks": blocks,
        })

    if INCLUDE_PAGE_HEADERS:
        full_text_parts = []

        for page in output_pages:
            if not page["text"]:
                continue

            full_text_parts.append(
                f"=== Page {page['page_number']} ===\n{page['text']}"
            )

        full_text = "\n\n".join(full_text_parts).strip()

    else:
        full_text_parts = []

        for page in output_pages:
            append_page_text(full_text_parts, page["text"])

        full_text = "\n\n".join(full_text_parts).strip()

    return {
        "text": full_text,
        "pages": output_pages,
        "section_headings": section_headings,
    }