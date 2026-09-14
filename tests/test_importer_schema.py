import json

from cis_benchmark.importer.schema import ImportedRule, BenchmarkCatalog, now_iso


def test_imported_rule_defaults():
    rule = ImportedRule(id="1.1", title="Example", scored=True, profile_level="Level 1", section="1. Example")
    assert rule.description == ""
    assert rule.references == []
    assert rule.incomplete is False
    assert rule.missing_sections == []


def test_catalog_to_dict_includes_counts():
    rules = [
        ImportedRule(id="1.1", title="A", scored=True, profile_level="Level 1", section="1. X"),
        ImportedRule(id="1.2", title="B", scored=False, profile_level="Level 2", section="1. X", incomplete=True, missing_sections=["Remediation:"]),
    ]
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark",
        benchmark_version="9.9.9",
        source_filename="test.pdf",
        extracted_at=now_iso(),
        rules=rules,
    )
    d = catalog.to_dict()
    assert d["total_rules"] == 2
    assert d["incomplete_rules"] == 1
    assert len(d["rules"]) == 2
    assert d["rules"][0]["id"] == "1.1"


def test_catalog_to_json_is_valid_json():
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="9.9.9",
        source_filename="test.pdf", extracted_at=now_iso(), rules=[],
    )
    parsed = json.loads(catalog.to_json())
    assert parsed["benchmark_name"] == "CIS Test Benchmark"
    assert parsed["total_rules"] == 0


def test_catalog_write_creates_parent_dirs_and_file(tmp_path):
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="9.9.9",
        source_filename="test.pdf", extracted_at=now_iso(),
        rules=[ImportedRule(id="1.1", title="A", scored=True, profile_level="Level 1", section="1. X")],
    )
    out_path = tmp_path / "nested" / "dir" / "catalog.json"
    result_path = catalog.write(str(out_path))

    assert result_path == str(out_path)
    assert out_path.exists()
    with open(out_path) as f:
        data = json.load(f)
    assert data["total_rules"] == 1
