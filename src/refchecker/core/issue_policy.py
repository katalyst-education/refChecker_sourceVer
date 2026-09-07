"""Shared issue counting and author-comparison helpers.

These helpers are used by the bulk, CLI, and WebUI paths so their result
counts and metadata comparisons remain consistent.
"""

from __future__ import annotations

import re
from typing import List, Optional

from refchecker.utils.text_utils import enhanced_name_match


_TEAM_NAMES = frozenset({
    "deepseek-ai", "qwen", "openai", "microsoft", "google", "meta",
    "team glm", "gemini team", "core team", "v team",
    "01.ai", "ai", "lcm team", "the lcm team",
})


def count_raw_errors(raw_errors: list) -> tuple:
    """Count errors, warnings, and informational items in verifier output."""
    error_count = 0
    warning_count = 0
    info_count = 0
    for issue in raw_errors or []:
        if "warning_type" in issue:
            warning_count += 1
        elif "info_type" in issue:
            info_count += 1
        elif "error_type" in issue:
            issue_type = issue["error_type"]
            if issue_type == "unverified":
                continue
            if (
                issue_type == "url"
                and "url references paper" in (issue.get("error_details") or "").lower()
            ):
                continue
            error_count += 1
    return error_count, warning_count, info_count


def _repair_compressed_lastname_initial_parts(parts: List[str]) -> Optional[List[str]]:
    if len(parts) < 3:
        return None
    initial_unit = r"[A-Z]\.?(?:-[A-Z]\.?)?"
    leading_initials_re = re.compile(
        rf"^(?P<initials>{initial_unit}(?:\s+{initial_unit})*)\s+(?P<next_surname>.+)$"
    )
    terminal_initials_re = re.compile(rf"^{initial_unit}(?:\s+{initial_unit})*$")
    authors: List[str] = []
    current_surname = parts[0]
    saw_compressed_boundary = False
    for index, part in enumerate(parts[1:], start=1):
        match = leading_initials_re.match(part)
        if match and index < len(parts) - 1:
            authors.append(f"{current_surname}, {match.group('initials').strip()}")
            current_surname = match.group("next_surname").strip()
            if not current_surname:
                return None
            saw_compressed_boundary = True
            continue
        if terminal_initials_re.match(part):
            authors.append(f"{current_surname}, {part}")
            current_surname = ""
            continue
        return None
    if current_surname:
        return None
    return authors if saw_compressed_boundary and len(authors) >= 2 else None


def _split_author_string(author_str: str) -> List[str]:
    raw_parts = [part.strip() for part in author_str.split(",") if part.strip()]
    compressed = _repair_compressed_lastname_initial_parts(raw_parts)
    if compressed:
        return compressed

    def is_initials(part: str) -> bool:
        stripped = part.strip().rstrip(".")
        return bool(stripped) and all(len(word.strip(".")) <= 1 for word in stripped.split())

    merged: List[str] = []
    index = 0
    while index < len(raw_parts):
        part = raw_parts[index]
        if index + 1 < len(raw_parts) and is_initials(raw_parts[index + 1]):
            merged.append(f"{part}, {raw_parts[index + 1]}")
            index += 2
        else:
            merged.append(part)
            index += 1
    return [
        name.strip()
        for name in merged
        if name.strip().lower().rstrip(".")
        not in {"et al", "et al.", "others", "and others", ""}
    ]


def _strip_team_names(authors: List[str]) -> List[str]:
    result = []
    for index, name in enumerate(authors):
        name_lower = name.strip().lower()
        if name_lower in _TEAM_NAMES:
            continue
        if index == 0:
            for team in _TEAM_NAMES:
                if name_lower.startswith(team + " "):
                    name = name[len(team):].strip()
                    break
        result.append(name)
    return result


def compute_author_overlap(
    cited_authors: str,
    correct_authors: str,
    cited_list: Optional[List[str]] = None,
) -> Optional[float]:
    """Return the fraction of cited authors found in the authoritative list."""
    if not cited_authors or not correct_authors:
        return None
    if cited_list is not None:
        cited = [
            name for name in cited_list
            if name.strip().lower().rstrip(".")
            not in {"et al", "et al.", "others", "and others", ""}
        ]
        cited = _repair_compressed_lastname_initial_parts(cited) or cited
    else:
        cited = _split_author_string(cited_authors)
    correct = _split_author_string(correct_authors)
    cited = _strip_team_names(cited)
    correct = _strip_team_names(correct)
    if len(cited) < 2 or len(correct) < 2:
        return None
    cited_subset = cited[:10]
    matches = sum(
        1
        for cited_name in cited_subset
        if any(enhanced_name_match(cited_name, correct_name) for correct_name in correct)
    )
    if len(cited_subset) <= 2 and matches == len(cited_subset):
        return 1.0
    if len(cited_subset) <= 2 and matches >= 1:
        return None
    return matches / len(cited_subset)
