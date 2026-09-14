import os
from typing import Dict, Any

STATUS_ICON = {
    "PASS": "✅ PASS",
    "FAIL": "❌ FAIL",
    "WARNING": "⚠️ WARNING",
    "MANUAL_CHECK": "🔍 MANUAL REVIEW",
    "ERROR": "💥 ERROR",
}


class DocReporter:
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown(self, summary: Dict[str, Any], filename: str = "cis_compliance_report.md") -> str:
        filepath = os.path.join(self.output_dir, filename)
        
        md_content = f"""# 🛡️ CIS Unified Cloud & Workspace Compliance Audit Report

**Date:** {summary.get('timestamp', 'N/A')}  
**Overall Compliance Score:** `{summary['score']}%`  
**Duration:** `{summary['duration']} seconds`  

---

## 📊 Executive Summary Metrics

| Metric | Count | Status |
| :--- | :--- | :--- |
| **Total Rules Evaluated** | `{summary['total_checks']}` | — |
| **Passed Checks** | `{summary['passed']}` | ✅ Compliant |
| **Failed Checks** | `{summary['failed']}` | ❌ Non-Compliant |
| **Warnings** | `{summary['warnings']}` | ⚠️ Attention Required |
| **Manual Review Required** | `{summary.get('manual', 0)}` | 🔍 Not Automated |
| **Errors** | `{summary.get('errors', 0)}` | 💥 Could Not Verify |

---

## 📋 Itemized Audit Results & Remediation Guide

"""
        for r in summary["results"]:
            d = r.to_dict()
            status_icon = STATUS_ICON.get(d['status'], d['status'])
            
            md_content += f"""### [{d['rule_id']}] {d['title']}

* **Section:** {d['section']}
* **Severity:** `{d['severity']}`
* **Status:** **{status_icon}**

**Audit Findings:**
{d['details']}

"""
            if d.get("affected_resources"):
                md_content += "**Affected Resources:**\n"
                for res in d["affected_resources"]:
                    md_content += f"- `{res}`\n"
                md_content += "\n"

            md_content += f"""**Rationale:**
{d['rationale']}

**Remediation Steps:**
```
{d['remediation']}
```

---
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        return filepath
