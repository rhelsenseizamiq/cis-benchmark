import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from .models import CheckResult, Status, Severity
from .config import load_settings
from ..modules.gcp_checks import (
    GCPCheckServiceAccountKeys,
    GCPCheckPrimitiveRoles,
    GCPCheckFirewallSSH,
    GCPCheckFirewallRDP,
    GCPCheckPublicBuckets,
    GCPCheckCloudSQLPublicIP
)
from ..modules.workspace_checks import (
    WorkspaceCheck2SV,
    WorkspaceCheckFIDO2Admins,
    WorkspaceCheckSPF_DKIM_DMARC,
    WorkspaceCheckOAuthRestricted,
    WorkspaceCheckAdminAuditLogs
)
from ..modules.aws_checks import (
    AWSCheckRootMFA,
    AWSCheckS3PublicAccessBlock,
    AWSCheckSecurityGroupIngressSSH,
    AWSCheckCloudTrailEnabled
)
from ..modules.azure_checks import (
    AzureCheckMFAAdmins,
    AzureCheckStoragePublicBlob,
    AzureCheckNSGUnrestrictedSSH
)

class ComplianceEngine:
    def __init__(self, max_workers: int = 10, target_domain: str = "example.com", cloud_filter: str = "all"):
        self.max_workers = max_workers
        self.target_domain = target_domain
        self.cloud_filter = cloud_filter.lower()
        self.settings = load_settings()
        self.checks = self._load_checks()

    def _load_checks(self):
        all_checks = []
        key_max_age = self.settings.get("key_expiration_threshold_days", 90)

        # GCP Checks
        if self.cloud_filter in ["all", "gcp"]:
            all_checks.extend([
                GCPCheckServiceAccountKeys(max_key_age_days=key_max_age),
                GCPCheckPrimitiveRoles(),
                GCPCheckFirewallSSH(),
                GCPCheckFirewallRDP(),
                GCPCheckPublicBuckets(),
                GCPCheckCloudSQLPublicIP()
            ])

        # Google Workspace Checks
        if self.cloud_filter in ["all", "workspace"]:
            all_checks.extend([
                WorkspaceCheck2SV(),
                WorkspaceCheckFIDO2Admins(),
                WorkspaceCheckSPF_DKIM_DMARC(domain=self.target_domain),
                WorkspaceCheckOAuthRestricted(),
                WorkspaceCheckAdminAuditLogs()
            ])

        # AWS Checks
        if self.cloud_filter in ["all", "aws"]:
            all_checks.extend([
                AWSCheckRootMFA(),
                AWSCheckS3PublicAccessBlock(),
                AWSCheckSecurityGroupIngressSSH(),
                AWSCheckCloudTrailEnabled()
            ])

        # Azure Checks
        if self.cloud_filter in ["all", "azure"]:
            all_checks.extend([
                AzureCheckMFAAdmins(),
                AzureCheckStoragePublicBlob(),
                AzureCheckNSGUnrestrictedSSH()
            ])

        return all_checks

    def run_all(self, status_callback=None) -> Dict[str, Any]:
        start_time = time.time()
        results: List[CheckResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_check = {executor.submit(check.execute): check for check in self.checks}
            for future in as_completed(future_to_check):
                try:
                    res = future.result()
                    results.append(res)
                    if status_callback:
                        status_callback(res)
                except Exception as e:
                    check = future_to_check[future]
                    res_err = CheckResult(
                        rule_id=getattr(check, 'rule_id', 'ERR'),
                        section=getattr(check, 'section', 'General'),
                        title=getattr(check, 'title', 'Execution Error'),
                        severity=getattr(check, 'severity', Severity.HIGH),
                        status=Status.ERROR,
                        rationale="Check failed to execute properly.",
                        remediation="Investigate API credentials or CLI tool authentication.",
                        details=str(e)
                    )
                    results.append(res_err)
                    if status_callback:
                        status_callback(res_err)

        duration = round(time.time() - start_time, 2)
        
        # Calculate Statistics
        total_checks = len(results)
        pass_count = sum(1 for r in results if r.status == Status.PASS)
        fail_count = sum(1 for r in results if r.status == Status.FAIL)
        warn_count = sum(1 for r in results if r.status == Status.WARNING)
        manual_count = sum(1 for r in results if r.status == Status.MANUAL_CHECK)
        error_count = sum(1 for r in results if r.status == Status.ERROR)

        compliance_score = round((pass_count / total_checks) * 100, 1) if total_checks > 0 else 0.0

        return {
            "duration": duration,
            "total_checks": total_checks,
            "passed": pass_count,
            "failed": fail_count,
            "warnings": warn_count,
            "manual": manual_count,
            "errors": error_count,
            "score": compliance_score,
            "results": results
        }
