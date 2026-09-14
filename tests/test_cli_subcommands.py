import argparse

import pytest

from cis_benchmark import cli
from cis_benchmark.core.config import load_settings
from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.schema import BenchmarkCatalog, ImportedRule


def test_bare_scan_flags_still_work():
    assert cli._normalize_argv(["--cloud", "aws"]) == ["scan", "--cloud", "aws"]


def test_empty_argv_defaults_to_scan():
    assert cli._normalize_argv([]) == ["scan"]


def test_explicit_scan_command_passes_through():
    assert cli._normalize_argv(["scan", "--cloud", "aws"]) == ["scan", "--cloud", "aws"]


def test_import_command_passes_through():
    assert cli._normalize_argv(["import", "file.pdf", "--cloud", "aws"]) == ["import", "file.pdf", "--cloud", "aws"]


def test_help_and_version_pass_through_unmodified():
    assert cli._normalize_argv(["--help"]) == ["--help"]
    assert cli._normalize_argv(["-h"]) == ["-h"]
    assert cli._normalize_argv(["--version"]) == ["--version"]


def test_parser_produces_scan_namespace_with_settings_defaults():
    settings = load_settings()
    parser = cli._build_parser(settings)
    args = parser.parse_args(cli._normalize_argv(["--cloud", "aws"]))
    assert args.command == "scan"
    assert args.cloud == "aws"
    assert args.workers == settings["max_worker_threads"]
    assert args.output == settings["output_directory"]
    assert args.plain is False


def test_parser_produces_import_namespace():
    settings = load_settings()
    parser = cli._build_parser(settings)
    args = parser.parse_args(["import", "/tmp/fake.pdf", "--cloud", "aws"])
    assert args.command == "import"
    assert args.pdf_path == "/tmp/fake.pdf"
    assert args.cloud == "aws"
    assert args.output is None


def test_import_requires_cloud_argument():
    settings = load_settings()
    parser = cli._build_parser(settings)
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "/tmp/fake.pdf"])


def test_run_import_writes_catalog_and_prints_summary(tmp_path, monkeypatch, capsys):
    fake_catalog = BenchmarkCatalog(
        benchmark_name="Fake Benchmark", benchmark_version="9.9.9",
        source_filename="fake.pdf", extracted_at="now",
        rules=[ImportedRule(id="1.1", title="t", scored=True, profile_level="Level 1", section="1. X")],
    )
    monkeypatch.setattr(cli, "extract_text", lambda path: "irrelevant")
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": lambda text, source_filename="": fake_catalog})

    output_path = tmp_path / "out.json"
    args = argparse.Namespace(cloud="aws", pdf_path="fake.pdf", output=str(output_path))
    cli._run_import(args)

    assert output_path.exists()
    captured = capsys.readouterr()
    assert "Parsed 1 rule(s) (0 incomplete)" in captured.out


def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="azure", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)


def test_run_import_default_output_path(tmp_path, monkeypatch):
    fake_catalog = BenchmarkCatalog(
        benchmark_name="Fake", benchmark_version="1.2.3",
        source_filename="fake.pdf", extracted_at="now", rules=[],
    )
    monkeypatch.setattr(cli, "extract_text", lambda path: "irrelevant")
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": lambda text, source_filename="": fake_catalog})
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(cloud="aws", pdf_path="fake.pdf", output=None)
    cli._run_import(args)

    assert (tmp_path / "imports" / "aws_1.2.3.json").exists()


def test_main_prints_clean_error_and_exits_1_on_importer_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["cis", "import", "fake.pdf", "--cloud", "azure"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.err
