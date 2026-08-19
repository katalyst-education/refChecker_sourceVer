from unittest.mock import MagicMock, patch

from backend.refchecker_wrapper import ProgressRefChecker


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
