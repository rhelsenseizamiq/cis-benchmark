"""Regression tests for the AWS module fixes:
- run_aws_json distinguishes CLI failure (ok=False) from a valid empty result.
- AWSCheckSecurityGroupIngressSSH no longer uses the invalid gcloud-style
  '--format=json' flag (the bug that made this CRITICAL check always
  silently report a false PASS).
"""
from unittest.mock import patch, MagicMock

from cis_benchmark.core.models import Status
from cis_benchmark.modules.aws_checks import run_aws_json, AWSCheckSecurityGroupIngressSSH, AWSCheckRootMFA


def _fake_run(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_run_aws_json_uses_output_flag_not_format():
    """The historical bug: aws_checks.py called `--format=json`, which AWS
    CLI rejects (that flag is gcloud syntax). All AWS commands must use the
    real AWS CLI flag `--output json`."""
    check = AWSCheckSecurityGroupIngressSSH()
    with patch("cis_benchmark.modules.aws_checks.subprocess.run") as mock_run:
        mock_run.return_value = _fake_run(returncode=0, stdout='{"SecurityGroups": []}')
        check.execute()
        called_command = mock_run.call_args[0][0]
    assert "--output json" in called_command
    assert "--format=json" not in called_command


def test_run_aws_json_reports_failure_not_silent_none():
    ok, data = run_aws_json("aws sts get-caller-identity")
    # sanity: real call will fail in this sandbox (no aws cli) -> ok False
    assert ok is False
    assert data


def test_cli_error_surfaces_as_error_status_not_false_pass():
    """A broken/unauthenticated AWS CLI must produce Status.ERROR, never a
    silent Status.PASS (the original fail-open behavior)."""
    check = AWSCheckSecurityGroupIngressSSH()
    with patch("cis_benchmark.modules.aws_checks.subprocess.run") as mock_run:
        mock_run.return_value = _fake_run(returncode=255, stderr="Unable to locate credentials")
        result = check.execute()
    assert result.status == Status.ERROR
    assert "credentials" in result.details.lower() or "could not verify" in result.details.lower()


def test_open_ssh_security_group_is_detected_as_fail():
    check = AWSCheckSecurityGroupIngressSSH()
    sg_payload = {
        "SecurityGroups": [
            {
                "GroupId": "sg-123",
                "GroupName": "wide-open",
                "IpPermissions": [
                    {"FromPort": 22, "ToPort": 22, "IpProtocol": "tcp",
                     "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}
                ]
            }
        ]
    }
    import json
    with patch("cis_benchmark.modules.aws_checks.subprocess.run") as mock_run:
        mock_run.return_value = _fake_run(returncode=0, stdout=json.dumps(sg_payload))
        result = check.execute()
    assert result.status == Status.FAIL
    assert "sg-123" in result.affected_resources[0]


def test_root_mfa_pass_when_enabled():
    import json
    with patch("cis_benchmark.modules.aws_checks.subprocess.run") as mock_run:
        mock_run.return_value = _fake_run(returncode=0, stdout=json.dumps({"SummaryMap": {"AccountMFAEnabled": 1}}))
        result = AWSCheckRootMFA().execute()
    assert result.status == Status.PASS
