import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.refchecker_wrapper import ProgressRefChecker
from refchecker.services.pdf_pipeline import ExtractedDocument


_PDF_BODY = (
    "The paper introduces a method and cites prior work [1]. "
) * 8
_PDF_BIBLIOGRAPHY = (
    "[1] John Smith and Alice Jones. A robust method for scientific analysis. "
    "Journal of Testing, 2021.\n"
    "[2] Jane Doe and Bob Roe. An efficient approach to academic research. "
    "Conference Proceedings, 2022.\n"
    "[3] Alice Brown and Carol White. Improved models for reliable systems. "
    "Transactions on Testing, 2023."
)


def _structured_pdf_document():
    return ExtractedDocument(
        file="paper.pdf",
        doc_type="one_column_paper",
        extractor="test_pipeline",
        body_text=_PDF_BODY,
        bibliography=_PDF_BIBLIOGRAPHY,
        full_text=f"{_PDF_BODY}\n\nReferences\n{_PDF_BIBLIOGRAPHY}",
        metadata={"extraction_diagnostics": {"bibliography_status": "extracted"}},
    )


def test_webui_direct_uvicorn_import_prefers_checkout_shared_core():
    project_root = Path(__file__).resolve().parents[2]
    expected_text_utils = (
        project_root / "src" / "refchecker" / "utils" / "text_utils.py"
    ).resolve()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import backend.main; "
                "from refchecker.utils import text_utils; "
                "print('TEXT_UTILS_PATH=' + text_utils.__file__)"
            ),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    imported_path = next(
        line.removeprefix("TEXT_UTILS_PATH=")
        for line in completed.stdout.splitlines()
        if line.startswith("TEXT_UTILS_PATH=")
    )
    assert Path(imported_path).resolve() == expected_text_utils


def test_webui_uses_shared_source_first_reference_dispatch():
    wrapper = ProgressRefChecker.__new__(ProgressRefChecker)
    wrapper.checker = MagicMock()
    source_errors = [{
        "error_type": "unverified",
        "error_details": "Web page not found (404)",
    }]
    reference = {
        "title": "Gorleben",
        "url": "http://www.gns.de/gorleben",
    }

    with patch(
        "backend.refchecker_wrapper.ArxivReferenceChecker.verify_reference_standard",
        return_value=(source_errors, reference["url"], None),
    ) as verify_standard:
        verified_data, errors, url = wrapper._verify_reference_body(reference)

    assert verified_data is None
    assert errors == source_errors
    assert url == reference["url"]
    verify_standard.assert_called_once()
    wrapper.checker.verify_reference.assert_not_called()


def test_webui_structured_pdf_extraction_separates_body_and_bibliography():
    wrapper = ProgressRefChecker.__new__(ProgressRefChecker)
    wrapper.check_id = None
    wrapper.llm = None
    wrapper.extraction_mode = "cascade"
    document = _structured_pdf_document()

    with patch(
        "backend.refchecker_wrapper.PDFProcessor"
    ) as processor_type:
        processor_type.return_value.extract_document.return_value = document
        result = wrapper._extract_pdf_document_scoped("paper.pdf")

    extracted_document, full_text, body_text, bibliography = result
    assert extracted_document is document
    assert full_text == document.full_text
    assert body_text == _PDF_BODY
    assert bibliography == _PDF_BIBLIOGRAPHY
    assert "[1] John Smith" not in body_text
    processor_type.return_value.extract_document.assert_called_once_with(
        "paper.pdf",
        include_bibliography=True,
    )


def test_webui_structured_pdf_failure_uses_legacy_body_recovery():
    wrapper = ProgressRefChecker.__new__(ProgressRefChecker)
    wrapper.check_id = None
    wrapper.llm = None
    wrapper.extraction_mode = "cascade"
    legacy_text = f"{_PDF_BODY}\n\nReferences\n{_PDF_BIBLIOGRAPHY}"
    wrapper._extract_pdf_text_scoped = MagicMock(return_value=legacy_text)

    with patch(
        "backend.refchecker_wrapper.PDFProcessor"
    ) as processor_type:
        processor_type.return_value.extract_document.side_effect = ValueError(
            "malformed PDF"
        )
        document, full_text, body_text, bibliography = (
            wrapper._extract_pdf_document_scoped("paper.pdf")
        )

    assert document is None
    assert full_text == legacy_text
    assert body_text
    assert "[1] John Smith" not in body_text
    assert bibliography and "[1] John Smith" in bibliography
    wrapper._extract_pdf_text_scoped.assert_called_once_with("paper.pdf")


def test_webui_pdf_cascade_parses_dedicated_bibliography_not_body_text():
    wrapper = ProgressRefChecker.__new__(ProgressRefChecker)
    wrapper.extraction_mode = "cascade"
    wrapper.llm = None
    wrapper._last_reference_parser_method = "regex"
    wrapper._extract_references = AsyncMock(
        return_value=[{"title": "Parsed reference"}]
    )

    with patch(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        return_value=(None, None),
    ):
        references, method = asyncio.run(
            wrapper._extract_references_from_pdf(
                "paper.pdf",
                _PDF_BODY,
                bibliography_text=_PDF_BIBLIOGRAPHY,
                full_text=f"{_PDF_BODY}\n\nReferences\n{_PDF_BIBLIOGRAPHY}",
            )
        )

    assert references == [{"title": "Parsed reference"}]
    assert method == "regex"
    wrapper._extract_references.assert_awaited_once_with(
        _PDF_BIBLIOGRAPHY,
        bibliography_text=_PDF_BIBLIOGRAPHY,
    )
