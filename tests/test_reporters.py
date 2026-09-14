"""Regression tests for the reporter fixes:
- html_reporter.py must HTML-escape resource names/details (a maliciously
  named cloud resource used to be able to inject markup/script into a
  report opened in a browser).
- excel_reporter.py must neutralize CSV/Excel formula-injection characters
  in cell values sourced from live resource names.
- doc_reporter.py / cli.py must render Status.ERROR and
  Status.MANUAL_CHECK distinctly rather than collapsing them into "WARNING".
"""
from cis_benchmark.core.models import CheckResult, Status, Severity
from cis_benchmark.reporters.html_reporter import HTMLReporter
from cis_benchmark.reporters.doc_reporter import DocReporter, STATUS_ICON
from cis_benchmark.reporters.excel_reporter import _sanitize_cell


def _summary_with(result):
    return {
        "duration": 0.1, "total_checks": 1, "passed": 0, "failed": 0,
        "warnings": 0, "manual": 0, "errors": 0, "score": 0.0,
        "results": [result], "timestamp": "now",
    }


def test_html_reporter_escapes_malicious_resource_name(tmp_path):
    malicious = CheckResult(
        rule_id="X", section="s", title="t", severity=Severity.HIGH,
        status=Status.FAIL, rationale="r", remediation="m",
        affected_resources=["<script>alert(1)</script>"],
        details="<img src=x onerror=alert(1)>",
    )
    reporter = HTMLReporter(output_dir=str(tmp_path))
    path = reporter.generate(_summary_with(malicious), filename="report.html")
    content = open(path).read()
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content
    assert "<img src=x onerror=alert(1)>" not in content


def test_html_reporter_distinguishes_error_and_manual_status(tmp_path):
    err = CheckResult(rule_id="E", section="s", title="t", severity=Severity.HIGH,
                       status=Status.ERROR, rationale="r", remediation="m")
    manual = CheckResult(rule_id="M", section="s", title="t", severity=Severity.HIGH,
                          status=Status.MANUAL_CHECK, rationale="r", remediation="m")
    reporter = HTMLReporter(output_dir=str(tmp_path))
    summary = _summary_with(err)
    summary["results"].append(manual)
    content = open(reporter.generate(summary, filename="report2.html")).read()
    assert "st-error" in content
    assert "st-manual" in content
    assert "st-warn\">⚠️ ERROR" not in content  # must not fall back to the warning style


def test_doc_reporter_status_icons_cover_all_statuses():
    for status in Status:
        assert status.value in STATUS_ICON


def test_excel_sanitize_neutralizes_formula_injection():
    assert _sanitize_cell("=cmd|'/c calc'!A0") == "'=cmd|'/c calc'!A0"
    assert _sanitize_cell("+1+1") == "'+1+1"
    assert _sanitize_cell("normal-bucket-name") == "normal-bucket-name"
    assert _sanitize_cell(42) == 42
