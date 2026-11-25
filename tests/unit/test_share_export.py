"""Share/export robustness for database-shaped verification results."""

import json
import io
import zipfile

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


def _mixed_check():
    return {"paper_title": "Mixed report", "results": [
        {"index": 1, "title": "Clean citation", "status": "verified"},
        {"index": 2, "title": "Warning citation", "status": "warning",
         "warnings": [{"message": "Year differs"}]},
        {"index": 3, "title": "Error citation", "status": "error",
         "errors": [{"error_type": "title", "message": "Wrong title"}],
         "warnings": [{"message": "Also warns"}]},
        {"index": 4, "title": "Missing citation", "status": "unverified",
         "errors": [{"error_type": "unverified", "message": "Missing"}]},
        {"index": 5, "title": "Suggested citation", "status": "suggestion",
         "suggestions": [{"message": "Optional change"}]},
    ]}


@pytest.mark.parametrize("statuses,indices", [
    (None, [1, 2, 3, 4, 5]), ("verified", [1, 5]), ("warning", [2]),
    ("error", [3]), ("unverified", [4]), ("warning,error", [2, 3]), ("", []),
])
def test_status_selection_uses_effective_precedence(statuses, indices):
    check = _mixed_check()
    filtered = export.filter_check_statuses(check, statuses)
    assert [ref["index"] for ref in filtered["results"]] == indices
    assert len(check["results"]) == 5


@pytest.mark.parametrize("fmt", ["html", "md", "pdf", "docx"])
@pytest.mark.parametrize("batch", [False, True])
def test_status_selection_reaches_every_report_format(fmt, batch):
    check = _mixed_check()
    if batch:
        content, _, _ = export.render_batch_export([check], fmt, statuses="warning,error")
    else:
        content, _, _ = export.render_export(check, fmt, statuses="warning,error")
    if fmt == "pdf":
        import fitz
        with fitz.open(stream=content, filetype="pdf") as document:
            text = " ".join(page.get_text() for page in document)
    elif fmt == "docx":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            text = archive.read("word/document.xml").decode()
    else:
        text = content
    assert "Warning citation" in text
    assert "Error citation" in text
    for excluded in ["Clean citation", "Missing citation", "Suggested citation"]:
        assert excluded not in text


def test_filtered_export_recomputes_summary():
    content, _, _ = export.render_export(
        _mixed_check(), "md", statuses="error",
        summary={"totalRefs": 99, "references": {"verified": 99}},
    )
    assert "99" not in content
    model = export._model(export.filter_check_statuses(_mixed_check(), "error"),
                          corrections=False, sections=None)
    assert model["stats"]["total"] == 1
    assert model["stats"]["error"] == 1


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="Unknown result status"):
        export.filter_check_statuses(_mixed_check(), "typo")


@pytest.mark.parametrize("statuses,lists,indices", [
    ("", "further_checks", [2]),
    ("verified", "further_checks", [1, 2, 5]),
    ("warning", "", []),
    (None, "", [1, 4, 5]),
    ("", "further_checks,custom-id", [2, 3]),
    ("", "", []),
    (None, None, [1, 2, 3, 4, 5]),
])
def test_user_lists_and_statuses_form_a_union(statuses, lists, indices):
    check = _mixed_check()
    check["results"][1]["review_list"] = "further_checks"
    check["results"][2]["review_list"] = "custom-id"
    check["results"] = json.dumps(check["results"])
    check["references"] = _mixed_check()["results"]
    filtered = export.filter_check_statuses(check, statuses, lists)
    refs = export._as_list(filtered["results"])
    assert [ref["index"] for ref in refs] == indices
    if statuses is not None or lists is not None:
        assert filtered["references"] == refs


@pytest.mark.parametrize("fmt", ["html", "md", "pdf", "docx"])
@pytest.mark.parametrize("batch", [False, True])
def test_user_list_only_export_reaches_every_format(fmt, batch):
    check = _mixed_check()
    check["results"][2]["review_list"] = "custom-id"
    render = export.render_batch_export if batch else export.render_export
    content, _, _ = render([check] if batch else check, fmt,
                           statuses="", review_lists="custom-id")
    if fmt == "pdf":
        import fitz
        with fitz.open(stream=content, filetype="pdf") as document:
            text = " ".join(page.get_text() for page in document)
    elif fmt == "docx":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            text = archive.read("word/document.xml").decode()
    else:
        text = content
    assert "Error citation" in text
    assert "Clean citation" not in text
    assert "Warning citation" not in text
    assert "Missing citation" not in text
