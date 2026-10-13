"""Shared patterns for recognizing bibliography entry boundaries."""

import re


AUTHOR_YEAR_ENTRY_START_RE = re.compile(
    r"(?m)(?:^[ \t]*(?:\d{1,2}[ \t]+)?|"
    r"(?<!\b[A-Z])(?<!\bet al)(?<!\bJr)(?<!\bSr)[.!?][\"']?\s+)"
    r"([A-Z](?:[^\n.!?]|\n(?!\s*\n)|(?<=\b[A-Z])\.|(?<=\bet al)\.|(?<=\bJr)\.|(?<=\bSr)\.){1,240}?)"
    r"[\.,]?\s*"
    r"\(?((?:19|20)\d{2}[a-z]?)\)?"
    r"(?:[\.:\s]|$)"
)
