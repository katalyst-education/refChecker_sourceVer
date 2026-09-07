"""CLI contract tests for the verification-only command surface."""

import pytest

from backend import cli


def test_legacy_server_form_still_parses():
    args = cli.parse_args(["--port", "9001", "--host", "127.0.0.1"])
    assert args.command == "serve"
    assert args.port == 9001
    assert args.host == "127.0.0.1"
    assert args._handler is cli.run_serve


def test_explicit_serve_subcommand():
    args = cli.parse_args(["serve", "--reload"])
    assert args.command == "serve"
    assert args.reload is True


def test_check_requires_a_paper_during_argument_parsing():
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["check"])
    assert exc_info.value.code == 2


def test_infer_source_type_for_arxiv_identifier():
    source_type, source = cli._infer_source_type("2406.01234")
    assert source_type == "url"
    assert source == "2406.01234"


def test_infer_source_type_for_local_file(tmp_path):
    bibliography = tmp_path / "refs.bib"
    bibliography.write_text("@article{a, title={X}}", encoding="utf-8")
    source_type, source = cli._infer_source_type(str(bibliography))
    assert source_type == "file"
    assert source == str(bibliography)
