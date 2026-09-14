import json
import subprocess
from datetime import datetime, timezone
from ..core.models import CheckResult, Status, Severity


def run_gcloud_json(command: str):
    """Runs a gcloud CLI command and returns (ok, data).

    ok=False means the CLI invocation itself failed — callers must treat
    this as Status.ERROR rather than assuming a clean/compliant result.
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
            return False, f"Failed to parse gcloud CLI JSON output: {e}"
    except subprocess.TimeoutExpired:
        return False, "gcloud CLI command timed out after 15s"
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
        remediation="Investigate gcloud CLI authentication/configuration, then re-run the audit.",
        affected_resources=[],
        details=f"Could not verify — gcloud CLI call failed: {error_detail}"
    )


class GCPCheckServiceAccountKeys:
    """GCP-1.1: Audit user-managed service account keys for age (>max_key_age_days)."""
    def __init__(self, max_key_age_days: int = 90):
        self.max_key_age_days = max_key_age_days

    def execute(self) -> CheckResult:
        rationale = "Service account keys do not automatically expire. Stale keys exposed in source code or backup files create long-term persistent backdoor access."
        remediation = "Delete old key IDs and rotate to new service account keys using gcloud iam service-accounts keys delete."
        title = f"Ensure User-Managed Service Account Keys are rotated every {self.max_key_age_days} days or less"

        ok, sa_list = run_gcloud_json("gcloud iam service-accounts list --format=json")
        if not ok:
            return _error_result("GCP-1.1", "1. Identity & Access Management (IAM)", title,
                                  Severity.HIGH, rationale, remediation, sa_list)

        stale_keys = []
        now = datetime.now(timezone.utc)

        if sa_list:
            for sa in sa_list:
                email = sa.get("email")
                key_ok, keys = run_gcloud_json(
                    f"gcloud iam service-accounts keys list --iam-account={email} --managed-by=user --format=json"
                )
                if not key_ok:
                    return _error_result("GCP-1.1", "1. Identity & Access Management (IAM)", title,
                                          Severity.HIGH, rationale, remediation, keys)
                if keys:
                    for key in keys:
                        valid_after = key.get("validAfterTime")
                        if valid_after:
                            dt = datetime.fromisoformat(valid_after.replace("Z", "+00:00"))
                            age_days = (now - dt).days
                            if age_days > self.max_key_age_days:
                                key_id = key.get("name", "").split("/")[-1]
                                stale_keys.append(f"SA: {email} (Key ID: {key_id}, Age: {age_days} days)")

        if stale_keys:
            status = Status.FAIL
            details = f"Found {len(stale_keys)} user-managed service account key(s) older than {self.max_key_age_days} days."
        else:
            status = Status.PASS
            details = f"All user-managed service account keys are compliant (< {self.max_key_age_days} days old)."

        return CheckResult(
            rule_id="GCP-1.1",
            section="1. Identity & Access Management (IAM)",
            title=title,
            severity=Severity.HIGH,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=stale_keys,
            details=details
        )


class GCPCheckPrimitiveRoles:
    """GCP-1.2: Ensure Primitive Roles (Owner/Editor) are not used for service accounts."""
    def execute(self) -> CheckResult:
        rationale = "Primitive roles grant blanket read/write/delete privileges across all resources in a GCP project."
        remediation = "Replace roles/owner and roles/editor with predefined, least-privileged IAM roles."
        section = "1. Identity & Access Management (IAM)"
        title = "Ensure Primitive Roles (Owner/Editor) are not used for service accounts"

        ok, project_id = run_gcloud_json("gcloud config get-value project --format=json")
        if not ok:
            return _error_result("GCP-1.2", section, title, Severity.CRITICAL, rationale, remediation, project_id)
        if not project_id:
            return _error_result("GCP-1.2", section, title, Severity.CRITICAL, rationale, remediation,
                                  "No active gcloud project is configured (gcloud config get-value project returned empty).")

        ok, iam_policy = run_gcloud_json(f"gcloud projects get-iam-policy {project_id} --format=json")
        if not ok:
            return _error_result("GCP-1.2", section, title, Severity.CRITICAL, rationale, remediation, iam_policy)

        violating_bindings = []
        if iam_policy and "bindings" in iam_policy:
            for b in iam_policy["bindings"]:
                role = b.get("role", "")
                if role in ["roles/owner", "roles/editor"]:
                    for member in b.get("members", []):
                        if member.startswith("serviceAccount:"):
                            violating_bindings.append(f"{member} has primitive role {role}")

        if violating_bindings:
            status = Status.FAIL
            details = f"Found {len(violating_bindings)} service account(s) assigned primitive Owner/Editor roles."
        else:
            status = Status.PASS
            details = "No service accounts found with primitive Owner/Editor roles."

        return CheckResult(
            rule_id="GCP-1.2", section=section, title=title, severity=Severity.CRITICAL, status=status,
            rationale=rationale, remediation=remediation, affected_resources=violating_bindings, details=details
        )


class GCPCheckFirewallSSH:
    """GCP-3.1: Ensure no VPC Firewall rules allow unrestricted 0.0.0.0/0 ingress to SSH (22)."""
    def execute(self) -> CheckResult:
        rationale = "Exposing SSH globally invites automated brute-force attacks and zero-day exploitation."
        remediation = "Modify firewall rule sourceRanges to trusted corporate IP blocks or use Identity-Aware Proxy (IAP)."
        section = "3. Networking & Perimeter Security"
        title = "Ensure no VPC Firewall rules allow unrestricted 0.0.0.0/0 ingress to SSH (22)"

        ok, rules = run_gcloud_json("gcloud compute firewall-rules list --format=json")
        if not ok:
            return _error_result("GCP-3.1", section, title, Severity.CRITICAL, rationale, remediation, rules)

        open_ssh = []
        if rules:
            for r in rules:
                if r.get("direction") == "INGRESS" and not r.get("disabled", False):
                    if "0.0.0.0/0" in r.get("sourceRanges", []):
                        for allowed in r.get("allowed", []):
                            ports = allowed.get("ports", [])
                            if "22" in ports or "ALL" in ports or not ports:
                                open_ssh.append(f"Firewall Rule: '{r.get('name')}' (VPC: {r.get('network', '').split('/')[-1]})")

        if open_ssh:
            status = Status.FAIL
            details = f"Found {len(open_ssh)} firewall rule(s) allowing unrestricted 0.0.0.0/0 ingress on SSH (port 22)."
        else:
            status = Status.PASS
            details = "No firewall rules permit unrestricted 0.0.0.0/0 SSH ingress."

        return CheckResult(
            rule_id="GCP-3.1", section=section, title=title, severity=Severity.CRITICAL, status=status,
            rationale=rationale, remediation=remediation, affected_resources=open_ssh, details=details
        )


class GCPCheckFirewallRDP:
    """GCP-3.2: Ensure no VPC Firewall rules allow unrestricted 0.0.0.0/0 ingress to RDP (3389)."""
    def execute(self) -> CheckResult:
        rationale = "Remote Desktop Protocol exposed to the internet is heavily targeted for ransomware deployment."
        remediation = "Restrict RDP ingress rules or mandate VPN / IAP desktop access."
        section = "3. Networking & Perimeter Security"
        title = "Ensure no VPC Firewall rules allow unrestricted 0.0.0.0/0 ingress to RDP (3389)"

        ok, rules = run_gcloud_json("gcloud compute firewall-rules list --format=json")
        if not ok:
            return _error_result("GCP-3.2", section, title, Severity.CRITICAL, rationale, remediation, rules)

        open_rdp = []
        if rules:
            for r in rules:
                if r.get("direction") == "INGRESS" and not r.get("disabled", False):
                    if "0.0.0.0/0" in r.get("sourceRanges", []):
                        for allowed in r.get("allowed", []):
                            ports = allowed.get("ports", [])
                            if "3389" in ports or "ALL" in ports:
                                open_rdp.append(f"Firewall Rule: '{r.get('name')}' (VPC: {r.get('network', '').split('/')[-1]})")

        if open_rdp:
            status = Status.FAIL
            details = f"Found {len(open_rdp)} firewall rule(s) allowing unrestricted 0.0.0.0/0 ingress on RDP (port 3389)."
        else:
            status = Status.PASS
            details = "No firewall rules permit unrestricted 0.0.0.0/0 RDP ingress."

        return CheckResult(
            rule_id="GCP-3.2", section=section, title=title, severity=Severity.CRITICAL, status=status,
            rationale=rationale, remediation=remediation, affected_resources=open_rdp, details=details
        )


class GCPCheckPublicBuckets:
    """GCP-4.1: Ensure Cloud Storage Buckets do not allow public allUsers or allAuthenticatedUsers read/write."""
    def execute(self) -> CheckResult:
        rationale = "Public GCS buckets expose proprietary source code, credentials, and customer PII to unauthorized internet scraping."
        remediation = "gcloud storage buckets remove-iam-policy-binding gs://BUCKET --member=allUsers --role=ROLE"
        section = "4. Storage & Storage Buckets"
        title = "Ensure Cloud Storage Buckets do not allow public allUsers or allAuthenticatedUsers read/write"

        ok, buckets = run_gcloud_json("gcloud storage buckets list --format=json")
        if not ok:
            return _error_result("GCP-4.1", section, title, Severity.CRITICAL, rationale, remediation, buckets)

        public_buckets = []
        if buckets:
            for b in buckets:
                name = b.get("name") or b.get("id")
                iam_ok, iam = run_gcloud_json(f"gcloud storage buckets get-iam-policy gs://{name} --format=json")
                if not iam_ok:
                    return _error_result("GCP-4.1", section, title, Severity.CRITICAL, rationale, remediation, iam)
                if iam and "bindings" in iam:
                    for binding in iam["bindings"]:
                        members = binding.get("members", [])
                        if any(m in ["allUsers", "allAuthenticatedUsers"] for m in members):
                            public_buckets.append(f"gs://{name} (Role: {binding.get('role')})")

        if public_buckets:
            status = Status.FAIL
            details = f"Found {len(public_buckets)} publicly exposed Google Cloud Storage bucket(s)."
        else:
            status = Status.PASS
            details = "All scanned Cloud Storage buckets are strictly private."

        return CheckResult(
            rule_id="GCP-4.1", section=section, title=title, severity=Severity.CRITICAL, status=status,
            rationale=rationale, remediation=remediation, affected_resources=public_buckets, details=details
        )


class GCPCheckCloudSQLPublicIP:
    """GCP-5.1: Ensure Cloud SQL Instances do not have public IPv4 addresses assigned."""
    def execute(self) -> CheckResult:
        rationale = "Direct public IP assignments to databases increase attack surface for SQL injection and brute-force attempts."
        remediation = "Disable IPv4 public network assignment and configure Private IP (VPC Peering)."
        section = "5. Databases & Cloud SQL"
        title = "Ensure Cloud SQL Instances do not have public IPv4 addresses assigned"

        ok, instances = run_gcloud_json("gcloud sql instances list --format=json")
        if not ok:
            return _error_result("GCP-5.1", section, title, Severity.HIGH, rationale, remediation, instances)

        public_dbs = []
        if instances:
            for db in instances:
                name = db.get("name")
                ip_config = db.get("settings", {}).get("ipConfiguration", {})
                if ip_config.get("ipv4Enabled", False):
                    ip_list = [ip["ipAddress"] for ip in db.get("ipAddresses", []) if ip.get("type") == "PRIMARY"]
                    public_dbs.append(f"Cloud SQL DB: '{name}' (Public IPv4: {', '.join(ip_list)})")

        if public_dbs:
            status = Status.FAIL
            details = f"Found {len(public_dbs)} Cloud SQL instance(s) with public IPv4 enabled."
        else:
            status = Status.PASS
            details = "All Cloud SQL instances are private (no public IPv4 assigned)."

        return CheckResult(
            rule_id="GCP-5.1", section=section, title=title, severity=Severity.HIGH, status=status,
            rationale=rationale, remediation=remediation, affected_resources=public_dbs, details=details
        )
