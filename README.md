# 🛡️ CIS Unified Multi-Cloud Compliance & Audit CLI

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

A high-performance, professional terminal CLI security auditing tool for **AWS**, **Microsoft Azure**, **Google Cloud Platform (GCP)**, and **Google Workspace**.

---

## ⚡ Features & Capabilities

- 🚀 **Ultra-Fast Parallel Execution**: Evaluates 18+ multi-cloud security rules in sub-second execution (< 1 second).
- 🎨 **Rich Terminal Interface**: Professional ASCII header banner, live progress bars, status badges, and executive score cards.
- ☁️ **Multi-Cloud Support**:
  - 🟠 **AWS**: CIS AWS Foundations Benchmark v1.5
  - 🔵 **Azure**: CIS Microsoft Azure Foundations Benchmark v2.0
  - 🟢 **GCP**: CIS Google Cloud Platform Foundations Benchmark v2.0
  - 🔴 **Google Workspace**: CIS Google Workspace Benchmark v1.4
- 📊 **Multi-Format Export**: Generates **Interactive HTML Dashboard**, **Excel Workbook (.xlsx)**, and **Markdown (.md)** reports.

---

## 🔑 Required Credentials & Cloud Access

Before scanning, ensure your environment or CLI is authenticated with read-only access for each target provider:

| Cloud Provider | Authentication / Command | Minimum Required Role / Policy |
| :--- | :--- | :--- |
| 🟢 **Google Cloud (GCP)** | `gcloud auth login` or `GOOGLE_APPLICATION_CREDENTIALS` | `Security Reviewer` (`roles/iam.securityReviewer`) or `Viewer` |
| 🟠 **AWS** | `aws configure` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `SecurityAudit` or `ReadOnlyAccess` managed policy |
| 🔵 **Microsoft Azure** | `az login` or `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` | `Reader` role on Target Subscription |
| 🔴 **Google Workspace** | Target domain (e.g. `company.com`) + Workspace Admin auth | Admin SDK API + Workspace Admin permissions |

---

## 📦 Installation

This is a CLI-only tool — there is no GUI, and none is planned. Install it as a regular Python package into a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable install + pytest for running tests
```

That gives you a real `cis` command on your `PATH` (via `pyproject.toml`'s `console_scripts` entry point) — it works from any directory, not just the repo root. To build a distributable wheel instead: `pip install build && python -m build`.

---

## 💻 CLI Usage

### Run All Clouds
```bash
cis --cloud all --domain yourdomain.com
```

### Audit Specific Cloud Provider
```bash
# Audit AWS only
cis --cloud aws

# Audit Azure only
cis --cloud azure

# Audit GCP only
cis --cloud gcp

# Audit Google Workspace only
cis --cloud workspace --domain example.com
```

### Custom Threads & Output Directory
```bash
cis --cloud all --workers 20 --output ./custom_reports
```

### Plain output (cron / CI / log capture)
```bash
cis --cloud all --plain
```
Drops the Rich banner/progress bar/live table in favor of simple line-per-rule output — same engine, same reports, just script-friendly stdout. There is one CLI entrypoint (`cis_benchmark/cli.py`); `--plain` selects the output mode, so there's no separate binary to keep in sync.

### Version
```bash
cis --version
```

---

## 📁 Project Architecture

```
CIS_Benchmark/
├── pyproject.toml               # Build config, dependencies, `cis` entry point
├── cis_benchmark/                # The installable package
│   ├── __init__.py              # __version__ (read from installed package metadata)
│   ├── cli.py                   # CLI entrypoint (Rich UI + --plain mode)
│   ├── core/
│   │   ├── engine.py            # Concurrent multi-threaded execution engine
│   │   ├── base_check.py        # Abstract Check interface
│   │   ├── models.py            # Dataclasses & Status Enums
│   │   ├── config.py            # Settings resolution (CWD override -> bundled defaults)
│   │   └── default_settings.json # Defaults bundled inside the installed package
│   ├── modules/                  # Cloud Provider Audit Modules
│   │   ├── aws_checks.py        # AWS IAM, S3, EC2, CloudTrail
│   │   ├── azure_checks.py      # Azure AD, Storage, NSGs
│   │   ├── gcp_checks.py        # GCP IAM, Storage, VPC, Cloud SQL
│   │   └── workspace_checks.py  # Workspace 2SV, SPF/DMARC, OAuth
│   └── reporters/                # Report Generators
│       ├── html_reporter.py     # Dark-mode HTML Dashboard
│       ├── excel_reporter.py    # Formatted XLSX Workbook
│       └── doc_reporter.py      # Markdown Report
├── config/settings.json         # OPTIONAL project-local override (see below)
├── benchmarks/                   # Reference-only JSON Benchmark Specifications
├── tests/                        # pytest suite
└── output/                       # Generated Reports (default)
```

> **Settings resolution order:** `core/config.py::load_settings()` checks, in
> order: (1) an explicit path (tests only), (2) a `config/settings.json` in
> your **current working directory** if present — this repo ships one as a
> ready-to-edit example, (3) the defaults bundled inside the installed
> package (`cis_benchmark/core/default_settings.json`), (4) a hardcoded
> fallback dict as an absolute last resort. This is what makes a real,
> non-editable `pip install` work correctly even after the source checkout
> is gone — the earlier design (a single `config/settings.json` living
> outside the package) would have silently broken in that case.
>
> **`benchmarks/*.json`** is reference documentation mirroring the rules
> actually implemented in `cis_benchmark/modules/*_checks.py` — it is **not**
> loaded at runtime, so the check logic in code is always the source of
> truth.

---

## 📋 Result Statuses

| Status | Meaning |
| :--- | :--- |
| ✅ `PASS` | The control was verified against the live environment and is compliant. |
| ❌ `FAIL` | The control was verified and is **not** compliant. |
| ⚠️ `WARNING` | The check ran but found a soft issue (e.g. a weak-but-present DMARC policy). |
| 🔍 `MANUAL_CHECK` | This rule is not yet automated (e.g. it needs Admin SDK / Microsoft Graph API access this tool doesn't call) — verify it manually. It never reports PASS or FAIL. |
| 💥 `ERROR` | The underlying CLI call itself failed (auth, network, bad flag) — the control's real state is unknown, and this must not be read as compliant. |

---

## 📄 License

Licensed under the [Apache License 2.0](LICENSE).
