"""Source-grounded author parsing across CLI, WebUI, and bulk extraction."""

from unittest.mock import Mock

import pytest

from backend.refchecker_wrapper import _make_cli_checker
from refchecker.core.bulk_pipeline import parse_references_bulk
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.biblatex_parser import (
    parse_biblatex_entry_content,
    parse_biblatex_references,
)
from refchecker.utils.text_utils import compare_authors


RUHLE = (
    '[21] S. Rühle, “Tabulated values of the shockley–queisser limit for single\n'
    'junction solar cells,”Solar energy, vol. 130, pp. 139–147, 2016.'
)
ABERLE = (
    '[39] A. G. Aberle, “Overview on sin surface passivation of crystalline sil-\n'
    'icon solar cells,”Solar energy materials and solar cells, vol. 65, no.\n'
    '1-4, pp. 239–248, 2001.'
)
REPEATED_ABERLE = (
    '[40] ——, “Overview on sin surface passivation of crystalline silicon solar\n'
    'cells,” Solar energy materials and solar cells, vol. 65, no. 1-4, pp.\n'
    '239–248, 2001.'
)


@pytest.mark.parametrize('author', ['S. Rühle', 'É. Noël', 'Ł. Żuk', 'Ö. Öz', 'A. 李明'])
def test_quoted_reference_accepts_unicode_author_names(author):
    ref = parse_biblatex_entry_content(
        '21', f'{author}, “A descriptive article title,” Solar energy, 2016.'
    )

    assert ref['authors'] == [author]


@pytest.mark.parametrize('marker', ['——', '—', '―', '––', '---', '___'])
def test_repeated_author_marker_uses_previous_cited_authors(marker):
    repeated = REPEATED_ABERLE.replace('——', marker)
    refs = parse_biblatex_references('\n'.join([ABERLE, repeated]))

    assert len(refs) == 2
    assert [ref['entry_number'] for ref in refs] == [39, 40]
    assert refs[0]['authors'] == refs[1]['authors'] == ['A. G. Aberle']
    assert marker in refs[1]['raw_text']
    assert refs[0]['authors'] is not refs[1]['authors']


def test_repeated_author_chain_copies_full_list_and_keeps_separate_works():
    refs = parse_biblatex_references(
        '[1] S. Rühle and A. G. Aberle, “First solar article,” Solar energy, 2016.\n'
        '[2] ——, “Second solar article,” Solar energy, 2017.\n'
        '[3] ——, “Third solar article,” Solar energy, 2018.'
    )

    assert len(refs) == 3
    assert [ref['authors'] for ref in refs] == [['S. Rühle', 'A. G. Aberle']] * 3
    assert [ref['year'] for ref in refs] == [2016, 2017, 2018]


@pytest.mark.parametrize('middle', [
    '',
    '[39] “An anonymous article,” Solar energy, 2000.\n',
])
def test_repeated_author_without_known_immediate_predecessor_stays_unknown(middle):
    # Extra valid entries keep the parser's aggregate quality gate satisfied.
    refs = parse_biblatex_references('\n'.join([
        '[35] A. Author, “An earlier article,” Solar energy, 2010.',
        '[36] B. Writer, “A second article,” Solar energy, 2011.',
        '[37] C. Editor, “A third article,” Solar energy, 2012.',
        '[38] D. Scholar, “A fourth article,” Solar energy, 2013.',
        middle + REPEATED_ABERLE,
        '[41] E. Researcher, “A final article,” Solar energy, 2014.',
        '[42] F. Scientist, “Another final article,” Solar energy, 2015.',
        '[43] G. Student, “One more article,” Solar energy, 2016.',
        '[44] H. Professor, “Last article,” Solar energy, 2017.',
    ]))

    repeated = next(ref for ref in refs if ref['entry_number'] == 40)
    assert repeated['authors'] == ['Unknown Author']


@pytest.mark.parametrize('path', ['cli', 'webui', 'bulk'])
def test_solar_bibliography_author_recovery_has_execution_path_parity(path):
    entries = [
        f'[{number}] A. Author, “A distinct cited article {number},” Solar energy, 2010.'
        for number in range(1, 263)
    ]
    entries[20], entries[38], entries[39] = RUHLE, ABERLE, REPEATED_ABERLE
    bibliography = '\n'.join(entries)
    if path == 'webui':
        checker = _make_cli_checker(None)
    else:
        checker = ArxivReferenceChecker(llm_config={'disabled': True})
    if path == 'bulk':
        batcher = Mock()
        refs = parse_references_bulk(checker, bibliography, batcher)
        batcher.extract_references.assert_not_called()
    else:
        refs = checker.parse_references(bibliography)

    assert len(refs) == 262
    assert [ref['entry_number'] for ref in refs] == list(range(1, 263))
    assert [refs[index]['authors'] for index in (20, 38, 39)] == [
        ['S. Rühle'], ['A. G. Aberle'], ['A. G. Aberle'],
    ]
    assert checker.last_reference_parser_method == 'regex'
    assert not checker.fatal_error
    assert compare_authors(refs[20]['authors'], ['Sven Rühle'])[0]
    assert compare_authors(refs[39]['authors'], ['Armin G Aberle'])[0]
