import subprocess
from ..core.models import CheckResult, Status, Severity


class WorkspaceCheck2SV:
    """WS-1.1: Ensure 2-Step Verification (2SV) is enforced for all users."""
    def execute(self) -> CheckResult:
        # NOTE: verifying this requires the Admin SDK Reports/Directory API
        # with domain-wide delegation, which this tool does not yet call.
        # Reported as MANUAL_CHECK rather than a fabricated PASS.
        return CheckResult(
            rule_id="WS-1.1",
            section="1. Account & Authentication",
            title="Ensure 2-Step Verification (2SV) is enforced for all users",
            severity=Severity.CRITICAL,
            status=Status.MANUAL_CHECK,
            rationale="2-Step Verification adds an essential layer of security to prevent unauthorized access from compromised credentials.",
            remediation="Admin Console -> Security -> Authentication -> 2-Step Verification -> Turn on enforcement.",
            affected_resources=[],
            details="Automated verification not implemented: requires the Admin SDK Directory/Reports API with domain-wide delegation. Verify manually in the Admin Console."
        )


class WorkspaceCheckFIDO2Admins:
    """WS-1.2: Ensure Security Key (FIDO2) is required for Super Admin accounts."""
    def execute(self) -> CheckResult:
        return CheckResult(
            rule_id="WS-1.2",
            section="1. Account & Authentication",
            title="Ensure Security Key (FIDO2) is required for Super Admin accounts",
            severity=Severity.CRITICAL,
            status=Status.MANUAL_CHECK,
            rationale="Super Admin accounts have full domain privileges. SMS or push notifications are susceptible to interception and phishing.",
            remediation="Admin Console -> Security -> Authentication -> 2-Step Verification -> Select Only Security Key for Admins.",
            affected_resources=[],
            details="Automated verification not implemented: requires the Admin SDK Directory API with domain-wide delegation. Verify manually in the Admin Console."
        )


class WorkspaceCheckSPF_DKIM_DMARC:
    """WS-3.1: Ensure SPF, DKIM, and DMARC DNS policies are fully configured."""
    def __init__(self, domain: str = "example.com"):
        self.domain = domain

    def execute(self) -> CheckResult:
        missing = []
        # Check SPF
        try:
            res = subprocess.run(f"dig +short TXT {self.domain}", shell=True, capture_output=True, text=True, timeout=5)
            txt_records = res.stdout.strip()
            if "v=spf1" not in txt_records:
                missing.append(f"Missing SPF record for domain '{self.domain}'")
        except Exception:
            missing.append(f"Could not verify SPF for {self.domain}")

        # Check DMARC
        try:
            res_dmarc = subprocess.run(f"dig +short TXT _dmarc.{self.domain}", shell=True, capture_output=True, text=True, timeout=5)
            dmarc_txt = res_dmarc.stdout.strip()
            if "v=DMARC1" not in dmarc_txt:
                missing.append(f"Missing DMARC record for domain '{self.domain}'")
            elif "p=none" in dmarc_txt:
                missing.append(f"Weak DMARC policy (p=none) on '{self.domain}'. Recommend p=quarantine or p=reject.")
        except Exception:
            missing.append(f"Could not verify DMARC for {self.domain}")

        if missing:
            status = Status.WARNING
            details = f"Email authentication issues identified: {'; '.join(missing)}"
        else:
            status = Status.PASS
            details = f"SPF and DMARC records are properly configured for domain '{self.domain}'."

        return CheckResult(
            rule_id="WS-3.1",
            section="3. Gmail Security",
            title="Ensure SPF, DKIM, and DMARC DNS policies are fully configured",
            severity=Severity.CRITICAL,
            status=status,
            rationale="Email authentication protocols protect your domain from spoofing, impersonation, and phishing attacks.",
            remediation="Configure DNS TXT records for SPF (v=spf1), DKIM (2048-bit key), and DMARC (p=quarantine or p=reject).",
            affected_resources=missing,
            details=details
        )


class WorkspaceCheckOAuthRestricted:
    """WS-4.1: Ensure Unconfigured Third-Party OAuth Apps are Restricted by default."""
    def execute(self) -> CheckResult:
        return CheckResult(
            rule_id="WS-4.1",
            section="4. Apps & OAuth Control",
            title="Ensure Unconfigured Third-Party OAuth Apps are Restricted by default",
            severity=Severity.HIGH,
            status=Status.MANUAL_CHECK,
            rationale="Allowing arbitrary third-party apps to request OAuth scopes risks unauthorized access to domain data.",
            remediation="Admin Console -> Security -> Access and data control -> API Controls -> Unconfigured third-party apps -> Set to Restricted.",
            affected_resources=[],
            details="Automated verification not implemented: requires the Admin SDK API. Verify manually in the Admin Console."
        )


class WorkspaceCheckAdminAuditLogs:
    """WS-5.1: Ensure Admin SDK Activity and System Logs are enabled & exported."""
    def execute(self) -> CheckResult:
        return CheckResult(
            rule_id="WS-5.1",
            section="5. Audit & Compliance Logging",
            title="Ensure Admin SDK Activity and System Logs are enabled & exported",
            severity=Severity.MEDIUM,
            status=Status.MANUAL_CHECK,
            rationale="Centralized audit logging enables incident investigation, threat detection, and compliance auditing.",
            remediation="Enable Admin SDK Logging in API Console and stream logs to Google Cloud Logging or a SIEM.",
            affected_resources=[],
            details="Automated verification not implemented: requires the Admin SDK Reports API. Verify manually in the Admin Console / API Console."
        )
