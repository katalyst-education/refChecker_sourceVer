import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

from backend.refchecker_wrapper import ProgressRefChecker


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
