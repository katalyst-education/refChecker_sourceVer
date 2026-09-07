"""Share/export robustness for database-shaped verification results."""

import json

import pytest

from backend import export


def _database_check():
    return {
        "paper_title": "Stored report",
        "timestamp": "2026-06-08T10:00:00Z",
        "results": json.dumps([
            {
                "index": 1,
                "title": "Stored reference",
                "status": "verified",
                "errors": [],
                "warnings": [],
            }
        ]),
    }


@pytest.mark.parametrize("fmt", ("html", "md", "pdf", "docx"))
def test_database_json_results_render_in_every_format(fmt):
    content, media_type, extension = export.render_export(_database_check(), fmt)
    assert content
    assert media_type
    assert extension


@pytest.mark.parametrize("fmt", ("html", "md", "pdf", "docx"))
def test_empty_database_results_render_in_every_format(fmt):
    content, _, _ = export.render_export({"paper_title": None, "results": ""}, fmt)
    assert content
