"""Shared reference-extraction policy helpers."""

import os
from typing import Optional


VALID_EXTRACTION_MODES = frozenset({'cascade', 'llm-only'})
DEFAULT_EXTRACTION_MODE = 'cascade'


def normalize_extraction_mode(mode: Optional[str] = None) -> str:
    """Return a supported extraction mode, including the environment default."""
    normalized = str(
        mode or os.environ.get('REFCHECKER_EXTRACTION_MODE') or DEFAULT_EXTRACTION_MODE
    ).strip().lower()
    if normalized not in VALID_EXTRACTION_MODES:
        return DEFAULT_EXTRACTION_MODE
    return normalized
