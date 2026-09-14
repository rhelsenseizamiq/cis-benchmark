import subprocess
import json
from ..core.models import CheckResult, Status, Severity


def run_az_json(command: str):
    """Runs an Azure CLI (az) command and returns (ok, data).

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
            return False, f"Failed to parse Azure CLI JSON output: {e}"
    except subprocess.TimeoutExpired:
        return False, "Azure CLI command timed out after 15s"
    except Exception as e:
        return False, str(e)


class AzureCheckMFAAdmins:
    """AZURE-1.1: Ensure MFA is enabled for all privileged Azure Active Directory accounts."""
    def execute(self) -> CheckResult:
        # NOTE: verifying MFA enforcement requires reading Conditional Access
        # policies from Microsoft Graph (policies/conditionalAccessPolicies),
        # which needs Graph API permissions this CLI does not request or
        # assume. `az account show` only confirms an authenticated session —
        # it says nothing about MFA policy, so this check is reported as
        # MANUAL_CHECK rather than a fabricated PASS.
        return CheckResult(
            rule_id="AZURE-1.1",
            section="1. Azure Active Directory (Entra ID)",
            title="Ensure MFA is enabled for all privileged Azure Active Directory accounts",
            severity=Severity.CRITICAL,
            status=Status.MANUAL_CHECK,
            rationale="Privileged Azure AD accounts hold administrative domain rights. Requiring MFA protects against credential theft.",
            remediation="Azure Portal -> Entra ID -> Conditional Access -> verify MFA is enforced for privileged admin roles.",
            affected_resources=[],
            details="Automated verification not implemented: this requires querying Conditional Access policies via Microsoft Graph, which this tool does not yet call. Verify manually in the Entra ID Conditional Access blade."
        )


class AzureCheckStoragePublicBlob:
    """AZURE-2.1: Ensure Storage Account Public Blob Access is disabled."""
    def execute(self) -> CheckResult:
        rationale = "Disabling public blob access at the storage account level prevents accidental public file exposure."
        remediation = "az storage account update --name ACCOUNT --resource-group RG --allow-blob-public-access false"

        ok, storage_accounts = run_az_json("az storage account list --output json")
        if not ok:
            return CheckResult(
                rule_id="AZURE-2.1", section="2. Storage Accounts",
                title="Ensure Storage Account Public Blob Access is disabled",
                severity=Severity.HIGH, status=Status.ERROR, rationale=rationale,
                remediation="Investigate Azure CLI authentication/configuration, then re-run the audit.",
                affected_resources=[], details=f"Could not verify — Azure CLI call failed: {storage_accounts}"
            )

        public_accs = []
        if storage_accounts:
            for sa in storage_accounts:
                name = sa.get("name")
                if sa.get("allowBlobPublicAccess", True) is True:
                    public_accs.append(f"Storage Account: '{name}'")

        if public_accs:
            status = Status.FAIL
            details = f"Found {len(public_accs)} Azure Storage Account(s) allowing public blob access."
        else:
            status = Status.PASS
            details = "All Azure Storage Accounts strictly disable public blob access."

        return CheckResult(
            rule_id="AZURE-2.1",
            section="2. Storage Accounts",
            title="Ensure Storage Account Public Blob Access is disabled",
            severity=Severity.HIGH,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=public_accs,
            details=details
        )


class AzureCheckNSGUnrestrictedSSH:
    """AZURE-3.1: Ensure Network Security Groups (NSG) restrict 0.0.0.0/0 ingress on SSH (22)."""
    def execute(self) -> CheckResult:
        rationale = "Unrestricted inbound SSH access exposes Azure Virtual Machines to unauthorized network infiltration."
        remediation = "Azure Portal -> Network Security Groups -> Inbound rules -> Restrict source IP address prefix."

        ok, nsgs = run_az_json("az network nsg list --output json")
        if not ok:
            return CheckResult(
                rule_id="AZURE-3.1", section="3. Networking & Network Security Groups",
                title="Ensure Network Security Groups (NSG) restrict 0.0.0.0/0 ingress on SSH (22)",
                severity=Severity.CRITICAL, status=Status.ERROR, rationale=rationale,
                remediation="Investigate Azure CLI authentication/configuration, then re-run the audit.",
                affected_resources=[], details=f"Could not verify — Azure CLI call failed: {nsgs}"
            )

        open_nsgs = []
        if nsgs:
            for nsg in nsgs:
                nsg_name = nsg.get("name")
                for rule in nsg.get("securityRules", []):
                    if rule.get("access") == "Allow" and rule.get("direction") == "Inbound":
                        src = rule.get("sourceAddressPrefix")
                        dst_port = rule.get("destinationPortRange")
                        if src in ["*", "0.0.0.0/0", "Internet"] and dst_port in ["22", "*"]:
                            open_nsgs.append(f"NSG Rule: '{rule.get('name')}' in NSG '{nsg_name}'")

        if open_nsgs:
            status = Status.FAIL
            details = f"Found {len(open_nsgs)} NSG rule(s) allowing unrestricted 0.0.0.0/0 ingress on SSH."
        else:
            status = Status.PASS
            details = "No Network Security Group rules permit unrestricted SSH ingress."

        return CheckResult(
            rule_id="AZURE-3.1",
            section="3. Networking & Network Security Groups",
            title="Ensure Network Security Groups (NSG) restrict 0.0.0.0/0 ingress on SSH (22)",
            severity=Severity.CRITICAL,
            status=status,
            rationale=rationale,
            remediation=remediation,
            affected_resources=open_nsgs,
            details=details
        )
