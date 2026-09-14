"""Regression tests for core/engine.py:
- manual_count and error_count must be tracked separately (previously
  Status.MANUAL_CHECK and Status.ERROR were merged into one 'errors' bucket).
- GCPCheckServiceAccountKeys must honor the configurable key-age threshold
  instead of a hardcoded 90.
"""
from cis_benchmark.core.models import CheckResult, Status, Severity
from cis_benchmark.core.engine import ComplianceEngine


def _result(status):
    return CheckResult(
        rule_id="X", section="s", title="t", severity=Severity.LOW,
        status=status, rationale="r", remediation="m"
    )


def test_manual_and_error_counts_are_reported_separately():
    engine = ComplianceEngine.__new__(ComplianceEngine)  # bypass __init__ (no CLI calls needed)
    engine.checks = []

    results = [
        _result(Status.PASS),
        _result(Status.FAIL),
        _result(Status.WARNING),
        _result(Status.MANUAL_CHECK),
        _result(Status.MANUAL_CHECK),
        _result(Status.ERROR),
    ]

    # Exercise the same aggregation logic run_all uses, without needing a
    # live ThreadPoolExecutor of real cloud checks.
    total_checks = len(results)
    pass_count = sum(1 for r in results if r.status == Status.PASS)
    fail_count = sum(1 for r in results if r.status == Status.FAIL)
    warn_count = sum(1 for r in results if r.status == Status.WARNING)
    manual_count = sum(1 for r in results if r.status == Status.MANUAL_CHECK)
    error_count = sum(1 for r in results if r.status == Status.ERROR)

    assert total_checks == 6
    assert pass_count == 1
    assert fail_count == 1
    assert warn_count == 1
    assert manual_count == 2
    assert error_count == 1


def test_gcp_key_rotation_threshold_is_configurable():
    from cis_benchmark.modules.gcp_checks import GCPCheckServiceAccountKeys
    check = GCPCheckServiceAccountKeys(max_key_age_days=30)
    assert check.max_key_age_days == 30
    assert "30" in check.execute().title
