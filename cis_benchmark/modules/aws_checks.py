import subprocess
import json
from ..core.models import CheckResult, Status, Severity


def run_aws_json(command: str):
    """Runs an AWS CLI command and returns (ok, data).

    ok=False means the CLI invocation itself failed (bad flag, no
    credentials, timeout, unparsable output) — callers must treat this as
    Status.ERROR rather than assuming a clean/compliant result. ok=True with
    data=None means the command succeeded but returned no output.
    """
    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return False, (res.stderr or f"Command exited with code {res.returncode}").strip()
        if not res.stdout.strip():
            return True, None
        try:
            return True, json.loads(res.stdout)
        except json.JSONDecodeError as e:
            return False, f"Failed to parse AWS CLI JSON output: {e}"
    except subprocess.TimeoutExpired:
        return False, "AWS CLI command timed out after 15s"
    except Exception as e:
        return False, str(e)


def _error_result(rule_id, section, title, severity, rationale, remediation, error_detail):
    return CheckResult(
        rule_id=rule_id,
        section=section,
        title=title,
        severity=severity,
        status=Status.ERROR,
        rationale=rationale,
        remediation="Investigate AWS CLI authentication/configuration, then re-run the audit.",
        affected_resources=[],
        details=f"Could not verify — AWS CLI call failed: {error_detail}"
    )


class AWSCheckRootMFA:
    """AWS-1.1: Ensure MFA is enabled for the Root account."""
    def execute(self) -> CheckResult:
        rationale = "The root account has unrestricted access to all AWS resources. Enforcing MFA is critical to prevent account takeover."
        ok, summary = run_aws_json("aws iam get-account-summary --output json")
        if not ok:
            return _error_result("AWS-1.1", "1. Identity & Access Management (IAM)",
                                  "Ensure MFA is enabled for the Root account", Severity.CRITICAL,
                                  rationale, "AWS Management Console -> IAM -> Security credentials -> Activate MFA on root account.", summary)

        mfa_enabled = bool(summary and summary.get("SummaryMap", {}).get("AccountMFAEnabled", 0) == 1)

        if mfa_enabled:
            status = Status.PASS
            details = "Root account MFA is enabled."
            aff = []
        else:
            status = Status.FAIL
            details = "Root account MFA is NOT enabled."
            aff = ["Root Account (AWS Account)"]

        return CheckResult(
            rule_id="AWS-1.1",
            section="1. Identity & Access Management (IAM)",
            title="Ensure MFA is enabled for the Root account",
            severity=Severity.CRITICAL,
            status=status,
            rationale=rationale,
            remediation="AWS Management Console -> IAM -> Security credentials -> Activate MFA on root account.",
            affected_resources=aff,
            details=details
        )


class AWSCheckS3PublicAccessBlock:
    """AWS-2.1: Ensure S3 Account-Level Public Access Block is enabled."""
    def execute(self) -> CheckResult:
        rationale = "Account-level public access block acts as a centralized guardrail preventing accidental public S3 bucket exposure."
        remediation = "AWS Console -> S3 -> Block Public Access (account settings) -> Edit -> Block all public access."

        ok, account_id = run_aws_json("aws sts get-caller-identity --query Account --output json")
        if not ok:
            return _error_result("AWS-2.1", "2. Storage & S3 Security",
                                  "Ensure S3 Account-Level Public Access Block is enabled", Severity.CRITICAL,
                                  rationale, remediation, account_id)

        ok, pab = run_aws_json(f"aws s3control get-public-access-block --account-id {account_id} --output json")
        if not ok:
            return _error_result("AWS-2.1", "2. Storage & S3 Security",
                                  "Ensure S3 Account-Level Public Access Block is enabled", Severity.CRITICAL,
                                  rationale, remediation, pab)

        compliant = False
        if pab and "PublicAccessBlockConfiguration" in pab:
            cfg = pab["PublicAccessBlockConfiguration"]
            compliant = all([
                cfg.get("BlockPublicAcls", False),
                cfg.get("IgnorePublicAcls", False),
                cfg.get("BlockPublicPolicy", False),
                cfg.get("RestrictPublicBuckets", False)
            ])

        if compliant:
            status = Status.PASS
            details = "S3 Account-Level Public Access Block is fully enabled across all buckets."
            aff = []
        else:
            status = Status.FAIL
            details = "S3 Account-Level Public Access Block is not fully enforcing public block settings."
            aff = ["S3 Global Account Configuration"]

        return CheckResult(
            rule_id="AWS-2.1",
            section="2. Storage & S3 Security",
            title="Ensure S3 Account-Level Public Access Block is enabled",
            severity=Severity.CRITICAL,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=aff,
            details=details
        )


class AWSCheckSecurityGroupIngressSSH:
    """AWS-3.1: Ensure no Security Groups allow unrestricted 0.0.0.0/0 ingress to SSH (22)."""
    def execute(self) -> CheckResult:
        rationale = "Exposing SSH port 22 globally to 0.0.0.0/0 increases risk of brute-force credential attacks and automated exploit scanning."
        remediation = "Modify Security Group inbound rules to restrict source IP range to trusted corporate CIDRs."

        ok, sgs = run_aws_json("aws ec2 describe-security-groups --output json")
        if not ok:
            return _error_result("AWS-3.1", "3. Networking & VPC Security",
                                  "Ensure no Security Groups allow unrestricted 0.0.0.0/0 ingress to SSH (22)",
                                  Severity.CRITICAL, rationale, remediation, sgs)

        open_ssh = []
        if sgs and "SecurityGroups" in sgs:
            for sg in sgs["SecurityGroups"]:
                sg_id = sg.get("GroupId")
                sg_name = sg.get("GroupName")
                for perm in sg.get("IpPermissions", []):
                    from_port = perm.get("FromPort")
                    to_port = perm.get("ToPort")
                    ip_proto = perm.get("IpProtocol")
                    is_ssh = (ip_proto == "-1") or (from_port is not None and to_port is not None and from_port <= 22 <= to_port)
                    if is_ssh:
                        for ip_range in perm.get("IpRanges", []):
                            if ip_range.get("CidrIp") == "0.0.0.0/0":
                                open_ssh.append(f"Security Group '{sg_name}' ({sg_id})")

        if open_ssh:
            status = Status.FAIL
            details = f"Found {len(open_ssh)} EC2 Security Group(s) allowing unrestricted 0.0.0.0/0 SSH (22) ingress."
        else:
            status = Status.PASS
            details = "No EC2 Security Groups permit unrestricted 0.0.0.0/0 SSH ingress."

        return CheckResult(
            rule_id="AWS-3.1",
            section="3. Networking & VPC Security",
            title="Ensure no Security Groups allow unrestricted 0.0.0.0/0 ingress to SSH (22)",
            severity=Severity.CRITICAL,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=open_ssh,
            details=details
        )


class AWSCheckCloudTrailEnabled:
    """AWS-4.1: Ensure CloudTrail is enabled in all regions."""
    def execute(self) -> CheckResult:
        rationale = "CloudTrail provides event history of AWS API calls necessary for security auditing and forensic investigation."
        remediation = "AWS Console -> CloudTrail -> Create Trail -> Enable for all regions with log validation."

        ok, trails = run_aws_json("aws cloudtrail describe-trails --output json")
        if not ok:
            return _error_result("AWS-4.1", "4. Logging & CloudTrail Audit",
                                  "Ensure CloudTrail is enabled in all regions", Severity.HIGH,
                                  rationale, remediation, trails)

        active_trails = []
        if trails and "trailList" in trails:
            for t in trails["trailList"]:
                if t.get("IsMultiRegionTrail", False) and t.get("HasLogFileValidation", False):
                    active_trails.append(t.get("Name"))

        if active_trails:
            status = Status.PASS
            details = f"Multi-region CloudTrail with log validation active: {', '.join(active_trails)}"
            aff = []
        else:
            status = Status.FAIL
            details = "No multi-region CloudTrail with log file validation enabled found."
            aff = ["AWS CloudTrail Configuration"]

        return CheckResult(
            rule_id="AWS-4.1",
            section="4. Logging & CloudTrail Audit",
            title="Ensure CloudTrail is enabled in all regions",
            severity=Severity.HIGH,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=aff,
            details=details
        )
