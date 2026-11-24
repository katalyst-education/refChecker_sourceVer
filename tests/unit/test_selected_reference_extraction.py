"""One-reference re-extraction limits generative work to its source entry."""

import asyncio
from unittest.mock import Mock

import pytest

from backend.refchecker_wrapper import ProgressRefChecker, _make_cli_checker


def bibliography():
    entries = [
        f'[{number}] A. Author, “A cited article numbered {number},” Journal, 2020.'
        for number in range(1, 263)
    ]
    # An unrelated damaged author must not force full-bibliography repair.
    entries[21] = '[22] ——, “An unrelated solar article,” Journal, 2020.'
    entries[20] = '[21] “An anonymous article,” Journal, 2020.'
    entries[38] = '[39] A. G. Aberle, “Surface passivation of silicon,” Journal, 2001.'
    entries[39] = '[40] ——, “Surface passivation of silicon,” Journal, 2001.'
    return '\n'.join(entries)


def test_valid_selected_entry_uses_shared_parser_despite_other_invalid_entries():
    checker = _make_cli_checker(None)
    checker.llm_extractor = Mock()

    selected = checker.parse_reference_entry(bibliography(), 49)

    assert selected['entry_number'] == 49
    assert selected['authors'] == ['A. Author']
    assert selected['title'] == 'A cited article numbered 49'
    checker.llm_extractor.extract_references.assert_not_called()
    assert checker.last_reference_parser_method == 'regex'


def test_selected_entry_preserves_repeated_author_context():
    checker = _make_cli_checker(None)

    selected = checker.parse_reference_entry(bibliography(), 40)

    assert selected['entry_number'] == 40
    assert selected['authors'] == ['A. G. Aberle']
    assert '——' in selected['raw_text']


@pytest.mark.parametrize('mode', ['cascade', 'llm-only'])
def test_selected_llm_repair_receives_only_requested_source_entry(mode):
    checker = _make_cli_checker(None, mode)
    checker.llm_extractor = Mock()
    checker.llm_extractor.extract_references.return_value = [
        'A. Author#An anonymous article#Journal#2020#',
    ]

    selected = checker.parse_reference_entry(bibliography(), 21)

    assert selected['authors'] == ['A. Author']
    assert selected['entry_number'] == 21
    args = checker.llm_extractor.extract_references.call_args.args
    assert args == ('[21] “An anonymous article,” Journal, 2020.',)
    assert checker.llm_extractor.extract_references.call_count == 1
    assert checker.last_reference_parser_method == 'llm'


def test_empty_selected_extraction_stops_after_one_attempt():
    checker = _make_cli_checker(None)
    checker.llm_extractor = Mock()
    checker.llm_extractor.extract_references.return_value = []

    with pytest.raises(ValueError, match='reference 21'):
        checker.parse_reference_entry(bibliography(), 21)

    assert checker.llm_extractor.extract_references.call_count == 1


@pytest.mark.parametrize('number', [None, 999, 'invalid'])
def test_unavailable_source_number_defers_to_document_pipeline(number):
    checker = _make_cli_checker(None)
    assert checker.parse_reference_entry(bibliography(), number) is None


def test_webui_selected_extraction_uses_shared_core():
    wrapper = ProgressRefChecker.__new__(ProgressRefChecker)
    wrapper.llm = None
    wrapper.extraction_mode = 'cascade'
    wrapper.check_id = None

    selected = asyncio.run(wrapper._extract_reference(
        'Introduction\nSome discussion.\n\nReferences\n' + bibliography(), 49,
    ))

    assert selected['entry_number'] == 49
    assert selected['authors'] == ['A. Author']
