"""Regression tests for the always-PASS bugs:
- AzureCheckMFAAdmins used to return Status.PASS on BOTH branches of its
  if/else, meaning it could never fail. It must now report MANUAL_CHECK,
  since no real MFA/Conditional Access verification is implemented.
- Four Google Workspace checks (WS-1.1, WS-1.2, WS-4.1, WS-5.1) were hardcoded
  to Status.PASS with no API call at all. They must now report MANUAL_CHECK.
"""
from cis_benchmark.core.models import Status
from cis_benchmark.modules.azure_checks import AzureCheckMFAAdmins
from cis_benchmark.modules.workspace_checks import (
    WorkspaceCheck2SV,
    WorkspaceCheckFIDO2Admins,
    WorkspaceCheckOAuthRestricted,
    WorkspaceCheckAdminAuditLogs,
)


def test_azure_mfa_is_manual_check_not_fabricated_pass():
    result = AzureCheckMFAAdmins().execute()
    assert result.status == Status.MANUAL_CHECK
    assert result.status != Status.PASS


def test_workspace_stub_checks_are_manual_not_fabricated_pass():
    for check_cls in (
        WorkspaceCheck2SV,
        WorkspaceCheckFIDO2Admins,
        WorkspaceCheckOAuthRestricted,
        WorkspaceCheckAdminAuditLogs,
    ):
        result = check_cls().execute()
        assert result.status == Status.MANUAL_CHECK, f"{check_cls.__name__} must not fabricate PASS"
